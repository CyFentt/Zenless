from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zenless.agent_gateway import AgentGateway
from zenless.browser_bridge import BridgeError
from zenless.core import ZenlessCore
from zenless.event_bus import EventBus
from zenless.managed_browser import ManagedBrowserController, ProviderSpec
from zenless.native_host import write_native_message
from zenless.provider_sessions import ProviderSessionMetadata
from zenless.webview2_browser import WebView2BrowserController, _Pending
from zenless.webview_host import WebViewHost


class _GatewayTransport:
    def __init__(self, data_root: Path, transport: str, *, fail: bool = False) -> None:
        self.data_root = data_root
        self.profile_root = data_root / transport
        self.transport = transport
        self.fail = fail
        self.running = True

    def login(
        self,
        provider: str,
        *,
        timeout: float,
        install_if_missing: bool = True,
        on_window_opened=None,
    ) -> dict[str, str]:
        if self.fail:
            raise BridgeError(f"{self.transport} unavailable")
        if on_window_opened is not None:
            on_window_opened(provider, self.transport)
        return {"state": "ready"}


class _HostWindow:
    def __init__(self) -> None:
        self.steps: list[str] = []

    def evaluate_js(self, _script: str) -> object:
        if not self.steps:
            self.steps.append("page_loaded")
            return "complete"
        self.steps.append("auth_checked")
        return {"state": "AUTHENTICATED", "ready": True}

    def show(self) -> None:
        self.steps.append("shown")

    def restore(self) -> None:
        self.steps.append("restored")

    def hide(self) -> None:
        self.steps.append("hidden")

    def get_current_url(self) -> str:
        return "https://provider.test/"


class _NeverStops:
    def wait(self, _timeout: float) -> bool:
        return False

    def is_set(self) -> bool:
        return False


class _CoreLoginBridge:
    def __init__(self, events: EventBus) -> None:
        self.events = events

    def login(self, provider: str, *, timeout: float, on_window_opened=None) -> dict[str, str]:
        published = [event.type for event in self.events.recent()]
        if "LOGIN_WINDOW_OPENED" in published:
            raise AssertionError("Login opened was published before the provider window existed")
        if on_window_opened is not None:
            on_window_opened(provider, "webview2")
        return {"state": "ready"}

    @staticmethod
    def selected_route(_provider: str) -> str:
        return "webview2"


class ProviderSessionContractTests(unittest.TestCase):
    def test_public_metadata_does_not_expose_profile_path(self) -> None:
        profile_path = r"C:\Users\Private\provider-profile"
        public = ProviderSessionMetadata(provider_id="chatgpt", profile_path=profile_path).public()

        self.assertNotIn("profilePath", public)
        self.assertNotIn(profile_path, public.values())


class LoginWindowContractTests(unittest.TestCase):
    def test_core_publishes_opened_only_from_transport_callback(self) -> None:
        core = object.__new__(ZenlessCore)
        core.events = EventBus()
        core.bridge = _CoreLoginBridge(core.events)
        core._set_connection = lambda *_args: None
        core._set_boot = lambda *_args: None

        core._login_worker("chatgpt")

        events = [event for event in core.events.recent() if event.type.startswith("LOGIN_")]
        self.assertEqual(
            [event.type for event in events],
            [
                "LOGIN_REQUIRED",
                "LOGIN_WINDOW_WILL_OPEN",
                "LOGIN_WINDOW_OPENED",
                "LOGIN_DETECTED",
                "LOGIN_PERSISTENCE_VERIFYING",
                "LOGIN_READY",
            ],
        )
        self.assertEqual(events[2].data, {"providerId": "chatgpt", "route": "webview2"})

    def test_gateway_forwards_callback_to_route_that_opens(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            embedded = _GatewayTransport(root, "webview2", fail=True)
            managed = _GatewayTransport(root, "playwright")
            gateway = AgentGateway(managed=managed, embedded=embedded)
            opened: list[tuple[str, str]] = []

            result = gateway.login("chatgpt", timeout=1, on_window_opened=lambda *args: opened.append(args))

        self.assertEqual(result["state"], "ready")
        self.assertEqual(opened, [("chatgpt", "playwright")])

    def test_managed_callback_runs_after_open_command_returns(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            controller = ManagedBrowserController(data_root=Path(folder))
            order: list[str] = []

            def open_page(*_args, **_kwargs) -> dict[str, str]:
                order.append("page_opened")
                with controller._state_lock:
                    controller._states["chatgpt"]["state"] = "Ready"
                return {"state": "login_window_open"}

            def opened(_provider: str, _transport: str) -> None:
                self.assertEqual(order, ["page_opened"])
                order.append("callback")

            with patch.object(controller, "_call", side_effect=open_page):
                result = controller.login("chatgpt", timeout=1, on_window_opened=opened)

        self.assertEqual(result["state"], "ready")
        self.assertEqual(order, ["page_opened", "callback"])

    def test_native_host_emits_opened_after_show_and_restore(self) -> None:
        spec = ProviderSpec("chatgpt", "https://provider.test/", (), (), (), ())
        source = io.BytesIO()
        target = io.BytesIO()
        host = WebViewHost(
            profile_root=Path("profile"),
            provider_specs={"chatgpt": spec},
            source=source,
            target=target,
        )
        window = _HostWindow()
        host._windows["chatgpt"] = window
        host._stop = _NeverStops()
        opened: list[tuple[str, dict[str, object], list[str]]] = []

        def on_event(event: str, payload: dict[str, object]) -> None:
            opened.append((event, payload, list(window.steps)))

        with patch("zenless.webview_host.time.monotonic", side_effect=[0.0, 1.0, 2.0, 4.1]):
            result = host._handle(
                {"action": "login", "provider": "chatgpt", "payload": {"timeout": 30}},
                event_callback=on_event,
            )

        self.assertEqual(result["state"], "ready")
        self.assertEqual(opened[0][0], "login_window_opened")
        self.assertEqual(opened[0][1]["transport"], "webview2")
        self.assertEqual(opened[0][2], ["page_loaded", "shown", "restored"])

    def test_webview_controller_delivers_native_opened_event_once(self) -> None:
        stream = io.BytesIO()
        lock = threading.Lock()
        event = {"id": "request", "event": "login_window_opened", "provider": "chatgpt"}
        result = {"id": "request", "ok": True, "result": {"state": "ready"}}
        for message in (event, event, result):
            write_native_message(stream, json.dumps(message).encode("utf-8"), lock)
        stream.seek(0)
        controller = WebView2BrowserController(data_root=Path("data"))
        controller._process = SimpleNamespace(stdout=stream)
        opened: list[tuple[str, str]] = []
        pending = _Pending(
            provider="chatgpt",
            window_opened_callback=lambda *args: opened.append(args),
        )
        controller._pending["request"] = pending

        controller._read_loop()

        self.assertEqual(opened, [("chatgpt", "webview2")])
        self.assertTrue(pending.event.is_set())


if __name__ == "__main__":
    unittest.main()
