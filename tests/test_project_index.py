from __future__ import annotations

import importlib.util
import json
import threading
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from zenless.project_index import ProjectIndexError, ProjectIndexService
from zenless.studio_mcp import MCPToolResult

ADAPTER_PATH = Path(__file__).resolve().parents[1] / "assets" / "code_search_adapter.py"
SPEC = importlib.util.spec_from_file_location("rubra_code_search_adapter", ADAPTER_PATH)
assert SPEC is not None and SPEC.loader is not None
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)


def result(name: str, text: str, error: bool = False) -> MCPToolResult:
    return MCPToolResult(name, text, error, ("text",))


@pytest.fixture
def index_service(tmp_path: Path):
    project = tmp_path / "game"
    project.mkdir()
    service = ProjectIndexService(tmp_path / "rubra")
    service.configure(str(project))
    client = Mock(running=True)
    client.call_tool.side_effect = lambda name, *args, **kwargs: result(
        name, "Indexing complete:" if name == "index_directory" else "InventoryService.luau:1-12"
    )
    service._client = client
    return service, project, client


def test_search_indexes_before_query_and_uses_upstream_arguments(index_service):
    service, project, client = index_service
    payload = service.search("inventory", limit=100)
    assert payload["available"] and payload["projectRoot"] == str(project)
    assert [call.args[0] for call in client.call_tool.call_args_list] == ["index_directory", "search_code"]
    assert client.call_tool.call_args.args[1] == {"query": "inventory", "limit": 30}
    service.search("GrantItem", semantic=False)
    assert client.call_tool.call_args.args[:2] == ("search_text", {"keyword": "GrantItem", "limit": 12})
    assert sum(call.args[0] == "index_directory" for call in client.call_tool.call_args_list) == 2


@pytest.mark.parametrize("text,error", [("Error: directory missing", False), ("interrupted", True), ("pending", False)])
def test_failed_index_cannot_be_used_as_search_evidence(index_service, text, error):
    service, project, client = index_service
    client.call_tool.return_value = result("index_directory", text, error)
    client.call_tool.side_effect = None
    with pytest.raises(ProjectIndexError):
        service.search("inventory")
    assert not service._indexed
    assert client.call_tool.call_count == 1


def test_project_switch_retires_client_and_isolates_storage(index_service, tmp_path):
    service, project, client = index_service
    service.index()
    first = service._environment()
    other = tmp_path / "other-game"
    other.mkdir()
    assert service.configure(str(other)) == str(other)
    second = service._environment()
    client.close.assert_called_once()
    assert service._client is None and not service._indexed
    assert first["RUBRA_INDEX_ROOT"] != second["RUBRA_INDEX_ROOT"]
    assert second["RUBRA_PROJECT_ROOT"] == str(other)
    assert Path(second["RUBRA_INDEX_ROOT"]).is_relative_to(service.portable_root)
    assert second["HF_HUB_DISABLE_TELEMETRY"] == "1"


def test_clearing_project_discards_client(index_service):
    service, project, client = index_service
    service.configure("")
    client.close.assert_called_once()
    assert not service.search("inventory")["available"]


def test_project_switch_waits_for_inflight_search(index_service, tmp_path):
    service, project, client = index_service
    entered = threading.Event()
    release = threading.Event()
    switched = threading.Event()
    other = tmp_path / "other-game"
    other.mkdir()

    def call(name, *args, **kwargs):
        if name == "search_code":
            entered.set()
            assert release.wait(3)
        return result(name, "Indexing complete:" if name == "index_directory" else "inventory")

    client.call_tool.side_effect = call
    search = threading.Thread(target=lambda: service.search("inventory", project_root=str(project)))
    switch = threading.Thread(target=lambda: (service.configure(str(other)), switched.set()))
    search.start()
    assert entered.wait(3)
    switch.start()
    try:
        assert not switched.wait(0.05)
    finally:
        release.set()
        search.join(3)
        switch.join(3)
    assert switched.is_set() and service.project_root == str(other)


@pytest.mark.parametrize("name", [".env", ".env.json", "credentials.json", "secrets.toml", "tokens.json", "game.rbxl", "texture.png", ".code-search.toml"])
def test_private_and_binary_files_are_rejected(tmp_path, name):
    file = tmp_path / name
    file.write_text("private content")
    assert not ADAPTER.safe_source_file(str(file), tmp_path, tmp_path / "rubra")


def test_luau_is_indexable_but_portable_data_is_excluded(tmp_path):
    script = tmp_path / "InventoryService.luau"
    script.write_text("return {}")
    portable = tmp_path / "rubra"
    secret = portable / "data" / "sessions.json"
    secret.parent.mkdir(parents=True)
    secret.write_text('{"cookie":"private"}')
    assert ADAPTER.safe_source_file(str(script), tmp_path, portable)
    assert not ADAPTER.safe_source_file(str(secret), tmp_path, portable)


def test_external_symlink_is_excluded_from_code_and_metadata(tmp_path):
    project = tmp_path / "game"
    project.mkdir()
    external = tmp_path / "private.json"
    external.write_text('{"token":"private"}')
    linked = project / "default.project.json"
    try:
        linked.symlink_to(external)
    except OSError:
        pytest.skip("Symlinks unavailable")
    service = ProjectIndexService(tmp_path / "rubra")
    service.configure(str(project))
    assert not ADAPTER.safe_source_file(str(linked), project, service.portable_root)
    assert "private" not in json.dumps(service.project_metadata())


def test_portable_client_launches_locked_upstream_through_adapter(tmp_path):
    portable = tmp_path / "rubra"
    service = ProjectIndexService(portable)
    uv = portable / "runtime" / "tools" / "uv" / "uv.exe"
    uv.parent.mkdir(parents=True)
    uv.touch()
    service.source_root.mkdir(parents=True)
    (service.source_root / "pyproject.toml").touch()
    service.configure(str(tmp_path))
    with patch("zenless.project_index.StudioMCPClient") as client_type:
        service._ensure_client()
        arguments = client_type.call_args.kwargs["args"]
        assert "--locked" in arguments
        assert arguments[-1] == str(ADAPTER_PATH)
        client_type.return_value.start.assert_called_once()
