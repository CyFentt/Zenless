from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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

    try:
        client.start()
        studios = client.list_studios()
        if not studios:
            raise MCPError("Nenhuma instância do Roblox Studio conectada ao StudioMCP.")

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
            return 2

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
        return 0
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        return 1
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
                report["returned_to_edit"] = (
                    not after.is_error and "Current Studio Mode: Edit" in after.text
                )
            except Exception as exc:
                report["stop_error"] = f"{type(exc).__name__}: {exc}"
        client.close()
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
