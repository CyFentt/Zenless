from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from .event_bus import EventBus
from .orchestrator import AgentTransport, OrchestratorError, TaskCancelled
from .protocol import ProtocolError, extract_json_object
from .store import SQLiteStore
from .studio_mcp import MCPError, MCPToolResult, StudioMCPClient, validate_json_schema

MULTIPLAYER_HARNESS_PROTOCOL = "ZENLESS_QA_MULTIPLAYER_V1"
MAX_STUDIO_TEST_CLIENTS = 8
DEVICE_TEST_WIDTH = 390
DEVICE_TEST_HEIGHT = 844

VIRTUAL_INPUT_SMOKE_LUA = r'''
local HttpService = game:GetService("HttpService")
local UserInputService = game:GetService("UserInputService")

local created, virtualInput = pcall(function()
    return UserInputService:CreateVirtualInput()
end)
if not created then
    return HttpService:JSONEncode({ ok = false, stage = "create", error = tostring(virtualInput) })
end

local sent, sendError = pcall(function()
    virtualInput:SendKey(true, Enum.KeyCode.Unknown, false)
    virtualInput:SendKey(false, Enum.KeyCode.Unknown, false)
end)
return HttpService:JSONEncode({
    ok = sent,
    stage = "send",
    error = sent and "" or tostring(sendError),
    probe = "Unknown key down/up",
})
'''

DEVICE_EMULATOR_BEGIN_LUA = rf'''
local HttpService = game:GetService("HttpService")
local Simulator = game:GetService("StudioDeviceSimulatorService")

local function enumName(value)
    return tostring(value):match("([^%.]+)$") or ""
end

local originalOk, original = pcall(function()
    local resolution = Simulator:GetResolutionAsync()
    return {{
        device = Simulator:GetDeviceAsync(),
        width = resolution.X,
        height = resolution.Y,
        orientation = enumName(Simulator:GetOrientationAsync()),
        density = Simulator:GetPixelDensityAsync(),
        scaling = enumName(Simulator:GetScalingModeAsync()),
    }}
end)
if not originalOk then
    return HttpService:JSONEncode({{ ok = false, stage = "read-original", error = tostring(original) }})
end

local originalIsRestorable = type(original.device) == "string"
    and #original.device > 0
    and #original.device <= 512
    and type(original.width) == "number"
    and original.width >= 64
    and original.width <= 16384
    and type(original.height) == "number"
    and original.height >= 64
    and original.height <= 16384
    and type(original.density) == "number"
    and original.density > 0
    and original.density <= 5000
    and original.orientation:match("^[%a_][%w_]*$") ~= nil
    and original.scaling:match("^[%a_][%w_]*$") ~= nil
if not originalIsRestorable then
    return HttpService:JSONEncode({{ ok = false, stage = "validate-original", error = "unsafe state" }})
end

local function restoreOriginal()
    if original.device == "default" then
        Simulator:StopSimulationAsync()
        return
    end
    Simulator:SetDeviceAsync(original.device)
    Simulator:SetResolutionAsync(original.width, original.height)
    Simulator:SetPixelDensityAsync(original.density)
    local orientation = Enum.ScreenOrientation[original.orientation]
    local scaling = Enum.DeviceSimulatorScalingMode[original.scaling]
    if orientation then
        Simulator:SetOrientationAsync(orientation)
    end
    if scaling then
        Simulator:SetScalingModeAsync(scaling)
    end
end

local applied, applyError = pcall(function()
    Simulator:SetResolutionAsync({DEVICE_TEST_WIDTH}, {DEVICE_TEST_HEIGHT})
    Simulator:SetOrientationAsync(Enum.ScreenOrientation.Portrait)
end)
if not applied then
    pcall(restoreOriginal)
    return HttpService:JSONEncode({{
        ok = false,
        stage = "apply",
        error = tostring(applyError),
        original = original,
    }})
end

local readBackOk, readBack = pcall(function()
    local resolution = Simulator:GetResolutionAsync()
    return {{
        width = resolution.X,
        height = resolution.Y,
        orientation = enumName(Simulator:GetOrientationAsync()),
    }}
end)
return HttpService:JSONEncode({{
    ok = readBackOk,
    stage = "read-back",
    error = readBackOk and "" or tostring(readBack),
    original = original,
    readBack = readBackOk and readBack or nil,
}})
'''


@dataclass(frozen=True, slots=True)
class TestProfile:
    name: str
    max_duration: float
    max_scenarios: int
    max_clients: int
    max_chaos_iterations: int


PROFILES = {
    "SMOKE": TestProfile("SMOKE", 45.0, 4, 1, 0),
    "STANDARD": TestProfile("STANDARD", 120.0, 10, 2, 2),
    "DEEP": TestProfile("DEEP", 240.0, 18, 4, 5),
}


@dataclass(slots=True)
class TestPlan:
    profile: str
    feature: str
    changed_tools: list[str]
    risk_areas: list[str]
    scenarios: list[str]
    seed: int


