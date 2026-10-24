"""Runner、HTTPクライアント、評価器が共有する値オブジェクト。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    name: str
    staff_count: int
    pattern: str
    dataset_generation: str
    seed: int
    source_path: Path
    input_hash: str
    payload: dict


@dataclass(frozen=True)
class BenchmarkDataset:
    generation: str
    manifest_path: Path
    manifest_hash: str
    dataset_hash: str
    cases: tuple[BenchmarkCase, ...]


@dataclass(frozen=True)
class ApiCallResult:
    status: str
    elapsed_seconds: float
    http_status: int | None = None
    response_body: dict | None = None
    error_type: str | None = None
    error_message: str | None = None

    @property
    def generation_succeeded(self) -> bool:
        return self.status == "success"

    @property
    def solver_status(self) -> str | None:
        if not self.response_body:
            return None
        value = self.response_body.get("solver_status")
        return str(value) if value is not None else None


@dataclass(frozen=True)
class QualityEvaluation:
    evaluator_version: str
    day_counts: dict[str, int]
    day_staffing_deltas: dict[str, int]
    night_counts: dict[int, int]
    maximum_consecutive_work_days: int
    hard_violation_count: int
    violations: list[dict]
    day_ability_totals: dict[str, int]
    night_ability_totals: dict[str, int]
    day_ability_deviation_percentages: dict[str, float]
    night_ability_deviation_percentages: dict[str, float]
    shift_counts_by_staff: dict[int, dict[str, int]]
    consecutive_work_days_by_staff: dict[int, int]
    night_count_standard_deviation: float
    work_count_difference: int
    off_count_difference: int
