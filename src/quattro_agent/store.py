"""Transactional SQLite/WAL state for the durable Quattro harness."""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import sqlite3
import uuid
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from .errors import LeaseConflict, StateTransitionError, WorkflowError
from .models import (
    RunState,
    StepState,
    TaskState,
    ensure_run_transition,
    ensure_step_transition,
    ensure_task_transition,
    utc_now,
)
from .policy import PolicyProfile
from .privacy import decode_json, display_json, display_text, private_json, redact_secret_text


# The durability tables are an additive schema extension intentionally kept
# readable by the deployed schema-v2 runtime. Existing v2 binaries ignore the
# new tables instead of refusing to open the shared database during rollout.
SCHEMA_VERSION = 2
SUPPORTED_AGENTS = frozenset({"codex", "pi"})


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _future(seconds: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=seconds)).isoformat(
        timespec="milliseconds"
    )


class TaskStore:
    """A crash-safe task database with a connection per transaction.

    The database itself is private (0600).  Callers that feed QML or status
    JSON must use :meth:`display_task` or :meth:`list_display_tasks`; those
    methods never expose private payload columns.
    """

    def __init__(self, path: str | os.PathLike[str], *, busy_timeout_ms: int = 5_000) -> None:
        self.path = Path(path).expanduser().resolve(strict=False)
        self.busy_timeout_ms = busy_timeout_ms
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        self._initialize()
        os.chmod(self.path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @contextlib.contextmanager
    def _transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextlib.contextmanager
    def _reader(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._reader() as connection:
            journal = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            if str(journal).lower() != "wal":
                raise RuntimeError(f"SQLite WAL mode is unavailable for {self.path}")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    parent_task_id TEXT REFERENCES tasks(task_id) ON DELETE RESTRICT,
                    workflow TEXT NOT NULL,
                    agent TEXT NOT NULL CHECK(agent IN ('codex','pi')),
                    project_path TEXT NOT NULL,
                    project_name TEXT NOT NULL,
                    display_title TEXT NOT NULL,
                    display_metadata_json TEXT NOT NULL,
                    private_payload_json TEXT NOT NULL,
                    policy_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    terminal_code TEXT,
                    terminal_summary TEXT
                );
                CREATE INDEX IF NOT EXISTS tasks_state_priority
                    ON tasks(state, priority DESC, created_at);
                CREATE INDEX IF NOT EXISTS tasks_parent ON tasks(parent_task_id);

                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    attempt INTEGER NOT NULL CHECK(attempt > 0),
                    agent TEXT NOT NULL CHECK(agent IN ('codex','pi')),
                    account_id TEXT,
                    native_session_ref TEXT,
                    state TEXT NOT NULL,
                    pid INTEGER,
                    process_start_ticks INTEGER,
                    process_group INTEGER,
                    expected_executable TEXT,
                    started_at TEXT,
                    heartbeat_at TEXT,
                    deadline_at TEXT,
                    completed_at TEXT,
                    exit_code INTEGER,
                    error_code TEXT,
                    private_result_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(task_id, attempt)
                );
                CREATE INDEX IF NOT EXISTS runs_task ON runs(task_id, attempt);
                CREATE INDEX IF NOT EXISTS runs_heartbeat ON runs(state, heartbeat_at);

                CREATE TABLE IF NOT EXISTS steps (
                    step_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    run_id TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
                    name TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    display_metadata_json TEXT NOT NULL,
                    private_payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id, run_id, name)
                );
                CREATE INDEX IF NOT EXISTS steps_task_position ON steps(task_id, position);

                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    run_id TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
                    event_type TEXT NOT NULL,
                    display_payload_json TEXT NOT NULL,
                    private_payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_task_sequence ON events(task_id, sequence);

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    run_id TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    sha256 TEXT,
                    size_bytes INTEGER,
                    display_name TEXT NOT NULL,
                    private_metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS artifacts_task ON artifacts(task_id, created_at);

                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    run_id TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
                    scope TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('requested','approved','declined','expired')),
                    confirmation_summary TEXT NOT NULL,
                    private_payload_json TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    resolved_at TEXT,
                    expires_at TEXT
                );
                CREATE INDEX IF NOT EXISTS approvals_task ON approvals(task_id, state);

                CREATE TABLE IF NOT EXISTS leases (
                    resource_key TEXT PRIMARY KEY,
                    holder_task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    holder_run_id TEXT REFERENCES runs(run_id) ON DELETE CASCADE,
                    token TEXT UNIQUE NOT NULL,
                    kind TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS leases_holder ON leases(holder_task_id, holder_run_id);
                CREATE INDEX IF NOT EXISTS leases_expiry ON leases(expires_at);

                CREATE TABLE IF NOT EXISTS external_effects (
                    effect_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    run_id TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    provider TEXT NOT NULL,
                    effect_type TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('intent','completed','failed','unknown')),
                    external_id TEXT,
                    display_summary TEXT NOT NULL,
                    private_payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS effects_task ON external_effects(task_id, created_at);

                CREATE TABLE IF NOT EXISTS task_dependencies (
                    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    depends_on_task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(task_id, depends_on_task_id),
                    CHECK(task_id <> depends_on_task_id)
                );
                CREATE INDEX IF NOT EXISTS dependencies_reverse
                    ON task_dependencies(depends_on_task_id, task_id);

                CREATE TABLE IF NOT EXISTS logical_sessions (
                    quattro_session_id TEXT PRIMARY KEY,
                    initial_task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
                    current_task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
                    repository_path TEXT NOT NULL,
                    working_directory TEXT NOT NULL,
                    originating_account_id TEXT,
                    last_account_id TEXT,
                    provider_id TEXT NOT NULL,
                    current_codex_session_id TEXT,
                    previous_codex_session_ids_json TEXT NOT NULL DEFAULT '[]',
                    current_checkpoint_id TEXT,
                    session_health TEXT NOT NULL,
                    recovery_state TEXT NOT NULL,
                    last_recovery_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS logical_sessions_updated
                    ON logical_sessions(updated_at DESC);
                CREATE INDEX IF NOT EXISTS logical_sessions_recovery
                    ON logical_sessions(recovery_state, updated_at DESC);

                CREATE TABLE IF NOT EXISTS task_logical_sessions (
                    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE CASCADE,
                    quattro_session_id TEXT NOT NULL
                        REFERENCES logical_sessions(quattro_session_id) ON DELETE CASCADE,
                    attached_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS task_logical_sessions_session
                    ON task_logical_sessions(quattro_session_id, attached_at);

                CREATE TABLE IF NOT EXISTS session_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    quattro_session_id TEXT NOT NULL
                        REFERENCES logical_sessions(quattro_session_id) ON DELETE CASCADE,
                    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
                    run_id TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
                    checkpoint_version INTEGER NOT NULL CHECK(checkpoint_version > 0),
                    kind TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS session_checkpoints_session
                    ON session_checkpoints(quattro_session_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS physical_sessions (
                    physical_session_id TEXT PRIMARY KEY,
                    quattro_session_id TEXT NOT NULL
                        REFERENCES logical_sessions(quattro_session_id) ON DELETE CASCADE,
                    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
                    run_id TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
                    native_codex_session_id TEXT,
                    account_id TEXT,
                    provider_id TEXT NOT NULL,
                    health TEXT NOT NULL,
                    replacement_for_physical_id TEXT
                        REFERENCES physical_sessions(physical_session_id) ON DELETE SET NULL,
                    failure_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS physical_sessions_logical
                    ON physical_sessions(quattro_session_id, created_at);

                CREATE TABLE IF NOT EXISTS session_recoveries (
                    recovery_id TEXT PRIMARY KEY,
                    quattro_session_id TEXT NOT NULL
                        REFERENCES logical_sessions(quattro_session_id) ON DELETE CASCADE,
                    failed_physical_session_id TEXT
                        REFERENCES physical_sessions(physical_session_id) ON DELETE SET NULL,
                    replacement_physical_session_id TEXT
                        REFERENCES physical_sessions(physical_session_id) ON DELETE SET NULL,
                    checkpoint_id TEXT NOT NULL
                        REFERENCES session_checkpoints(checkpoint_id) ON DELETE RESTRICT,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS session_recoveries_logical
                    ON session_recoveries(quattro_session_id, created_at);
                """
            )
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
                return
            version = int(row[0])
            if version == 1:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute("ALTER TABLE steps RENAME TO steps_v1")
                    connection.execute("""CREATE TABLE steps (
                        step_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                        run_id TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
                        name TEXT NOT NULL,
                        position INTEGER NOT NULL,
                        state TEXT NOT NULL,
                        display_metadata_json TEXT NOT NULL,
                        private_payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(task_id, run_id, name)
                    )""")
                    connection.execute("INSERT INTO steps SELECT * FROM steps_v1")
                    connection.execute("DROP TABLE steps_v1")
                    connection.execute("CREATE INDEX steps_task_position ON steps(task_id, position)")
                    connection.execute(
                        "UPDATE schema_meta SET value = '2' WHERE key = 'schema_version'"
                    )
                    connection.commit()
                    version = 2
                except BaseException:
                    connection.rollback()
                    raise
            if version != SCHEMA_VERSION:
                raise RuntimeError(f"unsupported harness database schema: {version}")

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        task_id: str,
        event_type: str,
        *,
        run_id: str | None = None,
        display: Mapping[str, Any] | None = None,
        private: Mapping[str, Any] | None = None,
    ) -> str:
        event_id = _id("evt")
        connection.execute(
            """INSERT INTO events(
                   event_id, task_id, run_id, event_type,
                   display_payload_json, private_payload_json, created_at
               ) VALUES(?,?,?,?,?,?,?)""",
            (
                event_id, task_id, run_id,
                display_text(event_type, field="event_type", maximum=100),
                display_json(display), private_json(private), utc_now(),
            ),
        )
        return event_id

    def create_task(
        self,
        *,
        workflow: str,
        agent: str,
        project_path: str | os.PathLike[str],
        display_title: str,
        policy: PolicyProfile,
        parent_task_id: str | None = None,
        display_metadata: Mapping[str, Any] | None = None,
        private_payload: Mapping[str, Any] | None = None,
        priority: int = 0,
        task_id: str | None = None,
    ) -> str:
        if agent not in SUPPORTED_AGENTS:
            raise ValueError(f"unsupported agent: {agent}")
        if not -1_000 <= priority <= 1_000:
            raise ValueError("priority must be between -1000 and 1000")
        project = Path(project_path).expanduser().resolve(strict=False)
        title = display_text(display_title, field="display_title", maximum=200)
        workflow = display_text(workflow, field="workflow", maximum=100)
        identifier = task_id or _id("task")
        now = utc_now()
        with self._transaction(immediate=True) as connection:
            if parent_task_id is not None:
                parent = connection.execute(
                    "SELECT policy_json FROM tasks WHERE task_id = ?", (parent_task_id,)
                ).fetchone()
                if parent is None:
                    raise KeyError(f"unknown parent task: {parent_task_id}")
                parent_policy = PolicyProfile.from_dict(json.loads(parent["policy_json"]))
                parent_policy.assert_child(policy)
            connection.execute(
                """INSERT INTO tasks(
                       task_id, parent_task_id, workflow, agent, project_path, project_name,
                       display_title, display_metadata_json, private_payload_json, policy_json,
                       state, priority, created_at, updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    identifier, parent_task_id, workflow, agent, str(project),
                    project.name or str(project), title, display_json(display_metadata),
                    private_json(private_payload),
                    json.dumps(policy.to_dict(), separators=(",", ":"), sort_keys=True),
                    TaskState.CREATED.value, priority, now, now,
                ),
            )
            self._event(
                connection, identifier, "task.created",
                display={"state": TaskState.CREATED.value, "agent": agent, "workflow": workflow},
            )
        return identifier

    def _task_row(self, connection: sqlite3.Connection, task_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown task: {task_id}")
        return row

    def get_task(self, task_id: str, *, include_private: bool = False) -> dict[str, Any]:
        with self._reader() as connection:
            row = self._task_row(connection, task_id)
        result = dict(row)
        result["display_metadata"] = decode_json(result.pop("display_metadata_json"))
        result["policy"] = json.loads(result.pop("policy_json"))
        private = decode_json(result.pop("private_payload_json"))
        if include_private:
            result["private_payload"] = private
        return result

    @staticmethod
    def _display_task_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "taskId": row["task_id"],
            "parentTaskId": row["parent_task_id"],
            "workflow": row["workflow"],
            "agent": row["agent"],
            "projectPath": row["project_path"],
            "projectName": row["project_name"],
            "title": row["display_title"],
            "metadata": decode_json(row["display_metadata_json"]),
            "policy": json.loads(row["policy_json"])["name"],
            "state": row["state"],
            "priority": row["priority"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "completedAt": row["completed_at"],
            "terminalCode": row["terminal_code"],
            "terminalSummary": row["terminal_summary"],
        }

    def display_task(self, task_id: str) -> dict[str, Any]:
        with self._reader() as connection:
            return self._display_task_row(self._task_row(connection, task_id))

    def list_display_tasks(self, *, limit: int = 100, state: TaskState | None = None) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1_000:
            raise ValueError("limit must be between 1 and 1000")
        query = "SELECT * FROM tasks"
        parameters: tuple[Any, ...] = ()
        if state is not None:
            query += " WHERE state = ?"
            parameters = (state.value,)
        query += " ORDER BY updated_at DESC LIMIT ?"
        parameters += (limit,)
        with self._reader() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._display_task_row(row) for row in rows]

    def update_display_metadata(self, task_id: str, metadata: Mapping[str, Any]) -> None:
        """Replace display-safe task metadata without exposing private payloads."""
        with self._transaction(immediate=True) as connection:
            self._task_row(connection, task_id)
            connection.execute(
                "UPDATE tasks SET display_metadata_json = ?, updated_at = ? WHERE task_id = ?",
                (display_json(metadata), utc_now(), task_id),
            )

    def transition_task(
        self,
        task_id: str,
        target: TaskState,
        *,
        expected: TaskState | None = None,
        terminal_code: str | None = None,
        terminal_summary: str | None = None,
    ) -> TaskState:
        now = utc_now()
        with self._transaction(immediate=True) as connection:
            row = self._task_row(connection, task_id)
            current = TaskState(row["state"])
            if expected is not None and current is not expected:
                raise StateTransitionError(
                    f"task {task_id} expected {expected.value}, found {current.value}"
                )
            ensure_task_transition(current, target)
            completed_at = now if target in {
                TaskState.SUCCEEDED, TaskState.FAILED, TaskState.CANCELLED,
                TaskState.TIMED_OUT, TaskState.INTERRUPTED,
            } else None
            summary = (
                display_text(terminal_summary, field="terminal_summary", maximum=1_000)
                if terminal_summary is not None else None
            )
            code = (
                display_text(terminal_code, field="terminal_code", maximum=100)
                if terminal_code is not None else None
            )
            connection.execute(
                """UPDATE tasks
                   SET state = ?, updated_at = ?, completed_at = ?,
                       terminal_code = ?, terminal_summary = ?
                   WHERE task_id = ?""",
                (target.value, now, completed_at, code, summary, task_id),
            )
            self._event(
                connection, task_id, "task.transition",
                display={"from": current.value, "to": target.value, "code": code},
            )
        return target

    def append_event(
        self,
        task_id: str,
        event_type: str,
        *,
        run_id: str | None = None,
        display: Mapping[str, Any] | None = None,
        private: Mapping[str, Any] | None = None,
    ) -> str:
        with self._transaction(immediate=True) as connection:
            self._task_row(connection, task_id)
            return self._event(
                connection, task_id, event_type, run_id=run_id,
                display=display, private=private,
            )

    def display_events(self, task_id: str, *, after_sequence: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1_000:
            raise ValueError("limit must be between 1 and 1000")
        with self._reader() as connection:
            rows = connection.execute(
                """SELECT sequence, event_id, task_id, run_id, event_type,
                          display_payload_json, created_at
                   FROM events WHERE task_id = ? AND sequence > ?
                   ORDER BY sequence LIMIT ?""",
                (task_id, after_sequence, limit),
            ).fetchall()
        return [{
            "sequence": row["sequence"], "eventId": row["event_id"],
            "taskId": row["task_id"], "runId": row["run_id"],
            "type": row["event_type"], "payload": decode_json(row["display_payload_json"]),
            "createdAt": row["created_at"],
        } for row in rows]

    def create_run(
        self,
        task_id: str,
        *,
        agent: str | None = None,
        account_id: str | None = None,
        native_session_ref: str | None = None,
        run_id: str | None = None,
    ) -> str:
        identifier = run_id or _id("run")
        with self._transaction(immediate=True) as connection:
            task = self._task_row(connection, task_id)
            selected_agent = agent or task["agent"]
            if selected_agent not in SUPPORTED_AGENTS:
                raise ValueError(f"unsupported agent: {selected_agent}")
            attempt = connection.execute(
                "SELECT COALESCE(MAX(attempt), 0) + 1 FROM runs WHERE task_id = ?", (task_id,)
            ).fetchone()[0]
            connection.execute(
                """INSERT INTO runs(
                       run_id, task_id, attempt, agent, account_id, native_session_ref, state
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    identifier, task_id, attempt, selected_agent, account_id,
                    native_session_ref, RunState.CREATED.value,
                ),
            )
            self._event(
                connection, task_id, "run.created", run_id=identifier,
                display={"attempt": attempt, "agent": selected_agent},
            )
        return identifier

    def claim_task_for_run(
        self,
        task_id: str,
        *,
        agent: str | None = None,
        account_id: str | None = None,
        native_session_ref: str | None = None,
    ) -> str:
        """Atomically claim a queued or approval-ready task and create its run."""
        identifier = _id("run")
        with self._transaction(immediate=True) as connection:
            task = self._task_row(connection, task_id)
            current = TaskState(task["state"])
            if current not in {TaskState.QUEUED, TaskState.READY}:
                raise StateTransitionError(
                    f"task {task_id} expected queued or ready, found {current.value}"
                )
            if current is TaskState.READY and connection.execute(
                "SELECT 1 FROM runs WHERE task_id = ? LIMIT 1", (task_id,)
            ).fetchone() is not None:
                raise StateTransitionError(f"task {task_id} is already claimed")
            selected_agent = agent or task["agent"]
            if selected_agent not in SUPPORTED_AGENTS:
                raise ValueError(f"unsupported agent: {selected_agent}")
            attempt = connection.execute(
                "SELECT COALESCE(MAX(attempt), 0) + 1 FROM runs WHERE task_id = ?",
                (task_id,),
            ).fetchone()[0]
            now = utc_now()
            connection.execute(
                "UPDATE tasks SET state = ?, updated_at = ? WHERE task_id = ?",
                (TaskState.READY.value, now, task_id),
            )
            connection.execute(
                """INSERT INTO runs(
                       run_id, task_id, attempt, agent, account_id, native_session_ref, state
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    identifier, task_id, attempt, selected_agent, account_id,
                    native_session_ref, RunState.CREATED.value,
                ),
            )
            self._event(
                connection, task_id, "task.claimed", run_id=identifier,
                display={"from": current.value, "to": TaskState.READY.value, "attempt": attempt},
            )
        return identifier

    def recover_abandoned_claims(self, cutoff: str) -> list[str]:
        """Interrupt ready tasks whose created run never acquired a worker PID."""
        recovered: list[str] = []
        with self._transaction(immediate=True) as connection:
            rows = connection.execute(
                """SELECT t.task_id, r.run_id
                   FROM tasks t JOIN runs r ON r.task_id = t.task_id
                   WHERE t.state = ? AND r.state = ? AND t.updated_at < ?
                   AND r.attempt = (SELECT MAX(r2.attempt) FROM runs r2 WHERE r2.task_id = t.task_id)""",
                (TaskState.READY.value, RunState.CREATED.value, cutoff),
            ).fetchall()
            for row in rows:
                now = utc_now()
                connection.execute(
                    "UPDATE runs SET state = ?, completed_at = ?, error_code = ? WHERE run_id = ?",
                    (RunState.INTERRUPTED.value, now, "claim_abandoned", row["run_id"]),
                )
                connection.execute(
                    """UPDATE tasks SET state = ?, updated_at = ?, completed_at = ?,
                              terminal_code = ?, terminal_summary = ? WHERE task_id = ?""",
                    (
                        TaskState.INTERRUPTED.value, now, now, "claim_abandoned",
                        "Worker stopped before process startup; task can be retried.", row["task_id"],
                    ),
                )
                self._event(
                    connection, row["task_id"], "task.claim.recovered", run_id=row["run_id"],
                    display={"state": TaskState.INTERRUPTED.value},
                )
                recovered.append(row["task_id"])
        return recovered

    def recover_orphaned_validations(self, cutoff: str) -> list[str]:
        """Make stale post-process validation tasks deterministically retryable."""
        recovered: list[str] = []
        with self._transaction(immediate=True) as connection:
            rows = connection.execute(
                """SELECT t.task_id
                   FROM tasks t
                   WHERE t.state = ? AND t.updated_at < ?
                   AND EXISTS (
                       SELECT 1 FROM runs r WHERE r.task_id = t.task_id
                       AND r.state = ?
                       AND r.attempt = (
                           SELECT MAX(r2.attempt) FROM runs r2 WHERE r2.task_id = t.task_id
                       )
                   )""",
                (TaskState.VALIDATING_RESULT.value, cutoff, RunState.SUCCEEDED.value),
            ).fetchall()
            for row in rows:
                now = utc_now()
                connection.execute(
                    """UPDATE tasks SET state = ?, updated_at = ?, completed_at = ?,
                              terminal_code = ?, terminal_summary = ? WHERE task_id = ?""",
                    (
                        TaskState.INTERRUPTED.value, now, now,
                        "validation_worker_lost",
                        "Host validation was interrupted after agent success; task can be retried.",
                        row["task_id"],
                    ),
                )
                self._event(
                    connection, row["task_id"], "validation.recovered",
                    display={"state": TaskState.INTERRUPTED.value},
                )
                recovered.append(row["task_id"])
        return recovered

    def purge_expired_leases(self) -> int:
        with self._transaction(immediate=True) as connection:
            cursor = connection.execute("DELETE FROM leases WHERE expires_at <= ?", (utc_now(),))
            return cursor.rowcount

    def get_run(self, run_id: str, *, include_private: bool = False) -> dict[str, Any]:
        with self._reader() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown run: {run_id}")
        result = dict(row)
        private = decode_json(result.pop("private_result_json"))
        if include_private:
            result["private_result"] = private
        return result

    def display_run(self, run_id: str) -> dict[str, Any]:
        """Return bounded run metadata without native output or private results."""
        run = self.get_run(run_id)
        return {
            "schemaVersion": 1,
            "runId": run["run_id"],
            "taskId": run["task_id"],
            "attempt": run["attempt"],
            "agent": run["agent"],
            "accountId": run["account_id"],
            "state": run["state"],
            "pid": run["pid"],
            "startedAt": run["started_at"],
            "heartbeatAt": run["heartbeat_at"],
            "deadlineAt": run["deadline_at"],
            "completedAt": run["completed_at"],
            "exitCode": run["exit_code"],
            "errorCode": run["error_code"],
        }

    def runs_for_task(self, task_id: str) -> list[dict[str, Any]]:
        """Return display-safe run records ordered by attempt."""
        with self._reader() as connection:
            rows = connection.execute(
                "SELECT run_id FROM runs WHERE task_id = ? ORDER BY attempt",
                (task_id,),
            ).fetchall()
        return [self.display_run(row["run_id"]) for row in rows]

    def latest_run(self, task_id: str) -> dict[str, Any] | None:
        """Return the newest run including process identity, but no private result."""
        with self._reader() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE task_id = ? ORDER BY attempt DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result.pop("private_result_json", None)
        return result

    def transition_run(
        self,
        run_id: str,
        target: RunState,
        *,
        exit_code: int | None = None,
        error_code: str | None = None,
        private_result: Mapping[str, Any] | None = None,
    ) -> RunState:
        now = utc_now()
        with self._transaction(immediate=True) as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown run: {run_id}")
            current = RunState(row["state"])
            ensure_run_transition(current, target)
            completed = now if target in {
                RunState.SUCCEEDED, RunState.FAILED, RunState.CANCELLED,
                RunState.TIMED_OUT, RunState.INTERRUPTED,
            } else None
            safe_error = (
                display_text(error_code, field="error_code", maximum=100)
                if error_code is not None else None
            )
            connection.execute(
                """UPDATE runs SET state = ?, completed_at = ?, exit_code = ?,
                                      error_code = ?, private_result_json = ?
                   WHERE run_id = ?""",
                (
                    target.value, completed, exit_code, safe_error,
                    private_json(private_result) if private_result is not None
                    else row["private_result_json"],
                    run_id,
                ),
            )
            self._event(
                connection, row["task_id"], "run.transition", run_id=run_id,
                display={"from": current.value, "to": target.value, "exitCode": exit_code,
                         "errorCode": safe_error},
            )
        return target

    def mark_run_started(
        self,
        run_id: str,
        *,
        pid: int,
        process_start_ticks: int,
        process_group: int,
        expected_executable: str,
        deadline_at: str | None,
    ) -> None:
        now = utc_now()
        with self._transaction(immediate=True) as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown run: {run_id}")
            current = RunState(row["state"])
            if current is RunState.CREATED:
                ensure_run_transition(current, RunState.STARTING)
                current = RunState.STARTING
            ensure_run_transition(current, RunState.RUNNING)
            connection.execute(
                """UPDATE runs SET state = ?, pid = ?, process_start_ticks = ?,
                   process_group = ?, expected_executable = ?, started_at = ?,
                   heartbeat_at = ?, deadline_at = ? WHERE run_id = ?""",
                (
                    RunState.RUNNING.value, pid, process_start_ticks, process_group,
                    expected_executable, now, now, deadline_at, run_id,
                ),
            )
            self._event(
                connection, row["task_id"], "run.started", run_id=run_id,
                display={"pid": pid, "startedAt": now},
            )

    def heartbeat_run(self, run_id: str) -> str:
        now = utc_now()
        with self._transaction(immediate=True) as connection:
            cursor = connection.execute(
                "UPDATE runs SET heartbeat_at = ? WHERE run_id = ? AND state = ?",
                (now, run_id, RunState.RUNNING.value),
            )
            if cursor.rowcount != 1:
                raise StateTransitionError(f"run is not heartbeat-eligible: {run_id}")
        return now

    def stale_runs(self, cutoff: str) -> list[dict[str, Any]]:
        with self._reader() as connection:
            rows = connection.execute(
                """SELECT * FROM runs
                   WHERE state IN (?,?) AND (heartbeat_at IS NULL OR heartbeat_at < ?)
                   ORDER BY heartbeat_at""",
                (RunState.STARTING.value, RunState.RUNNING.value, cutoff),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_step(
        self,
        task_id: str,
        name: str,
        *,
        position: int,
        run_id: str | None = None,
        display_metadata: Mapping[str, Any] | None = None,
        private_payload: Mapping[str, Any] | None = None,
    ) -> str:
        identifier = _id("step")
        now = utc_now()
        with self._transaction(immediate=True) as connection:
            self._task_row(connection, task_id)
            connection.execute(
                """INSERT INTO steps(
                    step_id, task_id, run_id, name, position, state,
                    display_metadata_json, private_payload_json, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    identifier, task_id, run_id,
                    display_text(name, field="step_name", maximum=120), position,
                    StepState.PENDING.value, display_json(display_metadata),
                    private_json(private_payload), now, now,
                ),
            )
            self._event(connection, task_id, "step.created", run_id=run_id,
                        display={"stepId": identifier, "name": name, "position": position})
        return identifier

    def transition_step(self, step_id: str, target: StepState) -> StepState:
        with self._transaction(immediate=True) as connection:
            row = connection.execute("SELECT * FROM steps WHERE step_id = ?", (step_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown step: {step_id}")
            current = StepState(row["state"])
            ensure_step_transition(current, target)
            connection.execute(
                "UPDATE steps SET state = ?, updated_at = ? WHERE step_id = ?",
                (target.value, utc_now(), step_id),
            )
            self._event(connection, row["task_id"], "step.transition", run_id=row["run_id"],
                        display={"stepId": step_id, "from": current.value, "to": target.value})
        return target

    def add_artifact(
        self,
        task_id: str,
        *,
        kind: str,
        path: str | os.PathLike[str],
        display_name: str,
        run_id: str | None = None,
        private_metadata: Mapping[str, Any] | None = None,
        calculate_hash: bool = False,
    ) -> str:
        artifact_path = Path(path).expanduser().resolve(strict=False)
        size: int | None = None
        digest: str | None = None
        if calculate_hash:
            hasher = hashlib.sha256()
            with artifact_path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    hasher.update(chunk)
            digest = hasher.hexdigest()
            size = artifact_path.stat().st_size
        identifier = _id("artifact")
        with self._transaction(immediate=True) as connection:
            self._task_row(connection, task_id)
            connection.execute(
                """INSERT INTO artifacts(
                    artifact_id, task_id, run_id, kind, path, sha256, size_bytes,
                    display_name, private_metadata_json, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    identifier, task_id, run_id,
                    display_text(kind, field="artifact_kind", maximum=100), str(artifact_path),
                    digest, size, display_text(display_name, field="display_name", maximum=200),
                    private_json(private_metadata), utc_now(),
                ),
            )
            self._event(connection, task_id, "artifact.added", run_id=run_id,
                        display={"artifactId": identifier, "kind": kind, "name": display_name,
                                 "sizeBytes": size})
        return identifier

    def artifacts_for_task(self, task_id: str) -> list[dict[str, Any]]:
        """Return display-safe artifact metadata without private payloads."""
        with self._reader() as connection:
            rows = connection.execute(
                """SELECT artifact_id, task_id, run_id, kind, path, sha256,
                          size_bytes, display_name, created_at
                   FROM artifacts WHERE task_id = ? ORDER BY created_at""",
                (task_id,),
            ).fetchall()
        return [{
            "artifactId": row["artifact_id"],
            "taskId": row["task_id"],
            "runId": row["run_id"],
            "kind": row["kind"],
            "path": row["path"],
            "sha256": row["sha256"],
            "sizeBytes": row["size_bytes"],
            "name": row["display_name"],
            "createdAt": row["created_at"],
        } for row in rows]

    def update_private_payload(self, task_id: str, payload: Mapping[str, Any]) -> None:
        """Replace a task's private payload transactionally and record no content."""
        with self._transaction(immediate=True) as connection:
            self._task_row(connection, task_id)
            connection.execute(
                "UPDATE tasks SET private_payload_json = ?, updated_at = ? WHERE task_id = ?",
                (private_json(payload), utc_now(), task_id),
            )
            self._event(connection, task_id, "task.private_payload.updated")

    @staticmethod
    def _checkpoint_json(payload: Mapping[str, Any]) -> tuple[str, str]:
        required = {
            "objective", "requirements", "repositoryPath", "workingDirectory",
            "completed", "filesChanged", "importantDecisions", "validation",
            "unresolved", "nextAction", "repositoryState", "activeCodexSessionId",
            "previousCodexSessionIds", "accountId", "timestamp", "checkpointVersion",
        }
        missing = sorted(required - set(payload))
        if missing:
            raise ValueError(f"checkpoint is missing required fields: {', '.join(missing)}")
        version = payload.get("checkpointVersion")
        if not isinstance(version, int) or version <= 0:
            raise ValueError("checkpointVersion must be a positive integer")
        sensitive_fragments = (
            "password", "token", "secret", "credential", "authorization",
            "cookie", "privatekey", "recoverycode", "authjson",
        )
        forbidden_checkpoint_keys = {
            "reasoning", "chainofthought", "hiddenthoughts", "terminaltranscript",
            "conversationhistory", "environment", "processenvironment",
        }

        def sanitize(value: Any, key: str = "") -> Any:
            compact = "".join(character for character in key.lower() if character.isalnum())
            if compact in forbidden_checkpoint_keys:
                raise ValueError(f"checkpoint field is prohibited: {key}")
            if key and any(fragment in compact for fragment in sensitive_fragments):
                return "[REDACTED BY QUATTRO]"
            if isinstance(value, str):
                return redact_secret_text(value)[0]
            if isinstance(value, Mapping):
                return {str(item_key): sanitize(item, str(item_key)) for item_key, item in value.items()}
            if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
                return [sanitize(item) for item in value]
            return value

        encoded = private_json(sanitize(payload))
        decoded = decode_json(encoded)
        if set(required) - set(decoded):
            raise ValueError("checkpoint failed validation after serialization")
        return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def create_logical_session(
        self,
        *,
        task_id: str,
        repository_path: str | os.PathLike[str],
        working_directory: str | os.PathLike[str],
        account_id: str | None,
        provider_id: str,
        initial_checkpoint: Mapping[str, Any],
        native_codex_session_id: str | None = None,
        quattro_session_id: str | None = None,
    ) -> tuple[str, str]:
        """Create a logical session and its write-ahead intent checkpoint atomically."""
        identifier = quattro_session_id or _id("qsession")
        checkpoint_id = _id("checkpoint")
        content, digest = self._checkpoint_json(initial_checkpoint)
        now = utc_now()
        repository = str(Path(repository_path).expanduser().resolve(strict=False))
        workdir = str(Path(working_directory).expanduser().resolve(strict=False))
        provider = display_text(provider_id, field="provider_id", maximum=100)
        with self._transaction(immediate=True) as connection:
            self._task_row(connection, task_id)
            connection.execute(
                """INSERT INTO logical_sessions(
                       quattro_session_id, initial_task_id, current_task_id,
                       repository_path, working_directory, originating_account_id,
                       last_account_id, provider_id, current_codex_session_id,
                       previous_codex_session_ids_json, current_checkpoint_id,
                       session_health, recovery_state, created_at, updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    identifier, task_id, task_id, repository, workdir, account_id,
                    account_id, provider, native_codex_session_id, "[]", None,
                    "healthy", "active", now, now,
                ),
            )
            connection.execute(
                """INSERT INTO task_logical_sessions(task_id, quattro_session_id, attached_at)
                   VALUES(?,?,?)""",
                (task_id, identifier, now),
            )
            connection.execute(
                """INSERT INTO session_checkpoints(
                       checkpoint_id, quattro_session_id, task_id, run_id,
                       checkpoint_version, kind, content_json, content_sha256, created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    checkpoint_id, identifier, task_id, None,
                    int(initial_checkpoint["checkpointVersion"]), "accepted-intent",
                    content, digest, now,
                ),
            )
            candidate = connection.execute(
                "SELECT content_json FROM session_checkpoints WHERE checkpoint_id = ?",
                (checkpoint_id,),
            ).fetchone()
            if candidate is None or hashlib.sha256(
                candidate["content_json"].encode("utf-8")
            ).hexdigest() != digest:
                raise RuntimeError("initial checkpoint verification failed")
            connection.execute(
                """UPDATE logical_sessions
                   SET current_checkpoint_id = ?, updated_at = ?
                   WHERE quattro_session_id = ?""",
                (checkpoint_id, now, identifier),
            )
            self._event(
                connection, task_id, "logical_session.created",
                display={"quattroSessionId": identifier, "checkpointId": checkpoint_id},
            )
        return identifier, checkpoint_id

    def attach_task_to_logical_session(self, task_id: str, quattro_session_id: str) -> None:
        now = utc_now()
        with self._transaction(immediate=True) as connection:
            self._task_row(connection, task_id)
            session = connection.execute(
                "SELECT 1 FROM logical_sessions WHERE quattro_session_id = ?",
                (quattro_session_id,),
            ).fetchone()
            if session is None:
                raise KeyError(f"unknown logical session: {quattro_session_id}")
            connection.execute(
                """INSERT INTO task_logical_sessions(task_id, quattro_session_id, attached_at)
                   VALUES(?,?,?)""",
                (task_id, quattro_session_id, now),
            )
            connection.execute(
                """UPDATE logical_sessions SET current_task_id = ?, updated_at = ?
                   WHERE quattro_session_id = ?""",
                (task_id, now, quattro_session_id),
            )
            self._event(
                connection, task_id, "logical_session.attached",
                display={"quattroSessionId": quattro_session_id},
            )

    def logical_session_for_task(self, task_id: str) -> dict[str, Any] | None:
        with self._reader() as connection:
            row = connection.execute(
                """SELECT s.* FROM task_logical_sessions m
                   JOIN logical_sessions s ON s.quattro_session_id = m.quattro_session_id
                   WHERE m.task_id = ?""",
                (task_id,),
            ).fetchone()
        return self._logical_session_dict(row) if row is not None else None

    @staticmethod
    def _logical_session_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["previous_codex_session_ids"] = json.loads(
            result.pop("previous_codex_session_ids_json")
        )
        return result

    def get_logical_session(self, quattro_session_id: str) -> dict[str, Any]:
        with self._reader() as connection:
            row = connection.execute(
                "SELECT * FROM logical_sessions WHERE quattro_session_id = ?",
                (quattro_session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown logical session: {quattro_session_id}")
        return self._logical_session_dict(row)

    def list_logical_sessions(
        self, *, recoverable_only: bool = False, limit: int = 100
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1_000:
            raise ValueError("limit must be between 1 and 1000")
        query = "SELECT * FROM logical_sessions"
        parameters: list[Any] = []
        if recoverable_only:
            query += " WHERE current_checkpoint_id IS NOT NULL AND recovery_state <> 'closed'"
        query += " ORDER BY updated_at DESC LIMIT ?"
        parameters.append(limit)
        with self._reader() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._logical_session_dict(row) for row in rows]

    def create_checkpoint(
        self,
        quattro_session_id: str,
        payload: Mapping[str, Any],
        *,
        kind: str,
        task_id: str | None = None,
        run_id: str | None = None,
    ) -> str:
        """Persist, verify, and publish a checkpoint in one transaction.

        The current pointer changes only after the candidate row is readable and
        its canonical content hash matches. Any failure rolls back both actions.
        """
        identifier = _id("checkpoint")
        content, digest = self._checkpoint_json(payload)
        safe_kind = display_text(kind, field="checkpoint_kind", maximum=100)
        now = utc_now()
        with self._transaction(immediate=True) as connection:
            session = connection.execute(
                "SELECT current_task_id FROM logical_sessions WHERE quattro_session_id = ?",
                (quattro_session_id,),
            ).fetchone()
            if session is None:
                raise KeyError(f"unknown logical session: {quattro_session_id}")
            bound_task = task_id or session["current_task_id"]
            if bound_task is not None:
                self._task_row(connection, bound_task)
            connection.execute(
                """INSERT INTO session_checkpoints(
                       checkpoint_id, quattro_session_id, task_id, run_id,
                       checkpoint_version, kind, content_json, content_sha256, created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    identifier, quattro_session_id, bound_task, run_id,
                    int(payload["checkpointVersion"]), safe_kind, content, digest, now,
                ),
            )
            candidate = connection.execute(
                "SELECT content_json, content_sha256 FROM session_checkpoints WHERE checkpoint_id = ?",
                (identifier,),
            ).fetchone()
            if candidate is None or candidate["content_sha256"] != hashlib.sha256(
                candidate["content_json"].encode("utf-8")
            ).hexdigest():
                raise RuntimeError("checkpoint candidate verification failed")
            connection.execute(
                """UPDATE logical_sessions
                   SET current_checkpoint_id = ?, updated_at = ?
                   WHERE quattro_session_id = ?""",
                (identifier, now, quattro_session_id),
            )
            if bound_task is not None:
                self._event(
                    connection, bound_task, "checkpoint.created", run_id=run_id,
                    display={
                        "quattroSessionId": quattro_session_id,
                        "checkpointId": identifier,
                        "kind": safe_kind,
                    },
                )
        return identifier

    def get_checkpoint(
        self, checkpoint_id: str, *, include_content: bool = False
    ) -> dict[str, Any]:
        with self._reader() as connection:
            row = connection.execute(
                "SELECT * FROM session_checkpoints WHERE checkpoint_id = ?",
                (checkpoint_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown checkpoint: {checkpoint_id}")
        result = dict(row)
        content = decode_json(result.pop("content_json"))
        if include_content:
            result["content"] = content
        return result

    def current_checkpoint(
        self, quattro_session_id: str, *, include_content: bool = False
    ) -> dict[str, Any] | None:
        session = self.get_logical_session(quattro_session_id)
        checkpoint_id = session.get("current_checkpoint_id")
        return self.get_checkpoint(
            str(checkpoint_id), include_content=include_content
        ) if checkpoint_id else None

    def checkpoints_for_session(self, quattro_session_id: str) -> list[dict[str, Any]]:
        with self._reader() as connection:
            rows = connection.execute(
                """SELECT checkpoint_id FROM session_checkpoints
                   WHERE quattro_session_id = ? ORDER BY created_at""",
                (quattro_session_id,),
            ).fetchall()
        return [self.get_checkpoint(row["checkpoint_id"]) for row in rows]

    def record_physical_session(
        self,
        quattro_session_id: str,
        *,
        task_id: str,
        run_id: str | None,
        account_id: str | None,
        provider_id: str,
        native_codex_session_id: str | None,
        replacement_for_physical_id: str | None = None,
    ) -> str:
        identifier = _id("physical")
        now = utc_now()
        with self._transaction(immediate=True) as connection:
            session = connection.execute(
                "SELECT * FROM logical_sessions WHERE quattro_session_id = ?",
                (quattro_session_id,),
            ).fetchone()
            if session is None:
                raise KeyError(f"unknown logical session: {quattro_session_id}")
            self._task_row(connection, task_id)
            connection.execute(
                """INSERT INTO physical_sessions(
                       physical_session_id, quattro_session_id, task_id, run_id,
                       native_codex_session_id, account_id, provider_id, health,
                       replacement_for_physical_id, created_at, updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    identifier, quattro_session_id, task_id, run_id,
                    native_codex_session_id, account_id,
                    display_text(provider_id, field="provider_id", maximum=100),
                    "healthy", replacement_for_physical_id, now, now,
                ),
            )
            previous = json.loads(session["previous_codex_session_ids_json"])
            current = session["current_codex_session_id"]
            if current and current != native_codex_session_id and current not in previous:
                previous.append(current)
            connection.execute(
                """UPDATE logical_sessions
                   SET current_codex_session_id = ?, previous_codex_session_ids_json = ?,
                       last_account_id = ?, session_health = 'healthy',
                       recovery_state = 'active', updated_at = ?
                   WHERE quattro_session_id = ?""",
                (
                    native_codex_session_id,
                    json.dumps(previous[-100:], separators=(",", ":")),
                    account_id, now, quattro_session_id,
                ),
            )
            self._event(
                connection, task_id, "physical_session.started", run_id=run_id,
                display={
                    "quattroSessionId": quattro_session_id,
                    "physicalSessionId": identifier,
                    "replacement": replacement_for_physical_id is not None,
                },
            )
        return identifier

    def latest_physical_session(self, quattro_session_id: str) -> dict[str, Any] | None:
        with self._reader() as connection:
            row = connection.execute(
                """SELECT * FROM physical_sessions WHERE quattro_session_id = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (quattro_session_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def mark_physical_session_failed(self, physical_session_id: str, reason: str) -> None:
        now = utc_now()
        safe_reason = display_text(reason, field="recovery_reason", maximum=1_000)
        with self._transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM physical_sessions WHERE physical_session_id = ?",
                (physical_session_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown physical session: {physical_session_id}")
            connection.execute(
                """UPDATE physical_sessions SET health = 'failed', failure_reason = ?,
                       updated_at = ? WHERE physical_session_id = ?""",
                (safe_reason, now, physical_session_id),
            )
            connection.execute(
                """UPDATE logical_sessions
                   SET session_health = 'physical_session_failed',
                       recovery_state = CASE WHEN current_checkpoint_id IS NULL
                           THEN 'unrecoverable' ELSE 'recoverable' END,
                       last_recovery_reason = ?, updated_at = ?
                   WHERE quattro_session_id = ?""",
                (safe_reason, now, row["quattro_session_id"]),
            )
            self._event(
                connection, row["task_id"], "physical_session.failed", run_id=row["run_id"],
                display={
                    "quattroSessionId": row["quattro_session_id"],
                    "physicalSessionId": physical_session_id,
                    "state": "physical_session_failed",
                },
            )

    def mark_physical_session_healthy(self, physical_session_id: str) -> None:
        """Record successful continuation without discarding recovery history."""
        now = utc_now()
        with self._transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM physical_sessions WHERE physical_session_id = ?",
                (physical_session_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown physical session: {physical_session_id}")
            recovered = connection.execute(
                """SELECT 1 FROM session_recoveries
                   WHERE replacement_physical_session_id = ? LIMIT 1""",
                (physical_session_id,),
            ).fetchone() is not None
            connection.execute(
                """UPDATE physical_sessions SET health = 'healthy', failure_reason = NULL,
                       updated_at = ? WHERE physical_session_id = ?""",
                (now, physical_session_id),
            )
            connection.execute(
                """UPDATE logical_sessions
                   SET session_health = 'healthy', recovery_state = ?, updated_at = ?
                   WHERE quattro_session_id = ?""",
                ("recovered" if recovered else "active", now, row["quattro_session_id"]),
            )

    def record_recovery(
        self,
        quattro_session_id: str,
        *,
        failed_physical_session_id: str | None,
        replacement_physical_session_id: str,
        checkpoint_id: str,
        reason: str,
    ) -> str:
        identifier = _id("recovery")
        now = utc_now()
        safe_reason = display_text(reason, field="recovery_reason", maximum=1_000)
        with self._transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO session_recoveries(
                       recovery_id, quattro_session_id, failed_physical_session_id,
                       replacement_physical_session_id, checkpoint_id, reason, created_at
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    identifier, quattro_session_id, failed_physical_session_id,
                    replacement_physical_session_id, checkpoint_id, safe_reason, now,
                ),
            )
            connection.execute(
                """UPDATE logical_sessions
                   SET recovery_state = 'replacement_started', session_health = 'recovering',
                       last_recovery_reason = ?, updated_at = ?
                   WHERE quattro_session_id = ?""",
                (safe_reason, now, quattro_session_id),
            )
        return identifier

    def recovery_history(self, quattro_session_id: str) -> list[dict[str, Any]]:
        with self._reader() as connection:
            rows = connection.execute(
                """SELECT * FROM session_recoveries WHERE quattro_session_id = ?
                   ORDER BY created_at""",
                (quattro_session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def request_approval(
        self,
        task_id: str,
        *,
        scope: str,
        confirmation_summary: str,
        run_id: str | None = None,
        private_payload: Mapping[str, Any] | None = None,
        expires_at: str | None = None,
    ) -> str:
        identifier = _id("approval")
        with self._transaction(immediate=True) as connection:
            self._task_row(connection, task_id)
            connection.execute(
                """INSERT INTO approvals(
                    approval_id, task_id, run_id, scope, state, confirmation_summary,
                    private_payload_json, requested_at, expires_at
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    identifier, task_id, run_id,
                    display_text(scope, field="approval_scope", maximum=100), "requested",
                    display_text(confirmation_summary, field="confirmation_summary", maximum=1_000),
                    private_json(private_payload), utc_now(), expires_at,
                ),
            )
            self._event(connection, task_id, "approval.requested", run_id=run_id,
                        display={"approvalId": identifier, "scope": scope})
        return identifier

    @staticmethod
    def _display_approval_row(row: sqlite3.Row) -> dict[str, Any]:
        """Return the allowlisted approval fields safe for desktop clients."""
        state = row["state"]
        actionable = state == "requested"
        if actionable and row["expires_at"]:
            try:
                expiry = dt.datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=dt.timezone.utc)
                actionable = expiry > dt.datetime.now(dt.timezone.utc)
            except ValueError:
                actionable = False
        return {
            "schemaVersion": 1,
            "approvalId": row["approval_id"],
            "taskId": row["task_id"],
            "runId": row["run_id"],
            "scope": row["scope"],
            "state": row["state"],
            "confirmationSummary": row["confirmation_summary"],
            "requestedAt": row["requested_at"],
            "resolvedAt": row["resolved_at"],
            "expiresAt": row["expires_at"],
            "capabilities": {
                "inspect": True,
                "approve": actionable,
                "reject": actionable,
            },
        }

    def display_approval(self, approval_id: str) -> dict[str, Any]:
        with self._reader() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown approval: {approval_id}")
        return self._display_approval_row(row)

    def list_display_approvals(
        self, *, state: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1_000:
            raise ValueError("limit must be between 1 and 1000")
        if state is not None and state not in {"requested", "approved", "declined", "expired"}:
            raise ValueError("unsupported approval state")
        query = "SELECT * FROM approvals"
        parameters: list[Any] = []
        if state is not None:
            query += " WHERE state = ?"
            parameters.append(state)
        query += " ORDER BY requested_at DESC LIMIT ?"
        parameters.append(limit)
        with self._reader() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._display_approval_row(row) for row in rows]

    def resolve_approval(self, approval_id: str, approved: bool) -> str:
        state = "approved" if approved else "declined"
        with self._transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown approval: {approval_id}")
            if row["state"] != "requested":
                raise StateTransitionError(f"approval is already {row['state']}")
            connection.execute(
                "UPDATE approvals SET state = ?, resolved_at = ? WHERE approval_id = ?",
                (state, utc_now(), approval_id),
            )
            self._event(connection, row["task_id"], f"approval.{state}", run_id=row["run_id"],
                        display={"approvalId": approval_id, "scope": row["scope"]})
        return state

    def resolve_pending_approval(self, approval_id: str, approved: bool) -> dict[str, Any]:
        """Atomically resolve a live approval and transition its waiting task."""
        decision = "approved" if approved else "declined"
        task_target = TaskState.READY if approved else TaskState.BLOCKED
        now = dt.datetime.now(dt.timezone.utc)
        now_text = now.isoformat(timespec="milliseconds")
        with self._transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown approval: {approval_id}")
            if row["state"] != "requested":
                raise StateTransitionError(f"approval is already {row['state']}")
            if row["expires_at"]:
                expiry = dt.datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=dt.timezone.utc)
                if expiry <= now:
                    raise StateTransitionError("approval has expired")
            task = self._task_row(connection, row["task_id"])
            current = TaskState(task["state"])
            if current is not TaskState.AWAITING_APPROVAL:
                raise StateTransitionError(
                    f"approval task is not awaiting approval (found {current.value})"
                )
            ensure_task_transition(current, task_target)
            connection.execute(
                "UPDATE approvals SET state = ?, resolved_at = ? WHERE approval_id = ?",
                (decision, now_text, approval_id),
            )
            connection.execute(
                """UPDATE tasks SET state = ?, updated_at = ?, terminal_code = ?,
                          terminal_summary = ? WHERE task_id = ?""",
                (
                    task_target.value, now_text,
                    None if approved else "approval_declined",
                    None if approved else "The requested operation was declined.",
                    row["task_id"],
                ),
            )
            self._event(
                connection, row["task_id"], f"approval.{decision}", run_id=row["run_id"],
                display={"approvalId": approval_id, "scope": row["scope"]},
            )
            self._event(
                connection, row["task_id"], "task.transition",
                display={"from": current.value, "to": task_target.value,
                         "code": None if approved else "approval_declined"},
            )
        return {
            "schemaVersion": 1,
            "approvalId": approval_id,
            "taskId": row["task_id"],
            "state": decision,
            "taskState": task_target.value,
        }

    def record_external_effect_intent(
        self,
        task_id: str,
        *,
        idempotency_key: str,
        provider: str,
        effect_type: str,
        display_summary: str,
        run_id: str | None = None,
        private_payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        key = display_text(idempotency_key, field="idempotency_key", maximum=500)
        with self._transaction(immediate=True) as connection:
            existing = connection.execute(
                "SELECT * FROM external_effects WHERE idempotency_key = ?", (key,)
            ).fetchone()
            if existing is not None:
                return dict(existing)
            self._task_row(connection, task_id)
            identifier = _id("effect")
            now = utc_now()
            connection.execute(
                """INSERT INTO external_effects(
                    effect_id, task_id, run_id, idempotency_key, provider, effect_type,
                    state, display_summary, private_payload_json, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    identifier, task_id, run_id, key,
                    display_text(provider, field="provider", maximum=100),
                    display_text(effect_type, field="effect_type", maximum=100), "intent",
                    display_text(display_summary, field="display_summary", maximum=1_000),
                    private_json(private_payload), now, now,
                ),
            )
            self._event(connection, task_id, "external_effect.intent", run_id=run_id,
                        display={"effectId": identifier, "provider": provider, "type": effect_type})
            return dict(connection.execute(
                "SELECT * FROM external_effects WHERE effect_id = ?", (identifier,)
            ).fetchone())

    def complete_external_effect(
        self, idempotency_key: str, *, external_id: str | None = None, failed: bool = False
    ) -> str:
        target = "failed" if failed else "completed"
        with self._transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM external_effects WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown external effect: {idempotency_key}")
            if row["state"] != "intent":
                if row["state"] == target and row["external_id"] == external_id:
                    return target
                raise StateTransitionError(f"external effect is already {row['state']}")
            safe_external = (
                display_text(external_id, field="external_id", maximum=500)
                if external_id is not None else None
            )
            connection.execute(
                """UPDATE external_effects SET state = ?, external_id = ?, updated_at = ?
                   WHERE idempotency_key = ?""",
                (target, safe_external, utc_now(), idempotency_key),
            )
            self._event(connection, row["task_id"], f"external_effect.{target}",
                        run_id=row["run_id"], display={"effectId": row["effect_id"],
                                                       "externalId": safe_external})
        return target

    def retry_external_effect(self, idempotency_key: str) -> str:
        """Reopen one failed stable effect for an explicitly authorized retry."""
        with self._transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM external_effects WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown external effect: {idempotency_key}")
            if row["state"] != "failed":
                raise StateTransitionError(
                    f"external effect is not retryable from {row['state']}"
                )
            connection.execute(
                """UPDATE external_effects SET state='intent', external_id=NULL,
                          updated_at=? WHERE idempotency_key=?""",
                (utc_now(), idempotency_key),
            )
            self._event(
                connection, row["task_id"], "external_effect.retried",
                run_id=row["run_id"], display={"effectId": row["effect_id"]},
            )
        return "intent"

    def add_dependency(self, task_id: str, depends_on_task_id: str) -> None:
        if task_id == depends_on_task_id:
            raise WorkflowError("a task cannot depend on itself")
        with self._transaction(immediate=True) as connection:
            self._task_row(connection, task_id)
            self._task_row(connection, depends_on_task_id)
            cycle = connection.execute(
                """WITH RECURSIVE descendants(task_id) AS (
                       SELECT task_id FROM task_dependencies WHERE depends_on_task_id = ?
                       UNION
                       SELECT d.task_id FROM task_dependencies d
                       JOIN descendants x ON d.depends_on_task_id = x.task_id
                   ) SELECT 1 FROM descendants WHERE task_id = ? LIMIT 1""",
                (task_id, depends_on_task_id),
            ).fetchone()
            if cycle is not None:
                raise WorkflowError("dependency would create a cycle")
            connection.execute(
                """INSERT OR IGNORE INTO task_dependencies(task_id, depends_on_task_id, created_at)
                   VALUES(?,?,?)""",
                (task_id, depends_on_task_id, utc_now()),
            )
            self._event(connection, task_id, "dependency.added",
                        display={"dependsOnTaskId": depends_on_task_id})

    def dependency_states(self, task_id: str) -> dict[str, TaskState]:
        with self._reader() as connection:
            rows = connection.execute(
                """SELECT t.task_id, t.state FROM task_dependencies d
                   JOIN tasks t ON t.task_id = d.depends_on_task_id
                   WHERE d.task_id = ?""",
                (task_id,),
            ).fetchall()
        return {row["task_id"]: TaskState(row["state"]) for row in rows}

    def children(self, parent_task_id: str) -> list[dict[str, Any]]:
        with self._reader() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE parent_task_id = ? ORDER BY created_at",
                (parent_task_id,),
            ).fetchall()
        return [self._display_task_row(row) for row in rows]

    def acquire_lease_set(
        self,
        *,
        holder_task_id: str,
        holder_run_id: str | None,
        resource_groups: Sequence[Sequence[str]],
        fixed_resources: Sequence[str] = (),
        ttl_seconds: float = 30.0,
        kind: str = "scheduler",
    ) -> list[dict[str, str]]:
        if ttl_seconds <= 0:
            raise ValueError("lease TTL must be positive")
        now = utc_now()
        expires = _future(ttl_seconds)
        acquired: list[dict[str, str]] = []
        with self._transaction(immediate=True) as connection:
            self._task_row(connection, holder_task_id)
            connection.execute("DELETE FROM leases WHERE expires_at <= ?", (now,))
            resources: list[str] = []
            for group in resource_groups:
                candidates = [str(candidate) for candidate in group]
                if not candidates:
                    raise ValueError("lease resource group cannot be empty")
                placeholders = ",".join("?" for _ in candidates)
                used = {row[0] for row in connection.execute(
                    f"SELECT resource_key FROM leases WHERE resource_key IN ({placeholders})",
                    candidates,
                ).fetchall()}
                selected = next((candidate for candidate in candidates if candidate not in used), None)
                if selected is None:
                    raise LeaseConflict(f"no resource available in group: {candidates[0]}")
                resources.append(selected)
            resources.extend(str(resource) for resource in fixed_resources)
            if len(resources) != len(set(resources)):
                raise ValueError("duplicate lease resource requested")
            for resource in resources:
                token = uuid.uuid4().hex
                try:
                    connection.execute(
                        """INSERT INTO leases(
                            resource_key, holder_task_id, holder_run_id, token, kind,
                            acquired_at, heartbeat_at, expires_at
                        ) VALUES(?,?,?,?,?,?,?,?)""",
                        (resource, holder_task_id, holder_run_id, token, kind, now, now, expires),
                    )
                except sqlite3.IntegrityError as error:
                    raise LeaseConflict(f"resource is already leased: {resource}") from error
                acquired.append({"resourceKey": resource, "token": token, "expiresAt": expires})
            self._event(connection, holder_task_id, "lease.acquired", run_id=holder_run_id,
                        display={"count": len(acquired), "kind": kind})
        return acquired

    def renew_holder_leases(
        self, holder_task_id: str, holder_run_id: str | None, *, ttl_seconds: float = 30.0
    ) -> int:
        now = utc_now()
        expires = _future(ttl_seconds)
        with self._transaction(immediate=True) as connection:
            if holder_run_id is None:
                cursor = connection.execute(
                    """UPDATE leases SET heartbeat_at = ?, expires_at = ?
                       WHERE holder_task_id = ? AND holder_run_id IS NULL""",
                    (now, expires, holder_task_id),
                )
            else:
                cursor = connection.execute(
                    """UPDATE leases SET heartbeat_at = ?, expires_at = ?
                       WHERE holder_task_id = ? AND holder_run_id = ?""",
                    (now, expires, holder_task_id, holder_run_id),
                )
            return cursor.rowcount

    def release_holder_leases(self, holder_task_id: str, holder_run_id: str | None = None) -> int:
        with self._transaction(immediate=True) as connection:
            if holder_run_id is None:
                cursor = connection.execute(
                    "DELETE FROM leases WHERE holder_task_id = ?", (holder_task_id,)
                )
            else:
                cursor = connection.execute(
                    "DELETE FROM leases WHERE holder_task_id = ? AND holder_run_id = ?",
                    (holder_task_id, holder_run_id),
                )
            count = cursor.rowcount
            if count:
                self._event(connection, holder_task_id, "lease.released", run_id=holder_run_id,
                            display={"count": count})
            return count

    def leases_for_holder(self, holder_task_id: str, holder_run_id: str | None = None) -> list[dict[str, Any]]:
        with self._reader() as connection:
            if holder_run_id is None:
                rows = connection.execute(
                    "SELECT * FROM leases WHERE holder_task_id = ? ORDER BY resource_key",
                    (holder_task_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT * FROM leases WHERE holder_task_id = ? AND holder_run_id = ?
                       ORDER BY resource_key""",
                    (holder_task_id, holder_run_id),
                ).fetchall()
        return [dict(row) for row in rows]

    def lease_for_resource(self, resource_key: str) -> dict[str, Any] | None:
        with self._reader() as connection:
            row = connection.execute(
                "SELECT * FROM leases WHERE resource_key = ? AND expires_at > ?",
                (resource_key, utc_now()),
            ).fetchone()
        return dict(row) if row is not None else None
