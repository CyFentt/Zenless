from __future__ import annotations

import hashlib
import json
import re
import shutil
import struct
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from .brain import BrainAnalysis, ZenlessBrain
from .browser_bridge import BridgeError
from .glb_viewer import GLBError, load_glb
from .models import (
    TERMINAL_STAGES,
    AgentProposal,
    InvalidStageTransition,
    PipelineEvent,
    ProposalAction,
    ReviewResult,
    Stage,
    TaskOptions,
    validate_stage_transition,
)
from .policy import classify_action, is_read_only, validate_proposal
from .prompts import (
    final_review_prompt,
    principal_prompt,
    repair_prompt,
    research_prompt,
    review_prompt,
    revision_prompt,
    visual_master_prompt,
    visual_qa_prompt,
    visual_view_prompt,
)
from .protocol import ProtocolError, extract_json_object
from .skills import SkillLibrary
from .store import SQLiteStore, now_iso
from .studio_data import active_studio_title, export_sources, read_scene, read_sources, read_tree, script_source
from .studio_mcp import MCPError, StudioMCPClient, select_studio_target

EventCallback = Callable[[PipelineEvent], None]
QACallback = Callable[[str, str, threading.Event, list[dict[str, Any]], bool], str]
ProjectSearchCallback = Callable[[str], dict[str, Any]]
LocalAICallback = Callable[[str], str]


class AgentTransport(Protocol):
    def wait_for_provider(self, provider: str, timeout: float = 0.0) -> bool: ...

    def send_prompt(
        self,
        provider: str,
        prompt: str,
        *,
        task_id: str,
        timeout: float = 360.0,
        stream_callback: Callable[[str], None] | None = None,
    ) -> str: ...

    def request(
        self,
        provider: str,
        action: str,
        payload: dict[str, Any],
        *,
        task_id: str,
        timeout: float,
    ) -> dict[str, Any]: ...


class OrchestratorError(RuntimeError):
    pass


class TaskCancelled(OrchestratorError):
    pass


class TaskBlocked(OrchestratorError):
    pass


@dataclass(slots=True)
class _ApprovalGate:
    event: threading.Event = field(default_factory=threading.Event)
    decision: str = ""
    note: str = ""


