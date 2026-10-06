from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .agent_gateway import AgentGateway
from .browser_bridge import BridgeError
from .diagnostics import DiagnosticEvent, ErrorBus
from .event_bus import EventBus
from .local_ai import LocalAIError, LocalAIService
from .managed_browser import ManagedBrowserController
from .models import PipelineEvent, Stage, TaskOptions
from .orchestrator import OrchestratorError, ZenlessOrchestrator
from .policy import is_read_only
from .project_index import ProjectIndexError, ProjectIndexService
from .qa_breaker import QABreaker
from .storage import StorageManager
from .store import SQLiteStore
from .studio_data import active_studio_title, read_tree, script_source, supported_arguments, tree_instances
from .studio_mcp import MCPBusyError, MCPError, MCPToolResult, StudioMCPClient, find_studio_mcp, select_studio_target
from .tool_registry import ToolRegistry
from .toolchain import ToolchainManager
from .webview2_browser import WebView2BrowserController

PROVIDER_LABELS = {
    "chatgpt": "Builder",
    "deepseek": "Reviewer",
    "gemini": "Research & Visual Review",
    "hunyuan": "3D Generator",
}


class CoreError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: int = 400, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details or {}


class _UnavailableStudio:
    def __init__(self, reason: str) -> None:
        self.reason = reason
        self.tools: dict[str, Any] = {}

    @property
    def running(self) -> bool:
        return False

    def start(self) -> None:
        raise MCPError(self.reason)

    def close(self) -> None:
        return

    def list_studios(self) -> list[Any]:
        raise MCPError(self.reason)

    def call_tool(self, *_args: Any, **_kwargs: Any) -> MCPToolResult:
        raise MCPError(self.reason)


def _milliseconds(value: str) -> int:
    try:
        return int(datetime.fromisoformat(value).timestamp() * 1000)
    except TypeError, ValueError:
        return int(time.time() * 1000)


