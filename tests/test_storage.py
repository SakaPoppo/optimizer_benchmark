from __future__ import annotations

import json
from pathlib import Path

import httpx

from optimizer_benchmark.artifacts import ArtifactStore
from optimizer_benchmark.datasets import load_fixed_case
from optimizer_benchmark.models import (
    ApiCallResult,
    BenchmarkDataset,
    QualityEvaluation,
)
from optimizer_benchmark.runner import BenchmarkRunner
from optimizer_benchmark.storage import BenchmarkStorage

from .helpers import successful_response


def test_runner_persists_trial_quality_and_artifacts(tmp_path) -> None:
    case_path = tmp_path / "case.json"
    project_case = Path("data/cases/demo_20_baseline_v1.json")
    case_payload = json.loads(project_case.read_text(encoding="utf-8"))
    case_path.write_text(
        json.dumps(case_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    response = {
        **successful_response(
            {
                "month_dates": case_payload["month_dates"],
            }
        ),
        "shifts": [
            {
                "staff_id": staff["id"],
                "date": target_date,
                "shift_type": "off",
            }
            for staff in case_payload["staff_members"]
            for target_date in case_payload["month_dates"]
        ],
    }
    storage = BenchmarkStorage(tmp_path / "benchmark.db")
    runner = BenchmarkRunner(
        storage=storage,
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        api_url="http://optimizer.test",
        api_key="test-key",
        timeout_seconds=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=response)
        ),
    )

    report = runner.run_once(
        case_path=case_path,
        version_name="test-version",
        change_summary="test summary",
    )

    assert report["trial_status"] == "success"
    assert report["evaluator_version"] == "phase3-v1"
    assert report["hard_violation_count"] > 0
    assert report["internal_elapsed_seconds"] == 0.4
    assert report["cpu_time_seconds"] == 0.6
    assert report["cpu_percent"] == 150.0
    assert report["peak_memory_mb"] == 128.0
    assert report["cpu_limit"] == 2.0
    assert report["optimizer_worker_count"] == 2
    assert report["ortools_version"] == "9.14.0"
    assert report["night_count_standard_deviation"] == 0
    assert report["phase_results"][0]["wall_time_seconds"] == 0.2
    assert Path(report["input_path"]).exists()
    assert Path(report["response_path"]).exists()
    assert BenchmarkStorage(tmp_path / "benchmark.db").list_runs()[0]["id"] == 1


def test_version_history_is_not_overwritten(tmp_path) -> None:
    storage = BenchmarkStorage(tmp_path / "benchmark.db")
    storage.get_or_create_version(
        "v1",
        "first",
        git_sha="a" * 40,
        git_dirty=False,
        git_source_path="/optimizer-api",
    )

    try:
        storage.get_or_create_version("v1", "different")
    except ValueError as error:
        assert "異なる変更概要" in str(error)
    else:
        raise AssertionError("異なる変更概要による上書きを拒否する必要があります。")

    try:
        storage.get_or_create_version(
            "v1",
            "first",
            git_sha="b" * 40,
            git_dirty=False,
            git_source_path="/optimizer-api",
        )
    except ValueError as error:
        assert "異なるGit SHA" in str(error)
    else:
        raise AssertionError("異なるGit SHAによる混在を拒否する必要があります。")


def _quality(evaluator_version: str, hard_violations: int) -> QualityEvaluation:
    return QualityEvaluation(
        evaluator_version=evaluator_version,
        day_counts={"2026-11-01": 1},
        day_staffing_deltas={"2026-11-01": 0},
        night_counts={1: 1},
        maximum_consecutive_work_days=1,
        hard_violation_count=hard_violations,
        violations=[],
        day_ability_totals={"2026-11-01": 5},
        night_ability_totals={"2026-11-01": 3},
        day_ability_deviation_percentages={"2026-11-01": 0.0},
        night_ability_deviation_percentages={"2026-11-01": 0.0},
        shift_counts_by_staff={1: {"day": 1}},
        consecutive_work_days_by_staff={1: 1},
        night_count_standard_deviation=0.5,
        work_count_difference=2,
        off_count_difference=1,
    )


