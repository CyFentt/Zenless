from __future__ import annotations

import json
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from zenless.models import ProposalAction, Stage, TaskOptions
from zenless.orchestrator import OrchestratorError, ZenlessOrchestrator
from zenless.store import SQLiteStore
from zenless.studio_mcp import MCPError, StudioMCPClient, find_studio_mcp


def _summary(text: str, limit: int = 600) -> str:
    clean = text.strip()
    return clean if len(clean) <= limit else clean[:limit] + "...[truncated]"


def main() -> int:
    report: dict[str, Any] = {
        "status": "failed",
        "play_started": False,
        "play_stopped": False,
    }
    client = StudioMCPClient(find_studio_mcp())
    target = None
    started = False
    probe_name = f"ZenlessValidation_{uuid.uuid4().hex}"
    probe_created = False

    try:
        client.start()
        studios = client.list_studios()
        if not studios:
            raise MCPError("No Roblox Studio instance is connected to StudioMCP.")

        target = studios[0]
        report["studio"] = target.label
        report["studio_id"] = target.studio_id

        before = client.call_tool(
            "get_studio_state",
            {},
            studio_id=target.studio_id,
            timeout=30,
        )
        report["state_before"] = _summary(before.text)
        if before.is_error:
            raise MCPError(before.text)
        if "Current Studio Mode: Edit" not in before.text:
            report["status"] = "skipped_not_edit"
            raise MCPError("Studio must be in Edit mode before validation")

        tree = client.call_tool(
            "search_game_tree",
            {
                "datamodel_type": "Edit",
                "path": "Workspace",
                "max_depth": 1,
                "head_limit": 20,
            },
            studio_id=target.studio_id,
            timeout=45,
        )
        report["tree_read_ok"] = not tree.is_error
        report["tree_excerpt"] = _summary(tree.text)
        if tree.is_error:
            raise MCPError(tree.text)

        created = client.call_tool("execute_luau", {
            "datamodel_type": "Edit",
            "code": f'local parent = game:GetService("ServerScriptService"); assert(not parent:FindFirstChild("{probe_name}")); local probe = Instance.new("ModuleScript"); probe.Name = "{probe_name}"; probe.Source = "return 1"; probe.Parent = parent; return probe:GetFullName()',
        }, studio_id=target.studio_id, timeout=30)
        if created.is_error:
            raise MCPError(created.text)
        probe_created = True
        path = f"game.ServerScriptService.{probe_name}"
        inspected = client.call_tool("inspect_instance", {"path": path}, studio_id=target.studio_id, timeout=30)
        if inspected.is_error:
            raise MCPError(inspected.text)
        report["property_read"] = "PASS"
        with tempfile.TemporaryDirectory(prefix="zenless-studio-validation-") as folder:
            root = Path(folder)
            store = SQLiteStore(root / "state.db")
            store.create_task("validation", "Verify controlled script mutation", TaskOptions())
            store.update_task("validation", stage=Stage.APPLYING, status="running")
            orchestrator = ZenlessOrchestrator(store=store, studio=client, bridge=None, run_root=root / "runs")
            action = ProposalAction("multi_edit", {"file_path": path, "edits": [{"old_string": "return 1", "new_string": "return 2"}]}, "Controlled validation")
            orchestrator._bind_mutation_preconditions("validation", target.studio_id, [action])
            evidence = orchestrator._apply_actions("validation", target.studio_id, [action])
            if not any(item.get("verified") for item in evidence):
                raise RuntimeError("Mutation read-back evidence is missing")
            repeated = orchestrator._apply_actions("validation", target.studio_id, [action])
            if repeated != evidence:
                raise RuntimeError("Idempotent replay changed mutation evidence")
            report["safe_mutation"] = "PASS"
            report["read_back"] = "PASS"
            report["idempotent_replay"] = "PASS"
            stale = ProposalAction("multi_edit", {"file_path": path, "edits": [{"old_string": "return 2", "new_string": "return 3"}]}, "Precondition validation")
            orchestrator._bind_mutation_preconditions("validation", target.studio_id, [stale])
            changed = client.call_tool("multi_edit", {"datamodel_type": "Edit", "file_path": path, "edits": [{"old_string": "return 2", "new_string": "return 4"}]}, studio_id=target.studio_id, timeout=30)
            if changed.is_error:
                raise MCPError(changed.text)
            try:
                orchestrator._apply_actions("validation", target.studio_id, [stale])
            except OrchestratorError as error:
                if "STUDIO_CHANGED" not in str(error):
                    raise
            else:
                raise RuntimeError("A stale mutation precondition was accepted")
            report["changed_precondition_blocked"] = "PASS"

        start = client.call_tool(
            "start_stop_play",
            {"is_start": True},
            studio_id=target.studio_id,
            timeout=60,
        )
        if start.is_error:
            raise MCPError(start.text)
        started = True
        report["play_started"] = True

        time.sleep(2.0)
        during = client.call_tool(
            "get_studio_state",
            {},
            studio_id=target.studio_id,
            timeout=30,
        )
        report["state_during"] = _summary(during.text)
        if during.is_error:
            raise MCPError(during.text)
        if "Current Studio Mode: Play" not in during.text:
            raise MCPError("Studio did not enter Play")
        if "user_keyboard_input" in client.tools:
            input_result = client.call_tool("user_keyboard_input", {
                "datamodel_type": "Client",
                "actions": [{"action": "keyPress", "key_code": "W"}],
            }, studio_id=target.studio_id, timeout=30)
            report["keyboard_input"] = "FAIL" if input_result.is_error else "PASS"
            if input_result.is_error:
                report["keyboard_error"] = _summary(input_result.text)
        else:
            report["keyboard_input"] = "CAPABILITY_UNAVAILABLE"
        report["device_emulation"] = "NOT_RUN"
        report["multiplayer"] = "NOT_RUN"

        output = client.call_tool(
            "get_console_output",
            {},
            studio_id=target.studio_id,
            timeout=45,
        )
        report["output_ok"] = not output.is_error
        report["output_excerpt"] = _summary(output.text)
        if output.is_error:
            raise MCPError(output.text)

        report["status"] = "passed"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["status"] = "failed"
    finally:
        if started and target is not None:
            try:
                stop = client.call_tool(
                    "start_stop_play",
                    {"is_start": False},
                    studio_id=target.studio_id,
                    timeout=60,
                )
                report["play_stopped"] = not stop.is_error
                if stop.is_error:
                    report["stop_error"] = _summary(stop.text)
                time.sleep(1.0)
                after = client.call_tool(
                    "get_studio_state",
                    {},
                    studio_id=target.studio_id,
                    timeout=30,
                )
                report["state_after"] = _summary(after.text)
                report["returned_to_edit"] = not after.is_error and "Current Studio Mode: Edit" in after.text
            except Exception as exc:
                report["stop_error"] = f"{type(exc).__name__}: {exc}"
        if probe_created and target is not None:
            try:
                cleanup = client.call_tool("execute_luau", {
                    "datamodel_type": "Edit",
                    "code": f'local parent = game:GetService("ServerScriptService"); local probe = parent:FindFirstChild("{probe_name}"); if probe then assert(probe:IsA("ModuleScript")); probe:Destroy() end; assert(not parent:FindFirstChild("{probe_name}")); return "CLEAN"',
                }, studio_id=target.studio_id, timeout=30)
                report["probe_removed"] = not cleanup.is_error
            except Exception as exc:
                report["cleanup_error"] = str(exc)
        if not report.get("returned_to_edit") or (probe_created and not report.get("probe_removed")):
            report["status"] = "failed"
        client.close()
        output = PROJECT_ROOT / "artifacts" / "final-validation" / "studio.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
