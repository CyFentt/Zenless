from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zenless.browser_bridge import BridgeError
from zenless.core import CoreError, ZenlessCore
from zenless.event_bus import EventBus
from zenless.managed_browser import ManagedBrowserController, _Command
from zenless.provider_registry import BUILTIN_MANIFESTS, ProviderRegistry, normalize_capabilities
from zenless.store import SQLiteStore


class _ModePage:
    def __init__(self) -> None:
        self.payload: dict[str, object] = {}
        self.waited = False

    def evaluate(self, _script: str, payload: dict[str, object]) -> dict[str, bool]:
        self.payload = payload
        return {"ok": True, "changed": True}

    def wait_for_timeout(self, _milliseconds: int) -> None:
        self.waited = True


class _ModeBridge:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.selections: list[tuple[str, str]] = []

    def request(self, provider: str, action: str, payload: dict[str, str], **_kwargs) -> dict[str, object]:
        self.calls.append((provider, action, payload))
        if self.fail:
            raise BridgeError("mode control unavailable")
        return {"status": "ok", "capabilities": {"supportsReasoning": payload["mode"] == "expert"}}

    def update_selection(self, provider: str, *, model: str = "", mode: str = "") -> None:
        self.selections.append((provider, mode))


class ProviderModeTests(unittest.TestCase):
    def test_live_capability_contract_exposes_mode_selection(self) -> None:
        capabilities = normalize_capabilities(
            {"send_text": True, "select_mode": True, "reasoning": True, "mode": "expert"}
        )

        self.assertTrue(capabilities["select_mode"])
        self.assertTrue(capabilities["supportsReasoning"])
        self.assertEqual(capabilities["mode"], "expert")

    def test_managed_mode_change_requires_verified_result(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            controller = ManagedBrowserController(data_root=Path(folder))
            page = _ModePage()
            controller._ensure_page = lambda _provider: page
            controller._capabilities = lambda _page, _spec: {"mode": "expert", "supportsReasoning": True}

            result = controller._select_mode(_Command("request", "deepseek", {"mode": "expert"}))

        self.assertEqual(result["selected"], "expert")
        self.assertTrue(page.waited)
        self.assertEqual(page.payload["labels"], ["expert"])

    def test_core_persists_mode_only_after_live_change(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            core = object.__new__(ZenlessCore)
            core.provider_registry = ProviderRegistry(BUILTIN_MANIFESTS)
            core.store = SQLiteStore(Path(folder) / "state.db")
            core.events = EventBus()
            core.bridge = _ModeBridge()
            core.provider = lambda provider_id, refresh=False: {"providerId": provider_id, "refresh": refresh}

            result = core.select_provider("deepseek", {"mode": "expert"})

        self.assertEqual(result, {"providerId": "deepseek", "refresh": True})
        self.assertEqual(core.bridge.calls, [("deepseek", "select_mode", {"mode": "expert"})])
        self.assertEqual(core.bridge.selections, [("deepseek", "expert")])

    def test_core_does_not_persist_unverified_mode(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            core = object.__new__(ZenlessCore)
            core.provider_registry = ProviderRegistry(BUILTIN_MANIFESTS)
            core.store = SQLiteStore(Path(folder) / "state.db")
            core.events = EventBus()
            core.bridge = _ModeBridge(fail=True)

            with self.assertRaises(CoreError) as raised:
                core.select_provider("deepseek", {"mode": "expert"})

            self.assertEqual(raised.exception.code, "PROVIDER_MODE_UNAVAILABLE")
            self.assertEqual(core.store.get_setting("provider.selections", {}), {})


if __name__ == "__main__":
    unittest.main()
