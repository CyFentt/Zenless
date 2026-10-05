from __future__ import annotations

import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen

import pytest

from zenless.agent_gateway import AgentGateway
from zenless.core import CoreError, ZenlessCore, _UnavailableStudio
from zenless.event_bus import EventBus
from zenless.local_ai import LocalAIError, LocalAIService
from zenless.managed_browser import PROVIDERS
from zenless.models import Stage
from zenless.store import SQLiteStore
from zenless.studio_mcp import MCPToolResult, StudioTarget
from zenless.web_bridge import LocalWebBridge
from zenless.webview2_browser import WebView2BrowserController
from zenless.webview_host import WebViewHost


@pytest.fixture
def core(tmp_path):
    value = object.__new__(ZenlessCore)
    value.data_root = tmp_path
    value.store = SQLiteStore(tmp_path / "state.db")
    value.events = EventBus()
    value._closing = threading.Event()
    value._connections = {"studio": "OFF"}
    value._connections_lock = threading.RLock()
    value._studio_lock = threading.RLock()
    value._studio_refresh_lock = threading.Lock()
    value._test_start_lock = threading.Lock()
    value._studio_nodes, value._studio_tree = {}, []
    value._studio_target_id = value._studio_label = value._studio_test_id = ""
    value._set_boot = Mock()
    value._report = Mock()
    value.studio = Mock(running=True)
    value.studio.list_studios.return_value = [StudioTarget("place", "My place", {})]
    value.studio.call_tool.return_value = MCPToolResult(
        "search_game_tree",
        "",
        False,
        (),
        structured_content={
            "instances": [
                {"path": "game.Workspace", "className": "Workspace"},
                {"path": "game.Workspace.Module", "className": "ModuleScript"},
            ]
        },
    )
    value.qa = Mock()
    value.qa.running.return_value = False
    value.qa.start_manual.return_value = True
    value.orchestrator = Mock(current_task_id=None)
    return value


def test_structured_tree_and_real_script_content(core):
    assert core.refresh_studio()
    tree = core.studio_tree()
    assert tree[0]["children"][0]["name"] == "Module"
    assert core.studio_state()["projectName"] == "My place"
    core.studio.call_tool.return_value = MCPToolResult(
        "script_read", "fallback", False, (), structured_content={"source": "return 42"}
    )
    node = core.inspect_studio(tree[0]["children"][0]["id"])
    assert node["source"] == "return 42"
    assert core.studio.call_tool.call_args.kwargs["studio_id"] == "place"


@pytest.mark.parametrize("payload", ["bad JSON", {"unexpected": []}, 42])
def test_invalid_tree_is_not_silently_reported_ready(core, payload):
    core.studio.call_tool.return_value = MCPToolResult("search_game_tree", "", False, (), structured_content=payload)
    with pytest.raises(CoreError, match="tree"):
        core.refresh_studio()
    assert core.connections()["studio"] == "ERR"


def test_late_studio_installation_rebinds_all_consumers(core):
    replacement = core.studio
    core.studio = _UnavailableStudio("not installed yet")
    with (
        patch("zenless.core.find_studio_mcp", return_value=Path("StudioMCP.exe")),
        patch("zenless.core.StudioMCPClient", return_value=replacement),
    ):
        assert core.refresh_studio()
    assert core.studio is core.qa.studio is core.orchestrator.studio is replacement


def test_studio_monitor_reconnects_when_place_changes(core):
    core._connections["studio"] = "READY"
    core._studio_target_id = "old-place"

    def refresh(**kwargs):
        core._closing.set()

    core.refresh_studio = Mock(side_effect=refresh)
    core._monitor_studio()
    core.refresh_studio.assert_called_once_with(report_error=False)


def test_multiple_places_do_not_select_an_arbitrary_project(core):
    core.studio.list_studios.return_value.append(StudioTarget("other", "Other", {}))
    with pytest.raises(CoreError, match="Multiple Studio"):
        core.refresh_studio()
    core.studio.call_tool.assert_not_called()


def test_standalone_play_creates_persisted_target_without_ai(core):
    core.refresh_studio()
    result = core.start_studio_test()
    task = core.store.load_task(result["jobId"])
    assert task["studio_id"] == "place"
    assert task["stage"] == Stage.TESTING
    assert task["context"]["manual_test"] is True
    core.qa.start_manual.assert_called_once_with(result["jobId"], "STANDARD")
    core.qa.running.return_value = True
    with pytest.raises(CoreError, match="already running"):
        core.start_studio_test()


def test_standalone_play_does_not_interrupt_build(core):
    core.orchestrator.current_task_id = "building"
    with pytest.raises(CoreError, match="active build"):
        core.start_studio_test()
    core.qa.start_manual.assert_not_called()


