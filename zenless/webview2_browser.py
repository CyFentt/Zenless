from __future__ import annotations

import json
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, cast
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .browser_bridge import BridgeError, LoginWindowOpenedCallback, StatusCallback
from .diagnostics import ErrorBus
from .managed_browser import PROVIDERS, ProviderSpec
from .native_host import read_native_message, write_native_message


@dataclass(slots=True)
class _Pending:
    provider: str = ""
    event: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None
    error: str = ""
    stream_callback: Callable[[str], None] | None = None
    window_opened_callback: LoginWindowOpenedCallback | None = None
    window_opened_notified: bool = False


class WebView2BrowserController:
    def __init__(
        self,
        *,
        data_root: Path,
        status_callback: StatusCallback | None = None,
        diagnostics: ErrorBus | None = None,
        provider_specs: dict[str, ProviderSpec] | None = None,
        host_executable: Path | None = None,
    ) -> None:
        self.data_root = data_root
        self.profile_root = data_root / "webview-profile"
        self.provider_specs = dict(provider_specs or PROVIDERS)
        self.status_callback = status_callback
        self.diagnostics = diagnostics
        self.host_executable = host_executable
        self._process: subprocess.Popen[bytes] | None = None
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._write_lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}
        self._pending_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._states: dict[str, dict[str, str]] = {
            code: {"state": "Standby", "detail": "WebView2 fallback idle", "transport": "webview2"}
            for code in self.provider_specs
        }
        self._states_lock = threading.Lock()
        self._stderr_tail = ""

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, timeout: float = 20.0) -> None:
        with self._lifecycle_lock:
            if self.running:
                return
            config_path = self.data_root / "webview-provider-config.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(
                    {code: asdict(spec) for code, spec in self.provider_specs.items()},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            command = self._command(config_path)
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._reader = threading.Thread(target=self._read_loop, name="Zenless-WebView2-stdout", daemon=True)
            self._stderr_reader = threading.Thread(
                target=self._read_stderr,
                name="Zenless-WebView2-stderr",
                daemon=True,
            )
            self._reader.start()
            self._stderr_reader.start()
        result = self._request("ping", "", {}, timeout=timeout)
        if result.get("engine") != "webview2":
            raise BridgeError("WebView2 helper returned an invalid handshake.")

    def stop(self, timeout: float = 8.0) -> None:
        with self._lifecycle_lock:
            process = self._process
        if process is None:
            return
        if process.poll() is None:
            try:
                self._request("shutdown", "", {}, timeout=min(3.0, timeout))
            except BridgeError:
                pass
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=max(1.0, timeout))
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired as exc:
                raise BridgeError("WebView2 helper did not stop cooperatively.") from exc
        for thread in (self._reader, self._stderr_reader):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=2)
        with self._lifecycle_lock:
            self._process = None
            self._reader = None
            self._stderr_reader = None

    def provider_status(self) -> dict[str, dict[str, str]]:
        with self._states_lock:
            return {key: dict(value) for key, value in self._states.items()}

    def wait_for_provider(self, provider: str, timeout: float = 20.0) -> bool:
        try:
            if not self.running:
                self.start(timeout=max(20.0, timeout))
            result = self._request("health", provider, {}, timeout=max(20.0, timeout))
        except BridgeError as exc:
            self._set_state(provider, "Unavailable", str(exc))
            return False
        ready = bool(result.get("ready"))
        self._set_state(
            provider,
            "Ready" if ready else "Login Required",
            "Authenticated WebView2 session" if ready else "Use Login to authenticate in the embedded window",
        )
        return ready

    def login(
        self,
        provider: str,
        *,
        timeout: float = 600.0,
        on_window_opened: LoginWindowOpenedCallback | None = None,
    ) -> dict[str, Any]:
        if not self.running:
            self.start()
        self._set_state(provider, "Login Required", "Complete login in the Zenless WebView2 window")
        result = self._request(
            "login",
            provider,
            {"timeout": timeout},
            timeout=timeout + 5,
            window_opened_callback=on_window_opened,
        )
        self._set_state(provider, "Ready", "Authenticated WebView2 session")
        return result

    def send_prompt(
        self,
        provider: str,
        prompt: str,
        *,
        task_id: str,
        timeout: float = 360.0,
        stream_callback: Callable[[str], None] | None = None,
    ) -> str:
        result = self.request(
            provider,
            "send_prompt",
            {"prompt": prompt, "timeout_ms": int(timeout * 1000)},
            task_id=task_id,
            timeout=timeout,
            stream_callback=stream_callback,
        )
        text = str(result.get("text") or "").strip()
        if not text:
            raise BridgeError(f"{provider} returned no text through WebView2.")
        return text

    def request(
        self,
        provider: str,
        action: str,
        payload: dict[str, Any],
        *,
        task_id: str,
        timeout: float,
        stream_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        if not self.running:
            self.start()
        request_payload = dict(payload)
        request_payload.update({"provider_action": action, "task_id": task_id})
        self._set_state(provider, "Working", f"WebView2: {action}")
        result = self._request(
            "request",
            provider,
            request_payload,
            timeout=timeout,
            stream_callback=stream_callback,
        )
        if (
            action in {"generate_3d", "generate_geometry", "generate_texture"}
            and result.get("artifact_url")
            and not result.get("artifact_path")
        ):
            try:
                result["artifact_path"] = str(self._download_artifact(str(result["artifact_url"]), task_id))
            except Exception as exc:
                result["download_error"] = str(exc)
                self._report(exc, "artifact-download")
        self._set_state(provider, "Ready", "WebView2 session idle")
        return result

    def _download_artifact(self, url: str, task_id: str) -> Path:
        parsed = urlparse(url)
        suffix = Path(parsed.path).suffix.casefold()
        if parsed.scheme != "https" or suffix not in {".glb", ".gltf", ".fbx", ".obj"}:
            raise BridgeError("The 3D artifact URL is not a supported HTTPS download.")
        request = Request(url, headers={"User-Agent": "Zenless/1.0 WebView2"})
        target_dir = self.data_root / "downloads" / task_id[:64]
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"hunyuan-{uuid.uuid4().hex[:8]}{suffix}"
        temporary = target.with_suffix(target.suffix + ".tmp")
        total = 0
        try:
            with urlopen(request, timeout=120) as response, temporary.open("wb") as stream:
                length = int(response.headers.get("Content-Length", "0") or 0)
                if length > 256 * 1024 * 1024:
                    raise BridgeError("3D artifact exceeds the local 256 MB limit.")
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > 256 * 1024 * 1024:
                        raise BridgeError("3D artifact exceeds the local 256 MB limit.")
                    stream.write(chunk)
            temporary.replace(target)
            return target
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def _request(
        self,
        action: str,
        provider: str,
        payload: dict[str, Any],
        *,
        timeout: float,
        stream_callback: Callable[[str], None] | None = None,
        window_opened_callback: LoginWindowOpenedCallback | None = None,
    ) -> dict[str, Any]:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            detail = self._stderr_tail[-1500:]
            raise BridgeError("WebView2 helper is not running." + (" " + detail if detail else ""))
        request_id = uuid.uuid4().hex
        pending = _Pending(
            provider=provider,
            stream_callback=stream_callback,
            window_opened_callback=window_opened_callback,
        )
        with self._pending_lock:
            self._pending[request_id] = pending
        message = json.dumps(
            {"id": request_id, "action": action, "provider": provider, "payload": payload},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            write_native_message(cast(BinaryIO, process.stdin), message, self._write_lock)
            if not pending.event.wait(max(1.0, timeout)):
                raise BridgeError(f"WebView2 timeout during {action}/{provider or 'core'}.")
            if pending.error:
                raise BridgeError(pending.error)
            return pending.result or {}
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def _read_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        reason = "WebView2 helper closed its output."
        try:
            while True:
                payload = read_native_message(cast(BinaryIO, process.stdout))
                if payload is None:
                    break
                message = json.loads(payload.decode("utf-8"))
                request_id = str(message.get("id") or "")
                with self._pending_lock:
                    pending = self._pending.get(request_id)
                if pending is None:
                    continue
                event = message.get("event")
                if event == "login_window_opened":
                    if pending.window_opened_callback is not None and not pending.window_opened_notified:
                        pending.window_opened_notified = True
                        try:
                            pending.window_opened_callback(pending.provider, "webview2")
                        except Exception as exc:
                            self._report(exc, "login-window-opened-callback")
                    continue
                if event == "stream":
                    delta = message.get("delta")
                    if isinstance(delta, str) and delta and pending.stream_callback is not None:
                        try:
                            pending.stream_callback(delta)
                        except Exception as exc:
                            self._report(exc, "stream-callback")
                    continue
                if message.get("ok"):
                    result = message.get("result")
                    pending.result = result if isinstance(result, dict) else {}
                else:
                    pending.error = str(message.get("error") or "WebView2 command failed")
                pending.event.set()
        except Exception as exc:
            reason = f"WebView2 framing error: {exc}"
            self._report(exc, "read-loop")
        finally:
            self._fail_all(reason)

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while True:
            line = process.stderr.readline()
            if not line:
                return
            text = line.decode("utf-8", "replace")
            self._stderr_tail = (self._stderr_tail + text)[-8000:]

    def _fail_all(self, reason: str) -> None:
        with self._pending_lock:
            pending = list(self._pending.values())
        for item in pending:
            item.error = reason
            item.event.set()

    def _command(self, config_path: Path) -> list[str]:
        arguments = [
            "--webview-host",
            "--profile-root",
            str(self.profile_root),
            "--provider-config",
            str(config_path),
        ]
        if self.host_executable is not None:
            return [str(self.host_executable), *arguments]
        if getattr(sys, "frozen", False):
            return [sys.executable, *arguments]
        return [sys.executable, "-m", "zenless.webview_host", *arguments[1:]]

    def _set_state(self, provider: str, state: str, detail: str) -> None:
        with self._states_lock:
            self._states[provider] = {"state": state, "detail": detail, "transport": "webview2"}
        if self.status_callback is not None:
            self.status_callback(provider, state, detail)

    def _report(self, exc: BaseException, component: str) -> None:
        if self.diagnostics is not None:
            self.diagnostics.report(
                severity="ERROR",
                source="browser",
                component=f"webview2:{component}",
                message=str(exc),
                exc=exc,
                impact="The embedded browser route became unavailable.",
                recovery_action="Retry the provider login; Zenless can use its managed Playwright fallback.",
            )
