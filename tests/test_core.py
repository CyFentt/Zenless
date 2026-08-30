from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from zenless.core import CoreError, ZenlessCore
from zenless.event_bus import EventBus
from zenless.models import PipelineEvent, Stage, TaskOptions
from zenless.protocol import ProtocolError, extract_json_object, make_envelope, parse_envelope
from zenless.store import SQLiteStore


class CoreTests(unittest.TestCase):
    def test_task_options_are_bounded_and_typed(self) -> None:
        options = TaskOptions.from_ui(
            {
                "Visual First": 1,
                "Create 3D Asset": 0,
                "Max Revisions": "99",
                "Max Test Fixes": "invalid",
            }
        )
        self.assertTrue(options.visual_first)
        self.assertFalse(options.create_3d_asset)
        self.assertEqual(options.max_revisions, 5)
        self.assertEqual(options.max_test_fixes, 3)

    def test_3d_option_forces_visual_first_but_non_3d_can_skip_it(self) -> None:
        model = TaskOptions.from_api({"visualFirst": False, "create3D": True})
        plain = TaskOptions.from_api({"visualFirst": False, "create3D": False})
        self.assertTrue(model.visual_first)
        self.assertFalse(plain.visual_first)

    def test_protocol_round_trip_and_rejects_unknown_source(self) -> None:
        original = make_envelope(
            "agent.command",
            source="zenless",
            provider="chatgpt",
            payload={"action": "send_prompt"},
            task_id="task-1",
        )
        parsed = parse_envelope(original.to_json())
        self.assertEqual(parsed, original)
        bad = original.to_dict()
        bad["source"] = "internet"
        with self.assertRaises(ProtocolError):
            parse_envelope(json.dumps(bad))

    def test_extract_json_from_markdown(self) -> None:
        value = extract_json_object('text\n```json\n{"ok": true, "items": [1]}\n```\nend')
        self.assertEqual(value, {"ok": True, "items": [1]})

    def test_sqlite_round_trip_and_parallel_writes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "state.db")
            task_id = "task-sqlite"
            options = TaskOptions()
            store.create_task(task_id, "Test", options)

            failures: list[Exception] = []

            def writer(index: int) -> None:
                try:
                    for item in range(10):
                        store.set_setting(f"worker.{index}.{item}", {"value": item})
                except Exception as exc:
                    failures.append(exc)

            workers = [threading.Thread(target=writer, args=(index,)) for index in range(6)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(10)

            self.assertFalse(failures)
            store.update_task(task_id, stage=Stage.TESTING, status="running", context_json={"live": True})
            store.append_event(PipelineEvent(task_id, Stage.TESTING, "Play", created_at="2026-01-01T00:00:00+00:00"))
            loaded = store.load_task(task_id)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["stage"], Stage.TESTING.value)
            self.assertEqual(loaded["context"], {"live": True})
            self.assertEqual(len(store.task_events(task_id)), 1)

    def test_recovery_pauses_pre_mutation_work_and_blocks_uncertain_writes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "state.db")
            store.create_task("planning", "Plan", TaskOptions())
            store.create_task("applying", "Apply", TaskOptions())
            store.update_task("planning", stage=Stage.PLANNING, status="running")
            store.update_task("applying", stage=Stage.APPLYING, status="running")

            recovered = {item["id"]: item for item in store.recover_interrupted_tasks()}

            self.assertEqual(recovered["planning"]["stage"], Stage.PAUSED.value)
            self.assertEqual(recovered["applying"]["stage"], Stage.BLOCKED.value)
            self.assertIn("Safe recovery", recovered["applying"]["reason"])

    def test_provider_preflight_returns_structured_login_requirement(self) -> None:
        core = object.__new__(ZenlessCore)
        core.bridge = _ProviderBridge(set())
        core.events = EventBus()
        core._connections_lock = threading.RLock()
        core._connections = {
            "bridge": "READY",
            "browser": "READY",
            "chatgpt": "OFF",
            "deepseek": "OFF",
            "hunyuan": "OFF",
            "studio": "OFF",
        }

        with self.assertRaises(CoreError) as raised:
            core._preflight_providers(TaskOptions(create_3d_asset=False, independent_review=False))

        self.assertEqual(raised.exception.code, "PROVIDER_LOGIN_REQUIRED")
        self.assertEqual(raised.exception.details, {"provider": "chatgpt"})
        self.assertEqual(core.connections()["chatgpt"], "LOGIN")

    def test_blocked_pipeline_event_publishes_persisted_chat_error(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            core = object.__new__(ZenlessCore)
            core.store = SQLiteStore(Path(folder) / "state.db")
            core.events = EventBus()
            core.store.create_task("blocked", "Build", TaskOptions())
            core.store.update_task("blocked", stage=Stage.BLOCKED, status="blocked", error="Builder requires login.")
            core.store.append_message("blocked", "Runtime", "error", "Builder requires login.")

            core._on_pipeline_event(PipelineEvent("blocked", Stage.BLOCKED, "Builder requires login."))

            messages = [event.data["message"] for event in core.events.recent() if event.type == "CHAT_MESSAGE"]
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0]["id"], "msg-1")
            self.assertEqual(messages[0]["role"], "system")
            self.assertEqual(messages[0]["action"], {"type": "LOGIN", "provider": "chatgpt"})


class _ProviderBridge:
    def __init__(self, ready: set[str]) -> None:
        self.ready = ready

    def wait_for_provider(self, provider: str, timeout: float = 0.0) -> bool:
        return provider in self.ready


if __name__ == "__main__":
    unittest.main()
