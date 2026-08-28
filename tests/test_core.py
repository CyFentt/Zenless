from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

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
        value = extract_json_object("texto\n```json\n{\"ok\": true, \"items\": [1]}\n```\nfim")
        self.assertEqual(value, {"ok": True, "items": [1]})

    def test_sqlite_round_trip_and_parallel_writes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "state.db")
            task_id = "task-sqlite"
            options = TaskOptions()
            store.create_task(task_id, "Teste", options)

            failures: list[Exception] = []

            def writer(index: int) -> None:
                try:
                    for item in range(10):
                        store.set_setting(f"worker.{index}.{item}", {"value": item})
                except Exception as exc:  # pragma: no cover - assertion captures it
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
            store.create_task("planning", "Planeje", TaskOptions())
            store.create_task("applying", "Aplique", TaskOptions())
            store.update_task("planning", stage=Stage.PLANNING, status="running")
            store.update_task("applying", stage=Stage.APPLYING, status="running")

            recovered = {item["id"]: item for item in store.recover_interrupted_tasks()}

            self.assertEqual(recovered["planning"]["stage"], Stage.PAUSED.value)
            self.assertEqual(recovered["applying"]["stage"], Stage.BLOCKED.value)
            self.assertIn("Recuperação segura", recovered["applying"]["reason"])


if __name__ == "__main__":
    unittest.main()
