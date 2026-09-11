from __future__ import annotations

import hashlib
import json
import mimetypes
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .agent_gateway import AgentGateway
from .attachments import AttachmentError, AttachmentInspector, AttachmentRouter, ProviderFileCapability
from .browser_bridge import BridgeError
from .diagnostics import DiagnosticEvent, ErrorBus
from .event_bus import EventBus
from .managed_browser import ManagedBrowserController
from .models import PipelineEvent, Stage, TaskOptions
from .orchestrator import OrchestratorError, ZenlessOrchestrator
from .policy import is_read_only
from .provider_registry import (
    BUILTIN_MANIFESTS,
    AuthState,
    ProviderRegistry,
    normalize_capabilities,
    resolve_provider_roles,
)
from .provisioning import ProvisioningError, ensure_webview2
from .qa_breaker import QABreaker
from .storage import StorageManager
from .store import SQLiteStore
from .studio_discovery import StudioCapabilityRegistry, StudioDiscoveryManager
from .studio_mcp import MCPError, MCPToolResult, StudioMCPClient, find_studio_mcp
from .system_diagnostics import SystemDiagnostics
from .tool_manager import DEFAULT_TOOL_MANIFESTS, ToolError, ToolManager
from .uninstall import UninstallError, UninstallManager
from .webview2_browser import WebView2BrowserController

