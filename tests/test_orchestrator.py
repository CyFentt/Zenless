from __future__ import annotations

import json
import struct
import tempfile
import time
import unittest
import zlib
from pathlib import Path
from typing import Any
from unittest.mock import patch

from zenless.browser_bridge import BridgeError
from zenless.models import ProposalAction, ReviewResult, Stage, TaskOptions
from zenless.orchestrator import OrchestratorError, ZenlessOrchestrator
from zenless.store import SQLiteStore
from zenless.studio_mcp import MCPError, MCPTool, MCPToolResult, StudioTarget


def proposal(*, replacement: str = "local value = 2", original: str = "local value = 1", read_only: bool = False) -> str:
    actions: list[dict[str, Any]]
    if read_only:
        actions = [{"tool": "script_search", "arguments": {"query": "Main"}, "reason": "inspect"}]
    else:
        actions = [
            {
                "tool": "multi_edit",
                "arguments": {
                    "file_path": "game.ServerScriptService.Main",
                    "edits": [{"old_string": original, "new_string": replacement}],
                },
                "reason": "verified change",
                "risk": "medium",
            }
        ]
    return json.dumps(
        {
            "summary": "Planned implementation",
            "actions": actions,
            "final_message": "Ready",
            "visual_prompt": "",
            "model_3d_prompt": "",
            "tests": ["Play Solo"],
        }
    )


