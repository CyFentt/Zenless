from __future__ import annotations

import io
import json
import threading
from unittest.mock import Mock, patch

import pytest

from zenless.agent_gateway import AgentGateway
from zenless.browser_bridge import BridgeError
from zenless.event_bus import EventBus
from zenless.local_ai import LocalAIService
from zenless.managed_browser import PROVIDERS
from zenless.models import TaskOptions
from zenless.qa_breaker import PROFILES, QABreaker
from zenless.store import SQLiteStore
from zenless.studio_data import SourceSnapshot, export_sources
from zenless.tool_registry import ToolRegistry
from zenless.toolchain import ToolchainManager
from zenless.webview_host import WebViewHost


def test_login_closing_authenticated_window_keeps_verified_session(tmp_path):
    host = WebViewHost(profile_root=tmp_path, provider_specs=PROVIDERS, source=io.BytesIO(), target=io.BytesIO())
    window = Mock()
    window.get_current_url.return_value = 'https://chatgpt.com/'
    host._windows['chatgpt'] = window
    def verify(*_):
        host._dismissed['chatgpt'].set()
        return {'authenticated': True, 'ready': False, 'composer': False}
    with patch.object(host, '_composer_state', side_effect=verify), patch.object(host._stop, 'wait', return_value=False):
        result = host._handle({'action': 'login', 'provider': 'chatgpt'})
    assert result['authenticated'] and result['state'] == 'ready'
    window.hide.assert_called_once()
    window.destroy.assert_not_called()


def test_login_closing_guest_does_not_report_authenticated(tmp_path):
    host = WebViewHost(profile_root=tmp_path, provider_specs=PROVIDERS, source=io.BytesIO(), target=io.BytesIO())
    window = Mock()
    host._windows['chatgpt'] = window
    def verify(*_):
        host._dismissed['chatgpt'].set()
        return {'authenticated': False, 'composer': True}
    with patch.object(host, '_composer_state', side_effect=verify), patch.object(host._stop, 'wait', return_value=False):
        with pytest.raises(RuntimeError, match='LOGIN_CANCELLED'):
            host._handle({'action': 'login', 'provider': 'chatgpt'})
    assert host._windows['chatgpt'] is window


def test_navigation_does_not_discard_existing_provider_window(tmp_path):
    host = WebViewHost(profile_root=tmp_path, provider_specs=PROVIDERS, source=io.BytesIO(), target=io.BytesIO())
    window = Mock()
    window.evaluate_js.side_effect = RuntimeError('navigation in progress')
    host._windows['chatgpt'] = window
    assert host._ensure_window('chatgpt') is window


def test_model_is_reapplied_to_selected_transport_before_each_prompt():
    transport = Mock()
    transport.request.return_value = {'status': 'ok', 'selected': 'GPT Test'}
    transport.send_prompt.return_value = 'answer'
    gateway = AgentGateway(managed=Mock(), embedded=transport, selected_model=lambda _: 'GPT Test')
    gateway._routes['chatgpt'] = 'webview2'
    assert gateway.send_prompt('chatgpt', 'one', task_id='task') == 'answer'
    assert gateway.send_prompt('chatgpt', 'two', task_id='task') == 'answer'
    assert transport.request.call_count == 2
    assert transport.request.call_args.args == ('chatgpt', 'select_model', {'model': 'GPT Test'})
    transport.request.return_value = {'status': 'error'}
    with pytest.raises(BridgeError, match='could not be confirmed'):
        gateway.send_prompt('chatgpt', 'three', task_id='task')
    assert transport.send_prompt.call_count == 2
    assert not gateway._can_use_local('chatgpt')


def test_tool_setup_continues_after_failed_critical_and_prioritizes_sources(tmp_path):
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets/toolchain.json').write_text(json.dumps({'artifacts': [
        {'id': 'broken', 'critical': True, 'target': 'runtime/tools/broken'},
        {'id': 'model', 'target': 'runtime/models/model.gguf'},
        {'id': 'working', 'target': 'runtime/tools/working'},
    ], 'sources': [{'id': 'skill', 'target': 'runtime/sources/skill'}]}))
    manager = ToolchainManager(resource_root=tmp_path, portable_root=tmp_path)
    calls = []
    def install(item):
        calls.append(item['id'])
        if item['id'] == 'broken':
            raise RuntimeError('network unavailable')
        return tmp_path
    with patch.object(manager, '_ensure_artifact', side_effect=install), patch.object(manager, '_ensure_source', side_effect=install), patch.object(manager, '_ensure_npm_packages'):
        results = manager.ensure_default()
    assert calls == ['broken', 'working', 'skill', 'model']
    assert [item.state for item in results] == ['failed', 'ready', 'ready', 'ready']
    assert json.loads((tmp_path / 'runtime/toolchain-results.json').read_text())['broken']['detail'] == 'network unavailable'
    assert ToolRegistry(tmp_path, tmp_path).descriptors()[0]['reason'] == 'network unavailable'


def test_manual_test_plan_never_waits_for_an_ai_account(tmp_path):
    store = SQLiteStore(tmp_path / 'state.db')
    store.create_task('manual', 'Play Test', TaskOptions())
    store.update_task('manual', context_json={'manual_test': True})
    qa = QABreaker(store=store, studio=Mock(), bridge=Mock(), events=EventBus())
    with patch.object(qa, '_ai_scenarios', side_effect=AssertionError('must not call AI')):
        for profile in PROFILES.values():
            assert qa._make_plan('manual', profile, [], 1, False).scenarios


def test_local_shutdown_can_interrupt_an_active_completion(tmp_path):
    service = LocalAIService(tmp_path)
    entered, finish = threading.Event(), threading.Event()
    def complete(*args, **kwargs):
        entered.set()
        finish.wait(3)
        return 'done'
    with patch.object(service, '_complete', side_effect=complete):
        worker = threading.Thread(target=service.complete, args=('prompt',))
        worker.start()
        assert entered.wait(1)
        stopped = threading.Event()
        closer = threading.Thread(target=lambda: (service.close(), stopped.set()))
        closer.start()
        try:
            assert stopped.wait(1), 'close must not wait for HTTP inference'
        finally:
            finish.set()
            worker.join(3)
            closer.join(3)


def test_corrupt_export_manifest_does_not_block_new_snapshot(tmp_path):
    (tmp_path / 'rubra-studio.json').write_text('{broken')
    source = {'id': '1', 'path': 'game.ServerScriptService.Script', 'source': 'return 1', 'readError': ''}
    manifest = export_sources(tmp_path, 'studio', SourceSnapshot([source], True, 1))
    assert (tmp_path / manifest['files'][0]).read_text() == 'return 1'
    assert json.loads((tmp_path / 'rubra-studio.json').read_text())['readable'] == 1


def test_background_health_and_requests_do_not_close_active_login(tmp_path):
    from zenless.managed_browser import ManagedBrowserController, _Command
    controller = ManagedBrowserController(data_root=tmp_path)
    controller._login_provider = "chatgpt"
    with patch.object(controller, "_ensure_context") as context:
        assert controller._handle(_Command("health", "deepseek"))["busy"]
        with pytest.raises(BridgeError, match="LOGIN_IN_PROGRESS"):
            controller._handle(_Command("request", "chatgpt"))
        with pytest.raises(BridgeError, match="LOGIN_IN_PROGRESS"):
            controller._handle(_Command("login", "deepseek"))
        context.assert_not_called()
