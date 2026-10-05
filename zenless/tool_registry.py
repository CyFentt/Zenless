from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ToolRegistry:
    _SOURCE_ROLES = {
        "zeroscript": "Web AI adapter reference",
        "robloxstudio-mcp": "Roblox Studio MCP bridge",
        "roblox-studio-mcp-native": "Roblox Studio MCP bridge alternative",
        "roblox-dev-skills": "Roblox UI, maps and 3D skills",
        "roblox-best-practices": "Roblox architecture and verification skills",
        "roblox-dev-skill": "Roblox engineering reference skill",
        "testez": "Luau test framework",
        "fusion": "Reactive Roblox UI library",
        "matter": "Roblox ECS",
        "zap": "Typed Roblox networking",
        "profile-store": "Persistent player data",
        "promise": "Promise abstraction",
        "blender-mcp": "Blender MCP asset pipeline",
        "code-search": "AST-aware semantic code index",
        "roblox-ai-studio": "Multi-agent Roblox architecture reference",
        "wally": "Roblox package manager",
        "run-in-roblox": "Roblox test runner",
        "remodel": "Roblox place/model transformation",
        "darklua": "Luau code transformation",
    }

    def __init__(self, portable_root: Path, resource_root: Path) -> None:
        self.portable_root = portable_root.resolve()
        self.resource_root = resource_root.resolve()
        self.manifest = json.loads((self.resource_root / "assets" / "toolchain.json").read_text(encoding="utf-8"))

    def descriptors(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in self.manifest.get("artifacts", []):
            target = self.portable_root / str(item.get("target") or "")
            marker = str(item.get("marker") or "")
            ready = self._ready(target, marker, str(item.get("kind") or ""))
            result.append(
                {
                    "id": str(item.get("id") or ""),
                    "name": str(item.get("name") or item.get("id") or ""),
                    "description": str(item.get("group") or "runtime").replace("-", " ").title(),
                    "status": "INSTALLED" if ready else "NOT_INSTALLED",
                    "category": "EXTERNAL",
                    "reason": "Pinned portable runtime dependency",
                }
            )
        for item in self.manifest.get("npm", []):
            marker = self.portable_root / "runtime" / "npm" / ".rubra-packages" / str(item.get("id") or "")
            result.append(
                {
                    "id": str(item.get("id") or ""),
                    "name": str(item.get("name") or item.get("package") or ""),
                    "description": str(item.get("package") or ""),
                    "status": "INSTALLED" if marker.is_file() else "NOT_INSTALLED",
                    "category": "MCP",
                    "reason": "Portable npm integration",
                }
            )
        for item in self.manifest.get("sources", []):
            source_id = str(item.get("id") or "")
            target = self.portable_root / str(item.get("target") or "")
            marker = target / ".rubra-source.json"
            result.append(
                {
                    "id": f"source:{source_id}",
                    "name": str(item.get("repo") or source_id),
                    "description": self._SOURCE_ROLES.get(source_id, "Pinned upstream source"),
                    "status": "INSTALLED" if marker.is_file() else "NOT_INSTALLED",
                    "category": "BUILT_IN",
                    "reason": f"Pinned to {str(item.get('commit') or '')[:12]}",
                }
            )
        try:
            outcomes = json.loads((self.portable_root / "runtime/toolchain-results.json").read_text(encoding="utf-8"))
            if not isinstance(outcomes, dict):
                outcomes = {}
        except (OSError, ValueError):
            outcomes = {}
        for descriptor in result:
            outcome = outcomes.get(descriptor["id"].removeprefix("source:"), {})
            if isinstance(outcome, dict) and descriptor["status"] != "INSTALLED":
                state = str(outcome.get("state") or "").casefold()
                if state == "failed":
                    descriptor["status"] = "FAILED"
                elif state in {"optional", "skipped"}:
                    descriptor["status"] = "OPTIONAL"
                if outcome.get("detail"):
                    descriptor["reason"] = str(outcome["detail"])
        return result

    def summary(self) -> dict[str, int]:
        items = self.descriptors()
        return {
            "total": len(items),
            "installed": sum(item["status"] == "INSTALLED" for item in items),
            "missing": sum(item["status"] != "INSTALLED" for item in items),
        }

    @staticmethod
    def _ready(target: Path, marker: str, kind: str) -> bool:
        if kind == "raw":
            return target.is_file()
        if not target.exists():
            return False
        return not marker or (target / marker).is_file() or next(target.rglob(marker), None) is not None
