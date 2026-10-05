from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from zenless.event_bus import EventBus
from zenless.models import ProposalAction, Stage, TaskOptions
from zenless.orchestrator import OrchestratorError
from zenless.policy import classify_action
from zenless.prompts import compact_json
from zenless.qa_breaker import QABreaker
from zenless.qa_breaker import TestProfile as QAProfile
from zenless.static_quality import StaticCheck
from zenless.store import SQLiteStore
from zenless.studio_data import (
    SourceSnapshot,
    export_sources,
    read_scene,
    read_sources,
    read_tree,
    result_tree,
    script_source,
    studio_edit_mode,
)
from zenless.studio_mcp import (
    MCPBusyError,
    MCPError,
    MCPTool,
    MCPToolResult,
    StudioMCPClient,
    StudioTarget,
    find_studio_mcp,
    select_studio_target,
)
from zenless.web_app import DesktopAPI


def result(payload, *, name="execute_luau", wrapped=False):
    return MCPToolResult(name, "Completed", False, ("text",), structured_content={"result": payload} if wrapped else payload)


def studio_tools():
    return {
        "execute_luau": MCPTool("execute_luau", "", {"properties": {"code": {}, "datamodel_type": {}}}),
        "search_game_tree": MCPTool("search_game_tree", "", {"properties": {"head_limit": {"maximum": 100}}}),
    }


@pytest.mark.parametrize("text", [
    'Found objects:\n```json\n{"instances":[{"path":"game.Workspace","className":"Workspace"}]}\n```',
    'Returned value: "{\\"instances\\":[{\\"path\\":\\"game.Workspace\\",\\"className\\":\\"Workspace\\"}]}"',
    '\ufeff{"output":{"data":{"instances":[{"path":"game.Workspace","className":"Workspace"}]}}}',
])
def test_tree_accepts_wrapped_and_encoded_rpc_values(text):
    assert result_tree(MCPToolResult("search_game_tree", text, False, ("text",)))[0]["path"] == "game.Workspace"


def test_summary_does_not_hide_embedded_resource_tree():
    client = StudioMCPClient(Path("unused"))
    client.tools["search_game_tree"] = MCPTool("search_game_tree", "", {"properties": {}})
    client.request = Mock(return_value={
        "structuredContent": {"count": 1},
        "content": [
            {"type": "text", "text": "Found 1 instance"},
            {"type": "resource", "resource": {"text": '{"instances":[{"name":"Workspace","className":"Workspace"}]}'}},
        ],
    })
    assert result_tree(client.call_tool("search_game_tree", {}))[0]["name"] == "Workspace"


def test_summary_only_is_not_an_empty_inventory():
    with pytest.raises(MCPError, match="summary"):
        result_tree(result({"count": 123}))


def test_inventory_pages_past_shallow_search_and_keeps_duplicate_paths():
    studio = Mock(tools=studio_tools())
    items = [{"id": str(i), "path": "game.Workspace.Same", "className": "Part"} for i in range(501)]
    studio.call_tool.side_effect = [
        result({"instances": items[:1]}, name="search_game_tree"),
        result({"instances": items[:500], "total": 501, "offset": 0}, wrapped=True),
        result({"instances": items[500:], "total": 501, "offset": 500}, wrapped=True),
    ]
    snapshot = read_tree(studio, "active-game")
    assert snapshot.complete and snapshot.instances == items and snapshot.total == 501
    assert studio.call_tool.call_args_list[0].args[1] == {"head_limit": 100}
    assert all(call.kwargs["studio_id"] == "active-game" for call in studio.call_tool.call_args_list)


@pytest.mark.parametrize("page", [
    {"instances": [], "total": 1, "offset": 0},
    {"instances": [], "total": 0, "offset": 500},
    {"total": 0, "offset": 0},
])
def test_incomplete_or_wrong_inventory_page_is_rejected(page):
    studio = Mock(tools=studio_tools())
    studio.call_tool.side_effect = [result({"count": 2}), result(page)]
    with pytest.raises(MCPError):
        read_tree(studio, "game")


def test_source_pages_export_entire_files_and_remove_only_owned_stale_files(tmp_path):
    studio = Mock(tools=studio_tools())
    sources = [{"id": str(i), "path": "game.ServerScriptService.Same", "source": "return '" + "x" * 5000 + "'", "readError": ""} for i in range(41)]
    sources[-1]["readError"] = "Source access denied"
    studio.call_tool.side_effect = [
        result({"sources": sources[:40], "total": 41, "offset": 0}, wrapped=True),
        result({"sources": sources[40:], "total": 41, "offset": 40}, wrapped=True),
    ]
    snapshot = read_sources(studio, "place")
    manifest = export_sources(tmp_path, "place", snapshot)
    assert manifest["readable"] == 40 and manifest["errors"][0]["error"] == "Source access denied"
    assert len(set(manifest["files"])) == 40
    assert (tmp_path / manifest["files"][0]).read_text() == sources[0]["source"]
    (tmp_path / "user-file.luau").write_text("return 1")
    export_sources(tmp_path, "place", SourceSnapshot([], True, 0))
    assert (tmp_path / "user-file.luau").is_file()
    assert not any((tmp_path / name).exists() for name in manifest["files"])
    assert (tmp_path / "selene.toml").read_text() == 'std = "roblox"\n'


