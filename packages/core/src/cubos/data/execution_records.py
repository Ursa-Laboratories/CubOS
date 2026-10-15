"""Run and step records on the campaign database connection."""

from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
from typing import Any, Iterator

RUN_TERMINAL = ("completed", "failed", "cancelled", "interrupted")
STEP_TERMINAL = RUN_TERMINAL + ("skipped",)
RUN_STATUSES = RUN_TERMINAL + ("queued", "running")
STEP_STATUSES = STEP_TERMINAL + ("running",)
MEASUREMENT_TABLES = (
    "uvvis",
    "filmetrics",
    "uv_curing",
    "camera",
    "asmi",
    "potentiostat",
)


def migrate_execution_records(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        raise RuntimeError("Migration requires no existing SQLite transaction")
    schema = """
    CREATE TABLE IF NOT EXISTS protocol_runs (
      run_id TEXT PRIMARY KEY, campaign_id INTEGER REFERENCES campaigns(id),
      status TEXT NOT NULL, started_at TEXT, ended_at TEXT, duration_ns INTEGER,
      recovered_at TEXT, metadata_json TEXT NOT NULL, details_json TEXT,
      recording_errors_json TEXT, terminal_sequence INTEGER,
      next_sequence INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS step_executions (
      step_execution_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES protocol_runs(run_id),
      parent_step_execution_id TEXT REFERENCES step_executions(step_execution_id),
      sequence INTEGER NOT NULL, command TEXT NOT NULL, source_json TEXT NOT NULL,
      parameters_json TEXT NOT NULL, iteration_index INTEGER, started_at TEXT,
      ended_at TEXT, duration_ns INTEGER, status TEXT NOT NULL, details_json TEXT,
      recovered_at TEXT, terminal_sequence INTEGER, UNIQUE(run_id, sequence));
    CREATE INDEX IF NOT EXISTS step_executions_parent ON step_executions(parent_step_execution_id);
    CREATE INDEX IF NOT EXISTS protocol_runs_status ON protocol_runs(status);
    CREATE INDEX IF NOT EXISTS protocol_runs_campaign ON protocol_runs(campaign_id);
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        for statement in schema.split(";"):
            if statement.strip():
                conn.execute(statement)
        _migrate_measurements(conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _migrate_measurements(conn: sqlite3.Connection) -> None:
    for kind in MEASUREMENT_TABLES:
        table = kind + "_measurements"
        columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, spec in [
            ("step_execution_id", "TEXT REFERENCES step_executions(step_execution_id)"),
            ("metadata_json", "TEXT"),
        ]:
            if name not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {spec}")
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_step ON {table}(step_execution_id)"
        )


def _json(value: Any) -> str:
    return json.dumps(value, allow_nan=False)


class ExecutionRecords:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        if self._conn.in_transaction:
            raise RuntimeError(
                "Execution records require no existing SQLite transaction"
            )
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise

    def _rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        cursor = self._conn.execute(sql, params)
        names = [c[0] for c in cursor.description]
        result = []
        for row in cursor:
            record = dict(zip(names, row))
            for name in list(record):
                if name.endswith("_json"):
                    value = record.pop(name)
                    record[name[:-5]] = json.loads(value) if value is not None else None
            record.pop("next_sequence", None)
            result.append(record)
        return result

    def create_run(
        self,
        run_id: str,
        *,
        campaign_id: int | None = None,
        metadata: dict,
        status: str = "running",
        started_at: str | None = None,
    ) -> None:
        if status not in RUN_STATUSES:
            raise ValueError("Invalid run status")
        with self._transaction():
            self._conn.execute(
                "INSERT INTO protocol_runs(run_id,campaign_id,metadata_json,status,started_at) VALUES(?,?,?,?,?)",
                (run_id, campaign_id, _json(metadata), status, started_at),
            )

    def update_run(self, run_id: str, **fields: Any) -> None:
        allowed = {
            "campaign_id",
            "metadata",
            "status",
            "started_at",
            "ended_at",
            "duration_ns",
            "details",
            "recording_errors",
            "recovered_at",
            "terminal_sequence",
        }
        if fields.keys() - allowed:
            raise ValueError("Unsupported run fields")
        with self._transaction():
            existing = self.get_run(run_id)
            if existing is None:
                raise ValueError(f"Run {run_id} not found")
            if fields.get("status", existing["status"]) not in RUN_STATUSES:
                raise ValueError("Invalid run status")
            if fields.get("duration_ns") is not None and fields["duration_ns"] < 0:
                raise ValueError("Duration must be nonnegative")
            if existing["status"] in RUN_TERMINAL:
                immutable = set(fields) - {"recording_errors", "metadata"}
                if any(fields[key] != existing[key] for key in immutable):
                    raise ValueError("Terminal run cannot change execution fields")
                if "metadata" in fields:
                    previous = existing["metadata"]
                    replacement = fields["metadata"]
                    if any(
                        replacement.get(key) != value for key, value in previous.items()
                    ):
                        raise ValueError(
                            "Terminal run metadata cannot replace recorded values"
                        )
                    if (
                        set(replacement)
                        - set(previous)
                        - {"recording_errors", "projection_errors"}
                    ):
                        raise ValueError(
                            "Terminal run only accepts additional recording errors"
                        )
            if "campaign_id" in fields:
                for kind in MEASUREMENT_TABLES:
                    mismatch = self._conn.execute(
                        f"SELECT 1 FROM {kind}_measurements m JOIN experiments e ON e.id=m.experiment_id "
                        "JOIN step_executions s ON s.step_execution_id=m.step_execution_id "
                        "WHERE s.run_id=? AND e.campaign_id IS NOT ? LIMIT 1",
                        (run_id, fields["campaign_id"]),
                    ).fetchone()
                    if mismatch:
                        raise ValueError("Run campaign must match linked measurements")
            if (
                fields.get("status") in RUN_TERMINAL
                and existing["status"] not in RUN_TERMINAL
            ):
                sequence = self._conn.execute(
                    "SELECT next_sequence FROM protocol_runs WHERE run_id=?", (run_id,)
                ).fetchone()[0]
                fields["terminal_sequence"] = sequence
                self._conn.execute(
                    "UPDATE protocol_runs SET next_sequence=next_sequence+1 WHERE run_id=?",
                    (run_id,),
                )
            if fields:
                json_fields = {"metadata", "details", "recording_errors"}
                assignments = [
                    f"{key}_json=?" if key in json_fields else f"{key}=?"
                    for key in fields
                ]
                values = [
                    _json(v) if k in json_fields and v is not None else v
                    for k, v in fields.items()
                ]
                self._conn.execute(
                    "UPDATE protocol_runs SET "
                    + ",".join(assignments)
                    + " WHERE run_id=?",
                    values + [run_id],
                )

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        ended_at: str | None = None,
        duration_ns: int | None = None,
        details: Any = None,
        recording_errors: Any = None,
        recovered_at: str | None = None,
    ) -> None:
        if status not in RUN_TERMINAL:
            raise ValueError("Run finish status must be terminal")
        self.update_run(
            run_id,
            status=status,
            ended_at=ended_at,
            duration_ns=duration_ns,
            details=details,
            recording_errors=recording_errors,
            recovered_at=recovered_at,
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM protocol_runs WHERE run_id=?", (run_id,))
        return rows[0] if rows else None

    def list_runs(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        self._page(limit, offset)
        return self._rows(
            "SELECT * FROM protocol_runs ORDER BY started_at DESC, run_id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )

    @staticmethod
    def _page(limit: int, offset: int) -> None:
        if limit < 1 or offset < 0:
            raise ValueError(
                "Pagination requires positive limit and nonnegative offset"
            )

    def start_step(
        self,
        step_execution_id: str,
        run_id: str,
        *,
        parent_step_execution_id: str | None = None,
        command: str,
        source: dict,
        parameters: dict,
        iteration_index: int | None = None,
        started_at: str | None,
    ) -> dict[str, Any]:
        with self._transaction():
            run = self._conn.execute(
                "SELECT next_sequence,status FROM protocol_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if run is None or run[1] in RUN_TERMINAL:
                raise ValueError("Step requires an existing nonterminal run")
            if parent_step_execution_id is not None:
                parent = self._conn.execute(
                    "SELECT run_id,status FROM step_executions WHERE step_execution_id=?",
                    (parent_step_execution_id,),
                ).fetchone()
                if parent is None or parent[0] != run_id or parent[1] in STEP_TERMINAL:
                    raise ValueError("Parent step must belong to the same run")
            self._conn.execute(
                "INSERT INTO step_executions(step_execution_id,run_id,parent_step_execution_id,sequence,command,source_json,parameters_json,iteration_index,started_at,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    step_execution_id,
                    run_id,
                    parent_step_execution_id,
                    run[0],
                    command,
                    _json(source),
                    _json(parameters),
                    iteration_index,
                    started_at,
                    "running",
                ),
            )
            self._conn.execute(
                "UPDATE protocol_runs SET next_sequence=next_sequence+1 WHERE run_id=?",
                (run_id,),
            )
        return self._rows(
            "SELECT * FROM step_executions WHERE step_execution_id=?",
            (step_execution_id,),
        )[0]

    def get_step(self, step_execution_id: str) -> dict[str, Any] | None:
        rows = self._rows(
            "SELECT * FROM step_executions WHERE step_execution_id=?",
            (step_execution_id,),
        )
        return rows[0] if rows else None

    def finish_step(
        self,
        step_execution_id: str,
        *,
        status: str,
        ended_at: str | None = None,
        duration_ns: int | None = None,
        details: Any = None,
        recovered_at: str | None = None,
    ) -> None:
        if status not in STEP_TERMINAL:
            raise ValueError("Step finish status must be terminal")
        if duration_ns is not None and duration_ns < 0:
            raise ValueError("Duration must be nonnegative")
        with self._transaction():
            existing = self.get_step(step_execution_id)
            if existing is None:
                raise ValueError("Step not found")
            fields = dict(
                status=status,
                ended_at=ended_at,
                duration_ns=duration_ns,
                details=details,
                recovered_at=recovered_at,
            )
            if existing["status"] in STEP_TERMINAL:
                if any(existing[key] != value for key, value in fields.items()):
                    raise ValueError("Terminal step cannot change")
                return
            run_id = existing["run_id"]
            sequence = self._conn.execute(
                "SELECT next_sequence FROM protocol_runs WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            self._conn.execute(
                "UPDATE step_executions SET status=?,ended_at=?,duration_ns=?,details_json=?,recovered_at=?,terminal_sequence=? WHERE step_execution_id=?",
                (
                    status,
                    ended_at,
                    duration_ns,
                    _json(details) if details is not None else None,
                    recovered_at,
                    sequence,
                    step_execution_id,
                ),
            )
            self._conn.execute(
                "UPDATE protocol_runs SET next_sequence=next_sequence+1 WHERE run_id=?",
                (run_id,),
            )

    def update_step_parameters(self, step_execution_id: str, parameters: dict) -> None:
        with self._transaction():
            rows = self._rows(
                "SELECT * FROM step_executions WHERE step_execution_id=?",
                (step_execution_id,),
            )
            if not rows:
                raise ValueError("Step not found")
            if rows[0]["status"] in STEP_TERMINAL:
                raise ValueError("Terminal step cannot change parameters")
            merged = dict(rows[0]["parameters"])
            merged.update(parameters)
            self._conn.execute(
                "UPDATE step_executions SET parameters_json=? WHERE step_execution_id=?",
                (_json(merged), step_execution_id),
            )

    def list_steps(
        self, run_id: str, *, after_sequence: int = 0, limit: int = 100
    ) -> list[dict[str, Any]]:
        self._page(limit, after_sequence)
        return self._rows(
            "SELECT * FROM step_executions WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?",
            (run_id, after_sequence, limit),
        )

    def recover_run(self, run_id: str, recovered_at: str) -> None:
        with self._transaction():
            for table, key in [
                ("protocol_runs", "run_id"),
                ("step_executions", "run_id"),
            ]:
                terminal = RUN_TERMINAL if table == "protocol_runs" else STEP_TERMINAL
                placeholders = ",".join("?" for _ in terminal)
                self._conn.execute(
                    f"UPDATE {table} SET status='interrupted',ended_at=NULL,duration_ns=NULL,recovered_at=?,details_json=? WHERE {key}=? AND status NOT IN ({placeholders})",
                    (recovered_at, _json({"kind": "owner_lost"}), run_id, *terminal),
                )