def test_local_roles_work_without_launching_web_login(tmp_path):
    browser = Mock()
    prompts = []
    gateway = AgentGateway(
        managed=browser,
        embedded=browser,
        local_available=lambda: True,
        local_complete=lambda prompt: prompts.append(prompt) or '{"ok": true}',
    )
    for provider in ("chatgpt", "deepseek"):
        assert gateway.wait_for_provider(provider)
        assert gateway.send_prompt(provider, "Code and protocol", task_id="job") == '{"ok": true}'
    assert prompts[0].startswith("Role: Builder")
    assert prompts[1].startswith("Role: Reviewer")
    browser.wait_for_provider.assert_not_called()
    browser.login.assert_not_called()
    browser.wait_for_provider.return_value = False
    assert not gateway.wait_for_provider("hunyuan")


def test_local_attachments_are_scoped_to_task_and_reject_images(tmp_path):
    text = tmp_path / "script.luau"
    text.write_text("return 42")
    image = tmp_path / "reference.png"
    image.write_bytes(b"image")
    captured = []
    gateway = AgentGateway(
        managed=Mock(),
        embedded=Mock(),
        local_available=lambda: True,
        local_complete=lambda p: captured.append(p) or "ok",
    )
    gateway.wait_for_provider("chatgpt")
    gateway.request("chatgpt", "upload_files", {"files": [str(text)]}, task_id="one", timeout=1)
    gateway.send_prompt("chatgpt", "build", task_id="one")
    gateway.send_prompt("chatgpt", "build", task_id="two")
    assert "return 42" in captured[0] and "return 42" not in captured[1]
    with pytest.raises(Exception, match="text/code"):
        gateway.request("chatgpt", "upload_files", {"files": [str(image)]}, task_id="one", timeout=1)


def test_webview_login_does_not_hide_guest_composer(tmp_path):
    host = WebViewHost(profile_root=tmp_path, provider_specs=PROVIDERS, source=io.BytesIO(), target=io.BytesIO())
    window = Mock()
    host._windows["chatgpt"] = window
    clock = iter([0, 1, 2, 32])
    with (
        patch.object(host, "_ensure_window", return_value=window),
        patch.object(host, "_composer_state", return_value={"composer": True, "ready": False}),
        patch.object(host._stop, "wait", return_value=False),
        patch("zenless.webview_host.time.monotonic", side_effect=lambda: next(clock)),
    ):
        with pytest.raises(TimeoutError):
            host._handle({"action": "login", "provider": "chatgpt", "payload": {"timeout": 30}})
    window.show.assert_called_once()
    window.hide.assert_not_called()


def test_closed_login_is_released_for_retry(tmp_path):
    host = WebViewHost(profile_root=tmp_path, provider_specs=PROVIDERS, source=io.BytesIO(), target=io.BytesIO())
    window = Mock()
    with patch.object(host, "_ensure_window", return_value=window):
        with pytest.raises(RuntimeError, match="closed"):
            host._handle({"action": "login", "provider": "chatgpt"})
    window.hide.assert_not_called()


def test_busy_login_does_not_block_other_providers_or_health(tmp_path):
    host = WebViewHost(profile_root=tmp_path, provider_specs=PROVIDERS, source=io.BytesIO(), target=io.BytesIO())
    host._provider_locks["chatgpt"].acquire()
    host._write = Mock()
    host._handle_guarded = Mock(return_value={"ok": True})
    host._dispatch({"id": "health", "action": "health", "provider": "chatgpt"})
    assert host._write.call_args.args[0]["result"] == {"ready": False, "busy": True}
    host._dispatch({"action": "health", "provider": "deepseek"})
    host._handle_guarded.assert_called_once()
    host._provider_locks["chatgpt"].release()


def test_controller_requires_explicit_authentication(tmp_path):
    controller = WebView2BrowserController(data_root=tmp_path)
    with patch.object(controller, "start"), patch.object(controller, "_request", return_value={"state": "ready"}):
        with pytest.raises(Exception, match="confirmed"):
            controller.login("chatgpt", timeout=1)
    assert controller.provider_status()["chatgpt"]["state"] != "Ready"


def test_completion_continues_truncated_json_without_restarting(tmp_path):
    service = LocalAIService(tmp_path)
    replies = [
        {"choices": [{"message": {"content": '{"code":'}, "finish_reason": "length"}]},
        {"choices": [{"message": {"content": "42}"}, "finish_reason": "stop"}]},
    ]
    requests = []

    def response(request, **kwargs):
        requests.append(json.loads(request.data))
        return io.BytesIO(json.dumps(replies.pop(0)).encode())

    with patch.object(service, "_ensure_started"), patch("zenless.local_ai.urlopen", side_effect=response):
        assert json.loads(service.complete("Build JSON")) == {"code": 42}
    assert requests[1]["messages"][2]["content"] == '{"code":'


