from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from zenless.models import Stage, TaskOptions
from zenless.orchestrator import OrchestratorError, ZenlessOrchestrator
from zenless.store import SQLiteStore
from zenless.studio_mcp import MCPError, MCPTool, MCPToolResult, StudioTarget


def proposal(*, replacement: str = "local value = 2", read_only: bool = False) -> str:
    actions: list[dict[str, Any]]
    if read_only:
        actions = [{"tool": "script_search", "arguments": {"query": "Main"}, "reason": "inspect"}]
    else:
        actions = [
            {
                "tool": "multi_edit",
                "arguments": {
                    "file_path": "game.ServerScriptService.Main",
                    "edits": [{"old_string": "local value = 1", "new_string": replacement}],
                },
                "reason": "verified change",
                "risk": "medium",
            }
        ]
    return json.dumps(
        {
            "summary": "Implementação planejada",
            "actions": actions,
            "final_message": "Pronto",
            "visual_prompt": "",
            "model_3d_prompt": "",
            "tests": ["Play Solo"],
        }
    )


def review(verdict: str = "approve") -> str:
    return json.dumps(
        {
            "verdict": verdict,
            "summary": "Revisão concluída",
            "issues": [] if verdict == "approve" else ["Ajustar implementação"],
            "required_changes": [] if verdict == "approve" else ["Corrigir o bloco"],
            "tests_required": ["Play Solo"],
            "risk": "low",
            "confidence": 0.95,
        }
    )


class FakeBridge:
    def __init__(self, responses: dict[str, list[str]], available: set[str] | None = None) -> None:
        self.responses = {key: list(value) for key, value in responses.items()}
        self.available = available or {"chatgpt", "deepseek"}
        self.prompts: list[tuple[str, str]] = []

    def wait_for_provider(self, provider: str, timeout: float = 0.0) -> bool:
        return provider in self.available

    def send_prompt(self, provider: str, prompt: str, *, task_id: str, timeout: float = 360.0) -> str:
        self.prompts.append((provider, prompt))
        queue = self.responses.get(provider, [])
        if not queue:
            raise AssertionError(f"Sem resposta mock para {provider}")
        return queue.pop(0)

    def request(self, provider: str, action: str, payload: dict[str, Any], *, task_id: str, timeout: float) -> dict[str, Any]:
        return {"status": "ok", "artifact_name": "asset.glb", "text": "generated"}


class FakeStudio:
    def __init__(self, console_outputs: list[str] | None = None, *, fail_console: bool = False) -> None:
        names = [
            "list_roblox_studios",
            "get_studio_state",
            "search_game_tree",
            "get_console_output",
            "script_search",
            "script_read",
            "multi_edit",
            "start_stop_play",
        ]
        self.tools = {
            name: MCPTool(name, name, {"type": "object", "properties": {}, "additionalProperties": True})
            for name in names
        }
        self.running = True
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.console_outputs = list(console_outputs or [""])
        self.fail_console = fail_console
        self.in_play = False
        self.source = "local value = 1"

    def start(self) -> None:
        self.running = True

    def list_studios(self) -> list[StudioTarget]:
        return [StudioTarget("studio-1", "Unit Test Studio", {})]

    def call_tool(self, name: str, arguments: dict[str, Any], *, studio_id: str = "", timeout: float = 0) -> MCPToolResult:
        self.calls.append((name, dict(arguments)))
        if name == "start_stop_play":
            self.in_play = bool(arguments.get("is_start"))
            return MCPToolResult(name, "ok", False, ("text",))
        if name == "get_console_output":
            if self.in_play and self.fail_console:
                raise MCPError("console unavailable")
            text = self.console_outputs.pop(0) if self.in_play and self.console_outputs else ""
            return MCPToolResult(name, text, False, ("text",))
        if name == "script_read":
            return MCPToolResult(name, self.source, False, ("text",))
        if name == "multi_edit":
            self.source = str(arguments["edits"][0]["new_string"])
            return MCPToolResult(name, "edited", False, ("text",))
        if name == "search_game_tree":
            return MCPToolResult(name, "[]", False, ("text",))
        if name == "get_studio_state":
            return MCPToolResult(name, '{"state":"Edit"}', False, ("text",))
        return MCPToolResult(name, "ok", False, ("text",))