def _save_suite(
    storage: BenchmarkStorage,
    tmp_path: Path,
    *,
    version_name: str,
    elapsed_seconds: float,
    hard_violations: int,
    evaluator_version: str = "phase3-v1",
    dataset_generation: str | None = None,
    dataset_hash: str = "dataset-hash",
) -> int:
    case = load_fixed_case(Path("data/cases/demo_20_baseline_v1.json"))
    generation = dataset_generation or case.dataset_generation
    dataset = BenchmarkDataset(
        generation=generation,
        manifest_path=tmp_path / "manifest.json",
        manifest_hash=f"manifest-{generation}",
        dataset_hash=dataset_hash,
        cases=(case,),
    )
    storage.register_dataset(dataset)
    storage.register_case(case)
    version_id = storage.get_or_create_version(
        version_name,
        f"{version_name} summary",
        git_sha=version_name * 20,
        git_dirty=False,
        git_source_path="/optimizer-api",
    )
    environment = {
        "python_version": "3.12.0",
        "platform": "test-platform",
        "processor": "test-cpu",
        "cpu_count": 8,
    }
    suite_id = storage.create_suite(
        version_id=version_id,
        dataset=dataset,
        mode="quick",
        trials_per_case=1,
        api_url="http://optimizer.test",
        environment=environment,
    )
    run_id = storage.create_run(
        version_id=version_id,
        case=case,
        api_url="http://optimizer.test",
        environment=environment,
        suite_id=suite_id,
    )
    result = ApiCallResult(
        status="success",
        elapsed_seconds=elapsed_seconds,
        http_status=200,
        response_body={
            "status": "success",
            "solver_status": "OPTIMAL",
            "phase_results": [],
            "issues": [],
            "metrics": {
                "internal_elapsed_seconds": elapsed_seconds - 0.1,
                "cpu_time_seconds": elapsed_seconds,
                "cpu_percent": 100.0,
                "peak_memory_mb": 128.0,
                "logical_cpu_count": 8,
                "cpu_limit": 2.0,
                "ortools_version": "9.15.0",
                "num_search_workers": 2,
                "solver_seed": 1,
            },
        },
    )
    trial_id = storage.record_trial(
        run_id=run_id,
        result=result,
        input_path=tmp_path / f"{version_name}-input.json",
        response_path=tmp_path / f"{version_name}-response.json",
    )
    storage.record_quality(
        trial_id,
        _quality(evaluator_version, hard_violations),
    )
    storage.finish_run(run_id)
    storage.set_suite_status(suite_id, "completed")
    return suite_id


def test_saved_suites_can_be_compared_without_running_api(tmp_path) -> None:
    storage = BenchmarkStorage(tmp_path / "benchmark.db")
    baseline_id = _save_suite(
        storage,
        tmp_path,
        version_name="v1",
        elapsed_seconds=10.0,
        hard_violations=2,
    )
    target_id = _save_suite(
        storage,
        tmp_path,
        version_name="v2",
        elapsed_seconds=8.0,
        hard_violations=1,
    )

    comparison = BenchmarkStorage(tmp_path / "benchmark.db").compare_suites(
        baseline_id,
        target_id,
    )

    assert comparison["dataset_comparable"] is True
    assert comparison["quality_comparable"] is True
    assert comparison["summary"]["average_elapsed_seconds"]["delta"] == -2.0
    assert (
        comparison["summary"]["average_elapsed_seconds"]["percent_change"]
        == -20.0
    )
    assert len(comparison["case_comparisons"]) == 1
    case = comparison["case_comparisons"][0]
    assert case["average_hard_violations_delta"] == -1.0
    assert case["elapsed_seconds_delta"] == -2.0

    version_report = storage.get_version_report(2)
    assert version_report["name"] == "v2"
    assert version_report["git_sha"] == "v2" * 20
    assert version_report["suite_count"] == 1
    assert len(version_report["suites"][0]["trial_results"]) == 1


def test_quality_delta_is_disabled_when_evaluator_versions_differ(tmp_path) -> None:
    storage = BenchmarkStorage(tmp_path / "benchmark.db")
    baseline_id = _save_suite(
        storage,
        tmp_path,
        version_name="v1",
        elapsed_seconds=10.0,
        hard_violations=2,
    )
    target_id = _save_suite(
        storage,
        tmp_path,
        version_name="v2",
        elapsed_seconds=8.0,
        hard_violations=1,
        evaluator_version="phase4-v1",
    )

    comparison = storage.compare_suites(baseline_id, target_id)

    assert comparison["dataset_comparable"] is True
    assert comparison["quality_comparable"] is False
    assert any(
        warning["code"] == "evaluator_mismatch"
        for warning in comparison["warnings"]
    )
    assert (
        comparison["case_comparisons"][0]["average_hard_violations_delta"]
        is None
    )


def test_case_comparison_is_blocked_when_datasets_differ(tmp_path) -> None:
    storage = BenchmarkStorage(tmp_path / "benchmark.db")
    baseline_id = _save_suite(
        storage,
        tmp_path,
        version_name="v1",
        elapsed_seconds=10.0,
        hard_violations=0,
    )
    target_id = _save_suite(
        storage,
        tmp_path,
        version_name="v2",
        elapsed_seconds=8.0,
        hard_violations=0,
        dataset_generation="phase2-v2",
        dataset_hash="different-dataset-hash",
    )

    comparison = storage.compare_suites(baseline_id, target_id)

    assert comparison["dataset_comparable"] is False
    assert comparison["quality_comparable"] is False
    assert comparison["case_comparisons"] == []
    assert any(
        warning["code"] == "dataset_mismatch"
        for warning in comparison["warnings"]
    )
