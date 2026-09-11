from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from zenless.event_bus import EventBus
from zenless.models import TaskOptions
from zenless.qa_breaker import QABreaker
from zenless.qa_breaker import TestPlan as _TestPlan
from zenless.store import SQLiteStore


class QAPersistenceTests(unittest.TestCase):
    def test_qa_planner_and_reviewer_follow_provider_role_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "state.db")
            store.create_task("job-qa", "Verify movement", TaskOptions())
            store.set_setting("provider.roles", {"deepseek": ["BUILDER"], "chatgpt": ["REVIEWER"]})
            bridge = Mock()
            bridge.wait_for_provider.return_value = True
            bridge.send_prompt.side_effect = ['{"scenarios":["Verify movement"]}', "Review completed"]
            qa = QABreaker(store=store, studio=Mock(), bridge=bridge, events=EventBus())

            scenarios = qa._ai_scenarios("job-qa", "Verify movement", [], [])
            review = qa._review_results(
                "job-qa", _TestPlan("SMOKE", "Movement", [], [], [], [], 1), [], "", False
            )

            self.assertEqual(scenarios, ["Verify movement"])
            self.assertEqual(review, "Review completed")
            self.assertEqual([call.args[0] for call in bridge.wait_for_provider.call_args_list], ["deepseek", "chatgpt"])
            self.assertEqual([call.args[0] for call in bridge.send_prompt.call_args_list], ["deepseek", "chatgpt"])

    def test_reopen_restores_normalized_test_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.db"
            store = SQLiteStore(path)
            store.create_task("job-1", "Verify movement", TaskOptions())
            store.create_test_run("run-1", "job-1", "STANDARD", 17)
            store.append_test_case(
                "case-1",
                run_id="run-1",
                job_id="job-1",
                name="Movement remains authoritative",
                suite="PLAY",
                status="FAILED",
                severity="MEDIUM",
                details={"expected": "Server validates movement", "actual": "Validation failed"},
                duration_ms=25,
                started_at=1_000,
                finished_at=1_025,
            )
            store.append_test_failure(
                "failure-1",
                run_id="run-1",
                job_id="job-1",
                test_case_id="case-1",
                name="Movement remains authoritative",
                suite="PLAY",
                severity="MEDIUM",
                message="Validation failed",
                details={
                    "file": "ServerScriptService/Movement",
                    "line": 12,
                    "stack": "stack",
                    "expected": "Server validates movement",
                    "actual": "Validation failed",
                    "cause": "PLAY",
                    "recovery": "Repair and rerun",
                },
                timestamp=1_025,
            )
            store.append_test_log(
                "log-1",
                run_id="run-1",
                job_id="job-1",
                level="ERR",
                message="Movement remains authoritative: FAILED",
                timestamp=1_025,
                test_case_id="case-1",
            )
            store.finish_test_run("run-1", "FAILED", {"durationMs": 25})

            snapshot = SQLiteStore(path).test_snapshot("job-1")

            self.assertEqual(snapshot["run"]["jobId"], "job-1")
            self.assertEqual(snapshot["run"]["status"], "FAILED")
            self.assertNotIn("job_id", snapshot["run"])
            self.assertEqual(
                snapshot["cases"][0],
                {
                    "id": "case-1",
                    "runId": "run-1",
                    "jobId": "job-1",
                    "name": "Movement remains authoritative",
                    "suite": "PLAY",
                    "status": "FAILED",
                    "startedAt": 1_000,
                    "finishedAt": 1_025,
                    "durationMs": 25,
                },
            )
            failure = snapshot["failures"][0]
            self.assertEqual(failure["runId"], "run-1")
            self.assertEqual(failure["jobId"], "job-1")
            self.assertEqual(failure["testCaseId"], "case-1")
            self.assertEqual(failure["expected"], "Server validates movement")
            self.assertEqual(failure["actual"], "Validation failed")
            log = snapshot["logs"][0]
            self.assertEqual(log["runId"], "run-1")
            self.assertEqual(log["jobId"], "job-1")
            self.assertEqual(log["testCaseId"], "case-1")

    def test_existing_test_case_table_is_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.db"
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE test_cases (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                """
            )
            connection.close()

            store = SQLiteStore(path)

            migrated = sqlite3.connect(path)
            case_columns = {row[1] for row in migrated.execute("PRAGMA table_info(test_cases)")}
            tables = {row[0] for row in migrated.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            migrated.close()
            self.assertTrue({"suite", "started_at_ms", "finished_at_ms"}.issubset(case_columns))
            self.assertTrue({"test_failures", "test_logs"}.issubset(tables))
            self.assertEqual(store.test_snapshot("missing"), {"run": None, "cases": [], "failures": [], "logs": []})

    def test_authoritative_outcomes_distinguish_skipped_and_not_run(self) -> None:
        cases = (
            ([], "NOT_RUN"),
            (["SKIPPED", "SKIPPED"], "SKIPPED"),
            (["PASSED", "SKIPPED"], "PASSED"),
            (["PASSED", "FAILED"], "FAILED"),
            (["PASSED", "CANCELLED"], "CANCELLED"),
        )
        for outcomes, expected in cases:
            with self.subTest(outcomes=outcomes):
                self.assertEqual(QABreaker._outcome_status(outcomes), expected)

    def test_test_finished_and_log_events_are_job_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "state.db")
            store.create_task("job-1", "Verify", TaskOptions())
            store.create_test_run("run-1", "job-1", "SMOKE", 3)
            events = EventBus()
            qa = QABreaker(store=store, studio=object(), bridge=object(), events=events)

            qa._log("job-1", "ZEN", "Executed", run_id="run-1", case_id="case-1")
            counts = qa._outcome_counts(["PASSED", "SKIPPED"])
            qa._publish_finished("job-1", "run-1", "PASSED", counts)

            log_event, finished_event = events.recent(2)
            self.assertEqual(log_event.type, "TEST_LOG")
            self.assertEqual(log_event.data["jobId"], "job-1")
            self.assertEqual(log_event.data["log"]["jobId"], "job-1")
            self.assertEqual(finished_event.type, "TEST_FINISHED")
            self.assertEqual(finished_event.data["jobId"], "job-1")
            self.assertEqual(finished_event.data["status"], "PASSED")
            self.assertEqual(
                finished_event.data["counts"],
                {key: counts[key] for key in ("total", "passed", "failed", "skipped")},
            )
            self.assertTrue(finished_event.data["passed"])

    def test_failure_and_log_retention_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "state.db")
            store.MAX_TEST_FAILURES_PER_RUN = 2
            store.MAX_TEST_LOGS_PER_RUN = 3
            store.create_task("job-1", "Verify", TaskOptions())
            store.create_test_run("run-1", "job-1", "SMOKE", 3)
            for index in range(5):
                store.append_test_failure(
                    f"failure-{index}",
                    run_id="run-1",
                    job_id="job-1",
                    test_case_id="",
                    name=f"Failure {index}",
                    suite="UNIT",
                    severity="LOW",
                    message="failure",
                    details={},
                    timestamp=index,
                )
                store.append_test_log(
                    f"log-{index}",
                    run_id="run-1",
                    job_id="job-1",
                    level="ERR",
                    message="failure",
                    timestamp=index,
                )

            self.assertEqual([item["id"] for item in store.test_failures("run-1")], ["failure-3", "failure-4"])
            self.assertEqual([item["id"] for item in store.test_logs("run-1")], ["log-2", "log-3", "log-4"])

    def test_final_run_status_rejects_non_authoritative_values(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(Path(folder) / "state.db")
            store.create_task("job-1", "Verify", TaskOptions())
            store.create_test_run("run-1", "job-1", "SMOKE", 3)
            with self.assertRaises(ValueError):
                store.finish_test_run("run-1", "SUCCESS", {})


if __name__ == "__main__":
    unittest.main()
