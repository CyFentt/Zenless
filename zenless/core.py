from __future__ import annotations

import hashlib
import json
import mimetypes
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .agent_gateway import AgentGateway
from .browser_bridge import BridgeError
from .diagnostics import DiagnosticEvent, ErrorBus
from .event_bus import EventBus
from .managed_browser import ManagedBrowserController
from .models import PipelineEvent, Stage, TaskOptions
from .orchestrator import OrchestratorError, ZenlessOrchestrator
from .policy import is_read_only
from .qa_breaker import QABreaker
from .storage import StorageManager
from .store import SQLiteStore
from .studio_mcp import MCPError, MCPToolResult, StudioMCPClient, find_studio_mcp
from .webview2_browser import WebView2BrowserController

PROVIDER_LABELS = {
    "chatgpt": "Builder",
    "deepseek": "Reviewer",
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
        self.storage = StorageManager(self.data_root)
        self._closing = threading.Event()
        self._startup_thread: threading.Thread | None = None
        self._provider_threads: dict[str, threading.Thread] = {}
        self._provider_lock = threading.Lock()
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
        self.store.maintenance()
        self._diagnostic_unsubscribe()
        if self._owns_diagnostics:
            self.diagnostics.close()

    def set_runtime_port(self, port: int) -> None:
        settings = self.settings()
        settings["bridgePort"] = int(port)
        self.store.set_setting("ui.settings", settings)

    def bootstrap(self) -> dict[str, Any]:
        with self._boot_lock:
            return {"steps": [dict(item) for item in self._boot_steps]}

    def status(self) -> dict[str, Any]:
        return {"ready": not self._closing.is_set()}

    def connections(self) -> dict[str, str]:
        with self._connections_lock:
            return dict(self._connections)

    def agents(self) -> list[dict[str, Any]]:
        connections = self.connections()
        models = self.settings()["models"]
        return [
            {
                "id": "chatgpt",
                "name": PROVIDER_LABELS["chatgpt"],
                "status": connections["chatgpt"],
                "model": models["chatgpt"]["model"],
                "reasoning": bool(models["chatgpt"]["reasoning"]),
            },
            {
                "id": "deepseek",
                "name": PROVIDER_LABELS["deepseek"],
                "status": connections["deepseek"],
                "model": models["deepseek"]["model"],
                "reasoning": bool(models["deepseek"]["reasoning"]),
            },
            {
                "id": "hunyuan",
                "name": PROVIDER_LABELS["hunyuan"],
                "status": connections["hunyuan"],
                "version": models["hunyuan"]["version"],
                "quality": models["hunyuan"]["quality"],
            },
            {"id": "studio", "name": "Studio", "status": connections["studio"]},
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
        options: dict[str, Any] | None = None,
        *,
        attachments: tuple[Path, ...] = (),
    ) -> dict[str, Any]:
        try:
            task_id = self.orchestrator.submit(
                title,
                TaskOptions.from_api(options),
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
        if str(task.get("stage")) != Stage.PAUSED.value or "Checkpoint recuperado" not in str(task.get("error")):
            raise CoreError("JOB_NOT_RESUMABLE", "The job is not paused.", status=409)
        try:
            options = TaskOptions(**dict(task.get("options") or {}))
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
        task_options = TaskOptions.from_api(options)
        self._preflight_providers(task_options)
        job = self.create_job(objective, options=options, attachments=attachments)
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

    def _preflight_providers(self, options: TaskOptions) -> None:
        required = ["chatgpt"]
        if options.independent_review:
            required.append("deepseek")
        if options.create_3d_asset:
            required.append("hunyuan")
        for provider in required:
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

    def timeline(self, job_id: str) -> dict[str, Any]:
        self._require_task(job_id)
        messages = self.messages(job_id)
        activities = self.store.list_activities(job_id)
        artifacts = self.store.list_artifacts(job_id)
        latest_run = self.store.latest_test_run(job_id)
        test_data = {"testState": self.test_state(job_id), "cases": [], "failures": []}
        if latest_run:
            run_id = str(latest_run["id"])
            test_data["cases"] = self.store.test_cases(run_id) if hasattr(self.store, "test_cases") else []
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
            self.events.publish("CONTEXT_UPDATED", {"items": self.context(str(item["job_id"]))})
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

    def edit_changes(self, job_id: str, _file_id: str, content: str) -> bool:
        if not content.strip():
            raise CoreError("EMPTY_EDIT", "The edit note is empty.")
        if not self.orchestrator.approve_active(job_id, ("changes:", "repair:"), "edit", content):
            raise CoreError("NO_CHANGE_GATE", "No change is waiting for an edit.", status=409)
        return True

    def visual(self, job_id: str) -> dict[str, Any]:
        task = self._require_task(job_id)
        context = task.get("context") or {}
        raw_visual = context.get("visual") if isinstance(context, dict) else None
        visual: dict[str, Any] = raw_visual if isinstance(raw_visual, dict) else {}
        views = []
        for name in ("FRONT", "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM"):
            entry = visual.get(name.casefold(), {}) if isinstance(visual, dict) else {}
            asset_id = str(entry.get("asset_id", "")) if isinstance(entry, dict) else ""
            views.append(
                {
                    "name": name,
                    "state": "READY" if asset_id else "EMPTY",
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
        self.events.publish("VISUAL_APPROVED", {
            "jobId": job_id,
            "views": ["FRONT", "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM"]
        })
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
        self.events.publish("MODEL_APPROVED", {})
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

    def studio_state(self) -> dict[str, str]:
        return {
            "state": "ONLINE"
            if self.connections()["studio"] == "READY"
            else ("CONNECTING" if self.connections()["studio"] == "CONNECTING" else "OFFLINE")
        }

    def studio_tree(self) -> list[dict[str, Any]]:
        with self._studio_lock:
            return json.loads(json.dumps(self._studio_tree))

    def refresh_studio(self) -> bool:
        try:
            if not self.studio.running:
                self.studio.start()
            studios = self.studio.list_studios()
            if not studios:
                raise MCPError("No Studio instance is connected.")
            target = studios[0]
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
            self.events.publish("STUDIO_STATE_CHANGED", {"state": "ONLINE"})
            self.events.publish("STUDIO_TREE_UPDATED", {"tree": tree})
            return True
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
                self.events.publish("JOB_UPDATED", {"job": self.job(str(item["id"]))})
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
        try:
            self.bridge.login(provider, timeout=600)
            self._set_connection(provider, "READY")
            self.events.publish("AGENT_STATUS_CHANGED", {"agent": provider, "status": "READY"})
            self._set_boot("AI", "READY")
        except Exception as exc:
            self._set_connection(provider, "ERR")
            self.events.publish("AGENT_STATUS_CHANGED", {"agent": provider, "status": "ERR"})
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
                {"messageId": event.message, "jobId": event.task_id, "provider": event.detail},
            )
            return
        if event.kind == "stream_delta":
            self.events.publish(
                "CHAT_STREAM_DELTA",
                {"messageId": event.message, "delta": event.detail},
            )
            return
        if event.kind == "stream_finish":
            self.events.publish("CHAT_STREAM_FINISHED", {"messageId": event.message})
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

        # Emit ChatActivity
        phase_map: dict[Stage, str] = {
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
        }
        phase = phase_map.get(event.stage, "PLAN")
        act_status = "DONE" if event.stage in {Stage.COMPLETE, Stage.WAITING_CHANGE_APPROVAL, Stage.WAITING_IMAGE_APPROVAL, Stage.WAITING_3D_APPROVAL} else ("FAILED" if event.stage in {Stage.FAILED, Stage.BLOCKED} else "RUNNING")
        activity_id = f"act_{event.task_id[:10]}_{phase.lower()}"
        activity = self.store.upsert_activity(
            activity_id=activity_id,
            job_id=event.task_id,
            phase=phase,
            status=act_status,
            title=event.message or f"Executing {phase}",
            detail=event.detail,
        )
        self.events.publish("CHAT_ACTIVITY", {"activity": activity})

        if event.stage == Stage.WAITING_CHANGE_APPROVAL:
            self.events.publish("CHANGES_UPDATED", {"files": self.changes(event.task_id)})
            rev = self.review(event.task_id)
            self.events.publish("REVIEW_READY", {"review": rev})
            diff_art = self.store.upsert_artifact(
                artifact_id=f"art_diff_{event.task_id[:10]}",
                job_id=event.task_id,
                artifact_type="DIFF",
                name="CODE CHANGES READY",
                state="READY",
                metadata={"risk": rev.get("risk"), "reviewer": rev.get("reviewer"), "decision": rev.get("decision"), "fileCount": len(rev.get("files", []))},
            )
            self.events.publish("CHAT_ARTIFACT", {"artifact": diff_art})
        elif event.stage == Stage.WAITING_IMAGE_APPROVAL:
            self.events.publish("VISUAL_GENERATION_CHANGED", {"state": "READY"})
            img_art = self.store.upsert_artifact(
                artifact_id=f"art_img_{event.task_id[:10]}",
                job_id=event.task_id,
                artifact_type="IMAGE",
                name="CONCEPT VISUAL READY",
                state="READY",
            )
            self.events.publish("CHAT_ARTIFACT", {"artifact": img_art})
        elif event.stage == Stage.GENERATING_3D:
            self.events.publish("MODEL_GENERATION_CHANGED", {"target": "geometry", "state": "GENERATING"})
        elif event.stage == Stage.WAITING_3D_APPROVAL:
            self._register_model_from_event(event)
            model_art = self.store.upsert_artifact(
                artifact_id=f"art_model_{event.task_id[:10]}",
                job_id=event.task_id,
                artifact_type="MODEL_3D",
                name="3D MODEL READY",
                state="READY",
            )
            self.events.publish("CHAT_ARTIFACT", {"artifact": model_art})
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
        except (TypeError, json.JSONDecodeError):
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
            {"modelUrl": f"/api/assets/{asset}/content", "filename": path.name},
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

    def _report(self, source: str, component: str, exc: BaseException, recovery: str) -> None:
        self.diagnostics.report(
            severity="ERROR",
            source=source,
            component=component,
            message=str(exc),
            exc=exc,
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
            "title": (prompt.splitlines()[0] or "Zenless task")[:100],
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

    def _register_file_asset(self, path: Path, *, job_id: str, kind: str) -> str:
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
