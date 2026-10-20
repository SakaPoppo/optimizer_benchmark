"""ベンチマーク履歴と基本メトリクスをSQLiteへ永続化する。"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .models import ApiCallResult, BenchmarkCase, QualityEvaluation

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS api_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    change_summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS benchmark_cases (
    case_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    staff_count INTEGER NOT NULL,
    pattern TEXT NOT NULL,
    dataset_generation TEXT NOT NULL,
    seed INTEGER NOT NULL,
    source_path TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS benchmark_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL REFERENCES api_versions(id),
    case_id TEXT NOT NULL REFERENCES benchmark_cases(case_id),
    input_hash TEXT NOT NULL,
    api_url TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    environment_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS benchmark_trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES benchmark_runs(id),
    trial_number INTEGER NOT NULL,
    status TEXT NOT NULL,
    http_status INTEGER,
    elapsed_seconds REAL NOT NULL,
    response_status TEXT,
    solver_status TEXT,
    error_type TEXT,
    error_message TEXT,
    input_path TEXT NOT NULL,
    response_path TEXT,
    phase_results_json TEXT NOT NULL,
    issues_json TEXT NOT NULL,
    internal_elapsed_seconds REAL,
    cpu_percent REAL,
    peak_memory_mb REAL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, trial_number)
);

CREATE TABLE IF NOT EXISTS quality_metrics (
    trial_id INTEGER PRIMARY KEY REFERENCES benchmark_trials(id),
    evaluator_version TEXT NOT NULL,
    day_counts_json TEXT NOT NULL,
    day_staffing_deltas_json TEXT NOT NULL,
    night_counts_json TEXT NOT NULL,
    maximum_consecutive_work_days INTEGER NOT NULL,
    hard_violation_count INTEGER NOT NULL,
    violations_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS benchmark_runs_version_idx
ON benchmark_runs(version_id, started_at);

CREATE INDEX IF NOT EXISTS benchmark_trials_run_idx
ON benchmark_trials(run_id, trial_number);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class BenchmarkStorage:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def get_or_create_version(self, name: str, change_summary: str) -> int:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id, change_summary FROM api_versions WHERE name = ?",
                (name,),
            ).fetchone()
            if existing:
                if existing["change_summary"] != change_summary:
                    raise ValueError(
                        "同じバージョン名に異なる変更概要は登録できません。"
                    )
                return int(existing["id"])
            cursor = connection.execute(
                """
                INSERT INTO api_versions(name, change_summary, created_at)
                VALUES (?, ?, ?)
                """,
                (name, change_summary, _now()),
            )
            return int(cursor.lastrowid)

    def register_case(self, case: BenchmarkCase) -> None:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT input_hash FROM benchmark_cases WHERE case_id = ?",
                (case.case_id,),
            ).fetchone()
            if existing:
                if existing["input_hash"] != case.input_hash:
                    raise ValueError(
                        "既存ケースと入力ハッシュが異なります。新しいcase_idが必要です。"
                    )
                return
            connection.execute(
                """
                INSERT INTO benchmark_cases(
                    case_id, name, staff_count, pattern, dataset_generation,
                    seed, source_path, input_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case.case_id,
                    case.name,
                    case.staff_count,
                    case.pattern,
                    case.dataset_generation,
                    case.seed,
                    str(case.source_path),
                    case.input_hash,
                    _now(),
                ),
            )

    def create_run(
        self,
        *,
        version_id: int,
        case: BenchmarkCase,
        api_url: str,
        environment: dict,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO benchmark_runs(
                    version_id, case_id, input_hash, api_url, status,
                    started_at, environment_json
                ) VALUES (?, ?, ?, ?, 'running', ?, ?)
                """,
                (
                    version_id,
                    case.case_id,
                    case.input_hash,
                    api_url,
                    _now(),
                    _json(environment),
                ),
            )
            return int(cursor.lastrowid)

    def finish_run(self, run_id: int, status: str = "completed") -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE benchmark_runs
                SET status = ?, completed_at = ?
                WHERE id = ?
                """,
                (status, _now(), run_id),
            )

    def record_trial(
        self,
        *,
        run_id: int,
        result: ApiCallResult,
        input_path: Path,
        response_path: Path | None,
    ) -> int:
        response = result.response_body or {}
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO benchmark_trials(
                    run_id, trial_number, status, http_status, elapsed_seconds,
                    response_status, solver_status, error_type, error_message,
                    input_path, response_path, phase_results_json, issues_json,
                    internal_elapsed_seconds, cpu_percent, peak_memory_mb, created_at
                ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?)
                """,
                (
                    run_id,
                    result.status,
                    result.http_status,
                    result.elapsed_seconds,
                    response.get("status"),
                    result.solver_status,
                    result.error_type,
                    result.error_message,
                    str(input_path),
                    str(response_path) if response_path else None,
                    _json(response.get("phase_results", [])),
                    _json(response.get("issues", [])),
                    _now(),
                ),
            )
            return int(cursor.lastrowid)

    def record_quality(self, trial_id: int, quality: QualityEvaluation) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO quality_metrics(
                    trial_id, evaluator_version, day_counts_json,
                    day_staffing_deltas_json, night_counts_json,
                    maximum_consecutive_work_days, hard_violation_count,
                    violations_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trial_id,
                    quality.evaluator_version,
                    _json(quality.day_counts),
                    _json(quality.day_staffing_deltas),
                    _json(quality.night_counts),
                    quality.maximum_consecutive_work_days,
                    quality.hard_violation_count,
                    _json(quality.violations),
                ),
            )

    def list_runs(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT r.id, r.status, r.started_at, v.name AS version_name,
                       c.name AS case_name
                FROM benchmark_runs r
                JOIN api_versions v ON v.id = r.version_id
                JOIN benchmark_cases c ON c.case_id = r.case_id
                ORDER BY r.id DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_run_report(self, run_id: int) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    r.id AS run_id, r.status AS run_status, r.started_at,
                    r.completed_at, r.api_url, r.input_hash,
                    r.environment_json, v.name AS version_name,
                    v.change_summary, c.case_id, c.name AS case_name,
                    c.staff_count, c.pattern, c.dataset_generation, c.seed,
                    t.id AS trial_id, t.status AS trial_status,
                    t.http_status, t.elapsed_seconds, t.response_status,
                    t.solver_status, t.error_type, t.error_message,
                    t.input_path, t.response_path, t.phase_results_json,
                    t.issues_json, t.internal_elapsed_seconds,
                    t.cpu_percent, t.peak_memory_mb,
                    q.evaluator_version, q.day_counts_json,
                    q.day_staffing_deltas_json, q.night_counts_json,
                    q.maximum_consecutive_work_days,
                    q.hard_violation_count, q.violations_json
                FROM benchmark_runs r
                JOIN api_versions v ON v.id = r.version_id
                JOIN benchmark_cases c ON c.case_id = r.case_id
                LEFT JOIN benchmark_trials t ON t.run_id = r.id
                LEFT JOIN quality_metrics q ON q.trial_id = t.id
                WHERE r.id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"benchmark run {run_id} は存在しません。")
        report = dict(row)
        for key in (
            "environment_json",
            "phase_results_json",
            "issues_json",
            "day_counts_json",
            "day_staffing_deltas_json",
            "night_counts_json",
            "violations_json",
        ):
            raw_value = report.pop(key)
            report[key.removesuffix("_json")] = (
                json.loads(raw_value) if raw_value is not None else None
            )
        return report