class ZenlessCore:
    DEFAULT_SETTINGS = {
        "models": {
            "chatgpt": {"model": "auto"},
            "deepseek": {"model": "auto"},
            "gemini": {"model": "auto"},
            "hunyuan": {"version": "auto"},
            "smartRouting": True,
        },
        "autoApprove": False,
        "approvalMode": "ASK",
        "maxRevisions": 3,
        "projectRoot": "",
        "semanticIndex": True,
        "localAI": True,
        "bridgePort": 0,
    }

    def __init__(
        self,
        *,
        data_root: Path,
        resource_root: Path,
        diagnostics: ErrorBus | None = None,
    ) -> None:
        self.data_root = data_root.resolve()
        self.resource_root = resource_root.resolve()
        self.data_root.mkdir(parents=True, exist_ok=True)
        self._owns_diagnostics = diagnostics is None
        self.diagnostics = diagnostics or ErrorBus(self.data_root / "logs")
        self.diagnostics.install_global_hooks()
        self.events = EventBus()
        self.store = SQLiteStore(self.data_root / "zenless.db")
        self.storage = StorageManager(self.data_root)
        self.portable_root = Path(os.environ.get("RUBRA_HOME") or self.data_root.parent).expanduser().resolve()
        self.project_index = ProjectIndexService(self.portable_root, self.resource_root)
        self.local_ai = LocalAIService(self.portable_root)
        self.tool_registry = ToolRegistry(self.portable_root, self.resource_root)
        self._closing = threading.Event()
        self._tools_thread: threading.Thread | None = None
        self._tools_state = {"state": "IDLE", "detail": ""}
        self._queue_wake = threading.Event()
        self._queue_thread: threading.Thread | None = None
        self._queue_lock = threading.RLock()
        self._startup_thread: threading.Thread | None = None
        self._provider_threads: dict[str, threading.Thread] = {}
        self._provider_lock = threading.Lock()
        self._settings_lock = threading.RLock()
        self._model_selection_lock = threading.Lock()
        self._studio_lock = threading.RLock()
        self._studio_refresh_lock = threading.Lock()
        self._studio_thread: threading.Thread | None = None
        self._studio_test_id = ""
        self._test_start_lock = threading.Lock()
        self._studio_target_id = ""
        self._studio_label = ""
        self._studio_tree_error = ""
        self._studio_inventory = {"complete": False, "total": 0, "source": ""}
        self._studio_nodes: dict[str, dict[str, Any]] = {}
        self._studio_tree: list[dict[str, Any]] = []
        self._connections = {
            "bridge": "READY",
            "browser": "CONNECTING",
            "chatgpt": "OFF",
            "deepseek": "OFF",
            "gemini": "OFF",
            "hunyuan": "OFF",
            "studio": "CONNECTING",
        }
        self._connections_lock = threading.RLock()
        self._boot_steps = [
            {"stage": "CORE", "state": "READY"},
            {"stage": "STATE", "state": "CONNECTING"},
            {"stage": "BRIDGE", "state": "READY"},
            {"stage": "UI", "state": "CONNECTING"},
            {"stage": "BROWSER", "state": "CONNECTING"},
            {"stage": "AI", "state": "OFF"},
            {"stage": "STUDIO", "state": "CONNECTING"},
        ]
        self._boot_lock = threading.RLock()
        self._model_cache: tuple[float, dict[str, Any]] | None = None

        self.managed_browser = ManagedBrowserController(
            data_root=self.data_root,
            status_callback=self._on_provider_status,
            diagnostics=self.diagnostics,
        )
        self.embedded_browser = WebView2BrowserController(
            data_root=self.data_root,
            status_callback=self._on_provider_status,
            diagnostics=self.diagnostics,
        )
        self.bridge = AgentGateway(
            managed=self.managed_browser,
            embedded=self.embedded_browser,
            status_callback=self._on_provider_status,
            local_available=lambda: bool(self.settings()["localAI"] and self.local_ai.available),
            local_complete=lambda prompt: self.local_ai.complete(
                prompt, max_tokens=2048, temperature=0.15, timeout=300
            ),
            selected_model=lambda provider: str(self.settings()["models"].get(provider, {}).get(
                "version" if provider == "hunyuan" else "model", "auto")),
            local_cancel=self.local_ai.close,
        )
        try:
            self.studio: Any = StudioMCPClient(
                find_studio_mcp(), notification_callback=self._on_mcp_notification, startup_timeout=8
            )
        except MCPError as exc:
            self.studio = _UnavailableStudio(str(exc))
            self._connections["studio"] = "OFF"
            self._set_boot("STUDIO", "OFF")

        tripwire_root = self.portable_root / "runtime" / "tools" / "tripwire"
        tripwire_executable = next(tripwire_root.rglob("tripwire-server.exe"), None) if tripwire_root.exists() else None
        self.tripwire: StudioMCPClient | None = (
            StudioMCPClient(
                tripwire_executable,
                client_name="Rubra Tripwire",
                client_version="1.0.0",
                startup_timeout=60,
            )
            if tripwire_executable is not None
            else None
        )

        self.qa = QABreaker(
            store=self.store,
            studio=self.studio,
            bridge=self.bridge,
            events=self.events,
            tripwire=self.tripwire,
            capture_root=self.data_root / "qa-captures",
            local_ai_callback=self._local_ai_complete,
            portable_root=self.portable_root,
        )
        self.orchestrator = ZenlessOrchestrator(
            store=self.store,
            bridge=self.bridge,
            studio=self.studio,
            run_root=self.data_root / "runs",
            event_callback=self._on_pipeline_event,
            qa_callback=self.qa.run_for_orchestrator,
            project_search_callback=self._project_search_for_orchestrator,
            local_ai_callback=self._local_ai_complete,
            portable_root=self.portable_root,
        )
        self._diagnostic_unsubscribe = self.diagnostics.subscribe(self._on_diagnostic)

    def start(self) -> None:
        if self._startup_thread is not None and self._startup_thread.is_alive():
            return
        self._startup_thread = threading.Thread(
            target=self._start_services,
            name="Rubra-Core-Startup",
            daemon=True,
        )
        self._startup_thread.start()

    def close(self) -> None:
        if self._closing.is_set():
            return
        self._closing.set()
        self._queue_wake.set()
        current = self.orchestrator.current_task_id
        if current:
            self.orchestrator.cancel(current)
            self.qa.stop(current)
        self.qa.stop_all()
        self.bridge.stop()
        self.orchestrator.wait_for_idle(3.0)
        self.qa.wait_for_manual_tests(3.0)
        self.studio.close()
        if self.tripwire is not None:
            self.tripwire.close()
        self.project_index.close()
        self.local_ai.close()
        with self._provider_lock:
            threads = tuple(self._provider_threads.values())
        background = (
            self._startup_thread,
            self._tools_thread,
            self._queue_thread,
            self._studio_thread,
            *threads,
        )
        for thread in background:
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=1.0)
        self.store.maintenance()
        self._diagnostic_unsubscribe()
        if self._owns_diagnostics:
            self.diagnostics.close()

    def set_runtime_port(self, port: int) -> None:
        with self._settings_lock:
            settings = self.settings()
            settings["bridgePort"] = int(port)
            self.store.set_setting("ui.settings", settings)

    def bootstrap(self) -> dict[str, Any]:
        with self._boot_lock:
            return {"steps": [dict(item) for item in self._boot_steps]}

    def status(self) -> dict[str, Any]:
        return {"ready": not self._closing.is_set()}

    def connections(self) -> dict[str, str]:
        bridge = getattr(self, "bridge", None)
        if bridge is not None and not self._closing.is_set():
            try:
                statuses = bridge.provider_status()
            except Exception:
                statuses = {}
            if statuses:
                with self._connections_lock:
                    for provider in ("chatgpt", "deepseek", "gemini", "hunyuan"):
                        raw = str(statuses.get(provider, {}).get("state") or "")
                        if not raw:
                            continue
                        normalized = "LOGIN" if raw.casefold() == "standby" else self._normalize_connection(raw)
                        thread = self._provider_threads.get(provider)
                        if thread is not None and thread.is_alive() and normalized not in {"READY", "LOGIN"}:
                            continue
                        self._connections[provider] = normalized
        with self._connections_lock:
            return dict(self._connections)

    def tools_payload(self) -> list[dict[str, Any]]:
        return self.tool_registry.descriptors()

    def tool_summary(self) -> dict[str, int]:
        return self.tool_registry.summary()

    def agents(self) -> list[dict[str, Any]]:
        connections = self.connections()
        models = self.settings()["models"]
        return [
            {
                "id": "chatgpt",
                "name": PROVIDER_LABELS["chatgpt"],
                "status": connections["chatgpt"],
                "model": models["chatgpt"]["model"],
            },
            {
                "id": "deepseek",
                "name": PROVIDER_LABELS["deepseek"],
                "status": connections["deepseek"],
                "model": models["deepseek"]["model"],
            },
            {
                "id": "gemini",
                "name": PROVIDER_LABELS["gemini"],
                "status": connections["gemini"],
                "model": models["gemini"]["model"],
            },
            {
                "id": "hunyuan",
                "name": PROVIDER_LABELS["hunyuan"],
                "status": connections["hunyuan"],
                "version": models["hunyuan"]["version"],
            },
            {"id": "studio", "name": "Studio", "status": connections["studio"]},
        ]

    def login_provider(self, provider: str) -> bool:
        if provider not in {"chatgpt", "deepseek", "gemini", "hunyuan"}:
            raise CoreError("UNKNOWN_PROVIDER", "Unknown provider.", status=404)
        with self._provider_lock:
            existing = self._provider_threads.get(provider)
            if existing is not None and existing.is_alive():
                return True
            thread = threading.Thread(
                target=self._login_worker,
                args=(provider,),
                name=f"Rubra-Login-{provider}",
                daemon=True,
            )
            self._provider_threads[provider] = thread
            thread.start()
        return True

    def jobs(self) -> list[dict[str, Any]]:
        return [self._task_to_job(task) for task in self.store.recent_tasks(100)]

    def job(self, job_id: str) -> dict[str, Any]:
        task = self.store.load_task(job_id)
        if task is None:
            raise CoreError("JOB_NOT_FOUND", "Job not found.", status=404)
        return self._task_to_job(task)

    def _create_job(
        self,
        title: str,
        options: dict[str, Any] | None = None,
        *,
        attachments: tuple[Path, ...] = (),
        parent_job_id: str = "",
    ) -> tuple[dict[str, Any], int]:
        prepared_job: dict[str, Any] | None = None
        initial_message_id = 0

        def prepare(task_id: str, _message_id: int) -> None:
            for path in attachments:
                self._register_file_asset(path, job_id=task_id, kind="IMG" if self._is_image(path) else "RBX")

        def ready(task_id: str, message_id: int) -> None:
            nonlocal prepared_job, initial_message_id
            prepared_job = self.job(task_id)
            initial_message_id = message_id

        try:
            self.orchestrator.submit(
                title,
                TaskOptions.from_api(options),
                attachment_paths=attachments,
                studio_id=self._studio_target_id if self.connections()["studio"] == "READY" else "",
                parent_task_id=parent_job_id,
                prepare_callback=prepare if attachments else None,
                ready_callback=ready,
            )
        except OrchestratorError as exc:
            raise CoreError("JOB_BUSY", str(exc), status=409) from exc
        if prepared_job is None or initial_message_id <= 0:
            raise CoreError("JOB_PREPARATION_FAILED", "The job could not be prepared before execution.", status=500)
        return prepared_job, initial_message_id

    def create_job(
        self,
        title: str,
        options: dict[str, Any] | None = None,
        *,
        attachments: tuple[Path, ...] = (),
        parent_job_id: str = "",
    ) -> dict[str, Any]:
        job, _ = self._create_job(
            title,
            options,
            attachments=attachments,
            parent_job_id=parent_job_id,
        )
        return job

    def pause_job(self, job_id: str) -> dict[str, Any]:
        if not self.orchestrator.pause(job_id):
            raise CoreError("JOB_NOT_PAUSABLE", "The job cannot be paused in its current state.", status=409)
        return self.job(job_id)

    def resume_job(self, job_id: str) -> dict[str, Any]:
        if self.orchestrator.resume(job_id):
            return self.job(job_id)
        task = self._require_task(job_id)
        recovery_error = str(task.get("error") or "")
        recovered_checkpoint = (
            "Checkpoint recovered after an unexpected shutdown" in recovery_error
            or "Checkpoint recuperado" in recovery_error
            or recovery_error.startswith("RECOVERED_CHECKPOINT:")
        )
        if str(task.get("stage")) != Stage.PAUSED.value or not recovered_checkpoint:
            raise CoreError("JOB_NOT_RESUMABLE", "The job is not a recoverable paused checkpoint.", status=409)
        try:
            options = TaskOptions(**dict(task.get("options") or {}))
            replacement_id = self.orchestrator.submit(
                str(task.get("prompt") or ""),
                options,
                parent_task_id=job_id,
            )
        except (TypeError, OrchestratorError) as exc:
            raise CoreError("JOB_NOT_RESUMABLE", str(exc), status=409) from exc
        self.store.update_task(
            job_id,
            stage=Stage.BLOCKED,
            status="blocked",
            error=f"Safely restarted as {replacement_id}; no previous write was repeated.",
        )
        self.store.append_message(job_id, "Recovery", "system", f"Replacement job: {replacement_id}")
        return self.job(replacement_id)

    def cancel_job(self, job_id: str) -> bool:
        stopped = self.qa.stop(job_id)
        cancelled = self.orchestrator.cancel(job_id)
        if stopped or cancelled:
            return True
        task = self._require_task(job_id)
        recovery_error = str(task.get("error") or "")
        if str(task.get("stage")) == Stage.PAUSED.value and (
            recovery_error.startswith("RECOVERED_CHECKPOINT:")
            or "Checkpoint recovered after an unexpected shutdown" in recovery_error
            or "Checkpoint recuperado" in recovery_error
        ):
            self.store.update_task(
                job_id,
                stage=Stage.BLOCKED,
                status="blocked",
                error="Recovered checkpoint cancelled by the user.",
                final_text="Recovered task cancelled.",
            )
            self.store.append_message(job_id, "Recovery", "system", "Recovered task cancelled by the user.")
            return True
        return False

    def send_chat(
        self,
        content: str,
        job_id: str | None,
        attachments: tuple[Path, ...],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        objective = content.strip()
        if not objective:
            objective = "Analyze the submitted attachments and implement the compatible Studio request."
        if job_id:
            existing = self.store.load_task(job_id)
            if existing is None:
                raise CoreError("JOB_NOT_FOUND", "The conversation task no longer exists.", status=404)
            if str(existing.get("status")) in {"running", "waiting"}:
                raise CoreError(
                    "JOB_ALREADY_RUNNING",
                    "The current job is still running. Pause, complete, or cancel it before sending another request.",
                    status=409,
                )
        effective_options = dict(options or {})
        current_settings = self.settings()
        model_settings = current_settings.get("models")
        if not isinstance(model_settings, dict):
            model_settings = {}
        effective_options.setdefault("smartRouting", bool(model_settings.get("smartRouting", True)))
        effective_options.setdefault("revisions", int(current_settings.get("maxRevisions", 3)))
        effective_options.setdefault(
            "approvalMode",
            str(
                current_settings.get("approvalMode")
                or ("FULL_AUTO" if bool(current_settings.get("autoApprove", False)) else "ASK")
            ),
        )
        task_options = TaskOptions.from_api(effective_options)
        self._preflight_providers(task_options)
        job, message_row_id = self._create_job(
            objective,
            options=effective_options,
            attachments=attachments,
            parent_job_id=job_id or "",
        )
        return {"messageId": f"msg-{message_row_id}", "jobId": job["id"]}

    def cancel_generation(self, job_id: str) -> bool:
        result = self.cancel_job(job_id)
        for provider in ("chatgpt", "deepseek", "gemini", "hunyuan"):
            try:
                if self.bridge.wait_for_provider(provider, timeout=0.1):
                    self.bridge.request(provider, "cancel", {}, task_id=job_id, timeout=5)
            except BridgeError:
                continue
        return result

    def _preflight_providers(self, options: TaskOptions) -> None:
        required = ["chatgpt"]
        if options.independent_review and not options.smart_routing:
            required.append("deepseek")
        if options.create_3d_asset:
            required.append("hunyuan")
        if options.research_mode == "on":
            required.append("gemini")
        for provider in required:
            web_only = not options.smart_routing and provider in {"chatgpt", "deepseek"}
            if not web_only and self.connections()[provider] == "READY":
                continue
            try:
                if web_only:
                    wait_for_web = getattr(self.bridge, "wait_for_web_provider", None)
                    ready = bool(wait_for_web(provider, 0.5)) if callable(wait_for_web) else False
                else:
                    ready = self.bridge.wait_for_provider(provider, timeout=0.5)
            except BridgeError as exc:
                self._set_connection(provider, "ERR")
                raise CoreError(
                    "PROVIDER_UNAVAILABLE",
                    f"{PROVIDER_LABELS[provider]} is unavailable.",
                    status=503,
                    details={"provider": provider},
                ) from exc
            if ready:
                self._set_connection(provider, "READY")
                continue
            if self.connections()[provider] != "ERR":
                self._set_connection(provider, "LOGIN")
            raise CoreError(
                "PROVIDER_LOGIN_REQUIRED",
                f"{PROVIDER_LABELS[provider]} requires login.",
                status=409,
                details={"provider": provider},
            )

    def prompt_queue(self) -> dict[str, Any]:
        return {
            "items": [self._queue_item_payload(item) for item in self.store.prompt_queue_items()],
            "config": self._prompt_queue_config(),
        }

    def enqueue_prompt(
        self,
        content: str,
        *,
        parent_job_id: str = "",
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        text = content.strip()
        if not text:
            raise CoreError("EMPTY_QUEUE_PROMPT", "Queued prompt is empty.")
        if len(text) > 32_000:
            raise CoreError("QUEUE_PROMPT_TOO_LARGE", "Queued prompts are limited to 32,000 characters.")
        items = self.store.prompt_queue_items(128)
        pending = [item for item in items if item["state"] not in {"completed", "cancelled"}]
        if len(pending) >= 64:
            raise CoreError("QUEUE_FULL", "The prompt queue already contains 64 pending items.", status=409)
        if parent_job_id and self.store.load_task(parent_job_id) is None:
            raise CoreError("JOB_NOT_FOUND", "The queue parent task no longer exists.", status=404)
        config = self._prompt_queue_config()
        item = self.store.enqueue_prompt(
            uuid.uuid4().hex,
            text,
            parent_job_id=parent_job_id,
            options=dict(options or {}),
            max_attempts=int(config["maxAttempts"]),
        )
        self._publish_prompt_queue()
        self._queue_wake.set()
        return self._queue_item_payload(item)

    def update_prompt_queue_item(
        self,
        queue_id: str,
        *,
        content: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item = self.store.prompt_queue_item(queue_id)
        if item is None:
            raise CoreError("QUEUE_ITEM_NOT_FOUND", "Prompt queue item not found.", status=404)
        if item["state"] in {"preparing", "inflight"}:
            raise CoreError("QUEUE_ITEM_ACTIVE", "An active queue item cannot be edited.", status=409)
        changes: dict[str, Any] = {}
        if content is not None:
            text = content.strip()
            if not text:
                raise CoreError("EMPTY_QUEUE_PROMPT", "Queued prompt is empty.")
            if len(text) > 32_000:
                raise CoreError("QUEUE_PROMPT_TOO_LARGE", "Queued prompts are limited to 32,000 characters.")
            changes["content"] = text
        if options is not None:
            changes["options_json"] = dict(options)
        if changes:
            self.store.update_prompt_queue_item(queue_id, **changes)
        self._publish_prompt_queue()
        return self._queue_item_payload(self.store.prompt_queue_item(queue_id) or item)

    def retry_prompt_queue_item(self, queue_id: str) -> dict[str, Any]:
        item = self.store.prompt_queue_item(queue_id)
        if item is None:
            raise CoreError("QUEUE_ITEM_NOT_FOUND", "Prompt queue item not found.", status=404)
        if item["state"] not in {"blocked", "failed"}:
            raise CoreError("QUEUE_ITEM_NOT_RETRYABLE", "Only blocked or failed queue items can be retried.", status=409)
        self.store.update_prompt_queue_item(
            queue_id,
            state="queued",
            attempts=0,
            dispatched_job_id="",
            last_error="",
            next_attempt_at="",
        )
        self._publish_prompt_queue()
        self._queue_wake.set()
        return self._queue_item_payload(self.store.prompt_queue_item(queue_id) or item)

    def delete_prompt_queue_item(self, queue_id: str) -> bool:
        item = self.store.prompt_queue_item(queue_id)
        if item is None:
            return False
        if item["state"] in {"preparing", "inflight"}:
            raise CoreError("QUEUE_ITEM_ACTIVE", "Pause or cancel the active job before removing its queue item.", status=409)
        deleted = self.store.delete_prompt_queue_item(queue_id)
        if deleted:
            self._publish_prompt_queue()
            self._queue_wake.set()
        return deleted

    def move_prompt_queue_item(self, queue_id: str, direction: int) -> dict[str, Any]:
        items = self.store.prompt_queue_items(128)
        movable = [item for item in items if item["state"] not in {"preparing", "inflight"}]
        index = next((i for i, item in enumerate(movable) if item["id"] == queue_id), -1)
        if index < 0:
            raise CoreError("QUEUE_ITEM_NOT_MOVABLE", "Prompt queue item cannot be moved.", status=409)
        target = max(0, min(len(movable) - 1, index + (-1 if direction < 0 else 1)))
        if target != index:
            movable[index], movable[target] = movable[target], movable[index]
            active = [item for item in items if item["state"] in {"preparing", "inflight"}]
            self.store.reorder_prompt_queue([*(item["id"] for item in active), *(item["id"] for item in movable)])
        self._publish_prompt_queue()
        return self.prompt_queue()

    def update_prompt_queue_config(self, patch: dict[str, Any]) -> dict[str, Any]:
        config = self._prompt_queue_config()
        if "paused" in patch:
            config["paused"] = TaskOptions._boolean(patch["paused"], bool(config["paused"]))
        if "continueOnFailure" in patch:
            config["continueOnFailure"] = TaskOptions._boolean(
                patch["continueOnFailure"], bool(config["continueOnFailure"])
            )
        if "chainConversation" in patch:
            config["chainConversation"] = TaskOptions._boolean(
                patch["chainConversation"], bool(config["chainConversation"])
            )
        if "delaySeconds" in patch:
            try:
                config["delaySeconds"] = max(0, min(300, int(patch["delaySeconds"])))
            except TypeError, ValueError:
                pass
        max_attempts_changed = False
        if "maxAttempts" in patch:
            try:
                config["maxAttempts"] = max(1, min(8, int(patch["maxAttempts"])))
                max_attempts_changed = True
            except TypeError, ValueError:
                pass
        self.store.set_setting("prompt_queue.config", config)
        if max_attempts_changed:
            for item in self.store.prompt_queue_items(128):
                if item["state"] in {"queued", "blocked", "failed"}:
                    self.store.update_prompt_queue_item(
                        item["id"],
                        max_attempts=max(int(item.get("attempts") or 0) + 1, int(config["maxAttempts"])),
                    )
        self._publish_prompt_queue()
        self._queue_wake.set()
        return config

    def _prompt_queue_config(self) -> dict[str, Any]:
        defaults = {
            "paused": False,
            "continueOnFailure": False,
            "chainConversation": True,
            "delaySeconds": 2,
            "maxAttempts": 3,
        }
        raw = self.store.get_setting("prompt_queue.config", {})
        if isinstance(raw, dict):
            defaults.update({key: raw[key] for key in defaults if key in raw})
        defaults["paused"] = bool(defaults["paused"])
        defaults["continueOnFailure"] = bool(defaults["continueOnFailure"])
        defaults["chainConversation"] = bool(defaults["chainConversation"])
        try:
            defaults["delaySeconds"] = max(0, min(300, int(defaults["delaySeconds"])))
        except TypeError, ValueError:
            defaults["delaySeconds"] = 2
        try:
            defaults["maxAttempts"] = max(1, min(8, int(defaults["maxAttempts"])))
        except TypeError, ValueError:
            defaults["maxAttempts"] = 3
        return defaults

    def _start_prompt_queue(self) -> None:
        with self._queue_lock:
            if self._queue_thread is not None and self._queue_thread.is_alive():
                return
            self._queue_thread = threading.Thread(
                target=self._prompt_queue_loop,
                name="Rubra-Prompt-Queue",
                daemon=True,
            )
            self._queue_thread.start()
        self._queue_wake.set()

    def _prompt_queue_loop(self) -> None:
        while not self._closing.is_set():
            self._queue_wake.clear()
            try:
                self._prompt_queue_tick()
            except Exception as exc:
                if not self._closing.is_set():
                    self._report(
                        "queue",
                        "dispatcher",
                        exc,
                        "Prompt delivery was paused fail-closed. Inspect the queue item and retry it explicitly.",
                        probable_cause="The durable queue dispatcher hit an unexpected internal failure.",
                        impact="No ambiguous prompt is automatically resent.",
                    )
                    config = self._prompt_queue_config()
                    config["paused"] = True
                    self.store.set_setting("prompt_queue.config", config)
                    self._publish_prompt_queue()
            self._queue_wake.wait(30.0)

    def _prompt_queue_tick(self) -> None:
        items = self.store.prompt_queue_items(128)
        changed = False
        config = self._prompt_queue_config()

        for item in items:
            if item["state"] != "inflight":
                continue
            job_id = str(item.get("dispatched_job_id") or "")
            task = self.store.load_task(job_id) if job_id else None
            if task is None:
                self.store.update_prompt_queue_item(
                    item["id"],
                    state="blocked",
                    last_error="The dispatched task cannot be found; automatic resend is blocked to prevent duplication.",
                )
                changed = True
                if not config["continueOnFailure"]:
                    config["paused"] = True
                    self.store.set_setting("prompt_queue.config", config)
                continue
            status = str(task.get("status") or "").casefold()
            if status == "complete":
                self.store.update_prompt_queue_item(item["id"], state="completed", last_error="")
                changed = True
            elif status in {"failed", "blocked"}:
                error = str(task.get("error") or task.get("final_text") or "Queued task failed.")
                self.store.update_prompt_queue_item(item["id"], state="failed", last_error=error[:4000])
                changed = True
                if not config["continueOnFailure"]:
                    config["paused"] = True
                    self.store.set_setting("prompt_queue.config", config)

        if changed:
            items = self.store.prompt_queue_items(128)
            self._publish_prompt_queue(items)
        if config["paused"] or any(item["state"] in {"preparing", "inflight"} for item in items):
            return
        if self.orchestrator.current_task_id:
            return

        now = datetime.now(UTC)
        candidate: dict[str, Any] | None = None
        for item in items:
            if item["state"] != "queued":
                continue
            next_attempt = str(item.get("next_attempt_at") or "")
            if next_attempt:
                try:
                    if datetime.fromisoformat(next_attempt) > now:
                        continue
                except ValueError:
                    pass
            candidate = item
            break
        if candidate is None:
            return

        if config["delaySeconds"]:
            previous = None
            for item in items:
                if item["id"] == candidate["id"]:
                    break
                previous = item
            if previous is not None and previous["state"] == "completed":
                try:
                    not_before = datetime.fromisoformat(str(previous["updated_at"])) + timedelta(
                        seconds=int(config["delaySeconds"])
                    )
                    if now < not_before:
                        return
                except ValueError:
                    pass

        previous_job_id = ""
        if config["chainConversation"]:
            for item in items:
                if item["id"] == candidate["id"]:
                    break
                if item["state"] == "completed" and item.get("dispatched_job_id"):
                    previous_job_id = str(item["dispatched_job_id"])
        parent_job_id = previous_job_id or str(candidate.get("parent_job_id") or "")
        attempts = int(candidate.get("attempts") or 0) + 1
        self.store.update_prompt_queue_item(
            candidate["id"],
            state="preparing",
            attempts=attempts,
            last_error="",
            next_attempt_at="",
        )
        self._publish_prompt_queue()
        try:
            response = self.send_chat(
                str(candidate["content"]),
                parent_job_id or None,
                (),
                dict(candidate.get("options") or {}),
            )
        except CoreError as exc:
            block_codes = {
                "PROVIDER_LOGIN_REQUIRED",
                "PROVIDER_UNAVAILABLE",
                "JOB_NOT_FOUND",
                "QUEUE_PROMPT_TOO_LARGE",
            }
            if exc.code in block_codes:
                state = "blocked"
                next_attempt_at = ""
            elif attempts < int(candidate.get("max_attempts") or config["maxAttempts"]):
                state = "queued"
                delay = min(60, 5 * (2 ** max(0, attempts - 1)))
                next_attempt_at = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat(timespec="seconds")
            else:
                state = "failed"
                next_attempt_at = ""
            self.store.update_prompt_queue_item(
                candidate["id"],
                state=state,
                last_error=f"{exc.code}: {exc}"[:4000],
                next_attempt_at=next_attempt_at,
            )
            if state in {"blocked", "failed"} and not config["continueOnFailure"]:
                config["paused"] = True
                self.store.set_setting("prompt_queue.config", config)
            self._publish_prompt_queue()
            return
        except Exception as exc:
            self.store.update_prompt_queue_item(
                candidate["id"],
                state="blocked",
                last_error=(
                    "Delivery outcome is uncertain; automatic resend was blocked to prevent duplication. "
                    + str(exc)
                )[:4000],
                next_attempt_at="",
            )
            self._publish_prompt_queue()
            raise

        job_id = str(response.get("jobId") or "")
        if not job_id:
            self.store.update_prompt_queue_item(
                candidate["id"],
                state="blocked",
                last_error="Dispatch returned no job identity; automatic resend was blocked.",
            )
        else:
            self.store.update_prompt_queue_item(
                candidate["id"],
                state="inflight",
                dispatched_job_id=job_id,
                last_error="",
            )
        self._publish_prompt_queue()

    def _publish_prompt_queue(self, items: list[dict[str, Any]] | None = None) -> None:
        payload = {
            "items": [self._queue_item_payload(item) for item in (items or self.store.prompt_queue_items())],
            "config": self._prompt_queue_config(),
        }
        self.events.publish("PROMPT_QUEUE_CHANGED", payload)

    @staticmethod
    def _queue_item_payload(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(item["id"]),
            "position": int(item.get("position") or 0),
            "state": str(item.get("state") or "queued").upper(),
            "content": str(item.get("content") or ""),
            "parentJobId": str(item.get("parent_job_id") or "") or None,
            "jobId": str(item.get("dispatched_job_id") or "") or None,
            "attempts": int(item.get("attempts") or 0),
            "maxAttempts": int(item.get("max_attempts") or 3),
            "lastError": str(item.get("last_error") or ""),
            "nextAttemptAt": str(item.get("next_attempt_at") or ""),
            "createdAt": _milliseconds(str(item.get("created_at") or "")),
            "updatedAt": _milliseconds(str(item.get("updated_at") or "")),
            "options": dict(item.get("options") or {}),
        }

    def messages(self, job_id: str) -> list[dict[str, Any]]:
        result = []
        for row in self.store.task_messages(job_id):
            stored_role = str(row["role"]).casefold()
            role = "user" if stored_role == "user" else ("system" if stored_role in {"error", "system"} else "zenless")
            message = {
                "id": f"msg-{row['id']}",
                "role": role,
                "content": row["content"],
                "timestamp": _milliseconds(row["created_at"]),
                "jobId": job_id,
            }
            action = self._message_action(str(row["content"]))
            if action:
                message["action"] = action
            result.append(message)
        return result

    @staticmethod
    def _message_action(content: str) -> dict[str, str] | None:
        normalized = content.casefold()
        if "login" not in normalized and "authenticate" not in normalized:
            return None
        for provider, label in PROVIDER_LABELS.items():
            if provider in normalized or label.casefold() in normalized:
                return {"type": "LOGIN", "provider": provider}
        return None

    def context(self, job_id: str, *, refresh: bool = False) -> list[dict[str, Any]]:
        task = self.store.load_task(job_id)
        if task is None:
            raise CoreError("JOB_NOT_FOUND", "Job not found.", status=404)
        stored = self.store.context_items(job_id)
        if stored and not refresh:
            return [self._public_context(item) for item in stored]

        context = dict(task.get("context") or {}) if isinstance(task.get("context"), dict) else {}
        if refresh:
            self.refresh_studio()
            relevant_classes = {
                "Script", "LocalScript", "ModuleScript", "RemoteEvent", "RemoteFunction",
                "Folder", "Workspace", "ReplicatedStorage", "ServerScriptService", "StarterPlayer", "StarterGui",
            }
            with self._studio_lock:
                live_nodes = [
                    {
                        "name": str(node.get("name") or ""),
                        "path": str(node.get("path") or ""),
                        "className": str(node.get("className") or "Instance"),
                    }
                    for node in self._studio_nodes.values()
                    if str(node.get("path") or "") and str(node.get("className") or "Instance") in relevant_classes
                ][:500]
            context["live_studio_nodes"] = live_nodes

        items = self._derive_context_items(job_id, context)
        if stored:
            state_by_path = {str(item.get("path") or ""): str(item.get("state") or "included") for item in stored}
            for item in items:
                prior = state_by_path.get(str(item.get("path") or ""))
                if prior in {"included", "excluded", "locked"}:
                    item["state"] = prior
        self.store.replace_context_items(job_id, items)
        return [self._public_context(item) for item in items]

    def context_item(self, item_id: str) -> dict[str, Any]:
        item = self.store.context_item(item_id)
        if item is None:
            raise CoreError("CONTEXT_NOT_FOUND", "Context item not found.", status=404)
        return self._public_context(item)

    def set_context_state(self, item_id: str, state: str) -> bool:
        if not self.store.set_context_state(item_id, state):
            raise CoreError("CONTEXT_NOT_FOUND", "Context item not found.", status=404)
        item = self.store.context_item(item_id)
        if item:
            self.events.publish(
                "CONTEXT_UPDATED",
                {"jobId": str(item["job_id"]), "items": self.context(str(item["job_id"]))},
            )
        return True

    def changes(self, job_id: str) -> list[dict[str, Any]]:
        task = self._require_task(job_id)
        proposal = task.get("proposal") or {}
        files: list[dict[str, Any]] = []
        for index, raw in enumerate(proposal.get("actions") or []):
            if not isinstance(raw, dict):
                continue
            tool = str(raw.get("tool", ""))
            if is_read_only(tool):
                continue
            raw_arguments = raw.get("arguments")
            arguments: dict[str, Any] = raw_arguments if isinstance(raw_arguments, dict) else {}
            name = str(
                arguments.get("file_path")
                or arguments.get("target_file")
                or arguments.get("path")
                or tool
                or "change"
            )
            diff: list[dict[str, Any]] = []
            additions = 0
            deletions = 0

            if tool == "multi_edit" and isinstance(arguments.get("edits"), list):
                for edit_index, edit in enumerate(arguments["edits"], start=1):
                    if not isinstance(edit, dict):
                        continue
                    old = str(edit.get("old_string") or "")
                    new = str(edit.get("new_string") or "")
                    diff.append({"type": "hunk", "content": f"@@ replacement {edit_index} @@"})
                    old_lines = old.splitlines()
                    new_lines = new.splitlines()
                    diff.extend({"type": "removed", "content": line} for line in old_lines)
                    diff.extend({"type": "added", "content": line} for line in new_lines)
                    deletions += len(old_lines)
                    additions += len(new_lines)
            elif tool == "execute_luau" and isinstance(arguments.get("code"), str):
                code_lines = str(arguments["code"]).splitlines()
                diff = [
                    {"type": "hunk", "content": "@@ bounded Studio scene change @@"},
                    *({"type": "added", "content": line} for line in code_lines),
                ]
                additions = len(code_lines)
            else:
                public_arguments = {
                    key: value for key, value in arguments.items() if not str(key).startswith("_zenless_")
                }
                content = json.dumps(public_arguments, ensure_ascii=False, indent=2)
                diff = [
                    {"type": "hunk", "content": f"@@ Studio {tool} @@"},
                    *(
                        {"type": "added", "content": line}
                        for line in content.splitlines()
                    ),
                ]
                additions = len(content.splitlines())

            files.append(
                {
                    "id": f"change-{job_id[:10]}-{index}",
                    "name": name,
                    "status": "M",
                    "additions": additions,
                    "deletions": deletions,
                    "diff": diff,
                }
            )
        return files


    def review(self, job_id: str) -> dict[str, Any]:
        task = self._require_task(job_id)
        raw = task.get("review") or {}
        verdict = str(raw.get("verdict", "revise")).casefold()
        decision = "APPROVE" if verdict in {"approve", "approved"} else ("BLOCK" if verdict == "block" else "REVISE")
        risk = str(raw.get("risk", "medium")).upper()
        if risk not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
            risk = "MEDIUM"
        issues = [str(item) for item in raw.get("issues", [])]
        return {
            "decision": decision,
            "risk": risk,
            "criticalIssues": issues if risk in {"HIGH", "CRITICAL"} else [],
            "warnings": issues if risk not in {"HIGH", "CRITICAL"} else [],
            "suggestions": [str(item) for item in raw.get("required_changes", [])],
            "summary": str(raw.get("summary", "")),
            "reviewer": "Reviewer",
            "timestamp": _milliseconds(task["updated_at"]),
            "files": self.changes(job_id),
            "ready": bool(raw),
        }

    def approve_changes(self, job_id: str, approved: bool, note: str = "") -> bool:
        decision = "approve" if approved else "reject"
        if not self.orchestrator.approve_active(job_id, ("changes:", "repair:"), decision, note):
            raise CoreError("NO_CHANGE_GATE", "No change is waiting for a decision.", status=409)
        return True

    def edit_changes(self, job_id: str, file_id: str, content: str) -> bool:
        note = content.strip()
        if not note:
            raise CoreError("EMPTY_EDIT", "The revision request is empty.")
        target = next((item for item in self.changes(job_id) if item["id"] == file_id), None)
        if target is None:
            raise CoreError("CHANGE_NOT_FOUND", "The selected proposed change no longer exists.", status=404)
        feedback = f"Requested changes for {target['name']}:\n{note}"
        if not self.orchestrator.approve_active(job_id, ("changes:", "repair:"), "edit", feedback):
            raise CoreError("NO_CHANGE_GATE", "No change is waiting for a revision request.", status=409)
        return True

    def visual(self, job_id: str) -> dict[str, Any]:
        task = self._require_task(job_id)
        context = task.get("context") or {}
        raw_visual = context.get("visual") if isinstance(context, dict) else None
        visual: dict[str, Any] = raw_visual if isinstance(raw_visual, dict) else {}
        persisted_status = str(visual.get("status") or "")
        views = []
        for name in ("FRONT", "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM"):
            entry = visual.get(name.casefold(), {}) if isinstance(visual, dict) else {}
            asset_id = str(entry.get("asset_id", "")) if isinstance(entry, dict) else ""
            view_state = "APPROVED" if asset_id and persisted_status == "APPROVED" else ("READY" if asset_id else "EMPTY")
            views.append(
                {
                    "name": name,
                    "state": view_state,
                    **({"imageUrl": f"/api/assets/{asset_id}/content"} if asset_id else {}),
                }
            )
        proposal = task.get("proposal") or {}
        prompt = str(visual.get("prompt") or proposal.get("visual_prompt", ""))
        stage = str(task.get("stage", ""))
        if persisted_status:
            status = persisted_status
        elif stage == Stage.GENERATING_CONCEPT.value:
            status = "GENERATING"
        elif stage == Stage.WAITING_IMAGE_APPROVAL.value:
            status = "READY"
        elif stage in {Stage.FAILED.value, Stage.BLOCKED.value}:
            status = "FAILED"
        else:
            status = "IDLE" if not prompt else "PENDING"
        return {
            "views": views,
            "concept": {
                "version": int(visual.get("version") or (1 if prompt else 0)),
                "status": status,
                "prompt": prompt,
                "qa": visual.get("qa") or {},
            },
        }

    def approve_visual(self, job_id: str) -> bool:
        if not self.orchestrator.approve_active(job_id, ("visual",), "approve"):
            raise CoreError("NO_VISUAL_GATE", "No visual concept is waiting for approval.", status=409)
        self.events.publish("VISUAL_APPROVED", {"jobId": job_id})
        return True

    def edit_visual(self, job_id: str, prompt: str) -> bool:
        if not prompt.strip():
            raise CoreError("EMPTY_VISUAL_EDIT", "Describe the requested visual adjustment.")
        if not self.orchestrator.approve_active(job_id, ("visual",), "edit", prompt):
            raise CoreError("NO_VISUAL_GATE", "No visual concept is waiting for an edit.", status=409)
        return True

    def regenerate_visual(self, job_id: str, view: str = "") -> bool:
        normalized = view.strip().casefold()
        if normalized and normalized not in {"front", "back", "left", "right", "top", "bottom"}:
            raise CoreError("INVALID_VISUAL_VIEW", "Invalid visual view.")
        note = f"regen:view:{normalized}" if normalized else "regen:all"
        if not self.orchestrator.approve_active(job_id, ("visual",), "edit", note):
            raise CoreError("NO_VISUAL_GATE", "No visual concept is waiting for regeneration.", status=409)
        return True

    def model(self, job_id: str) -> dict[str, Any]:
        task = self._require_task(job_id)
        context = task.get("context") if isinstance(task.get("context"), dict) else {}
        raw_model = context.get("model") if isinstance(context, dict) else None
        model: dict[str, Any] = raw_model if isinstance(raw_model, dict) else {}
        stage = str(task.get("stage", ""))
        final_asset_id = str(model.get("asset_id") or "")
        asset = self.store.asset(final_asset_id) if final_asset_id else None
        if asset is None:
            assets = [candidate for candidate in self.store.assets(job_id) if candidate["kind"] in {"GLB", "GLTF"}]
            asset = assets[0] if assets else None
        if asset is None:
            state = (
                "GENERATING"
                if stage == Stage.GENERATING_3D.value
                else ("FAILED" if stage in {Stage.FAILED.value, Stage.BLOCKED.value} else "EMPTY")
            )
            return {
                "state": state,
                "geometryStatus": "GENERATING"
                if state == "GENERATING"
                else ("FAILED" if state == "FAILED" else "IDLE"),
                "textureStatus": "IDLE",
            }
        approved = str(model.get("status") or "") == "APPROVED"
        return {
            "state": "APPROVED" if approved else "READY",
            "geometryStatus": "READY" if model.get("geometry_path") else "PENDING",
            "textureStatus": "READY" if model.get("texture_path") else "PENDING",
            "modelUrl": f"/api/assets/{asset['id']}/content",
            "filename": asset["name"],
        }

    def approve_model(self, job_id: str) -> bool:
        if not self.orchestrator.approve_active(job_id, ("3d",), "approve"):
            raise CoreError("NO_MODEL_GATE", "No 3D model is waiting for approval.", status=409)
        self.events.publish("MODEL_APPROVED", {"jobId": job_id})
        return True

    def regenerate_model(self, job_id: str, target: str) -> bool:
        if target not in {"geometry", "texture"}:
            raise CoreError("INVALID_MODEL_TARGET", "Invalid 3D target.")
        if not self.bridge.wait_for_provider("hunyuan", timeout=0.5):
            raise CoreError(
                "PROVIDER_LOGIN_REQUIRED", "3D Generator requires login.", status=409, details={"provider": "hunyuan"}
            )
        if not self.orchestrator.approve_active(job_id, ("3d",), "edit", f"regen:{target}"):
            raise CoreError("NO_MODEL_GATE", "No 3D model is waiting for regeneration.", status=409)
        return True

    def assets(self) -> list[dict[str, Any]]:
        result = []
        for asset in self.store.assets():
            metadata = dict(asset.get("metadata") or {})
            kind = str(asset.get("kind") or "RBX").upper()
            if kind == "PNG":
                kind = "VIEW" if metadata.get("view") else "IMG"
            if kind == "VIEW" and "conceptVersion" not in metadata and "version" in metadata:
                metadata["conceptVersion"] = metadata.pop("version")
            if kind not in {"IMG", "VIEW", "GLB", "GLTF", "TEX", "RBX"}:
                kind = "RBX"
            result.append(
                {
                    "id": asset["id"],
                    "name": asset["name"],
                    "type": kind,
                    "url": f"/api/assets/{asset['id']}/content",
                    "size": int(asset["size"]),
                    "createdAt": _milliseconds(asset["created_at"]),
                    "jobId": asset["job_id"] or None,
                    **metadata,
                }
            )
        return result

    def asset_file(self, asset_id: str) -> tuple[Path, str, str]:
        asset = self.store.asset(asset_id)
        if asset is None:
            raise CoreError("ASSET_NOT_FOUND", "Asset not found.", status=404)
        path = Path(str(asset["path"])).resolve()
        if not self._is_within(path, self.data_root) or not path.is_file():
            raise CoreError("ASSET_UNAVAILABLE", "Local asset unavailable.", status=404)
        return path, str(asset["mime"]), str(asset["name"])

    def studio_state(self) -> dict[str, Any]:
        return {
            "state": "ONLINE"
            if self.connections()["studio"] == "READY"
            else ("CONNECTING" if self.connections()["studio"] == "CONNECTING" else "OFFLINE"),
            "projectName": self._studio_label,
            "studioId": self._studio_target_id,
            "treeError": getattr(self, "_studio_tree_error", ""),
            "inventory": getattr(self, "_studio_inventory", {}),
        }

    def studio_tree(self) -> list[dict[str, Any]]:
        with self._studio_lock:
            return json.loads(json.dumps(self._studio_tree))

    def refresh_studio(self, *, report_error: bool = True) -> bool:
        if not self._studio_refresh_lock.acquire(blocking=False):
            raise CoreError("STUDIO_BUSY", "Studio connection is being refreshed. Please wait.", status=409)
        try:
            return self._refresh_studio(report_error=report_error)
        finally:
            self._studio_refresh_lock.release()

    def _refresh_studio(self, *, report_error: bool) -> bool:
        try:
            if self._closing.is_set():
                raise MCPError("Rubra is closing.")
            if isinstance(self.studio, _UnavailableStudio):
                self.studio = StudioMCPClient(
                    find_studio_mcp(), notification_callback=self._on_mcp_notification, startup_timeout=8
                )
                self.qa.studio = self.studio
                self.orchestrator.studio = self.studio
            if not self.studio.running:
                self.studio.start()
            studios = self.studio.list_studios()
            target = select_studio_target(
                studios, preferred_id=self._studio_target_id, active_title=active_studio_title()
            )
            with self._studio_lock:
                same_target = target.studio_id == self._studio_target_id
                retained_references = {
                    node_id: {
                        "locked": bool(node.get("locked")),
                        "usedAsContext": bool(node.get("usedAsContext")),
                    }
                    for node_id, node in self._studio_nodes.items()
                    if same_target and (node.get("locked") or node.get("usedAsContext"))
                }
                if not same_target:
                    self._studio_tree, self._studio_nodes = [], {}
                    self._studio_inventory = {"complete": False, "total": 0, "source": ""}
                    self._studio_tree_error = ""
                self._studio_target_id = target.studio_id
                self._studio_label = target.label
            self._set_connection("studio", "READY")
            self.events.publish("STUDIO_STATE_CHANGED", self.studio_state())
            try:
                snapshot = read_tree(self.studio, target.studio_id)
                tree, nodes = self._parse_studio_tree(snapshot.instances)
                for node_id, state in retained_references.items():
                    node = nodes.get(node_id)
                    if node is not None:
                        node.update(state)
                with self._studio_lock:
                    self._studio_tree, self._studio_nodes = tree, nodes
                    self._studio_inventory = {
                        "complete": snapshot.complete,
                        "total": snapshot.total,
                        "source": snapshot.source,
                    }
                self._studio_tree_error = ""
                self._last_studio_inventory = time.monotonic()
            except MCPError as exc:
                self._studio_tree_error = str(exc)
            self.events.publish("STUDIO_STATE_CHANGED", self.studio_state())
            tree = self.studio_tree()
            self.events.publish("STUDIO_TREE_UPDATED", {"tree": tree})
            return True
        except MCPBusyError as exc:
            raise CoreError("STUDIO_BUSY", str(exc), status=409) from exc
        except Exception as exc:
            with self._studio_lock:
                self._studio_label = self._studio_target_id = ""
                self._studio_tree, self._studio_nodes = [], {}
                self._studio_inventory = {}
            self._set_connection("studio", "ERR")
            self.events.publish("STUDIO_STATE_CHANGED", {"state": "OFFLINE"})
            self.events.publish("STUDIO_TREE_UPDATED", {"tree": []})
            if report_error:
                self._report(
                    "studio",
                    "refresh",
                    exc,
                    "Open Studio in Edit mode and enable MCP servers. Rubra retries automatically.",
                )
            raise CoreError("STUDIO_UNAVAILABLE", str(exc), status=503) from exc

    def _monitor_studio(self) -> None:
        while not self._closing.is_set():
            try:
                if self.connections()["studio"] != "READY" or not self.studio.running:
                    self.refresh_studio(report_error=False)
                else:
                    target = select_studio_target(
                        self.studio.list_studios(),
                        preferred_id=self._studio_target_id,
                        active_title=active_studio_title(),
                    )
                    studio_idle = (
                        not self.orchestrator.current_task_id
                        and not self.qa.running(self._studio_test_id)
                    )
                    inventory_due = (
                        bool(getattr(self, "_studio_tree_error", ""))
                        or time.monotonic() - getattr(self, "_last_studio_inventory", 0) >= 30
                    )
                    if (
                        target.studio_id != self._studio_target_id
                        or target.label != self._studio_label
                        or (studio_idle and inventory_due)
                    ):
                        self.refresh_studio(report_error=False)
                self._set_boot("STUDIO", "READY")
            except (CoreError, MCPError) as exc:
                if isinstance(exc, MCPBusyError) or isinstance(exc, CoreError) and exc.code == "STUDIO_BUSY":
                    if self._closing.wait(5.0):
                        break
                    continue
                if self.connections()["studio"] != "OFF":
                    with self._studio_lock:
                        self._studio_label = self._studio_target_id = ""
                        self._studio_tree, self._studio_nodes = [], {}
                        self._studio_inventory = {}
                    self._set_connection("studio", "OFF")
                    self.events.publish("STUDIO_STATE_CHANGED", {"state": "OFFLINE", "projectName": ""})
                    self.events.publish("STUDIO_TREE_UPDATED", {"tree": []})
                self._set_boot("STUDIO", "OFF")
            if self._closing.wait(5.0):
                break

    def search_studio(self, query: str) -> list[dict[str, Any]]:
        needle = query.strip().casefold()
        with self._studio_lock:
            values = list(self._studio_nodes.values())
        if not needle:
            return values[:200]
        return [item for item in values if needle in item["name"].casefold() or needle in item["path"].casefold()][:200]

    def inspect_studio(self, node_id: str) -> dict[str, Any]:
        if self.connections()["studio"] != "READY":
            raise CoreError("STUDIO_UNAVAILABLE", "Reconnect Studio before inspecting this object.", status=503)
        with self._studio_lock:
            node = self._studio_nodes.get(node_id)
        if node is None:
            raise CoreError("STUDIO_NODE_NOT_FOUND", "Studio object not found.", status=404)
        result = dict(node)
        tools = getattr(self.studio, "tools", {})
        if isinstance(tools, dict) and "inspect_instance" in tools:
            tool = tools["inspect_instance"]
            properties = tool.input_schema.get("properties", {})
            key = next(
                (name for name in ("path", "instance_path", "instancePath", "target") if name in properties), None
            )
            if key:
                try:
                    details = self.studio.call_tool(
                        "inspect_instance",
                        supported_arguments(self.studio, "inspect_instance", {key: node["path"], "datamodel_type": "Edit"}),
                        studio_id=self._studio_target_id,
                        timeout=10,
                    )
                    if details.is_error:
                        raise MCPError(details.compact(2000))
                    result["details"] = details.structured_content or details.text
                except MCPError as exc:
                    result["detailsError"] = str(exc)
        if node["className"] in {"Script", "LocalScript", "ModuleScript"}:
            source = self.studio.call_tool(
                "script_read",
                {"target_file": node["path"], "should_read_entire_file": True},
                studio_id=self._studio_target_id,
                timeout=10,
            )
            if source.is_error:
                raise CoreError("STUDIO_READ_FAILED", source.compact(2000), status=503)
            result["source"] = script_source(source)
        return result

    def set_studio_reference(self, node_id: str, action: str) -> bool:
        with self._studio_lock:
            node = self._studio_nodes.get(node_id)
            if node is None:
                raise CoreError("STUDIO_NODE_NOT_FOUND", "Studio object not found.", status=404)
            if action == "lock":
                node["locked"] = True
            elif action == "unlock":
                node["locked"] = False
            elif action == "context":
                node["usedAsContext"] = True
            else:
                raise CoreError("INVALID_STUDIO_ACTION", "Invalid reference action.")
        self.events.publish("STUDIO_TREE_UPDATED", {"tree": self.studio_tree()})
        return True

    def start_test(self, job_id: str, profile: str = "STANDARD") -> bool:
        self._require_task(job_id)
        if self.orchestrator.current_task_id:
            raise CoreError("STUDIO_BUSY", "Wait for the active task before starting a manual test.", status=409)
        if not self.qa.start_manual(job_id, profile):
            raise CoreError("TEST_ALREADY_RUNNING", "A test is already running.", status=409)
        return True

    def start_studio_test(self, profile: str = "STANDARD") -> dict[str, Any]:
        with self._test_start_lock:
            return self._start_studio_test(profile)

    def _start_studio_test(self, profile: str) -> dict[str, Any]:
        if self.orchestrator.current_task_id:
            raise CoreError(
                "STUDIO_BUSY", "Wait for the active build to finish before testing the open place.", status=409
            )
        if self.connections()["studio"] != "READY":
            self.refresh_studio()
        if self.connections()["studio"] != "READY" or not self._studio_target_id:
            raise CoreError("STUDIO_UNAVAILABLE", "Open a place in Roblox Studio and enable its MCP server.", status=409)
        if self.qa.running(self._studio_test_id):
            raise CoreError("TEST_ALREADY_RUNNING", "A test is already running.", status=409)
        job_id = uuid.uuid4().hex
        self.store.create_task(
            job_id, f"Play Test: {self._studio_label}", TaskOptions(create_3d_asset=False, independent_review=False)
        )
        self.store.update_task(
            job_id,
            studio_id=self._studio_target_id,
            stage=Stage.TESTING,
            status="running",
            context_json={"manual_test": True},
        )
        try:
            self.start_test(job_id, profile)
        except Exception as exc:
            self.store.update_task(
                job_id,
                stage=Stage.FAILED,
                status="failed",
                error=str(exc),
                final_text="Play Test could not start.",
            )
            raise
        self._studio_test_id = job_id
        return {"ok": True, "jobId": job_id}

    def stop_test(self, job_id: str) -> bool:
        if self.qa.stop(job_id):
            return True
        if self.orchestrator.cancel(job_id):
            return True
        raise CoreError("TEST_NOT_RUNNING", "No test is running.", status=409)

    def test_state(self, job_id: str) -> dict[str, Any]:
        task = self._require_task(job_id)
        latest = self.store.latest_test_run(job_id)
        if self.qa.running(job_id):
            status = "RUNNING"
        elif latest is None:
            status = "IDLE"
        elif latest["status"] == "FAILED":
            status = "FAILED"
        else:
            status = "STOPPED"
        options = task.get("options") or {}
        return {
            "status": status,
            "elapsedMs": int((latest or {}).get("summary", {}).get("durationMs", 0)),
            "fixAttempt": 0,
            "maxFixAttempts": int(options.get("max_test_fixes", 3)),
        }

    def settings(self) -> dict[str, Any]:
        with self._settings_lock:
            stored = self.store.get_setting("ui.settings", {})
            result = json.loads(json.dumps(self.DEFAULT_SETTINGS))
            if isinstance(stored, dict):
                result.update({key: value for key, value in stored.items() if key in result and key != "models"})
                if isinstance(stored.get("models"), dict):
                    result["models"] = self._merge_models(result["models"], stored["models"])
            return result

    def local_ai_state(self) -> dict[str, Any]:
        results_path = self.portable_root / "runtime" / "toolchain-results.json"
        tool_results: dict[str, Any] = {}
        try:
            raw = json.loads(results_path.read_text(encoding="utf-8")) if results_path.is_file() else {}
            if isinstance(raw, dict):
                tool_results = raw
        except (OSError, json.JSONDecodeError):
            tool_results = {}
        model_results = {"qwen-coder-7b": tool_results.get("qwen-coder-7b"), "qwen3-4b": tool_results.get("qwen3-4b")}
        models = []
        for item in self.local_ai.model_status():
            model = dict(item)
            result = model_results.get(str(model.get("id") or ""))
            if isinstance(result, dict):
                model["state"] = str(result.get("state") or "")
                model["detail"] = str(result.get("detail") or "")
            models.append(model)
        return {
            "enabled": bool(self.settings()["localAI"]),
            "available": self.local_ai.available,
            "running": self.local_ai.running,
            "model": "Qwen Coder 7B + Qwen3 4B",
            "models": models,
            "setup": dict(self._tools_state),
        }

    def prepare_tools(self) -> bool:
        with self._provider_lock:
            if self._tools_thread is not None and self._tools_thread.is_alive():
                return True
            self._tools_thread = threading.Thread(target=self._prepare_tools, name="Rubra-Tools", daemon=True)
            self._tools_thread.start()
        return True

    def _prepare_tools(self) -> None:
        def progress(stage: str, detail: str) -> None:
            self._tools_state = {"state": "INSTALLING", "detail": f"{stage}: {detail}"}

        self._tools_state = {"state": "INSTALLING", "detail": "Preparing pinned tools and local model"}
        try:
            manager = ToolchainManager(
                resource_root=self.resource_root,
                portable_root=self.portable_root,
                status_callback=progress,
                cancel_event=self._closing,
            )
            results = manager.ensure_default()
            os.environ.update(manager.environment())
            failures = [item.item_id for item in results if item.state == "failed"]
            self._tools_state = {
                "state": "ERROR" if failures else "READY",
                "detail": "; ".join(f"{item.item_id}: {item.detail}" for item in results if item.state == "failed") if failures else "Tools and skills prepared",
            }
            self._model_cache = None
            if self.local_ai.available and self.settings()["localAI"]:
                for provider in ("chatgpt", "deepseek"):
                    if self.connections()[provider] != "READY":
                        self.bridge.wait_for_provider(provider, timeout=0.5)
        except Exception as exc:
            self._tools_state = {"state": "ERROR", "detail": str(exc)}
            if not self._closing.is_set():
                self._report("tools", "prepare", exc, "Retry preparation in Settings > Models.")

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._settings_lock:
            current = self.settings()
            if "autoApprove" in patch:
                current["autoApprove"] = TaskOptions._boolean(patch["autoApprove"], bool(current["autoApprove"]))
                current["approvalMode"] = "FULL_AUTO" if current["autoApprove"] else "ASK"
            if "approvalMode" in patch:
                approval_mode = str(patch["approvalMode"] or "ASK").strip().upper().replace("-", "_").replace(" ", "_")
                if approval_mode not in {"ASK", "SAFE_AUTO", "FULL_AUTO"}:
                    raise CoreError("INVALID_APPROVAL_MODE", "Approval mode must be ASK, SAFE_AUTO, or FULL_AUTO.")
                current["approvalMode"] = approval_mode
                current["autoApprove"] = approval_mode == "FULL_AUTO"
            if "maxRevisions" in patch:
                current["maxRevisions"] = max(1, min(64, int(patch["maxRevisions"])))
            if "projectRoot" in patch:
                project_root = str(patch["projectRoot"] or "").strip()
                try:
                    current["projectRoot"] = self.project_index.configure(project_root)
                except ProjectIndexError as exc:
                    raise CoreError("INVALID_PROJECT_ROOT", str(exc), status=400) from exc
            if "semanticIndex" in patch:
                current["semanticIndex"] = TaskOptions._boolean(patch["semanticIndex"], bool(current["semanticIndex"]))
            if "localAI" in patch:
                current["localAI"] = TaskOptions._boolean(patch["localAI"], bool(current["localAI"]))
                if not current["localAI"]:
                    self.local_ai.close()
            if "models" in patch and isinstance(patch["models"], dict):
                current["models"] = self._merge_models(current["models"], patch["models"])
            self.store.set_setting("ui.settings", current)
            self.events.publish("SETTINGS_CHANGED", {"settings": current})
            return current
    

    def model_catalog(self, *, refresh: bool = False) -> dict[str, Any]:
        if not refresh and self._model_cache and time.monotonic() - self._model_cache[0] < 60:
            return json.loads(json.dumps(self._model_cache[1]))
        settings = self.settings()["models"]
        catalog: dict[str, Any] = {
            "chatgpt": {
                "models": [
                    {
                        "id": settings["chatgpt"]["model"],
                        "label": "Provider default"
                        if settings["chatgpt"]["model"] == "auto"
                        else settings["chatgpt"]["model"],
                    }
                ]
            },
            "deepseek": {
                "models": [
                    {
                        "id": settings["deepseek"]["model"],
                        "label": "Provider default"
                        if settings["deepseek"]["model"] == "auto"
                        else settings["deepseek"]["model"],
                    }
                ]
            },
            "gemini": {
                "models": [
                    {
                        "id": settings["gemini"]["model"],
                        "label": "Provider default"
                        if settings["gemini"]["model"] == "auto"
                        else settings["gemini"]["model"],
                    }
                ]
            },
            "hunyuan": {
                "versions": [{"id": settings["hunyuan"]["version"], "label": settings["hunyuan"]["version"]}],
            },
        }
        for provider in ("chatgpt", "deepseek", "gemini", "hunyuan"):
            if self.connections()[provider] != "READY":
                continue
            try:
                response = self.bridge.request(provider, "get_models", {}, task_id="settings", timeout=8)
                names = [str(item).strip() for item in response.get("models", []) if str(item).strip()]
            except BridgeError:
                names = []
            if not names:
                continue
            options = [{"id": "auto", "label": "Current provider default"}]
            selected = settings[provider].get("version" if provider == "hunyuan" else "model", "auto")
            options.extend({"id": name, "label": name} for name in dict.fromkeys([selected, *names]) if name != "auto")
            if provider == "hunyuan":
                catalog[provider]["versions"] = options
            else:
                catalog[provider]["models"] = options
        self._model_cache = (time.monotonic(), catalog)
        return json.loads(json.dumps(catalog))

    def set_model(self, provider: str, model: str) -> bool:
        with self._model_selection_lock:
            if provider not in {"chatgpt", "deepseek", "gemini", "hunyuan"} or not model.strip():
                raise CoreError("INVALID_MODEL", "Invalid model or provider.")
            if model != "auto":
                if not self.bridge.wait_for_provider(provider, timeout=0.5):
                    raise CoreError(
                        "PROVIDER_LOGIN_REQUIRED",
                        f"{PROVIDER_LABELS[provider]} requires login.",
                        status=409,
                        details={"provider": provider},
                    )
                response = self.bridge.request(
                    provider, "select_model", {"model": model}, task_id="settings", timeout=15
                )
                selected = str(response.get("selected") or "").strip()
                if response.get("status") != "ok" or selected.casefold() != model.casefold():
                    raise CoreError(
                        "MODEL_SELECTION_FAILED",
                        f"{PROVIDER_LABELS[provider]} did not confirm the selected model: {model}",
                        status=409,
                        details={"provider": provider, "model": model, "selected": selected},
                    )
            with self._settings_lock:
                current = self.settings()
                if provider == "hunyuan":
                    current["models"][provider]["version"] = model
                else:
                    current["models"][provider]["model"] = model
                self.store.set_setting("ui.settings", current)
                self._model_cache = None
                self.events.publish("SETTINGS_CHANGED", {"settings": current})
            return True

    def set_smart_routing(self, enabled: Any) -> bool:
        with self._settings_lock:
            current = self.settings()
            current["models"]["smartRouting"] = TaskOptions._boolean(
                enabled, bool(current["models"]["smartRouting"])
            )
            self.store.set_setting("ui.settings", current)
            self.events.publish("SETTINGS_CHANGED", {"settings": current})
        return True

    def _effective_project_root(self) -> str:
        configured = str(self.settings().get("projectRoot") or "").strip()
        if configured:
            return configured
        roots = self.store.get_setting("studio.projectRoots", {})
        root = roots.get(self._studio_target_id, "") if isinstance(roots, dict) else ""
        if root and self._is_within(Path(root).resolve(), self.data_root):
            return str(root)
        return ""

    def project_index_status(self) -> dict[str, Any]:
        root = self._effective_project_root()
        try:
            return self.project_index.status(project_root=root)
        except ProjectIndexError as exc:
            return {"configured": False, "projectRoot": root, "running": False, "result": "", "error": str(exc)}

    def reindex_project(self, *, incremental: bool = True) -> dict[str, Any]:
        root = self._effective_project_root()
        if not root:
            raise CoreError(
                "PROJECT_ROOT_REQUIRED",
                "Open a game in Studio and start a chat task to collect its source index.",
                status=409,
            )
        try:
            return self.project_index.index(project_root=root, incremental=incremental)
        except ProjectIndexError as exc:
            raise CoreError("PROJECT_INDEX_FAILED", str(exc), status=503) from exc

    def search_project(self, query: str, *, semantic: bool = True, limit: int = 12) -> dict[str, Any]:
        root = self._effective_project_root()
        if not root:
            return {"projectRoot": "", "query": query, "result": "", "available": False}
        try:
            return self.project_index.search(query, semantic=semantic, limit=limit, project_root=root)
        except ProjectIndexError as exc:
            raise CoreError("PROJECT_SEARCH_FAILED", str(exc), status=503) from exc

    def _project_search_for_orchestrator(self, query: str) -> dict[str, Any]:
        settings = self.settings()
        if not bool(settings.get("semanticIndex", True)):
            return {"available": False, "result": ""}
        root = self._effective_project_root()
        if root:
            self.project_index.index(project_root=root, incremental=True)
        return self.search_project(query, semantic=True, limit=12)

    def _local_ai_complete(self, prompt: str) -> str:
        settings = self.settings()
        if not bool(settings.get("localAI", True)) or not self.local_ai.available:
            return ""
        try:
            return self.local_ai.complete(prompt, max_tokens=700, temperature=0.1, timeout=120)
        except LocalAIError as exc:
            self._report(
                "local-ai", "inference", exc, "Rubra will continue with web providers and deterministic routing."
            )
            return ""

    def _index_project_background(self) -> None:
        settings = self.settings()
        root = self._effective_project_root()
        if not root or not bool(settings.get("semanticIndex", True)):
            return
        try:
            self.project_index.index(project_root=root, incremental=True)
        except Exception as exc:
            self._report(
                "index",
                "background",
                exc,
                "Project indexing is optional; configure a valid project folder or retry manually.",
            )

    def diagnostics_payload(self) -> list[dict[str, Any]]:
        return [self._diagnostic_payload(event) for event in self.diagnostics.recent(200)]

    def _start_services(self) -> None:
        try:
            recovered = self.store.recover_interrupted_tasks()
            recovered_queue = self.store.recover_prompt_queue()
            self._set_boot("STATE", "READY")
            for item in recovered:
                self.events.publish("JOB_UPDATED", {"job": self.job(str(item["id"]))})
                self.diagnostics.report(
                    severity="WARNING",
                    source="state",
                    component="recovery",
                    message=str(item["reason"]),
                    impact=f"Interrupted task {item['id']} moved to {item['stage']}.",
                    recovery_action="Resume only pre-mutation checkpoints; inspect blocked mutation evidence manually.",
                )
            for queue_id in recovered_queue:
                self.diagnostics.report(
                    severity="WARNING",
                    source="queue",
                    component="recovery",
                    message="A prompt was being prepared when Rubra stopped; automatic resend was blocked.",
                    impact=f"Queue item {queue_id} requires an explicit retry so it cannot be submitted twice.",
                    recovery_action="Check Recent Tasks, then use Retry on the queued prompt only if no matching job exists.",
                )
        except Exception as exc:
            self._set_boot("STATE", "OFF")
            self._report("state", "recovery", exc, "Inspect the local SQLite state before running another mutation.")
        if self._closing.is_set():
            return
        try:
            self.bridge.start()
            self._set_connection("browser", "READY")
            self._set_boot("BROWSER", "READY")
        except Exception as exc:
            self._set_connection("browser", "ERR")
            self._set_boot("BROWSER", "OFF")
            self._report(
                "browser",
                "startup",
                exc,
                "The embedded browser remains available; the managed browser will be prepared during login if needed.",
            )
        if self._closing.is_set():
            return
        self._set_boot("UI", "READY")
        self.events.publish("BOOT_COMPLETE", {})
        self._start_prompt_queue()
        if os.environ.get("RUBRA_PREPARE_TOOLS") == "1" and not self._closing.is_set():
            self.prepare_tools()
        if self._closing.is_set():
            return
        self._studio_thread = threading.Thread(target=self._monitor_studio, name="Rubra-Studio-Monitor", daemon=True)
        self._studio_thread.start()
        self._refresh_provider_states()
        if self._closing.is_set():
            return
        threading.Thread(target=self._restore_provider_sessions, name="Rubra-Session-Restore", daemon=True).start()
        index_thread = threading.Thread(target=self._index_project_background, name="Rubra-Project-Index", daemon=True)
        index_thread.start()

    def _restore_provider_sessions(self) -> None:
        roots = (self.data_root / "webview-profile", self.data_root / "browser-profile")
        if not any(root.is_dir() and any(root.iterdir()) for root in roots):
            return
        for provider in PROVIDER_LABELS:
            if self._closing.is_set():
                return
            with self._provider_lock:
                thread = self._provider_threads.get(provider)
                logging_in = thread is not None and thread.is_alive()
            if not logging_in:
                self.bridge.wait_for_provider(provider, timeout=2)

    def _login_worker(self, provider: str) -> None:
        self._set_connection(provider, "LOGIN")
        self.events.publish("AGENT_STATUS_CHANGED", {"agent": provider, "status": "LOGIN"})
        try:
            result = self.bridge.login(provider, timeout=600)
            if result.get("state") != "ready":
                deadline = time.monotonic() + 600
                while not self._closing.is_set() and time.monotonic() < deadline:
                    if self.bridge.wait_for_provider(provider, timeout=2):
                        break
                    self._closing.wait(1)
                else:
                    raise BridgeError("Login was not confirmed. Reopen the provider window and try again.")
            self._set_connection(provider, "READY")
            self.events.publish("AGENT_STATUS_CHANGED", {"agent": provider, "status": "READY"})
            self._set_boot("AI", "READY")
        except Exception as exc:
            message = str(exc)
            attention = any(
                marker in message
                for marker in ("LOGIN_CANCELLED", "LOGIN_CHALLENGE", "requires login", "Login was not confirmed")
            )
            status = "LOGIN" if attention else "ERR"
            self._set_connection(provider, status)
            self.events.publish("AGENT_STATUS_CHANGED", {"agent": provider, "status": status})
            if attention:
                probable = (
                    "The provider login was closed or the provider's anti-bot challenge could not be confirmed. "
                    "Embedded browsers can be rejected by CAPTCHA systems even when the saved session remains valid."
                )
                recovery = (
                    "Retry Login in a stable network/browser session. DeepSeek review is optional when Independent Review "
                    "is disabled or Smart Routing can use the local reviewer."
                )
                self._report(
                    "browser",
                    f"login:{provider}",
                    exc,
                    recovery,
                    severity="WARNING",
                    probable_cause=probable,
                    impact="Only this provider remains unauthenticated; other providers and local routing stay available.",
                )
            else:
                self._report(
                    "browser",
                    f"login:{provider}",
                    exc,
                    "Retry login. Password, MFA, and CAPTCHA steps remain manual.",
                )

    def _refresh_provider_states(self) -> None:
        statuses = self.bridge.provider_status()
        any_ready = False
        for provider in ("chatgpt", "deepseek", "gemini", "hunyuan"):
            state = str(statuses.get(provider, {}).get("state", "OFF"))
            normalized = "LOGIN" if state.casefold() == "standby" else self._normalize_connection(state)
            self._set_connection(provider, normalized)
            any_ready = any_ready or normalized == "READY"
        self._set_boot("AI", "READY" if any_ready else "OFF")

    def _on_provider_status(self, provider: str, state: str, _detail: str) -> None:
        if provider in {"chatgpt", "deepseek", "gemini", "hunyuan"}:
            normalized = self._normalize_connection(state)
            self._set_connection(provider, normalized)
            self.events.publish("AGENT_STATUS_CHANGED", {"agent": provider, "status": normalized})
        elif provider == "browser":
            self._set_connection("browser", self._normalize_connection(state))

    def _on_pipeline_event(self, event: PipelineEvent) -> None:
        self._queue_wake.set()
        if event.kind == "stream_start":
            self.events.publish(
                "CHAT_STREAM_STARTED",
                {"messageId": event.message, "jobId": event.task_id, "provider": event.detail},
            )
            return
        if event.kind == "stream_delta":
            self.events.publish(
                "CHAT_STREAM_DELTA",
                {"messageId": event.message, "jobId": event.task_id, "delta": event.detail},
            )
            return
        if event.kind == "stream_finish":
            self.events.publish("CHAT_STREAM_FINISHED", {"messageId": event.message, "jobId": event.task_id})
            return
        try:
            job = self.job(event.task_id)
        except CoreError:
            return
        if event.stage == Stage.NEW:
            self.events.publish("JOB_CREATED", {"job": job})
        else:
            self.events.publish("JOB_UPDATED", {"job": job})
        self.events.publish(
            "PIPELINE_STATE_CHANGED",
            {"jobId": event.task_id, "stage": event.stage.value},
        )
        phase = {
            "COLLECTING_CONTEXT": "CONTEXT",
            "PLANNING": "PLAN",
            "BUILDING": "BUILD",
            "REVIEWING": "REVIEW",
            "APPLYING": "APPLY",
            "TESTING": "TEST",
            "FINAL_REVIEW": "FINAL",
            "GENERATING_3D": "THREED",
        }.get(event.stage.value, "PLAN")
        self.events.publish(
            "CHAT_ACTIVITY",
            {
                "activity": {
                    "id": f"{event.task_id}:{event.stage.value}",
                    "jobId": event.task_id,
                    "phase": phase,
                    "status": "FAILED"
                    if event.stage == Stage.FAILED
                    else "WARNING"
                    if event.stage == Stage.BLOCKED
                    else "DONE"
                    if event.stage == Stage.COMPLETE
                    else "RUNNING",
                    "title": event.message,
                    "detail": event.detail[:600],
                    "timestamp": int(time.time() * 1000),
                }
            },
        )
        if event.stage == Stage.WAITING_CHANGE_APPROVAL:
            self.events.publish("CHANGES_UPDATED", {"jobId": event.task_id, "files": self.changes(event.task_id)})
            self.events.publish("REVIEW_READY", {"jobId": event.task_id, "review": self.review(event.task_id)})
        elif event.stage == Stage.GENERATING_CONCEPT:
            self.events.publish("VISUAL_GENERATION_CHANGED", {"jobId": event.task_id, "state": "GENERATING"})
        elif event.stage == Stage.WAITING_IMAGE_APPROVAL:
            visual = self.visual(event.task_id)
            concept = visual.get("concept") if isinstance(visual, dict) else {}
            self.events.publish(
                "VISUAL_GENERATION_CHANGED",
                {
                    "jobId": event.task_id,
                    "state": "READY",
                    "version": int(concept.get("version") or 0) if isinstance(concept, dict) else 0,
                    "prompt": str(concept.get("prompt") or "") if isinstance(concept, dict) else "",
                },
            )
            for view in visual.get("views", []) if isinstance(visual, dict) else []:
                if isinstance(view, dict) and view.get("imageUrl") and view.get("name"):
                    self.events.publish(
                        "VISUAL_READY",
                        {"jobId": event.task_id, "view": str(view["name"]), "imageUrl": str(view["imageUrl"])},
                    )
        elif event.stage == Stage.GENERATING_3D:
            self.events.publish(
                "MODEL_GENERATION_CHANGED",
                {"jobId": event.task_id, "target": "geometry", "state": "GENERATING"},
            )
        elif event.stage == Stage.WAITING_3D_APPROVAL:
            self._register_model_from_event(event)
        elif event.stage == Stage.COMPLETE:
            self.events.publish("JOB_COMPLETE", {"jobId": event.task_id})
            task = self.store.load_task(event.task_id) or {}
            text = str(task.get("final_text") or event.message)
            self.events.publish(
                "CHAT_MESSAGE",
                {"message": self._event_chat_message(event.task_id, text, "zenless")},
            )
        elif event.stage in {Stage.BLOCKED, Stage.FAILED}:
            if event.stage == Stage.FAILED:
                self.events.publish("JOB_FAILED", {"jobId": event.task_id, "reason": event.message})
            self.events.publish(
                "CHAT_MESSAGE",
                {"message": self._event_chat_message(event.task_id, event.message, "system")},
            )

    def _event_chat_message(self, job_id: str, content: str, role: str) -> dict[str, Any]:
        stored = self.messages(job_id)
        for message in reversed(stored):
            if message["content"] == content and message["role"] == role:
                return message
        result: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "role": role,
            "content": content,
            "timestamp": int(time.time() * 1000),
            "jobId": job_id,
        }
        action = self._message_action(content)
        if action:
            result["action"] = action
        return result

    def _register_model_from_event(self, event: PipelineEvent) -> None:
        try:
            payload = json.loads(event.detail)
        except TypeError, json.JSONDecodeError:
            payload = {}
        path_text = str(payload.get("path") or "") if isinstance(payload, dict) else ""
        if not path_text:
            return
        path = Path(path_text).resolve()
        if not self._is_within(path, self.data_root) or not path.is_file():
            self._report(
                "asset",
                "hunyuan",
                RuntimeError("The 3D generator returned a path outside local storage."),
                "Use the authorized internal download flow.",
            )
            return
        asset = self._register_file_asset(path, job_id=event.task_id, kind="GLB")
        self.events.publish("ASSETS_UPDATED", {"assets": self.assets()})
        self.events.publish(
            "MODEL_READY",
            {"jobId": event.task_id, "modelUrl": f"/api/assets/{asset}/content", "filename": path.name},
        )

    def _on_diagnostic(self, event: DiagnosticEvent) -> None:
        self.events.publish("DIAGNOSTIC_EVENT", {"diagnostic": self._diagnostic_payload(event)})

    def _on_mcp_notification(self, message: dict[str, Any]) -> None:
        method = str(message.get("method", "notification"))
        if "studio" in method.casefold():
            self.events.publish("STUDIO_STATE_CHANGED", self.studio_state())

    def _set_connection(self, name: str, state: str) -> None:
        with self._connections_lock:
            if self._connections.get(name) == state:
                return
            self._connections[name] = state
        self.events.publish("CONNECTION_CHANGED", {name: state})

    def _set_boot(self, stage: str, state: str) -> None:
        with self._boot_lock:
            for item in self._boot_steps:
                if item["stage"] == stage:
                    item["state"] = state
                    break
        self.events.publish("BOOT_STAGE_CHANGED", {"stage": stage, "state": state})

    def _report(
        self,
        source: str,
        component: str,
        exc: BaseException,
        recovery: str,
        *,
        severity: str = "ERROR",
        probable_cause: str = "",
        impact: str = "",
    ) -> None:
        self.diagnostics.report(
            severity=severity,
            source=source,
            component=component,
            message=str(exc),
            exc=exc,
            probable_cause=probable_cause,
            impact=impact,
            recovery_action=recovery,
        )

    def _require_task(self, job_id: str) -> dict[str, Any]:
        task = self.store.load_task(job_id)
        if task is None:
            raise CoreError("JOB_NOT_FOUND", "Job not found.", status=404)
        return task

    @staticmethod
    def _task_to_job(task: dict[str, Any]) -> dict[str, Any]:
        raw_status = str(task.get("status", "new")).casefold()
        status_map = {
            "queued": "NEW",
            "running": "RUNNING",
            "waiting": "PAUSED" if task.get("stage") == Stage.PAUSED.value else "RUNNING",
            "complete": "COMPLETE",
            "blocked": "BLOCKED",
            "failed": "FAILED",
        }
        prompt = str(task.get("prompt", ""))
        options = task.get("options") or {}
        return {
            "id": task["id"],
            "title": (prompt.splitlines()[0] or "Rubra task")[:100],
            "status": status_map.get(raw_status, "NEW"),
            "stage": str(task.get("stage", Stage.NEW.value)),
            "createdAt": _milliseconds(task["created_at"]),
            "updatedAt": _milliseconds(task["updated_at"]),
            "options": {
                "visualFirst": bool(options.get("visual_first", False)),
                "create3D": bool(options.get("create_3d_asset", True)),
                "review": bool(options.get("independent_review", True)),
                "autoTest": bool(options.get("automatic_play_test", True)),
                "autoFix": bool(options.get("auto_fix_errors", True)),
                "approval": bool(options.get("require_approval", True)),
                "approvalMode": str(options.get("approval_mode", "ask")).upper(),
                "effort": str(options.get("effort_level", "auto")).upper(),
                "research": str(options.get("research_mode", "auto")).upper(),
                "smartRouting": bool(options.get("smart_routing", True)),
                "continuousVerification": bool(options.get("continuous_verification", True)),
                "risk": str(options.get("risk_level", "medium")),
                "revisions": int(options.get("max_revisions", 3)),
                "fixAttempts": int(options.get("max_test_fixes", 3)),
            },
            "fixAttempts": 0,
            "maxFixAttempts": int(options.get("max_test_fixes", 3)),
        }

    @staticmethod
    def _derive_context_items(job_id: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(path: str, name: str, kind: str, relevance: float, raw: dict[str, Any] | None = None) -> None:
            normalized_path = path.strip()
            if not normalized_path or normalized_path in seen or len(items) >= 240:
                return
            seen.add(normalized_path)
            item_id = hashlib.sha256(f"{job_id}:{normalized_path}".encode("utf-8", "replace")).hexdigest()[:24]
            items.append(
                {
                    "id": item_id,
                    "job_id": job_id,
                    "name": name.strip() or normalized_path.rsplit(".", 1)[-1],
                    "type": kind,
                    "path": normalized_path,
                    "relevance": max(0.0, min(1.0, relevance)),
                    "state": "included",
                    "raw": raw or {},
                }
            )

        raw_sources = context.get("script_sources")
        if isinstance(raw_sources, dict):
            for index, (path, source) in enumerate(raw_sources.items()):
                add(
                    str(path),
                    str(path).rsplit(".", 1)[-1],
                    "Script",
                    max(0.72, 1.0 - index * 0.012),
                    {"sourceExcerpt": str(source)[:4000]},
                )

        inventory = context.get("inventory")
        scripts = inventory.get("scripts") if isinstance(inventory, dict) else None
        if isinstance(scripts, list):
            for index, raw in enumerate(scripts):
                if not isinstance(raw, dict):
                    continue
                path = str(raw.get("path") or "")
                class_name = str(raw.get("className") or "Script")
                kind = "Module" if class_name == "ModuleScript" else ("Local" if class_name == "LocalScript" else "Script")
                add(path, str(raw.get("name") or path.rsplit(".", 1)[-1]), kind, max(0.55, 0.82 - index * 0.006), raw)

        live_nodes = context.get("live_studio_nodes")
        if isinstance(live_nodes, list):
            for index, raw in enumerate(live_nodes):
                if not isinstance(raw, dict):
                    continue
                class_name = str(raw.get("className") or "Instance")
                if class_name not in {
                    "Script", "LocalScript", "ModuleScript", "RemoteEvent", "RemoteFunction",
                    "Folder", "Workspace", "ReplicatedStorage", "ServerScriptService", "StarterPlayer",
                    "StarterGui",
                }:
                    continue
                kind = (
                    "Module" if class_name == "ModuleScript"
                    else "Local" if class_name == "LocalScript"
                    else "Script" if class_name == "Script"
                    else "Remote" if class_name in {"RemoteEvent", "RemoteFunction"}
                    else "Service"
                )
                path = str(raw.get("path") or "")
                add(path, str(raw.get("name") or path.rsplit(".", 1)[-1]), kind, max(0.35, 0.68 - index * 0.002), raw)

        raw_reads = context.get("reads")
        reads: dict[str, Any] = raw_reads if isinstance(raw_reads, dict) else {}
        for index, (name, content) in enumerate(reads.items()):
            path = str(name).split(":", 1)[0]
            add(path, path, "Service", max(0.1, 0.45 - index * 0.03), {"summary": str(content)[:4000]})

        return items

    @staticmethod
    def _public_context(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item["id"],
            "name": item["name"],
            "type": item.get("type", "Service"),
            "path": item["path"],
            "relevance": float(item.get("relevance", 0.0)),
            "state": item.get("state", "included"),
        }

    @staticmethod
    def _parse_studio_tree(payload: Any) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        payload = tree_instances(payload)
        paths: dict[str, dict[str, Any]] = {}
        parents: dict[str, str] = {}
        path_keys: dict[str, str] = {}

        def add(raw: Any, parent: str = "", depth: int = 0) -> None:
            if not isinstance(raw, dict) or depth > 128 or len(paths) >= 50_000:
                return
            name = str(raw.get("name") or raw.get("Name") or "")
            path = str(
                raw.get("fullPath")
                or raw.get("full_path")
                or raw.get("path")
                or raw.get("Path")
                or ((parent + "." if parent else "") + name)
            )
            if not path:
                return
            key = "instance:" + str(raw["id"]) if raw.get("id") else path
            if key in paths:
                key += f":{len(paths)}"
            node = {
                "id": hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()[:24],
                "name": name or path.rsplit(".", 1)[-1],
                "className": str(
                    raw.get("className")
                    or raw.get("class_name")
                    or raw.get("ClassName")
                    or raw.get("class")
                    or "Instance"
                ),
                "path": path,
                "children": [],
            }
            paths[key] = node
            path_keys[path] = key
            parents[key] = "instance:" + str(raw["parentId"]) if raw.get("parentId") else path.rpartition(".")[0]
            for child in raw.get("children", raw.get("Children", [])) or []:
                add(child, path, depth + 1)

        for raw in payload:
            add(raw)
        roots: list[dict[str, Any]] = []
        for key, node in paths.items():
            parent = paths.get(parents[key]) or paths.get(path_keys.get(parents[key], ""))
            if parent is not None:
                parent["children"].append(node)
            else:
                roots.append(node)
        return roots, {node["id"]: node for node in paths.values()}

    def _register_file_asset(self, path: Path, *, job_id: str, kind: str) -> str:
        resolved = path.resolve()
        if not self._is_within(resolved, self.data_root) or not resolved.is_file():
            raise CoreError("INVALID_ASSET_PATH", "The asset does not belong to local storage.")
        hasher = hashlib.sha256()
        with resolved.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        normalized_kind = kind if kind in {"IMG", "VIEW", "GLB", "GLTF", "TEX", "RBX"} else "RBX"
        asset_id = hashlib.sha256(f"{job_id}:{normalized_kind}:{digest}".encode("utf-8")).hexdigest()[:32]
        mime = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        self.store.register_asset(
            asset_id,
            job_id=job_id,
            name=resolved.name,
            kind=normalized_kind,
            path=resolved,
            mime=mime,
        )
        return asset_id

    @staticmethod
    def _diagnostic_payload(event: DiagnosticEvent) -> dict[str, Any]:
        severity = event.severity.casefold()
        if severity not in {"critical", "error", "warning", "info"}:
            severity = "error"
        return {
            "id": event.id,
            "severity": severity,
            "source": event.source,
            "component": event.component,
            "message": event.message,
            "file": event.file or None,
            "line": event.line or None,
            "function": event.function or None,
            "probableCause": event.probable_cause or None,
            "impact": event.impact or None,
            "recovery": event.recovery_action or None,
            "stack": event.stack_trace or None,
            "occurrenceCount": event.occurrence_count,
            "jobId": event.job_id or None,
            "requestId": event.request_id or None,
            "operationId": event.operation_id or None,
            "timestamp": _milliseconds(event.timestamp),
        }

    @staticmethod
    def _normalize_connection(state: str) -> str:
        value = state.casefold()
        if value in {"ready", "connected", "idle", "working"}:
            return "READY"
        if value in {"login required", "login needed", "requires attention"}:
            return "LOGIN"
        if value in {"starting", "connecting", "installing", "standby", "degraded"}:
            return "CONNECTING"
        if value in {"error", "failed", "unavailable", "runtime required"}:
            return "ERR"
        return "OFF"

    @staticmethod
    def _merge_models(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        result = json.loads(json.dumps(current))
        for provider in ("chatgpt", "deepseek", "gemini"):
            value = patch.get(provider)
            if isinstance(value, dict) and "model" in value:
                result[provider]["model"] = str(value["model"] or "auto")
        value = patch.get("hunyuan")
        if isinstance(value, dict) and "version" in value:
            result["hunyuan"]["version"] = str(value["version"] or "auto")
        if "smartRouting" in patch:
            result["smartRouting"] = TaskOptions._boolean(
                patch["smartRouting"], bool(result["smartRouting"])
            )
        return result

    @staticmethod
    def _is_image(path: Path) -> bool:
        return (mimetypes.guess_type(path.name)[0] or "").startswith("image/")

    @staticmethod
    def _is_within(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False
