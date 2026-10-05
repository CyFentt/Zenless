from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest

from zenless.studio_mcp import MCPError, StudioMCPClient, validate_json_schema


@pytest.mark.parametrize(('value', 'schema', 'valid'), [
    (1, {'oneOf': [{'type': 'integer'}, {'type': 'number'}]}, False),
    ('x', {'oneOf': [{'type': 'integer'}, {'type': 'string'}]}, True),
    ('a', {'anyOf': [{'type': 'string'}], 'minLength': 2}, False),
    (3, {'allOf': [{'minimum': 2}, {'maximum': 4}]}, True),
    (5, {'allOf': [{'minimum': 2}, {'maximum': 4}]}, False),
    (None, {'type': ['string', 'null']}, True),
    (2, {'type': ['string', 'null']}, False),
    ([], {'type': 'array', 'minItems': 1}, False),
    ([1, 2], {'type': 'array', 'maxItems': 1}, False),
    (True, {'type': 'integer'}, False),
    ({}, {'type': 'object', 'required': ['path']}, False),
    ({'unknown': 1}, {'type': 'object', 'additionalProperties': False}, False),
    (['x'], {'type': 'array', 'items': {'type': 'integer'}}, False),
])
def test_schema_boundaries(value, schema, valid):
    assert (not validate_json_schema(value, schema)) is valid


def start_child(script: str) -> StudioMCPClient:
    client = StudioMCPClient(Path(sys.executable))
    client.process = subprocess.Popen(
        [sys.executable, '-u', '-c', script], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    client._reader = threading.Thread(target=client._read_stdout, daemon=True)
    client._reader.start()
    return client


def test_real_child_exit_releases_pending_request():
    client = start_child('import sys; sys.stdin.readline(); sys.exit(0)')
    try:
        with pytest.raises(MCPError, match='closed the connection'):
            client.request('test', {}, timeout=2)
        assert not client._pending
    finally:
        client.close()


def test_real_transport_ignores_invalid_lines_and_boolean_response_ids():
    client = start_child('''import sys,json
r=json.loads(sys.stdin.readline())
for message in ['invalid', '[]', json.dumps({'id':True,'result':{'wrong':True}}), json.dumps({'id':r['id'],'result':{'ok':True}})]:
 print(message,flush=True)
sys.stdin.read()
''')
    try:
        assert client.request('test', {}, timeout=2) == {'ok': True}
        assert not client._pending
    finally:
        client.close()


def test_request_timeout_does_not_poison_next_response():
    client = start_child('''import sys,json,time
first=json.loads(sys.stdin.readline());time.sleep(.15)
print(json.dumps({'id':first['id'],'result':{'old':True}}),flush=True)
second=json.loads(sys.stdin.readline())
print(json.dumps({'id':second['id'],'result':{'new':True}}),flush=True)
sys.stdin.read()
''')
    try:
        with pytest.raises(MCPError, match='exceeded'):
            client.request('first', {}, timeout=.02)
        assert client.request('second', {}, timeout=2) == {'new': True}
        assert not client._pending
    finally:
        client.close()


def test_broken_pipe_is_controlled_and_clears_pending():
    client = StudioMCPClient(Path('unused'))
    client.process = Mock()
    client.process.poll.return_value = None
    client.process.stdin.write.side_effect = BrokenPipeError('closed')
    with pytest.raises(MCPError, match='could not send'):
        client.request('test', {}, timeout=1)
    assert not client._pending


def test_close_kills_unresponsive_owned_child_without_closing_active_reader():
    client = StudioMCPClient(Path('unused'))
    process = Mock()
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired('child', 3), subprocess.TimeoutExpired('child', 2), 0]
    reader = Mock()
    reader.is_alive.return_value = True
    client.process, client._reader = process, reader
    client.tools["stale"] = Mock()
    client.close()
    process.kill.assert_called_once()
    process.stdout.close.assert_not_called()
    assert client.process is None
    assert client.tools == {}


def test_stream_failure_releases_waiters():
    import queue

    client = StudioMCPClient(Path('unused'))
    client.process = Mock()
    client.process.stdout = Mock()
    client.process.stdout.__iter__ = Mock(side_effect=OSError('stream failed'))
    pending = queue.Queue()
    client._pending[1] = pending
    client._read_stdout()
    assert 'closed the connection' in pending.get_nowait()['error']['message']


def test_real_transport_matches_out_of_order_concurrent_responses():
    from concurrent.futures import ThreadPoolExecutor

    client = start_child('''import sys,json
requests=[json.loads(sys.stdin.readline()) for _ in range(32)]
for r in reversed(requests):
 print(json.dumps({'id':r['id'],'result':r['params']}),flush=True)
sys.stdin.read()
''')
    try:
        with ThreadPoolExecutor(max_workers=32) as pool:
            results = list(pool.map(lambda n: client.request('echo', {'value': n}, timeout=5), range(32)))
        assert results == [{'value': n} for n in range(32)]
        assert not client._pending
    finally:
        client.close()
