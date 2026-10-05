from __future__ import annotations

import io
import json
import os
import stat
import tarfile
import threading
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from zenless.agent_gateway import AgentGateway
from zenless.browser_bridge import BridgeError
from zenless.core import CoreError, ZenlessCore
from zenless.event_bus import EventBus
from zenless.local_ai import LocalAIService
from zenless.managed_browser import PROVIDERS, ManagedBrowserController, _Command
from zenless.models import TaskOptions
from zenless.webview2_browser import WebView2BrowserController
from zenless.qa_breaker import PROFILES, QABreaker
from zenless.store import SQLiteStore
from zenless.studio_data import SourceSnapshot, export_sources
from zenless.tool_registry import ToolRegistry
from zenless.toolchain import ToolchainError, ToolchainManager
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
    failed = ToolRegistry(tmp_path, tmp_path).descriptors()[0]
    assert failed['reason'] == 'network unavailable'
    assert failed['status'] == 'FAILED'


def test_toolchain_rejects_archive_links(tmp_path):
    target = tmp_path / 'extract'
    target.mkdir()

    zip_path = tmp_path / 'unsafe.zip'
    with zipfile.ZipFile(zip_path, 'w') as bundle:
        info = zipfile.ZipInfo('link')
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        bundle.writestr(info, '../outside')
    with zipfile.ZipFile(zip_path) as bundle:
        with pytest.raises(ToolchainError, match='symbolic links'):
            ToolchainManager._safe_zip(bundle, target)

    tar_path = tmp_path / 'unsafe.tar.gz'
    with tarfile.open(tar_path, 'w:gz') as bundle:
        info = tarfile.TarInfo('link')
        info.type = tarfile.SYMTYPE
        info.linkname = '../outside'
        bundle.addfile(info)
    with tarfile.open(tar_path, 'r:gz') as bundle:
        with pytest.raises(ToolchainError, match='links and device'):
            ToolchainManager._safe_tar(bundle, target)


def test_toolchain_directory_swap_restores_previous_version_on_failure(tmp_path):
    archive = tmp_path / 'tool.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('new.txt', 'new')
    target = tmp_path / 'tool'
    target.mkdir()
    (target / 'old.txt').write_text('old', encoding='utf-8')
    manager = object.__new__(ToolchainManager)
    real_replace = os.replace

    def fail_new_swap(source, destination):
        source_path, destination_path = Path(source), Path(destination)
        if source_path.name == 'tool.new' and destination_path == target:
            raise OSError('simulated replacement failure')
        return real_replace(source, destination)

    with patch('zenless.toolchain.os.replace', side_effect=fail_new_swap):
        with pytest.raises(OSError, match='simulated replacement failure'):
            manager._extract_atomic(archive, target, 'zip', False)

    assert (target / 'old.txt').read_text(encoding='utf-8') == 'old'
    assert not target.with_name('tool.new').exists()
    assert not target.with_name('tool.old').exists()


def test_legacy_unverifiable_model_fields_are_not_restored():
    current = {
        'chatgpt': {'model': 'auto'},
        'deepseek': {'model': 'auto'},
        'gemini': {'model': 'auto'},
        'hunyuan': {'version': 'auto'},
        'smartRouting': True,
    }
    merged = ZenlessCore._merge_models(
        current,
        {
            'chatgpt': {'model': 'chosen', 'reasoning': False},
            'hunyuan': {'version': 'new', 'quality': 'high'},
        },
    )
    assert merged['chatgpt'] == {'model': 'chosen'}
    assert merged['hunyuan'] == {'version': 'new'}
    assert 'reasoning' not in merged['chatgpt']
    assert 'quality' not in merged['hunyuan']


def test_gateway_rejects_provider_model_mismatch():
    transport = Mock()
    transport.request.return_value = {'status': 'ok', 'selected': 'different'}
    gateway = AgentGateway(
        managed=transport,
        embedded=transport,
        selected_model=lambda _provider: 'Expected Model',
    )
    with pytest.raises(BridgeError, match='provider reported different'):
        gateway._apply_selected_model('webview2', 'chatgpt', 'job')


def test_system_messages_remain_notices(tmp_path):
    core = ZenlessCore.__new__(ZenlessCore)
    core.store = SQLiteStore(tmp_path / 'state.db')
    core.store.create_task('job', 'test', TaskOptions())
    core.store.append_message('job', 'Recovery', 'system', 'Recovered checkpoint')
    messages = core.messages('job')
    assert len(messages) == 1
    assert messages[0]['role'] == 'system'
    assert messages[0]['content'] == 'Recovered checkpoint'


