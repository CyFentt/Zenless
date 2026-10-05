from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from zenless.studio_mcp import (
    MCPError,
    MCPTool,
    MCPToolResult,
    StudioMCPClient,
    StudioTarget,
    find_studio_mcp,
    select_studio_target,
)


class StudioMCPDiscoveryTests(unittest.TestCase):
    def test_current_paired_binary_is_preferred_over_stale_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            roblox = root / "Roblox"
            launcher = roblox / "mcp.bat"
            launcher.parent.mkdir(parents=True)
            launcher.write_text("@echo off\n", encoding="utf-8")
            version = roblox / "Versions" / "version-current"
            version.mkdir(parents=True)
            binary = version / "StudioMCP.exe"
            binary.write_bytes(b"MZ")
            (version / "RobloxStudioBeta.exe").write_bytes(b"MZ")
            with patch.dict(os.environ, {"LOCALAPPDATA": str(root)}, clear=False):
                self.assertEqual(find_studio_mcp(), binary.resolve())

    def test_launcher_is_only_used_when_no_versioned_binary_exists(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            launcher = root / "Roblox" / "mcp.bat"
            launcher.parent.mkdir(parents=True)
            launcher.write_text("@echo off\n", encoding="utf-8")
            with patch.dict(os.environ, {"LOCALAPPDATA": str(root)}, clear=False):
                self.assertEqual(find_studio_mcp(), launcher.resolve())

    def test_startup_retries_an_initial_empty_tool_catalog(self) -> None:
        client = StudioMCPClient(Path("unused.exe"), startup_timeout=5)
        tool = MCPTool("list_roblox_studios", "", {"type": "object"})
        client.refresh_tools = Mock(side_effect=[
            MCPError("Rubra started but did not advertise any tools."),
            [tool],
        ])
        with patch("zenless.studio_mcp.time.sleep"):
            self.assertEqual(client._wait_for_tools(), [tool])
        self.assertEqual(client.refresh_tools.call_count, 2)


class StudioMCPConcurrencyTests(unittest.TestCase):
    def test_discovery_loads_all_pages_before_replacing_the_catalog(self) -> None:
        client = StudioMCPClient(Path("unused.exe"))
        client.request = Mock(side_effect=[
            {"tools": [{"name": "first"}], "nextCursor": "page-2"},
            {"tools": [{"name": "second"}]},
        ])
        self.assertEqual([tool.name for tool in client.refresh_tools()], ["first", "second"])
        self.assertEqual(client.request.call_args_list[1].args[1], {"cursor": "page-2"})
        client.request = Mock(return_value={"tools": [{"name": "incomplete"}], "nextCursor": "loop"})
        with self.assertRaisesRegex(MCPError, "repeated cursor"):
            client.refresh_tools()
        self.assertEqual(set(client.tools), {"first", "second"})

    def test_structured_tool_results_support_studio_discovery(self) -> None:
        client = StudioMCPClient(Path("unused.exe"))
        client.tools["list_roblox_studios"] = MCPTool("list_roblox_studios", "", {"type": "object"})
        client.request = Mock(return_value={
            "content": [], "structuredContent": {"studios": [{"studio_id": "target", "name": "Game"}]},
        })
        self.assertEqual(client.list_studios()[0].studio_id, "target")

    def test_studio_selection_preserves_task_target_and_rejects_ambiguity(self) -> None:
        first, second = StudioTarget("one", "Game one", {}), StudioTarget("two", "Game two", {})
        self.assertEqual(select_studio_target([first, second], "two"), second)
        with self.assertRaisesRegex(MCPError, "Multiple Studio"):
            select_studio_target([first, second])
        with self.assertRaisesRegex(MCPError, "no longer connected"):
            select_studio_target([first], "two")

    def test_tool_calls_are_serialized(self) -> None:
        client = StudioMCPClient(Path("unused-StudioMCP.exe"))
        client.tools["slow"] = MCPTool("slow", "test", {"type": "object", "properties": {}})
        state_lock = threading.Lock()
        active = 0
        max_active = 0
        results: list[str] = []

        def fake_call(name, arguments, *, studio_id="", timeout=180):
            nonlocal active, max_active
            with state_lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.03)
            with state_lock:
                active -= 1
            return MCPToolResult(name, str(arguments["id"]), False, ("text",))

        client._call_tool = fake_call

        def worker(index: int) -> None:
            results.append(client.call_tool("slow", {"id": index}).text)

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)

        self.assertEqual(max_active, 1)
        self.assertCountEqual(results, [str(index) for index in range(6)])


if __name__ == "__main__":
    unittest.main()