def test_empty_script_and_structured_mode_are_not_confused_with_summaries():
    assert script_source(result({"output": {"source": ""}})) == ""
    assert studio_edit_mode(result({"result": {"isPlaying": False}})) is True
    assert studio_edit_mode(result({"mode": "Play"})) is False
    assert studio_edit_mode(result({"summary": "Alive"})) is None


def test_busy_lock_has_a_deadline_and_does_not_send_an_rpc():
    client = StudioMCPClient(Path("unused"))
    client._call_tool = Mock()
    client._tool_call_lock.acquire()
    try:
        with pytest.raises(MCPBusyError):
            client.call_tool("execute_luau", {}, timeout=0.001)
        client._call_tool.assert_not_called()
    finally:
        client._tool_call_lock.release()
    client.call_tool("execute_luau", {}, timeout=1)
    assert 0 < client._call_tool.call_args.kwargs["timeout"] <= 1


def test_latest_paired_studio_binary_precedes_old_launcher(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    roblox = tmp_path / "Roblox"
    roblox.mkdir()
    (roblox / "mcp.bat").write_text("stale path")
    version = roblox / "Versions" / "version-active"
    version.mkdir(parents=True)
    (version / "StudioMCP.exe").write_bytes(b"binary")
    (version / "RobloxStudioBeta.exe").write_bytes(b"studio")
    assert find_studio_mcp() == version / "StudioMCP.exe"


def test_active_game_is_automatic_but_running_task_cannot_switch():
    old = StudioTarget("old", "Old game", {})
    active = StudioTarget("active", "New game", {"isActive": True})
    assert select_studio_target([old, active], preferred_id="old") == active
    assert select_studio_target([old, active], "old") == old
    with pytest.raises(MCPError, match="no longer"):
        select_studio_target([active], "old")


def test_scene_mutation_needs_expected_properties_and_exact_readback():
    args = {"code": "game.Workspace.Spawn.Anchored = true", "datamodel_type": "Edit", "_zenless_expected_instances": {"game.Workspace.Spawn": {"Anchored": True}}}
    assert classify_action(ProposalAction("execute_luau", args), {"execute_luau"}).allowed
    assert not classify_action(ProposalAction("execute_luau", {**args, "datamodel_type": "Client"}), {"execute_luau"}).allowed
    studio = Mock(tools=studio_tools())
    studio.call_tool.return_value = result({"observed": {}, "missing": ["game.Workspace.Spawn"], "failures": []})
    with pytest.raises(MCPError, match="did not match"):
        read_scene(studio, "active", args["_zenless_expected_instances"], verify=True)


def test_tray_close_preserves_workers_and_quit_is_explicit():
    window = SimpleNamespace(hide=Mock(), show=Mock(), restore=Mock(), destroy=Mock())
    api = DesktopAPI()
    api._bind(window)
    api._tray = Mock(available=True)
    api.close_window()
    assert api._on_closing() is False
    window.destroy.assert_not_called()
    api._show()
    window.show.assert_called_once()
    api._quit()
    api._tray.stop.assert_called_once()
    window.destroy.assert_called_once()
    assert api._on_closing() is True


def qa_fixture(tmp_path, studio):
    db = SQLiteStore(tmp_path / "state.db")
    db.create_task("test", "Review the existing game", TaskOptions())
    db.update_task("test", studio_id="active", context_json={"manual_test": True})
    return QABreaker(store=db, studio=studio, bridge=Mock(), events=EventBus(), capture_root=tmp_path / "captures", play_test_seconds=1)


def test_manual_qa_automatically_exports_and_refreshes_live_sources(tmp_path):
    studio = Mock(tools=studio_tools())
    source = {"id": "1", "path": "game.ServerScriptService.Main", "source": "return 1", "readError": ""}
    studio.call_tool.return_value = result({"sources": [source], "total": 1, "offset": 0})
    qa = qa_fixture(tmp_path, studio)
    root = Path(qa._qa_project_root("test"))
    assert root.is_relative_to(tmp_path) and not qa.store.get_setting("ui.settings", {}).get("projectRoot")
    studio.call_tool.return_value = result({"sources": [{**source, "source": "return 2"}], "total": 1, "offset": 0})
    qa._qa_project_root("test", refresh=True)
    assert next(root.glob("script_*.luau")).read_text() == "return 2"


def test_partial_source_checks_do_not_claim_full_success(tmp_path):
    studio = Mock(tools=studio_tools())
    studio.call_tool.return_value = result({"sources": [{"path": "game.Private", "source": "", "readError": "Protected"}], "total": 1, "offset": 0})
    qa = qa_fixture(tmp_path, studio)
    qa.static_quality.run = Mock(return_value=[StaticCheck("Syntax", "PASSED", "ok")])
    status, _, details = qa._run_static_quality("test")
    assert status == "SKIPPED" and "0/1" in details and "Coverage incomplete" in details


def test_manual_play_retries_inventory_lock_without_changing_target(tmp_path):
    studio = Mock(running=True)
    studio.list_studios.side_effect = [MCPBusyError("busy"), [StudioTarget("active", "Game", {})]]
    qa = qa_fixture(tmp_path, studio)
    qa.run = Mock()
    qa._manual_worker("test", "STANDARD", Mock(is_set=Mock(return_value=False)))
    qa.run.assert_called_once()
    assert qa.run.call_args.kwargs["studio_id"] == "active"


def test_cancel_before_discovery_does_not_start_play(tmp_path):
    studio = Mock(running=True)
    qa = qa_fixture(tmp_path, studio)
    qa.run = Mock()
    cancel = threading.Event()
    cancel.set()
    qa._manual_worker("test", "STANDARD", cancel)
    qa.run.assert_not_called()
    assert qa.store.load_task("test")["final_text"] == "Play Test stopped."


def test_capture_keeps_original_pixels_and_registers_resolution(tmp_path):
    from tests.test_orchestrator import FakeVisualBridge

    qa = qa_fixture(tmp_path, Mock())
    captured = []
    qa.events.subscribe(lambda event: captured.append(event.data) if event.type == "TEST_CAPTURE" else None)
    pixels = FakeVisualBridge._png_bytes((20, 30, 40))
    path = qa._persist_capture("test", 123, {"data": base64.b64encode(pixels).decode(), "mimeType": "image/png"})
    assert path is not None and path.read_bytes() == pixels
    assert captured[0]["capture"]["width"] == 256
    assert captured[0]["capture"]["height"] == 256
    assert qa._persist_capture("test", 124, {"data": "ZmFrZQ==", "mimeType": "image/png"}) is None


def test_large_context_is_valid_json_and_excerpts_are_explicit():
    payload = {"source_coverage": {"total_scripts": 2000, "complete": False}, "sources": ["x" * 50000] * 100}
    encoded = compact_json(payload, 5000)
    assert len(encoded) <= 5000
    parsed = json.loads(encoded)
    assert parsed["source_coverage"]["complete"] is False
    assert "excerpt" in parsed["sources"][0]


def test_gameplay_captures_happen_before_stop_and_console_errors_fail(tmp_path):
    from tests.test_orchestrator import FakeVisualBridge

    studio = Mock(tools={
        "start_stop_play": MCPTool("start_stop_play", "", {}),
        "screen_capture": MCPTool("screen_capture", "", {"properties": {"capture_id": {}}}),
        "get_console_output": MCPTool("get_console_output", "", {}),
    })
    playing = False
    capture_count = 0
    pixels = base64.b64encode(FakeVisualBridge._png_bytes((20, 30, 40))).decode()

    def call(name, arguments, **kwargs):
        nonlocal playing, capture_count
        if name == "start_stop_play":
            playing = arguments["is_start"]
            return result({"ok": True})
        if name == "screen_capture":
            assert playing, "A gameplay frame must be captured while Studio is playing"
            capture_count += 1
            return MCPToolResult(name, "", False, ("image",), images=({"data": pixels, "mimeType": "image/png"},))
        assert playing
        return result({"errors": ["Runtime error: bad argument"]}, name=name)

    studio.call_tool.side_effect = call
    qa = qa_fixture(tmp_path, studio)
    qa.store.create_test_run("run", "test", "FAST", 123)
    failures = []
    _, status = qa._run_play_case("run", "test", "active", QAProfile("FAST", 10, 1, 1, 1), threading.Event(), failures, [], 123)
    assert status == "FAILED" and failures
    assert capture_count == 3 and not playing
    assert len(qa._play_captures["test"]) == 3


@pytest.mark.parametrize("concurrent", [False, True])
def test_scene_readback_and_concurrent_write_protection(tmp_path, concurrent):
    from tests.test_orchestrator import FakeBridge, FakeStudio, OrchestratorTests

    studio = FakeStudio()
    studio.tools.update(studio_tools())
    orchestrator, store = OrchestratorTests().make_system(str(tmp_path), FakeBridge({}), studio)
    store.create_task("scene", "Fix spawn", TaskOptions())
    store.update_task("scene", stage=Stage.APPLYING, status="running")
    args = {"code": "game.Workspace.Spawn.Anchored = true", "datamodel_type": "Edit", "_zenless_expected_instances": {"game.Workspace.Spawn": {"Anchored": True}}}
    action = ProposalAction("execute_luau", args)
    before = {"observed": {"game.Workspace.Spawn": {"Anchored": False}}, "missing": [], "failures": ["game.Workspace.Spawn:Anchored"]}
    after = {"observed": {"game.Workspace.Spawn": {"Anchored": True}}, "missing": [], "failures": []}
    with patch("zenless.orchestrator.read_scene", side_effect=[before, after if concurrent else before, after]):
        orchestrator._bind_mutation_preconditions("scene", "studio-1", [action])
        if concurrent:
            with pytest.raises(OrchestratorError, match="STUDIO_CHANGED"):
                orchestrator._apply_actions("scene", "studio-1", [action])
            assert not any(name == "execute_luau" for name, _ in studio.calls)
        else:
            evidence = orchestrator._apply_actions("scene", "studio-1", [action])
            assert evidence[-1]["verified"] is True
            native_args = next(arguments for name, arguments in studio.calls if name == "execute_luau")
            assert not any(key.startswith("_zenless_") for key in native_args)
            before_calls = len(studio.calls)
            orchestrator._apply_actions("scene", "studio-1", [action])
            assert len(studio.calls) == before_calls


LUNE = os.environ.get("RUBRA_TEST_LUNE") or shutil.which("lune")


@pytest.mark.skipif(not LUNE, reason="Upstream Lune runtime is not installed")
@pytest.mark.parametrize("operation", ["inventory", "sources", "scene", "scene_missing"])
def test_readers_execute_real_luau_against_roblox_instances(tmp_path, operation):
    fixture = '''local rb = require('@lune/roblox')
local serde = require('@lune/serde')
local workspace = rb.Instance.new('Folder')
workspace.Name = 'Workspace'
local spawn = rb.Instance.new('Part')
spawn.Name = 'Spawn'
spawn.Anchored = true
spawn.Position = rb.Vector3.new(1, 2, 3)
spawn.Parent = workspace
for i=1, 510 do
    local p=rb.Instance.new('Part') p.Name='Same' p.Parent=workspace
end
for i=1, 45 do
    local s=rb.Instance.new('ModuleScript') s.Name='Module' s.Source='return '..i s.Parent=workspace
end
local game = {}
function game:GetChildren() return {workspace} end
function game:GetDescendants()
    local items = {workspace}
    for _, item in workspace:GetDescendants() do table.insert(items, item) end
    return items
end
function game:GetService(name)
    assert(name == 'HttpService')
    return {JSONEncode=function(_, v) return serde.encode('json',v) end, JSONDecode=function(_, v) return serde.decode('json',v) end}
end
local function rpc()
'''
    studio = Mock(tools=studio_tools())

    def call(name, arguments, **kwargs):
        assert kwargs["studio_id"] == "real-fixture"
        if name == "search_game_tree":
            return MCPToolResult(name, "Found objects (summary)", False, ("text",))
        file = tmp_path / "read.luau"
        file.write_text(fixture + arguments["code"] + "\nend\nprint(rpc())\n")
        output = subprocess.run([str(LUNE), "run", str(file)], capture_output=True, text=True, timeout=20, check=True)
        return MCPToolResult(name, "Returned value: " + output.stdout.strip(), False, ("text",))

    studio.call_tool.side_effect = call
    if operation == "inventory":
        snapshot = read_tree(studio, "real-fixture")
        assert snapshot.complete and snapshot.total == 557 and len(snapshot.instances) == 557
        assert len({item["id"] for item in snapshot.instances}) == 557
    elif operation == "sources":
        snapshot = read_sources(studio, "real-fixture")
        assert snapshot.complete and snapshot.total == 45
        assert snapshot.scripts[-1]["source"] == "return 45"
    else:
        path = "game.Workspace.Spawn" if operation == "scene" else "game.Workspace.Absent"
        expected = {path: {"Anchored": True, "Position": [1, 2, 3]}}
        if operation == "scene_missing":
            with pytest.raises(MCPError, match="did not match"):
                read_scene(studio, "real-fixture", expected, verify=True)
        else:
            evidence = read_scene(studio, "real-fixture", expected, verify=True)
            assert evidence["observed"][path]["Position"] == [1, 2, 3]