class ZenlessOrchestrator:
    def __init__(
        self,
        *,
        store: SQLiteStore,
        bridge: AgentTransport,
        studio: StudioMCPClient,
        run_root: Path,
        event_callback: EventCallback | None = None,
        play_test_seconds: float = 5.0,
        brain: ZenlessBrain | None = None,
        qa_callback: QACallback | None = None,
        project_search_callback: ProjectSearchCallback | None = None,
        local_ai_callback: LocalAICallback | None = None,
        portable_root: Path | None = None,
    ) -> None:
        self.store = store
        self.bridge = bridge
        self.studio = studio
        self.run_root = run_root
        self.skills = SkillLibrary(portable_root or run_root.parent)
        self.event_callback = event_callback
        self.play_test_seconds = max(1.0, min(30.0, play_test_seconds))
        self.brain = brain or ZenlessBrain()
        self.qa_callback = qa_callback
        self.project_search_callback = project_search_callback
        self.local_ai_callback = local_ai_callback
        self._run_lock = threading.Lock()
        self._tasks: dict[str, threading.Thread] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._pause: dict[str, threading.Event] = {}
        self._paused_from: dict[str, Stage] = {}
        self._gates: dict[tuple[str, str], _ApprovalGate] = {}
        self._attachment_routes: set[tuple[str, str, str, str]] = set()
        self._state_lock = threading.RLock()
        self.current_task_id = ""

    def submit(
        self,
        prompt: str,
        options: TaskOptions,
        *,
        attachment_paths: tuple[Path, ...] = (),
        studio_id: str = "",
        parent_task_id: str = "",
        prepare_callback: Callable[[str, int], None] | None = None,
        ready_callback: Callable[[str, int], None] | None = None,
    ) -> str:
        objective = prompt.strip()
        if not objective:
            raise ValueError("The request is empty.")
        task_id = uuid.uuid4().hex
        cancel_event = threading.Event()
        pause_event = threading.Event()
        thread = threading.Thread(
            target=self._run_guarded,
            args=(task_id, objective, options, cancel_event, attachment_paths),
            name=f"Rubra-Task-{task_id[:8]}",
            daemon=True,
        )
        persisted = False
        with self._state_lock:
            if self._tasks:
                raise OrchestratorError(
                    "A task is already active. Complete, reject, or close the current stage before submitting another request."
                )
            try:
                history: list[dict[str, str]] = []
                if parent_task_id:
                    if self.store.load_task(parent_task_id) is None:
                        raise OrchestratorError(f"Parent task not found: {parent_task_id}")
                    for row in self.store.task_messages(parent_task_id)[-24:]:
                        history.append(
                            {
                                "sender": str(row.get("sender") or ""),
                                "role": str(row.get("role") or ""),
                                "content": str(row.get("content") or ""),
                            }
                        )
                self.store.create_task(task_id, objective, options)
                persisted = True
                updates: dict[str, Any] = {}
                if studio_id:
                    updates["studio_id"] = studio_id
                if parent_task_id:
                    updates["context_json"] = {
                        "parent_task_id": parent_task_id,
                        "conversation_history": [
                            {
                                "sender": item["sender"][:120],
                                "role": item["role"][:80],
                                "content": item["content"][:6000],
                            }
                            for item in history
                        ],
                    }
                if updates:
                    self.store.update_task(task_id, **updates)
                for item in history:
                    self.store.append_message(
                        task_id,
                        item["sender"] or "Previous",
                        item["role"] or "assistant",
                        item["content"],
                    )
                initial_message_id = self.store.append_message(task_id, "User", "user", objective)
                if prepare_callback is not None:
                    prepare_callback(task_id, initial_message_id)
                if ready_callback is not None:
                    ready_callback(task_id, initial_message_id)
                self._tasks[task_id] = thread
                self._cancel[task_id] = cancel_event
                self._pause[task_id] = pause_event
                self.current_task_id = task_id
                self._emit(task_id, Stage.NEW, "Request received and queued.")
                thread.start()
            except Exception as exc:
                self._tasks.pop(task_id, None)
                self._cancel.pop(task_id, None)
                self._pause.pop(task_id, None)
                if self.current_task_id == task_id:
                    self.current_task_id = ""
                rollback_error: Exception | None = None
                if persisted:
                    try:
                        self.store.delete_task(task_id)
                    except Exception as cleanup_exc:
                        rollback_error = cleanup_exc
                if rollback_error is not None:
                    raise RuntimeError(
                        f"Job preparation failed ({exc}); rollback also failed ({rollback_error}). "
                        f"Task {task_id} may require recovery on the next startup."
                    ) from exc
                raise
        return task_id

    def approve(self, task_id: str, gate: str, decision: str, note: str = "") -> bool:
        normalized = decision.strip().lower()
        if normalized not in {"approve", "reject", "edit"}:
            raise ValueError("Invalid approval decision.")
        with self._state_lock:
            target = self._gates.get((task_id, gate))
            if target is None or target.event.is_set():
                return False
            target.decision = normalized
            target.note = note.strip()
            self.store.record_approval(task_id, gate, normalized, target.note)
            target.event.set()
        return True

    def approve_active(self, task_id: str, prefixes: tuple[str, ...], decision: str, note: str = "") -> bool:
        with self._state_lock:
            names = [gate for owner, gate in self._gates if owner == task_id and gate.startswith(prefixes)]
        if not names:
            return False
        return self.approve(task_id, names[-1], decision, note)

    def cancel(self, task_id: str) -> bool:
        with self._state_lock:
            event = self._cancel.get(task_id)
        if event is None:
            return False
        event.set()
        with self._state_lock:
            pause_event = self._pause.get(task_id)
        if pause_event is not None:
            pause_event.clear()
        return True

    def pause(self, task_id: str) -> bool:
        with self._state_lock:
            pause_event = self._pause.get(task_id)
            task = self.store.load_task(task_id)
            if pause_event is None or task is None:
                return False
            current = Stage(str(task["stage"]))
            if current in TERMINAL_STAGES or current == Stage.PAUSED:
                return False
            self._paused_from[task_id] = current
            pause_event.set()
        self._emit(task_id, Stage.PAUSED, "Task paused at a safe checkpoint.", "warning")
        return True

    def resume(self, task_id: str) -> bool:
        with self._state_lock:
            pause_event = self._pause.get(task_id)
            previous = self._paused_from.pop(task_id, None)
            if pause_event is None or previous is None:
                return False
            pause_event.clear()
        self._emit(task_id, previous, "Task resumed.")
        return True

    def active_task(self) -> dict[str, Any] | None:
        task_id = self.current_task_id
        return self.store.load_task(task_id) if task_id else None

    @property
    def busy(self) -> bool:
        with self._state_lock:
            return bool(self._tasks)

    def wait_for_idle(self, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            with self._state_lock:
                threads = list(self._tasks.values())
            if not threads:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            if threads[0].is_alive():
                threads[0].join(timeout=min(0.1, remaining))
            else:
                time.sleep(min(0.01, remaining))

    def _send_agent_prompt(
        self,
        provider: str,
        prompt: str,
        *,
        task_id: str,
        timeout: float = 360.0,
        attachment_paths: tuple[Path, ...] = (),
    ) -> str:
        message_id = uuid.uuid4().hex
        task = self.store.load_task(task_id) or {}
        stored_options = task.get("options") if isinstance(task.get("options"), dict) else {}
        smart_routing = bool(stored_options.get("smart_routing", True))
        try:
            stage = Stage(str(task.get("stage") or Stage.PLANNING.value))
        except ValueError:
            stage = Stage.PLANNING
        streamed = False
        effective_prompt = prompt

        def publish(kind: str, detail: str = "") -> None:
            if self.event_callback is None:
                return
            self.event_callback(
                PipelineEvent(
                    task_id=task_id,
                    stage=stage,
                    message=message_id,
                    kind=kind,
                    detail=detail,
                    created_at=now_iso(),
                )
            )

        def on_delta(delta: str) -> None:
            nonlocal streamed
            value = str(delta)
            if value:
                streamed = True
                publish("stream_delta", value)

        def send(target: str) -> str:
            if attachment_paths:
                self._ensure_provider_attachments(target, task_id, attachment_paths)
            try:
                return self.bridge.send_prompt(
                    target,
                    effective_prompt,
                    task_id=task_id,
                    timeout=timeout,
                    stream_callback=on_delta,
                )
            except TypeError as exc:
                if "stream_callback" not in str(exc):
                    raise
                return self.bridge.send_prompt(target, effective_prompt, task_id=task_id, timeout=timeout)

        publish("stream_start", provider)
        try:
            try:
                return send(provider)
            except BridgeError as primary_error:
                if not streamed and self._provider_input_limit_error(primary_error):
                    compacted = self._compact_provider_prompt(prompt)
                    if compacted != prompt:
                        effective_prompt = compacted
                        self._emit(
                            task_id,
                            stage,
                            "Provider rejected the context size; retrying once with deterministic context compaction.",
                            "warning",
                            f"Prompt reduced from {len(prompt)} to {len(compacted)} characters.",
                        )
                        try:
                            return send(provider)
                        except BridgeError as compacted_error:
                            if streamed:
                                raise
                            primary_error = compacted_error
                if (
                    provider not in {"chatgpt", "deepseek"}
                    or not smart_routing
                    or streamed
                    or not self._recoverable_provider_error(primary_error)
                ):
                    raise

                role = "Builder" if provider == "chatgpt" else "Reviewer"
                fallback_errors = [str(primary_error)]
                current_transport = ""
                status_fn = getattr(self.bridge, "provider_status", None)
                if callable(status_fn):
                    try:
                        status = status_fn().get(provider, {})
                        if isinstance(status, dict):
                            current_transport = str(status.get("transport") or "").casefold()
                    except Exception:
                        current_transport = ""

                prefer_local = getattr(self.bridge, "prefer_local", None)
                primary_is_local = current_transport == "local" or str(primary_error).casefold().startswith("local ")
                if not primary_is_local and callable(prefer_local):
                    try:
                        local_selected = bool(prefer_local(provider))
                    except Exception as exc:
                        local_selected = False
                        fallback_errors.append(f"local-route: {exc}")
                    if local_selected:
                        self._emit(
                            task_id,
                            stage,
                            f"{role} web route is unavailable; Smart Routing handed the role to the local model.",
                            "warning",
                            str(primary_error)[:1000],
                        )
                        publish("stream_start", f"local-{provider}")
                        try:
                            return send(provider)
                        except BridgeError as local_error:
                            if streamed:
                                raise
                            fallback_errors.append(str(local_error))
                            self._emit(
                                task_id,
                                stage,
                                f"Local {role.lower()} failed before producing output; trying the next independent route.",
                                "warning",
                                str(local_error)[:1000],
                            )

                if self.bridge.wait_for_provider("gemini", timeout=0.75):
                    self._emit(
                        task_id,
                        stage,
                        f"{role} route failed; Smart Routing handed the role to Gemini.",
                        "warning",
                        " | ".join(fallback_errors)[-1800:],
                    )
                    publish("stream_start", "gemini")
                    result = send("gemini")
                    if provider == "chatgpt":
                        self._set_builder_provider(task_id, "gemini")
                    return result
                raise BridgeError(
                    f"Smart Routing exhausted available {role.lower()} routes: "
                    + " | ".join(fallback_errors)[-3000:]
                ) from primary_error
        finally:
            publish("stream_finish", provider)

    @staticmethod
    def _provider_input_limit_error(error: BaseException) -> bool:
        message = str(error).casefold()
        return any(
            marker in message
            for marker in (
                "provider_input_limit",
                "capability_unavailable",
                "message is too long",
                "prompt is too long",
                "input is too long",
                "context length",
                "context window",
                "maximum context",
                "max context",
                "too many tokens",
                "token limit",
            )
        )

    @staticmethod
    def _compact_provider_prompt(prompt: str) -> str:
        if len(prompt) <= 16_000:
            return prompt
        target = min(48_000, max(16_000, len(prompt) // 2))
        if len(prompt) <= target:
            return prompt
        digest = hashlib.sha256(prompt.encode("utf-8", "replace")).hexdigest()
        marker = (
            "\n\n[RUBRA CONTEXT COMPACTED "
            f"original_chars={len(prompt)} sha256={digest}; "
            "middle context omitted after the provider rejected the original input size]\n\n"
        )
        budget = max(2, target - len(marker))
        head = max(1, budget * 7 // 10)
        tail = max(1, budget - head)
        return prompt[:head] + marker + prompt[-tail:]

    @staticmethod
    def _recoverable_provider_error(error: BaseException) -> bool:
        message = str(error).casefold()
        return any(
            marker in message
            for marker in (
                "provider_rate_limit",
                "provider_capacity",
                "provider_transient_error",
                "provider_circuit_open",
                "provider_input_limit",
                "rate limit",
                "too many requests",
                "reached your limit",
                "usage limit",
                "quota exceeded",
                "server is busy",
                "servers are busy",
                "high traffic",
                "overloaded",
                "response timeout",
                "timed out waiting for a complete response",
                "local builder failed",
                "local reviewer failed",
                "local ai is unavailable",
                "local model request failed",
                "local model returned empty output",
                "local output is still truncated",
                "local completion exceeded",
            )
        )

    def _run_guarded(
        self,
        task_id: str,
        objective: str,
        options: TaskOptions,
        cancel_event: threading.Event,
        attachment_paths: tuple[Path, ...],
    ) -> None:
        try:
            with self._run_lock:
                self._run(task_id, objective, options, cancel_event, attachment_paths)
        except TaskCancelled as exc:
            self._finish_error(task_id, Stage.BLOCKED, str(exc))
        except TaskBlocked as exc:
            self._finish_error(task_id, Stage.BLOCKED, str(exc))
        except BridgeError as exc:
            self._finish_error(task_id, Stage.BLOCKED, str(exc))
        except (MCPError, ProtocolError, OrchestratorError) as exc:
            self._finish_error(task_id, Stage.FAILED, str(exc))
        except Exception as exc:
            self._finish_error(task_id, Stage.FAILED, f"Controlled internal failure: {exc}")
        finally:
            release_route = getattr(self.bridge, "release_task_route", None)
            if callable(release_route):
                release_route(task_id)
            with self._state_lock:
                self._tasks.pop(task_id, None)
                self._cancel.pop(task_id, None)
                self._pause.pop(task_id, None)
                self._paused_from.pop(task_id, None)
                if self.current_task_id == task_id:
                    self.current_task_id = ""
                stale = [key for key in self._gates if key[0] == task_id]
                for key in stale:
                    self._gates.pop(key, None)
                self._attachment_routes = {
                    key for key in self._attachment_routes if key[0] != task_id
                }

    def _run(
        self,
        task_id: str,
        objective: str,
        options: TaskOptions,
        cancel_event: threading.Event,
        attachment_paths: tuple[Path, ...],
    ) -> None:
        self._check_control(task_id, cancel_event)
        builder_provider = self._select_builder_provider(options, timeout=2.0)
        if not builder_provider:
            raise BridgeError("Builder requires ChatGPT, Gemini, or an available local text model.")
        required: list[tuple[str, str]] = []
        if options.independent_review and not options.smart_routing:
            required.append(("deepseek", "Reviewer"))
        if options.create_3d_asset:
            required.append(("hunyuan", "3D Generator"))
        for provider, label in required:
            if not self._provider_ready(provider, timeout=2, options=options):
                raise BridgeError(f"{label} requires login.")
        self._emit(task_id, Stage.COLLECTING_CONTEXT, "Reading the active Studio project.")
        if not self.studio.running:
            self.studio.start()
        studios = self.studio.list_studios()
        task = self.store.load_task(task_id) or {}
        seed_context = task.get("context") if isinstance(task.get("context"), dict) else {}
        target = select_studio_target(studios, str(task.get("studio_id") or ""), active_title=active_studio_title())
        self.store.update_task(task_id, studio_id=target.studio_id)
        analysis = self.brain.analyze(
            objective,
            independent_review=options.independent_review,
            create_3d=options.create_3d_asset,
        )
        context = self._collect_context(task_id, target.studio_id, analysis)
        context["builder_provider"] = builder_provider
        if attachment_paths:
            context["attachment_paths"] = [str(path.resolve()) for path in attachment_paths]
        if isinstance(seed_context, dict):
            history = seed_context.get("conversation_history")
            if isinstance(history, list) and history:
                context["conversation_history"] = history[-24:]
            parent_task_id = str(seed_context.get("parent_task_id") or "")
            if parent_task_id:
                context["parent_task_id"] = parent_task_id
        research_enabled = self._should_research(options, analysis)
        skill_selection = self.skills.select(objective)
        if skill_selection.text:
            context["rubra_skills"] = skill_selection.text
            context["rubra_skill_sources"] = list(skill_selection.names)
            self._emit(
                task_id,
                Stage.COLLECTING_CONTEXT,
                f"Loaded {len(skill_selection.names)} Roblox skill references.",
                detail=", ".join(skill_selection.names),
            )
        if self.project_search_callback is not None:
            try:
                indexed = self.project_search_callback(objective)
                if indexed.get("available") and indexed.get("result"):
                    context["semantic_project_index"] = str(indexed["result"])[:30000]
                    context["semantic_project_root"] = str(indexed.get("projectRoot") or "")
                    metadata = indexed.get("metadata")
                    if isinstance(metadata, dict):
                        context["semantic_project_metadata"] = {
                            str(key): str(value)[:16000] for key, value in metadata.items()
                        }
            except Exception as exc:
                context["semantic_project_index_unavailable"] = str(exc)
        local_research_available = False
        if research_enabled and self.local_ai_callback is not None:
            local_prompt = (
                "Analyze this Roblox Studio task as a local scout before the stronger web agents run. "
                "Identify likely architecture boundaries, risk areas, files or DataModel scopes to inspect, "
                "and concrete verification targets. Do not write implementation code.\n\n"
                f"OBJECTIVE:\n{objective}\n\n"
                f"BRAIN:\n{json.dumps(context.get('brain', {}), ensure_ascii=False)}\n\n"
                f"INDEX EVIDENCE:\n{str(context.get('semantic_project_index', ''))[:12000]}"
            )
            try:
                local_note = self.local_ai_callback(local_prompt)
                if local_note:
                    context["local_scout"] = local_note[:16000]
                    local_research_available = True
            except Exception as exc:
                context["local_scout_unavailable"] = str(exc)
        if research_enabled:
            if self.bridge.wait_for_provider("gemini", timeout=0.5):
                self._emit(task_id, Stage.COLLECTING_CONTEXT, "Gemini is performing an independent research pass.")
                try:
                    research = self._send_agent_prompt(
                        "gemini",
                        research_prompt(objective, context),
                        task_id=task_id,
                        timeout=240,
                    )
                    context["gemini_research"] = research[:30000]
                    self.store.append_message(task_id, "Gemini", "researcher", research)
                except BridgeError as exc:
                    context["gemini_research_unavailable"] = str(exc)
                    if local_research_available:
                        self._emit(
                            task_id,
                            Stage.COLLECTING_CONTEXT,
                            "Gemini research failed; continuing with the local research scout.",
                            "warning",
                            str(exc)[:1000],
                        )
                    elif options.research_mode == "on":
                        raise
            elif local_research_available:
                self._emit(
                    task_id,
                    Stage.COLLECTING_CONTEXT,
                    "Gemini is unavailable; Research is continuing with the local scout.",
                    "warning",
                )
            elif options.research_mode == "on":
                raise BridgeError("Research is enabled, but neither Gemini nor the local research scout is available.")
        self.store.update_task(task_id, context_json=context)

        builder_provider = self._builder_provider(task_id)
        if not self._provider_ready(builder_provider, timeout=2, options=options):
            replacement = self._select_builder_provider(options, timeout=2.0)
            if not replacement:
                raise BridgeError("Builder requires ChatGPT, Gemini, or an available local text model.")
            builder_provider = replacement
            self._set_builder_provider(task_id, builder_provider)
            context["builder_provider"] = builder_provider
        if attachment_paths:
            self._emit(task_id, Stage.COLLECTING_CONTEXT, "Uploading validated attachments to the active Builder route.")
            try:
                self._ensure_provider_attachments(builder_provider, task_id, attachment_paths)
            except BridgeError as primary_error:
                if (
                    builder_provider == "chatgpt"
                    and options.smart_routing
                    and self.bridge.wait_for_provider("gemini", timeout=0.75)
                ):
                    self._ensure_provider_attachments("gemini", task_id, attachment_paths)
                    builder_provider = "gemini"
                    self._set_builder_provider(task_id, builder_provider)
                    context["builder_provider"] = builder_provider
                    self._emit(
                        task_id,
                        Stage.COLLECTING_CONTEXT,
                        "The original Builder route could not carry every attachment; Gemini took over the Builder role.",
                        "warning",
                        str(primary_error)[:1000],
                    )
                else:
                    raise

        proposal, evidence = self._build_proposal(
            task_id,
            objective,
            context,
            target.studio_id,
            cancel_event,
            options,
            analysis,
        )
        proposal, review = self._review_and_revise(
            task_id,
            objective,
            context,
            proposal,
            evidence,
            options,
            cancel_event,
        )
        self.store.update_task(
            task_id,
            proposal_json=proposal.to_dict(),
            review_json=review.to_dict() if review else {},
        )

        self._handle_visual_and_3d(task_id, objective, proposal, options, cancel_event)

        mutating = [action for action in proposal.actions if not is_read_only(action.tool)]
        if not mutating:
            if options.automatic_play_test and any(intent in analysis.intents for intent in ("audit", "debug", "test")):
                self._emit(task_id, Stage.TESTING, "Testing the existing game without persistent changes.")
                output = self._run_quality_test(task_id, target.studio_id, cancel_event, [], False)
                self.store.append_message(task_id, "Studio", "test", output)
                if self._console_has_errors(output):
                    raise TaskBlocked("The existing-game review found test failures. " + output[-6000:])
            final_text = proposal.final_message or proposal.summary or "No persistent changes were required."
            self.store.append_message(task_id, "Builder", "assistant", final_text)
            self.store.update_task(task_id, final_text=final_text)
            self._emit(task_id, Stage.COMPLETE, "Completed without persistent changes.", "success")
            return
        self._bind_mutation_preconditions(task_id, target.studio_id, mutating)
        self.store.update_task(task_id, proposal_json=proposal.to_dict())

        if self._requires_change_approval(options, mutating, review):
            gate_round = 0
            while True:
                gate_round += 1
                gate_name = f"changes:{gate_round}"
                detail = self._proposal_detail(proposal, review)
                decision, note = self._wait_gate(
                    task_id,
                    gate_name,
                    Stage.WAITING_CHANGE_APPROVAL,
                    "Changes are ready and awaiting approval before reaching Studio.",
                    detail,
                    cancel_event,
                )
                if decision == "reject":
                    raise TaskBlocked("Changes were rejected by the user." + (f" {note}" if note else ""))
                if decision == "edit":
                    self._emit(task_id, Stage.REVISING, "Builder is revising the proposal from your feedback.")
                    proposal = self._request_revision(task_id, objective, context, proposal, review, note)
                    proposal, review = self._review_and_revise(
                        task_id,
                        objective,
                        context,
                        proposal,
                        evidence,
                        options,
                        cancel_event,
                        initial_review=False,
                    )
                    self.store.update_task(
                        task_id,
                        proposal_json=proposal.to_dict(),
                        review_json=review.to_dict() if review else {},
                    )
                    mutating = [action for action in proposal.actions if not is_read_only(action.tool)]
                    if not mutating:
                        self._emit(task_id, Stage.COMPLETE, "The revision found that no write was required.", "success")
                        return
                    self._bind_mutation_preconditions(task_id, target.studio_id, mutating)
                    self.store.update_task(task_id, proposal_json=proposal.to_dict())
                    continue
                break
        else:
            self._record_auto_approval(task_id, "changes:auto", self._effective_approval_mode(options))

        self._emit(task_id, Stage.APPLYING, "Applying the approved changes through the Studio bridge.")
        apply_evidence = self._apply_actions(task_id, target.studio_id, mutating)

        console_output = "[Automatic QA disabled by the user.]"
        if options.automatic_play_test:
            console_output = self._run_quality_test(task_id, target.studio_id, cancel_event, apply_evidence, False)
            fix_count = 0
            fix_limit = options.max_test_fixes if options.continuous_verification else 1
            while self._console_has_errors(console_output):
                if not options.auto_fix_errors or fix_count >= fix_limit:
                    raise OrchestratorError(
                        "The play test returned errors and reached the correction limit.\n" + console_output[-6000:]
                    )
                fix_count += 1
                self._emit(
                    task_id,
                    Stage.REPAIRING,
                    f"Builder is preparing correction {fix_count} from the actual output.",
                    "warning",
                )
                repair = self._request_repair(task_id, objective, proposal, console_output, apply_evidence)
                repair, repair_review = self._review_and_revise(
                    task_id,
                    objective,
                    context,
                    repair,
                    apply_evidence,
                    options,
                    cancel_event,
                )
                self.store.update_task(
                    task_id,
                    proposal_json=repair.to_dict(),
                    review_json=repair_review.to_dict() if repair_review else {},
                )
                repair_actions = [action for action in repair.actions if not is_read_only(action.tool)]
                if self._requires_change_approval(options, repair_actions, repair_review):
                    decision, note = self._wait_gate(
                        task_id,
                        f"repair:{fix_count}",
                        Stage.WAITING_CHANGE_APPROVAL,
                        f"Correction {fix_count} is ready and awaiting approval.",
                        self._proposal_detail(repair, repair_review),
                        cancel_event,
                    )
                    if decision != "approve":
                        raise TaskBlocked("The correction was not approved." + (f" {note}" if note else ""))
                else:
                    self._record_auto_approval(
                        task_id, f"repair:{fix_count}:auto", self._effective_approval_mode(options)
                    )
                self._bind_mutation_preconditions(task_id, target.studio_id, repair_actions)
                apply_evidence.extend(self._apply_actions(task_id, target.studio_id, repair_actions))
                proposal = repair
                console_output = self._run_quality_test(task_id, target.studio_id, cancel_event, apply_evidence, True)

        proposal, apply_evidence, console_output = self._final_review_and_repair(
            task_id,
            objective,
            context,
            proposal,
            apply_evidence,
            console_output,
            options,
            cancel_event,
            target.studio_id,
        )
        final_text = proposal.final_message or proposal.summary or "Changes applied and verified."
        self.store.append_message(task_id, "Orchestrator", "assistant", final_text)
        self.store.update_task(task_id, final_text=final_text)
        self._emit(task_id, Stage.COMPLETE, "Implementation completed and released.", "success")

    def _collect_context(self, task_id: str, studio_id: str, analysis: BrainAnalysis) -> dict[str, Any]:
        calls: list[tuple[str, dict[str, Any]]] = [
            ("get_studio_state", {}),
            ("get_console_output", {}),
        ]
        context: dict[str, Any] = {
            "studio_id": studio_id,
            "captured_at": now_iso(),
            "brain": analysis.to_dict(),
            "reads": {},
        }
        try:
            snapshot = read_tree(self.studio, studio_id)
            folder = self.run_root / task_id
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "studio-inventory.json").write_text(
                json.dumps(snapshot.instances, ensure_ascii=False), encoding="utf-8"
            )
            counts: dict[str, int] = {}
            scripts: list[dict[str, Any]] = []
            for item in snapshot.instances:
                class_name = str(item.get("className") or item.get("class_name") or item.get("ClassName") or "Instance")
                counts[class_name] = counts.get(class_name, 0) + 1
                if class_name in {"Script", "LocalScript", "ModuleScript"}:
                    scripts.append(item)
            context["inventory"] = {
                "total": snapshot.total,
                "indexed": len(snapshot.instances),
                "complete": snapshot.complete,
                "classes": counts,
                "scripts": [
                    {key: item.get(key) for key in ("path", "className", "name")}
                    for item in scripts[:64]
                ],
                "script_count": len(scripts),
                "source": snapshot.source,
            }
            context["reads"]["search_game_tree:inventory"] = json.dumps(snapshot.instances[:100], ensure_ascii=False)
            source_snapshot = read_sources(self.studio, studio_id, snapshot)
            source_root = folder / "studio-project"
            source_manifest = export_sources(source_root, studio_id, source_snapshot)
            context["studio_project_root"] = str(source_root)
            context["studio_source_snapshot"] = True
            ranked = sorted(
                source_snapshot.scripts,
                key=lambda item: -sum(word in str(item.get("path", "")).casefold() for word in analysis.keywords),
            )
            sources: dict[str, str] = {}
            budget = 22000
            for item in ranked[:24]:
                if budget <= 0:
                    break
                excerpt = (
                    ("READ_UNAVAILABLE: " + item["readError"])
                    if item.get("readError")
                    else item["source"][: min(4000, budget)]
                )
                sources[item["path"]] = excerpt
                budget -= len(excerpt)
            context["script_sources"] = sources
            context["source_coverage"] = {
                "exported": source_manifest["readable"],
                "total_scripts": source_snapshot.total,
                "complete": source_snapshot.complete,
                "errors": source_manifest["errors"],
                "prompt_excerpts": len(sources),
                "additional_reads": "Full source is exported for static checks. Prompt sources are excerpts; use script_read before each change.",
            }
            self.store.update_task(task_id, context_json=context)
            roots = self.store.get_setting("studio.projectRoots", {})
            if not isinstance(roots, dict):
                roots = {}
            roots[studio_id] = str(source_root)
            self.store.set_setting("studio.projectRoots", roots)
            self._emit(
                task_id,
                Stage.COLLECTING_CONTEXT,
                f"Indexed {len(snapshot.instances)} objects and exported {source_manifest['readable']} scripts for checks.",
                "success",
            )
        except MCPError as exc:
            context["inventory_unavailable"] = str(exc)
        for tool_name, arguments in calls:
            if tool_name not in self.studio.tools:
                continue
            try:
                result = self.studio.call_tool(tool_name, arguments, studio_id=studio_id, timeout=30)
            except MCPError as exc:
                context["reads"][tool_name] = "READ_UNAVAILABLE: " + str(exc)
                continue
            context["reads"][tool_name + f":{len(context['reads'])}"] = result.compact(28_000)
            self._emit(task_id, Stage.COLLECTING_CONTEXT, f"Context collected: {tool_name}.", "warning" if result.is_error else "success")
        context["tool_count"] = len(self.studio.tools)
        return self.brain.compact_context(context)

    def _build_proposal(
        self,
        task_id: str,
        objective: str,
        context: dict[str, Any],
        studio_id: str,
        cancel_event: threading.Event,
        options: TaskOptions,
        analysis: BrainAnalysis,
    ) -> tuple[AgentProposal, list[dict[str, Any]]]:
        tools = self._tool_catalog()
        evidence: list[dict[str, Any]] = []
        seen_reads: set[str] = set()
        proposal: AgentProposal | None = None
        total_rounds = self._builder_rounds(options, analysis)
        read_limit = self._builder_read_limit(options)
        for research_round in range(1, total_rounds + 1):
            self._check_control(task_id, cancel_event)
            self._emit(
                task_id,
                Stage.CREATING,
                f"Builder is creating the strategic plan (round {research_round}/{total_rounds}).",
            )
            prompt = principal_prompt(objective, context, tools, evidence, research_round)
            builder = self._builder_provider(task_id)
            raw = self._send_agent_prompt(
                builder,
                prompt,
                task_id=task_id,
                attachment_paths=self._task_attachment_paths(task_id),
            )
            self.store.append_message(task_id, "Builder", "agent", raw)
            proposal = self._parse_proposal_with_recovery(self._builder_provider(task_id), raw, task_id)
            errors = validate_proposal(proposal.actions, set(self.studio.tools))
            if errors:
                raise OrchestratorError("The proposal was blocked by policy: " + " | ".join(errors))
            reads = [action for action in proposal.actions if is_read_only(action.tool)]
            if not reads:
                break
            unique_reads: list[ProposalAction] = []
            for action in reads[:read_limit]:
                key = json.dumps([action.tool, action.arguments], ensure_ascii=False, sort_keys=True, default=str)
                if key in seen_reads:
                    continue
                seen_reads.add(key)
                unique_reads.append(action)
            self._emit(task_id, Stage.COLLECTING_CONTEXT, "Running the reads requested by the builder.")
            evidence.extend(self._execute_read_actions(task_id, studio_id, unique_reads))
            if research_round == total_rounds:
                proposal.actions = [action for action in proposal.actions if not is_read_only(action.tool)]
        if proposal is None:
            raise OrchestratorError("The builder did not produce a proposal.")
        return proposal, evidence

    def _execute_read_actions(
        self,
        task_id: str,
        studio_id: str,
        actions: list[ProposalAction],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for action in actions:
            key = json.dumps([action.tool, action.arguments], ensure_ascii=False, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            arguments = self._prepare_arguments(action.tool, action.arguments)
            result = self.studio.call_tool(action.tool, arguments, studio_id=studio_id, timeout=120)
            results.append(
                {
                    "tool": action.tool,
                    "arguments": arguments,
                    "is_error": result.is_error,
                    "result": result.compact(28_000),
                }
            )
            kind = "warning" if result.is_error else "success"
            self._emit(task_id, Stage.COLLECTING_CONTEXT, f"Read completed: {action.tool}.", kind)
        return results

    def _review_and_revise(
        self,
        task_id: str,
        objective: str,
        context: dict[str, Any],
        proposal: AgentProposal,
        evidence: list[dict[str, Any]],
        options: TaskOptions,
        cancel_event: threading.Event,
        *,
        initial_review: bool = True,
    ) -> tuple[AgentProposal, ReviewResult | None]:
        if not options.independent_review:
            return proposal, None
        reviewer = self._review_provider(options)
        if not reviewer:
            self._emit(
                task_id,
                Stage.REVIEWING,
                "Independent review skipped because no separate reviewer route is currently available.",
                "warning",
                "Smart Routing will continue with deterministic policy and QA instead of blocking on DeepSeek login.",
            )
            return proposal, None

        review: ReviewResult | None = None
        revisions = 0
        while True:
            self._check_control(task_id, cancel_event)
            self._emit(task_id, Stage.REVIEWING, "Reviewer is independently reviewing the plan.")
            raw = self._send_agent_prompt(
                reviewer,
                review_prompt(objective, context, proposal, evidence),
                task_id=task_id,
            )
            self.store.append_message(task_id, "Reviewer", "reviewer", raw)
            review = self._parse_review_with_recovery(reviewer, raw, task_id)
            if review.approved:
                self._emit(task_id, Stage.REVIEWING, "Independent review approved.", "success", review.summary)
                return proposal, review
            if review.verdict == "block":
                raise TaskBlocked("Reviewer blocked the plan: " + (review.summary or "no summary"))
            if revisions >= options.max_revisions:
                raise OrchestratorError("The revision limit was reached without independent approval.")
            revisions += 1
            self._emit(
                task_id,
                Stage.REVISING,
                f"Builder is addressing review feedback ({revisions}/{options.max_revisions}).",
                "warning",
            )
            proposal = self._request_revision(task_id, objective, context, proposal, review, "")
            errors = validate_proposal(proposal.actions, set(self.studio.tools))
            if errors:
                raise OrchestratorError("The revision produced blocked actions: " + " | ".join(errors))

    def _request_revision(
        self,
        task_id: str,
        objective: str,
        context: dict[str, Any],
        proposal: AgentProposal,
        review: ReviewResult | None,
        user_note: str,
    ) -> AgentProposal:
        effective_review = review or ReviewResult(
            verdict="revise",
            summary="The user requested adjustments.",
            required_changes=[user_note] if user_note else [],
        )
        builder = self._builder_provider(task_id)
        raw = self._send_agent_prompt(
            builder,
            revision_prompt(objective, context, proposal, effective_review, user_note),
            task_id=task_id,
            attachment_paths=self._task_attachment_paths(task_id),
        )
        self.store.append_message(task_id, "Builder", "agent", raw)
        return self._parse_proposal_with_recovery(self._builder_provider(task_id), raw, task_id)

    def _handle_visual_and_3d(
        self,
        task_id: str,
        objective: str,
        proposal: AgentProposal,
        options: TaskOptions,
        cancel_event: threading.Event,
    ) -> None:
        visual_required = options.visual_first or options.create_3d_asset
        visual_prompt = proposal.visual_prompt.strip() or proposal.model_3d_prompt.strip() or objective
        if visual_required:
            version = 0
            master: dict[str, Any] = {}
            visual: dict[str, Any] = {}
            revision_note = ""
            target_views: set[str] | None = None
            while True:
                self._check_control(task_id, cancel_event)
                if not master or (revision_note and not revision_note.startswith("regen:")):
                    raw_master = self._send_agent_prompt(
                        self._builder_provider(task_id),
                        visual_master_prompt(objective, visual_prompt, revision_note),
                        task_id=task_id,
                        attachment_paths=self._task_attachment_paths(task_id),
                    )
                    self.store.append_message(task_id, "Builder", "visual-spec", raw_master)
                    master = extract_json_object(raw_master)
                version += 1
                visual = self._generate_visual_version(
                    task_id,
                    master,
                    version,
                    previous=visual,
                    target_views=target_views,
                )
                qa = self._qa_visual_version(task_id, master, version, visual)
                visual.update(
                    {
                        "version": version,
                        "master": master,
                        "qa": qa,
                        "status": "READY",
                        "prompt": visual_prompt,
                    }
                )
                self.store.update_context_section(task_id, "visual", visual)
                if not bool(qa.get("approved")):
                    failed = {
                        str(item).strip().casefold()
                        for item in qa.get("failed_views", [])
                        if str(item).strip().casefold() in self._visual_views()
                    }
                    if version >= 3:
                        raise OrchestratorError(
                            "Visual QA rejected three versions: " + str(qa.get("summary") or qa.get("warnings"))
                        )
                    target_views = failed or set(self._visual_views())
                    revision_note = "regen:qa"
                    self._emit(
                        task_id,
                        Stage.GENERATING_CONCEPT,
                        f"Visual QA requested regeneration of version {version}.",
                        "warning",
                        json.dumps(qa, ensure_ascii=False),
                    )
                    continue
                if self._effective_approval_mode(options) == "full_auto":
                    self._record_auto_approval(
                        task_id, f"visual:{version}:auto", self._effective_approval_mode(options)
                    )
                    visual["status"] = "APPROVED"
                    self.store.update_context_section(task_id, "visual", visual)
                    break
                decision, note = self._wait_gate(
                    task_id,
                    f"visual:{version}",
                    Stage.WAITING_VISUAL_APPROVAL,
                    f"Six PNG views for version {version} are ready and awaiting approval.",
                    json.dumps({"version": version, "master": master, "qa": qa}, ensure_ascii=False),
                    cancel_event,
                )
                if decision == "approve":
                    visual["status"] = "APPROVED"
                    self.store.update_context_section(task_id, "visual", visual)
                    break
                if decision == "reject":
                    raise OrchestratorError("Visual concept rejected: " + note)
                revision_note = note.strip() or "Revise the concept while preserving the object's identity."
                target_views = self._visual_regen_targets(revision_note)

        if options.create_3d_asset:
            model_prompt = proposal.model_3d_prompt.strip()
            if not model_prompt:
                raise TaskBlocked(
                    "The builder did not provide a 3D prompt, so the 3D generator cannot run without a specification."
                )
            if not self.bridge.wait_for_provider("hunyuan", timeout=2):
                raise BridgeError("The 3D generator is not connected to create the requested asset.")
            target = "all"
            model_version = 0
            while True:
                model_version += 1
                response = self._generate_hunyuan_model(
                    task_id,
                    model_prompt,
                    model_version,
                    target,
                )
                detail = json.dumps(response, ensure_ascii=False)
                if options.approval_mode == "full_auto":
                    self._record_auto_approval(
                        task_id, f"3d:{model_version}:auto", self._effective_approval_mode(options)
                    )
                    response["status"] = "APPROVED"
                    self.store.update_context_section(task_id, "model", response)
                    break
                decision, note = self._wait_gate(
                    task_id,
                    f"3d:{model_version}",
                    Stage.WAITING_3D_APPROVAL,
                    f"3D geometry and texture for version {model_version} are ready and awaiting approval.",
                    detail,
                    cancel_event,
                )
                if decision == "approve":
                    response["status"] = "APPROVED"
                    self.store.update_context_section(task_id, "model", response)
                    break
                if decision == "reject":
                    raise OrchestratorError("3D model rejected: " + note)
                normalized = note.strip().casefold()
                target = "texture" if "texture" in normalized or "material" in normalized else "geometry"

    @staticmethod
    def _visual_views() -> tuple[str, ...]:
        return ("front", "back", "left", "right", "top", "bottom")

    def _generate_visual_version(
        self,
        task_id: str,
        master: dict[str, Any],
        version: int,
        *,
        previous: dict[str, Any],
        target_views: set[str] | None,
    ) -> dict[str, Any]:
        self._emit(
            task_id,
            Stage.GENERATING_CONCEPT,
            f"Generating six actual orthographic views (version {version}).",
        )
        version_dir = self.run_root.parent / "assets" / task_id / "concept" / f"v{version}"
        version_dir.mkdir(parents=True, exist_ok=True)
        requested = target_views or set(self._visual_views())
        visual: dict[str, Any] = {}
        for view in self._visual_views():
            output = version_dir / f"{view}.png"
            prior = previous.get(view) if isinstance(previous.get(view), dict) else {}
            prior_path = Path(str(prior.get("path") or "")) if prior else Path()
            if view not in requested and prior_path.is_file():
                shutil.copy2(prior_path, output)
            else:
                response = self.bridge.request(
                    "chatgpt",
                    "generate_image",
                    {
                        "prompt": visual_view_prompt(master, view),
                        "output_path": str(output),
                        "timeout_ms": 420_000,
                    },
                    task_id=task_id,
                    timeout=435,
                )
                if str(response.get("status", "ok")).casefold() != "ok":
                    raise BridgeError(str(response.get("error") or f"Failed to generate the {view} view."))
                artifact = Path(str(response.get("artifact_path") or output)).resolve()
                if artifact != output.resolve() or not artifact.is_file():
                    raise BridgeError(f"The {view} view did not produce the authorized PNG.")
            width, height, digest = self._validate_png(output)
            asset_id = f"{task_id}-concept-v{version}-{view}"
            self.store.register_asset(
                asset_id,
                job_id=task_id,
                name=output.name,
                kind="VIEW",
                path=output,
                mime="image/png",
                metadata={"view": view.upper(), "conceptVersion": version, "width": width, "height": height},
            )
            visual[view] = {
                "asset_id": asset_id,
                "path": str(output.resolve()),
                "sha256": digest,
                "width": width,
                "height": height,
            }
        return visual

    def _qa_visual_version(
        self,
        task_id: str,
        master: dict[str, Any],
        version: int,
        visual: dict[str, Any],
    ) -> dict[str, Any]:
        paths = [str(visual[view]["path"]) for view in self._visual_views()]
        hashes = [str(visual[view]["sha256"]) for view in self._visual_views()]
        if len(set(hashes)) != len(hashes):
            duplicates = [view for view in self._visual_views() if hashes.count(str(visual[view]["sha256"])) > 1]
            return {
                "approved": False,
                "failed_views": duplicates,
                "warnings": ["Two or more views have identical PNG content."],
                "summary": "Deterministic visual QA detected duplicate directions.",
            }
        upload = self.bridge.request(
            "chatgpt",
            "upload_files",
            {"files": paths},
            task_id=task_id,
            timeout=120,
        )
        if int(upload.get("uploaded") or 0) != 6:
            raise BridgeError("Visual QA requires confirmed uploads for all six separate views.")
        raw = self._send_agent_prompt(
            "chatgpt",
            visual_qa_prompt(master, version),
            task_id=task_id,
        )
        self.store.append_message(task_id, "Builder", "visual-qa", raw)
        qa = extract_json_object(raw)
        return {
            "approved": qa.get("approved") is True,
            "failed_views": [str(item).casefold() for item in qa.get("failed_views", [])],
            "warnings": [str(item) for item in qa.get("warnings", [])],
            "summary": str(qa.get("summary") or "Visual QA provided no summary."),
        }

    @staticmethod
    def _validate_png(path: Path) -> tuple[int, int, str]:
        raw = path.read_bytes()
        if len(raw) < 33 or raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
            raise OrchestratorError(f"Invalid or truncated PNG: {path.name}")
        width, height = struct.unpack(">II", raw[16:24])
        if width < 256 or height < 256 or max(width, height) / min(width, height) > 1.15:
            raise OrchestratorError(f"View {path.name} must be nearly square and at least 256 px.")
        return width, height, hashlib.sha256(raw).hexdigest()

    def _visual_regen_targets(self, note: str) -> set[str] | None:
        normalized = note.casefold()
        selected = {view for view in self._visual_views() if f"regen:view:{view}" in normalized}
        if selected:
            return selected
        return set(self._visual_views()) if normalized.startswith("regen:") else None

    def _generate_hunyuan_model(
        self,
        task_id: str,
        prompt: str,
        version: int,
        target: str,
    ) -> dict[str, Any]:
        capabilities_response = self.bridge.request("hunyuan", "capabilities", {}, task_id=task_id, timeout=45)
        capabilities = capabilities_response.get("capabilities")
        caps = capabilities if isinstance(capabilities, dict) else {}
        required = {"upload_files", "geometry", "texture"}
        missing = sorted(name for name in required if not bool(caps.get(name)))
        if missing:
            raise BridgeError("CAPABILITY_UNAVAILABLE: 3D Generator is missing " + ", ".join(missing) + ".")
        task = self.store.load_task(task_id) or {}
        raw_context = task.get("context")
        context: dict[str, Any] = raw_context if isinstance(raw_context, dict) else {}
        raw_visual = context.get("visual")
        visual: dict[str, Any] = raw_visual if isinstance(raw_visual, dict) else {}
        if str(visual.get("status") or "").upper() != "APPROVED":
            raise BridgeError("The 3D generator requires an approved visual version before generation.")
        references = [
            str(visual[view]["path"])
            for view in self._visual_views()
            if isinstance(visual.get(view), dict) and Path(str(visual[view].get("path") or "")).is_file()
        ]
        if len(references) != len(self._visual_views()):
            raise BridgeError(
                "The 3D generator requires all six approved PNG views: front, back, left, right, top, and bottom."
            )
        try:
            max_images = max(1, min(6, int(caps.get("max_image_inputs") or 1)))
        except TypeError, ValueError:
            max_images = 1
        references = references[:max_images]
        self._emit(
            task_id,
            Stage.GENERATING_3D,
            f"3D Generator is creating separate geometry and PBR materials from {len(references)} supported reference(s).",
        )
        raw_previous = context.get("model")
        previous: dict[str, Any] = raw_previous if isinstance(raw_previous, dict) else {}
        geometry_path = str(previous.get("geometry_path") or "")
        if target in {"all", "geometry"}:
            uploaded = self.bridge.request(
                "hunyuan", "upload_files", {"files": references}, task_id=task_id, timeout=120
            )
            if int(uploaded.get("uploaded") or 0) != len(references):
                raise BridgeError("The 3D generator did not confirm all supported visual references.")
            geometry = self.bridge.request(
                "hunyuan",
                "generate_geometry",
                {"prompt": prompt, "timeout_ms": 600_000},
                task_id=task_id,
                timeout=615,
            )
            geometry_path = self._validated_glb_artifact(geometry, "geometry")
            geometry_asset = f"{task_id}-geometry-v{version}"
            self.store.register_asset(
                geometry_asset,
                job_id=task_id,
                name=Path(geometry_path).name,
                kind="GLB",
                path=Path(geometry_path),
                mime="model/gltf-binary",
                metadata={"phase": "geometry", "version": version, "references": len(references)},
            )
        if not geometry_path or not Path(geometry_path).is_file():
            raise BridgeError("The texture and PBR stage requires valid local GLB geometry.")
        texture_inputs = [geometry_path, *references]
        uploaded_texture = self.bridge.request(
            "hunyuan",
            "upload_files",
            {"files": texture_inputs},
            task_id=task_id,
            timeout=120,
        )
        if int(uploaded_texture.get("uploaded") or 0) != len(texture_inputs):
            raise BridgeError(
                "The 3D generator did not confirm the geometry plus every approved texture reference; "
                "Rubra will not silently drop a view."
            )
        textured = self.bridge.request(
            "hunyuan",
            "generate_texture",
            {
                "prompt": prompt + "\nPreserve the approved geometry; generate final texture and PBR materials.",
                "timeout_ms": 600_000,
            },
            task_id=task_id,
            timeout=615,
        )
        textured_path = self._validated_glb_artifact(textured, "texture/PBR")
        textured_asset = f"{task_id}-textured-v{version}"
        self.store.register_asset(
            textured_asset,
            job_id=task_id,
            name=Path(textured_path).name,
            kind="GLB",
            path=Path(textured_path),
            mime="model/gltf-binary",
            metadata={"phase": "texture", "version": version, "references": len(references)},
        )
        response = {
            "version": version,
            "status": "READY",
            "capabilities": caps,
            "reference_count": len(references),
            "geometry_path": geometry_path,
            "texture_path": textured_path,
            "asset_id": textured_asset,
            "name": Path(textured_path).name,
            "path": textured_path,
        }
        self.store.update_context_section(task_id, "model", response)
        return response

    @staticmethod
    def _validated_glb_artifact(response: dict[str, Any], phase: str) -> str:
        if str(response.get("status", "ok")).casefold() != "ok":
            raise BridgeError(str(response.get("error") or f"The 3D generator failed during {phase}."))
        path_text = str(response.get("artifact_path") or "").strip()
        if not path_text:
            error = str(response.get("download_error") or "").strip()
            raise BridgeError(error or f"The 3D generator completed {phase} without a local GLB file.")
        path = Path(path_text).resolve()
        if path.suffix.casefold() != ".glb":
            raise BridgeError(
                f"The 3D generator returned {path.suffix or 'an unknown format'} during {phase}; GLB is required."
            )
        try:
            load_glb(path)
        except GLBError as exc:
            raise BridgeError(f"Invalid GLB during {phase}: {exc}") from exc
        return str(path)

    def _apply_actions(
        self,
        task_id: str,
        studio_id: str,
        actions: list[ProposalAction],
    ) -> list[dict[str, Any]]:
        run_dir = self.run_root / task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        evidence: list[dict[str, Any]] = []
        for index, action in enumerate(actions, start=1):
            decision = classify_action(action, set(self.studio.tools))
            if not decision.allowed or decision.risk == "critical":
                raise OrchestratorError(
                    f"Action {action.tool} was blocked during application: {'; '.join(decision.reasons)}"
                )
            operation_payload = {
                "tool": action.tool,
                "arguments": action.arguments,
                "reason": action.reason,
            }
            digest = hashlib.sha256(
                json.dumps(operation_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            operation_id = f"mutation:{task_id}:{digest}"
            operation = self.store.claim_operation(operation_id, "studio_mutation", task_id)
            if not operation.get("claimed"):
                state = str(operation.get("state") or "")
                if state == "complete":
                    response = operation.get("response")
                    prior = response.get("evidence") if isinstance(response, dict) else None
                    if isinstance(prior, list):
                        evidence.extend(item for item in prior if isinstance(item, dict))
                    self._emit(
                        task_id,
                        Stage.APPLYING,
                        f"Mutation {index}/{len(actions)} was already confirmed; idempotent replay prevented.",
                        "success",
                        operation_id,
                    )
                    continue
                raise OrchestratorError(
                    f"RECOVERY_REQUIRED: operation {operation_id} remained in state {state or 'unknown'}; "
                    "the orchestrator will not repeat a write without human review."
                )

            operation_evidence: list[dict[str, Any]] = []
            try:
                arguments = self._prepare_arguments(action.tool, action.arguments)
                expected_hash = str(action.arguments.get("_zenless_expected_sha256") or "")
                before_hash = ""
                expected_source = ""
                if action.tool == "execute_luau":
                    expected = action.arguments.get("_zenless_expected_instances")
                    if not isinstance(expected, dict) or "_zenless_scene_before" not in action.arguments:
                        raise OrchestratorError("Scene changes require a bound property snapshot.")
                    current = read_scene(self.studio, studio_id, expected)
                    if current["observed"] != action.arguments["_zenless_scene_before"].get("observed") or current[
                        "missing"
                    ] != action.arguments["_zenless_scene_before"].get("missing"):
                        raise OrchestratorError("STUDIO_CHANGED: scene properties changed after review.")
                    (run_dir / f"before-scene-{index:02d}.json").write_text(
                        json.dumps(current, ensure_ascii=False), encoding="utf-8"
                    )
                if action.tool == "multi_edit":
                    if not expected_hash:
                        raise OrchestratorError("MUTATION_PRECONDITION_MISSING: multi_edit has no expected hash.")
                    expected_exists = action.arguments.get("_zenless_expected_exists", True)
                    exists, source = self._read_script_state(studio_id, arguments, allow_missing=not expected_exists)
                    before_hash = self._source_hash(source)
                    if exists != expected_exists or before_hash != expected_hash:
                        raise OrchestratorError(
                            "STUDIO_CHANGED: the script changed after the proposal, so the write was blocked "
                            f"(expected {expected_hash[:12]}, current {before_hash[:12]})."
                        )
                    expected_source = self._edited_source(source, arguments)
                    if exists:
                        self._snapshot_script(task_id, arguments, run_dir, index, source)
                self._emit(
                    task_id,
                    Stage.APPLYING,
                    f"Studio bridge is applying {index}/{len(actions)}: {action.tool}.",
                    detail=f"{action.reason}\noperation_id={operation_id}",
                )
                result = self.studio.call_tool(action.tool, arguments, studio_id=studio_id, timeout=240)
                item = {
                    "tool": action.tool,
                    "arguments": arguments,
                    "is_error": result.is_error,
                    "result": result.compact(24_000),
                    "operation_id": operation_id,
                    "mutation_id": digest,
                    "expected_sha256": expected_hash,
                    "before_sha256": before_hash,
                }
                operation_evidence.append(item)
                if result.is_error:
                    raise OrchestratorError(f"Studio bridge failed at {action.tool}: {result.compact(6000)}")
                if action.tool == "multi_edit":
                    operation_evidence.extend(
                        self._verify_script(task_id, studio_id, arguments, expected_hash, operation_id, expected_source)
                    )
                if action.tool == "execute_luau":
                    verified = read_scene(
                        self.studio, studio_id, action.arguments["_zenless_expected_instances"], verify=True
                    )
                    operation_evidence.append(
                        {
                            "tool": "rubra_scene_readback",
                            "is_error": False,
                            "verified": True,
                            "result": verified,
                            "operation_id": operation_id,
                        }
                    )
                self.store.finish_operation(
                    operation_id,
                    "complete",
                    {"evidence": operation_evidence, "completed_at": now_iso()},
                )
                evidence.extend(operation_evidence)
            except Exception as exc:
                self.store.finish_operation(
                    operation_id,
                    "failed",
                    {"error": str(exc), "evidence": operation_evidence, "failed_at": now_iso()},
                )
                raise
        (run_dir / "apply-evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return evidence

    def _bind_mutation_preconditions(
        self,
        task_id: str,
        studio_id: str,
        actions: list[ProposalAction],
    ) -> None:
        predicted: dict[str, tuple[bool, str]] = {}
        for action in actions:
            if action.tool == "execute_luau":
                action.arguments["_zenless_scene_before"] = read_scene(
                    self.studio, studio_id, action.arguments["_zenless_expected_instances"]
                )
            if action.tool != "multi_edit":
                continue
            arguments = self._prepare_arguments(action.tool, action.arguments)
            target = str(arguments.get("file_path") or "")
            edits = arguments.get("edits", [])
            creation = len(edits) == 1 and isinstance(edits[0], dict) and edits[0].get("old_string") == ""
            if target in predicted:
                exists, source = predicted[target]
            else:
                exists, source = self._read_script_state(studio_id, arguments, allow_missing=creation)
            predicted[target] = (True, self._edited_source(source, arguments))
            action.arguments["_zenless_expected_sha256"] = self._source_hash(source)
            action.arguments["_zenless_expected_exists"] = exists
            task = self.store.load_task(task_id) or {}
            current_stage = Stage(str(task.get("stage") or Stage.REVIEWING.value))
            self._emit(
                task_id,
                current_stage,
                f"Precondition bound to the current state of {arguments.get('file_path', 'script')}.",
                "success",
            )

    def _read_script_source(self, studio_id: str, arguments: dict[str, Any]) -> str:
        return self._read_script_state(studio_id, arguments)[1]

    def _read_script_state(
        self, studio_id: str, arguments: dict[str, Any], *, allow_missing: bool = False
    ) -> tuple[bool, str]:
        if "script_read" not in self.studio.tools:
            raise OrchestratorError("MUTATION_PRECONDITION_UNAVAILABLE: script_read is required before multi_edit.")
        target = str(arguments.get("file_path", "")).strip()
        if not target:
            raise OrchestratorError("multi_edit did not provide file_path for the snapshot and precondition.")
        result = self.studio.call_tool(
            "script_read",
            {"target_file": target, "should_read_entire_file": True},
            studio_id=studio_id,
            timeout=90,
        )
        if result.is_error:
            if (
                allow_missing
                and target in result.text
                and re.search(r"\b(?:not found|does not exist|doesn't exist)\b", result.text, re.IGNORECASE)
            ):
                return False, ""
            raise OrchestratorError(f"Could not read back {target}: {result.compact(3000)}")
        return True, script_source(result)

    @staticmethod
    def _edited_source(source: str, arguments: dict[str, Any]) -> str:
        for edit in arguments.get("edits", []):
            old, new = edit.get("old_string"), edit.get("new_string")
            if not isinstance(old, str) or not isinstance(new, str):
                raise OrchestratorError("INVALID_EDIT: old_string and new_string must be strings.")
            if not old:
                if source:
                    raise OrchestratorError("INVALID_EDIT: empty old_string requires a new or empty script.")
                source = new
                continue
            matches = source.count(old)
            replace_all = edit.get("replace_all") is True
            if matches == 0 or (matches > 1 and not replace_all):
                raise OrchestratorError("INVALID_EDIT: old_string must identify an existing, unambiguous source range.")
            source = source.replace(old, new) if replace_all else source.replace(old, new, 1)
        return source

    @staticmethod
    def _source_hash(source: str) -> str:
        return hashlib.sha256(source.encode("utf-8", "replace")).hexdigest()

    def _snapshot_script(
        self,
        task_id: str,
        arguments: dict[str, Any],
        run_dir: Path,
        index: int,
        source: str,
    ) -> None:
        target = str(arguments.get("file_path", ""))
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", target)[-100:] or "script"
        (run_dir / f"before-{index:02d}-{safe_name}.luau.txt").write_text(source, encoding="utf-8")
        self._emit(task_id, Stage.APPLYING, f"Snapshot created before editing {target}.", "success")

    def _verify_script(
        self,
        task_id: str,
        studio_id: str,
        arguments: dict[str, Any],
        expected_hash: str,
        operation_id: str,
        expected_source: str,
    ) -> list[dict[str, Any]]:
        target = str(arguments.get("file_path", ""))
        source = self._read_script_source(studio_id, arguments)
        if source != expected_source:
            raise OrchestratorError(f"READ_BACK_MISMATCH: {target} does not match the complete expected source.")
        post_hash = self._source_hash(source)
        if post_hash == expected_hash and any(
            isinstance(edit, dict) and edit.get("old_string") != edit.get("new_string")
            for edit in arguments.get("edits", [])
        ):
            raise OrchestratorError(f"READ_BACK_MISMATCH: {target} kept the previous hash after editing.")
        self._emit(
            task_id,
            Stage.APPLYING,
            f"Post-edit source read back: {target}.",
            "success",
        )
        return [
            {
                "tool": "script_read",
                "arguments": {"target_file": target},
                "is_error": False,
                "result": source[:24_000],
                "operation_id": operation_id,
                "expected_sha256": expected_hash,
                "post_sha256": post_hash,
                "verified": True,
            }
        ]

    def _play_test(
        self,
        task_id: str,
        studio_id: str,
        cancel_event: threading.Event,
    ) -> str:
        if "start_stop_play" not in self.studio.tools:
            raise OrchestratorError("The current Studio bridge does not provide start_stop_play.")
        self._emit(task_id, Stage.TESTING, "Starting an actual play test in Studio.")
        started = False
        console_output = ""
        try:
            result = self.studio.call_tool("start_stop_play", {"is_start": True}, studio_id=studio_id, timeout=60)
            if result.is_error:
                raise OrchestratorError("Failed to start the play test: " + result.compact(3000))
            started = True
            if cancel_event.wait(self.play_test_seconds):
                self._check_control(task_id, cancel_event)
            if "get_console_output" in self.studio.tools:
                console = self.studio.call_tool("get_console_output", {}, studio_id=studio_id, timeout=60)
                if console.is_error:
                    raise OrchestratorError("Failed to read the output: " + console.compact(3000))
                console_output = console.text
        finally:
            if started:
                try:
                    stopped = self.studio.call_tool(
                        "start_stop_play", {"is_start": False}, studio_id=studio_id, timeout=60
                    )
                    if stopped.is_error:
                        raise OrchestratorError("Studio refused to stop: " + stopped.compact(3000))
                except MCPError as exc:
                    raise OrchestratorError(f"Failed to stop the play test: {exc}") from exc
        kind = "warning" if self._console_has_errors(console_output) else "success"
        message = "Play test returned errors." if kind == "warning" else "Play test completed with no detected errors."
        self._emit(task_id, Stage.TESTING, message, kind, console_output[-5000:])
        self.store.append_message(task_id, "Studio", "test", console_output or "[Empty output]")
        return console_output

    def _run_quality_test(
        self,
        task_id: str,
        studio_id: str,
        cancel_event: threading.Event,
        evidence: list[dict[str, Any]],
        rerun: bool,
    ) -> str:
        self._emit(task_id, Stage.TESTING, "QA is preparing tests based on the changes.")
        if self.qa_callback is not None:
            return self.qa_callback(task_id, studio_id, cancel_event, evidence, rerun)
        return self._play_test(task_id, studio_id, cancel_event)

    def _request_repair(
        self,
        task_id: str,
        objective: str,
        proposal: AgentProposal,
        console_output: str,
        source_evidence: list[dict[str, Any]],
    ) -> AgentProposal:
        builder = self._builder_provider(task_id)
        raw = self._send_agent_prompt(
            builder,
            repair_prompt(objective, proposal, console_output, source_evidence),
            task_id=task_id,
            attachment_paths=self._task_attachment_paths(task_id),
        )
        self.store.append_message(task_id, "Builder", "agent", raw)
        repair = self._parse_proposal_with_recovery(self._builder_provider(task_id), raw, task_id)
        errors = validate_proposal(repair.actions, set(self.studio.tools))
        if errors:
            raise OrchestratorError("The correction was blocked by policy: " + " | ".join(errors))
        return repair

    def _final_review_and_repair(
        self,
        task_id: str,
        objective: str,
        context: dict[str, Any],
        proposal: AgentProposal,
        mutation_evidence: list[dict[str, Any]],
        console_output: str,
        options: TaskOptions,
        cancel_event: threading.Event,
        studio_id: str,
    ) -> tuple[AgentProposal, list[dict[str, Any]], str]:
        if not options.independent_review:
            self._emit(
                task_id,
                Stage.FINAL_REVIEW,
                "Independent Reviewer disabled; final release relies on deterministic policy, mutation read-back, and QA evidence.",
                "warning",
            )
            self.store.update_task(
                task_id,
                final_review_json={
                    "verdict": "skipped",
                    "summary": "Independent Reviewer disabled for this task.",
                    "warnings": ["No independent AI final review was requested."],
                },
            )
            return proposal, mutation_evidence, console_output
        reviewer = self._review_provider(options)
        if not reviewer:
            self._emit(
                task_id,
                Stage.FINAL_REVIEW,
                "No independent reviewer route is available; releasing only if deterministic QA evidence is clean.",
                "warning",
                "Smart Routing did not block on DeepSeek CAPTCHA or provider quota.",
            )
            self.store.update_task(
                task_id,
                final_review_json={
                    "verdict": "skipped",
                    "summary": "Independent reviewer unavailable; deterministic QA evidence used.",
                    "warnings": ["No separate AI reviewer route was available."],
                },
            )
            return proposal, mutation_evidence, console_output
        revisions = 0
        while True:
            self._check_control(task_id, cancel_event)
            self._emit(
                task_id,
                Stage.FINAL_REVIEW,
                "Reviewer is examining the final state, read-back, and actual QA evidence.",
            )
            final_state = self._collect_final_state(studio_id, mutation_evidence)
            latest_test = self.store.latest_test_run(task_id)
            qa_result: dict[str, Any] = {
                "automatic_enabled": options.automatic_play_test,
                "latest_run": latest_test or {},
                "studio_output": console_output[-24_000:],
            }
            warnings: list[str] = []
            if not options.automatic_play_test:
                warnings.append("Automatic QA was explicitly disabled; no test pass may be inferred.")
            if self._console_has_errors(console_output):
                warnings.append("The latest Studio output still contains an error marker.")
            raw = self._send_agent_prompt(
                reviewer,
                final_review_prompt(objective, final_state, mutation_evidence, qa_result, warnings),
                task_id=task_id,
            )
            self.store.append_message(task_id, "Reviewer", "final-reviewer", raw)
            review = self._parse_review_with_recovery(reviewer, raw, task_id)
            self.store.update_task(task_id, final_review_json=review.to_dict())
            if review.approved:
                self._emit(
                    task_id,
                    Stage.FINAL_REVIEW,
                    "Independent final review approved with post-change evidence.",
                    "success",
                    review.summary,
                )
                return proposal, mutation_evidence, console_output
            if review.verdict == "block":
                raise TaskBlocked("Reviewer blocked the final state: " + review.summary)
            if revisions >= options.max_revisions:
                raise TaskBlocked("Final review did not approve after the correction limit: " + review.summary)
            revisions += 1
            self._emit(
                task_id,
                Stage.FIXING,
                f"Preparing final correction {revisions}/{options.max_revisions}.",
                "warning",
                review.summary,
            )
            repair = self._request_revision(
                task_id,
                objective,
                {**context, "final_state": final_state, "qa": qa_result},
                proposal,
                review,
                "Fix only the issues found during final review.",
            )
            errors = validate_proposal(repair.actions, set(self.studio.tools))
            if errors:
                raise OrchestratorError("The final correction was blocked by policy: " + " | ".join(errors))
            repair, repair_review = self._review_and_revise(
                task_id,
                objective,
                context,
                repair,
                mutation_evidence,
                options,
                cancel_event,
                initial_review=False,
            )
            repair_actions = [action for action in repair.actions if not is_read_only(action.tool)]
            if not repair_actions:
                raise TaskBlocked("The final correction proposed no verifiable action.")
            self._bind_mutation_preconditions(task_id, studio_id, repair_actions)
            self.store.update_task(
                task_id,
                proposal_json=repair.to_dict(),
                review_json=repair_review.to_dict() if repair_review else {},
            )
            if self._requires_change_approval(options, repair_actions, repair_review):
                decision, note = self._wait_gate(
                    task_id,
                    f"final-repair:{revisions}",
                    Stage.WAITING_CHANGE_APPROVAL,
                    f"Final review correction {revisions} is awaiting approval.",
                    self._proposal_detail(repair, repair_review),
                    cancel_event,
                )
                if decision != "approve":
                    raise TaskBlocked("Final correction was not approved: " + note)
            else:
                self._record_auto_approval(
                    task_id, f"final-repair:{revisions}:auto", self._effective_approval_mode(options)
                )
            self._emit(task_id, Stage.APPLYING, "Applying the approved final review correction.")
            mutation_evidence.extend(self._apply_actions(task_id, studio_id, repair_actions))
            proposal = repair
            if options.automatic_play_test:
                console_output = self._run_quality_test(
                    task_id,
                    studio_id,
                    cancel_event,
                    mutation_evidence,
                    True,
                )
                if self._console_has_errors(console_output):
                    raise TaskBlocked("The rerun after the final correction still returned errors.")

    def _collect_final_state(
        self,
        studio_id: str,
        mutation_evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        state: dict[str, Any] = {"captured_at": now_iso(), "studio_id": studio_id, "sources": {}}
        if "get_studio_state" in self.studio.tools:
            result = self.studio.call_tool("get_studio_state", {}, studio_id=studio_id, timeout=90)
            state["studio_state"] = result.compact(18_000)
        targets: set[str] = set()
        for item in mutation_evidence:
            raw_arguments = item.get("arguments")
            arguments: dict[str, Any] = raw_arguments if isinstance(raw_arguments, dict) else {}
            target = str(arguments.get("file_path") or arguments.get("target_file") or "").strip()
            if target:
                targets.add(target)
        for target in sorted(targets)[:20]:
            result = self.studio.call_tool(
                "script_read",
                {"target_file": target, "should_read_entire_file": True},
                studio_id=studio_id,
                timeout=90,
            )
            if result.is_error:
                state["sources"][target] = {"error": result.compact(3000)}
                continue
            state["sources"][target] = {
                "sha256": self._source_hash(script_source(result)),
                "source": script_source(result)[:32_000],
            }
        return state

    def _wait_gate(
        self,
        task_id: str,
        gate_name: str,
        stage: Stage,
        message: str,
        detail: str,
        cancel_event: threading.Event,
    ) -> tuple[str, str]:
        gate = _ApprovalGate()
        key = (task_id, gate_name)
        with self._state_lock:
            self._gates[key] = gate
        self._emit(task_id, stage, message, "warning", detail)
        try:
            while not gate.event.wait(0.25):
                self._check_control(task_id, cancel_event)
            return gate.decision, gate.note
        finally:
            with self._state_lock:
                self._gates.pop(key, None)

    def _prepare_arguments(self, tool_name: str, raw: dict[str, Any]) -> dict[str, Any]:
        arguments = {key: value for key, value in raw.items() if not str(key).startswith("_zenless_")}
        arguments.pop("studio_id", None)
        tool = self.studio.tools.get(tool_name)
        if tool is None:
            return arguments
        properties = tool.input_schema.get("properties", {})
        if "datamodel_type" in properties and "datamodel_type" not in arguments:
            enum = (
                properties["datamodel_type"].get("enum", []) if isinstance(properties["datamodel_type"], dict) else []
            )
            arguments["datamodel_type"] = "Edit" if "Edit" in enum or not enum else enum[0]
        return arguments

    def _tool_catalog(self) -> list[dict[str, Any]]:
        catalog: list[dict[str, Any]] = []
        for tool in sorted(self.studio.tools.values(), key=lambda item: item.name):
            if tool.name in {"user_keyboard_input", "user_mouse_input", "start_stop_play"}:
                continue
            schema = tool.input_schema
            if tool.name == "execute_luau":
                schema = {
                    **schema,
                    "properties": {
                        **schema.get("properties", {}),
                        "_zenless_expected_instances": {
                            "type": "object",
                            "description": "Required post-change expectations: exact game paths mapped to the properties and JSON values that Rubra must read back.",
                        },
                    },
                }
            catalog.append(
                {
                    "name": tool.name,
                    "description": tool.description[:1200],
                    "inputSchema": schema,
                }
            )
        return catalog

    def _protocol_repair(
        self,
        provider: str,
        raw: str,
        task_id: str,
        *,
        kind: str,
        parse_error: ProtocolError,
    ) -> str:
        value = str(raw or "")
        if len(value) > 60_000:
            value = value[:45_000] + "\n...[middle omitted by Rubra protocol recovery]...\n" + value[-15_000:]
        schema = (
            '{"summary":"string","actions":[{"tool":"string","arguments":{},"reason":"string",'
            '"risk":"low|medium|high|critical"}],"final_message":"string","visual_prompt":"string",'
            '"model_3d_prompt":"string","tests":["string"]}'
            if kind == "proposal"
            else '{"verdict":"approve|revise|block","summary":"string","issues":["string"],'
            '"required_changes":["string"],"tests_required":["string"],'
            '"risk":"low|medium|high|critical","confidence":0.0}'
        )
        self._emit(
            task_id,
            Stage.REVISING if kind == "proposal" else Stage.REVIEWING,
            f"{kind.title()} response was incomplete; requesting one bounded protocol repair.",
            "warning",
            str(parse_error)[:1000],
        )
        repair_prompt = (
            "Your previous response could not be parsed as the required Rubra protocol. "
            "Do not execute tools, do not add commentary, and do not repeat analysis. "
            "Return exactly one complete compact JSON object matching this schema:\n"
            f"{schema}\n\n"
            "Preserve the intent and concrete decisions from the previous response. "
            "If content must be shortened, compress prose rather than dropping required fields or actions.\n\n"
            f"PREVIOUS RESPONSE:\n{value}"
        )
        repaired = self._send_agent_prompt(provider, repair_prompt, task_id=task_id, timeout=180)
        sender = "Builder Recovery" if kind == "proposal" else "Reviewer Recovery"
        role = "agent" if kind == "proposal" else "reviewer"
        self.store.append_message(task_id, sender, role, repaired)
        return repaired

    def _parse_proposal_with_recovery(self, provider: str, raw: str, task_id: str) -> AgentProposal:
        try:
            return self._parse_proposal(raw)
        except ProtocolError as first_error:
            repaired = self._protocol_repair(
                provider,
                raw,
                task_id,
                kind="proposal",
                parse_error=first_error,
            )
            try:
                return self._parse_proposal(repaired)
            except ProtocolError as second_error:
                raise ProtocolError(
                    f"Proposal protocol recovery failed: {second_error}; initial parse error: {first_error}"
                ) from second_error

    def _parse_review_with_recovery(self, provider: str, raw: str, task_id: str) -> ReviewResult:
        try:
            return self._parse_review(raw)
        except ProtocolError as first_error:
            repaired = self._protocol_repair(
                provider,
                raw,
                task_id,
                kind="review",
                parse_error=first_error,
            )
            try:
                return self._parse_review(repaired)
            except ProtocolError as second_error:
                raise ProtocolError(
                    f"Review protocol recovery failed: {second_error}; initial parse error: {first_error}"
                ) from second_error

    @staticmethod
    def _parse_proposal(raw: str) -> AgentProposal:
        data = extract_json_object(raw)
        proposal = AgentProposal.from_dict(data, raw)
        if not proposal.summary and not proposal.final_message:
            raise ProtocolError("The proposal contains neither summary nor final_message.")
        if len(proposal.actions) > 16:
            raise ProtocolError("The proposal exceeds 16 actions.")
        if any(not action.tool for action in proposal.actions):
            raise ProtocolError("The proposal contains an action without a tool name.")
        return proposal

    @staticmethod
    def _parse_review(raw: str) -> ReviewResult:
        data = extract_json_object(raw)
        review = ReviewResult.from_dict(data, raw)
        if review.verdict not in {"approve", "approved", "revise", "block"}:
            raise ProtocolError(f"Invalid review verdict: {review.verdict}")
        if not review.summary:
            raise ProtocolError("The review contains no summary.")
        return review

    @staticmethod
    def _console_has_errors(output: str) -> bool:
        if not output.strip():
            return False
        return bool(re.search(r"(?im)(\bexception\b|\btraceback\b|stack begin|(^|\s)error[:\s])", output))

    def _select_builder_provider(self, options: TaskOptions, *, timeout: float) -> str:
        if self._provider_ready("chatgpt", timeout=timeout, options=options):
            return "chatgpt"
        if options.smart_routing and self.bridge.wait_for_provider("gemini", timeout=timeout):
            return "gemini"
        return ""

    def _builder_provider(self, task_id: str) -> str:
        task = self.store.load_task(task_id) or {}
        context = task.get("context") if isinstance(task.get("context"), dict) else {}
        provider = str(context.get("builder_provider") or "chatgpt")
        return provider if provider in {"chatgpt", "gemini"} else "chatgpt"

    def _set_builder_provider(self, task_id: str, provider: str) -> None:
        if provider not in {"chatgpt", "gemini"}:
            raise ValueError(f"Unsupported Builder provider: {provider}")
        self.store.update_context_section(task_id, "builder_provider", provider)

    def _task_attachment_paths(self, task_id: str) -> tuple[Path, ...]:
        task = self.store.load_task(task_id) or {}
        context = task.get("context") if isinstance(task.get("context"), dict) else {}
        raw = context.get("attachment_paths")
        if not isinstance(raw, list):
            return ()
        paths: list[Path] = []
        for value in raw[:5]:
            path = Path(str(value)).expanduser().resolve()
            if path.is_file():
                paths.append(path)
        return tuple(paths)

    def _route_identity(self, provider: str) -> str:
        identify = getattr(self.bridge, "route_identity", None)
        if callable(identify):
            try:
                value = str(identify(provider) or "").strip().casefold()
                if value:
                    return value
            except BridgeError:
                pass
        status_fn = getattr(self.bridge, "provider_status", None)
        if callable(status_fn):
            try:
                status = status_fn().get(provider, {})
                if isinstance(status, dict):
                    value = str(status.get("transport") or "").strip().casefold()
                    if value:
                        return value
            except Exception:
                pass
        return provider

    def _ensure_provider_attachments(
        self,
        provider: str,
        task_id: str,
        paths: tuple[Path, ...],
    ) -> None:
        valid = tuple(path.expanduser().resolve() for path in paths if path.is_file())
        if not valid:
            return
        fingerprint = hashlib.sha256(
            "\0".join(str(path) for path in valid).encode("utf-8", "replace")
        ).hexdigest()[:24]
        route = self._route_identity(provider)
        key = (task_id, provider, route, fingerprint)
        if key in self._attachment_routes:
            return
        result = self.bridge.request(
            provider,
            "upload_files",
            {"files": [str(path) for path in valid]},
            task_id=task_id,
            timeout=120,
        )
        if str(result.get("status", "ok")).casefold() != "ok":
            raise BridgeError(f"{provider} rejected this job's attachments.")
        if "uploaded" in result and int(result.get("uploaded") or 0) != len(valid):
            raise BridgeError(
                f"{provider} confirmed only {int(result.get('uploaded') or 0)} of {len(valid)} attachments."
            )
        actual_route = str(result.get("transport") or self._route_identity(provider) or route).casefold()
        self._attachment_routes.add((task_id, provider, actual_route, fingerprint))

    def _ensure_task_attachments(self, provider: str, task_id: str) -> None:
        self._ensure_provider_attachments(provider, task_id, self._task_attachment_paths(task_id))

    def _builder_smart_routing(self, task_id: str) -> bool:
        task = self.store.load_task(task_id) or {}
        options = task.get("options") if isinstance(task.get("options"), dict) else {}
        return bool(options.get("smart_routing", True))

    def _ensure_builder_attachments(self, task_id: str, paths: tuple[Path, ...]) -> str:
        provider = self._builder_provider(task_id)
        try:
            self._ensure_provider_attachments(provider, task_id, paths)
            return provider
        except BridgeError as primary_error:
            if (
                provider == "chatgpt"
                and self._builder_smart_routing(task_id)
                and self.bridge.wait_for_provider("gemini", timeout=0.75)
            ):
                self._ensure_provider_attachments("gemini", task_id, paths)
                self._set_builder_provider(task_id, "gemini")
                task = self.store.load_task(task_id) or {}
                try:
                    stage = Stage(str(task.get("stage") or Stage.COLLECTING_CONTEXT.value))
                except ValueError:
                    stage = Stage.COLLECTING_CONTEXT
                self._emit(
                    task_id,
                    stage,
                    "Builder attachment capability moved to Gemini.",
                    "warning",
                    str(primary_error)[:1000],
                )
                return "gemini"
            raise

    def _builder_request(
        self,
        task_id: str,
        action: str,
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        provider = self._builder_provider(task_id)
        try:
            return self.bridge.request(provider, action, payload, task_id=task_id, timeout=timeout)
        except BridgeError as primary_error:
            message = str(primary_error).casefold()
            safely_reroutable = any(
                marker in message
                for marker in (
                    "capability_unavailable",
                    "provider_rate_limit",
                    "provider_capacity",
                    "provider_transient_error",
                    "rate limit",
                    "quota exceeded",
                    "high traffic",
                    "overloaded",
                )
            )
            if (
                provider != "chatgpt"
                or not self._builder_smart_routing(task_id)
                or not safely_reroutable
                or not self.bridge.wait_for_provider("gemini", timeout=0.75)
            ):
                raise
            task_attachments = self._task_attachment_paths(task_id)
            if task_attachments:
                self._ensure_provider_attachments("gemini", task_id, task_attachments)
            result = self.bridge.request("gemini", action, payload, task_id=task_id, timeout=timeout)
            self._set_builder_provider(task_id, "gemini")
            task = self.store.load_task(task_id) or {}
            try:
                stage = Stage(str(task.get("stage") or Stage.CREATING.value))
            except ValueError:
                stage = Stage.CREATING
            self._emit(
                task_id,
                stage,
                f"Builder capability {action} moved to Gemini.",
                "warning",
                str(primary_error)[:1000],
            )
            return result

    def _review_provider(self, options: TaskOptions) -> str:
        if self._provider_ready("deepseek", timeout=1.0, options=options):
            return "deepseek"
        if options.smart_routing and self.bridge.wait_for_provider("gemini", timeout=0.75):
            return "gemini"
        return ""

    def _provider_ready(self, provider: str, *, timeout: float, options: TaskOptions) -> bool:
        if not options.smart_routing and provider in {"chatgpt", "deepseek"}:
            web_only = getattr(self.bridge, "wait_for_web_provider", None)
            if callable(web_only):
                return bool(web_only(provider, timeout))
        return self.bridge.wait_for_provider(provider, timeout)

    @staticmethod
    def _should_research(options: TaskOptions, analysis: BrainAnalysis) -> bool:
        if options.research_mode == "off":
            return False
        if options.research_mode == "on":
            return True
        if not options.smart_routing:
            return False
        complex_intents = {"debug", "test", "visual", "3d", "audit"}
        return bool(complex_intents.intersection(analysis.intents)) or len(analysis.keywords) >= 5

    @staticmethod
    def _builder_rounds(options: TaskOptions, analysis: BrainAnalysis) -> int:
        if options.effort_level == "min":
            return 1
        if options.effort_level == "med":
            return 2
        if options.effort_level == "max":
            return 3
        if options.risk_level == "high" or any(intent in {"audit", "debug", "3d"} for intent in analysis.intents):
            return 3
        return 2

    @staticmethod
    def _builder_read_limit(options: TaskOptions) -> int:
        if options.effort_level == "min":
            return 4
        if options.effort_level == "max":
            return 12
        return 8

    @staticmethod
    def _effective_approval_mode(options: TaskOptions) -> str:
        if not options.require_approval and options.approval_mode == "ask":
            return "full_auto"
        return options.approval_mode

    def _requires_change_approval(
        self,
        options: TaskOptions,
        actions: list[ProposalAction],
        review: ReviewResult | None,
    ) -> bool:
        mode = self._effective_approval_mode(options)
        if mode == "full_auto":
            return False
        if mode == "ask":
            return True
        if review is None or not review.approved or review.confidence < 0.75 or review.risk not in {"low", "medium"}:
            return True
        for action in actions:
            if action.risk not in {"low", "medium"}:
                return True
            decision = classify_action(action, set(self.studio.tools))
            if not decision.allowed or decision.risk not in {"low", "medium"}:
                return True
        return False

    def _record_auto_approval(self, task_id: str, gate: str, mode: str) -> None:
        note = f"Automatically approved by Rubra approval mode: {mode}."
        self.store.record_approval(task_id, gate, "approve", note)
        self.store.append_message(task_id, "Rubra", "system", note)

    @staticmethod
    def _proposal_detail(proposal: AgentProposal, review: ReviewResult | None) -> str:
        payload = {
            "summary": proposal.summary,
            "actions": [asdict(action) for action in proposal.actions if not is_read_only(action.tool)],
            "review": review.to_dict() if review else None,
            "tests": proposal.tests,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)[:80_000]

    def _check_control(self, task_id: str, cancel_event: threading.Event) -> None:
        if cancel_event.is_set():
            raise TaskCancelled("Task cancelled by the user.")
        with self._state_lock:
            pause_event = self._pause.get(task_id)
        while pause_event is not None and pause_event.is_set():
            if cancel_event.wait(0.1):
                raise TaskCancelled("Task cancelled by the user.")

    def _emit(
        self,
        task_id: str,
        stage: Stage,
        message: str,
        kind: str = "info",
        detail: str = "",
    ) -> None:
        event = PipelineEvent(task_id, stage, message, kind, detail, now_iso())
        waiting = stage in {
            Stage.WAITING_VISUAL_APPROVAL,
            Stage.WAITING_3D_APPROVAL,
            Stage.WAITING_CHANGE_APPROVAL,
            Stage.PAUSED,
        }
        status = (
            "complete"
            if stage == Stage.COMPLETE
            else (
                "blocked"
                if stage == Stage.BLOCKED
                else ("failed" if stage == Stage.FAILED else ("waiting" if waiting else "running"))
            )
        )
        try:
            current = self.store.load_task(task_id)
            if current is not None:
                validate_stage_transition(str(current["stage"]), stage)
            self.store.update_task(task_id, stage=stage, status=status)
            self.store.append_event(event)
        except InvalidStageTransition:
            raise
        except KeyError:
            return
        if self.event_callback is not None:
            self.event_callback(event)

    def _finish_error(self, task_id: str, stage: Stage, message: str) -> None:
        try:
            self.store.update_task(task_id, error=message)
            self.store.append_message(task_id, "Orchestrator", "error", message)
        except KeyError:
            return
        self._emit(task_id, stage, message, "error")
