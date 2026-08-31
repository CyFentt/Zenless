from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import PipelineEvent, Stage, TaskOptions


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class SQLiteStore:
    MAX_MESSAGE_CHARS = 32_000
    MAX_MESSAGES_PER_TASK = 48
    _TASK_COLUMNS = {
        "stage",
        "status",
        "studio_id",
        "context_json",
        "proposal_json",
        "review_json",
        "final_review_json",
        "final_text",
        "error",
    }

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migration_lock = threading.Lock()
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _migrate(self) -> None:
        with self._migration_lock, closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    prompt TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    studio_id TEXT NOT NULL DEFAULT '',
                    options_json TEXT NOT NULL,
                    context_json TEXT NOT NULL DEFAULT '{}',
                    proposal_json TEXT NOT NULL DEFAULT '{}',
                    review_json TEXT NOT NULL DEFAULT '{}',
                    final_review_json TEXT NOT NULL DEFAULT '{}',
                    final_text TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    gate TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS operations (
                    idempotency_key TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    resource_id TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL,
                    response_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS assets (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    mime TEXT NOT NULL DEFAULT 'application/octet-stream',
                    size INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS context_items (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    relevance REAL NOT NULL DEFAULT 0,
                    state TEXT NOT NULL DEFAULT 'included',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES tasks(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS test_runs (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    status TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(job_id) REFERENCES tasks(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS test_cases (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES test_runs(id) ON DELETE CASCADE,
                    FOREIGN KEY(job_id) REFERENCES tasks(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, id);
                CREATE INDEX IF NOT EXISTS idx_messages_task ON messages(task_id, id);
                CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_assets_job ON assets(job_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_context_job ON context_items(job_id, relevance DESC);
                CREATE TABLE IF NOT EXISTS chat_activities (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL DEFAULT '',
                    timestamp INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES tasks(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS chat_artifacts (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    state TEXT NOT NULL,
                    preview_url TEXT NOT NULL DEFAULT '',
                    content_url TEXT NOT NULL DEFAULT '',
                    model_url TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES tasks(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_test_runs_job ON test_runs(job_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_test_cases_run ON test_cases(run_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_activities_job ON chat_activities(job_id, timestamp);
                CREATE INDEX IF NOT EXISTS idx_artifacts_job ON chat_artifacts(job_id, created_at);
                """
            )
            columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(tasks)")}
            if "final_review_json" not in columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN final_review_json TEXT NOT NULL DEFAULT '{}'")

    def create_task(self, task_id: str, prompt: str, options: TaskOptions) -> None:
        timestamp = now_iso()
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO tasks(id, prompt, stage, status, options_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    prompt,
                    Stage.NEW.value,
                    "queued",
                    json.dumps(options.to_dict(), ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )

    def update_task(self, task_id: str, **changes: Any) -> None:
        unknown = set(changes) - self._TASK_COLUMNS
        if unknown:
            raise ValueError(f"Unknown task fields: {sorted(unknown)}")
        if not changes:
            return
        encoded: dict[str, Any] = {}
        for key, value in changes.items():
            if key.endswith("_json") and not isinstance(value, str):
                encoded[key] = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, Stage):
                encoded[key] = value.value
            else:
                encoded[key] = value
        encoded["updated_at"] = now_iso()
        assignments = ", ".join(f"{key} = ?" for key in encoded)
        values = [*encoded.values(), task_id]
        with closing(self._connect()) as connection:
            cursor = connection.execute(f"UPDATE tasks SET {assignments} WHERE id = ?", values)
            if cursor.rowcount != 1:
                raise KeyError(f"Task not found: {task_id}")

    def append_event(self, event: PipelineEvent) -> None:
        timestamp = event.created_at or now_iso()
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO events(task_id, stage, kind, message, detail, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event.task_id, event.stage.value, event.kind, event.message, event.detail, timestamp),
            )

    def append_message(self, task_id: str, sender: str, role: str, content: str) -> None:
        compact = self._compact_message(content)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO messages(task_id, sender, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task_id, sender, role, compact, now_iso()),
            )
            connection.execute(
                """
                DELETE FROM messages
                WHERE task_id = ? AND id NOT IN (
                    SELECT id FROM messages WHERE task_id = ? ORDER BY id DESC LIMIT ?
                )
                """,
                (task_id, task_id, self.MAX_MESSAGES_PER_TASK),
            )
            connection.execute("COMMIT")

    def maintenance(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
            connection.execute("PRAGMA optimize")

    def update_context_section(self, task_id: str, section: str, value: dict[str, Any]) -> None:
        if not section or len(section) > 80:
            raise ValueError("Invalid context section.")
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT context_json FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise KeyError(f"Task not found: {task_id}")
            try:
                context = json.loads(row["context_json"])
            except (TypeError, json.JSONDecodeError):
                context = {}
            if not isinstance(context, dict):
                context = {}
            context[section] = value
            connection.execute(
                "UPDATE tasks SET context_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(context, ensure_ascii=False), now_iso(), task_id),
            )
            connection.execute("COMMIT")

    def recover_interrupted_tasks(self) -> list[dict[str, Any]]:
        unsafe_stages = {
            Stage.APPLYING.value,
            Stage.TESTING.value,
            Stage.FIXING.value,
            Stage.FINAL_REVIEW.value,
        }
        recovered: list[dict[str, Any]] = []
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT id, stage FROM tasks WHERE status IN ('queued', 'running', 'waiting')"
            ).fetchall()
            timestamp = now_iso()
            for row in rows:
                task_id = str(row["id"])
                previous = str(row["stage"])
                if previous in unsafe_stages:
                    next_stage = Stage.BLOCKED.value
                    next_status = "blocked"
                    reason = (
                        "Safe recovery blocked automatic replay of an operation that may have changed "
                        "Studio. Review mutation evidence before starting another task."
                    )
                else:
                    next_stage = Stage.PAUSED.value
                    next_status = "waiting"
                    reason = "Checkpoint recovered after an unexpected shutdown; resuming restarts only the pre-change phase."
                connection.execute(
                    "UPDATE tasks SET stage = ?, status = ?, error = ?, updated_at = ? WHERE id = ?",
                    (next_stage, next_status, reason, timestamp, task_id),
                )
                recovered.append(
                    {
                        "id": task_id,
                        "previous_stage": previous,
                        "stage": next_stage,
                        "status": next_status,
                        "reason": reason,
                    }
                )
            connection.execute("COMMIT")
        return recovered

    def operations_for_resource(self, resource_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM operations WHERE resource_id = ? ORDER BY created_at", (resource_id,)
            ).fetchall()
        return [self._decode_operation(row) for row in rows]

    def record_approval(self, task_id: str, gate: str, decision: str, note: str = "") -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO approvals(task_id, gate, decision, note, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task_id, gate, decision, note, now_iso()),
            )

    def set_setting(self, key: str, value: Any) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO settings(key, value_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False), now_iso()),
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT value_json FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value_json"])
        except json.JSONDecodeError:
            return default

    def load_task(self, task_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._decode_task(row) if row else None

    def recent_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(200, int(limit)))
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?", (safe_limit,)).fetchall()
        return [self._decode_task(row) for row in rows]

    def task_events(self, task_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM events WHERE task_id = ? ORDER BY id", (task_id,)).fetchall()
        return [dict(row) for row in rows]

    def task_messages(self, task_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM messages WHERE task_id = ? ORDER BY id", (task_id,)).fetchall()
        return [dict(row) for row in rows]

    def claim_operation(self, key: str, kind: str, resource_id: str = "") -> dict[str, Any]:
        timestamp = now_iso()
        claimed = False
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM operations WHERE idempotency_key = ?", (key,)).fetchone()
            if row is None:
                claimed = True
                connection.execute(
                    """
                    INSERT INTO operations(idempotency_key, kind, resource_id, state, created_at, updated_at)
                    VALUES (?, ?, ?, 'pending', ?, ?)
                    """,
                    (key, kind, resource_id, timestamp, timestamp),
                )
                row = connection.execute("SELECT * FROM operations WHERE idempotency_key = ?", (key,)).fetchone()
            connection.execute("COMMIT")
        operation = self._decode_operation(row)
        operation["claimed"] = claimed
        return operation

    def finish_operation(self, key: str, state: str, response: dict[str, Any]) -> None:
        if state not in {"complete", "failed", "cancelled"}:
            raise ValueError("Invalid final operation state.")
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE operations SET state = ?, response_json = ?, updated_at = ?
                WHERE idempotency_key = ?
                """,
                (state, json.dumps(response, ensure_ascii=False), now_iso(), key),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Operation not found: {key}")

    def operation(self, key: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM operations WHERE idempotency_key = ?", (key,)).fetchone()
        return self._decode_operation(row) if row else None

    def register_asset(
        self,
        asset_id: str,
        *,
        job_id: str,
        name: str,
        kind: str,
        path: Path,
        mime: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        resolved = path.resolve()
        size = resolved.stat().st_size if resolved.is_file() else 0
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO assets(id, job_id, name, kind, path, mime, size, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    job_id = excluded.job_id,
                    name = excluded.name,
                    kind = excluded.kind,
                    path = excluded.path,
                    mime = excluded.mime,
                    size = excluded.size,
                    metadata_json = excluded.metadata_json
                """,
                (
                    asset_id,
                    job_id,
                    name,
                    kind,
                    str(resolved),
                    mime,
                    size,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now_iso(),
                ),
            )

    def assets(self, job_id: str = "") -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            if job_id:
                rows = connection.execute(
                    "SELECT * FROM assets WHERE job_id = ? ORDER BY created_at DESC", (job_id,)
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM assets ORDER BY created_at DESC").fetchall()
        return [self._decode_json_column(dict(row), "metadata_json", "metadata") for row in rows]

    def asset(self, asset_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        if row is None:
            return None
        return self._decode_json_column(dict(row), "metadata_json", "metadata")

    def replace_context_items(self, job_id: str, items: list[dict[str, Any]]) -> None:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM context_items WHERE job_id = ?", (job_id,))
            timestamp = now_iso()
            for item in items:
                connection.execute(
                    """
                    INSERT INTO context_items(id, job_id, name, kind, path, relevance, state, raw_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(item["id"]),
                        job_id,
                        str(item.get("name", "")),
                        str(item.get("type", "Service")),
                        str(item.get("path", "")),
                        max(0.0, min(1.0, float(item.get("relevance", 0.0)))),
                        str(item.get("state", "included")),
                        json.dumps(item.get("raw", {}), ensure_ascii=False),
                        timestamp,
                    ),
                )
            connection.execute("COMMIT")

    def context_items(self, job_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM context_items WHERE job_id = ? ORDER BY relevance DESC, name", (job_id,)
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = self._decode_json_column(dict(row), "raw_json", "raw")
            item["type"] = item.pop("kind")
            result.append(item)
        return result

    def context_item(self, item_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM context_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            return None
        item = self._decode_json_column(dict(row), "raw_json", "raw")
        item["type"] = item.pop("kind")
        return item

    def set_context_state(self, item_id: str, state: str) -> bool:
        if state not in {"included", "excluded", "locked"}:
            raise ValueError("Invalid context state.")
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                "UPDATE context_items SET state = ?, updated_at = ? WHERE id = ?",
                (state, now_iso(), item_id),
            )
        return cursor.rowcount == 1

    def create_test_run(self, run_id: str, job_id: str, profile: str, seed: int) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO test_runs(id, job_id, profile, status, seed, started_at)
                VALUES (?, ?, ?, 'RUNNING', ?, ?)
                """,
                (run_id, job_id, profile, int(seed), now_iso()),
            )

    def finish_test_run(self, run_id: str, status: str, summary: dict[str, Any]) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE test_runs SET status = ?, summary_json = ?, finished_at = ? WHERE id = ?
                """,
                (status, json.dumps(summary, ensure_ascii=False), now_iso(), run_id),
            )

    def invalidate_test_runs(self, job_id: str) -> int:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                "UPDATE test_runs SET status = 'STALE' WHERE job_id = ? AND status IN ('PASSED', 'FAILED')",
                (job_id,),
            )
        return cursor.rowcount

    def append_test_case(
        self,
        case_id: str,
        *,
        run_id: str,
        job_id: str,
        name: str,
        status: str,
        severity: str,
        details: dict[str, Any],
        duration_ms: int,
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO test_cases(
                    id, run_id, job_id, name, status, severity, details_json, duration_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    run_id,
                    job_id,
                    name,
                    status,
                    severity,
                    json.dumps(details, ensure_ascii=False),
                    max(0, int(duration_ms)),
                    now_iso(),
                ),
            )

    def upsert_activity(
        self,
        activity_id: str,
        job_id: str,
        phase: str,
        status: str,
        title: str,
        detail: str = "",
        provider: str = "",
        role: str = "",
        timestamp: int | None = None,
    ) -> dict[str, Any]:
        ts = timestamp if timestamp is not None else int(datetime.now(UTC).timestamp() * 1000)
        updated = now_iso()
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO chat_activities(
                    id, job_id, phase, status, title, detail, provider, role, timestamp, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    phase = excluded.phase,
                    status = excluded.status,
                    title = excluded.title,
                    detail = excluded.detail,
                    provider = excluded.provider,
                    role = excluded.role,
                    timestamp = excluded.timestamp,
                    updated_at = excluded.updated_at
                """,
                (activity_id, job_id, phase, status, title, detail, provider, role, ts, updated),
            )
        return {
            "id": activity_id,
            "jobId": job_id,
            "phase": phase,
            "status": status,
            "title": title,
            "detail": detail,
            "provider": provider,
            "role": role,
            "timestamp": ts,
        }

    def list_activities(self, job_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM chat_activities WHERE job_id = ? ORDER BY timestamp ASC", (job_id,)
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "jobId": str(row["job_id"]),
                "phase": str(row["phase"]),
                "status": str(row["status"]),
                "title": str(row["title"]),
                "detail": str(row["detail"]),
                "provider": str(row["provider"]),
                "role": str(row["role"]),
                "timestamp": int(row["timestamp"]),
            }
            for row in rows
        ]

    def upsert_artifact(
        self,
        artifact_id: str,
        job_id: str,
        artifact_type: str,
        name: str,
        state: str,
        preview_url: str = "",
        content_url: str = "",
        model_url: str = "",
        metadata: dict[str, Any] | None = None,
        created_at: int | None = None,
    ) -> dict[str, Any]:
        ts = created_at if created_at is not None else int(datetime.now(UTC).timestamp() * 1000)
        updated = now_iso()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO chat_artifacts(
                    id, job_id, type, name, state, preview_url, content_url, model_url, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    type = excluded.type,
                    name = excluded.name,
                    state = excluded.state,
                    preview_url = excluded.preview_url,
                    content_url = excluded.content_url,
                    model_url = excluded.model_url,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (artifact_id, job_id, artifact_type, name, state, preview_url, content_url, model_url, meta_json, ts, updated),
            )
        return {
            "id": artifact_id,
            "jobId": job_id,
            "type": artifact_type,
            "name": name,
            "state": state,
            "previewUrl": preview_url,
            "contentUrl": content_url,
            "modelUrl": model_url,
            "metadata": metadata or {},
            "createdAt": ts,
        }

    def list_artifacts(self, job_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM chat_artifacts WHERE job_id = ? ORDER BY created_at ASC", (job_id,)
            ).fetchall()
        result = []
        for row in rows:
            raw = dict(row)
            item = self._decode_json_column(raw, "metadata_json", "metadata")
            result.append(
                {
                    "id": str(item["id"]),
                    "jobId": str(item["job_id"]),
                    "type": str(item["type"]),
                    "name": str(item["name"]),
                    "state": str(item["state"]),
                    "previewUrl": str(item["preview_url"]),
                    "contentUrl": str(item["content_url"]),
                    "modelUrl": str(item["model_url"]),
                    "metadata": item["metadata"],
                    "createdAt": int(item["created_at"]),
                }
            )
        return result

    def test_cases(self, run_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM test_cases WHERE run_id = ? ORDER BY created_at", (run_id,)
            ).fetchall()
        return [self._decode_json_column(dict(row), "details_json", "details") for row in rows]

    def latest_test_run(self, job_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM test_runs WHERE job_id = ? ORDER BY started_at DESC LIMIT 1", (job_id,)
            ).fetchone()
        if row is None:
            return None
        return self._decode_json_column(dict(row), "summary_json", "summary")

    @classmethod
    def _compact_message(cls, content: str) -> str:
        text = str(content)
        if len(text) <= cls.MAX_MESSAGE_CHARS:
            return text
        digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
        head_size = cls.MAX_MESSAGE_CHARS * 3 // 4
        tail_size = cls.MAX_MESSAGE_CHARS - head_size - 160
        marker = f"\n\n[ZENLESS COMPACTED original_chars={len(text)} sha256={digest}]\n\n"
        return text[:head_size] + marker + text[-max(1000, tail_size) :]

    @staticmethod
    def _decode_task(row: sqlite3.Row) -> dict[str, Any]:
        task = dict(row)
        for key in (
            "options_json",
            "context_json",
            "proposal_json",
            "review_json",
            "final_review_json",
        ):
            try:
                task[key.removesuffix("_json")] = json.loads(task.pop(key))
            except json.JSONDecodeError:
                task[key.removesuffix("_json")] = {}
        return task

    @staticmethod
    def _decode_operation(row: sqlite3.Row) -> dict[str, Any]:
        return SQLiteStore._decode_json_column(dict(row), "response_json", "response")

    @staticmethod
    def _decode_json_column(data: dict[str, Any], source: str, target: str) -> dict[str, Any]:
        raw = data.pop(source, "{}")
        try:
            data[target] = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            data[target] = {}
        return data
