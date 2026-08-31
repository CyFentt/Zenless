from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable

from .studio_mcp import MCPError, StudioMCPClient, StudioTarget


class StudioReadiness(StrEnum):
    MCP_RUNTIME_AVAILABLE = "MCP_RUNTIME_AVAILABLE"
    MCP_CONNECTED = "MCP_CONNECTED"
    STUDIO_NOT_RUNNING = "STUDIO_NOT_RUNNING"
    STUDIO_INSTANCE_FOUND = "STUDIO_INSTANCE_FOUND"
    MULTIPLE_STUDIOS = "MULTIPLE_STUDIOS"
    PROJECT_SELECTED = "PROJECT_SELECTED"
    PROJECT_READY = "PROJECT_READY"
    MCP_SETUP_REQUIRED = "MCP_SETUP_REQUIRED"
    MCP_RUNTIME_ERROR = "MCP_RUNTIME_ERROR"
    NO_PROJECT = "NO_PROJECT"


@dataclass(frozen=True, slots=True)
class StudioSelection:
    state: StudioReadiness
    studios: tuple[StudioTarget, ...]
    selected: StudioTarget | None
    detail: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "selectedStudioId": self.selected.studio_id if self.selected else None,
            "detail": self.detail,
            "studios": [
                {
                    "id": target.studio_id,
                    "label": target.label,
                    "placeId": target.raw.get("place_id") or target.raw.get("placeId"),
                    "universeId": target.raw.get("universe_id") or target.raw.get("universeId"),
                    "project": target.raw.get("project") or target.raw.get("place_name") or target.raw.get("placeName"),
                    "raw": dict(target.raw),
                }
                for target in self.studios
            ],
        }


class StudioCapabilityRegistry:
    _GROUPS = {
        "READ": ("get_", "read_", "inspect_"),
        "SEARCH": ("search_", "find_", "list_"),
        "VISUAL": ("screen", "screenshot", "capture"),
        "PLAYTEST": ("play", "test", "start_stop"),
        "INPUT": ("keyboard", "mouse", "input", "navigate"),
        "RUNTIME": ("execute", "runtime", "console"),
        "ASSET": ("asset", "mesh", "model", "image"),
        "MUTATION": ("edit", "write", "create", "delete", "insert", "set_", "multi_edit"),
        "ADMIN_PROJECT": ("project", "publish", "place", "studio"),
    }

    def __init__(self, client: StudioMCPClient) -> None:
        self.client = client

    def public(self) -> list[dict[str, Any]]:
        result = []
        for name, tool in sorted(self.client.tools.items()):
            result.append(
                {
                    "name": name,
                    "category": self.classify(name),
                    "description": tool.description,
                    "inputSchema": tool.input_schema,
                }
            )
        return result

    @classmethod
    def classify(cls, name: str) -> str:
        normalized = name.casefold()
        for group, markers in cls._GROUPS.items():
            if any(marker in normalized for marker in markers):
                return group
        return "READ"


class StudioDiscoveryManager:
    def __init__(
        self,
        client: StudioMCPClient,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        retry_delays: tuple[float, ...] = (0.0, 0.5, 1.0, 2.0, 4.0),
    ) -> None:
        self.client = client
        self.sleeper = sleeper
        self.retry_delays = retry_delays
        self._selection: StudioSelection | None = None

    @property
    def selection(self) -> StudioSelection | None:
        return self._selection

    def discover(
        self,
        *,
        preferred_studio_id: str = "",
        preferred_place_id: str = "",
        preferred_universe_id: str = "",
    ) -> StudioSelection:
        try:
            if not self.client.running:
                self.client.start()
        except MCPError as exc:
            self._selection = StudioSelection(StudioReadiness.MCP_RUNTIME_ERROR, (), None, str(exc))
            return self._selection
        studios: list[StudioTarget] = []
        last_error = ""
        for delay in self.retry_delays:
            if delay:
                self.sleeper(delay)
            try:
                studios = self.client.list_studios()
            except MCPError as exc:
                last_error = str(exc)
                continue
            if studios:
                break
        targets = tuple(studios)
        if not targets:
            state = (
                StudioReadiness.MCP_SETUP_REQUIRED
                if "list_roblox_studios" not in self.client.tools
                else StudioReadiness.STUDIO_NOT_RUNNING
            )
            self._selection = StudioSelection(state, (), None, last_error or "No Studio instance registered with MCP.")
            return self._selection
        selected = self._match(targets, preferred_studio_id, preferred_place_id, preferred_universe_id)
        if selected is None and len(targets) > 1:
            self._selection = StudioSelection(
                StudioReadiness.MULTIPLE_STUDIOS,
                targets,
                None,
                "Select the Studio project that this job may access.",
            )
            return self._selection
        selected = selected or next(iter(targets), None)
        if selected is None:
            self._selection = StudioSelection(StudioReadiness.STUDIO_NOT_RUNNING, (), None)
            return self._selection
        self._selection = StudioSelection(StudioReadiness.PROJECT_READY, targets, selected)
        return self._selection

    def select(self, studio_id: str) -> StudioSelection:
        current = self._selection
        if current is None:
            raise MCPError("Studio discovery has not run.")
        selected = next((target for target in current.studios if target.studio_id == studio_id), None)
        if selected is None:
            raise MCPError("The selected Studio instance is unavailable.")
        self._selection = StudioSelection(StudioReadiness.PROJECT_READY, current.studios, selected)
        return self._selection

    @staticmethod
    def _match(
        targets: tuple[StudioTarget, ...],
        studio_id: str,
        place_id: str,
        universe_id: str,
    ) -> StudioTarget | None:
        if studio_id:
            match = next((target for target in targets if target.studio_id == studio_id), None)
            if match:
                return match
        for key, value in (("place", place_id), ("universe", universe_id)):
            if not value:
                continue
            keys = (f"{key}_id", f"{key}Id")
            matches = [target for target in targets if any(str(target.raw.get(name) or "") == value for name in keys)]
            if len(matches) == 1:
                return matches[0]
        return targets[0] if len(targets) == 1 else None
