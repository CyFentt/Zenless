from __future__ import annotations

import asyncio

import pytest
from aiohttp import ClientSession
from test_web_backend import _FakeCore

from zenless.web_bridge import LocalWebBridge


@pytest.fixture
def bridge(tmp_path):
    frontend = tmp_path / 'frontend'
    frontend.mkdir()
    (frontend / 'index.html').write_text('<html>Rubra</html>')
    core = _FakeCore(tmp_path)
    instance = LocalWebBridge(core=core, frontend_root=frontend)
    instance.start()
    yield instance, core
    instance.stop()


@pytest.mark.parametrize(('payload', 'status', 'code'), [
    (b'{broken', 400, 'INVALID_JSON'),
    (b'[]', 400, 'INVALID_JSON_SHAPE'),
    (b'null', 400, 'INVALID_JSON_SHAPE'),
    (b'\xff', 400, 'INVALID_JSON'),
    (b'{"content":"' + b'x' * (2 * 1024 * 1024) + b'"}', 413, 'JSON_TOO_LARGE'),
])
def test_chunked_invalid_requests_are_bounded_and_do_not_dispatch(bridge, payload, status, code):
    instance, core = bridge

    async def run():
        async def chunks():
            for start in range(0, len(payload), 4096):
                yield payload[start:start + 4096]

        async with ClientSession() as session:
            async with session.post(instance.base_url + '/api/chat', data=chunks(), headers={'X-Rubra-Token': instance.token, 'Content-Type': 'application/json'}) as response:
                assert response.status == status
                assert (await response.json())['code'] == code
        assert core.chats == 0

    asyncio.run(run())


def test_idempotency_key_cannot_replay_a_different_task(bridge):
    instance, core = bridge

    async def run():
        async with ClientSession() as session:
            headers = {'X-Rubra-Token': instance.token, 'Idempotency-Key': 'chat-operation-123'}
            async with session.post(instance.base_url + '/api/chat', json={'content': 'a', 'jobId': 'one'}, headers=headers) as response:
                assert response.status == 200
            async with session.post(instance.base_url + '/api/chat', json={'content': 'b', 'jobId': 'two'}, headers=headers) as response:
                assert response.status == 409
                assert (await response.json())['code'] == 'IDEMPOTENCY_CONFLICT'
        assert core.chats == 1

    asyncio.run(run())


@pytest.mark.parametrize('profile', ['STANDARD', 'DEEP'])
def test_optional_json_preserves_chunked_test_profile(bridge, profile):
    import json
    from unittest.mock import Mock

    instance, core = bridge
    core.start_test = Mock(return_value=True)

    async def run():
        async def chunks():
            yield json.dumps({'profile': profile}).encode()

        async with ClientSession() as session:
            async with session.post(instance.base_url + '/api/jobs/job/test', data=chunks(), headers={'X-Rubra-Token': instance.token, 'Content-Type': 'application/json'}) as response:
                assert response.status == 200
        core.start_test.assert_called_once_with('job', profile)

    asyncio.run(run())
