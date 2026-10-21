from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from optimizer_benchmark.artifacts import ArtifactStore
from optimizer_benchmark.runner import MODE_TRIALS, BenchmarkRunner
from optimizer_benchmark.storage import BenchmarkStorage

MANIFEST_PATH = Path("data/datasets/phase2-v1/manifest.json")


def _success_response(request: httpx.Request) -> httpx.Response:
    payload = json.loads(request.content)
    shifts = [
        {
            "staff_id": staff["id"],
            "date": target_date,
            "shift_type": "off",
        }
        for staff in payload["staff_members"]
        for target_date in payload["month_dates"]
    ]
    return httpx.Response(
        200,
        json={
            "status": "success",
            "solver_status": "OPTIMAL",
            "shifts": shifts,
            "phase_results": [],
            "issues": [],
        },
    )


def _runner(tmp_path: Path, handler) -> BenchmarkRunner:
    return BenchmarkRunner(
        storage=BenchmarkStorage(tmp_path / "benchmark.db"),
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        api_url="http://optimizer.test",
        api_key="test-key",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )


def test_quick_mode_saves_all_16_trials(tmp_path) -> None:
    progress = []
    report = _runner(tmp_path, _success_response).run_suite(
        manifest_path=MANIFEST_PATH,
        version_name="quick-test",
        change_summary="quick",
        mode="quick",
        progress_callback=lambda *values: progress.append(values),
    )

    assert MODE_TRIALS == {"quick": 1, "standard": 3, "full": 10}
    assert report["status"] == "completed"
    assert report["completed_trials"] == 16
    assert report["total_trials"] == 16
    assert report["successful_trials"] == 16
    assert report["success_rate"] == 1
    assert len(report["case_results"]) == 16
    assert progress[-1][0:2] == (16, 16)
    assert len(list((tmp_path / "artifacts").glob("run-*/trial-1/input.json"))) == 16
    assert len(list((tmp_path / "artifacts").glob("run-*/trial-1/response.json"))) == 16


def test_standard_mode_resumes_only_unfinished_trials(tmp_path) -> None:
    calls_before_interrupt = 0

    def interrupting_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls_before_interrupt
        calls_before_interrupt += 1
        if calls_before_interrupt == 5:
            raise RuntimeError("test interruption")
        return _success_response(request)

    with pytest.raises(RuntimeError, match="test interruption"):
        _runner(tmp_path, interrupting_handler).run_suite(
            manifest_path=MANIFEST_PATH,
            version_name="resume-test",
            change_summary="resume",
            mode="standard",
        )

    storage = BenchmarkStorage(tmp_path / "benchmark.db")
    interrupted = storage.list_suites()[0]
    assert interrupted["status"] == "interrupted"
    assert interrupted["completed_trials"] == 4
    assert interrupted["total_trials"] == 48

    resumed_calls = 0

    def resumed_handler(request: httpx.Request) -> httpx.Response:
        nonlocal resumed_calls
        resumed_calls += 1
        return _success_response(request)

    report = _runner(tmp_path, resumed_handler).resume_suite(interrupted["id"])

    assert resumed_calls == 44
    assert report["status"] == "completed"
    assert report["completed_trials"] == 48
    assert report["successful_trials"] == 48
    assert len(list((tmp_path / "artifacts").glob("run-*/trial-*/input.json"))) == 48