def test_set_model_requires_exact_provider_confirmation_and_invalidates_cache():
    core = ZenlessCore.__new__(ZenlessCore)
    core.bridge = Mock()
    core.bridge.wait_for_provider.return_value = True
    core.store = Mock()
    core.events = Mock()
    core._settings_lock = threading.RLock()
    core._model_selection_lock = threading.Lock()
    core._model_cache = (1.0, {'stale': True})
    settings = {
        'models': {
            'chatgpt': {'model': 'auto'},
            'deepseek': {'model': 'auto'},
            'gemini': {'model': 'auto'},
            'hunyuan': {'version': 'auto'},
            'smartRouting': True,
        }
    }
    core.settings = lambda: json.loads(json.dumps(settings))

    core.bridge.request.return_value = {'status': 'ok', 'selected': 'different'}
    with pytest.raises(CoreError, match='did not confirm'):
        core.set_model('chatgpt', 'GPT Test')
    core.store.set_setting.assert_not_called()

    core.bridge.request.return_value = {'status': 'ok', 'selected': 'GPT Test'}
    assert core.set_model('chatgpt', 'GPT Test')
    saved = core.store.set_setting.call_args.args[1]
    assert saved['models']['chatgpt']['model'] == 'GPT Test'
    assert core._model_cache is None


def test_manual_play_button_always_uses_standalone_studio_test():
    root = Path(__file__).resolve().parents[1]
    for relative in (
        ('frontend', 'src', 'features', 'test', 'TestPage.tsx'),
        ('frontend', 'src', 'features', 'studio', 'StudioPage.tsx'),
    ):
        source = (root.joinpath(*relative)).read_text(encoding='utf-8')
        assert 'const result = await getApi().startStudioTest();' in source
        assert 'startTest(currentJobId)' not in source


def test_stop_test_falls_back_to_orchestrator_cancel():
    core = ZenlessCore.__new__(ZenlessCore)
    core.qa = Mock()
    core.qa.stop.return_value = False
    core.orchestrator = Mock()
    core.orchestrator.cancel.return_value = True
    assert core.stop_test('job')
    core.orchestrator.cancel.assert_called_once_with('job')


def test_studio_monitor_defers_inventory_retry_while_work_is_active():
    core = ZenlessCore.__new__(ZenlessCore)
    core._closing = Mock()
    core._closing.is_set.return_value = False
    core._closing.wait.return_value = True
    core._studio_target_id = "studio"
    core._studio_label = "Game"
    core._studio_tree_error = "inventory unavailable"
    core._last_studio_inventory = 0.0
    core.studio = Mock(running=True)
    core.studio.list_studios.return_value = [Mock(studio_id="studio", label="Game", raw={})]
    core.orchestrator = Mock(current_task_id="active-job")
    core.qa = Mock()
    core.qa.running.return_value = True
    core.connections = Mock(return_value={"studio": "READY"})
    core.refresh_studio = Mock()
    core._set_boot = Mock()

    core._monitor_studio()

    core.refresh_studio.assert_not_called()


def test_studio_refresh_preserves_reference_flags_only_for_same_game():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'zenless' / 'core.py').read_text(encoding='utf-8')
    assert 'same_target = target.studio_id == self._studio_target_id' in source
    assert 'retained_references = {' in source
    assert 'if not same_target:' in source
    assert 'node.update(state)' in source


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
    controller = ManagedBrowserController(data_root=tmp_path)
    controller._login_provider = "chatgpt"
    with patch.object(controller, "_ensure_context") as context:
        assert controller._handle(_Command("health", "deepseek"))["busy"]
        with pytest.raises(BridgeError, match="LOGIN_IN_PROGRESS"):
            controller._handle(_Command("request", "chatgpt"))
        with pytest.raises(BridgeError, match="LOGIN_IN_PROGRESS"):
            controller._handle(_Command("login", "deepseek"))
        context.assert_not_called()

def test_managed_request_failure_clears_working_state(tmp_path):
    controller = ManagedBrowserController(data_root=tmp_path)
    command = _Command("request", "chatgpt", {"provider_action": "send_prompt"})
    controller._commands.put(command)
    controller._commands.put(_Command("stop"))

    def fail(_command):
        controller._set_state("chatgpt", "Working", "Waiting")
        raise BridgeError("send failed")

    with patch.object(controller, "_handle", side_effect=fail):
        controller._event_loop()

    assert isinstance(command.error, BridgeError)
    assert controller.provider_status()["chatgpt"]["state"] == "Error"


def test_webview2_request_failure_clears_working_state(tmp_path):
    controller = WebView2BrowserController(data_root=tmp_path)
    process = Mock()
    process.poll.return_value = None
    controller._process = process
    with patch.object(controller, "_request", side_effect=BridgeError("selector changed")):
        with pytest.raises(BridgeError, match="selector changed"):
            controller.request("chatgpt", "send_prompt", {"prompt": "x"}, task_id="task", timeout=1)
    state = controller.provider_status()["chatgpt"]
    assert state["state"] == "Error"
    assert "selector changed" in state["detail"]


