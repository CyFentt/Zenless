from __future__ import annotations

import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import ServerConnection, serve

from .protocol import Envelope, ProtocolError, make_envelope, parse_envelope


class BridgeError(RuntimeError):
    pass


StatusCallback = Callable[[str, str, str], None]


@dataclass(slots=True)
class _Pending:
    provider: str
    event: threading.Event = field(default_factory=threading.Event)
    response: Envelope | None = None
    error: str = ""


@dataclass(slots=True)
class _Session:
    provider: str
    connection: ServerConnection
    tab_id: str
    transport: str
    connected_at: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)
    send_lock: threading.Lock = field(default_factory=threading.Lock)

    def send(self, envelope: Envelope) -> None:
        with self.send_lock:
            self.connection.send(envelope.to_json())


class BrowserBridge:
    def __init__(
        self,
        *,
        token: str,
        runtime_file: Path,
        host: str = "127.0.0.1",
        port: int = 17613,
        status_callback: StatusCallback | None = None,
    ) -> None:
        if len(token) < 32:
            raise ValueError("The bridge token must contain at least 32 characters.")
        self.token = token
        self.runtime_file = runtime_file
        self.host = host
        self.port = port
        self.status_callback = status_callback
        self._server: Any = None
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()
        self._stop_requested = threading.Event()
        self._ready = threading.Event()
        self._start_error = ""
        self._sessions: dict[str, _Session] = {}
        self._sessions_lock = threading.RLock()
        self._pending: dict[str, _Pending] = {}
        self._pending_lock = threading.Lock()
        self._provider_locks = {
            "chatgpt": threading.Lock(),
            "deepseek": threading.Lock(),
            "hunyuan": threading.Lock(),
        }

    @staticmethod
    def new_token() -> str:
        return secrets.token_urlsafe(48)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and self._start_error == ""

    def start(self, timeout: float = 8.0) -> None:
        with self._lifecycle_lock:
            if self.running:
                return
            if self._thread is not None and self._thread.is_alive():
                raise BridgeError("The previous bridge instance is still stopping.")
            self._ready.clear()
            self._stop_requested.clear()
            self._start_error = ""
            self._thread = threading.Thread(target=self._serve, name="Zenless-BrowserBridge", daemon=True)
            self._thread.start()
        if not self._ready.wait(timeout):
            raise BridgeError("The bridge did not confirm startup within the expected time.")
        if self._stop_requested.is_set():
            raise BridgeError("Bridge startup was canceled.")
        if self._start_error:
            raise BridgeError(self._start_error)
        self._write_runtime_file()
        self._emit_status("bridge", "Connected", f"ws://{self.host}:{self.port}")

    def stop(self) -> None:
        self._stop_requested.set()
        server = self._server
        if server is not None:
            server.shutdown()
        with self._sessions_lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            try:
                session.connection.close(1001, "Application closed")
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3)
        with self._lifecycle_lock:
            if thread is None or not thread.is_alive():
                self._thread = None
            else:
                self._start_error = "The bridge did not stop within the cooperative timeout."
        self._server = None
        self._fail_all("Bridge stopped.")
        self._remove_runtime_file()
        self._emit_status("bridge", "Disconnected", "Local bridge stopped")

    def provider_status(self) -> dict[str, dict[str, Any]]:
        with self._sessions_lock:
            return {
                provider: {
                    "connected": True,
                    "tab_id": session.tab_id,
                    "transport": session.transport,
                    "last_seen": session.last_seen,
                }
                for provider, session in self._sessions.items()
            }

    def wait_for_provider(self, provider: str, timeout: float = 0.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            with self._sessions_lock:
                if provider in self._sessions:
                    return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def request(
        self,
        provider: str,
        action: str,
        payload: dict[str, Any],
        *,
        task_id: str,
        timeout: float = 240.0,
    ) -> dict[str, Any]:
        if provider not in self._provider_locks:
            raise BridgeError("Unsupported browser service.")
        if not action or len(action) > 64:
            raise BridgeError("Invalid bridge action.")
        with self._provider_locks[provider]:
            with self._sessions_lock:
                session = self._sessions.get(provider)
            if session is None:
                raise BridgeError("The browser service is not connected. Sign in and keep the tab open.")

            command = make_envelope(
                "agent.command",
                source="zenless",
                provider=provider,
                task_id=task_id,
                payload={"action": action, **payload},
            )
            pending = _Pending(provider=provider)
            with self._pending_lock:
                self._pending[command.id] = pending
            try:
                session.send(command)
                if not pending.event.wait(max(1.0, timeout)):
                    raise BridgeError(f"The browser service exceeded {timeout:.0f}s while running {action}.")
                if pending.error:
                    raise BridgeError(pending.error)
                if pending.response is None:
                    raise BridgeError("The browser service finished without a valid response.")
                return dict(pending.response.payload)
            except ConnectionClosed as exc:
                raise BridgeError(f"The browser service connection was closed: {exc}") from exc
            finally:
                with self._pending_lock:
                    self._pending.pop(command.id, None)

    def send_prompt(self, provider: str, prompt: str, *, task_id: str, timeout: float = 360.0) -> str:
        clean_prompt = prompt.strip()
        if not clean_prompt:
            raise BridgeError("Prompt is empty.")
        response = self.request(
            provider,
            "send_prompt",
            {"prompt": clean_prompt, "timeout_ms": int(timeout * 1000)},
            task_id=task_id,
            timeout=timeout + 15,
        )
        status = str(response.get("status", "ok"))
        if status == "requires_attention":
            reason = str(response.get("error") or response.get("message") or "The tab requires manual attention.")
            raise BridgeError(reason)
        text = str(response.get("text", "")).strip()
        if not text:
            raise BridgeError("The browser service returned no text.")
        return text

    def _serve(self) -> None:
        try:
            with serve(
                self._handle_connection,
                self.host,
                self.port,
                compression="deflate",
                max_size=2 * 1024 * 1024,
                max_queue=32,
                ping_interval=20,
                ping_timeout=20,
            ) as server:
                self._server = server
                self._ready.set()
                if self._stop_requested.is_set():
                    threading.Thread(
                        target=server.shutdown,
                        name="Zenless-BrowserBridge-EarlyStop",
                        daemon=True,
                    ).start()
                server.serve_forever()
        except OSError as exc:
            self._start_error = f"Could not open {self.host}:{self.port}: {exc}"
            self._ready.set()
        except Exception as exc:
            self._start_error = f"Unexpected bridge failure: {exc}"
            self._ready.set()
        finally:
            self._server = None

    def _handle_connection(self, connection: ServerConnection) -> None:
        session: _Session | None = None
        try:
            request = getattr(connection, "request", None)
            path = getattr(request, "path", "")
            query = parse_qs(urlsplit(path).query)
            supplied = query.get("token", [""])[0]
            if not secrets.compare_digest(supplied, self.token):
                connection.close(1008, "Invalid token")
                return

            hello = parse_envelope(connection.recv(timeout=12))
            if hello.type != "bridge.hello" or hello.source not in {"extension", "native-host"}:
                connection.close(1008, "Invalid handshake")
                return
            provider = hello.provider
            if provider not in self._provider_locks:
                connection.close(1008, "Invalid service")
                return
            session = _Session(
                provider=provider,
                connection=connection,
                tab_id=str(hello.payload.get("tab_id", "unknown"))[:128],
                transport=str(hello.payload.get("transport", "websocket"))[:64],
            )
            with self._sessions_lock:
                previous = self._sessions.get(provider)
                self._sessions[provider] = session
            if previous is not None and previous.connection is not connection:
                try:
                    previous.connection.close(1000, "A new tab replaced this session")
                except Exception:
                    pass
            session.send(
                make_envelope(
                    "bridge.ready",
                    source="zenless",
                    provider=provider,
                    reply_to=hello.id,
                    payload={"accepted": True, "protocol": 1},
                )
            )
            self._emit_status(provider, "Connected", f"tab {session.tab_id} via {session.transport}")

            while True:
                raw = connection.recv()
                envelope = parse_envelope(raw)
                session.last_seen = time.monotonic()
                self._route_envelope(envelope)
        except (ConnectionClosed, TimeoutError):
            pass
        except ProtocolError as exc:
            try:
                connection.close(1008, str(exc)[:120])
            except Exception:
                pass
        except Exception as exc:
            if session is not None:
                self._emit_status(session.provider, "Error", str(exc))
        finally:
            if session is not None:
                with self._sessions_lock:
                    if self._sessions.get(session.provider) is session:
                        self._sessions.pop(session.provider, None)
                self._fail_provider(session.provider, "The browser service session disconnected.")
                self._emit_status(session.provider, "Disconnected", "Tab unavailable")

    def _route_envelope(self, envelope: Envelope) -> None:
        if envelope.type == "bridge.heartbeat":
            return
        if envelope.type not in {"agent.result", "agent.error", "agent.status"}:
            return
        if envelope.type == "agent.status":
            state = str(envelope.payload.get("state", "Working"))[:64]
            detail = str(envelope.payload.get("detail", ""))[:300]
            self._emit_status(envelope.provider, state, detail)
            return
        request_id = envelope.reply_to
        if not request_id:
            return
        with self._pending_lock:
            pending = self._pending.get(request_id)
        if pending is None or pending.provider != envelope.provider:
            return
        if envelope.type == "agent.error":
            pending.error = str(envelope.payload.get("error", "Web agent failure."))
        else:
            pending.response = envelope
        pending.event.set()

    def _fail_provider(self, provider: str, reason: str) -> None:
        with self._pending_lock:
            targets = [item for item in self._pending.values() if item.provider == provider]
        for pending in targets:
            pending.error = reason
            pending.event.set()

    def _fail_all(self, reason: str) -> None:
        with self._pending_lock:
            targets = list(self._pending.values())
        for pending in targets:
            pending.error = reason
            pending.event.set()

    def _emit_status(self, provider: str, state: str, detail: str) -> None:
        if self.status_callback is not None:
            self.status_callback(provider, state, detail)

    def _write_runtime_file(self) -> None:
        self.runtime_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "host": self.host,
            "port": self.port,
            "token": self.token,
            "protocol": 1,
        }
        temporary = self.runtime_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        temporary.replace(self.runtime_file)

    def _remove_runtime_file(self) -> None:
        try:
            data = json.loads(self.runtime_file.read_text(encoding="utf-8"))
            if int(data.get("pid", -1)) == os.getpid():
                self.runtime_file.unlink(missing_ok=True)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
