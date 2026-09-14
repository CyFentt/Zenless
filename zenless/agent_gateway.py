from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .browser_bridge import BridgeError, BrowserBridge, LoginWindowOpenedCallback, StatusCallback
from .managed_browser import ManagedBrowserController
from .provider_registry import normalize_capabilities
from .provider_sessions import ProviderSessionStore
from .webview2_browser import WebView2BrowserController


class AgentGateway:
    _ACTION_CAPABILITIES = {
        "upload_files": "upload_files",
        "select_model": "select_model",
        "select_mode": "select_mode",
        "get_models": "select_model",
        "cancel": "cancel",
        "generate_image": "supportsImageGeneration",
        "generate_3d": "supports3DGeneration",
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
        data_root = getattr(managed, "data_root", None)
        self._route_state_path: Path | None = Path(data_root) / "provider-routes.json" if data_root else None
        self._session_store = ProviderSessionStore(Path(data_root) / "provider-sessions.json") if data_root else None
        self._routes.update(self._load_routes())

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
            self._task_routes.clear()
        self.managed.stop()
        self.embedded.stop()
        if self.extension is not None:
            self.extension.stop()

    def login(
        self,
        provider: str,
        *,
        timeout: float = 180.0,
        on_window_opened: LoginWindowOpenedCallback | None = None,
    ) -> dict[str, Any]:
        if self._stopping.is_set():
            raise BridgeError("Zenless is closing; provider login was cancelled.")
        try:
            result = self.embedded.login(provider, timeout=timeout, on_window_opened=on_window_opened)
            route = "webview2"
        except BridgeError as embedded_error:
            if self._stopping.is_set():
                raise BridgeError("Zenless is closing; provider login was cancelled.") from embedded_error
            result = self.managed.login(
                provider,
                install_if_missing=True,
                timeout=timeout,
                on_window_opened=on_window_opened,
            )
            route = "playwright"
        self._set_route(provider, route, clear_tasks=True)
        self._mark_ready(provider, route)
        return result

    def release_task_route(self, task_id: str) -> None:
        with self._route_lock:
            self._task_routes = {key: value for key, value in self._task_routes.items() if key[1] != task_id}

    def wait_for_provider(self, provider: str, timeout: float = 5.0) -> bool:
        if self._stopping.is_set():
            return False
        with self._route_lock:
            preferred = self._routes.get(provider)
        routes = [preferred] if preferred in {"webview2", "playwright"} else []
        routes.extend(route for route in ("webview2", "playwright") if route not in routes)
        probe_timeout = max(1.0, min(timeout, 20.0))
        for route in routes:
            ready = (
                self.embedded.wait_for_provider(provider, probe_timeout)
                if route == "webview2"
                else self.managed.wait_for_provider(provider, probe_timeout)
            )
            if ready:
                self._set_route(provider, route)
                self._mark_ready(provider, route)
                return True
        if (
            self.allow_extension_fallback
            and self.extension is not None
            and self.extension.wait_for_provider(provider, max(0.0, timeout))
        ):
            self._set_route(provider, "extension")
            if self.status_callback is not None:
                self.status_callback(provider, "Connected", "Extension fallback selected")
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
            managed_ready = self._status_ready(managed.get(provider))
            embedded_ready = self._status_ready(embedded.get(provider))
            active_status = embedded.get(provider) if route == "webview2" else managed.get(provider)
            active_failure = self._status_availability_failure(active_status)
            if route == "webview2" and not active_failure and not embedded_ready and managed_ready:
                route = "playwright"
                self._set_route(provider, route)
            elif route == "playwright" and not active_failure and not managed_ready and embedded_ready:
                route = "webview2"
                self._set_route(provider, route)
            if route == "extension" and provider in extension:
                result[provider] = dict(extension[provider])
            elif route == "webview2" and provider in embedded:
                result[provider] = dict(embedded[provider])
            elif route == "playwright" and provider in managed:
                result[provider] = dict(managed[provider])
            else:
                result[provider] = dict(
                    (managed.get(provider) if managed_ready else None)
                    or (embedded.get(provider) if embedded_ready else None)
                    or embedded.get(provider)
                    or managed.get(provider)
                    or extension.get(provider)
                    or {}
                )
            result[provider]["route"] = route or ""
            if route and self._status_ready(result[provider]):
                self._mark_ready(provider, route)
            elif self._session_store is not None:
                state = str(result[provider].get("state") or "UNKNOWN").strip().replace(" ", "_").upper()
                self._session_store.mark_health(provider, state)
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
        if provider == "hunyuan" and action in self._HUNYUAN_TRANSACTION_ACTIONS:
            route, capabilities = self._hunyuan_transaction_route(provider, task_id=task_id, timeout=timeout)
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
            self._set_route(provider, route)
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
        normalized = normalize_capabilities(dict(raw) if isinstance(raw, dict) else {})
        if self._session_store is not None:
            self._session_store.update_capabilities(provider, normalized)
        return normalized

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
        if route:
            return route
        if not self.wait_for_provider(provider, 5.0):
            raise BridgeError(f"{provider} is not authenticated through an internal route.")
        with self._route_lock:
            return self._routes[provider]

    def select_route(self, provider: str, route: str) -> None:
        if provider not in self.managed.provider_specs or route not in {"webview2", "playwright"}:
            raise BridgeError("Invalid provider route selection.")
        self._set_route(provider, route, clear_tasks=True)

    def selected_route(self, provider: str) -> str:
        with self._route_lock:
            return self._routes.get(provider, "")

    def session_metadata(self, provider: str) -> dict[str, str]:
        if self._session_store is None:
            return {"providerId": provider, "healthState": "UNKNOWN"}
        return self._session_store.get(provider).public()

    def update_selection(self, provider: str, *, model: str = "", mode: str = "") -> None:
        if self._session_store is not None:
            self._session_store.update_selection(provider, model=model, mode=mode)

    def _set_route(self, provider: str, route: str, *, clear_tasks: bool = False) -> None:
        with self._route_lock:
            unchanged = self._routes.get(provider) == route
            self._routes[provider] = route
            if clear_tasks:
                self._task_routes = {key: value for key, value in self._task_routes.items() if key[0] != provider}
            snapshot = dict(self._routes)
        if unchanged:
            return
        self._persist_routes(snapshot)

    def _mark_ready(self, provider: str, route: str) -> None:
        if self._session_store is None or route not in {"playwright", "webview2"}:
            return
        controller = self.managed if route == "playwright" else self.embedded
        profile = getattr(controller, "profile_root", None)
        profile_path = Path(profile).name if profile else ""
        self._session_store.mark_ready(provider, route, profile_path)

    def _load_routes(self) -> dict[str, str]:
        if self._route_state_path is None:
            return {}
        try:
            raw = json.loads(self._route_state_path.read_text(encoding="utf-8"))
        except OSError, UnicodeError, json.JSONDecodeError:
            return {}
        if not isinstance(raw, dict):
            return {}
        providers = set(self.managed.provider_specs)
        return {
            str(provider): str(route)
            for provider, route in raw.items()
            if provider in providers and route in {"webview2", "playwright"}
        }

    def _persist_routes(self, routes: dict[str, str]) -> None:
        if self._route_state_path is None:
            return
        self._route_state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._route_state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(routes, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        temporary.replace(self._route_state_path)

    @staticmethod
    def _status_ready(status: dict[str, str] | None) -> bool:
        return str((status or {}).get("state", "")).casefold() in {
            "ready",
            "connected",
        }

    @staticmethod
    def _status_availability_failure(status: dict[str, str] | None) -> bool:
        return str((status or {}).get("state", "")).strip().replace("_", " ").casefold() in {
            "rate limited",
            "quota exhausted",
            "model unavailable",
            "temp unavailable",
            "temporarily unavailable",
        }
