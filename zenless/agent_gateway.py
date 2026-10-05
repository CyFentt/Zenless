from __future__ import annotations

import threading
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
        result = self._request_via_route(route, provider, "select_model", {"model": model},
                                        task_id=task_id, timeout=20, stream_callback=None)
        if result.get("status") != "ok" or not result.get("selected"):
            raise BridgeError(f"The selected {provider} model could not be confirmed: {model}")

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
            if "LOGIN_CANCELLED" in str(embedded_error):
                raise
            if self._stopping.is_set():
                raise BridgeError("Rubra is closing; provider login was cancelled.") from embedded_error
            result = self.managed.login(provider, install_if_missing=True, timeout=timeout)
            route = "playwright"
        with self._route_lock:
            self._routes[provider] = route
            self._task_routes = {key: value for key, value in self._task_routes.items() if key[0] != provider}
        return result

    def release_task_route(self, task_id: str) -> None:
        with self._route_lock:
            self._task_routes = {key: value for key, value in self._task_routes.items() if key[1] != task_id}
            self._local_attachments = {
                key: value for key, value in self._local_attachments.items() if key[1] != task_id
            }

    def wait_for_provider(self, provider: str, timeout: float = 5.0) -> bool:
        if self._stopping.is_set():
            return False
        budget = max(0.0, float(timeout))
        deadline = time.monotonic() + budget
        with self._route_lock:
            selected = self._routes.get(provider)
        if selected == "local" and self._can_use_local(provider):
            return True
        if selected in {"webview2", "playwright"}:
            if self._route_ready(selected, provider, budget):
                return True
            with self._route_lock:
                if self._routes.get(provider) == selected:
                    self._routes.pop(provider, None)
        elif selected == "extension" and self.allow_extension_fallback and self.extension is not None:
            if self.extension.wait_for_provider(provider, budget):
                return True
            with self._route_lock:
                if self._routes.get(provider) == selected:
                    self._routes.pop(provider, None)

        def remaining() -> float:
            return max(0.0, deadline - time.monotonic())

        # Existing authenticated web sessions win over the local fallback.
        for route in ("webview2", "playwright"):
            if self._route_ready(route, provider, 0.0):
                with self._route_lock:
                    self._routes[provider] = route
                return True

        for index, route in enumerate(("webview2", "playwright")):
            left = remaining()
            if left <= 0:
                break
            share = left / (2 - index)
            if self._route_ready(route, provider, share):
                with self._route_lock:
                    self._routes[provider] = route
                return True

        if self.allow_extension_fallback and self.extension is not None:
            if self.extension.wait_for_provider(provider, remaining()):
                with self._route_lock:
                    self._routes[provider] = "extension"
                if self.status_callback is not None:
                    self.status_callback(provider, "Connected", "Extension fallback selected")
                return True

        if self._can_use_local(provider):
            with self._route_lock:
                self._routes[provider] = "local"
            if self.status_callback is not None:
                self.status_callback(
                    provider, "Ready", "Local model fallback; no authenticated web route is available"
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
        for provider in set(managed) | set(embedded) | set(extension):
            route = routes.get(provider)
            if route == "extension" and provider in extension:
                result[provider] = dict(extension[provider])
            elif route == "webview2" and provider in embedded:
                result[provider] = dict(embedded[provider])
            elif route == "playwright" and provider in managed:
                result[provider] = dict(managed[provider])
            else:
                result[provider] = dict(
                    embedded.get(provider) or managed.get(provider) or extension.get(provider) or {}
                )
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
        selected_route = self._selected_route(provider)
        if selected_route == "local" and action == "select_model":
            route = self._web_route_for_capability(
                provider, "select_model", task_id=task_id, timeout=timeout
            )
            with self._route_lock:
                self._routes[provider] = route
            return self._request_via_route(
                route,
                provider,
                action,
                payload,
                task_id=task_id,
                timeout=timeout,
                stream_callback=stream_callback,
            )
        if selected_route == "local":
            if action == "upload_files":
                parts = []
                for filename in payload.get("files", []):
                    path = Path(str(filename))
                    if (
                        path.suffix.casefold()
                        not in {".lua", ".luau", ".json", ".md", ".txt", ".toml", ".yaml", ".yml"}
                        or path.stat().st_size > 40000
                    ):
                        raise BridgeError(
                            "Local AI accepts small text/code attachments. Images and large files require a web provider."
                        )
                    parts.append(f"File: {path.name}\n{path.read_text(encoding='utf-8')}")
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

    def _web_route_for_capability(
        self,
        provider: str,
        capability: str,
        *,
        task_id: str,
        timeout: float,
    ) -> str:
        deadline = time.monotonic() + max(0.0, timeout)
        routes = ("webview2", "playwright")
        for route in routes:
            if not self._route_ready(route, provider, 0.0):
                continue
            capabilities = self._route_capabilities(route, provider, task_id=task_id, timeout=max(0.1, timeout))
            if bool(capabilities.get(capability)):
                return route
        for index, route in enumerate(routes):
            remaining = max(0.0, deadline - time.monotonic())
            if remaining <= 0:
                break
            share = remaining / (len(routes) - index)
            if not self._route_ready(route, provider, share):
                continue
            capabilities = self._route_capabilities(
                route,
                provider,
                task_id=task_id,
                timeout=max(0.1, max(0.0, deadline - time.monotonic())),
            )
            if bool(capabilities.get(capability)):
                return route
        raise BridgeError(
            f"CAPABILITY_UNAVAILABLE: {provider} requires an authenticated web route for {capability}."
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
        probe_timeout = max(0.0, min(float(timeout), 20.0))
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