def test_unfinished_output_is_never_returned_as_complete(tmp_path):
    service = LocalAIService(tmp_path)

    def response(*args, **kwargs):
        return io.BytesIO(
            json.dumps({"choices": [{"message": {"content": "partial"}, "finish_reason": "length"}]}).encode()
        )

    with patch.object(service, "_ensure_started"), patch("zenless.local_ai.urlopen", side_effect=response):
        with pytest.raises(LocalAIError, match="still truncated"):
            service.complete("Build JSON")


def test_model_switch_unloads_previous_process(tmp_path):
    service = LocalAIService(tmp_path)
    coder, general = service._model_paths()
    coder.parent.mkdir(parents=True)
    coder.touch()
    general.touch()
    with patch.object(service, "_stop_process") as stop:
        service._select_model("Role: Builder. Build")
        assert service.model_path == coder
        service._select_model("Role: Reviewer. Review")
        assert service.model_path == general
    assert stop.call_count == 2


def test_slow_mcp_request_does_not_block_status_or_websocket(tmp_path):
    from tests.test_web_backend import _FakeCore

    core = _FakeCore(tmp_path)
    started, release = threading.Event(), threading.Event()

    def refresh():
        started.set()
        assert release.wait(3)
        return True

    core.refresh_studio = refresh
    (tmp_path / "index.html").write_text("<html></html>")
    bridge = LocalWebBridge(core=core, frontend_root=tmp_path)
    base = bridge.start().split("/?")[0].rstrip("/")
    try:
        with urlopen(base + "/api/session") as response:
            token = json.load(response)["token"]
        headers = {"X-Rubra-Token": token, "Origin": base}

        def slow_request():
            with urlopen(Request(base + "/api/studio/refresh", method="POST", headers=headers), timeout=5) as response:
                return json.load(response)

        with ThreadPoolExecutor(max_workers=1) as pool:
            slow = pool.submit(slow_request)
            try:
                assert started.wait(2)
                with urlopen(Request(base + "/api/status", headers=headers), timeout=0.8) as response:
                    assert json.load(response)["ready"]
                assert not slow.done()
            finally:
                release.set()
            assert slow.result(2)["ok"]
    finally:
        bridge.stop()


def test_refresh_does_not_queue_another_long_mcp_operation(core):
    core._studio_refresh_lock.acquire()
    try:
        with pytest.raises(CoreError, match="being refreshed") as failure:
            core.refresh_studio()
        assert failure.value.code == "STUDIO_BUSY"
        core.studio.list_studios.assert_not_called()
    finally:
        core._studio_refresh_lock.release()


def test_default_code_task_does_not_require_web_3d_login():
    from zenless.models import TaskOptions

    options = TaskOptions.from_api({})
    assert not options.create_3d_asset
    assert not options.visual_first


def test_manual_play_lifecycle_calls_start_and_stop_and_finishes_task(core):
    from tests.test_web_backend import _OfflineBridge, _QAStudio
    from zenless.qa_breaker import QABreaker

    studio = _QAStudio()
    studio.list_studios = lambda: [StudioTarget("place", "My place", {})]
    qa = QABreaker(store=core.store, studio=studio, bridge=_OfflineBridge(), events=core.events, play_test_seconds=1)
    core.qa = qa
    core._connections["studio"] = "READY"
    core._studio_target_id = "place"
    core._studio_label = "My place"
    result = core.start_studio_test("SMOKE")
    qa.wait_for_manual_tests(5)
    assert not qa.running(result["jobId"])
    play_calls = [args["is_start"] for name, args in studio.calls if name == "start_stop_play"]
    assert play_calls == [True, False]
    assert core.store.latest_test_run(result["jobId"]) is not None
    assert core.store.load_task(result["jobId"])["status"] in {"complete", "failed"}


def test_stopping_manual_play_preserves_cancellation_and_stops_studio(core):
    from tests.test_web_backend import _OfflineBridge, _QAStudio
    from zenless.qa_breaker import QABreaker

    studio = _QAStudio()
    studio.list_studios = lambda: [StudioTarget("place", "My place", {})]
    qa = QABreaker(store=core.store, studio=studio, bridge=_OfflineBridge(), events=core.events, play_test_seconds=1)
    original = studio.call_tool

    def tool(name, args, **kwargs):
        result = original(name, args, **kwargs)
        if name == "start_stop_play" and args.get("is_start"):
            qa.stop_all()
        return result

    studio.call_tool = tool
    core.qa = qa
    core._connections["studio"] = "READY"
    core._studio_target_id = "place"
    result = core.start_studio_test("SMOKE")
    qa.wait_for_manual_tests(5)
    assert [args["is_start"] for name, args in studio.calls if name == "start_stop_play"] == [True, False]
    assert core.store.latest_test_run(result["jobId"])["status"] == "CANCELLED"
    assert core.store.load_task(result["jobId"])["final_text"] == "Play Test stopped."
