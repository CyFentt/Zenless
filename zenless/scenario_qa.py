from __future__ import annotations

import re
import threading
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from .studio_mcp import MCPError, StudioMCPClient


class ScenarioStepKind(StrEnum):
    START_PLAY = "START_PLAY"
    WAIT = "WAIT"
    MOVE_CHARACTER = "MOVE_CHARACTER"
    KEY_PRESS = "KEY_PRESS"
    MOUSE_CLICK = "MOUSE_CLICK"
    CALL_SAFE_TEST_HARNESS = "CALL_SAFE_TEST_HARNESS"
    ASSERT_PROPERTY = "ASSERT_PROPERTY"
    ASSERT_OUTPUT_NOT_CONTAINS_ERROR = "ASSERT_OUTPUT_NOT_CONTAINS_ERROR"
    CAPTURE_SCREEN = "CAPTURE_SCREEN"
    STOP_PLAY = "STOP_PLAY"


@dataclass(frozen=True, slots=True)
class ScenarioStep:
    kind: ScenarioStepKind
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CompiledScenario:
    id: str
    title: str
    steps: tuple[ScenarioStep, ...]

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "steps": [asdict(step) for step in self.steps]}


@dataclass(frozen=True, slots=True)
class ScenarioExecution:
    scenario_id: str
    status: str
    detail: str
    steps_completed: int


class ScenarioCompiler:
    def compile(self, scenarios: list[str], *, maximum: int) -> tuple[CompiledScenario, ...]:
        result = []
        seen = set()
        for index, raw in enumerate(scenarios[: max(0, min(20, maximum))]):
            title = " ".join(str(raw).split())[:300]
            key = title.casefold()
            if not title or key in seen:
                continue
            seen.add(key)
            steps = [
                ScenarioStep(ScenarioStepKind.START_PLAY, {}),
                ScenarioStep(ScenarioStepKind.WAIT, {"seconds": 0.4}),
            ]
            if any(marker in key for marker in ("move", "moving", "walk", "correr", "movimento")):
                steps.append(ScenarioStep(ScenarioStepKind.KEY_PRESS, {"key": "W", "duration": 0.15}))
            steps.append(ScenarioStep(ScenarioStepKind.ASSERT_OUTPUT_NOT_CONTAINS_ERROR, {}))
            if any(marker in key for marker in ("visual", "screen", "ui", "hud", "camera")):
                steps.append(ScenarioStep(ScenarioStepKind.CAPTURE_SCREEN, {"captureId": f"scenario-{index + 1}"}))
            steps.append(ScenarioStep(ScenarioStepKind.STOP_PLAY, {}))
            result.append(CompiledScenario(f"scenario-{index + 1}", title, tuple(steps)))
        return tuple(result)


class ScenarioExecutor:
    ERROR_PATTERN = re.compile(
        r"(?im)(\bexception\b|\btraceback\b|stack begin|(^|\s)error[:\s]|infinite yield possible)"
    )

    def __init__(self, studio: StudioMCPClient) -> None:
        self.studio = studio

    def execute(
        self,
        scenario: CompiledScenario,
        *,
        studio_id: str,
        cancel: threading.Event,
        deadline: float,
    ) -> ScenarioExecution:
        started = False
        completed = 0
        skipped = False
        details = []
        try:
            for step in scenario.steps:
                if cancel.is_set():
                    raise MCPError("Scenario execution cancelled.")
                if time.monotonic() >= deadline:
                    raise MCPError("Scenario execution exceeded its deadline.")
                status, detail = self._execute_step(step, studio_id, cancel)
                details.append(f"{step.kind.value}:{status}:{detail}")
                completed += 1
                if step.kind == ScenarioStepKind.START_PLAY and status == "SKIPPED":
                    return ScenarioExecution(scenario.id, "SKIPPED", " | ".join(details), completed)
                if step.kind == ScenarioStepKind.START_PLAY and status == "PASSED":
                    started = True
                if step.kind == ScenarioStepKind.STOP_PLAY and status == "PASSED":
                    started = False
                if status == "FAILED":
                    return ScenarioExecution(scenario.id, "FAILED", " | ".join(details)[-6000:], completed)
                if status == "SKIPPED":
                    skipped = True
            status = "SKIPPED" if skipped else "PASSED"
            return ScenarioExecution(scenario.id, status, " | ".join(details)[-6000:], completed)
        finally:
            if started and "start_stop_play" in self.studio.tools:
                self.studio.call_tool("start_stop_play", {"is_start": False}, studio_id=studio_id, timeout=60)

    def _execute_step(
        self,
        step: ScenarioStep,
        studio_id: str,
        cancel: threading.Event,
    ) -> tuple[str, str]:
        if step.kind == ScenarioStepKind.START_PLAY:
            return self._call("start_stop_play", {"is_start": True}, studio_id)
        if step.kind == ScenarioStepKind.STOP_PLAY:
            return self._call("start_stop_play", {"is_start": False}, studio_id)
        if step.kind == ScenarioStepKind.WAIT:
            seconds = max(0.0, min(10.0, float(step.arguments.get("seconds", 0.0))))
            cancel.wait(seconds)
            return "PASSED", f"waited {seconds:.2f}s"
        if step.kind == ScenarioStepKind.ASSERT_OUTPUT_NOT_CONTAINS_ERROR:
            status, detail = self._call("get_console_output", {}, studio_id)
            if status != "PASSED":
                return status, detail
            return ("FAILED", detail) if self.ERROR_PATTERN.search(detail) else ("PASSED", detail)
        if step.kind == ScenarioStepKind.CAPTURE_SCREEN:
            return self._call(
                "screen_capture", {"capture_id": str(step.arguments.get("captureId") or scenario_id())}, studio_id
            )
        if step.kind == ScenarioStepKind.KEY_PRESS:
            return "SKIPPED", "No compatible bounded keyboard schema was advertised."
        return "SKIPPED", "The discovered Studio tools do not map this bounded step."

    def _call(self, name: str, arguments: dict[str, Any], studio_id: str) -> tuple[str, str]:
        if name not in self.studio.tools:
            return "SKIPPED", f"{name} is unavailable."
        result = self.studio.call_tool(name, arguments, studio_id=studio_id, timeout=60)
        return ("FAILED" if result.is_error else "PASSED", result.compact(3000))


def scenario_id() -> str:
    return f"scenario-{int(time.time() * 1000)}"
