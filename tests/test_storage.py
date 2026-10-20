from __future__ import annotations

import json
from pathlib import Path

import httpx

from optimizer_benchmark.artifacts import ArtifactStore
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
    assert report["evaluator_version"] == "phase1-v1"
    assert report["hard_violation_count"] > 0
    assert Path(report["input_path"]).exists()
    assert Path(report["response_path"]).exists()
    assert BenchmarkStorage(tmp_path / "benchmark.db").list_runs()[0]["id"] == 1


def test_version_history_is_not_overwritten(tmp_path) -> None:
    storage = BenchmarkStorage(tmp_path / "benchmark.db")
    storage.get_or_create_version("v1", "first")

    try:
        storage.get_or_create_version("v1", "different")
    except ValueError as error:
        assert "異なる変更概要" in str(error)
    else:
        raise AssertionError("異なる変更概要による上書きを拒否する必要があります。")