@dataclass(slots=True)
class TestFailure:
    id: str
    test_case_id: str
    job_id: str
    scenario: str
    severity: str
    expected: str
    actual: str
    studio_mode: str = ""
    players: int = 1
    seed: int = 0
    script: str = ""
    line: int = 0
    stack: str = ""
    related_mutation: str = ""
    reproduction: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    probable_area: str = ""
    status: str = "OPEN"


class QABreaker:
    """Bounded, change-aware QA runner. It never mutates production code."""

    ERROR_PATTERN = re.compile(
        r"(?im)(\bexception\b|\btraceback\b|stack begin|(^|\s)error[:\s]|infinite yield possible)"
    )

    def __init__(
        self,
        *,
        store: SQLiteStore,
        studio: StudioMCPClient,
        bridge: AgentTransport,
        events: EventBus,
        play_test_seconds: float = 6.0,
    ) -> None:
        self.store = store
        self.studio = studio
        self.bridge = bridge
        self.events = events
        self.play_test_seconds = max(1.0, min(20.0, play_test_seconds))
        self._run_lock = threading.Lock()
        self._manual_lock = threading.Lock()
        self._manual_threads: dict[str, threading.Thread] = {}
        self._manual_cancel: dict[str, threading.Event] = {}

    def select_profile(self, job_id: str, evidence: list[dict[str, Any]]) -> TestProfile:
        task = self.store.load_task(job_id) or {}
        prompt = str(task.get("prompt", "")).casefold()
        risk = str((task.get("options") or {}).get("risk_level", "medium")).casefold()
        tools = {str(item.get("tool", "")).casefold() for item in evidence}
        deep_terms = ("datastore", "persist", "currency", "remoteevent", "multiplayer", "ragdoll", "physics")
        smoke_terms = ("textlabel", "texto", "cor ", "label", "tooltip")
        if risk == "high" or any(term in prompt for term in deep_terms) or any("remote" in tool for tool in tools):
            return PROFILES["DEEP"]
        if risk == "low" and len(evidence) <= 2 and any(term in prompt for term in smoke_terms):
            return PROFILES["SMOKE"]
        return PROFILES["STANDARD"]

    def run_for_orchestrator(
        self,
        job_id: str,
        studio_id: str,
        cancel_event: threading.Event,
        evidence: list[dict[str, Any]],
        rerun: bool,
    ) -> str:
        profile = self.select_profile(job_id, evidence)
        return self.run(
            job_id,
            studio_id=studio_id,
            profile_name=profile.name,
            evidence=evidence,
            cancel_event=cancel_event,
            rerun=rerun,
        )

    def start_manual(self, job_id: str, profile_name: str = "STANDARD") -> bool:
        profile = profile_name.upper()
        if profile not in PROFILES:
            raise ValueError("Perfil QA inválido.")
        with self._manual_lock:
            running = self._manual_threads.get(job_id)
            if running is not None and running.is_alive():
                return False
            cancel = threading.Event()
            thread = threading.Thread(
                target=self._manual_worker,
                args=(job_id, profile, cancel),
                name=f"Zenless-QA-{job_id[:8]}",
                daemon=True,
            )
            self._manual_cancel[job_id] = cancel
            self._manual_threads[job_id] = thread
            thread.start()
        return True

    def stop(self, job_id: str) -> bool:
        with self._manual_lock:
            cancel = self._manual_cancel.get(job_id)
        if cancel is None:
            return False
        cancel.set()
        return True

    def running(self, job_id: str) -> bool:
        with self._manual_lock:
            thread = self._manual_threads.get(job_id)
        return thread is not None and thread.is_alive()

    def run(
        self,
        job_id: str,
        *,
        studio_id: str,
        profile_name: str,
        evidence: list[dict[str, Any]],
        cancel_event: threading.Event,
        rerun: bool = False,
    ) -> str:
        profile = PROFILES.get(profile_name.upper(), PROFILES["STANDARD"])
        with self._run_lock:
            run_id = uuid.uuid4().hex
            seed = int.from_bytes(hashlib.sha256(f"{job_id}:{run_id}".encode()).digest()[:4], "big")
            plan = self._make_plan(job_id, profile, evidence, seed, rerun)
            self.store.create_test_run(run_id, job_id, profile.name, seed)
            self.events.publish("TEST_STARTED", {"jobId": job_id})
            started_at = time.monotonic()
            failures: list[TestFailure] = []
            logs: list[str] = []
            outcomes: list[str] = []
            try:
                self._check_cancel(cancel_event)
                outcomes.append(
                    self._run_case(
                        run_id,
                        job_id,
                        "mutation-evidence",
                        "Mutation evidence integrity",
                        "SAFETY",
                        lambda: self._check_evidence(evidence),
                        failures,
                        logs,
                        seed,
                        skip_is_ok=not evidence,
                    )
                )
                self._enforce_bound(started_at, profile, cancel_event)

                outcomes.append(
                    self._run_case(
                        run_id,
                        job_id,
                        "studio-edit-mode",
                        "Studio starts in Edit mode",
                        "STUDIO",
                        lambda: self._check_edit_mode(studio_id),
                        failures,
                        logs,
                        seed,
                    )
                )
                self._enforce_bound(started_at, profile, cancel_event)

                output, play_outcome = self._run_play_case(
                    run_id,
                    job_id,
                    studio_id,
                    profile,
                    cancel_event,
                    failures,
                    logs,
                    seed,
                )
                outcomes.append(play_outcome)
                self._enforce_bound(started_at, profile, cancel_event)

                if profile.name in {"STANDARD", "DEEP"}:
                    outcomes.append(
                        self._run_case(
                            run_id,
                            job_id,
                            "virtual-input-smoke",
                            "VirtualInput bounded transport smoke",
                            "VIRTUAL_INPUT",
                            lambda: self._run_virtual_input_smoke(studio_id),
                            failures,
                            logs,
                            seed,
                            skip_is_ok=True,
                        )
                    )
                    self._enforce_bound(started_at, profile, cancel_event)

                if profile.name == "DEEP":
                    outcomes.append(
                        self._run_case(
                            run_id,
                            job_id,
                            "device-emulator-smoke",
                            "Device emulator read-back and capture smoke",
                            "DEVICE",
                            lambda: self._run_device_emulator_smoke(studio_id, seed),
                            failures,
                            logs,
                            seed,
                            skip_is_ok=True,
                        )
                    )
                    self._enforce_bound(started_at, profile, cancel_event)

                    outcomes.append(
                        self._run_case(
                            run_id,
                            job_id,
                            "multiplayer-studiotest",
                            "StudioTestService opt-in multiplayer harness",
                            "MULTIPLAYER",
                            lambda: self._run_multiplayer_test(studio_id, profile, seed),
                            failures,
                            logs,
                            seed,
                            skip_is_ok=True,
                        )
                    )
                    self._enforce_bound(started_at, profile, cancel_event)

                review = self._review_results(job_id, plan, failures, output, rerun)
                if review:
                    logs.append(review)
                passed = not failures
                summary = {
                    "profile": profile.name,
                    "seed": seed,
                    "planned": len(plan.scenarios),
                    "completed": len(outcomes),
                    "passedCases": outcomes.count("PASSED"),
                    "skippedCases": outcomes.count("SKIPPED"),
                    "failedCases": outcomes.count("FAILED"),
                    "failures": len(failures),
                    "durationMs": int((time.monotonic() - started_at) * 1000),
                    "plan": asdict(plan),
                    "review": review,
                }
                self.store.finish_test_run(run_id, "PASSED" if passed else "FAILED", summary)
                self.events.publish("TEST_FINISHED", {"passed": passed, "jobId": job_id})
                joined = "\n".join(logs)[-20_000:]
                if failures:
                    return "ERROR: QA Breaker encontrou falhas.\n" + joined
                return joined or "QA Breaker concluído sem erros detectados."
            except TaskCancelled:
                self.store.finish_test_run(run_id, "CANCELLED", {"profile": profile.name, "seed": seed})
                self.events.publish("TEST_FINISHED", {"passed": False, "jobId": job_id})
                raise
            except Exception as exc:
                self.store.finish_test_run(
                    run_id,
                    "FAILED",
                    {"profile": profile.name, "seed": seed, "error": str(exc)},
                )
                self.events.publish("TEST_FINISHED", {"passed": False, "jobId": job_id})
                raise

    def _manual_worker(self, job_id: str, profile: str, cancel: threading.Event) -> None:
        try:
            if not self.studio.running:
                self.studio.start()
            studios = self.studio.list_studios()
            if not studios:
                raise MCPError("Nenhum Roblox Studio conectado ao StudioMCP.")
            self.run(
                job_id,
                studio_id=studios[0].studio_id,
                profile_name=profile,
                evidence=[],
                cancel_event=cancel,
            )
        except Exception as exc:
            self._log(job_id, "ERR", f"QA manual falhou: {exc}")
            self.events.publish("TEST_FINISHED", {"passed": False, "jobId": job_id})
        finally:
            with self._manual_lock:
                self._manual_threads.pop(job_id, None)
                self._manual_cancel.pop(job_id, None)

    def _make_plan(
        self,
        job_id: str,
        profile: TestProfile,
        evidence: list[dict[str, Any]],
        seed: int,
        rerun: bool,
    ) -> TestPlan:
        task = self.store.load_task(job_id) or {}
        feature = str(task.get("prompt", ""))[:500]
        changed_tools = sorted({str(item.get("tool", "")) for item in evidence if item.get("tool")})
        risk_areas = ["mutation read-back", "Studio lifecycle", "runtime output"]
        if any("remote" in value.casefold() for value in changed_tools) or "remote" in feature.casefold():
            risk_areas.extend(["server authority", "replication", "duplicate requests"])
        if any(term in feature.casefold() for term in ("ui", "hud", "gui", "button")):
            risk_areas.append("UI reopen and rapid interaction")
        if rerun:
            risk_areas.append("regression after an applied fix")
        scenarios = [
            "Validate approved mutation evidence",
            "Confirm Studio starts in Edit mode",
            "Start Play, collect Output, Stop, and reject runtime errors",
        ]
        if profile.name in {"STANDARD", "DEEP"}:
            scenarios.append("Execute a bounded no-op VirtualInput transport smoke in Client mode")
        if profile.name == "DEEP":
            scenarios.extend(
                [
                    "Apply and read back a temporary device profile, capture it, then restore Studio",
                    "Run the opt-in StudioTestService multiplayer harness when its exact protocol marker exists",
                ]
            )
        return TestPlan(
            profile=profile.name,
            feature=feature,
            changed_tools=changed_tools,
            risk_areas=risk_areas,
            scenarios=scenarios[: profile.max_scenarios],
            seed=seed,
        )

    def _ai_scenarios(
        self,
        job_id: str,
        feature: str,
        changed_tools: list[str],
        risks: list[str],
    ) -> list[str]:
        if not self.bridge.wait_for_provider("chatgpt", timeout=0.5):
            return []
        prompt = (
            "Você é o planejador QA do próprio projeto Roblox do usuário. "
            "Gere até 4 cenários legítimos e determinísticos; não gere exploit nem código. "
            "Responda somente JSON {\"scenarios\":[\"...\"]}.\n"
            f"Objetivo: {feature}\nMudanças: {changed_tools}\nRiscos: {risks}"
        )
        try:
            raw = self.bridge.send_prompt("chatgpt", prompt, task_id=job_id, timeout=120)
            payload = extract_json_object(raw)
        except (MCPError, OrchestratorError, ProtocolError, RuntimeError, ValueError):
            return []
        scenarios = payload.get("scenarios", [])
        return [str(item).strip()[:300] for item in scenarios if str(item).strip()][:4]

    def _review_results(
        self,
        job_id: str,
        plan: TestPlan,
        failures: list[TestFailure],
        output: str,
        rerun: bool,
    ) -> str:
        if rerun or not self.bridge.wait_for_provider("deepseek", timeout=0.5):
            return ""
        payload = {
            "plan": asdict(plan),
            "failures": [asdict(item) for item in failures],
            "output_tail": output[-5000:],
        }
        prompt = (
            "Revise independentemente este resultado de QA do projeto Roblox do usuário. "
            "Não proponha exploit nem execute alterações. Responda em no máximo 6 linhas com "
            "veredito, risco e lacunas de teste.\n" + json.dumps(payload, ensure_ascii=False)
        )
        try:
            return self.bridge.send_prompt("deepseek", prompt, task_id=job_id, timeout=120).strip()[:3000]
        except RuntimeError:
            return ""

    def _run_play_case(
        self,
        run_id: str,
        job_id: str,
        studio_id: str,
        profile: TestProfile,
        cancel_event: threading.Event,
        failures: list[TestFailure],
        logs: list[str],
        seed: int,
    ) -> tuple[str, str]:
        output_holder = {"text": ""}

        def play() -> tuple[str, str, str]:
            if "start_stop_play" not in self.studio.tools:
                return "SKIPPED", "StudioMCP does not expose start_stop_play", ""
            started = False
            try:
                result = self.studio.call_tool(
                    "start_stop_play", {"is_start": True}, studio_id=studio_id, timeout=60
                )
                if result.is_error:
                    return "FAILED", "Play Test starts", result.compact(3000)
                started = True
                deadline = time.monotonic() + min(self.play_test_seconds, profile.max_duration / 3)
                while time.monotonic() < deadline:
                    self._check_cancel(cancel_event)
                    cancel_event.wait(0.1)
                if "get_console_output" in self.studio.tools:
                    console = self.studio.call_tool(
                        "get_console_output", {}, studio_id=studio_id, timeout=60
                    )
                    if console.is_error:
                        return "FAILED", "Output can be read", console.compact(3000)
                    output_holder["text"] = console.text
                if self.ERROR_PATTERN.search(output_holder["text"]):
                    return "FAILED", "No runtime errors", output_holder["text"][-6000:]
                return "PASSED", "No runtime errors", output_holder["text"][-6000:]
            finally:
                if started:
                    stopped = self.studio.call_tool(
                        "start_stop_play", {"is_start": False}, studio_id=studio_id, timeout=60
                    )
                    if stopped.is_error:
                        raise MCPError("Studio recusou Stop: " + stopped.compact(3000))

        outcome = self._run_case(
            run_id,
            job_id,
            "studio-play-output",
            "Studio Play Test and Output",
            "PLAY",
            play,
            failures,
            logs,
            seed,
        )
        return output_holder["text"], outcome

    def _run_case(
        self,
        run_id: str,
        job_id: str,
        case_suffix: str,
        name: str,
        suite: str,
        callback: Any,
        failures: list[TestFailure],
        logs: list[str],
        seed: int,
        *,
        skip_is_ok: bool = False,
    ) -> str:
        case_id = f"{run_id[:10]}-{case_suffix}"
        started_ms = int(time.time() * 1000)
        self.events.publish(
            "TEST_CASE_STARTED",
            {
                "jobId": job_id,
                "testCase": {
                    "id": case_id,
                    "name": name,
                    "suite": suite,
                    "status": "RUNNING",
                    "startedAt": started_ms,
                },
            },
        )
        started = time.monotonic()
        try:
            status, expected, actual = callback()
        except Exception as exc:
            status, expected, actual = "FAILED", "Case completes without exception", str(exc)
        if status == "SKIPPED" and not skip_is_ok:
            status = "FAILED"
        duration_ms = int((time.monotonic() - started) * 1000)
        finished_ms = int(time.time() * 1000)
        case = {
            "id": case_id,
            "name": name,
            "suite": suite,
            "status": status,
            "startedAt": started_ms,
            "finishedAt": finished_ms,
            "durationMs": duration_ms,
        }
        severity = "MEDIUM" if status == "FAILED" else "LOW"
        details = {"expected": expected, "actual": actual, "seed": seed}
        self.store.append_test_case(
            case_id,
            run_id=run_id,
            job_id=job_id,
            name=name,
            status=status,
            severity=severity,
            details=details,
            duration_ms=duration_ms,
        )
        self.events.publish("TEST_CASE_FINISHED", {"jobId": job_id, "testCase": case})
        level = "ERR" if status == "FAILED" else ("WARN" if status == "SKIPPED" else "ZEN")
        self._log(job_id, level, f"{name}: {status} — {actual or expected}", case_id=case_id)
        logs.append(f"{level} {name}: {status} — {actual or expected}")
        if status == "FAILED":
            failure = TestFailure(
                id=uuid.uuid4().hex,
                test_case_id=case_id,
                job_id=job_id,
                scenario=name,
                severity=severity,
                expected=expected,
                actual=actual,
                seed=seed,
                reproduction=[f"Execute o perfil QA e reproduza: {name}"],
                evidence=[actual[-4000:]],
                probable_area=suite,
            )
            failures.append(failure)
            self.events.publish(
                "TEST_FAILURE",
                {
                    "jobId": job_id,
                    "failure": {
                        "id": failure.id,
                        "testCaseId": case_id,
                        "name": name,
                        "suite": suite,
                        "message": actual[:4000] or "Falha sem detalhe",
                        "timestamp": finished_ms,
                        "expected": expected,
                        "actual": actual,
                        "cause": failure.probable_area,
                        "recovery": "Corrigir pelo fluxo Builder -> Reviewer -> safety gate e repetir este caso.",
                    },
                },
            )
        return status

    def _check_evidence(self, evidence: list[dict[str, Any]]) -> tuple[str, str, str]:
        errors = [item for item in evidence if bool(item.get("is_error"))]
        if errors:
            return "FAILED", "All approved mutations succeed and are read back", json.dumps(errors)[:6000]
        mutations = [item for item in evidence if item.get("tool") not in {"script_read", "get_console_output"}]
        if not evidence:
            return "SKIPPED", "Mutation evidence exists", "No mutation evidence supplied"
        return "PASSED", "All approved mutations succeed", f"{len(mutations)} mutation records validated"

    def _check_edit_mode(self, studio_id: str) -> tuple[str, str, str]:
        if "get_studio_state" not in self.studio.tools:
            return "SKIPPED", "Studio mode is observable", "get_studio_state unavailable"
        result = self.studio.call_tool("get_studio_state", {}, studio_id=studio_id, timeout=30)
        if result.is_error:
            return "FAILED", "Studio mode can be read", result.compact(3000)
        edit = "current studio mode: edit" in result.text.casefold()
        return ("PASSED" if edit else "FAILED", "Studio is in Edit mode", result.compact(3000))

    def _run_virtual_input_smoke(self, studio_id: str) -> tuple[str, str, str]:
        expected = "Create VirtualInput and deliver a bounded no-op key transition in Client mode"
        if not self._tool_supports("start_stop_play", {"is_start"}):
            return "SKIPPED", expected, "start_stop_play is not exposed with its required schema"
        if not self._tool_supports("execute_luau", {"code", "datamodel_type"}, "Client"):
            return (
                "SKIPPED",
                expected,
                "execute_luau is unavailable for Client; VirtualInput execution was not simulated",
            )

        started = False
        outcome = ("FAILED", expected, "VirtualInput smoke did not complete")
        try:
            start = self._call_validated(
                "start_stop_play", {"is_start": True}, studio_id=studio_id, timeout=60
            )
            if start.is_error:
                return "FAILED", expected, "Play could not start: " + start.compact(3000)
            started = True
            time.sleep(0.4)
            result = self._call_validated(
                "execute_luau",
                {"code": VIRTUAL_INPUT_SMOKE_LUA, "datamodel_type": "Client"},
                studio_id=studio_id,
                timeout=30,
            )
            if result.is_error:
                outcome = ("FAILED", expected, result.compact(3000))
            else:
                payload = self._decode_tool_json(result)
                if payload.get("ok") is True and payload.get("probe") == "Unknown key down/up":
                    outcome = (
                        "PASSED",
                        expected,
                        "VirtualInput executed Unknown key down/up; no gameplay behavior was asserted",
                    )
                else:
                    outcome = ("FAILED", expected, json.dumps(payload, ensure_ascii=False)[:3000])
        except (MCPError, ProtocolError, ValueError) as exc:
            outcome = ("FAILED", expected, str(exc))
        finally:
            if started:
                try:
                    stop = self._call_validated(
                        "start_stop_play", {"is_start": False}, studio_id=studio_id, timeout=60
                    )
                    if stop.is_error:
                        outcome = ("FAILED", expected, "VirtualInput ran, but Stop failed: " + stop.compact(3000))
                except MCPError as exc:
                    outcome = ("FAILED", expected, f"VirtualInput ran, but Stop failed: {exc}")
        return outcome

    def _run_device_emulator_smoke(self, studio_id: str, seed: int) -> tuple[str, str, str]:
        expected = "Apply/read back a temporary phone viewport, capture it, and restore the original state"
        if not self._tool_supports("execute_luau", {"code", "datamodel_type"}, "Edit"):
            return (
                "SKIPPED",
                expected,
                "execute_luau is unavailable for Edit; device emulation was not simulated",
            )
        if not self._tool_supports("screen_capture", {"capture_id"}):
            return (
                "SKIPPED",
                expected,
                "screen_capture is unavailable; no device screenshot was claimed",
            )

        original: dict[str, Any] | None = None
        outcome = ("FAILED", expected, "Device emulator smoke did not complete")
        try:
            begin = self._call_validated(
                "execute_luau",
                {"code": DEVICE_EMULATOR_BEGIN_LUA, "datamodel_type": "Edit"},
                studio_id=studio_id,
                timeout=45,
            )
            if begin.is_error:
                outcome = ("FAILED", expected, begin.compact(3000))
            else:
                payload = self._decode_tool_json(begin)
                raw_original = payload.get("original")
                if isinstance(raw_original, dict):
                    original = self._validated_device_state(raw_original)
                if payload.get("ok") is not True:
                    outcome = ("FAILED", expected, json.dumps(payload, ensure_ascii=False)[:3000])
                elif original is None:
                    outcome = (
                        "FAILED",
                        expected,
                        "Studio returned an unsafe or incomplete original device state",
                    )
                else:
                    read_back = payload.get("readBack")
                    if not isinstance(read_back, dict):
                        outcome = ("FAILED", expected, "Device emulator returned no read-back state")
                    else:
                        width = self._bounded_number(read_back.get("width"), 64, 16384)
                        height = self._bounded_number(read_back.get("height"), 64, 16384)
                        orientation = str(read_back.get("orientation", ""))
                        if (
                            width != DEVICE_TEST_WIDTH
                            or height != DEVICE_TEST_HEIGHT
                            or orientation != "Portrait"
                        ):
                            outcome = (
                                "FAILED",
                                expected,
                                "Temporary device settings did not match their read-back",
                            )
                        else:
                            capture = self._call_validated(
                                "screen_capture",
                                {"capture_id": f"ZenlessQA_{seed:08x}"},
                                studio_id=studio_id,
                                timeout=45,
                            )
                            if capture.is_error:
                                outcome = ("FAILED", expected, capture.compact(3000))
                            elif "image" not in capture.content_types:
                                outcome = ("FAILED", expected, "screen_capture returned no image evidence")
                            else:
                                outcome = (
                                    "PASSED",
                                    expected,
                                    "390x844 Portrait applied/read back and an image was captured; "
                                    "pixels were not visually asserted",
                                )
        except (MCPError, ProtocolError, ValueError) as exc:
            outcome = ("FAILED", expected, str(exc))
        finally:
            if original is not None:
                try:
                    restore = self._call_validated(
                        "execute_luau",
                        {
                            "code": self._device_restore_lua(original),
                            "datamodel_type": "Edit",
                        },
                        studio_id=studio_id,
                        timeout=45,
                    )
                    restored = self._decode_tool_json(restore) if not restore.is_error else {}
                    if restore.is_error or restored.get("ok") is not True:
                        outcome = (
                            "FAILED",
                            expected,
                            "Device test ran, but restoring the original Studio state failed: "
                            + (restore.compact(2000) if restore.is_error else json.dumps(restored)[:2000]),
                        )
                    elif outcome[0] == "PASSED":
                        outcome = (
                            "PASSED",
                            expected,
                            outcome[2] + "; original device state restored",
                        )
                except (MCPError, ProtocolError, ValueError) as exc:
                    outcome = ("FAILED", expected, f"Device test ran, but restore failed: {exc}")
        return outcome

    def _run_multiplayer_test(
        self,
        studio_id: str,
        profile: TestProfile,
        seed: int,
    ) -> tuple[str, str, str]:
        expected = "Run a project-owned StudioTestService harness with a bounded client count"
        if not self._tool_supports("script_grep", {"query"}):
            return (
                "SKIPPED",
                expected,
                "script_grep is unavailable; Zenless did not guess whether a harness exists",
            )
        if not self._tool_supports("execute_luau", {"code", "datamodel_type"}, "Edit"):
            return (
                "SKIPPED",
                expected,
                "execute_luau is unavailable for Edit; multiplayer was not simulated",
            )
        if not self._tool_supports("start_stop_play", {"is_start"}):
            return (
                "SKIPPED",
                expected,
                "start_stop_play is unavailable, so Zenless cannot guarantee multiplayer cleanup",
            )

        launched = False
        outcome = ("FAILED", expected, "StudioTestService harness did not complete")
        try:
            discovery = self._call_validated(
                "script_grep",
                {"query": MULTIPLAYER_HARNESS_PROTOCOL},
                studio_id=studio_id,
                timeout=30,
            )
            if discovery.is_error:
                outcome = ("FAILED", expected, "Harness discovery failed: " + discovery.compact(3000))
            elif not self._has_multiplayer_harness_marker(discovery.text):
                outcome = (
                    "SKIPPED",
                    expected,
                    f"No explicit {MULTIPLAYER_HARNESS_PROTOCOL} script marker; no multiplayer test was launched",
                )
            else:
                players = max(1, min(MAX_STUDIO_TEST_CLIENTS, int(profile.max_clients)))
                bounded_seed = max(0, min(0xFFFFFFFF, int(seed)))
                code = self._multiplayer_test_lua(players, bounded_seed)
                launched = True
                result = self._call_validated(
                    "execute_luau",
                    {"code": code, "datamodel_type": "Edit"},
                    studio_id=studio_id,
                    timeout=max(30.0, min(120.0, profile.max_duration / 2)),
                )
                if result.is_error:
                    outcome = ("FAILED", expected, result.compact(3000))
                else:
                    payload = self._decode_tool_json(result)
                    if (
                        payload.get("ok") is True
                        and payload.get("protocol") == MULTIPLAYER_HARNESS_PROTOCOL
                        and payload.get("players") == players
                    ):
                        outcome = (
                            "PASSED",
                            expected,
                            f"StudioTestService harness returned its signed protocol result for {players} clients",
                        )
                    else:
                        outcome = ("FAILED", expected, json.dumps(payload, ensure_ascii=False)[:3000])
        except (MCPError, ProtocolError, ValueError) as exc:
            outcome = ("FAILED", expected, str(exc))
        finally:
            if launched and self._tool_supports("start_stop_play", {"is_start"}):
                try:
                    stopped = self._call_validated(
                        "start_stop_play", {"is_start": False}, studio_id=studio_id, timeout=60
                    )
                    if stopped.is_error:
                        outcome = (
                            "FAILED",
                            expected,
                            "Multiplayer harness returned, but cleanup failed: " + stopped.compact(2000),
                        )
                except MCPError as exc:
                    outcome = ("FAILED", expected, f"Multiplayer cleanup failed: {exc}")
        return outcome

    def _check_multiplayer_capability(self) -> tuple[str, str, str]:
        available = self._tool_supports("script_grep", {"query"}) and self._tool_supports(
            "execute_luau", {"code", "datamodel_type"}, "Edit"
        )
        if available:
            return (
                "SKIPPED",
                "A project-owned multiplayer harness explicitly opts into execution",
                "StudioTestService transport is available, but discovery alone is not a test pass",
            )
        return (
            "SKIPPED",
            "A project-owned multiplayer harness explicitly opts into execution",
            "Current StudioMCP cannot safely discover and invoke StudioTestService; support was not simulated",
        )

    def _call_validated(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        studio_id: str,
        timeout: float,
    ) -> MCPToolResult:
        if not isinstance(studio_id, str) or not studio_id.strip() or len(studio_id) > 256:
            raise MCPError("Studio id inválido para QA.")
        if not math.isfinite(timeout) or timeout < 1 or timeout > 180:
            raise MCPError("Timeout de ferramenta inválido para QA.")
        tool = self.studio.tools.get(name)
        schema = getattr(tool, "input_schema", None)
        if not isinstance(schema, dict):
            raise MCPError(f"{name} não anunciou um schema validável.")
        safe_arguments = dict(arguments)
        properties = schema.get("properties", {})
        if isinstance(properties, dict) and "studio_id" in properties:
            safe_arguments["studio_id"] = studio_id
        errors = validate_json_schema(safe_arguments, schema)
        if errors:
            raise MCPError(f"Argumentos QA inválidos para {name}: " + "; ".join(errors[:6]))
        return self.studio.call_tool(
            name,
            arguments,
            studio_id=studio_id,
            timeout=timeout,
        )

    def _tool_supports(
        self,
        name: str,
        required_properties: set[str],
        datamodel_type: str = "",
    ) -> bool:
        tool = self.studio.tools.get(name)
        schema = getattr(tool, "input_schema", None)
        if not isinstance(schema, dict):
            return False
        properties = schema.get("properties")
        if not isinstance(properties, dict) or not required_properties.issubset(properties):
            return False
        if not datamodel_type:
            return True
        model_schema = properties.get("datamodel_type")
        if not isinstance(model_schema, dict):
            return False
        accepted = model_schema.get("enum")
        return isinstance(accepted, list) and datamodel_type in accepted

    @staticmethod
    def _decode_tool_json(result: MCPToolResult) -> dict[str, Any]:
        if result.is_error:
            raise MCPError(result.compact(3000) or f"{result.tool_name} failed")
        payload = extract_json_object(result.text)
        if not isinstance(payload, dict):
            raise ProtocolError(f"{result.tool_name} returned a non-object payload")
        return payload

    @staticmethod
    def _bounded_number(value: Any, minimum: float, maximum: float) -> int | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < minimum or numeric > maximum:
            return None
        return int(numeric)

    @classmethod
    def _validated_device_state(cls, raw: dict[str, Any]) -> dict[str, Any] | None:
        device = raw.get("device")
        orientation = raw.get("orientation")
        scaling = raw.get("scaling")
        width = cls._bounded_number(raw.get("width"), 64, 16384)
        height = cls._bounded_number(raw.get("height"), 64, 16384)
        density = raw.get("density")
        if (
            not isinstance(device, str)
            or not 1 <= len(device) <= 512
            or not isinstance(orientation, str)
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", orientation) is None
            or not isinstance(scaling, str)
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", scaling) is None
            or width is None
            or height is None
            or isinstance(density, bool)
            or not isinstance(density, (int, float))
            or not math.isfinite(float(density))
            or not 0 < float(density) <= 5000
        ):
            return None
        return {
            "device": device,
            "width": width,
            "height": height,
            "orientation": orientation,
            "density": float(density),
            "scaling": scaling,
        }

    @staticmethod
    def _luau_bytes(value: str) -> str:
        encoded = value.encode("utf-8")
        return '"' + "".join(f"\\{byte:03d}" for byte in encoded) + '"'

    @classmethod
    def _device_restore_lua(cls, state: dict[str, Any]) -> str:
        device = cls._luau_bytes(str(state["device"]))
        orientation = cls._luau_bytes(str(state["orientation"]))
        scaling = cls._luau_bytes(str(state["scaling"]))
        width = int(state["width"])
        height = int(state["height"])
        density = float(state["density"])
        return f'''
local HttpService = game:GetService("HttpService")
local Simulator = game:GetService("StudioDeviceSimulatorService")
local ok, restoreError = pcall(function()
    local device = {device}
    if device == "default" then
        Simulator:StopSimulationAsync()
        return
    end
    Simulator:SetDeviceAsync(device)
    Simulator:SetResolutionAsync({width}, {height})
    Simulator:SetPixelDensityAsync({density!r})
    local orientation = Enum.ScreenOrientation[{orientation}]
    local scaling = Enum.DeviceSimulatorScalingMode[{scaling}]
    if orientation then
        Simulator:SetOrientationAsync(orientation)
    end
    if scaling then
        Simulator:SetScalingModeAsync(scaling)
    end
end)
return HttpService:JSONEncode({{ ok = ok, error = ok and "" or tostring(restoreError) }})
'''

    @staticmethod
    def _has_multiplayer_harness_marker(text: str) -> bool:
        normalized = text.casefold()
        no_match_terms = ("no match", "0 match", "not found", "nenhum resultado", "nenhuma correspondência")
        if any(term in normalized for term in no_match_terms):
            return False
        if MULTIPLAYER_HARNESS_PROTOCOL not in text:
            return False
        return re.search(
            r"(?i)(ServerScriptService|ReplicatedStorage|TestService|StarterPlayer)[.\\/]",
            text,
        ) is not None

    @staticmethod
    def _multiplayer_test_lua(players: int, seed: int) -> str:
        if not 1 <= players <= MAX_STUDIO_TEST_CLIENTS:
            raise ValueError("StudioTestService aceita de 1 a 8 clientes neste runner.")
        if not 0 <= seed <= 0xFFFFFFFF:
            raise ValueError("Seed de multiplayer fora do intervalo permitido.")
        return f'''
local HttpService = game:GetService("HttpService")
local StudioTestService = game:GetService("StudioTestService")
local protocol = "{MULTIPLAYER_HARNESS_PROTOCOL}"
local callOk, result = pcall(function()
    return StudioTestService:ExecuteMultiplayerTestAsync({players}, {{
        protocol = protocol,
        seed = {seed},
        expectedPlayers = {players},
    }})
end)
if not callOk then
    return HttpService:JSONEncode({{ ok = false, protocol = protocol, error = tostring(result) }})
end
local resultOk = typeof(result) == "table"
    and result.protocol == protocol
    and result.ok == true
    and result.players == {players}
return HttpService:JSONEncode({{
    ok = resultOk,
    protocol = protocol,
    players = typeof(result) == "table" and result.players or -1,
    detail = typeof(result) == "table" and tostring(result.detail or "") or tostring(result),
}})
'''

    def _log(self, job_id: str, level: str, message: str, *, case_id: str = "") -> None:
        self.events.publish(
            "TEST_LOG",
            {
                "log": {
                    "id": uuid.uuid4().hex,
                    "timestamp": int(time.time() * 1000),
                    "level": level,
                    "message": message[:6000],
                    "testCaseId": case_id or None,
                }
            },
        )

    @staticmethod
    def _check_cancel(cancel_event: threading.Event) -> None:
        if cancel_event.is_set():
            raise TaskCancelled("QA cancelado pelo usuário.")

    def _enforce_bound(
        self,
        started_at: float,
        profile: TestProfile,
        cancel_event: threading.Event,
    ) -> None:
        self._check_cancel(cancel_event)
        if time.monotonic() - started_at > profile.max_duration:
            raise OrchestratorError(f"QA excedeu o limite de {profile.max_duration:.0f}s do perfil {profile.name}.")
