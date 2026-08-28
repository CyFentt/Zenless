from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
from tkinter import messagebox, simpledialog
from typing import Any, Callable

from .agent_gateway import AgentGateway
from .browser_bridge import BridgeError, BrowserBridge
from .diagnostics import DiagnosticEvent, ErrorBus
from .discord_integration import DiscordIntegration
from .managed_browser import ManagedBrowserController
from .models import PipelineEvent, Stage, TaskOptions
from .orchestrator import ZenlessOrchestrator
from .storage import StorageManager
from .store import SQLiteStore
from .studio_mcp import MCPError, StudioMCPClient, find_studio_mcp
from .webview2_browser import WebView2BrowserController


def user_data_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Zenless"


class ZenlessController:
    def __init__(
        self,
        root,
        *,
        data_root: Path | None = None,
        diagnostics: ErrorBus | None = None,
    ) -> None:
        self.root = root
        self.data_root = data_root or user_data_root()
        self.data_root.mkdir(parents=True, exist_ok=True)
        self._owns_diagnostics = diagnostics is None
        self.diagnostics = diagnostics or ErrorBus(self.data_root / "logs")
        self.diagnostics.install_global_hooks(root)
        self.storage = StorageManager(self.data_root)
        self.store = SQLiteStore(self.data_root / "zenless.db")
        token = self.store.get_setting("bridge_token", "")
        if not isinstance(token, str) or len(token) < 32:
            token = BrowserBridge.new_token()
            self.store.set_setting("bridge_token", token)
        self.bridge_token = token
        self.extension_bridge = BrowserBridge(
            token=token,
            runtime_file=self.data_root / "runtime.json",
            status_callback=self._on_bridge_status,
        )
        self.managed_browser = ManagedBrowserController(
            data_root=self.data_root,
            status_callback=self._on_bridge_status,
            diagnostics=self.diagnostics,
        )
        self.embedded_browser = WebView2BrowserController(
            data_root=self.data_root,
            status_callback=self._on_bridge_status,
            diagnostics=self.diagnostics,
        )
        self.bridge = AgentGateway(
            managed=self.managed_browser,
            embedded=self.embedded_browser,
            extension=self.extension_bridge,
            status_callback=self._on_bridge_status,
        )
        self.studio = StudioMCPClient(find_studio_mcp(), notification_callback=self._on_mcp_notification)
        self.orchestrator = ZenlessOrchestrator(
            store=self.store,
            bridge=self.bridge,
            studio=self.studio,
            run_root=self.data_root / "runs",
            event_callback=self._on_pipeline_event,
        )
        self.app = None
        webhook_url = self.store.get_setting("discord.webhook_url", "")
        self.discord = DiscordIntegration(
            webhook_url if isinstance(webhook_url, str) else "",
            error_callback=self._on_discord_error,
        )
        self._closing = False
        self._service_thread: threading.Thread | None = None
        self._manual_test_cancel = threading.Event()
        self._manual_test_thread: threading.Thread | None = None
        self._manual_test_lock = threading.Lock()
        self._rescan_thread: threading.Thread | None = None
        self._rescan_lock = threading.Lock()
        self._studio_connect_lock = threading.Lock()
        self._context_enabled: set[str] = set()
        self._ui_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._colors: dict[str, str] = {}
        self._provider_threads: set[threading.Thread] = set()
        self._diagnostic_unsubscribe: Callable[[], None] | None = None

    def attach(self, app) -> None:
        self.app = app
        app.backend = self
        module = sys.modules.get(app.__class__.__module__)
        palette = getattr(module, "C", {})
        if isinstance(palette, dict):
            self._colors = {str(key): str(value) for key, value in palette.items()}
        app.data.connections["Managed Browser"] = {
            "url": "Playwright • persistent local profile",
            "status": "Starting",
        }
        app.data.connections["Extension Fallback"] = {
            "url": "Native Messaging / localhost standby",
            "status": "Standby",
        }
        app.data.connections["StudioMCP"] = {"url": "stdio → Studio", "status": "Starting"}
        app.data.connections["Web Context Engine"] = {"url": "SQLite + live MCP", "status": "Connected"}
        discord_status = self.discord.status()
        app.data.connections["Discord (Optional)"] = {
            "url": discord_status.detail,
            "status": discord_status.state,
        }
        app.data.agent_state["bridge"]["status"] = "Starting"
        app.data.agent_state["bridge"]["activity"] = "Starting managed browser controller"
        self._diagnostic_unsubscribe = self.diagnostics.subscribe(self._on_diagnostic_event)
        self.root.after(25, self._drain_ui_queue)

    def start(self) -> None:
        if self._service_thread is not None and self._service_thread.is_alive():
            return
        self._service_thread = threading.Thread(target=self._start_services, name="Zenless-Startup", daemon=True)
        self._service_thread.start()

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        task_id = self.orchestrator.current_task_id
        if task_id:
            self.orchestrator.cancel(task_id)
        self._manual_test_cancel.set()
        self.bridge.stop()
        self.orchestrator.wait_for_idle(2.0)
        manual_thread = self._manual_test_thread
        if manual_thread is not None and manual_thread is not threading.current_thread():
            manual_thread.join(timeout=2.0)
        self.studio.close()
        for thread in tuple(self._provider_threads):
            if thread is not threading.current_thread():
                thread.join(timeout=2.0)
        self.store.maintenance()
        if self._diagnostic_unsubscribe is not None:
            self._diagnostic_unsubscribe()
            self._diagnostic_unsubscribe = None
        if self._owns_diagnostics:
            self.diagnostics.close()

    def submit_prompt(self, text: str) -> str:
        if self.app is None:
            raise RuntimeError("Controller ainda não anexado à HUD.")
        if self._manual_test_running():
            raise RuntimeError("Finalize o Play Test manual antes de iniciar uma tarefa.")
        options = TaskOptions.from_ui(self.app.data.task_options)
        task_id = self.orchestrator.submit(text, options)
        self._schedule(lambda: self._refresh_chat())
        return task_id

    def approve_changes(self) -> None:
        self._approve_active(("changes:", "repair:"), "approve")

    def edit_changes(self) -> None:
        if self.app is None:
            return
        note = simpledialog.askstring(
            "Zenless • ajustar proposta",
            "O que deve ser alterado antes de aplicar no Studio?",
            parent=self.root,
        )
        if note is not None:
            self._approve_active(("changes:", "repair:"), "edit", note)

    def reject_changes(self) -> None:
        self._approve_active(("changes:", "repair:"), "reject", "Rejeitado na HUD.")

    def approve_visual(self) -> None:
        accepted = self._approve_active(("visual",), "approve")
        if accepted and self.app is not None:
            self.app.data.visual_approval_state = "APPROVED"
            self.app.data.model_3d_state = "AVAILABLE"

    def approve_3d(self) -> None:
        accepted = self._approve_active(("3d",), "approve")
        if accepted and self.app is not None:
            self.app.data.model_3d_approval = "APPROVED"

    def start_manual_test(self) -> None:
        if self.orchestrator.busy:
            self._append_ui_message(
                "Orchestrator",
                "O Play Test manual fica bloqueado enquanto uma tarefa está usando o Studio.",
                "warning",
            )
            return
        with self._manual_test_lock:
            if self._manual_test_thread is not None and self._manual_test_thread.is_alive():
                self._append_ui_message("Roblox Studio", "Já existe um Play Test manual em andamento.", "warning")
                return
            self._manual_test_cancel.clear()
            self._manual_test_thread = threading.Thread(
                target=self._manual_test_worker,
                name="Zenless-ManualPlayTest",
                daemon=True,
            )
            self._manual_test_thread.start()

    def stop_manual_test(self) -> None:
        self._manual_test_cancel.set()

    def rescan_studio(self) -> None:
        if self.orchestrator.busy or self._manual_test_running():
            self._append_ui_message(
                "StudioMCP",
                "A sincronização será liberada quando a operação atual do Studio terminar.",
                "warning",
            )
            return
        with self._rescan_lock:
            if self._rescan_thread is not None and self._rescan_thread.is_alive():
                return
            self._rescan_thread = threading.Thread(
                target=self._rescan_studio_worker,
                name="Zenless-RescanStudio",
                daemon=True,
            )
            self._rescan_thread.start()

    def toggle_context(self) -> None:
        if self.app is None:
            return
        page = self.app.pw.get("chat")
        label = getattr(page, "_context_last_clicked", "live-studio")
        if label in self._context_enabled:
            self._context_enabled.remove(label)
        else:
            self._context_enabled.add(label)
        self._append_ui_message("Context", f"Regra de contexto alternada: {label}", "info")

    def set_agent_setting(self, agent: str, key: str, value: str) -> None:
        self.store.set_setting(f"agent.{agent}.{key}", value)

    def set_smart_routing(self, enabled: bool) -> None:
        self.store.set_setting("smart_routing", bool(enabled))

    def connect_agent(self, code: str) -> None:
        if code == "bridge":
            self._copy_bridge_token()
            return
        if code == "studio":
            threading.Thread(target=self._connect_studio, name="Zenless-ConnectStudio", daemon=True).start()
            return
        if code in {"chatgpt", "deepseek", "hunyuan"}:
            self._start_provider_login(code)
            return
        self._set_agent_status(code, "Error", "Unknown connection target")

    def diff_lines(self) -> tuple[str, list[tuple[str, str]]]:
        task = self.orchestrator.active_task() or {}
        proposal = task.get("proposal") or {}
        review = task.get("review") or {}
        verdict = str(review.get("verdict", "waiting")).upper()
        risk = str(review.get("risk", "unknown")).title()
        summary = str(review.get("summary", "Sem revisão persistida ainda."))
        review_text = f"Status: {verdict}  |  Risk: {risk}  |  {summary}"
        lines: list[tuple[str, str]] = []
        for action in proposal.get("actions", []):
            if not isinstance(action, dict):
                continue
            tool = str(action.get("tool", "unknown"))
            arguments = action.get("arguments") or {}
            if tool == "multi_edit" and isinstance(arguments, dict):
                path = str(arguments.get("file_path", "script"))
                lines.append(("mod", f"~ {path}"))
                for edit in arguments.get("edits", [])[:20]:
                    if not isinstance(edit, dict):
                        continue
                    old = str(edit.get("old_string", ""))
                    new = str(edit.get("new_string", ""))
                    if old:
                        lines.append(("del", "- " + self._one_line(old)))
                    if new:
                        lines.append(("add", "+ " + self._one_line(new)))
            else:
                lines.append(("mod", f"~ {tool}: {self._one_line(json.dumps(arguments, ensure_ascii=False))}"))
        if not lines:
            lines.append(("sys", "-- Nenhuma alteração persistente pronta --"))
        return review_text, lines

    def context_items(self) -> list[str]:
        task = self.orchestrator.active_task() or {}
        context = task.get("context") or {}
        items = [str(key) for key in (context.get("reads") or {}).keys()]
        return items[:20] or ["Live Studio tree", "Script inventory", "Studio Output"]

    def studio_tree_lines(self) -> list[str]:
        if self.app is not None and hasattr(self.app.data, "studio_tree_lines"):
            return list(self.app.data.studio_tree_lines)
        return ["Game", "Workspace", "ReplicatedStorage", "ServerScriptService", "StarterPlayer", "StarterGui"]

    def bridge_pairing_text(self) -> str:
        return self.bridge_token

    def _start_services(self) -> None:
        try:
            self.bridge.start()
            self._update_connection(
                "Managed Browser",
                "Ready",
                "WebView2 embedded primary; Playwright and extension are automatic fallbacks",
            )
            self._set_agent_status("bridge", "Connected", "Managed browser controller ready")
        except BridgeError as exc:
            self._set_agent_status("bridge", "Error", str(exc))
            self._update_connection("Managed Browser", "Error", str(exc))
            self.diagnostics.report(
                severity="ERROR",
                source="startup",
                component="agent-gateway",
                message=str(exc),
                exc=exc,
                impact="Web providers are unavailable until a transport starts.",
                recovery_action="Retry provider login or use the extension fallback.",
            )
        try:
            removed, bytes_removed = self.storage.cleanup_temporary()
            self.store.maintenance()
            if removed:
                self.diagnostics.report(
                    severity="INFO",
                    source="storage",
                    component="startup-maintenance",
                    message=f"Removed {removed} stale temporary files ({bytes_removed} bytes).",
                )
        except Exception as exc:
            self.diagnostics.report(
                severity="WARNING",
                source="storage",
                component="startup-maintenance",
                message=str(exc),
                exc=exc,
                impact="Zenless remains usable; temporary storage was not compacted.",
            )
        try:
            self._connect_studio()
        except Exception as exc:
            self._set_agent_status("studio", "Error", str(exc))
            self.diagnostics.report(
                severity="ERROR",
                source="startup",
                component="studio-connect",
                message=str(exc),
                exc=exc,
                recovery_action="Confirm Roblox Studio is in Edit and StudioMCP is enabled, then rescan.",
            )

    def _start_provider_login(self, provider: str) -> None:
        def worker() -> None:
            try:
                self._set_agent_status(provider, "Connecting", "Preparing managed login window")
                self.bridge.login(provider, timeout=600)
            except Exception as exc:
                self._set_agent_status(provider, "Error", str(exc))
                self.diagnostics.report(
                    severity="ERROR",
                    source="browser",
                    component=f"login:{provider}",
                    message=str(exc),
                    exc=exc,
                    recovery_action="Retry Login. CAPTCHA, 2FA and passwords remain manual.",
                )
            finally:
                self._provider_threads.discard(threading.current_thread())

        thread = threading.Thread(target=worker, name=f"Zenless-Login-{provider}", daemon=True)
        self._provider_threads.add(thread)
        thread.start()

    def _connect_studio(self) -> None:
        with self._studio_connect_lock:
            try:
                if not self.studio.running:
                    self.studio.start()
                studios = self.studio.list_studios()
                if not studios:
                    raise MCPError("StudioMCP iniciou, mas nenhum Studio está conectado.")
                target = studios[0]
                self._set_agent_status("studio", "Connected", target.label)
                self._update_connection("StudioMCP", "Connected", f"{len(self.studio.tools)} tools • {target.label}")
                self._rescan_studio_worker()
            except Exception as exc:
                self._set_agent_status("studio", "Error", str(exc))
                self._update_connection("StudioMCP", "Error", str(exc))
                self.diagnostics.report(
                    severity="ERROR",
                    source="studio",
                    component="connect",
                    message=str(exc),
                    exc=exc,
                    recovery_action="Keep Studio in Edit, enable MCP Servers and use Rescan Studio.",
                )

    def _rescan_studio_worker(self) -> None:
        try:
            if not self.studio.running:
                self.studio.start()
            studios = self.studio.list_studios()
            if not studios:
                raise MCPError("Nenhum Studio conectado.")
            target = studios[0]
            result = self.studio.call_tool(
                "search_game_tree",
                {"datamodel_type": "Edit", "max_depth": 4, "head_limit": 220},
                studio_id=target.studio_id,
                timeout=90,
            )
            names = self._tree_names(result.text)
            if self.app is not None:
                app = self.app
                self._schedule(lambda: setattr(app.data, "studio_tree_lines", names))
                self._schedule(self._refresh_studio_page)
            self._append_ui_message("StudioMCP", f"Hierarquia sincronizada: {len(names)} nós visíveis.", "success")
        except Exception as exc:
            self._append_ui_message("StudioMCP", str(exc), "error")
            self.diagnostics.report(
                severity="ERROR",
                source="studio",
                component="rescan",
                message=str(exc),
                exc=exc,
                recovery_action="Return Studio to Edit and retry the hierarchy scan.",
            )

    def _manual_test_worker(self) -> None:
        started = False
        studio_id = ""
        output = ""
        final_status = "FAILED"
        self._set_test_status("RUNNING", "Iniciando Play Test real...")
        try:
            if not self.studio.running:
                self.studio.start()
            studios = self.studio.list_studios()
            if not studios:
                raise MCPError("Nenhum Studio conectado.")
            studio_id = studios[0].studio_id
            if "get_studio_state" in self.studio.tools:
                state = self.studio.call_tool("get_studio_state", {}, studio_id=studio_id, timeout=30)
                if state.is_error or "Current Studio Mode: Edit" not in state.text:
                    raise MCPError("O Studio precisa estar em Edit antes do Play Test manual.")
            result = self.studio.call_tool("start_stop_play", {"is_start": True}, studio_id=studio_id, timeout=60)
            if result.is_error:
                raise MCPError(result.text)
            started = True
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and not self._manual_test_cancel.wait(0.1):
                pass
            if self._manual_test_cancel.is_set():
                output = "Play Test interrompido pelo usuário."
                final_status = "IDLE"
            else:
                console = self.studio.call_tool("get_console_output", {}, studio_id=studio_id, timeout=60)
                if console.is_error:
                    raise MCPError(console.text or "Não foi possível ler o Output.")
                output = console.text or "Output vazio; nenhum erro detectado."
                final_status = "FAILED" if self.orchestrator._console_has_errors(output) else "PASSED"
        except Exception as exc:
            output = f"Falha no Play Test: {exc}"
            final_status = "FAILED"
        finally:
            if started and studio_id:
                try:
                    stopped = self.studio.call_tool(
                        "start_stop_play", {"is_start": False}, studio_id=studio_id, timeout=60
                    )
                    if stopped.is_error:
                        raise MCPError(stopped.text or "Studio recusou Stop.")
                    if "get_studio_state" in self.studio.tools:
                        state = self.studio.call_tool("get_studio_state", {}, studio_id=studio_id, timeout=30)
                        if state.is_error or "Current Studio Mode: Edit" not in state.text:
                            raise MCPError("Studio não confirmou retorno ao modo Edit.")
                except Exception as exc:
                    output += f"\nFalha ao retornar ao Edit: {exc}"
                    final_status = "FAILED"
            self._set_test_status(final_status, output)

    def _manual_test_running(self) -> bool:
        with self._manual_test_lock:
            return self._manual_test_thread is not None and self._manual_test_thread.is_alive()

    def _approve_active(self, prefixes: tuple[str, ...], decision: str, note: str = "") -> bool:
        task_id = self.orchestrator.current_task_id
        if not task_id:
            messagebox.showinfo("Zenless", "Não há tarefa aguardando aprovação.", parent=self.root)
            return False
        accepted = self.orchestrator.approve_active(task_id, prefixes, decision, note)
        if not accepted:
            messagebox.showinfo("Zenless", "Esta etapa ainda não está aguardando sua decisão.", parent=self.root)
        return accepted

    def _copy_bridge_token(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.bridge_token)
        self.root.update_idletasks()
        messagebox.showinfo(
            "Zenless • Browser Bridge",
            "Token de pareamento copiado. A extensão está em:\n"
            f"{self.data_root / 'extension' / 'manifest.json'}\n\n"
            "Cole o token no popup somente se o Native Messaging não estiver disponível.",
            parent=self.root,
        )

    def _on_pipeline_event(self, event: PipelineEvent) -> None:
        self._schedule(lambda: self._apply_pipeline_event(event))

    def _apply_pipeline_event(self, event: PipelineEvent) -> None:
        if self.app is None:
            return
        if event.stage not in {Stage.PAUSED, Stage.BLOCKED, Stage.FAILED}:
            self.app.data.pipeline_previous_state = event.stage.value
        self.app.data.pipeline_state = event.stage.value
        actor = "Orchestrator"
        if event.stage in {Stage.CREATING, Stage.REVISING, Stage.REPAIRING}:
            actor = "Agent [ChatGPT]"
            self._set_agent_status_ui("chatgpt", "Connected", event.message)
        elif event.stage == Stage.REVIEWING:
            actor = "Agent [DeepSeek]"
            self._set_agent_status_ui("deepseek", "Connected", event.message)
        elif event.stage in {Stage.APPLYING, Stage.TESTING, Stage.COLLECTING_CONTEXT}:
            actor = "Roblox Studio"
            self._set_agent_status_ui("studio", "Connected", event.message)
        elif event.stage == Stage.WAITING_3D_APPROVAL:
            actor = "Agent [Hunyuan3D]"
            self.app.data.model_3d_state = "AVAILABLE"
            self.app.data.hunyuan_status = "Awaiting approval"
            try:
                artifact = json.loads(event.detail)
            except (TypeError, json.JSONDecodeError):
                artifact = {}
            if isinstance(artifact, dict):
                artifact_path = str(artifact.get("path") or "")
                self.app.data.model_3d_path = artifact_path
                download_error = str(artifact.get("download_error") or "")
                if download_error:
                    self.app.data.hunyuan_status = "Generated; local download needs attention"
        if event.stage == Stage.WAITING_VISUAL_APPROVAL:
            self.app.data.visual_approval_state = "WAITING_IMAGE_APPROVAL"
            self.app.data.concept_desc = event.detail or self.app.data.concept_desc
        color = "error" if event.kind == "error" else ("success" if event.kind == "success" else "info")
        artifact_path = self.app.data.model_3d_path if event.stage == Stage.WAITING_3D_APPROVAL else ""
        self._append_ui_message(actor, event.message, color, refresh=False, artifact_path=artifact_path)
        if event.stage == Stage.TESTING:
            self.app.data.test_logs.append((event.message + ("\n" + event.detail if event.detail else ""), "warn" if event.kind == "warning" else "sys"))
        self._refresh_chat()
        self._refresh_pipeline_view()
        if event.kind == "error":
            self.diagnostics.report(
                severity="ERROR",
                source="orchestrator",
                component=event.stage.value,
                message=event.message,
                job_id=event.task_id,
                probable_cause=event.detail,
                impact="The current task did not reach its next pipeline stage.",
                recovery_action="Read the task log, fix the reported dependency and retry once.",
            )
            self.discord.notify_async("Zenless task failed", event.message)
        elif event.stage == Stage.COMPLETE:
            self.discord.notify_async("Zenless task complete", event.message)

    def _on_bridge_status(self, provider: str, state: str, detail: str) -> None:
        if provider == "bridge":
            self._update_connection("Extension Fallback", state, detail)
        elif "extension fallback" in detail.casefold():
            self._update_connection("Extension Fallback", state, detail)
        else:
            self._update_connection("Managed Browser", state, f"{provider}: {detail}")
        if provider in {"chatgpt", "deepseek", "hunyuan", "bridge"}:
            normalized = "Connected" if state.lower() in {"connected", "ready", "idle"} else state
            self._set_agent_status(provider, normalized, detail)

    def _on_mcp_notification(self, message: dict[str, Any]) -> None:
        method = str(message.get("method", "notification"))
        self._append_ui_message("StudioMCP", f"Notification: {method}", "info")

    def _on_discord_error(self, exc: BaseException) -> None:
        self.diagnostics.report(
            severity="WARNING",
            source="discord",
            component="webhook",
            message=str(exc),
            exc=exc,
            impact="Only the optional notification was skipped.",
            recovery_action="Check the webhook configuration; normal Zenless operation is unaffected.",
        )

    def _on_diagnostic_event(self, event: DiagnosticEvent) -> None:
        if event.severity not in {"ERROR", "CRITICAL"}:
            return

        def apply() -> None:
            if self.app is None:
                return
            location = f"{Path(event.file).name}:{event.line}" if event.file else event.component
            text = f"[{event.severity}] {event.source}/{location} — {event.message}"
            self.app.data.test_logs.append((text, "warn"))

        self._schedule(apply)

    def _set_agent_status(self, code: str, status: str, activity: str) -> None:
        self._schedule(lambda: self._set_agent_status_ui(code, status, activity))

    def _set_agent_status_ui(self, code: str, status: str, activity: str) -> None:
        if self.app is None or code not in self.app.data.agent_state:
            return
        self.app.data.agent_state[code]["status"] = status
        self.app.data.agent_state[code]["activity"] = activity
        onboarding = self.app.pw.get("onboard")
        controls = getattr(onboarding, "bts", {}).get(code)
        if controls:
            led, button, frame = controls
            try:
                if led.winfo_exists() and button.winfo_exists() and frame.winfo_exists():
                    connected = status == "Connected"
                    waiting = status in {
                        "Starting",
                        "Connecting",
                        "Working",
                        "Installing",
                        "Requires Attention",
                        "Login Needed",
                        "Login Required",
                        "Runtime Required",
                    }
                    color = self._colors.get("ok" if connected else ("warn" if waiting else "err"), "#E6E6E6")
                    led.configure(fg=color)
                    frame.configure(highlightbackground=color if connected or waiting else self._colors.get("line2", color))
                    button.lbl.configure(text="Stream Locked" if connected else ("Check Session" if waiting else "Retry Tunnel"))
            except Exception:
                pass
        if self.app.curr in {"agen", "dash", "onboard"}:
            page = self.app.pw.get(self.app.curr)
            if hasattr(page, "on_enter"):
                try:
                    page.on_enter()
                except Exception:
                    pass

    def _update_connection(self, name: str, state: str, detail: str) -> None:
        def apply() -> None:
            if self.app is None:
                return
            if name in self.app.data.connections:
                self.app.data.connections[name]["status"] = state
                self.app.data.connections[name]["url"] = detail
            if self.app.curr == "set" and getattr(self.app.pw["set"], "cur_tab", "") == "Connections":
                self.app.pw["set"]._ro("Connections")

        self._schedule(apply)

    def _append_ui_message(
        self,
        sender: str,
        text: str,
        level: str,
        *,
        refresh: bool = True,
        artifact_path: str = "",
    ) -> None:
        def apply() -> None:
            if self.app is None:
                return
            color = self._colors.get(
                "err" if level == "error" else ("ok" if level == "success" else "info"),
                "#5DA2FF",
            )
            self.app.data.messages.append(
                {"type": "agent", "sender": sender, "text": text, "color": color, "artifact_path": artifact_path}
            )
            if refresh:
                self._refresh_chat()

        self._schedule(apply)

    def _refresh_chat(self) -> None:
        if self.app is None or self.app.curr != "chat":
            return
        page = self.app.pw["chat"]
        if getattr(page, "cur_tab", "") == "Chat / Tasks":
            page._route("Chat / Tasks")

    def _refresh_pipeline_view(self) -> None:
        if self.app is None:
            return
        page = self.app.pw.get("chat")
        view = getattr(page, "pipe_view", None)
        if view is not None and view.winfo_exists():
            view.render()

    def _refresh_studio_page(self) -> None:
        if self.app is not None and self.app.curr == "studio":
            self.app.pw["studio"]._r("Studio Hierarchy")

    def _set_test_status(self, status: str, text: str) -> None:
        def apply() -> None:
            if self.app is None:
                return
            self.app.data.test_logs.append((text, "warn" if "Falha" in text or "Error" in text else "sys"))
            page = self.app.pw.get("test")
            if page is not None:
                page.st_lbl.configure(text=f"Status: {status}")
                if self.app.curr == "test":
                    page.on_enter()

        self._schedule(apply)

    def _schedule(self, callback: Callable[[], None]) -> None:
        if self._closing:
            return
        self._ui_queue.put(callback)

    def _drain_ui_queue(self) -> None:
        if self._closing:
            return
        for _ in range(100):
            try:
                callback = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception as exc:
                self.diagnostics.report(
                    severity="ERROR",
                    source="ui",
                    component="dispatcher",
                    message=str(exc),
                    exc=exc,
                    impact="One queued HUD update was skipped.",
                    recovery_action="Retry the related control; inspect Zenless Logs if it repeats.",
                )
        try:
            self.root.after(25, self._drain_ui_queue)
        except Exception as exc:
            if not self._closing:
                self.diagnostics.report(
                    severity="ERROR",
                    source="ui",
                    component="dispatcher-schedule",
                    message=str(exc),
                    exc=exc,
                )

    @staticmethod
    def _tree_names(text: str) -> list[str]:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return [line.strip() for line in text.splitlines() if line.strip()][:80]
        names: list[str] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    path = str(item.get("fullPath") or item.get("name") or "")
                    if path and path not in names:
                        names.append(path)
        return names[:100]

    @staticmethod
    def _one_line(text: str, limit: int = 180) -> str:
        compact = " ".join(text.split())
        return compact if len(compact) <= limit else compact[:limit] + "..."
