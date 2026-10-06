from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .browser_bridge import BridgeError, BrowserBridge, StatusCallback
from .managed_browser import ManagedBrowserController
from .webview2_browser import WebView2BrowserController


class AgentGateway:
    _ACTION_CAPABILITIES = {
        "upload_files": "upload_files",
        "select_model": "select_model",
        "get_models": "select_model",
        "cancel": "cancel",
        "generate_geometry": "geometry",
        "generate_texture": "texture",
    }
    _HUNYUAN_TRANSACTION_ACTIONS = frozenset({"capabilities", "upload_files", "generate_geometry", "generate_texture"})
    _HUNYUAN_REQUIRED_CAPABILITIES = frozenset({"upload_files", "geometry", "texture"})

    def __init__(
        self,
        *,
        managed: ManagedBrowserController,
        embedded: WebView2BrowserController,
        extension: BrowserBridge | None = None,
        status_callback: StatusCallback | None = None,
        allow_extension_fallback: bool = False,
        local_available: Callable[[], bool] | None = None,
        local_complete: Callable[[str], str] | None = None,
        selected_model: Callable[[str], str] | None = None,
        local_cancel: Callable[[], None] | None = None,
    ) -> None:
        self.managed = managed
        self.embedded = embedded
        self.extension = extension
        self.status_callback = status_callback
        self.allow_extension_fallback = allow_extension_fallback
        self._routes: dict[str, str] = {}
        self._task_routes: dict[tuple[str, str], str] = {}
        self._route_lock = threading.Lock()
        self._stopping = threading.Event()
        self.local_available = local_available
        self.local_complete = local_complete
        self.selected_model = selected_model
        self.local_cancel = local_cancel
        self._local_attachments: dict[tuple[str, str], str] = {}

    def _can_use_local(self, provider: str) -> bool:
        return (provider in {"chatgpt", "deepseek"} and self.local_available is not None
                and self.local_available() and (self.selected_model is None or self.selected_model(provider) == "auto"))

    def _apply_selected_model(self, route: str, provider: str, task_id: str) -> None:
        model = self.selected_model(provider) if self.selected_model is not None else "auto"
        if model == "auto":
            return
        result = self._request_via_route(
            route,
            provider,
            "select_model",
            {"model": model},
            task_id=task_id,
            timeout=20,
            stream_callback=None,
        )
        selected = str(result.get("selected") or "").strip()
        if result.get("status") != "ok" or selected.casefold() != str(model).strip().casefold():
            raise BridgeError(
                f"The selected {provider} model could not be confirmed: requested {model}, provider reported {selected or 'none'}"
            )

    @property
    def running(self) -> bool:
        return self.managed.running or self.embedded.running or bool(self.extension and self.extension.running)

    def start(self) -> None:
        self._stopping.clear()
        try:
            self.managed.start()
        except BridgeError as exc:
            if self.status_callback is not None:
                self.status_callback("browser", "Degraded", str(exc))
        if self.allow_extension_fallback and self.extension is not None:
            self.extension.start()

    def stop(self) -> None:
        self._stopping.set()
        with self._route_lock:
            self._routes.clear()
            self._task_routes.clear()
        self.managed.stop()
        self.embedded.stop()
        if self.extension is not None:
            self.extension.stop()

    def login(self, provider: str, *, timeout: float = 180.0) -> dict[str, Any]:
        if self._stopping.is_set():
            raise BridgeError("Rubra is closing; provider login was cancelled.")
        try:
            result = self.embedded.login(provider, timeout=timeout)
            route = "webview2"
        except BridgeError as embedded_error:
            message = str(embedded_error)
            if "LOGIN_CANCELLED" in message or "LOGIN_CHALLENGE" in message:
                # Do not escalate anti-bot challenges into Playwright. Production challenge
                # systems intentionally reject automated browsers; preserve the WebView2
                # profile and leave the provider optional/retryable instead.
                raise
            if self._stopping.is_set():
                raise BridgeError("Rubra is closing; provider login was cancelled.") from embedded_error
            result = self.managed.login(provider, install_if_missing=True, timeout=timeout)
            route = "playwright"
        with self._route_lock:
            self._routes[provider] = route
            self._task_routes = {key: value for key, value in self._task_routes.items() if key[0] != provider}
        return result

    def prefer_local(self, provider: str) -> bool:
        if not self._can_use_local(provider):
            return False
        with self._route_lock:
            self._routes[provider] = "local"
            self._task_routes = {
                key: value for key, value in self._task_routes.items() if key[0] != provider
            }
        if self.status_callback is not None:
            self.status_callback(
                provider,
                "Ready",
                "Smart Routing moved this text role to the local model after the web route became unavailable.",
            )
        return True

    def release_task_route(self, task_id: str) -> None:
        with self._route_lock:
            self._task_routes = {key: value for key, value in self._task_routes.items() if key[1] != task_id}
            self._local_attachments = {
                key: value for key, value in self._local_attachments.items() if key[1] != task_id
            }

    def wait_for_provider(self, provider: str, timeout: float = 5.0) -> bool:
        return self._wait_for_provider(provider, timeout, allow_local=True)

    def wait_for_web_provider(self, provider: str, timeout: float = 5.0) -> bool:
        return self._wait_for_provider(provider, timeout, allow_local=False)

    def _wait_for_provider(self, provider: str, timeout: float, *, allow_local: bool) -> bool:
        if self._stopping.is_set():
            return False

        embedded_status = self.embedded.provider_status().get(provider, {})
        if self.embedded.running and str(embedded_status.get("state") or "").casefold() == "ready":
            with self._route_lock:
                self._routes[provider] = "webview2"
            return True
        managed_status = self.managed.provider_status().get(provider, {})
        if self.managed.running and str(managed_status.get("state") or "").casefold() == "ready":
            with self._route_lock:
                self._routes[provider] = "playwright"
            return True
        if self.allow_extension_fallback and self.extension is not None:
            extension_status = self.extension.provider_status().get(provider, {})
            if self.extension.running and str(extension_status.get("state") or "").casefold() in {"ready", "connected"}:
                with self._route_lock:
                    self._routes[provider] = "extension"
                return True

        if allow_local:
            with self._route_lock:
                existing_route = self._routes.get(provider)
            if existing_route == "local" and self._can_use_local(provider):
                return True

        budget = max(0.0, float(timeout))
        deadline = time.monotonic() + budget
        if budget > 0:
            first_budget = max(0.05, budget * 0.6)
            if self.embedded.wait_for_provider(provider, min(first_budget, max(0.05, deadline - time.monotonic()))):
                with self._route_lock:
                    self._routes[provider] = "webview2"
                return True
            remaining = deadline - time.monotonic()
            if remaining > 0 and self.managed.wait_for_provider(provider, remaining):
                with self._route_lock:
                    self._routes[provider] = "playwright"
                return True
            remaining = deadline - time.monotonic()
            if (
                remaining > 0
                and self.allow_extension_fallback
                and self.extension is not None
                and self.extension.wait_for_provider(provider, remaining)
            ):
                with self._route_lock:
                    self._routes[provider] = "extension"
                if self.status_callback is not None:
                    self.status_callback(provider, "Connected", "Extension fallback selected")
                return True

        if allow_local and self._can_use_local(provider):
            with self._route_lock:
                self._routes[provider] = "local"
            if self.status_callback is not None:
                self.status_callback(
                    provider, "Ready", "Local fallback; web provider is not currently authenticated"
                )
            return True
        return False

    def provider_status(self) -> dict[str, dict[str, str]]:
        managed = self.managed.provider_status()
        embedded = self.embedded.provider_status()
        extension = (
            self.extension.provider_status() if self.allow_extension_fallback and self.extension is not None else {}
        )
        with self._route_lock:
            routes = dict(self._routes)
        result: dict[str, dict[str, str]] = {}
        for provider in set(managed) | set(embedded) | set(extension) | set(routes):
            route = routes.get(provider)
            if route == "local" and self._can_use_local(provider):
                result[provider] = {
                    "state": "Ready",
                    "detail": "Local fallback; web provider is not currently authenticated",
                    "transport": "local",
                }
            elif route == "extension" and self.extension is not None and self.extension.running and provider in extension:
                result[provider] = dict(extension[provider])
            elif route == "webview2" and self.embedded.running and provider in embedded:
                result[provider] = dict(embedded[provider])
            elif route == "playwright" and self.managed.running and provider in managed:
                result[provider] = dict(managed[provider])
            else:
                live = (
                    (embedded.get(provider) if self.embedded.running else None)
                    or (managed.get(provider) if self.managed.running else None)
                    or (extension.get(provider) if self.extension is not None and self.extension.running else None)
                )
                if live:
                    result[provider] = dict(live)
                elif self._can_use_local(provider):
                    result[provider] = {
                        "state": "Ready",
                        "detail": "Local fallback; web provider is not currently authenticated",
                        "transport": "local",
                    }
                else:
                    result[provider] = {"state": "Off", "detail": "No live provider transport", "transport": ""}
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
        route = self._selected_route(provider)
        if route != "local":
            self._apply_selected_model(route, provider, task_id)
        if route == "local":
            if not self._can_use_local(provider) or self.local_complete is None:
                raise BridgeError("Local AI is unavailable. Install its runtime and model in Settings.")
            with self._route_lock:
                attachments = self._local_attachments.get((provider, task_id), "")
            role = (
                "Builder"
                if provider == "chatgpt"
                else "Reviewer: evaluate the supplied result independently and identify concrete defects"
            )
            try:
                text = self.local_complete(f"Role: {role}.\n{attachments}\n{prompt}")
            except Exception as exc:
                raise BridgeError(f"Local {role.split(':')[0]} failed: {exc}") from exc
            if not text.strip():
                raise BridgeError("Local model returned empty output.")
            if stream_callback is not None:
                stream_callback(text)
            return text
        if route == "playwright":
            if stream_callback is None:
                return self.managed.send_prompt(provider, prompt, task_id=task_id, timeout=timeout)
            return self.managed.send_prompt(
                provider,
                prompt,
                task_id=task_id,
                timeout=timeout,
                stream_callback=stream_callback,
            )
        if route == "webview2":
            if stream_callback is None:
                return self.embedded.send_prompt(provider, prompt, task_id=task_id, timeout=timeout)
            return self.embedded.send_prompt(
                provider,
                prompt,
                task_id=task_id,
                timeout=timeout,
                stream_callback=stream_callback,
            )
        if route == "extension" and self.allow_extension_fallback and self.extension is not None:
            return self.extension.send_prompt(provider, prompt, task_id=task_id, timeout=timeout)
        raise BridgeError(f"No authenticated internal route is available for {provider}.")

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
        if self._selected_route(provider) == "local":
            if action == "upload_files":
                parts = []
                for filename in payload.get("files", []):
                    path = Path(str(filename))
                    try:
                        valid = (
                            path.is_file()
                            and path.suffix.casefold()
                            in {".lua", ".luau", ".json", ".md", ".txt", ".toml", ".yaml", ".yml"}
                            and path.stat().st_size <= 40000
                        )
                    except OSError as exc:
                        raise BridgeError(f"Local attachment is unavailable: {path.name}") from exc
                    if not valid:
                        raise BridgeError(
                            "Local AI accepts existing small text/code attachments. Images and large files require a web provider."
                        )
                    try:
                        content = path.read_text(encoding="utf-8", errors="replace")
                    except OSError as exc:
                        raise BridgeError(f"Local attachment could not be read: {path.name}") from exc
                    parts.append(f"File: {path.name}\n{content}")
                combined = "\n".join(parts)
                if len(combined) > 40000:
                    raise BridgeError("Local attachments exceed the context budget.")
                with self._route_lock:
                    self._local_attachments[(provider, task_id)] = combined
                return {"status": "ok", "transport": "local"}
            if action == "get_models":
                return {"status": "ok", "models": ["auto"], "transport": "local"}
            if action == "capabilities":
                return {
                    "status": "ok",
                    "capabilities": {"send_prompt": True, "upload_files": True},
                    "transport": "local",
                }
            if action == "cancel":
                if self.local_cancel is not None:
                    self.local_cancel()
                return {"status": "idle", "cancelled": self.local_cancel is not None, "transport": "local"}
            raise BridgeError(f"Local route does not support {action}.")
        if provider == "hunyuan" and action in self._HUNYUAN_TRANSACTION_ACTIONS:
            route, capabilities = self._hunyuan_transaction_route(provider, task_id=task_id, timeout=timeout)
            if action in {"generate_geometry", "generate_texture"}:
                self._apply_selected_model(route, provider, task_id)
            if action == "capabilities":
                return {
                    "status": "ok",
                    "capabilities": capabilities,
                    "routes": {route: capabilities},
                    "transport": route,
                }
            return self._request_via_route(
                route,
                provider,
                action,
                payload,
                task_id=task_id,
                timeout=timeout,
                stream_callback=stream_callback,
            )
        if action == "capabilities":
            return self._combined_capabilities(provider, task_id=task_id, timeout=timeout)
        route = self._route_for_action(provider, action, task_id=task_id, timeout=timeout)
        return self._request_via_route(
            route,
            provider,
            action,
            payload,
            task_id=task_id,
            timeout=timeout,
            stream_callback=stream_callback,
        )

    def _request_via_route(
        self,
        route: str,
        provider: str,
        action: str,
        payload: dict[str, Any],
        *,
        task_id: str,
        timeout: float,
        stream_callback: Callable[[str], None] | None,
    ) -> dict[str, Any]:
        if route == "playwright":
            if stream_callback is None:
                return self.managed.request(provider, action, payload, task_id=task_id, timeout=timeout)
            return self.managed.request(
                provider,
                action,
                payload,
                task_id=task_id,
                timeout=timeout,
                stream_callback=stream_callback,
            )
        if route == "webview2":
            if stream_callback is None:
                return self.embedded.request(provider, action, payload, task_id=task_id, timeout=timeout)
            return self.embedded.request(
                provider,
                action,
                payload,
                task_id=task_id,
                timeout=timeout,
                stream_callback=stream_callback,
            )
        if route == "extension" and self.allow_extension_fallback and self.extension is not None:
            return self.extension.request(provider, action, payload, task_id=task_id, timeout=timeout)
        raise BridgeError(f"No authenticated internal route is available for {provider}.")

    def _hunyuan_transaction_route(
        self,
        provider: str,
        *,
        task_id: str,
        timeout: float,
    ) -> tuple[str, dict[str, Any]]:
        key = (provider, task_id)
        with self._route_lock:
            pinned = self._task_routes.get(key)
        if pinned:
            capabilities = self._route_capabilities(pinned, provider, task_id=task_id, timeout=timeout)
            if all(bool(capabilities.get(name)) for name in self._HUNYUAN_REQUIRED_CAPABILITIES):
                return pinned, capabilities
            raise BridgeError(
                "CAPABILITY_UNAVAILABLE: this task session lost a required capability; "
                "the route cannot change during the transaction."
            )

        selected = self._selected_route(provider)
        if selected == "extension":
            raise BridgeError(
                "CAPABILITY_UNAVAILABLE: the 3D provider requires one WebView2 or Playwright session "
                "with upload, geometry, and texture capabilities."
            )
        candidates = [selected]
        alternate = "playwright" if selected == "webview2" else "webview2"
        if self._route_ready(alternate, provider, timeout):
            candidates.append(alternate)
        for route in candidates:
            capabilities = self._route_capabilities(route, provider, task_id=task_id, timeout=timeout)
            if not all(bool(capabilities.get(name)) for name in self._HUNYUAN_REQUIRED_CAPABILITIES):
                continue
            with self._route_lock:
                self._task_routes[key] = route
                self._routes[provider] = route
            if self.status_callback is not None:
                self.status_callback(
                    provider,
                    "Routed",
                    f"Hunyuan transaction pinned to {'Playwright' if route == 'playwright' else 'WebView2'}",
                )
            return route, capabilities
        raise BridgeError(
            "CAPABILITY_UNAVAILABLE: the 3D provider needs one authenticated session with upload, "
            "geometry, and texture capabilities."
        )

    def _route_for_action(self, provider: str, action: str, *, task_id: str, timeout: float) -> str:
        route = self._selected_route(provider)
        capability = self._ACTION_CAPABILITIES.get(action)
        if capability is None or route == "extension":
            return route
        primary = self._route_capabilities(route, provider, task_id=task_id, timeout=timeout)
        if bool(primary.get(capability)):
            return route
        alternate = "playwright" if route == "webview2" else "webview2"
        if self._route_ready(alternate, provider, timeout):
            alternate_capabilities = self._route_capabilities(
                alternate,
                provider,
                task_id=task_id,
                timeout=timeout,
            )
            if bool(alternate_capabilities.get(capability)):
                if self.status_callback is not None:
                    self.status_callback(
                        provider,
                        "Routed",
                        f"{action} via {'Playwright' if alternate == 'playwright' else 'WebView2'}",
                    )
                return alternate
        raise BridgeError(
            f"CAPABILITY_UNAVAILABLE: {provider} did not expose {capability} through an authenticated route."
        )

    def _combined_capabilities(self, provider: str, *, task_id: str, timeout: float) -> dict[str, Any]:
        selected = self._selected_route(provider)
        routes: dict[str, dict[str, Any]] = {}
        if selected != "extension":
            routes[selected] = self._route_capabilities(selected, provider, task_id=task_id, timeout=timeout)
            alternate = "playwright" if selected == "webview2" else "webview2"
            if self._route_ready(alternate, provider, timeout):
                routes[alternate] = self._route_capabilities(
                    alternate,
                    provider,
                    task_id=task_id,
                    timeout=timeout,
                )
        merged: dict[str, Any] = {}
        for capabilities in routes.values():
            for key, value in capabilities.items():
                current = merged.get(key)
                if isinstance(value, bool):
                    merged[key] = bool(current) or value
                elif isinstance(value, int):
                    merged[key] = max(int(current or 0), value)
                elif isinstance(value, list):
                    existing = current if isinstance(current, list) else []
                    merged[key] = list(dict.fromkeys([*existing, *value]))
                elif key not in merged:
                    merged[key] = value
        return {
            "status": "ok",
            "capabilities": merged,
            "routes": routes,
            "transport": selected,
        }

    def _route_capabilities(
        self,
        route: str,
        provider: str,
        *,
        task_id: str,
        timeout: float,
    ) -> dict[str, Any]:
        try:
            if route == "playwright":
                result = self.managed.request(provider, "capabilities", {}, task_id=task_id, timeout=timeout)
            elif route == "webview2":
                result = self.embedded.request(provider, "capabilities", {}, task_id=task_id, timeout=timeout)
            else:
                return {}
        except BridgeError:
            return {}
        raw = result.get("capabilities")
        return dict(raw) if isinstance(raw, dict) else {}

    def _route_ready(self, route: str, provider: str, timeout: float) -> bool:
        probe_timeout = max(1.0, min(timeout, 20.0))
        if route == "playwright":
            return self.managed.wait_for_provider(provider, probe_timeout)
        if route == "webview2":
            return self.embedded.wait_for_provider(provider, probe_timeout)
        return False

    def _selected_route(self, provider: str) -> str:
        with self._route_lock:
            route = self._routes.get(provider)
            if route == "local" and not self._can_use_local(provider):
                self._routes.pop(provider, None)
                route = None
        if route:
            return route
        if not self.wait_for_provider(provider, 5.0):
            raise BridgeError(f"{provider} is not authenticated through an internal route.")
        with self._route_lock:
            return self._routes[provider]
