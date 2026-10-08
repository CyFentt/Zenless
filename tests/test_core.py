from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from zenless.browser_bridge import BridgeError
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

    def test_local_ai_state_does_not_report_failed_existing_model_as_installed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runtime = root / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "toolchain-results.json").write_text(
                json.dumps({
                    "qwen3-4b": {
                        "item_id": "qwen3-4b",
                        "state": "failed",
                        "detail": "SHA-256 mismatch",
                        "path": "",
                    }
                }),
                encoding="utf-8",
            )
            core = object.__new__(ZenlessCore)
            core.portable_root = root
            core.store = SQLiteStore(root / "state.db")
            core._settings_lock = threading.RLock()
            local_ai = Mock()
            local_ai.available = False
            local_ai.running = False
            local_ai.backend_label = "Local AI unavailable"
            local_ai.model_status.return_value = [
                {"id": "qwen3-4b", "name": "Qwen3-4B-Q4_K_M", "installed": True}
            ]
            core.local_ai = local_ai
            core._tools_state = {"state": "ERROR", "detail": "qwen3-4b failed"}

            state = core.local_ai_state()

            model = next(item for item in state["models"] if item["id"] == "qwen3-4b")
            self.assertFalse(model["installed"])
            self.assertEqual(model["state"], "failed")
            self.assertIn("SHA-256", model["detail"])

    def test_update_settings_rejects_non_numeric_revision_limit(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            core = object.__new__(ZenlessCore)
            core.store = SQLiteStore(Path(folder) / "state.db")
            core._settings_lock = threading.RLock()
            core.project_index = Mock()
            core.local_ai = Mock()
            core.events = EventBus()

            with self.assertRaises(CoreError) as raised:
                core.update_settings({"maxRevisions": "not-a-number"})

            self.assertEqual(raised.exception.code, "INVALID_MAX_REVISIONS")
            self.assertEqual(raised.exception.status, 400)

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

    def test_prompt_queue_is_durable_ordered_and_fail_closed_on_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "queue.db"
            store = SQLiteStore(path)
            first = store.enqueue_prompt("q1", "First", options={"review": False}, max_attempts=3)
            second = store.enqueue_prompt("q2", "Second", parent_job_id="job-parent", max_attempts=4)
            self.assertLess(first["position"], second["position"])
            store.update_prompt_queue_item("q1", state="preparing", attempts=1)
            recovered = store.recover_prompt_queue()
            self.assertEqual(recovered, ["q1"])

            reopened = SQLiteStore(path)
            items = reopened.prompt_queue_items()
            self.assertEqual([item["id"] for item in items], ["q1", "q2"])
            self.assertEqual(items[0]["state"], "sent_unconfirmed")
            self.assertIn("uncertain", items[0]["last_error"].casefold())
            self.assertEqual(items[0]["options"]["review"], False)
            self.assertEqual(items[1]["max_attempts"], 4)

    def test_prompt_queue_partial_reorder_preserves_unspecified_order(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "queue.db")
            for queue_id in ("q1", "q2", "q3", "q4"):
                store.enqueue_prompt(queue_id, queue_id)

            store.reorder_prompt_queue(["q3", "q1"])

            self.assertEqual(
                [item["id"] for item in store.prompt_queue_items()],
                ["q3", "q1", "q2", "q4"],
            )

    def test_prompt_queue_unconfirmed_delivery_requires_explicit_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            core = object.__new__(ZenlessCore)
            core.store = SQLiteStore(Path(folder) / "queue.db")
            core.events = EventBus()
            core._queue_wake = threading.Event()
            core._prompt_queue_config = lambda: {
                "paused": True,
                "continueOnFailure": False,
                "chainConversation": True,
                "delaySeconds": 2,
                "maxAttempts": 3,
            }
            core.store.enqueue_prompt("queue-uncertain", "Potentially sent")
            core.store.update_prompt_queue_item(
                "queue-uncertain",
                state="sent_unconfirmed",
                attempts=1,
                last_error="Delivery outcome is uncertain.",
            )

            confirmed = core.confirm_prompt_queue_item("queue-uncertain")
            self.assertEqual(confirmed["state"], "COMPLETED")

            core.store.update_prompt_queue_item(
                "queue-uncertain",
                state="sent_unconfirmed",
                attempts=1,
                last_error="Delivery outcome is uncertain.",
            )
            retried = core.retry_prompt_queue_item("queue-uncertain")
            self.assertEqual(retried["state"], "QUEUED")
            self.assertEqual(retried["attempts"], 0)
            self.assertEqual(retried["lastError"], "")

    def test_prompt_queue_audit_states_are_not_editable_or_movable(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            core = object.__new__(ZenlessCore)
            core.store = SQLiteStore(Path(folder) / "queue.db")
            core.events = EventBus()
            core._queue_wake = threading.Event()
            core.store.enqueue_prompt("queue-uncertain", "Potentially sent")
            core.store.enqueue_prompt("queue-next", "Next")
            core.store.update_prompt_queue_item("queue-uncertain", state="sent_unconfirmed")

            with self.assertRaises(CoreError) as edited:
                core.update_prompt_queue_item("queue-uncertain", content="Changed after send")
            self.assertEqual(edited.exception.code, "QUEUE_ITEM_NOT_EDITABLE")

            with self.assertRaises(CoreError) as moved:
                core.move_prompt_queue_item("queue-uncertain", 1)
            self.assertEqual(moved.exception.code, "QUEUE_ITEM_NOT_MOVABLE")

    def test_prompt_queue_live_missing_job_becomes_unconfirmed_and_pauses(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            core = object.__new__(ZenlessCore)
            core.store = SQLiteStore(Path(folder) / "queue.db")
            core.events = EventBus()
            core.orchestrator = Mock()
            core.orchestrator.current_task_id = ""
            core.store.enqueue_prompt("queue-live", "Potentially dispatched")
            core.store.update_prompt_queue_item(
                "queue-live",
                state="inflight",
                dispatched_job_id="missing-job",
                attempts=1,
            )

            core._prompt_queue_tick()

            item = core.store.prompt_queue_item("queue-live")
            self.assertIsNotNone(item)
            self.assertEqual(item["state"], "sent_unconfirmed")
            self.assertTrue(core._prompt_queue_config()["paused"])

    def test_prompt_queue_rejects_invalid_numeric_config(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            core = object.__new__(ZenlessCore)
            core.store = SQLiteStore(Path(folder) / "queue.db")
            core.events = EventBus()
            core._queue_wake = threading.Event()

            with self.assertRaises(CoreError) as delay:
                core.update_prompt_queue_config({"delaySeconds": "later"})
            self.assertEqual(delay.exception.code, "INVALID_QUEUE_DELAY")
            self.assertEqual(delay.exception.status, 400)

            with self.assertRaises(CoreError) as attempts:
                core.update_prompt_queue_config({"maxAttempts": "many"})
            self.assertEqual(attempts.exception.code, "INVALID_QUEUE_ATTEMPTS")
            self.assertEqual(attempts.exception.status, 400)

    def test_prompt_queue_cannot_resume_with_unconfirmed_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            core = object.__new__(ZenlessCore)
            core.store = SQLiteStore(Path(folder) / "queue.db")
            core.events = EventBus()
            core._queue_wake = threading.Event()
            core.store.set_setting(
                "prompt_queue.config",
                {
                    "paused": True,
                    "continueOnFailure": False,
                    "chainConversation": True,
                    "delaySeconds": 2,
                    "maxAttempts": 3,
                },
            )
            core.store.enqueue_prompt("queue-uncertain", "Potentially sent")
            core.store.update_prompt_queue_item(
                "queue-uncertain",
                state="sent_unconfirmed",
                attempts=1,
                last_error="Delivery outcome is uncertain.",
            )

            with self.assertRaises(CoreError) as raised:
                core.update_prompt_queue_config({"paused": False})

            self.assertEqual(raised.exception.code, "QUEUE_UNCONFIRMED_DELIVERY")
            self.assertTrue(core._prompt_queue_config()["paused"])

    def test_prompt_queue_tick_marks_missing_inflight_job_unconfirmed_and_pauses(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            core = object.__new__(ZenlessCore)
            core.store = SQLiteStore(Path(folder) / "queue.db")
            core.events = EventBus()
            core._queue_wake = threading.Event()
            core.orchestrator = Mock()
            core.orchestrator.current_task_id = ""
            core.store.set_setting(
                "prompt_queue.config",
                {
                    "paused": False,
                    "continueOnFailure": True,
                    "chainConversation": True,
                    "delaySeconds": 0,
                    "maxAttempts": 3,
                },
            )
            core.store.enqueue_prompt("queue-missing", "Potentially dispatched")
            core.store.update_prompt_queue_item(
                "queue-missing",
                state="inflight",
                dispatched_job_id="missing-job",
                attempts=1,
            )

            core._prompt_queue_tick()

            item = core.store.prompt_queue_item("queue-missing")
            self.assertEqual(item["state"], "sent_unconfirmed")
            self.assertTrue(core._prompt_queue_config()["paused"])
            self.assertIn("cannot be found", item["last_error"])

    def test_prompt_queue_unconfirmed_delivery_cannot_be_edited(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            core = object.__new__(ZenlessCore)
            core.store = SQLiteStore(Path(folder) / "queue.db")
            core.events = EventBus()
            core._queue_wake = threading.Event()
            core.store.enqueue_prompt("queue-uncertain", "Original")
            core.store.update_prompt_queue_item("queue-uncertain", state="sent_unconfirmed")

            with self.assertRaises(CoreError) as raised:
                core.update_prompt_queue_item("queue-uncertain", content="Different text")

            self.assertEqual(raised.exception.code, "QUEUE_ITEM_NOT_EDITABLE")
            self.assertEqual(core.store.prompt_queue_item("queue-uncertain")["content"], "Original")

    def test_prompt_queue_recovery_blocks_inflight_paused_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "queue.db")
            store.create_task("job-1", "Queued child", TaskOptions())
            store.update_task("job-1", stage=Stage.PAUSED, status="waiting")
            store.enqueue_prompt("queue-1", "Continue")
            store.update_prompt_queue_item(
                "queue-1",
                state="inflight",
                dispatched_job_id="job-1",
                attempts=1,
            )

            recovered = store.recover_prompt_queue()
            item = store.prompt_queue_item("queue-1")

            self.assertEqual(recovered, ["queue-1"])
            self.assertIsNotNone(item)
            self.assertEqual(item["state"], "blocked")
            self.assertIn("paused checkpoint", item["last_error"].casefold())
            self.assertEqual(item["dispatched_job_id"], "job-1")

    def test_prompt_queue_history_never_hides_new_pending_work(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "queue.db")
            for index in range(140):
                queue_id = f"done-{index:03d}"
                store.enqueue_prompt(queue_id, queue_id)
                store.update_prompt_queue_item(queue_id, state="completed")
            store.enqueue_prompt("pending-new", "Must remain visible")

            items = store.prompt_queue_items(128)

            self.assertIn("pending-new", [item["id"] for item in items])
            self.assertEqual(
                [item["id"] for item in items if item["state"] != "completed"],
                ["pending-new"],
            )
            self.assertLessEqual(
                len([item for item in items if item["state"] == "completed"]),
                128,
            )

    def test_prompt_queue_position_swap_does_not_reorder_terminal_history(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "queue.db")
            store.enqueue_prompt("done", "done")
            store.update_prompt_queue_item("done", state="completed")
            store.enqueue_prompt("one", "one")
            store.enqueue_prompt("two", "two")
            before_done = store.prompt_queue_item("done")["position"]

            store.swap_prompt_queue_positions("one", "two")

            self.assertEqual(store.prompt_queue_item("done")["position"], before_done)
            self.assertLess(
                store.prompt_queue_item("two")["position"],
                store.prompt_queue_item("one")["position"],
            )

    def test_prompt_queue_reorder_preserves_every_item_once(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "queue.db")
            for queue_id in ("one", "two", "three"):
                store.enqueue_prompt(queue_id, queue_id)
            store.reorder_prompt_queue(["three", "one", "two"])
            self.assertEqual(
                [item["id"] for item in store.prompt_queue_items()],
                ["three", "one", "two"],
            )

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

    def test_cancel_provider_login_preserves_session_and_returns_to_login_state(self) -> None:
        core = object.__new__(ZenlessCore)
        core._connections = {
            "bridge": "READY",
            "browser": "READY",
            "chatgpt": "OFF",
            "deepseek": "CONNECTING",
            "gemini": "OFF",
            "hunyuan": "OFF",
            "studio": "OFF",
        }
        core._connections_lock = threading.RLock()
        core.bridge = Mock()
        core.bridge.cancel_login.return_value = True
        core.events = EventBus()

        self.assertTrue(core.cancel_provider_login("deepseek"))

        self.assertEqual(core._connections["deepseek"], "LOGIN")
        event = core.events.recent()[-1]
        self.assertEqual(event.type, "AGENT_STATUS_CHANGED")
        self.assertEqual(event.data["agent"], "deepseek")
        self.assertEqual(event.data["status"], "LOGIN")

    def test_connections_do_not_downgrade_active_login_to_login_required(self) -> None:
        core = object.__new__(ZenlessCore)
        core._closing = threading.Event()
        core._connections = {
            "bridge": "READY",
            "browser": "READY",
            "chatgpt": "OFF",
            "deepseek": "CONNECTING",
            "gemini": "OFF",
            "hunyuan": "OFF",
            "studio": "OFF",
        }
        core._connections_lock = threading.RLock()
        core._provider_threads = {"deepseek": Mock()}
        core._provider_threads["deepseek"].is_alive.return_value = True
        core.bridge = Mock()
        core.bridge.provider_status.return_value = {
            "deepseek": {"state": "Login Required", "detail": "manual login"}
        }

        result = core.connections()

        self.assertEqual(result["deepseek"], "CONNECTING")

    def test_frontend_diagnostic_is_bounded_and_forwarded_to_error_bus(self) -> None:
        core = object.__new__(ZenlessCore)
        core.diagnostics = Mock()
        payload = {
            "severity": "error",
            "source": "window",
            "component": "react",
            "message": "Render failed",
            "file": "app.tsx",
            "line": 42,
            "function": "Widget",
            "stack": "x" * 25000,
            "requestId": "request-1",
        }

        self.assertTrue(core.report_frontend_diagnostic(payload))

        kwargs = core.diagnostics.report.call_args.kwargs
        self.assertEqual(kwargs["severity"], "ERROR")
        self.assertEqual(kwargs["source"], "window")
        self.assertEqual(kwargs["file_name"], "app.tsx")
        self.assertEqual(kwargs["line_number"], 42)
        self.assertEqual(kwargs["function_name"], "Widget")
        self.assertEqual(len(kwargs["stack_trace"]), 20000)
        self.assertEqual(kwargs["request_id"], "request-1")

    def test_degraded_provider_status_is_visible_in_diagnostics_without_invalidating_login(self) -> None:
        core = object.__new__(ZenlessCore)
        core._connections = {"chatgpt": "READY"}
        core._connections_lock = threading.RLock()
        core._provider_lock = threading.Lock()
        core._provider_threads = {}
        core.events = Mock()
        core.diagnostics = Mock()

        core._on_provider_status(
            "chatgpt",
            "Degraded",
            "Provider cooling down for 30s after repeated transient failures.",
        )

        self.assertEqual(core._connections["chatgpt"], "CONNECTING")
        core.diagnostics.report.assert_called_once()
        kwargs = core.diagnostics.report.call_args.kwargs
        self.assertEqual(kwargs["severity"], "WARNING")
        self.assertEqual(kwargs["source"], "chatgpt")
        self.assertIn("cooling down", kwargs["message"])

    def test_provider_refresh_does_not_end_active_login_early(self) -> None:
        core = object.__new__(ZenlessCore)
        core._connections = {
            "bridge": "READY",
            "browser": "READY",
            "chatgpt": "OFF",
            "deepseek": "CONNECTING",
            "gemini": "OFF",
            "hunyuan": "OFF",
            "studio": "OFF",
        }
        core._connections_lock = threading.RLock()
        core._provider_lock = threading.Lock()
        login_thread = Mock()
        login_thread.is_alive.return_value = True
        core._provider_threads = {"deepseek": login_thread}
        core.bridge = Mock()
        core.bridge.provider_status.return_value = {
            "deepseek": {"state": "Login Required", "detail": "manual login"},
        }
        core._set_boot = Mock()

        core._refresh_provider_states()

        self.assertEqual(core._connections["deepseek"], "CONNECTING")
        core._set_boot.assert_called_once_with("AI", "OFF")

    def test_provider_status_event_does_not_end_active_login_early(self) -> None:
        core = object.__new__(ZenlessCore)
        core._connections = {"deepseek": "CONNECTING"}
        core._connections_lock = threading.RLock()
        core._provider_lock = threading.Lock()
        login_thread = Mock()
        login_thread.is_alive.return_value = True
        core._provider_threads = {"deepseek": login_thread}
        core.events = Mock()
        core.diagnostics = Mock()

        core._on_provider_status(
            "deepseek",
            "Login Required",
            "Anti-bot challenge is active; complete it manually.",
        )

        self.assertEqual(core._connections["deepseek"], "CONNECTING")
        event = core.events.publish.call_args
        self.assertEqual(event.args[0], "AGENT_STATUS_CHANGED")
        self.assertEqual(event.args[1]["status"], "CONNECTING")

    def test_login_challenge_returns_provider_to_login_attention_state(self) -> None:
        core = object.__new__(ZenlessCore)
        core._connections = {"deepseek": "OFF"}
        core._connections_lock = threading.RLock()
        core._closing = threading.Event()
        core.events = Mock()
        core.bridge = Mock()
        core.bridge.login.side_effect = BridgeError("LOGIN_CHALLENGE: verification loop")
        core._report = Mock()

        core._login_worker("deepseek")

        self.assertEqual(core._connections["deepseek"], "LOGIN")
        statuses = [
            call.args[1]["status"]
            for call in core.events.publish.call_args_list
            if call.args and call.args[0] == "AGENT_STATUS_CHANGED"
        ]
        self.assertEqual(statuses, ["CONNECTING", "LOGIN"])
        core._report.assert_called_once()

    def test_stop_test_reconciles_provider_state_without_cancelling_login_sessions(self) -> None:
        core = object.__new__(ZenlessCore)
        core.qa = Mock()
        core.qa.stop.return_value = True
        core.orchestrator = Mock()
        core._refresh_provider_states = Mock()

        self.assertTrue(core.stop_test("job-test"))

        core.qa.wait_for_manual_tests.assert_called_once_with(3.0)
        core._refresh_provider_states.assert_called_once_with()
        core.orchestrator.cancel.assert_not_called()

    def test_chat_rejects_empty_json_request_without_attachments(self) -> None:
        core = object.__new__(ZenlessCore)

        with self.assertRaises(CoreError) as raised:
            core.send_chat("   ", None, (), None)

        self.assertEqual(raised.exception.code, "EMPTY_MESSAGE")

    def test_chat_returns_prepared_message_identity_without_post_start_message_read(self) -> None:
        core = object.__new__(ZenlessCore)
        core.settings = lambda: json.loads(json.dumps(ZenlessCore.DEFAULT_SETTINGS))
        core._preflight_providers = Mock()
        core._create_job = Mock(return_value=({"id": "job"}, 41))
        core.messages = Mock(side_effect=AssertionError("post-start message read"))

        result = core.send_chat("Continue", None, (), None)

        self.assertEqual(result, {"messageId": "msg-41", "jobId": "job"})
        core.messages.assert_not_called()

    def test_job_snapshot_is_prepared_before_submit_returns(self) -> None:
        core = object.__new__(ZenlessCore)
        core.orchestrator = Mock()
        core._studio_target_id = ""
        core.connections = Mock(return_value={"studio": "OFF"})
        timeline: list[str] = []
        core.job = Mock(side_effect=lambda task_id: timeline.append("snapshot") or {"id": task_id})

        def submit(_title, _options, **kwargs):
            timeline.append("submit")
            kwargs["ready_callback"]("job", 9)
            timeline.append("return")
            return "job"

        core.orchestrator.submit.side_effect = submit
        job, message_id = core._create_job("Build")

        self.assertEqual(job, {"id": "job"})
        self.assertEqual(message_id, 9)
        self.assertEqual(timeline, ["submit", "snapshot", "return"])

    def test_recovery_pauses_pre_mutation_work_and_blocks_uncertain_writes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "state.db")
            store.create_task("planning", "Plan", TaskOptions())
            store.create_task("applying", "Apply", TaskOptions())
            store.update_task("planning", stage=Stage.PLANNING, status="running")
            store.update_task("applying", stage=Stage.APPLYING, status="running")
            store.create_test_run("run-applying", "applying", "STANDARD", 7)

            recovered = {item["id"]: item for item in store.recover_interrupted_tasks()}

            self.assertEqual(recovered["planning"]["stage"], Stage.PAUSED.value)
            self.assertEqual(recovered["applying"]["stage"], Stage.BLOCKED.value)
            self.assertIn("Safe recovery", recovered["applying"]["reason"])
            recovered_run = store.latest_test_run("applying")
            self.assertIsNotNone(recovered_run)
            self.assertEqual(recovered_run["status"], "CANCELLED")
            self.assertTrue(recovered_run["summary"]["recovered"])

    def test_orphan_running_test_is_cancelled_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "state.db")
            store.create_task("done-task", "Already done", TaskOptions())
            store.update_task("done-task", stage=Stage.COMPLETE, status="complete")
            store.create_test_run("orphan-run", "done-task", "STANDARD", 3)

            recovered = store.recover_running_test_runs()

            self.assertEqual(recovered, ["orphan-run"])
            run = store.latest_test_run("done-task")
            self.assertIsNotNone(run)
            self.assertEqual(run["status"], "CANCELLED")
            self.assertTrue(run["summary"]["recovered"])

    def test_pending_idempotent_operations_fail_closed_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "state.db")
            claimed = store.claim_operation("chat-op-12345678", "chat", "")
            self.assertTrue(claimed["claimed"])
            self.assertEqual(claimed["state"], "pending")

            recovered = store.recover_pending_operations()

            self.assertEqual(recovered, ["chat-op-12345678"])
            operation = store.operation("chat-op-12345678")
            self.assertIsNotNone(operation)
            self.assertEqual(operation["state"], "uncertain")
            self.assertEqual(operation["response"]["code"], "IDEMPOTENCY_UNCERTAIN")

    def test_operation_history_pruning_keeps_recent_uncertain_operations(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "state.db")
            for index in range(140):
                key = f"done-op-{index:08d}"
                store.claim_operation(key, "chat", "")
                store.finish_operation(key, "complete", {"ok": True})
            store.claim_operation("uncertain-op-12345678", "chat", "")
            store.recover_pending_operations()

            removed = store.prune_operations(128)

            self.assertGreaterEqual(removed, 12)
            uncertain = store.operation("uncertain-op-12345678")
            self.assertIsNotNone(uncertain)
            self.assertEqual(uncertain["state"], "uncertain")

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
        self.assertEqual(raised.exception.details["provider"], "chatgpt")
        self.assertEqual(raised.exception.details["alternatives"], ["gemini", "local"])
        self.assertEqual(core.connections()["chatgpt"], "LOGIN")

    def test_preflight_smart_routing_accepts_gemini_when_chatgpt_and_local_are_unavailable(self) -> None:
        core = object.__new__(ZenlessCore)
        bridge = Mock()
        bridge.wait_for_provider.side_effect = lambda provider, timeout=0.0: provider == "gemini"
        core.bridge = bridge
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

        core._preflight_providers(
            TaskOptions(create_3d_asset=False, independent_review=False, smart_routing=True)
        )

        self.assertEqual(core._connections["gemini"], "READY")
        self.assertEqual(
            [call.args[0] for call in bridge.wait_for_provider.call_args_list],
            ["chatgpt", "gemini"],
        )

    def test_preflight_research_on_with_smart_routing_does_not_require_gemini(self) -> None:
        core = object.__new__(ZenlessCore)
        bridge = Mock()
        bridge.wait_for_provider.side_effect = lambda provider, timeout=0.0: provider == "chatgpt"
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

        core._preflight_providers(
            TaskOptions(
                create_3d_asset=False,
                independent_review=False,
                smart_routing=True,
                research_mode="on",
            )
        )

        self.assertFalse(any(call.args and call.args[0] == "gemini" for call in bridge.wait_for_provider.call_args_list))

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