PROVIDER_LABELS = {
    "chatgpt": "ChatGPT",
    "deepseek": "DeepSeek",
    "hunyuan": "Hunyuan",
}
PROVIDER_ROLES = {
    "chatgpt": ("BUILDER", "VISUAL", "RESEARCH"),
    "deepseek": ("REVIEWER",),
    "hunyuan": ("THREED",),
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
    except (TypeError, ValueError):
        return int(time.time() * 1000)


class ZenlessCore:
    DEFAULT_SETTINGS = {
        "models": {
            "chatgpt": {"model": "auto", "reasoning": True},
            "deepseek": {"model": "auto", "reasoning": True},
            "hunyuan": {"version": "auto", "quality": "standard"},
            "smartRouting": True,
        },
        "autoApprove": False,
        "maxRevisions": 3,
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
        self.provider_registry = ProviderRegistry(BUILTIN_MANIFESTS)
        custom_providers = self.store.get_setting("provider.custom", [])
        if isinstance(custom_providers, list):
            for item in custom_providers:
                if not isinstance(item, dict):
                    continue
                try:
                    self.provider_registry.register_custom(
                        str(item.get("providerId") or ""),
                        str(item.get("displayName") or ""),
                        str(item.get("webUrl") or ""),
                    )
                except ValueError:
                    continue
        stored_budget = self.store.get_setting("storage.budget", StorageManager.DEFAULT_BUDGET_BYTES)
        self.storage = StorageManager(self.data_root, budget_bytes=int(stored_budget))
        self.tools = ToolManager(self.data_root / "tools", DEFAULT_TOOL_MANIFESTS)
        self.attachments = AttachmentRouter(AttachmentInspector())
        self.uninstaller = UninstallManager(self.resource_root, self.data_root)
        self.system_diagnostics = SystemDiagnostics(self.data_root)
        self._closing = threading.Event()
        self._startup_thread: threading.Thread | None = None
        self._provider_probe_thread: threading.Thread | None = None
        self._provider_threads: dict[str, threading.Thread] = {}
        self._provider_lock = threading.Lock()
        self._activities: dict[str, dict[str, Any]] = {}
        self._artifacts_seen: set[str] = set()
        self._studio_lock = threading.RLock()
        self._studio_nodes: dict[str, dict[str, Any]] = {}
        self._studio_tree: list[dict[str, Any]] = []
        self._connections = {
            "bridge": "READY",
            "browser": "CONNECTING",
            "chatgpt": "OFF",
            "deepseek": "OFF",
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
        self._readiness_cache: tuple[float, dict[str, Any]] | None = None
        self._shutdown_callback: Any = None

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
        )
        try:
            self.studio: Any = StudioMCPClient(find_studio_mcp(), notification_callback=self._on_mcp_notification)
        except MCPError as exc:
            self.studio = _UnavailableStudio(str(exc))
            self._connections["studio"] = "OFF"
            self._set_boot("STUDIO", "OFF")
        self.studio_discovery = StudioDiscoveryManager(self.studio)
        self.studio_capabilities = StudioCapabilityRegistry(self.studio)

        self.qa = QABreaker(
            store=self.store,
            studio=self.studio,
            bridge=self.bridge,
            events=self.events,
        )
        self.orchestrator = ZenlessOrchestrator(
            store=self.store,
            bridge=self.bridge,
            studio=self.studio,
            run_root=self.data_root / "runs",
            event_callback=self._on_pipeline_event,
            qa_callback=self.qa.run_for_orchestrator,
            studio_discovery=self.studio_discovery,
        )
        self._diagnostic_unsubscribe = self.diagnostics.subscribe(self._on_diagnostic)

    def start(self) -> None:
        if self._startup_thread is not None and self._startup_thread.is_alive():
            return
        self._startup_thread = threading.Thread(
            target=self._start_services,
            name="Zenless-Core-Startup",
            daemon=True,
        )
        self._startup_thread.start()

    def close(self) -> None:
        if self._closing.is_set():
            return
        self._closing.set()
        current = self.orchestrator.current_task_id
        if current:
            self.orchestrator.cancel(current)
            self.qa.stop(current)
        self.bridge.stop()
        self.orchestrator.wait_for_idle(3.0)
        self.studio.close()
        with self._provider_lock:
            threads = tuple(self._provider_threads.values())
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(timeout=1.0)
        provider_probe = self._provider_probe_thread
        if provider_probe is not None and provider_probe is not threading.current_thread():
            provider_probe.join(timeout=1.0)
        self.store.maintenance()
        self._diagnostic_unsubscribe()
        if self._owns_diagnostics:
            self.diagnostics.close()

    def set_runtime_port(self, port: int) -> None:
        settings = self.settings()
        settings["bridgePort"] = int(port)
        self.store.set_setting("ui.settings", settings)

    def set_shutdown_callback(self, callback: Any) -> None:
        self._shutdown_callback = callback

    def bootstrap(self) -> dict[str, Any]:
        with self._boot_lock:
            return {"steps": [dict(item) for item in self._boot_steps]}

    def status(self) -> dict[str, Any]:
        return {"ready": not self._closing.is_set()}

    def readiness(self, *, refresh: bool = False) -> dict[str, Any]:
        if not refresh and self._readiness_cache and time.monotonic() - self._readiness_cache[0] < 3:
            return json.loads(json.dumps(self._readiness_cache[1]))
        if refresh:
            for provider in PROVIDER_LABELS:
                self.bridge.wait_for_provider(provider, timeout=1)
            try:
                self.studios(refresh=True)
            except CoreError:
                pass
        connections = self.connections()
        provider_states = self.bridge.provider_status()
        builder_provider = self._resolved_role_providers()["BUILDER"]
        providers = []
        for provider in PROVIDER_LABELS:
            raw = provider_states.get(provider, {})
            auth_state = self._provider_auth_state(str(raw.get("state") or connections.get(provider) or "OFF"))
            providers.append(
                {
                    "providerId": provider,
                    "displayName": PROVIDER_LABELS[provider],
                    "authState": auth_state.value,
                    "route": str(raw.get("route") or raw.get("transport") or self.bridge.selected_route(provider)),
                    "required": provider == builder_provider,
                    "detail": str(raw.get("detail") or ""),
                }
            )
        selection = self.studio_discovery.selection
        studio = (
            selection.public()
            if selection
            else {
                "state": "MCP_CONNECTED" if getattr(self.studio, "running", False) else "STUDIO_NOT_RUNNING",
                "selectedStudioId": None,
                "studios": [],
                "detail": "Studio discovery has not completed.",
            }
        )
        usage = self.storage.usage()
        studio_tools = set(getattr(self.studio, "tools", {}))
        required_studio_tools = {"multi_edit", "script_read", "search_game_tree"}
        missing_studio_tools = sorted(required_studio_tools - studio_tools)
        checks = [
            {
                "id": "core",
                "label": "Core",
                "state": "READY" if not self._closing.is_set() else "ERROR",
                "required": True,
            },
            {"id": "state", "label": "State", "state": self._boot_state("STATE"), "required": True},
            {"id": "bridge", "label": "Bridge", "state": connections.get("bridge", "OFF"), "required": True},
            {
                "id": "websocket",
                "label": "WebSocket",
                "state": "READY" if int(self.settings().get("bridgePort") or 0) > 0 else "CHECKING",
                "required": True,
            },
            {
                "id": "ui",
                "label": "UI",
                "state": "READY" if (self.resource_root / "frontend" / "dist" / "index.html").is_file() else "ERROR",
                "required": True,
            },
            {"id": "browser", "label": "Browser", "state": connections.get("browser", "OFF"), "required": True},
            {
                "id": "studio",
                "label": "Roblox Studio",
                "state": str(studio["state"]),
                "required": True,
            },
            {
                "id": "studioTools",
                "label": "Studio capabilities",
                "state": "READY" if not missing_studio_tools else "CAPABILITY_MISSING",
                "required": True,
                "detail": "" if not missing_studio_tools else ", ".join(missing_studio_tools),
            },
            {
                "id": "storage",
                "label": "Storage",
                "state": "READY" if usage.total <= self.storage.budget_bytes else "CLEANUP_REQUIRED",
                "required": True,
            },
        ]
        provider_steps = [
            {
                "id": item["providerId"],
                "label": item["displayName"],
                "state": item["authState"],
                "required": item["required"],
                "detail": item["detail"],
            }
            for item in providers
        ]
        steps = [*checks, *provider_steps]
        ready_states = {"READY", "PROJECT_READY"}
        required_ready = all(not item["required"] or item["state"] in ready_states for item in steps)
        optional_problem = any(not item["required"] and item["state"] in {"ERROR", "EXPIRED"} for item in steps)
        readiness_state = "READY" if required_ready else "ACTION_REQUIRED"
        if required_ready and optional_problem:
            readiness_state = "DEGRADED"
        result = {
            "state": readiness_state,
            "canRunProjectTasks": required_ready,
            "checkedAt": int(time.time() * 1000),
            "checks": checks,
            "steps": steps,
            "providers": providers,
            "studio": studio,
            "storage": {
                "bytesUsed": usage.total,
                "budgetBytes": self.storage.budget_bytes,
                "withinBudget": usage.total <= self.storage.budget_bytes,
            },
            "system": self.system_diagnostics.inspect(),
        }
        previous = self._readiness_cache[1] if self._readiness_cache else None
        self._readiness_cache = (time.monotonic(), result)
        comparable = {key: value for key, value in result.items() if key != "checkedAt"}
        previous_comparable = (
            {key: value for key, value in previous.items() if key != "checkedAt"} if previous else None
        )
        if previous_comparable != comparable:
            self.events.publish("READINESS_CHANGED", {"readiness": result})
        return json.loads(json.dumps(result))

    def connections(self) -> dict[str, str]:
        with self._connections_lock:
            return dict(self._connections)

    def providers(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        return [self.provider(str(item["providerId"]), refresh=refresh) for item in self.provider_registry.catalog()]

    def provider(self, provider_id: str, *, refresh: bool = False) -> dict[str, Any]:
        try:
            manifest = self.provider_registry.get(provider_id)
        except KeyError as exc:
            raise CoreError("UNKNOWN_PROVIDER", "Unknown provider.", status=404) from exc
        result = manifest.public()
        selections = self.store.get_setting("provider.selections", {})
        selections = selections if isinstance(selections, dict) else {}
        assigned = self.store.get_setting("provider.roles", {})
        assigned = assigned if isinstance(assigned, dict) else {}
        result["selection"] = dict(selections.get(provider_id) or {})
        result["roles"] = list(assigned.get(provider_id) or manifest.roles)
        if not manifest.enabled:
            result.update({"authState": AuthState.UNKNOWN.value, "route": "", "liveCapabilities": None})
            return result
        status = self.bridge.provider_status().get(provider_id, {})
        result["authState"] = self._provider_auth_state(str(status.get("state") or "UNKNOWN")).value
        result["route"] = str(status.get("route") or status.get("transport") or self.bridge.selected_route(provider_id))
        result["detail"] = str(status.get("detail") or "")
        metadata = getattr(self.bridge, "session_metadata", None)
        result["session"] = metadata(provider_id) if callable(metadata) else None
        result["liveCapabilities"] = None
        if refresh and self.bridge.wait_for_provider(provider_id, timeout=2):
            try:
                response = self.bridge.request(provider_id, "capabilities", {}, task_id="provider-refresh", timeout=15)
                raw = response.get("capabilities")
                result["liveCapabilities"] = normalize_capabilities(dict(raw) if isinstance(raw, dict) else {})
                result["authState"] = AuthState.READY.value
            except BridgeError as exc:
                result["detail"] = str(exc)
        return result

    def refresh_provider(self, provider_id: str) -> dict[str, Any]:
        manifest = self.provider(provider_id)
        if not bool(self.provider_registry.get(provider_id).enabled):
            return manifest
        if not self.bridge.wait_for_provider(provider_id, timeout=2):
            raise CoreError(
                "PROVIDER_LOGIN_REQUIRED",
                f"{PROVIDER_LABELS[provider_id]} requires login.",
                status=409,
                details={"provider": provider_id},
            )
        try:
            self.bridge.request(provider_id, "reload", {}, task_id="provider-refresh", timeout=30)
        except BridgeError:
            pass
        payload = self.provider(provider_id, refresh=True)
        self.events.publish("PROVIDER_CAPABILITIES_CHANGED", {"provider": payload})
        return payload

    def select_provider(self, provider_id: str, selection: dict[str, Any]) -> dict[str, Any]:
        try:
            manifest = self.provider_registry.get(provider_id)
        except KeyError as exc:
            raise CoreError("PROVIDER_NOT_FOUND", "Provider not found.", status=404) from exc
        if not manifest.enabled:
            raise CoreError("PROVIDER_UNSUPPORTED", "This provider has no verified active adapter.", status=409)
        route = str(selection.get("route") or "").strip().casefold()
        if route:
            try:
                self.bridge.select_route(provider_id, route)
            except BridgeError as exc:
                raise CoreError("INVALID_PROVIDER_ROUTE", str(exc)) from exc
        mode = str(selection.get("mode") or "").strip().casefold()
        model = str(selection.get("model") or "").strip()
        if mode and mode not in {item.id for item in manifest.modes}:
            raise CoreError("INVALID_PROVIDER_MODE", "Invalid provider mode.")
        if mode in {"instant", "expert"}:
            try:
                self.bridge.request(
                    provider_id,
                    "select_mode",
                    {"mode": mode},
                    task_id="provider-selection",
                    timeout=30,
                )
            except BridgeError as exc:
                raise CoreError("PROVIDER_MODE_UNAVAILABLE", str(exc), status=409) from exc
        if model:
            self.set_model(provider_id, model)
        stored = self.store.get_setting("provider.selections", {})
        stored = dict(stored) if isinstance(stored, dict) else {}
        stored[provider_id] = {
            key: value for key, value in {"route": route, "mode": mode, "model": model}.items() if value
        }
        self.store.set_setting("provider.selections", stored)
        update_selection = getattr(self.bridge, "update_selection", None)
        if callable(update_selection):
            update_selection(provider_id, model=model, mode=mode)
        payload = self.provider(provider_id, refresh=True)
        self.events.publish("PROVIDER_MODEL_CHANGED", {"providerId": provider_id, "selection": stored[provider_id]})
        return payload

    def assign_provider_role(self, provider_id: str, role: str) -> dict[str, Any]:
        try:
            manifest = self.provider_registry.get(provider_id)
        except KeyError as exc:
            raise CoreError("PROVIDER_NOT_FOUND", "Provider not found.", status=404) from exc
        normalized = role.strip().upper()
        if normalized == "3D":
            normalized = "THREED"
        if not manifest.enabled or normalized not in {"BUILDER", "REVIEWER", "VISUAL", "RESEARCH", "THREED"}:
            raise CoreError("INVALID_PROVIDER_ROLE", "Invalid provider role assignment.")
        bindings = self.store.get_setting("provider.roles", {})
        bindings = dict(bindings) if isinstance(bindings, dict) else {}
        for key, roles in tuple(bindings.items()):
            values = roles if isinstance(roles, list) else []
            bindings[key] = [
                item
                for item in values
                if ("THREED" if str(item).upper() == "3D" else str(item).upper()) != normalized
            ]
        current = bindings.get(provider_id)
        values = current if isinstance(current, list) else []
        bindings[provider_id] = list(dict.fromkeys([*values, normalized]))
        self.store.set_setting("provider.roles", bindings)
        return self.provider(provider_id)

    def create_custom_provider(self, provider_id: str, display_name: str, web_url: str) -> dict[str, Any]:
        try:
            manifest = self.provider_registry.register_custom(
                provider_id.strip(), display_name.strip(), web_url.strip()
            )
        except ValueError as exc:
            raise CoreError("INVALID_CUSTOM_PROVIDER", str(exc)) from exc
        stored = self.store.get_setting("provider.custom", [])
        entries = [dict(item) for item in stored if isinstance(item, dict)] if isinstance(stored, list) else []
        entry = {
            "providerId": manifest.id,
            "displayName": manifest.display_name,
            "webUrl": manifest.web_url,
            "support": "UNSUPPORTED",
        }
        entries = [item for item in entries if str(item.get("providerId")) != manifest.id]
        entries.append(entry)
        self.store.set_setting("provider.custom", entries)
        return self.provider(manifest.id)

    def agents(self) -> list[dict[str, Any]]:
        connections = self.connections()
        models = self.settings()["models"]
        assigned = self.store.get_setting("provider.roles", {})
        assigned = assigned if isinstance(assigned, dict) else {}
        return [
            {
                "id": "chatgpt",
                "name": PROVIDER_LABELS["chatgpt"],
                "providerId": "chatgpt",
                "roles": list(assigned.get("chatgpt") or PROVIDER_ROLES["chatgpt"]),
                "status": connections["chatgpt"],
                "model": models["chatgpt"]["model"],
                "reasoning": bool(models["chatgpt"]["reasoning"]),
            },
            {
                "id": "deepseek",
                "name": PROVIDER_LABELS["deepseek"],
                "providerId": "deepseek",
                "roles": list(assigned.get("deepseek") or PROVIDER_ROLES["deepseek"]),
                "status": connections["deepseek"],
                "model": models["deepseek"]["model"],
                "reasoning": bool(models["deepseek"]["reasoning"]),
            },
            {
                "id": "hunyuan",
                "name": PROVIDER_LABELS["hunyuan"],
                "providerId": "hunyuan",
                "roles": list(assigned.get("hunyuan") or PROVIDER_ROLES["hunyuan"]),
                "status": connections["hunyuan"],
                "version": models["hunyuan"]["version"],
                "quality": models["hunyuan"]["quality"],
            },
            {"id": "studio", "name": "Roblox Studio", "status": connections["studio"]},
        ]

    def login_provider(self, provider: str) -> bool:
        if provider not in {"chatgpt", "deepseek", "hunyuan"}:
            raise CoreError("UNKNOWN_PROVIDER", "Unknown provider.", status=404)
        with self._provider_lock:
            existing = self._provider_threads.get(provider)
            if existing is not None and existing.is_alive():
                return True
            thread = threading.Thread(
                target=self._login_worker,
                args=(provider,),
                name=f"Zenless-Login-{provider}",
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

    def create_job(
        self,
        title: str,
        options: dict[str, Any] | TaskOptions | None = None,
        *,
        attachments: tuple[Path, ...] = (),
    ) -> dict[str, Any]:
        try:
            task_id = self.orchestrator.submit(
                title,
                (options if isinstance(options, TaskOptions) else TaskOptions.from_api(options)).resolve(title),
                attachment_paths=attachments,
            )
        except OrchestratorError as exc:
            raise CoreError("JOB_BUSY", str(exc), status=409) from exc
        for path in attachments:
            self._register_file_asset(path, job_id=task_id, kind="IMG" if self._is_image(path) else "RBX")
        return self.job(task_id)

    def pause_job(self, job_id: str) -> dict[str, Any]:
        if not self.orchestrator.pause(job_id):
            raise CoreError("JOB_NOT_PAUSABLE", "The job cannot be paused in its current state.", status=409)
        return self.job(job_id)

    def resume_job(self, job_id: str) -> dict[str, Any]:
        if self.orchestrator.resume(job_id):
            return self.job(job_id)
        task = self._require_task(job_id)
        if str(task.get("stage")) != Stage.PAUSED.value or "Checkpoint recovered" not in str(task.get("error")):
            raise CoreError("JOB_NOT_RESUMABLE", "The job is not paused.", status=409)
        try:
            options = TaskOptions(**dict(task.get("options") or {})).resolve(str(task.get("prompt") or ""))
            replacement_id = self.orchestrator.submit(str(task.get("prompt") or ""), options)
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
        return stopped or cancelled

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
            if existing and str(existing.get("status")) in {"running", "waiting"}:
                raise CoreError(
                    "JOB_ALREADY_RUNNING",
                    "The current job is still running. Pause, complete, or cancel it before sending another request.",
                    status=409,
                )
        task_options = TaskOptions.from_api(options).resolve(objective)
        roles = self._preflight_providers(task_options)
        builder = roles["BUILDER"]
        prepared = self._prepare_attachments(attachments, builder) if attachments else attachments
        job = self.create_job(objective, options=task_options, attachments=prepared)
        user_messages = [message for message in self.messages(job["id"]) if message["role"] == "user"]
        message_id = user_messages[-1]["id"] if user_messages else uuid.uuid4().hex
        return {"messageId": message_id, "jobId": job["id"]}

    def cancel_generation(self, job_id: str) -> bool:
        result = self.cancel_job(job_id)
        for provider in ("chatgpt", "deepseek", "hunyuan"):
            try:
                if self.bridge.wait_for_provider(provider, timeout=0.1):
                    self.bridge.request(provider, "cancel", {}, task_id=job_id, timeout=5)
            except BridgeError:
                continue
        return result

    def _preflight_providers(self, options: TaskOptions) -> dict[str, str]:
        roles = self._resolved_role_providers()
        required = [roles["BUILDER"]]
        if options.independent_review:
            required.append(roles["REVIEWER"])
        if options.visual_first or options.create_3d_asset:
            required.append(roles["VISUAL"])
        if options.create_3d_asset:
            required.append(roles["3D"])
        for provider in dict.fromkeys(required):
            if self.connections()[provider] == "READY":
                continue
            try:
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
        return roles

    def _resolved_role_providers(self) -> dict[str, str]:
        store = getattr(self, "store", None)
        return resolve_provider_roles(store.get_setting("provider.roles", {}) if store else None)

    def timeline(self, job_id: str) -> dict[str, Any]:
        self._require_task(job_id)
        messages = self.messages(job_id)
        activities = self.store.list_activities(job_id)
        artifacts = self.store.list_artifacts(job_id)
        snapshot = self.store.test_snapshot(job_id)
        test_data = {
            "testState": self.test_state(job_id),
            "cases": snapshot["cases"],
            "failures": snapshot["failures"],
            "logs": snapshot["logs"],
        }
        return {
            "jobId": job_id,
            "messages": messages,
            "activities": activities,
            "artifacts": artifacts,
            "test": test_data,
        }

    def messages(self, job_id: str) -> list[dict[str, Any]]:
        result = []
        for row in self.store.task_messages(job_id):
            role = "user" if row["role"] == "user" else ("system" if row["role"] == "error" else "zenless")
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

    def _message_action(self, content: str) -> dict[str, str] | None:
        normalized = content.casefold()
        if "login" not in normalized and "authenticate" not in normalized:
            return None
        for provider, label in PROVIDER_LABELS.items():
            if provider in normalized or label.casefold() in normalized:
                return {"type": "LOGIN", "provider": provider}
        roles = self._resolved_role_providers()
        for marker, provider in {
            "builder": roles["BUILDER"],
            "reviewer": roles["REVIEWER"],
            "visual generator": roles["VISUAL"],
            "researcher": roles["RESEARCH"],
            "3d generator": roles["3D"],
        }.items():
            if marker in normalized:
                return {"type": "LOGIN", "provider": provider}
        return None

    def context(self, job_id: str, *, refresh: bool = False) -> list[dict[str, Any]]:
        if refresh:
            self.refresh_studio()
        stored = self.store.context_items(job_id)
        if stored:
            return [self._public_context(item) for item in stored]
        task = self.store.load_task(job_id)
        if task is None:
            raise CoreError("JOB_NOT_FOUND", "Job not found.", status=404)
        items = self._derive_context_items(job_id, task.get("context") or {})
        if items:
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
            job_id = str(item["job_id"])
            self.events.publish("CONTEXT_UPDATED", {"jobId": job_id, "items": self.context(job_id)})
        return True

    def changes(self, job_id: str) -> list[dict[str, Any]]:
        task = self._require_task(job_id)
        proposal = task.get("proposal") or {}
        files: list[dict[str, Any]] = []
        for index, raw in enumerate(proposal.get("actions") or []):
            if not isinstance(raw, dict) or is_read_only(str(raw.get("tool", ""))):
                continue
            raw_arguments = raw.get("arguments")
            arguments: dict[str, Any] = raw_arguments if isinstance(raw_arguments, dict) else {}
            name = str(arguments.get("file_path") or arguments.get("target_file") or raw.get("tool") or "change")
            content = json.dumps(arguments, ensure_ascii=False, indent=2)
            diff = [
                {"type": "hunk", "content": f"@@ Studio {raw.get('tool', '')} @@"},
                *(
                    {"type": "added", "content": line, "newLine": line_no}
                    for line_no, line in enumerate(content.splitlines(), 1)
                ),
            ]
            files.append(
                {
                    "id": f"change-{job_id[:10]}-{index}",
                    "name": name,
                    "status": "M",
                    "additions": len(content.splitlines()),
                    "deletions": 0,
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
        reviewer_id = self._resolved_role_providers()["REVIEWER"]
        return {
            "decision": decision,
            "risk": risk,
            "criticalIssues": issues if risk in {"HIGH", "CRITICAL"} else [],
            "warnings": issues if risk not in {"HIGH", "CRITICAL"} else [],
            "suggestions": [str(item) for item in raw.get("required_changes", [])],
            "summary": str(raw.get("summary", "")),
            "reviewer": PROVIDER_LABELS[reviewer_id],
            "providerId": reviewer_id,
            "role": "REVIEWER",
            "timestamp": _milliseconds(task["updated_at"]),
            "files": self.changes(job_id),
            "ready": bool(raw),
        }

    def approve_changes(self, job_id: str, approved: bool, note: str = "") -> bool:
        decision = "approve" if approved else "reject"
        if not self.orchestrator.approve_active(job_id, ("changes:", "repair:"), decision, note):
            raise CoreError("NO_CHANGE_GATE", "No change is waiting for a decision.", status=409)
        self._transition_latest_artifact(job_id, "DIFF", "APPROVED" if approved else "REJECTED")
        return True

    def edit_changes(self, job_id: str, _file_id: str, content: str) -> bool:
        if not content.strip():
            raise CoreError("EMPTY_EDIT", "The edit note is empty.")
        if not self.orchestrator.approve_active(job_id, ("changes:", "repair:"), "edit", content):
            raise CoreError("NO_CHANGE_GATE", "No change is waiting for an edit.", status=409)
        self._transition_latest_artifact(job_id, "DIFF", "REJECTED")
        return True

    def visual(self, job_id: str) -> dict[str, Any]:
        task = self._require_task(job_id)
        context = task.get("context") or {}
        raw_visual = context.get("visual") if isinstance(context, dict) else None
        visual: dict[str, Any] = raw_visual if isinstance(raw_visual, dict) else {}
        approved = str(visual.get("status") or "").upper() == "APPROVED"
        failed = str(visual.get("status") or "").upper() == "FAILED"
        views = []
        for name in ("FRONT", "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM"):
            entry = visual.get(name.casefold(), {}) if isinstance(visual, dict) else {}
            asset_id = str(entry.get("asset_id", "")) if isinstance(entry, dict) else ""
            views.append(
                {
                    "name": name,
                    "state": "FAILED" if failed else (("APPROVED" if approved else "READY") if asset_id else "EMPTY"),
                    **({"assetId": asset_id} if asset_id else {}),
                    **({"imageUrl": f"/api/assets/{asset_id}/content"} if asset_id else {}),
                }
            )
        proposal = task.get("proposal") or {}
        prompt = str(visual.get("prompt") or proposal.get("visual_prompt", ""))
        stage = str(task.get("stage", ""))
        persisted_status = str(visual.get("status") or "")
        if persisted_status:
            status = persisted_status
        elif stage == Stage.GENERATING_CONCEPT.value:
            status = "GENERATING"
        elif stage == Stage.WAITING_IMAGE_APPROVAL.value:
            status = "READY"
        elif stage in {Stage.FAILED.value, Stage.BLOCKED.value}:
            status = "FAILED"
        else:
            status = "IDLE"
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
        task = self._require_task(job_id)
        raw_context = task.get("context")
        context: dict[str, Any] = raw_context if isinstance(raw_context, dict) else {}
        raw_visual = context.get("visual")
        visual: dict[str, Any] = raw_visual if isinstance(raw_visual, dict) else {}
        self.store.update_context_section(job_id, "visual", {**visual, "status": "APPROVED"})
        views = ["FRONT", "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM"]
        concept_version = max(0, int(visual.get("version") or 0))
        self.events.publish(
            "VISUAL_APPROVED",
            {"jobId": job_id, "views": views, "conceptVersion": concept_version},
        )
        self._publish_visual_artifact(job_id, state="APPROVED")
        return True

    def edit_visual(self, job_id: str, prompt: str) -> bool:
        if not prompt.strip():
            raise CoreError("EMPTY_VISUAL_EDIT", "Describe the requested visual adjustment.")
        if not self.orchestrator.approve_active(job_id, ("visual",), "edit", prompt):
            raise CoreError("NO_VISUAL_GATE", "No visual concept is waiting for an edit.", status=409)
        self._transition_latest_artifact(job_id, "IMAGE", "REJECTED")
        return True

    def regenerate_visual(self, job_id: str, view: str = "") -> bool:
        normalized = view.strip().casefold()
        if normalized and normalized not in {"front", "back", "left", "right", "top", "bottom"}:
            raise CoreError("INVALID_VISUAL_VIEW", "Invalid visual view.")
        note = f"regen:view:{normalized}" if normalized else "regen:all"
        if not self.orchestrator.approve_active(job_id, ("visual",), "edit", note):
            raise CoreError("NO_VISUAL_GATE", "No visual concept is waiting for regeneration.", status=409)
        self._transition_latest_artifact(job_id, "IMAGE", "REJECTED")
        return True

    def model(self, job_id: str) -> dict[str, Any]:
        task = self._require_task(job_id)
        context = task.get("context") if isinstance(task.get("context"), dict) else {}
        raw_model = context.get("model") if isinstance(context, dict) else None
        model: dict[str, Any] = raw_model if isinstance(raw_model, dict) else {}
        stage = str(task.get("stage", ""))
        artifacts = [item for item in self.store.list_artifacts(job_id) if item["type"] == "MODEL_3D"]
        latest = artifacts[-1] if artifacts else {}
        artifact_state = str(latest.get("state") or "")
        final_asset_id = str(model.get("asset_id") or "")
        if not final_asset_id and artifact_state in {"READY", "APPROVED"}:
            final_asset_id = str((latest.get("metadata") or {}).get("assetId") or "")
        asset = self.store.asset(final_asset_id) if final_asset_id else None
        if asset is None or artifact_state in {"GENERATING", "FAILED"}:
            state = (
                "GENERATING"
                if artifact_state == "GENERATING" or stage == Stage.GENERATING_3D.value
                else (
                    "FAILED"
                    if artifact_state == "FAILED" or stage in {Stage.FAILED.value, Stage.BLOCKED.value}
                    else "IDLE"
                )
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
            "state": "READY",
            "approvalState": "APPROVED" if approved else "PENDING_APPROVAL",
            "geometryStatus": "READY" if model.get("geometry_path") else "IDLE",
            "textureStatus": "READY" if model.get("texture_path") else "IDLE",
            "modelUrl": f"/api/assets/{asset['id']}/content",
            "filename": asset["name"],
        }

    def approve_model(self, job_id: str) -> bool:
        if not self.orchestrator.approve_active(job_id, ("3d",), "approve"):
            raise CoreError("NO_MODEL_GATE", "No 3D model is waiting for approval.", status=409)
        task = self._require_task(job_id)
        raw_context = task.get("context")
        context: dict[str, Any] = raw_context if isinstance(raw_context, dict) else {}
        raw_model = context.get("model")
        model: dict[str, Any] = raw_model if isinstance(raw_model, dict) else {}
        self.store.update_context_section(job_id, "model", {**model, "status": "APPROVED"})
        self.events.publish("MODEL_APPROVED", {"jobId": job_id})
        artifacts = [item for item in self.store.list_artifacts(job_id) if item["type"] == "MODEL_3D"]
        if artifacts:
            latest = artifacts[-1]
            self._publish_artifact({**latest, "state": "APPROVED"})
        return True

    def regenerate_model(self, job_id: str, target: str) -> bool:
        if target not in {"geometry", "texture"}:
            raise CoreError("INVALID_MODEL_TARGET", "Invalid 3D target.")
        provider = self._resolved_role_providers()["3D"]
        if not self.bridge.wait_for_provider(provider, timeout=0.5):
            raise CoreError(
                "PROVIDER_LOGIN_REQUIRED",
                f"{PROVIDER_LABELS[provider]} requires login for 3D generation.",
                status=409,
                details={"provider": provider},
            )
        if not self.orchestrator.approve_active(job_id, ("3d",), "edit", f"regen:{target}"):
            raise CoreError("NO_MODEL_GATE", "No 3D model is waiting for regeneration.", status=409)
        self._transition_latest_artifact(job_id, "MODEL_3D", "REJECTED")
        return True

    def assets(self) -> list[dict[str, Any]]:
        result = []
        for asset in self.store.assets():
            result.append(
                {
                    "id": asset["id"],
                    "name": asset["name"],
                    "type": asset["kind"],
                    "url": f"/api/assets/{asset['id']}/content",
                    "size": int(asset["size"]),
                    "createdAt": _milliseconds(asset["created_at"]),
                    "jobId": asset["job_id"] or None,
                    **dict(asset.get("metadata") or {}),
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
        selection = self.studio_discovery.selection
        selected = selection.selected if selection else None
        raw = selected.raw if selected else {}
        return {
            "state": "ONLINE"
            if self.connections()["studio"] == "READY"
            else ("CONNECTING" if self.connections()["studio"] == "CONNECTING" else "OFFLINE"),
            "readiness": selection.state.value if selection else "STUDIO_NOT_RUNNING",
            "selectedStudioId": selected.studio_id if selected else None,
            "studioId": selected.studio_id if selected else None,
            "projectName": (
                raw.get("project") or raw.get("name") or raw.get("place_name") or raw.get("placeName")
                if selected
                else None
            ),
            "placeId": raw.get("place_id") or raw.get("placeId") if selected else None,
            "universeId": raw.get("universe_id") or raw.get("universeId") if selected else None,
        }

    def studios(self, *, refresh: bool = False) -> dict[str, Any]:
        selection = self.studio_discovery.selection
        if refresh or selection is None:
            preferred = self.store.get_setting("studio.selection", {})
            preferred = preferred if isinstance(preferred, dict) else {}
            selection = self.studio_discovery.discover(
                preferred_studio_id=str(preferred.get("studioId") or ""),
                preferred_place_id=str(preferred.get("placeId") or ""),
                preferred_universe_id=str(preferred.get("universeId") or ""),
            )
        payload = selection.public()
        payload["capabilities"] = self.studio_capabilities.public() if getattr(self.studio, "running", False) else []
        return payload

    def select_studio(self, studio_id: str) -> dict[str, Any]:
        try:
            selection = self.studio_discovery.select(studio_id)
        except MCPError as exc:
            raise CoreError("STUDIO_SELECTION_INVALID", str(exc), status=409) from exc
        target = selection.selected
        if target is None:
            raise CoreError("STUDIO_SELECTION_INVALID", "Studio selection failed.", status=409)
        self.store.set_setting(
            "studio.selection",
            {
                "studioId": target.studio_id,
                "placeId": target.raw.get("place_id") or target.raw.get("placeId"),
                "universeId": target.raw.get("universe_id") or target.raw.get("universeId"),
            },
        )
        self.events.publish("STUDIO_DISCOVERY_CHANGED", selection.public())
        return self.studios()

    def studio_tree(self) -> list[dict[str, Any]]:
        with self._studio_lock:
            return json.loads(json.dumps(self._studio_tree))

    def refresh_studio(self) -> bool:
        try:
            selection_payload = self.studios(refresh=True)
            selection = self.studio_discovery.selection
            target = selection.selected if selection else None
            if selection is None or target is None:
                if selection and len(selection.studios) > 1:
                    self.events.publish("STUDIO_SELECTION_REQUIRED", selection_payload)
                    raise CoreError("STUDIO_SELECTION_REQUIRED", selection.detail, status=409)
                detail = selection.detail if selection else "No Studio instance is connected."
                raise MCPError(detail)
            result = self.studio.call_tool(
                "search_game_tree",
                {"datamodel_type": "Edit", "max_depth": 5, "head_limit": 500},
                studio_id=target.studio_id,
                timeout=90,
            )
            if result.is_error:
                raise MCPError(result.compact(4000))
            tree, nodes = self._parse_studio_tree(result.text)
            with self._studio_lock:
                self._studio_tree = tree
                self._studio_nodes = nodes
            self._set_connection("studio", "READY")
            self.events.publish("STUDIO_STATE_CHANGED", self.studio_state())
            if selection is None:
                raise MCPError("Studio selection became unavailable during refresh.")
            self.events.publish("STUDIO_DISCOVERY_CHANGED", selection.public())
            self.events.publish("STUDIO_TREE_UPDATED", {"tree": tree})
            return True
        except CoreError:
            raise
        except Exception as exc:
            self._set_connection("studio", "ERR")
            self.events.publish("STUDIO_STATE_CHANGED", {"state": "OFFLINE"})
            self._report("studio", "refresh", exc, "Open Studio in Edit mode and enable MCP servers.")
            raise CoreError("STUDIO_UNAVAILABLE", str(exc), status=503) from exc

    def search_studio(self, query: str) -> list[dict[str, Any]]:
        needle = query.strip().casefold()
        with self._studio_lock:
            values = list(self._studio_nodes.values())
        if not needle:
            return values[:200]
        return [item for item in values if needle in item["name"].casefold() or needle in item["path"].casefold()][:200]

    def inspect_studio(self, node_id: str) -> dict[str, Any]:
        with self._studio_lock:
            node = self._studio_nodes.get(node_id)
        if node is None:
            raise CoreError("STUDIO_NODE_NOT_FOUND", "Studio object not found.", status=404)
        return dict(node)

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
        if not self.qa.start_manual(job_id, profile):
            raise CoreError("TEST_ALREADY_RUNNING", "A test is already running.", status=409)
        return True

    def stop_test(self, job_id: str) -> bool:
        if not self.qa.stop(job_id):
            raise CoreError("TEST_NOT_RUNNING", "No test is running.", status=409)
        return True

    def test_state(self, job_id: str) -> dict[str, Any]:
        task = self._require_task(job_id)
        latest = self.store.latest_test_run(job_id)
        if self.qa.running(job_id):
            status = "RUNNING"
        elif latest is None:
            status = "IDLE"
        elif latest["status"] == "FAILED":
            status = "FAILED"
        elif latest["status"] == "STALE":
            status = "STALE"
        else:
            status = "STOPPED"
        options = task.get("options") or {}
        result = {
            "status": status,
            "elapsedMs": int((latest or {}).get("summary", {}).get("durationMs", 0)),
            "fixAttempt": 0,
            "maxFixAttempts": int(options.get("max_test_fixes", 3)),
        }
        if latest and str(latest["status"]) in self.store.FINAL_TEST_STATUSES:
            counts = self.store.test_case_counts(str(latest["id"]))
            result["resultStatus"] = str(latest["status"])
            result["counts"] = {
                key: counts[key] for key in ("total", "passed", "failed", "skipped")
            }
        return result

    def storage_status(self) -> dict[str, Any]:
        usage = self.storage.usage()
        labels = {
            "database": "DATABASE",
            "logs": "LOGS",
            "runs": "RUNS",
            "job_snapshots": "JOB_SNAPSHOTS",
            "generated_images": "GENERATED_IMAGES",
            "generated_3d": "GENERATED_3D",
            "downloads": "DOWNLOADS",
            "temporary": "TEMP",
            "browser_cache": "BROWSER_CACHE",
            "browser_profile": "BROWSER_SESSION_PROFILE",
            "browser_runtime": "BROWSER_RUNTIME",
            "optional_tools": "OPTIONAL_TOOLS",
            "tool_cache": "TOOL_CACHE",
            "test_artifacts": "TEST_ARTIFACTS",
            "other": "OTHER",
        }
        categories = [
            {"id": labels[key], "bytes": value, "protected": key in {"database", "browser_profile", "browser_runtime"}}
            for key, value in asdict(usage).items()
        ]
        return {
            "bytesUsed": usage.total,
            "budgetBytes": self.storage.budget_bytes,
            "withinBudget": usage.total <= self.storage.budget_bytes,
            "categories": categories,
        }

    def cleanup_storage(self) -> dict[str, Any]:
        protected = []
        active = self.orchestrator.current_task_id
        if active:
            protected.append(self.data_root / "runs" / active)
            protected.extend(Path(str(asset["path"])) for asset in self.store.assets(active))
        result = self.storage.cleanup_to_budget(protected_paths=tuple(protected))
        payload = result.public()
        response = {**payload, "storage": self.storage_status()}
        self.events.publish("STORAGE_CLEANUP_COMPLETED", response)
        return response

    def update_storage_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        raw = patch.get("budgetBytes")
        if raw is None:
            raise CoreError("INVALID_STORAGE_SETTINGS", "budgetBytes is required.")
        try:
            budget = self.storage.set_budget(int(raw))
        except (TypeError, ValueError) as exc:
            raise CoreError("INVALID_STORAGE_SETTINGS", "Invalid storage budget.") from exc
        self.store.set_setting("storage.budget", budget)
        return self.storage_status()

    def tool_catalog(self) -> list[dict[str, object]]:
        return self.tools.catalog()

    def install_tool(self, tool_id: str) -> dict[str, object]:
        try:
            result = self.tools.install(tool_id)
        except ToolError as exc:
            raise CoreError("TOOL_INSTALL_UNAVAILABLE", str(exc), status=409) from exc
        self.events.publish("TOOL_STATUS_CHANGED", {"tool": result})
        return result

    def remove_tool(self, tool_id: str) -> dict[str, object]:
        try:
            result = self.tools.remove(tool_id)
        except ToolError as exc:
            raise CoreError("TOOL_REMOVE_FAILED", str(exc), status=409) from exc
        self.events.publish("TOOL_STATUS_CHANGED", {"tool": result})
        return result

    def uninstall(self, mode: str) -> dict[str, object]:
        try:
            result = self.uninstaller.execute(mode)
        except UninstallError as exc:
            raise CoreError("UNINSTALL_UNAVAILABLE", str(exc), status=409) from exc
        callback = self._shutdown_callback
        if callable(callback):
            threading.Timer(0.75, callback).start()
        return result

    def repair_component(self, component: str) -> dict[str, Any]:
        normalized = component.strip().upper()
        try:
            if normalized == "WEBVIEW2":
                path = ensure_webview2(self.resource_root, self.data_root)
                return {"component": normalized, "state": "READY", "path": str(path)}
            if normalized in {"MANAGED_CHROMIUM", "BROWSER_RUNTIME"}:
                path = self.managed_browser.runtime.install()
                return {"component": normalized, "state": "READY", "path": str(path)}
            if normalized == "FRONTEND_BUNDLE":
                bundle = self.resource_root / "frontend" / "dist" / "index.html"
                if bundle.is_file():
                    return {"component": normalized, "state": "READY", "path": str(bundle)}
                raise CoreError("REPAIR_SOURCE_UNAVAILABLE", "The packaged frontend bundle is missing.", status=409)
        except (BridgeError, ProvisioningError) as exc:
            raise CoreError("COMPONENT_REPAIR_FAILED", str(exc), status=503) from exc
        raise CoreError("UNKNOWN_REPAIR_COMPONENT", "Unknown repair component.", status=404)

    def settings(self) -> dict[str, Any]:
        stored = self.store.get_setting("ui.settings", {})
        result = json.loads(json.dumps(self.DEFAULT_SETTINGS))
        if isinstance(stored, dict):
            result.update({key: value for key, value in stored.items() if key in result})
            if isinstance(stored.get("models"), dict):
                for provider, value in stored["models"].items():
                    if provider in result["models"] and isinstance(value, dict):
                        result["models"][provider].update(value)
                if "smartRouting" in stored["models"]:
                    result["models"]["smartRouting"] = bool(stored["models"]["smartRouting"])
        return result

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.settings()
        if "autoApprove" in patch:
            current["autoApprove"] = bool(patch["autoApprove"])
        if "maxRevisions" in patch:
            current["maxRevisions"] = max(1, min(5, int(patch["maxRevisions"])))
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
            "chatgpt": {"models": [{"id": settings["chatgpt"]["model"], "label": settings["chatgpt"]["model"]}]},
            "deepseek": {"models": [{"id": settings["deepseek"]["model"], "label": settings["deepseek"]["model"]}]},
            "hunyuan": {
                "versions": [{"id": settings["hunyuan"]["version"], "label": settings["hunyuan"]["version"]}],
                "qualities": [
                    {"id": "standard", "label": "Standard"},
                    {"id": "high", "label": "High"},
                ],
            },
        }
        for provider in ("chatgpt", "deepseek", "hunyuan"):
            if self.connections()[provider] != "READY":
                continue
            try:
                response = self.bridge.request(provider, "get_models", {}, task_id="settings", timeout=8)
                names = [str(item).strip() for item in response.get("models", []) if str(item).strip()]
            except BridgeError:
                names = []
            if not names:
                continue
            options = [{"id": name, "label": name} for name in names]
            if provider == "hunyuan":
                catalog[provider]["versions"] = options
            else:
                catalog[provider]["models"] = options
        for provider in ("chatgpt", "deepseek", "hunyuan"):
            detail = self.provider(provider, refresh=False)
            catalog[provider]["modes"] = detail.get("modes", [])
            catalog[provider]["selection"] = detail.get("selection", {})
            catalog[provider]["liveCapabilities"] = detail.get("liveCapabilities")
        self._model_cache = (time.monotonic(), catalog)
        return json.loads(json.dumps(catalog))

    def set_model(self, provider: str, model: str) -> bool:
        if provider not in {"chatgpt", "deepseek", "hunyuan"} or not model.strip():
            raise CoreError("INVALID_MODEL", "Invalid model or provider.")
        if model != "auto":
            if not self.bridge.wait_for_provider(provider, timeout=0.5):
                raise CoreError(
                    "PROVIDER_LOGIN_REQUIRED",
                    f"{PROVIDER_LABELS[provider]} requires login.",
                    status=409,
                    details={"provider": provider},
                )
            self.bridge.request(provider, "select_model", {"model": model}, task_id="settings", timeout=15)
        current = self.settings()
        if provider == "hunyuan":
            current["models"][provider]["version"] = model
        else:
            current["models"][provider]["model"] = model
        self.store.set_setting("ui.settings", current)
        self.events.publish("SETTINGS_CHANGED", {"settings": current})
        return True

    def set_smart_routing(self, enabled: bool) -> bool:
        current = self.settings()
        current["models"]["smartRouting"] = bool(enabled)
        self.store.set_setting("ui.settings", current)
        self.events.publish("SETTINGS_CHANGED", {"settings": current})
        return True

    def diagnostics_payload(self) -> list[dict[str, Any]]:
        return [self._diagnostic_payload(event) for event in self.diagnostics.recent(200)]

    def _start_services(self) -> None:
        try:
            recovered = self.store.recover_interrupted_tasks()
            self._set_boot("STATE", "READY")
            for item in recovered:
                job_id = str(item["id"])
                self.events.publish("JOB_UPDATED", {"jobId": job_id, "job": self.job(job_id)})
                self.diagnostics.report(
                    severity="WARNING",
                    source="state",
                    component="recovery",
                    message=str(item["reason"]),
                    impact=f"Interrupted task {item['id']} moved to {item['stage']}.",
                    recovery_action="Resume only pre-mutation checkpoints; inspect blocked mutation evidence manually.",
                )
        except Exception as exc:
            self._set_boot("STATE", "OFF")
            self._report("state", "recovery", exc, "Inspect the local SQLite state before running another mutation.")
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
        self._refresh_provider_states()
        if not self._closing.is_set():
            self._provider_probe_thread = threading.Thread(
                target=self._probe_provider_sessions,
                name="Zenless-Provider-Probe",
                daemon=True,
            )
            self._provider_probe_thread.start()
        try:
            self.refresh_studio()
            self._set_boot("STUDIO", "READY")
        except CoreError:
            self._set_boot("STUDIO", "OFF")
        self._set_boot("UI", "READY")
        self.events.publish("BOOT_COMPLETE", {})

    def _login_worker(self, provider: str) -> None:
        self._set_connection(provider, "LOGIN")
        self.events.publish("AGENT_STATUS_CHANGED", {"agent": provider, "status": "LOGIN"})
        self.events.publish("LOGIN_REQUIRED", {"providerId": provider})
        self.events.publish("LOGIN_WINDOW_WILL_OPEN", {"providerId": provider})

        def on_window_opened(opened_provider: str, route: str) -> None:
            self.events.publish("LOGIN_WINDOW_OPENED", {"providerId": opened_provider, "route": route})

        try:
            self.bridge.login(provider, timeout=600, on_window_opened=on_window_opened)
            self.events.publish("LOGIN_DETECTED", {"providerId": provider})
            self.events.publish("LOGIN_PERSISTENCE_VERIFYING", {"providerId": provider})
            self._set_connection(provider, "READY")
            self.events.publish("AGENT_STATUS_CHANGED", {"agent": provider, "status": "READY"})
            self.events.publish(
                "LOGIN_READY",
                {"providerId": provider, "route": self.bridge.selected_route(provider), "persistent": True},
            )
            self._set_boot("AI", "READY")
        except Exception as exc:
            self._set_connection(provider, "ERR")
            self.events.publish("AGENT_STATUS_CHANGED", {"agent": provider, "status": "ERR"})
            failure = {"providerId": provider, "message": str(exc), "recovery": "Retry provider login."}
            self.events.publish("LOGIN_FAILED", failure)
            self.events.publish(
                "CHAT_SYSTEM_EVENT",
                {
                    "severity": "ERROR",
                    "title": f"{PROVIDER_LABELS[provider]} login failed",
                    "message": str(exc),
                    "recovery": "Retry login. Complete password, challenge, and verification steps manually.",
                },
            )
            self._report(
                "browser", f"login:{provider}", exc, "Retry login. Password, MFA, and CAPTCHA steps remain manual."
            )

    def _refresh_provider_states(self) -> None:
        statuses = self.bridge.provider_status()
        any_ready = False
        for provider in ("chatgpt", "deepseek", "hunyuan"):
            state = str(statuses.get(provider, {}).get("state", "OFF"))
            normalized = "LOGIN" if state.casefold() == "standby" else self._normalize_connection(state)
            self._set_connection(provider, normalized)
            any_ready = any_ready or normalized == "READY"
        self._set_boot("AI", "READY" if any_ready else "OFF")

    def _probe_provider_sessions(self) -> None:
        any_ready = False
        for provider in ("chatgpt", "deepseek", "hunyuan"):
            if self._closing.is_set():
                return
            try:
                ready = self.bridge.wait_for_provider(provider, timeout=45)
            except Exception as exc:
                self._report("browser", f"session-probe:{provider}", exc, "Use Login to authenticate the provider.")
                ready = False
            if ready:
                any_ready = True
                self._set_connection(provider, "READY")
                self.events.publish("AGENT_STATUS_CHANGED", {"agent": provider, "status": "READY"})
                self.events.publish(
                    "LOGIN_READY",
                    {"providerId": provider, "route": self.bridge.selected_route(provider), "persistent": True},
                )
            else:
                self._set_connection(provider, "LOGIN")
                self.events.publish("AGENT_STATUS_CHANGED", {"agent": provider, "status": "LOGIN"})
                self.events.publish("LOGIN_REQUIRED", {"providerId": provider})
        self._set_boot("AI", "READY" if any_ready else "OFF")

    def _on_provider_status(self, provider: str, state: str, _detail: str) -> None:
        if provider in {"chatgpt", "deepseek", "hunyuan"}:
            normalized = self._normalize_connection(state)
            self._set_connection(provider, normalized)
            self.events.publish("AGENT_STATUS_CHANGED", {"agent": provider, "status": normalized})
        elif provider == "browser":
            self._set_connection("browser", self._normalize_connection(state))

    def _on_pipeline_event(self, event: PipelineEvent) -> None:
        if event.kind == "stream_start":
            self.events.publish(
                "CHAT_STREAM_STARTED",
                {"jobId": event.task_id, "messageId": event.message, "provider": event.detail},
            )
            return
        if event.kind == "stream_delta":
            self.events.publish(
                "CHAT_STREAM_DELTA",
                {"jobId": event.task_id, "messageId": event.message, "delta": event.detail},
            )
            return
        if event.kind == "stream_finish":
            self.events.publish("CHAT_STREAM_FINISHED", {"jobId": event.task_id, "messageId": event.message})
            return
        try:
            job = self.job(event.task_id)
        except CoreError:
            return
        if event.stage == Stage.NEW:
            self.events.publish("JOB_CREATED", {"jobId": event.task_id, "job": job})
        else:
            self.events.publish("JOB_UPDATED", {"jobId": event.task_id, "job": job})
        self.events.publish(
            "PIPELINE_STATE_CHANGED",
            {"jobId": event.task_id, "stage": event.stage.value},
        )
        self._record_activity(event, job)

        if event.kind == "visual_generation":
            version = self._event_version(event, self._next_artifact_version(event.task_id, "IMAGE"))
            self._publish_visual_generation(event.task_id, version)
            return
        if event.kind == "visual_ready":
            self._publish_visual_ready(event)
            return
        if event.kind == "model_generation":
            version = self._event_version(event, self._next_artifact_version(event.task_id, "MODEL_3D"))
            self._publish_model_generation(event.task_id, version)
            return
        if event.kind == "model_geometry_ready":
            self.events.publish(
                "MODEL_GENERATION_CHANGED",
                {"jobId": event.task_id, "target": "geometry", "state": "READY"},
            )
            self.events.publish(
                "MODEL_GENERATION_CHANGED",
                {"jobId": event.task_id, "target": "texture", "state": "GENERATING"},
            )
            return
        if event.kind == "model_texture_generation":
            self.events.publish(
                "MODEL_GENERATION_CHANGED",
                {"jobId": event.task_id, "target": "texture", "state": "GENERATING"},
            )
            return
        if event.kind == "diff_generation":
            revision = self._next_artifact_version(event.task_id, "DIFF")
            self._publish_artifact(
                {
                    "id": f"artifact-diff-{event.task_id}-r{revision}",
                    "jobId": event.task_id,
                    "type": "DIFF",
                    "name": "Code changes",
                    "state": "GENERATING",
                    "version": revision,
                    "revision": revision,
                }
            )
            return

        if event.stage == Stage.WAITING_CHANGE_APPROVAL:
            files = self.changes(event.task_id)
            self.events.publish("CHANGES_UPDATED", {"jobId": event.task_id, "files": files})
            rev = self.review(event.task_id)
            self.events.publish("REVIEW_READY", {"jobId": event.task_id, "review": rev})
            artifacts = [item for item in self.store.list_artifacts(event.task_id) if item["type"] == "DIFF"]
            generating = next((item for item in reversed(artifacts) if item["state"] == "GENERATING"), None)
            revision = (
                int(generating.get("revision") or generating.get("version") or 1)
                if generating
                else self._next_artifact_version(event.task_id, "DIFF")
            )
            self._publish_artifact(
                {
                    "id": f"artifact-diff-{event.task_id}-r{revision}",
                    "jobId": event.task_id,
                    "type": "DIFF",
                    "name": "Code changes ready",
                    "state": "READY",
                    "revision": revision,
                    "version": revision,
                    "metadata": {
                        "risk": rev.get("risk"),
                        "reviewer": rev.get("reviewer"),
                        "reviewerRole": rev.get("role"),
                        "providerId": rev.get("providerId"),
                        "decision": rev.get("decision"),
                        "fileCount": len(files),
                    },
                }
            )
        elif event.stage == Stage.WAITING_IMAGE_APPROVAL:
            self._publish_visual_state(event.task_id)
            self._publish_visual_artifact(event.task_id)
        elif event.stage == Stage.GENERATING_CONCEPT:
            self._publish_visual_state(event.task_id, fallback="GENERATING")
        elif event.stage == Stage.GENERATING_3D:
            self.events.publish("MODEL_GENERATION_CHANGED", {"jobId": event.task_id, "target": "geometry", "state": "GENERATING"})
        elif event.stage == Stage.WAITING_3D_APPROVAL:
            self._register_model_from_event(event)
        elif event.stage == Stage.COMPLETE:
            self.events.publish("JOB_COMPLETE", {"jobId": event.task_id})
            task = self.store.load_task(event.task_id) or {}
            text = str(task.get("final_text") or event.message)
            self.events.publish(
                "CHAT_MESSAGE",
                {"jobId": event.task_id, "message": self._event_chat_message(event.task_id, text, "zenless")},
            )
        elif event.stage in {Stage.BLOCKED, Stage.FAILED}:
            self._fail_generating_artifacts(event.task_id)
            if event.stage == Stage.FAILED:
                self.events.publish("JOB_FAILED", {"jobId": event.task_id, "reason": event.message})
            self.events.publish(
                "CHAT_MESSAGE",
                {
                    "jobId": event.task_id,
                    "message": self._event_chat_message(event.task_id, event.message, "system"),
                },
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

    def _record_activity(self, event: PipelineEvent, job: dict[str, Any]) -> None:
        phase_map: dict[Stage, str] = {
            Stage.NEW: "CONTEXT",
            Stage.COLLECTING_CONTEXT: "CONTEXT",
            Stage.PLANNING: "PLAN",
            Stage.GENERATING_CONCEPT: "CONCEPT",
            Stage.WAITING_IMAGE_APPROVAL: "CONCEPT",
            Stage.GENERATING_3D: "THREED",
            Stage.WAITING_3D_APPROVAL: "THREED",
            Stage.BUILDING: "BUILD",
            Stage.REVIEWING: "REVIEW",
            Stage.REVISING: "REVIEW",
            Stage.WAITING_CHANGE_APPROVAL: "REVIEW",
            Stage.APPLYING: "APPLY",
            Stage.TESTING: "TEST",
            Stage.FIXING: "BUILD",
            Stage.FINAL_REVIEW: "FINAL",
            Stage.COMPLETE: "FINAL",
            Stage.FAILED: "FINAL",
            Stage.BLOCKED: "FINAL",
            Stage.PAUSED: "REVIEW",
        }
        research_status = {
            "research_running": "RUNNING",
            "research_done": "DONE",
            "research_warning": "WARNING",
        }
        phase = "RESEARCH" if event.kind in research_status else phase_map.get(event.stage, "PLAN")
        terminal_waits = {
            Stage.WAITING_CHANGE_APPROVAL,
            Stage.WAITING_IMAGE_APPROVAL,
            Stage.WAITING_3D_APPROVAL,
            Stage.COMPLETE,
        }
        status = research_status.get(
            event.kind,
            "FAILED"
            if event.stage in {Stage.FAILED, Stage.BLOCKED}
            else ("DONE" if event.stage in terminal_waits else "RUNNING"),
        )
        if not hasattr(self, "_active_activities"):
            self._active_activities = {}
        previous = self._active_activities.get(event.task_id)
        if previous is None:
            previous = next(
                (
                    item
                    for item in reversed(self.store.list_activities(event.task_id))
                    if item["status"] == "RUNNING"
                ),
                None,
            )
        if previous and (previous["phase"] != phase or previous["status"] != "RUNNING"):
            if previous["status"] == "RUNNING":
                closed = self.store.upsert_activity(
                    str(previous["id"]),
                    event.task_id,
                    str(previous["phase"]),
                    "DONE" if status != "FAILED" else "FAILED",
                    str(previous["title"]),
                    str(previous.get("detail") or ""),
                    str(previous.get("providerId") or ""),
                    str(previous.get("role") or ""),
                    int(previous.get("cycle") or 1),
                    int(previous.get("attempt") or 1),
                )
                self.events.publish("CHAT_ACTIVITY", {"jobId": event.task_id, "activity": closed})
            previous = None
        if previous is None:
            cycle = self._next_activity_cycle(event.task_id, phase)
            activity_id = f"activity-{event.task_id}-{phase.casefold()}-{cycle}"
        else:
            cycle = int(previous.get("cycle") or 1)
            activity_id = str(previous["id"])
        provider_id, role = self._activity_owner(event.stage, job)
        if phase == "RESEARCH":
            provider_id = self._resolved_role_providers()["RESEARCH"]
            role = "RESEARCH"
        activity = self.store.upsert_activity(
            activity_id,
            event.task_id,
            phase,
            status,
            event.message or f"Executing {phase.casefold()}",
            event.detail[:4_000],
            provider_id,
            role,
            cycle,
            cycle,
        )
        self.events.publish("CHAT_ACTIVITY", {"jobId": event.task_id, "activity": activity})
        if status == "RUNNING":
            self._active_activities[event.task_id] = activity
        else:
            self._active_activities.pop(event.task_id, None)

    def _next_activity_cycle(self, job_id: str, phase: str) -> int:
        cycles = [
            int(item.get("cycle") or 1)
            for item in self.store.list_activities(job_id)
            if item.get("phase") == phase
        ]
        return max(cycles, default=0) + 1

    def _next_artifact_version(self, job_id: str, artifact_type: str) -> int:
        versions = [
            int(item.get("version") or 1)
            for item in self.store.list_artifacts(job_id)
            if item.get("type") == artifact_type
        ]
        return max(versions, default=0) + 1

    def _activity_owner(self, stage: Stage, job: dict[str, Any]) -> tuple[str, str]:
        providers = self._resolved_role_providers()
        if stage in {Stage.REVIEWING, Stage.FINAL_REVIEW} and bool((job.get("options") or {}).get("review", True)):
            return providers["REVIEWER"], "REVIEWER"
        if stage in {Stage.APPLYING, Stage.COLLECTING_CONTEXT}:
            return "studio", "STUDIO"
        if stage in {Stage.TESTING, Stage.FIXING}:
            return "", "QA_ANALYST"
        if stage in {Stage.GENERATING_3D, Stage.WAITING_3D_APPROVAL}:
            return providers["3D"], "THREED"
        if stage in {Stage.GENERATING_CONCEPT, Stage.WAITING_IMAGE_APPROVAL}:
            return providers["VISUAL"], "VISUAL"
        return providers["BUILDER"], "BUILDER"

    def _publish_visual_artifact(self, job_id: str, *, state: str = "READY") -> None:
        visual = self.visual(job_id)
        version = max(1, int(visual["concept"].get("version") or 1))
        artifact = {
            "id": f"artifact-visual-{job_id}-v{version}",
            "jobId": job_id,
            "messageId": None,
            "type": "IMAGE",
            "name": "Six-view concept",
            "mime": "image/png",
            "size": 0,
            "state": state,
            "previewUrl": next((item.get("imageUrl") for item in visual["views"] if item.get("imageUrl")), None),
            "contentUrl": None,
            "modelUrl": None,
            "metadata": {"views": visual["views"], "concept": visual["concept"]},
            "version": version,
            "revision": version,
            "actions": ["APPROVE", "REJECT", "REGENERATE", "EDIT", "OPEN_FULL_VIEW"],
        }
        self._publish_artifact(artifact)

    def _publish_visual_state(self, job_id: str, *, fallback: str = "EMPTY") -> None:
        visual = self.visual(job_id)
        concept_version = max(0, int(visual["concept"].get("version") or 0))
        for view in visual["views"]:
            state = str(view.get("state") or "EMPTY")
            if state == "EMPTY" and fallback != "EMPTY":
                state = fallback
            self.events.publish(
                "VISUAL_GENERATION_CHANGED",
                {
                    "jobId": job_id,
                    "view": view["name"],
                    "state": state,
                    "assetId": view.get("assetId"),
                    "conceptVersion": concept_version,
                },
            )
            if state in {"READY", "APPROVED"} and view.get("imageUrl") and view.get("assetId"):
                self.events.publish(
                    "VISUAL_READY",
                    {
                        "jobId": job_id,
                        "view": view["name"],
                        "imageUrl": view["imageUrl"],
                        "assetId": view["assetId"],
                        "conceptVersion": concept_version,
                    },
                )

    def _publish_visual_generation(self, job_id: str, version: int) -> None:
        for view in ("FRONT", "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM"):
            self.events.publish(
                "VISUAL_GENERATION_CHANGED",
                {
                    "jobId": job_id,
                    "view": view,
                    "state": "GENERATING",
                    "assetId": None,
                    "conceptVersion": version,
                },
            )
        self._publish_artifact(
            {
                "id": f"artifact-visual-{job_id}-v{version}",
                "jobId": job_id,
                "type": "IMAGE",
                "name": "Six-view concept",
                "state": "GENERATING",
                "metadata": {"views": [], "concept": {"version": version, "status": "GENERATING"}},
                "version": version,
                "revision": version,
            }
        )

    def _publish_visual_ready(self, event: PipelineEvent) -> None:
        try:
            payload = json.loads(event.detail)
        except (TypeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        view = str(payload.get("view") or "").upper()
        asset_id = str(payload.get("assetId") or "")
        version = self._safe_positive_int(payload.get("conceptVersion"), 1)
        if view not in {"FRONT", "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM"} or not asset_id:
            return
        asset = self.store.asset(asset_id)
        if asset is None or str(asset.get("job_id") or "") != event.task_id or str(asset.get("kind") or "") != "VIEW":
            return
        path = Path(str(asset.get("path") or "")).resolve()
        if not self._is_within(path, self.data_root) or not path.is_file():
            return
        image_url = f"/api/assets/{asset_id}/content"
        self.events.publish(
            "VISUAL_GENERATION_CHANGED",
            {
                "jobId": event.task_id,
                "view": view,
                "state": "READY",
                "assetId": asset_id,
                "conceptVersion": version,
            },
        )
        self.events.publish(
            "VISUAL_READY",
            {
                "jobId": event.task_id,
                "view": view,
                "imageUrl": image_url,
                "assetId": asset_id,
                "conceptVersion": version,
            },
        )

    def _publish_model_generation(self, job_id: str, version: int) -> None:
        self.events.publish(
            "MODEL_GENERATION_CHANGED",
            {"jobId": job_id, "target": "geometry", "state": "GENERATING"},
        )
        self._publish_artifact(
            {
                "id": f"artifact-model-{job_id}-v{version}",
                "jobId": job_id,
                "type": "MODEL_3D",
                "name": f"3D model V{version}",
                "state": "GENERATING",
                "version": version,
                "revision": version,
            }
        )

    def _fail_generating_artifacts(self, job_id: str) -> None:
        latest: dict[str, dict[str, Any]] = {}
        for artifact in self.store.list_artifacts(job_id):
            latest[str(artifact["type"])] = artifact
        for artifact in latest.values():
            if artifact["state"] == "GENERATING":
                self._publish_artifact({**artifact, "state": "FAILED"})
                if artifact["type"] == "IMAGE":
                    task = self._require_task(job_id)
                    context = task.get("context") or {}
                    visual = context.get("visual") or {}
                    self.store.update_context_section(job_id, "visual", {**visual, "status": "FAILED"})
                    for view in ("FRONT", "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM"):
                        self.events.publish(
                            "VISUAL_GENERATION_CHANGED",
                            {
                                "jobId": job_id,
                                "view": view,
                                "state": "FAILED",
                                "conceptVersion": artifact["version"],
                            },
                        )
                elif artifact["type"] == "MODEL_3D":
                    for target in ("geometry", "texture"):
                        self.events.publish(
                            "MODEL_GENERATION_CHANGED",
                            {"jobId": job_id, "target": target, "state": "FAILED"},
                        )

    @staticmethod
    def _safe_positive_int(value: Any, fallback: int) -> int:
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return max(1, fallback)

    def _event_version(self, event: PipelineEvent, fallback: int) -> int:
        try:
            payload = json.loads(event.detail)
        except (TypeError, json.JSONDecodeError):
            return max(1, fallback)
        return self._safe_positive_int(payload.get("version") if isinstance(payload, dict) else None, fallback)

    def _publish_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        job_id = str(artifact.get("jobId") or "")
        if not job_id:
            raise ValueError("Artifact jobId is required.")
        metadata = dict(artifact.get("metadata") or {})
        for key in ("messageId", "mime", "size", "actions"):
            if key in artifact and artifact[key] is not None:
                metadata[key] = artifact[key]
        version = max(1, int(artifact.get("version") or metadata.get("version") or 1))
        revision = max(1, int(artifact.get("revision") or metadata.get("revision") or version))
        persisted = self.store.upsert_artifact(
            artifact_id=str(artifact["id"]),
            job_id=job_id,
            artifact_type=str(artifact["type"]),
            name=str(artifact["name"]),
            state=str(artifact["state"]),
            preview_url=str(artifact.get("previewUrl") or ""),
            content_url=str(artifact.get("contentUrl") or ""),
            model_url=str(artifact.get("modelUrl") or ""),
            metadata=metadata,
            version=version,
            revision=revision,
            created_at=int(artifact.get("createdAt") or int(time.time() * 1000)),
        )
        persisted.update(
            {
                key: artifact[key]
                for key in ("messageId", "mime", "size", "actions")
                if key in artifact and artifact[key] is not None
            }
        )
        self.events.publish("CHAT_ARTIFACT", {"jobId": job_id, "artifact": persisted})
        return persisted

    def _transition_latest_artifact(self, job_id: str, artifact_type: str, state: str) -> dict[str, Any] | None:
        artifacts = [item for item in self.store.list_artifacts(job_id) if item["type"] == artifact_type]
        if not artifacts:
            return None
        return self._publish_artifact({**artifacts[-1], "state": state})

    def _register_model_from_event(self, event: PipelineEvent) -> None:
        try:
            payload = json.loads(event.detail)
        except (TypeError, json.JSONDecodeError):
            payload = {}
        path_text = str(payload.get("path") or "") if isinstance(payload, dict) else ""
        if not path_text:
            return
        path = Path(path_text).resolve()
        if not self._is_within(path, self.data_root) or not path.is_file():
            self._report(
                "asset",
                "3d-provider",
                RuntimeError("The 3D generator returned a path outside local storage."),
                "Use the authorized internal download flow.",
            )
            return
        asset = self._register_file_asset(path, job_id=event.task_id, kind="GLB", publish_artifact=False)
        try:
            version = int(payload.get("version") or 0)
        except (TypeError, ValueError):
            version = 0
        version = max(1, version or self._next_artifact_version(event.task_id, "MODEL_3D"))
        self.events.publish("ASSETS_UPDATED", {"assets": self.assets()})
        self.events.publish(
            "MODEL_READY",
            {
                "jobId": event.task_id,
                "assetId": asset,
                "version": version,
                "modelUrl": f"/api/assets/{asset}/content",
                "filename": path.name,
                "geometryStatus": "READY",
                "textureStatus": "READY",
            },
        )
        record = self.store.asset(asset) or {}
        self._publish_artifact(
            {
                "id": f"artifact-model-{event.task_id}-v{version}",
                "jobId": event.task_id,
                "messageId": None,
                "type": "MODEL_3D",
                "name": path.name,
                "mime": str(record.get("mime") or "model/gltf-binary"),
                "size": int(record.get("size") or 0),
                "state": "READY",
                "previewUrl": None,
                "contentUrl": f"/api/assets/{asset}/content",
                "modelUrl": f"/api/assets/{asset}/content",
                "metadata": {
                    "assetId": asset,
                    "geometryStatus": "READY",
                    "textureStatus": "READY",
                    "version": version,
                },
                "version": version,
                "revision": version,
                "actions": ["APPROVE", "REJECT", "REGENERATE_GEOMETRY", "REGENERATE_TEXTURE", "OPEN_FULL_VIEW"],
                "createdAt": int(time.time() * 1000),
            }
        )

    def _on_diagnostic(self, event: DiagnosticEvent) -> None:
        payload = self._diagnostic_payload(event)
        self.events.publish("DIAGNOSTIC_EVENT", {"diagnostic": payload})
        if payload["severity"] in {"critical", "error", "warning"}:
            self.events.publish(
                "CHAT_SYSTEM_EVENT",
                {
                    "severity": payload["severity"].upper(),
                    "title": payload["component"] or payload["source"],
                    "message": payload["message"],
                    "recovery": payload["recovery"],
                    "jobId": payload["jobId"],
                    "diagnosticId": payload["id"],
                },
            )

    def _on_mcp_notification(self, message: dict[str, Any]) -> None:
        method = str(message.get("method", "notification"))
        if "studio" in method.casefold():
            self.events.publish("STUDIO_STATE_CHANGED", self.studio_state())

    def _set_connection(self, name: str, state: str) -> None:
        with self._connections_lock:
            if self._connections.get(name) == state:
                return
            self._connections[name] = state
            if hasattr(self, "_readiness_cache"):
                self._readiness_cache = None
        self.events.publish("CONNECTION_CHANGED", {name: state})

    def _set_boot(self, stage: str, state: str) -> None:
        with self._boot_lock:
            for item in self._boot_steps:
                if item["stage"] == stage:
                    item["state"] = state
                    break
        self.events.publish("BOOT_STAGE_CHANGED", {"stage": stage, "state": state})

    def _report(self, source: str, component: str, exc: BaseException, recovery: str) -> None:
        self.diagnostics.report(
            severity="ERROR",
            source=source,
            component=component,
            message=str(exc),
            exc=exc,
            recovery_action=recovery,
        )

    def _prepare_attachments(self, paths: tuple[Path, ...], provider: str) -> tuple[Path, ...]:
        try:
            response = self.bridge.request(provider, "capabilities", {}, task_id="attachment-routing", timeout=15)
        except BridgeError as exc:
            raise CoreError(
                "PROVIDER_CAPABILITY_UNAVAILABLE",
                "The provider attachment limits could not be verified.",
                status=409,
                details={"provider": provider},
            ) from exc
        raw = response.get("capabilities")
        capabilities = normalize_capabilities(dict(raw) if isinstance(raw, dict) else {})
        if not bool(capabilities.get("supportsFiles")):
            raise CoreError(
                "PROVIDER_FILE_CAPABILITY_UNAVAILABLE",
                "The selected provider mode does not expose file upload.",
                status=409,
                details={"provider": provider},
            )
        capability = ProviderFileCapability(
            max_count=max(1, int(capabilities.get("maxFiles") or 1)),
            max_file_size=max(1, int(capabilities.get("maxBytesPerFile") or 32 * 1024 * 1024)),
            accepted_mime=tuple(str(item) for item in capabilities.get("acceptedMimeTypes", [])),
            accepted_extensions=tuple(str(item) for item in capabilities.get("acceptedExtensions", [])),
            accepts_archives=bool(capabilities.get("supportsArchives")),
        )
        try:
            route = self.attachments.route(
                list(paths),
                capability,
                extraction_root=self.data_root / "tmp" / "extracted",
            )
        except AttachmentError as exc:
            raise CoreError(exc.code, str(exc), status=400) from exc
        if route.rejected:
            raise CoreError(
                "ATTACHMENT_REJECTED",
                "One or more attachments are incompatible with the selected provider mode.",
                status=409,
                details={
                    "provider": provider,
                    "rejected": [
                        {"name": item.name, "code": item.code, "message": item.message} for item in route.rejected
                    ],
                },
            )
        return tuple(item.path for batch in route.batches for item in batch)

    def _boot_state(self, stage: str) -> str:
        with self._boot_lock:
            match = next((item for item in self._boot_steps if item["stage"] == stage), None)
        return str((match or {}).get("state") or "OFF")

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
            "title": (prompt.splitlines()[0] or "Zenless task")[:100],
            "status": status_map.get(raw_status, "NEW"),
            "stage": str(task.get("stage", Stage.NEW.value)),
            "createdAt": _milliseconds(task["created_at"]),
            "updatedAt": _milliseconds(task["updated_at"]),
            "options": {
                "visualFirst": bool(options.get("visual_first", False)),
                "create3D": bool(options.get("create_3d_asset", False)),
                "visualMode": str(options.get("visual_mode", "AUTO")).upper(),
                "create3DMode": str(options.get("create_3d_mode", "AUTO")).upper(),
                "research": str(options.get("research", "AUTO")).upper(),
                "effort": str(options.get("effort", "AUTO")).upper(),
                "chatMode": str(options.get("chat_mode", options.get("chatMode", "PROJECT"))).upper(),
                "deadlineMinutes": int(options.get("deadline_minutes", 60)),
                "review": bool(options.get("independent_review", True)),
                "autoTest": bool(options.get("automatic_play_test", True)),
                "autoFix": bool(options.get("auto_fix_errors", True)),
                "approval": bool(options.get("require_approval", True)),
                "risk": str(options.get("risk_level", "medium")),
                "revisions": int(options.get("max_revisions", 3)),
                "fixAttempts": int(options.get("max_test_fixes", 3)),
            },
            "fixAttempts": 0,
            "maxFixAttempts": int(options.get("max_test_fixes", 3)),
        }

    @staticmethod
    def _derive_context_items(job_id: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        raw_reads = context.get("reads")
        reads: dict[str, Any] = raw_reads if isinstance(raw_reads, dict) else {}
        items: list[dict[str, Any]] = []
        for index, (name, content) in enumerate(reads.items()):
            path = str(name).split(":", 1)[0]
            item_id = hashlib.sha256(f"{job_id}:{path}:{index}".encode()).hexdigest()[:24]
            items.append(
                {
                    "id": item_id,
                    "job_id": job_id,
                    "name": path,
                    "type": "Service",
                    "path": path,
                    "relevance": max(0.1, 1.0 - index * 0.08),
                    "state": "included",
                    "raw": {"summary": str(content)[:4000]},
                }
            )
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
    def _parse_studio_tree(text: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = []
        raw_items = (
            payload
            if isinstance(payload, list)
            else payload.get("results", payload.get("instances", []))
            if isinstance(payload, dict)
            else []
        )
        nodes: dict[str, dict[str, Any]] = {}
        roots: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_items if isinstance(raw_items, list) else []):
            if not isinstance(raw, dict):
                continue
            path = str(raw.get("fullPath") or raw.get("path") or raw.get("name") or f"Instance{index}")
            name = str(raw.get("name") or path.rsplit(".", 1)[-1])
            class_name = str(raw.get("className") or raw.get("class") or "Instance")
            node_id = hashlib.sha256(path.encode("utf-8", "replace")).hexdigest()[:24]
            node = {"id": node_id, "name": name, "className": class_name, "path": path, "children": []}
            nodes[node_id] = node
            roots.append(node)
        return roots[:500], nodes

    def _register_file_asset(
        self,
        path: Path,
        *,
        job_id: str,
        kind: str,
        publish_artifact: bool = True,
    ) -> str:
        resolved = path.resolve()
        if not self._is_within(resolved, self.data_root) or not resolved.is_file():
            raise CoreError("INVALID_ASSET_PATH", "The asset does not belong to local storage.")
        hasher = hashlib.sha256()
        with resolved.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        asset_id = digest[:32]
        mime = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        normalized_kind = kind if kind in {"IMG", "VIEW", "GLB", "GLTF", "TEX", "RBX"} else "RBX"
        self.store.register_asset(
            asset_id,
            job_id=job_id,
            name=resolved.name,
            kind=normalized_kind,
            path=resolved,
            mime=mime,
        )
        artifact_type = (
            "MODEL_3D"
            if normalized_kind in {"GLB", "GLTF"}
            else ("IMAGE" if normalized_kind in {"IMG", "VIEW", "TEX"} else "FILE")
        )
        content_url = f"/api/assets/{asset_id}/content"
        if publish_artifact:
            self._publish_artifact(
                {
                    "id": f"artifact-file-{asset_id}",
                    "jobId": job_id,
                    "messageId": None,
                    "type": artifact_type,
                    "name": resolved.name,
                    "mime": mime,
                    "size": resolved.stat().st_size,
                    "state": "READY",
                    "previewUrl": content_url if artifact_type == "IMAGE" else None,
                    "contentUrl": content_url,
                    "modelUrl": content_url if artifact_type == "MODEL_3D" else None,
                    "metadata": {"assetKind": normalized_kind},
                    "actions": ["OPEN", "DOWNLOAD"],
                    "createdAt": int(time.time() * 1000),
                }
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
        if value in {
            "login required",
            "login needed",
            "requires attention",
            "challenge",
            "expired",
            "login window open",
            "authenticating",
        }:
            return "LOGIN"
        if value in {
            "starting",
            "connecting",
            "installing",
            "standby",
            "degraded",
            "authenticated",
            "verifying persistence",
        }:
            return "CONNECTING"
        if value in {"error", "failed", "unavailable", "runtime required"}:
            return "ERR"
        return "OFF"

    @staticmethod
    def _provider_auth_state(state: str) -> AuthState:
        value = state.strip().replace("_", " ").casefold()
        mapping = {
            "unknown": AuthState.UNKNOWN,
            "checking": AuthState.CHECKING,
            "standby": AuthState.LOGIN_REQUIRED,
            "off": AuthState.LOGIN_REQUIRED,
            "login": AuthState.LOGIN_REQUIRED,
            "login required": AuthState.LOGIN_REQUIRED,
            "login window open": AuthState.LOGIN_WINDOW_OPEN,
            "authenticating": AuthState.AUTHENTICATING,
            "challenge": AuthState.CHALLENGE,
            "authenticated": AuthState.AUTHENTICATED,
            "verifying persistence": AuthState.VERIFYING_PERSISTENCE,
            "ready": AuthState.READY,
            "connected": AuthState.READY,
            "idle": AuthState.READY,
            "working": AuthState.READY,
            "expired": AuthState.EXPIRED,
            "error": AuthState.ERROR,
            "err": AuthState.ERROR,
            "failed": AuthState.ERROR,
            "unavailable": AuthState.ERROR,
        }
        return mapping.get(value, AuthState.UNKNOWN)

    @staticmethod
    def _merge_models(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        result = json.loads(json.dumps(current))
        for provider in ("chatgpt", "deepseek", "hunyuan"):
            value = patch.get(provider)
            if isinstance(value, dict):
                result[provider].update(value)
        if "smartRouting" in patch:
            result["smartRouting"] = bool(patch["smartRouting"])
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
