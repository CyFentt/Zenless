from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from zenless.agent_gateway import AgentGateway
from zenless.brain import ZenlessBrain
from zenless.components import WEBVIEW2_BOOTSTRAPPER_SHA256, WebView2Runtime
from zenless.diagnostics import ErrorBus
from zenless.discord_integration import DiscordIntegration
from zenless.managed_browser import BrowserRuntimeManager
from zenless.models import TaskOptions
from zenless.storage import StorageManager
from zenless.store import SQLiteStore


class FakeTransport:
    def __init__(self, ready: set[str] | None = None) -> None:
        self.ready = ready or set()
        self.sent: list[tuple[str, str]] = []
        self.running = True

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def wait_for_provider(self, provider: str, timeout: float = 0.0) -> bool:
        return provider in self.ready

    def send_prompt(self, provider: str, prompt: str, *, task_id: str, timeout: float = 360.0) -> str:
        self.sent.append((provider, prompt))
        return f"{provider}:{prompt}"

    def request(
        self,
        provider: str,
        action: str,
        payload: dict[str, Any],
        *,
        task_id: str,
        timeout: float,
    ) -> dict[str, Any]:
        self.sent.append((provider, action))
        return {"status": "ok", "text": action}

    def provider_status(self) -> dict[str, dict[str, str]]:
        return {
            provider: {"state": "Ready", "detail": "test", "transport": "fake"}
            for provider in self.ready
        }


class FakeManaged(FakeTransport):
    def login(self, provider: str, *, install_if_missing: bool = True, timeout: float = 180.0) -> dict[str, Any]:
        self.ready.add(provider)
        return {"state": "ready"}


class FakeEmbedded(FakeManaged):
    pass


class HardeningTests(unittest.TestCase):
    def test_webview2_bootstrapper_integrity_gate(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            installer = Path(folder) / "MicrosoftEdgeWebview2Setup.exe"
            installer.write_bytes(b"tampered")
            with self.assertRaises(RuntimeError):
                WebView2Runtime.verify_installer(installer)
            self.assertEqual(len(WEBVIEW2_BOOTSTRAPPER_SHA256), 64)

    def test_brain_routes_without_local_model_and_deduplicates(self) -> None:
        brain = ZenlessBrain()
        analysis = brain.analyze(
            "Corrija o erro do servidor e teste a UI 3D",
            independent_review=True,
            create_3d=True,
        )
        self.assertIn("debug", analysis.intents)
        self.assertIn("3d", analysis.intents)
        self.assertEqual(analysis.providers, ("chatgpt", "deepseek", "hunyuan"))
        self.assertEqual(brain.deduplicate([{"a": 1}, {"a": 1}, {"a": 2}]), [{"a": 1}, {"a": 2}])

    @settings(max_examples=50, deadline=None)
    @given(st.text(max_size=500))
    def test_brain_analysis_is_total_and_bounded(self, objective: str) -> None:
        analysis = ZenlessBrain().analyze(objective)
        self.assertEqual(len(analysis.fingerprint), 32)
        self.assertLessEqual(len(analysis.keywords), 16)
        self.assertIn("chatgpt", analysis.providers)

    def test_store_compacts_provider_transcripts_and_retains_recent_messages(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "zenless.db")
            task_id = "compact-task"
            store.create_task(task_id, "compact", TaskOptions())
            huge = "x" * 80_000
            store.append_message(task_id, "Provider", "agent", huge)
            for index in range(60):
                store.append_message(task_id, "Provider", "agent", str(index))
            messages = store.task_messages(task_id)
            self.assertEqual(len(messages), store.MAX_MESSAGES_PER_TASK)
            self.assertEqual(messages[-1]["content"], "59")

            second = "compact-task-2"
            store.create_task(second, "compact", TaskOptions())
            store.append_message(second, "Provider", "agent", huge)
            compacted = store.task_messages(second)[0]["content"]
            self.assertIn("ZENLESS COMPACTED", compacted)
            self.assertLessEqual(len(compacted), store.MAX_MESSAGE_CHARS + 200)

    def test_storage_cleanup_never_traverses_profile_auth_state(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manager = StorageManager(root)
            stale = manager.temp_root / "old.tmp"
            stale.write_text("temporary", encoding="utf-8")
            old_time = time.time() - 3 * 24 * 60 * 60
            os.utime(stale, (old_time, old_time))
            cookie = root / "browser-profile" / "Default" / "Cookies"
            cookie.parent.mkdir(parents=True)
            cookie.write_text("auth-state", encoding="utf-8")
            removed, _ = manager.cleanup_temporary(older_than_seconds=60)
            self.assertEqual(removed, 1)
            self.assertFalse(stale.exists())
            self.assertEqual(cookie.read_text(encoding="utf-8"), "auth-state")

    def test_diagnostics_redacts_and_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            bus = ErrorBus(Path(folder))
            event = bus.report(
                severity="ERROR",
                source="test",
                component="redaction",
                message="token=super-secret https://discord.com/api/webhooks/123/abcdef",
            )
            again = bus.report(
                severity="ERROR",
                source="test",
                component="redaction",
                message="token=super-secret https://discord.com/api/webhooks/123/abcdef",
            )
            self.assertIs(event, again)
            self.assertEqual(event.occurrence_count, 2)
            self.assertNotIn("super-secret", event.message)
            self.assertNotIn("abcdef", event.message)
            bus.close()

    def test_discord_is_optional(self) -> None:
        integration = DiscordIntegration()
        self.assertFalse(integration.enabled)
        self.assertFalse(integration.notify_async("title", "message"))
        self.assertEqual(integration.status().state, "Not Configured")

    def test_gateway_prefers_webview2_then_playwright_then_extension(self) -> None:
        managed = FakeManaged({"chatgpt"})
        embedded = FakeEmbedded({"chatgpt"})
        extension = FakeTransport({"chatgpt", "deepseek"})
        gateway = AgentGateway(  # type: ignore[arg-type]
            managed=managed,
            embedded=embedded,
            extension=extension,
            allow_extension_fallback=True,
        )
        self.assertTrue(gateway.wait_for_provider("chatgpt", 2))
        self.assertEqual(gateway.send_prompt("chatgpt", "hello", task_id="1"), "chatgpt:hello")
        self.assertEqual(embedded.sent, [("chatgpt", "hello")])
        self.assertFalse(managed.sent)
        self.assertFalse(extension.sent)
        self.assertTrue(gateway.wait_for_provider("deepseek", 2))
        gateway.send_prompt("deepseek", "review", task_id="1")
        self.assertEqual(extension.sent, [("deepseek", "review")])

    def test_gateway_does_not_require_extension_by_default(self) -> None:
        gateway = AgentGateway(  # type: ignore[arg-type]
            managed=FakeManaged(set()),
            embedded=FakeEmbedded(set()),
            extension=FakeTransport({"chatgpt"}),
        )
        self.assertFalse(gateway.wait_for_provider("chatgpt", 1))

    def test_runtime_manager_detects_only_full_chromium(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            manager = BrowserRuntimeManager(Path(folder))
            self.assertFalse(manager.installed)
            executable = Path(folder) / "chromium-123" / "chrome-win64" / "chrome.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"test")
            self.assertEqual(manager.chromium_executable(), executable)


if __name__ == "__main__":
    unittest.main()