class OrchestratorTests(unittest.TestCase):
    def make_system(
        self,
        folder: str,
        bridge: FakeBridge,
        studio: FakeStudio,
    ) -> tuple[ZenlessOrchestrator, SQLiteStore]:
        store = SQLiteStore(Path(folder) / "state.db")
        orchestrator = ZenlessOrchestrator(
            store=store,
            bridge=bridge,  # type: ignore[arg-type]
            studio=studio,  # type: ignore[arg-type]
            run_root=Path(folder) / "runs",
            play_test_seconds=1,
        )
        return orchestrator, store

    def finish_with_gate_decisions(
        self,
        orchestrator: ZenlessOrchestrator,
        task_id: str,
        decisions: list[str],
        timeout: float = 12,
    ) -> None:
        seen: set[str] = set()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with orchestrator._state_lock:
                gates = [gate for owner, gate in orchestrator._gates if owner == task_id]
                thread = orchestrator._tasks.get(task_id)
            for gate in gates:
                if gate in seen:
                    continue
                seen.add(gate)
                decision = decisions.pop(0) if decisions else "approve"
                self.assertTrue(orchestrator.approve(task_id, gate, decision))
            if thread is None or not thread.is_alive():
                return
            time.sleep(0.02)
        self.fail("Orquestrador não concluiu dentro do timeout")

    def test_create_review_approve_apply_and_play_test(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = FakeBridge({"chatgpt": [proposal()], "deepseek": [review()]})
            studio = FakeStudio([""])
            orchestrator, store = self.make_system(folder, bridge, studio)
            task_id = orchestrator.submit("Mude o script", TaskOptions(create_3d_asset=False))
            self.finish_with_gate_decisions(orchestrator, task_id, ["approve"])
            task = store.load_task(task_id)
            self.assertEqual(task["stage"], Stage.COMPLETE.value)
            calls = [name for name, _ in studio.calls]
            self.assertIn("multi_edit", calls)
            self.assertEqual(
                [args["is_start"] for name, args in studio.calls if name == "start_stop_play"],
                [True, False],
            )
            self.assertTrue(list((Path(folder) / "runs" / task_id).glob("before-*.luau.txt")))

    def test_rejected_change_never_reaches_multi_edit(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = FakeBridge({"chatgpt": [proposal()], "deepseek": [review()]})
            studio = FakeStudio()
            orchestrator, store = self.make_system(folder, bridge, studio)
            task_id = orchestrator.submit("Não aplique", TaskOptions(create_3d_asset=False))
            self.finish_with_gate_decisions(orchestrator, task_id, ["reject"])
            self.assertEqual(store.load_task(task_id)["stage"], Stage.BLOCKED.value)
            self.assertNotIn("multi_edit", [name for name, _ in studio.calls])

    def test_review_revision_and_repair_loop(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = FakeBridge(
                {
                    "chatgpt": [proposal(), proposal(replacement="local value = 3"), proposal(replacement="local value = 4")],
                    "deepseek": [review("revise"), review(), review()],
                }
            )
            studio = FakeStudio(["Error: simulated failure", ""])
            orchestrator, store = self.make_system(folder, bridge, studio)
            task_id = orchestrator.submit("Corrija e teste", TaskOptions(create_3d_asset=False, max_revisions=2))
            self.finish_with_gate_decisions(orchestrator, task_id, ["approve", "approve"], timeout=18)
            self.assertEqual(store.load_task(task_id)["stage"], Stage.COMPLETE.value)
            calls = [name for name, _ in studio.calls]
            self.assertEqual(calls.count("multi_edit"), 2)
            self.assertEqual(calls.count("start_stop_play"), 4)
            self.assertEqual(len([provider for provider, _ in bridge.prompts if provider == "chatgpt"]), 3)

    def test_play_test_is_stopped_when_output_read_fails(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = FakeBridge({"chatgpt": [proposal()], "deepseek": [review()]})
            studio = FakeStudio(fail_console=True)
            orchestrator, store = self.make_system(folder, bridge, studio)
            task_id = orchestrator.submit("Teste falha segura", TaskOptions(create_3d_asset=False))
            self.finish_with_gate_decisions(orchestrator, task_id, ["approve"])
            self.assertEqual(store.load_task(task_id)["stage"], Stage.FAILED.value)
            self.assertEqual(
                [args["is_start"] for name, args in studio.calls if name == "start_stop_play"],
                [True, False],
            )
            self.assertFalse(studio.in_play)

    def test_duplicate_research_reads_execute_once(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = FakeBridge({"chatgpt": [proposal(read_only=True), proposal(read_only=True)]}, {"chatgpt"})
            studio = FakeStudio()
            orchestrator, store = self.make_system(folder, bridge, studio)
            options = TaskOptions(create_3d_asset=False, independent_review=False, automatic_play_test=False)
            task_id = orchestrator.submit("Somente leia", options)
            self.finish_with_gate_decisions(orchestrator, task_id, [])
            self.assertEqual(store.load_task(task_id)["stage"], Stage.COMPLETE.value)
            self.assertEqual([name for name, _ in studio.calls].count("script_search"), 1)

    def test_explicit_no_approval_option_does_not_pause(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = FakeBridge({"chatgpt": [proposal()], "deepseek": [review()]})
            studio = FakeStudio([""])
            orchestrator, store = self.make_system(folder, bridge, studio)
            options = TaskOptions(create_3d_asset=False, require_approval=False)
            task_id = orchestrator.submit("Aplique no modo autorizado", options)
            self.finish_with_gate_decisions(orchestrator, task_id, [])
            self.assertEqual(store.load_task(task_id)["stage"], Stage.COMPLETE.value)
            self.assertIn("multi_edit", [name for name, _ in studio.calls])

    def test_second_task_is_rejected_while_approval_is_pending(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = FakeBridge({"chatgpt": [proposal()], "deepseek": [review()]})
            studio = FakeStudio()
            orchestrator, store = self.make_system(folder, bridge, studio)
            first = orchestrator.submit("Primeira tarefa", TaskOptions(create_3d_asset=False))
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if store.load_task(first)["stage"] == Stage.WAITING_CHANGE_APPROVAL.value:
                    break
                time.sleep(0.02)
            with self.assertRaisesRegex(OrchestratorError, "tarefa ativa"):
                orchestrator.submit("Segunda tarefa", TaskOptions(create_3d_asset=False))
            self.assertTrue(orchestrator.approve_active(first, ("changes:",), "reject"))
            self.assertTrue(orchestrator.wait_for_idle(5))
            self.assertEqual(store.load_task(first)["stage"], Stage.BLOCKED.value)


if __name__ == "__main__":
    unittest.main()
