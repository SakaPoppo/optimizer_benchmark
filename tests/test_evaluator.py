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
    assert quality.evaluator_version == "phase3-v1"
    assert quality.day_ability_totals == {"2026-11-01": 5, "2026-11-02": 5}
    assert quality.night_ability_totals == {"2026-11-01": 3, "2026-11-02": 3}
    assert quality.day_ability_deviation_percentages == {
        "2026-11-01": 25.0,
        "2026-11-02": 25.0,
    }
    assert quality.night_count_standard_deviation == 1
    assert summary["night_count_difference"] == 2
    assert summary["work_count_difference"] == 0


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


def test_evaluator_checks_ability_and_night_sequence_constraints() -> None:
    payload = minimal_payload()
    payload["effective_rules"][0]["min_ability_level"] = 5
    payload["effective_rules"][0]["min_ability_level_staff_count"] = 1
    shifts = [
        {"staff_id": 1, "date": "2026-11-01", "shift_type": "night"},
        {"staff_id": 1, "date": "2026-11-02", "shift_type": "day"},
        {"staff_id": 2, "date": "2026-11-01", "shift_type": "day"},
        {"staff_id": 2, "date": "2026-11-02", "shift_type": "night"},
    ]

    quality = evaluate_schedule(payload, shifts)

    violation_codes = {item["code"] for item in quality.violations}
    assert "MINIMUM_ABILITY_SHORTAGE" in violation_codes
    assert "NIGHT_AFTER_NIGHT_MISMATCH" in violation_codes


def test_evaluator_includes_previous_month_in_consecutive_work() -> None:
    payload = minimal_payload()
    payload["previous_consecutive_work_days"] = [
        {"staff_id": 1, "previous_consecutive_work_days": 5},
        {"staff_id": 2, "previous_consecutive_work_days": 0},
    ]
    shifts = successful_response(payload)["shifts"]

    quality = evaluate_schedule(payload, shifts)

    assert quality.consecutive_work_days_by_staff[1] == 7
    assert "MAX_CONSECUTIVE_WORK_EXCEEDED" in {
        item["code"] for item in quality.violations
    }
