from __future__ import annotations

import threading
from typing import Any

from .browser_bridge import BridgeError, BrowserBridge, StatusCallback
from .managed_browser import ManagedBrowserController
from .webview2_browser import WebView2BrowserController


class AgentGateway:
    """Embedded WebView2 first and Playwright only when a capability needs it."""

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
        self._route_lock = threading.Lock()
        self._stopping = threading.Event()

    @property
    def running(self) -> bool:
        return self.managed.running or self.embedded.running or bool(self.extension and self.extension.running)

    def start(self) -> None:
        self._stopping.clear()
        try:
            self.managed.start()
        except BridgeError as exc:
            # WebView2 remains independently available and is started lazily.
            if self.status_callback is not None:
                self.status_callback("browser", "Degraded", str(exc))
        if self.allow_extension_fallback and self.extension is not None:
            self.extension.start()

    def stop(self) -> None:
        self._stopping.set()
        self.managed.stop()
        self.embedded.stop()
        if self.extension is not None:
            self.extension.stop()

    def login(self, provider: str, *, timeout: float = 180.0) -> dict[str, Any]:
        if self._stopping.is_set():
            raise BridgeError("Zenless is closing; provider login was cancelled.")
        try:
            result = self.embedded.login(provider, timeout=timeout)
            route = "webview2"
        except BridgeError as embedded_error:
            if self._stopping.is_set():
                raise BridgeError("Zenless is closing; provider login was cancelled.") from embedded_error
            result = self.managed.login(provider, install_if_missing=True, timeout=timeout)
            route = "playwright"
        with self._route_lock:
            self._routes[provider] = route
        return result

    def wait_for_provider(self, provider: str, timeout: float = 5.0) -> bool:
        if self._stopping.is_set():
            return False
        embedded_timeout = max(1.0, min(timeout, 20.0))
        if self.embedded.wait_for_provider(provider, embedded_timeout):
            with self._route_lock:
                self._routes[provider] = "webview2"
            return True
        managed_timeout = max(1.0, min(timeout, 15.0))
        if self.managed.wait_for_provider(provider, managed_timeout):
            with self._route_lock:
                self._routes[provider] = "playwright"
            return True
        if self.allow_extension_fallback and self.extension is not None and self.extension.wait_for_provider(
            provider, max(0.0, timeout - managed_timeout - embedded_timeout)
        ):
            with self._route_lock:
                self._routes[provider] = "extension"
            if self.status_callback is not None:
                self.status_callback(provider, "Connected", "Extension fallback selected")
            return True
        return False

    def provider_status(self) -> dict[str, dict[str, str]]:
        managed = self.managed.provider_status()
        embedded = self.embedded.provider_status()
        extension = self.extension.provider_status() if self.allow_extension_fallback and self.extension is not None else {}
        with self._route_lock:
            routes = dict(self._routes)
        result: dict[str, dict[str, str]] = {}
        for provider in set(managed) | set(embedded) | set(extension):
            route = routes.get(provider)
            if route == "extension" and provider in extension:
                result[provider] = dict(extension[provider])
            elif route == "webview2" and provider in embedded:
                result[provider] = dict(embedded[provider])
            else:
                result[provider] = dict(embedded.get(provider) or managed.get(provider) or extension.get(provider) or {})
        return result

    def send_prompt(self, provider: str, prompt: str, *, task_id: str, timeout: float = 360.0) -> str:
        route = self._selected_route(provider)
        if route == "playwright":
            return self.managed.send_prompt(provider, prompt, task_id=task_id, timeout=timeout)
        if route == "webview2":
            return self.embedded.send_prompt(provider, prompt, task_id=task_id, timeout=timeout)
        if route == "extension" and self.allow_extension_fallback and self.extension is not None:
            return self.extension.send_prompt(provider, prompt, task_id=task_id, timeout=timeout)
        raise BridgeError(f"Nenhuma rota interna autenticada para {provider}.")

    def request(
        self,
        provider: str,
        action: str,
        payload: dict[str, Any],
        *,
        task_id: str,
        timeout: float,
    ) -> dict[str, Any]:
        route = self._selected_route(provider)
        if route == "playwright":
            return self.managed.request(provider, action, payload, task_id=task_id, timeout=timeout)
        if route == "webview2":
            return self.embedded.request(provider, action, payload, task_id=task_id, timeout=timeout)
        if route == "extension" and self.allow_extension_fallback and self.extension is not None:
            return self.extension.request(provider, action, payload, task_id=task_id, timeout=timeout)
        raise BridgeError(f"Nenhuma rota interna autenticada para {provider}.")

    def _selected_route(self, provider: str) -> str:
        with self._route_lock:
            route = self._routes.get(provider)
        if route:
            return route
        if not self.wait_for_provider(provider, 5.0):
            raise BridgeError(f"{provider} não está autenticado no WebView2 nem no Playwright interno.")
        with self._route_lock:
            return self._routes[provider]
