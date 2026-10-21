"""ベンチマーク履歴と基本メトリクスをSQLiteへ永続化する。"""

from __future__ import annotations

import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .models import (
    ApiCallResult,
    BenchmarkCase,
    BenchmarkDataset,
    QualityEvaluation,
)

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS api_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    change_summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS datasets (
    generation TEXT PRIMARY KEY,
    manifest_path TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    dataset_hash TEXT NOT NULL,
    case_count INTEGER NOT NULL,
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
    environment_json TEXT NOT NULL,
    suite_id INTEGER REFERENCES benchmark_suites(id),
    planned_trials INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS benchmark_suites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL REFERENCES api_versions(id),
    dataset_generation TEXT NOT NULL REFERENCES datasets(generation),
    mode TEXT NOT NULL,
    trials_per_case INTEGER NOT NULL,
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


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


class BenchmarkStorage:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate(connection)

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(benchmark_runs)")
        }
        if "suite_id" not in columns:
            connection.execute("ALTER TABLE benchmark_runs ADD COLUMN suite_id INTEGER")
        if "planned_trials" not in columns:
            connection.execute(
                "ALTER TABLE benchmark_runs "
                "ADD COLUMN planned_trials INTEGER NOT NULL DEFAULT 1"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS benchmark_runs_suite_idx "
            "ON benchmark_runs(suite_id, id)"
        )

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

    def register_dataset(self, dataset: BenchmarkDataset) -> None:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT manifest_hash, dataset_hash FROM datasets WHERE generation = ?",
                (dataset.generation,),
            ).fetchone()
            if existing:
                if (
                    existing["manifest_hash"] != dataset.manifest_hash
                    or existing["dataset_hash"] != dataset.dataset_hash
                ):
                    raise ValueError(
                        "同じデータセット世代に異なるmanifestは登録できません。"
                    )
                return
            connection.execute(
                """
                INSERT INTO datasets(
                    generation, manifest_path, manifest_hash, dataset_hash,
                    case_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset.generation,
                    str(dataset.manifest_path),
                    dataset.manifest_hash,
                    dataset.dataset_hash,
                    len(dataset.cases),
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
        suite_id: int | None = None,
        planned_trials: int = 1,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO benchmark_runs(
                    version_id, case_id, input_hash, api_url, status,
                    started_at, environment_json, suite_id, planned_trials
                ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?)
                """,
                (
                    version_id,
                    case.case_id,
                    case.input_hash,
                    api_url,
                    _now(),
                    _json(environment),
                    suite_id,
                    planned_trials,
                ),
            )
            return int(cursor.lastrowid)

    def create_suite(
        self,
        *,
        version_id: int,
        dataset: BenchmarkDataset,
        mode: str,
        trials_per_case: int,
        api_url: str,
        environment: dict,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO benchmark_suites(
                    version_id, dataset_generation, mode, trials_per_case,
                    api_url, status, started_at, environment_json
                ) VALUES (?, ?, ?, ?, ?, 'running', ?, ?)
                """,
                (
                    version_id,
                    dataset.generation,
                    mode,
                    trials_per_case,
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

    def set_suite_status(self, suite_id: int, status: str) -> None:
        completed_at = _now() if status in {"completed", "interrupted"} else None
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE benchmark_suites
                SET status = ?, completed_at = ?
                WHERE id = ?
                """,
                (status, completed_at, suite_id),
            )

    def record_trial(
        self,
        *,
        run_id: int,
        result: ApiCallResult,
        input_path: Path,
        response_path: Path | None,
        trial_number: int = 1,
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?)
                """,
                (
                    run_id,
                    trial_number,
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

    def get_suite(self, suite_id: int) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT s.*, v.name AS version_name, v.change_summary,
                       d.manifest_path, d.manifest_hash, d.dataset_hash,
                       d.case_count
                FROM benchmark_suites s
                JOIN api_versions v ON v.id = s.version_id
                JOIN datasets d ON d.generation = s.dataset_generation
                WHERE s.id = ?
                """,
                (suite_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"benchmark suite {suite_id} は存在しません。")
        value = dict(row)
        value["environment"] = json.loads(value.pop("environment_json"))
        return value

    def get_suite_work_items(self, suite_id: int) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT r.id AS run_id, r.case_id, r.planned_trials, r.status,
                       c.staff_count, c.pattern, c.seed, c.input_hash,
                       GROUP_CONCAT(t.trial_number) AS completed_trial_numbers
                FROM benchmark_runs r
                JOIN benchmark_cases c ON c.case_id = r.case_id
                LEFT JOIN benchmark_trials t ON t.run_id = r.id
                WHERE r.suite_id = ?
                GROUP BY r.id
                ORDER BY c.staff_count, c.pattern
                """,
                (suite_id,),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            raw_numbers = item.pop("completed_trial_numbers")
            item["completed_trial_numbers"] = {
                int(value) for value in raw_numbers.split(",")
            } if raw_numbers else set()
            items.append(item)
        return items

    def list_suites(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT s.id, s.mode, s.status, s.started_at, s.completed_at,
                       s.dataset_generation, s.trials_per_case,
                       v.name AS version_name,
                       COUNT(t.id) AS completed_trials,
                       COUNT(DISTINCT r.id) * s.trials_per_case AS total_trials
                FROM benchmark_suites s
                JOIN api_versions v ON v.id = s.version_id
                LEFT JOIN benchmark_runs r ON r.suite_id = s.id
                LEFT JOIN benchmark_trials t ON t.run_id = r.id
                GROUP BY s.id
                ORDER BY s.id DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_suite_summary(self, suite_id: int) -> dict:
        suite = self.get_suite(suite_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT c.case_id, c.name AS case_name, c.staff_count, c.pattern,
                       r.id AS run_id, r.planned_trials,
                       COUNT(t.id) AS completed_trials,
                       SUM(CASE WHEN t.status = 'success' THEN 1 ELSE 0 END)
                           AS successful_trials,
                       AVG(t.elapsed_seconds) AS average_elapsed_seconds,
                       MIN(t.elapsed_seconds) AS minimum_elapsed_seconds,
                       MAX(t.elapsed_seconds) AS maximum_elapsed_seconds,
                       AVG(q.hard_violation_count) AS average_hard_violations
                FROM benchmark_runs r
                JOIN benchmark_cases c ON c.case_id = r.case_id
                LEFT JOIN benchmark_trials t ON t.run_id = r.id
                LEFT JOIN quality_metrics q ON q.trial_id = t.id
                WHERE r.suite_id = ?
                GROUP BY r.id
                ORDER BY c.staff_count, c.pattern
                """,
                (suite_id,),
            ).fetchall()
            elapsed_rows = connection.execute(
                """
                SELECT t.elapsed_seconds, t.status
                FROM benchmark_trials t
                JOIN benchmark_runs r ON r.id = t.run_id
                WHERE r.suite_id = ?
                ORDER BY t.elapsed_seconds
                """,
                (suite_id,),
            ).fetchall()
        case_results = [dict(row) for row in rows]
        elapsed = [float(row["elapsed_seconds"]) for row in elapsed_rows]
        successful = sum(row["status"] == "success" for row in elapsed_rows)
        completed = len(elapsed_rows)
        total = len(case_results) * int(suite["trials_per_case"])
        return {
            **suite,
            "completed_trials": completed,
            "total_trials": total,
            "successful_trials": successful,
            "success_rate": successful / completed if completed else None,
            "average_elapsed_seconds": sum(elapsed) / completed if completed else None,
            "median_elapsed_seconds": _percentile(elapsed, 0.5),
            "p95_elapsed_seconds": _percentile(elapsed, 0.95),
            "case_results": case_results,
        }

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
                WHERE r.suite_id IS NULL
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
