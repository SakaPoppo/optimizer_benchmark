from __future__ import annotations

from optimizer_benchmark.evaluator import evaluate_schedule, summarize_quality

from .helpers import minimal_payload, successful_response


def test_evaluator_recalculates_basic_quality_independently() -> None:
    payload = minimal_payload()
    response = successful_response(payload)

    quality = evaluate_schedule(payload, response["shifts"])
    summary = summarize_quality(quality)

    assert quality.day_counts == {"2026-11-01": 1, "2026-11-02": 1}
    assert quality.night_counts == {1: 0, 2: 2}
    assert quality.maximum_consecutive_work_days == 2
    assert quality.hard_violation_count == 0
    assert summary["night_count_difference"] == 2


def test_evaluator_reports_missing_cells_and_hard_constraint_violations() -> None:
    payload = minimal_payload()

    quality = evaluate_schedule(
        payload,
        [{"staff_id": 1, "date": "2026-11-01", "shift_type": "off"}],
    )

    violation_codes = {item["code"] for item in quality.violations}
    assert "MISSING_SHIFT_CELLS" in violation_codes
    assert "REQUIRED_NIGHT_STAFF_MISMATCH" in violation_codes
    assert "REQUIRED_LEADER_SHORTAGE" in violation_codes
    assert "MONTHLY_OFF_COUNT_MISMATCH" in violation_codes