def review(verdict: str = "approve") -> str:
    return json.dumps(
        {
            "verdict": verdict,
            "summary": "Review completed",
            "issues": [] if verdict == "approve" else ["Adjust implementation"],
            "required_changes": [] if verdict == "approve" else ["Fix the block"],
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
            raise AssertionError(f"No mock response for {provider}")
        return queue.pop(0)

    def request(
        self, provider: str, action: str, payload: dict[str, Any], *, task_id: str, timeout: float
    ) -> dict[str, Any]:
        return {"status": "ok", "artifact_name": "asset.glb", "text": "generated"}


class FakeVisualBridge(FakeBridge):
    _VIEW_COLORS = {
        "front": (220, 50, 47),
        "back": (38, 139, 210),
        "left": (133, 153, 0),
        "right": (181, 137, 0),
        "top": (108, 113, 196),
        "bottom": (203, 75, 22),
    }

    @staticmethod
    def _png_bytes(color: tuple[int, int, int]) -> bytes:
        width = height = 256
        pixel = bytes((*color, 255))
        scanlines = b"".join(b"\0" + pixel * width for _ in range(height))

        def chunk(kind: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(scanlines))
            + chunk(b"IEND", b"")
        )

    def request(
        self,
        provider: str,
        action: str,
        payload: dict[str, Any],
        *,
        task_id: str,
        timeout: float,
    ) -> dict[str, Any]:
        if action == "generate_image":
            output = Path(str(payload["output_path"]))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(self._png_bytes(self._VIEW_COLORS[output.stem]))
            return {"status": "ok", "artifact_path": str(output)}
        if action == "upload_files":
            files = payload.get("files") or []
            return {"status": "ok", "uploaded": len(files)}
        return super().request(provider, action, payload, task_id=task_id, timeout=timeout)


class FakeHunyuanBridge(FakeVisualBridge):
    def request(
        self,
        provider: str,
        action: str,
        payload: dict[str, Any],
        *,
        task_id: str,
        timeout: float,
    ) -> dict[str, Any]:
        if provider == "hunyuan" and action == "capabilities":
            return {
                "status": "ok",
                "capabilities": {"upload_files": True, "geometry": True, "texture": True, "max_image_inputs": 6},
            }
        return super().request(provider, action, payload, task_id=task_id, timeout=timeout)


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

    def call_tool(
        self, name: str, arguments: dict[str, Any], *, studio_id: str = "", timeout: float = 0
    ) -> MCPToolResult:
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
            for edit in arguments["edits"]:
                old, new = edit["old_string"], edit["new_string"]
                if old and self.source.count(old) != 1:
                    return MCPToolResult(name, "Source range not found or ambiguous", True, ("text",))
                self.source = self.source.replace(old, new, 1) if old else new
            return MCPToolResult(name, "edited", False, ("text",))
        if name == "search_game_tree":
            return MCPToolResult(name, "[]", False, ("text",))
        if name == "get_studio_state":
            return MCPToolResult(name, '{"state":"Edit"}', False, ("text",))
        return MCPToolResult(name, "ok", False, ("text",))


class OrchestratorTests(unittest.TestCase):
    def test_sequential_edits_to_one_script_use_predicted_preconditions(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            studio = FakeStudio()
            orchestrator, store = self.make_system(folder, FakeBridge({}), studio)
            store.create_task("sequence", "Edit", TaskOptions())
            store.update_task("sequence", stage=Stage.APPLYING, status="running")
            actions = [ProposalAction("multi_edit", {
                "file_path": "game.ServerScriptService.Main",
                "edits": [{"old_string": f"local value = {old}", "new_string": f"local value = {new}"}],
            }) for old, new in [(1, 2), (2, 3)]]
            orchestrator._bind_mutation_preconditions("sequence", "studio-1", actions)
            evidence = orchestrator._apply_actions("sequence", "studio-1", actions)
            self.assertEqual(studio.source, "local value = 3")
            self.assertEqual(sum(item.get("verified", False) for item in evidence), 2)

    def test_new_script_requires_confirmed_absence_and_complete_readback(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            studio = FakeStudio()
            original_call = studio.call_tool
            created = False

            def call(name: str, arguments: dict[str, Any], **kwargs: Any) -> MCPToolResult:
                nonlocal created
                if name == "script_read" and not created:
                    return MCPToolResult(name, "game.ServerScriptService.NewScript not found", True, ("text",))
                if name == "multi_edit":
                    created = True
                return original_call(name, arguments, **kwargs)

            orchestrator, store = self.make_system(folder, FakeBridge({}), studio)
            store.create_task("new", "Create", TaskOptions())
            store.update_task("new", stage=Stage.APPLYING, status="running")
            action = ProposalAction("multi_edit", {
                "file_path": "game.ServerScriptService.NewScript", "className": "Script",
                "edits": [{"old_string": "", "new_string": "local ready = true"}],
            })
            with patch.object(studio, "call_tool", side_effect=call):
                orchestrator._bind_mutation_preconditions("new", "studio-1", [action])
                self.assertFalse(action.arguments["_zenless_expected_exists"])
                evidence = orchestrator._apply_actions("new", "studio-1", [action])
            self.assertTrue(created)
            self.assertTrue(evidence[-1]["verified"])
            self.assertEqual(studio.source, "local ready = true")

    def test_read_failure_is_not_treated_as_a_missing_script(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            studio = FakeStudio()
            orchestrator, store = self.make_system(folder, FakeBridge({}), studio)
            store.create_task("unreadable", "Create", TaskOptions())
            action = ProposalAction("multi_edit", {
                "file_path": "game.ServerScriptService.NewScript",
                "edits": [{"old_string": "", "new_string": "local ready = true"}],
            })
            with patch.object(studio, "call_tool", return_value=MCPToolResult("script_read", "Connection unavailable", True, ("text",))):
                with self.assertRaisesRegex(OrchestratorError, "Could not read back"):
                    orchestrator._bind_mutation_preconditions("unreadable", "studio-1", [action])

    def test_readback_rejects_unexpected_source_even_when_replacement_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            studio = FakeStudio()
            orchestrator, store = self.make_system(folder, FakeBridge({}), studio)
            store.create_task("corrupt", "Edit", TaskOptions())
            store.update_task("corrupt", stage=Stage.APPLYING, status="running")
            action = ProposalAction("multi_edit", {
                "file_path": "game.ServerScriptService.Main",
                "edits": [{"old_string": "local value = 1", "new_string": "local value = 2"}],
            })
            orchestrator._bind_mutation_preconditions("corrupt", "studio-1", [action])
            original_call = studio.call_tool

            def call(name: str, arguments: dict[str, Any], **kwargs: Any) -> MCPToolResult:
                result = original_call(name, arguments, **kwargs)
                if name == "multi_edit":
                    studio.source += "\nunexpected()"
                return result

            with patch.object(studio, "call_tool", side_effect=call):
                with self.assertRaisesRegex(OrchestratorError, "READ_BACK_MISMATCH"):
                    orchestrator._apply_actions("corrupt", "studio-1", [action])

    def make_system(
        self,
        folder: str,
        bridge: Any,
        studio: Any,
    ) -> tuple[ZenlessOrchestrator, SQLiteStore]:
        store = SQLiteStore(Path(folder) / "state.db")
        orchestrator = ZenlessOrchestrator(
            store=store,
            bridge=bridge,
            studio=studio,
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
        self.fail("Orchestrator did not finish within the timeout")

    def test_safe_auto_requires_low_review_and_action_risk(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            orchestrator, _ = self.make_system(folder, FakeBridge({}), FakeStudio())
            options = TaskOptions(create_3d_asset=False, approval_mode="safe_auto")
            action = ProposalAction(
                tool="multi_edit",
                arguments={
                    "file_path": "game.ServerScriptService.Main",
                    "edits": [{"old_string": "local value = 1", "new_string": "local value = 2"}],
                },
                risk="medium",
            )
            low_review = ReviewResult(verdict="approve", summary="ok", risk="low", confidence=0.95)
            high_review = ReviewResult(verdict="approve", summary="risk", risk="high", confidence=0.95)
            high_action = ProposalAction(
                tool="multi_edit",
                arguments=action.arguments,
                risk="high",
            )

            self.assertFalse(orchestrator._requires_change_approval(options, [action], low_review))
            self.assertTrue(orchestrator._requires_change_approval(options, [action], high_review))
            self.assertTrue(orchestrator._requires_change_approval(options, [high_action], low_review))

    def test_full_auto_preserves_policy_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            orchestrator, _ = self.make_system(folder, FakeBridge({}), FakeStudio())
            options = TaskOptions(create_3d_asset=False, require_approval=False, approval_mode="full_auto")
            dangerous = ProposalAction(
                tool="multi_edit",
                arguments={
                    "file_path": "game.ServerScriptService.Main",
                    "edits": [{"old_string": "workspace:Destroy()", "new_string": "local value = 2"}],
                },
                risk="critical",
            )
            self.assertFalse(orchestrator._requires_change_approval(options, [dangerous], None))
            from zenless.policy import validate_proposal
            self.assertTrue(validate_proposal([dangerous], set(orchestrator.studio.tools)))

    def test_create_review_approve_apply_and_play_test(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = FakeBridge({"chatgpt": [proposal()], "deepseek": [review(), review()]})
            studio = FakeStudio([""])
            orchestrator, store = self.make_system(folder, bridge, studio)
            task_id = orchestrator.submit("Mude o script", TaskOptions(create_3d_asset=False))
            self.finish_with_gate_decisions(orchestrator, task_id, ["approve"])
            task = store.load_task(task_id)
            self.assertEqual(task["stage"], Stage.COMPLETE.value)
            self.assertTrue(task["final_review"])
            calls = [name for name, _ in studio.calls]
            self.assertIn("multi_edit", calls)
            self.assertEqual(
                [args["is_start"] for name, args in studio.calls if name == "start_stop_play"],
                [True, False],
            )
            self.assertTrue(list((Path(folder) / "runs" / task_id).glob("before-*.luau.txt")))
            self.assertEqual(len([provider for provider, _ in bridge.prompts if provider == "deepseek"]), 2)

    def test_mutation_precondition_blocks_changed_studio_source(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = FakeBridge({})
            studio = FakeStudio()
            orchestrator, store = self.make_system(folder, bridge, studio)
            task_id = "precondition"
            store.create_task(task_id, "Mude o script", TaskOptions())
            store.update_task(task_id, stage=Stage.APPLYING, status="running")
            action = ProposalAction(
                tool="multi_edit",
                arguments={
                    "file_path": "game.ServerScriptService.Main",
                    "edits": [{"old_string": "local value = 1", "new_string": "local value = 2"}],
                },
                reason="test",
            )
            orchestrator._bind_mutation_preconditions(task_id, "studio-1", [action])
            studio.source = "local value = 99"
            with self.assertRaisesRegex(OrchestratorError, "STUDIO_CHANGED"):
                orchestrator._apply_actions(task_id, "studio-1", [action])
            self.assertNotIn("multi_edit", [name for name, _ in studio.calls])
            operation = store.operations_for_resource(task_id)[0]
            self.assertEqual(operation["state"], "failed")

    def test_visual_generation_writes_six_distinct_pngs_and_runs_qa(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = FakeVisualBridge(
                {
                    "chatgpt": [
                        json.dumps(
                            {
                                "approved": True,
                                "failed_views": [],
                                "warnings": [],
                                "summary": "Seis vistas coerentes.",
                            }
                        )
                    ]
                }
            )
            studio = FakeStudio()
            orchestrator, store = self.make_system(folder, bridge, studio)
            task_id = "visual"
            store.create_task(task_id, "Create the object", TaskOptions(visual_first=True, create_3d_asset=False))
            store.update_task(task_id, stage=Stage.GENERATING_CONCEPT, status="running")
            visual = orchestrator._generate_visual_version(
                task_id,
                {"identity": "totem", "background": "neutral"},
                1,
                previous={},
                target_views=None,
            )
            qa = orchestrator._qa_visual_version(task_id, {"identity": "totem"}, 1, visual)
            self.assertTrue(qa["approved"])
            self.assertEqual(set(visual), {"front", "back", "left", "right", "top", "bottom"})
            self.assertEqual(len({item["sha256"] for item in visual.values()}), 6)
            self.assertEqual(len(store.assets(task_id)), 6)

    def test_hunyuan_refuses_to_run_without_an_approved_six_view_concept(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = FakeHunyuanBridge({})
            orchestrator, store = self.make_system(folder, bridge, FakeStudio())
            task_id = "requires-approved-visual"
            store.create_task(task_id, "Create the object", TaskOptions())
            with self.assertRaisesRegex(BridgeError, "approved visual version"):
                orchestrator._generate_hunyuan_model(task_id, "mesh", 1, "all")

    def test_rejected_change_never_reaches_multi_edit(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = FakeBridge({"chatgpt": [proposal()], "deepseek": [review()]})
            studio = FakeStudio()
            orchestrator, store = self.make_system(folder, bridge, studio)
            task_id = orchestrator.submit("Do not apply", TaskOptions(create_3d_asset=False))
            self.finish_with_gate_decisions(orchestrator, task_id, ["reject"])
            self.assertEqual(store.load_task(task_id)["stage"], Stage.BLOCKED.value)
            self.assertNotIn("multi_edit", [name for name, _ in studio.calls])

    def test_review_revision_and_repair_loop(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = FakeBridge(
                {
                    "chatgpt": [
                        proposal(),
                        proposal(replacement="local value = 3"),
                        proposal(replacement="local value = 4", original="local value = 3"),
                    ],
                    "deepseek": [review("revise"), review(), review(), review()],
                }
            )
            studio = FakeStudio(["Error: simulated failure", ""])
            orchestrator, store = self.make_system(folder, bridge, studio)
            task_id = orchestrator.submit("Fix and test", TaskOptions(create_3d_asset=False, max_revisions=2))
            self.finish_with_gate_decisions(orchestrator, task_id, ["approve", "approve"], timeout=18)
            self.assertEqual(store.load_task(task_id)["stage"], Stage.COMPLETE.value)
            calls = [name for name, _ in studio.calls]
            self.assertEqual(calls.count("multi_edit"), 2)
            self.assertEqual(calls.count("start_stop_play"), 4)
            self.assertEqual(len([provider for provider, _ in bridge.prompts if provider == "chatgpt"]), 3)

    def test_play_test_is_stopped_when_output_read_fails(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = FakeBridge({"chatgpt": [proposal()], "deepseek": [review(), review()]})
            studio = FakeStudio(fail_console=True)
            orchestrator, store = self.make_system(folder, bridge, studio)
            task_id = orchestrator.submit("Test safe failure", TaskOptions(create_3d_asset=False))
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
            task_id = orchestrator.submit("Read only", options)
            self.finish_with_gate_decisions(orchestrator, task_id, [])
            self.assertEqual(store.load_task(task_id)["stage"], Stage.COMPLETE.value)
            self.assertEqual([name for name, _ in studio.calls].count("script_search"), 1)

    def test_explicit_no_approval_option_does_not_pause(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bridge = FakeBridge({"chatgpt": [proposal()], "deepseek": [review(), review()]})
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
            first = orchestrator.submit("First job", TaskOptions(create_3d_asset=False))
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if store.load_task(first)["stage"] == Stage.WAITING_CHANGE_APPROVAL.value:
                    break
                time.sleep(0.02)
            with self.assertRaisesRegex(OrchestratorError, "task is already active"):
                orchestrator.submit("Second job", TaskOptions(create_3d_asset=False))
            self.assertTrue(orchestrator.approve_active(first, ("changes:",), "reject"))
            self.assertTrue(orchestrator.wait_for_idle(5))
            self.assertEqual(store.load_task(first)["stage"], Stage.BLOCKED.value)


if __name__ == "__main__":
    unittest.main()