def test_compacted_messages_do_not_expose_legacy_branding():
    compacted = SQLiteStore._compact_message('x' * (SQLiteStore.MAX_MESSAGE_CHARS + 1000))
    assert '[RUBRA COMPACTED ' in compacted
    assert 'ZENLESS COMPACTED' not in compacted


def test_user_facing_diagnostic_log_uses_rubra_branding():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'zenless' / 'diagnostics.py').read_text(encoding='utf-8')
    assert 'rubra.log' in source
    assert 'zenless.log' not in source


def test_frontend_lockfile_keeps_resolved_package_versions_consistent():
    root = Path(__file__).resolve().parents[1]
    lock = json.loads((root / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    package = lock["packages"]["node_modules/is-extglob"]
    assert package["version"] == "2.1.1"
    assert "is-extglob-2.1.1.tgz" in package["resolved"]


def test_development_bridge_accepts_rubra_session_contract():
    root = Path(__file__).resolve().parents[1]
    source = (root / "frontend" / "bridge" / "server.ts").read_text(encoding="utf-8")
    assert "process.env.RUBRA_TOKEN || process.env.ZENLESS_TOKEN" in source
    assert "req.headers['x-rubra-token'] === SESSION_TOKEN" in source
    assert "X-Rubra-Token" in source


def test_installer_updates_keep_a_rollback_copy_until_extraction_succeeds():
    root = Path(__file__).resolve().parents[1]
    source = (root / "packaging" / "setup.nsi").read_text(encoding="utf-8")
    update_gate = source.index('StrCmp $0 "Rubra" update_backup install_payload')
    launcher_backup = source.index('Rename "$INSTDIR\\Rubra.exe" "$INSTDIR\\Rubra.exe.__rubra_old"')
    app_backup = source.index('Rename "$INSTDIR\\app" "$INSTDIR\\app.__rubra_old"')
    python_backup = source.index('Rename "$INSTDIR\\runtime\\python" "$INSTDIR\\runtime\\python.__rubra_old"')
    extraction = source.index('File /r "${PACKAGE}/*"')
    cleanup = source.index('Delete "$INSTDIR\\Rubra.exe.__rubra_old"', extraction)
    rollback = source.index('install_failed:', extraction)
    assert update_gate < launcher_backup < app_backup < python_backup < extraction < cleanup
    assert rollback > extraction
    assert 'Rename "$INSTDIR\\Rubra.exe.__rubra_old" "$INSTDIR\\Rubra.exe"' in source[rollback:]
    assert 'Rename "$INSTDIR\\app.__rubra_old" "$INSTDIR\\app"' in source[rollback:]
    assert 'Rename "$INSTDIR\\runtime\\python.__rubra_old" "$INSTDIR\\runtime\\python"' in source[rollback:]
    assert 'fresh_install_failed:' in source[rollback:]
    assert 'recovery_failed:' in source[rollback:]
    assert 'RMDir /r "$INSTDIR\\runtime"' not in source[:extraction]


def test_chat_attachment_limit_matches_backend_contract():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'frontend' / 'src' / 'features' / 'chat' / 'ChatPage.tsx').read_text(encoding='utf-8')
    assert 'Array.from(files).slice(0, 5)' in source
    assert 'combined.slice(0, 5)' in source


def test_model_discovery_does_not_treat_menu_buttons_as_options():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'zenless' / 'provider_auth.py').read_text(encoding='utf-8')
    assert "[data-model]:not(button)" in source
    assert "querySelectorAll('button[data-model]')" not in source
    assert 'open_model_menu_script' in source


def test_uninstaller_checks_open_app_before_removing_user_state():
    root = Path(__file__).resolve().parents[1]
    source = (root / "packaging" / "setup.nsi").read_text(encoding="utf-8")
    uninstall = source[source.index('Section "Uninstall"'):]
    launcher_check = uninstall.index('Delete "$INSTDIR\\Rubra.exe"')
    close_guard = uninstall.index('IfErrors uninstall_close_required')
    data_cleanup = uninstall.index('RMDir /r "$INSTDIR\\data"')
    assert launcher_check < close_guard < data_cleanup
    assert 'uninstall_close_required:' in uninstall
    assert 'Delete "$INSTDIR\\Rubra.exe.__rubra_old"' in uninstall
    assert 'RMDir /r "$INSTDIR\\app.__rubra_old"' in uninstall
    for name in ("NOTICE.md", "README.md", "RUBRA.md", "NSIS-LICENSE.txt"):
        assert f'Delete "$INSTDIR\\{name}"' in uninstall

