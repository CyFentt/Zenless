from __future__ import annotations

import json
import tempfile
import threading
import unittest
from unittest.mock import Mock
from pathlib import Path

from zenless.core import CoreError, ZenlessCore
from zenless.event_bus import EventBus
from zenless.models import PipelineEvent, Stage, TaskOptions
from zenless.protocol import ProtocolError, extract_json_object, make_envelope, parse_envelope
from zenless.store import SQLiteStore


class CoreTests(unittest.TestCase):
    def test_partial_legacy_model_settings_keep_defaults_and_new_providers(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            core = object.__new__(ZenlessCore)
            core.store = SQLiteStore(Path(folder) / "state.db")
            core.store.set_setting("ui.settings", {"models": {"chatgpt": {"model": "chosen"}}})
            settings = core.settings()
            self.assertEqual(settings["models"]["chatgpt"]["model"], "chosen")
            for provider in ("deepseek", "gemini", "hunyuan"):
                self.assertEqual(settings["models"][provider], core.DEFAULT_SETTINGS["models"][provider])
            settings["models"]["gemini"]["model"] = "modified"
            self.assertNotEqual(core.settings()["models"]["gemini"]["model"], "modified")

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
        self.assertEqual(options.max_revisions, 64)
        self.assertEqual(options.max_test_fixes, 3)

    def test_task_options_normalize_routing_and_approval_modes(self) -> None:
        options = TaskOptions.from_api(
            {
                "approvalMode": "SAFE_AUTO",
                "effort": "MAX",
                "research": "ON",
                "smartRouting": False,
                "continuousVerification": True,
            }
        )
        self.assertTrue(options.require_approval)
        self.assertEqual(options.approval_mode, "safe_auto")
        self.assertEqual(options.effort_level, "max")
        self.assertEqual(options.research_mode, "on")
        self.assertFalse(options.smart_routing)
        self.assertTrue(options.continuous_verification)

        legacy = TaskOptions.from_api({"approval": False})
        self.assertFalse(legacy.require_approval)
        self.assertEqual(legacy.approval_mode, "full_auto")

    def test_task_options_parse_string_booleans_explicitly(self) -> None:
        options = TaskOptions.from_api({
            "visualFirst": "false",
            "create3D": "0",
            "review": "false",
            "autoTest": "off",
            "autoFix": "no",
            "continuousVerification": "false",
            "smartRouting": "false",
            "approval": "false",
        })
        self.assertFalse(options.visual_first)
        self.assertFalse(options.create_3d_asset)
        self.assertFalse(options.independent_review)
        self.assertFalse(options.automatic_play_test)
        self.assertFalse(options.auto_fix_errors)
        self.assertFalse(options.continuous_verification)
        self.assertFalse(options.smart_routing)
        self.assertEqual(options.approval_mode, "full_auto")


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

    def test_file_assets_are_scoped_to_their_job_and_survive_other_job_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            core = object.__new__(ZenlessCore)
            core.data_root = root
            core.store = SQLiteStore(root / "state.db")
            core.store.create_task("job-a", "A", TaskOptions())
            core.store.create_task("job-b", "B", TaskOptions())
            attachment = root / "shared.rbxm"
            attachment.write_bytes(b"same attachment")

            first = core._register_file_asset(attachment, job_id="job-a", kind="RBX")
            second = core._register_file_asset(attachment, job_id="job-b", kind="RBX")

            self.assertNotEqual(first, second)
            self.assertEqual(len(core.store.assets("job-a")), 1)
            self.assertEqual(len(core.store.assets("job-b")), 1)
            self.assertTrue(core.store.delete_task("job-b"))
            self.assertEqual(len(core.store.assets("job-a")), 1)
            self.assertEqual(core.store.assets("job-b"), [])

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

    def test_recovered_checkpoint_resume_restarts_as_child_job(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            core = object.__new__(ZenlessCore)
            core.store = SQLiteStore(Path(folder) / "state.db")
            core.store.create_task("parent", "Continue safely", TaskOptions())
            core.store.update_task("parent", stage=Stage.PLANNING, status="running")
            recovered = core.store.recover_interrupted_tasks()
            self.assertTrue(recovered[0]["reason"].startswith("RECOVERED_CHECKPOINT:"))

            core.orchestrator = Mock()
            core.orchestrator.resume.return_value = False
            core.orchestrator.submit.return_value = "child"
            core.job = Mock(return_value={"id": "child"})

            result = core.resume_job("parent")

            self.assertEqual(result, {"id": "child"})
            self.assertEqual(core.orchestrator.submit.call_args.kwargs["parent_task_id"], "parent")
            parent = core.store.load_task("parent")
            self.assertEqual(parent["stage"], Stage.BLOCKED.value)
            self.assertIn("child", parent["error"])

    def test_recovered_checkpoint_can_be_cancelled_without_live_worker(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            core = object.__new__(ZenlessCore)
            core.store = SQLiteStore(Path(folder) / "state.db")
            core.store.create_task("recovered", "Recover", TaskOptions())
            core.store.update_task("recovered", stage=Stage.PLANNING, status="running")
            core.store.recover_interrupted_tasks()
            core.qa = Mock()
            core.qa.stop.return_value = False
            core.orchestrator = Mock()
            core.orchestrator.cancel.return_value = False

            self.assertTrue(core.cancel_job("recovered"))

            task = core.store.load_task("recovered")
            self.assertEqual(task["stage"], Stage.BLOCKED.value)
            self.assertEqual(task["status"], "blocked")
            self.assertIn("cancelled", task["error"].casefold())


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
            "gemini": "OFF",
            "hunyuan": "OFF",
            "studio": "OFF",
        }

        with self.assertRaises(CoreError) as raised:
            core._preflight_providers(TaskOptions(create_3d_asset=False, independent_review=False))

        self.assertEqual(raised.exception.code, "PROVIDER_LOGIN_REQUIRED")
        self.assertEqual(raised.exception.details, {"provider": "chatgpt"})
        self.assertEqual(core.connections()["chatgpt"], "LOGIN")

    def test_preflight_smart_routing_off_requires_web_even_if_local_is_ready(self) -> None:
        core = object.__new__(ZenlessCore)
        bridge = Mock()
        bridge.wait_for_provider.return_value = True
        bridge.wait_for_web_provider.return_value = False
        core.bridge = bridge
        core.events = EventBus()
        core._connections_lock = threading.RLock()
        core._connections = {
            "bridge": "READY",
            "browser": "READY",
            "chatgpt": "READY",
            "deepseek": "OFF",
            "gemini": "OFF",
            "hunyuan": "OFF",
            "studio": "OFF",
        }

        with self.assertRaises(CoreError) as raised:
            core._preflight_providers(
                TaskOptions(create_3d_asset=False, independent_review=False, smart_routing=False)
            )

        self.assertEqual(raised.exception.code, "PROVIDER_LOGIN_REQUIRED")
        bridge.wait_for_web_provider.assert_called_once_with("chatgpt", 0.5)
        bridge.wait_for_provider.assert_not_called()

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
