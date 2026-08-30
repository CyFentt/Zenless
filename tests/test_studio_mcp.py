from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path

from zenless.studio_mcp import MCPTool, MCPToolResult, StudioMCPClient


class StudioMCPConcurrencyTests(unittest.TestCase):
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
