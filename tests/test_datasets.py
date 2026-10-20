from __future__ import annotations

from optimizer_benchmark.config import DEFAULT_CASE_PATH
from optimizer_benchmark.datasets import load_fixed_case


def test_fixed_case_matches_phase_one_contract() -> None:
    case = load_fixed_case(DEFAULT_CASE_PATH)

    assert case.case_id == "demo-20-baseline-v1"
    assert case.staff_count == 20
    assert case.seed == 0
    assert len(case.payload["month_dates"]) == 30
    assert len(case.payload["effective_rules"]) == 30
    assert len(case.payload["previous_consecutive_work_days"]) == 20
    assert len(case.payload["effective_off_days"]) == 20
    assert len(case.payload["configured_off_days"]) == 20
    assert all(
        "ability_level" in staff and "regular_days_off" in staff
        for staff in case.payload["staff_members"]
    )
    assert all(
        "required_day_staff" in rule and "required_night_staff" in rule
        for rule in case.payload["effective_rules"]
    )
