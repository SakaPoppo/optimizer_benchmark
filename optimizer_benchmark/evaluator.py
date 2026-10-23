"""APIのissuesに依存せず、入力条件と完成シフトから品質を再計算する。"""

from __future__ import annotations

from collections import Counter
from statistics import pstdev

from .models import QualityEvaluation

EVALUATOR_VERSION = "phase3-v1"
WORKLIKE_SHIFT_TYPES = {"day", "night", "after_night", "training"}
MONTHLY_OFF_SHIFT_TYPES = {"off", "off_request"}
KNOWN_SHIFT_TYPES = WORKLIKE_SHIFT_TYPES | MONTHLY_OFF_SHIFT_TYPES | {
    "paid_leave",
    "special_leave",
}


def evaluate_schedule(payload: dict, shifts: list[dict]) -> QualityEvaluation:
    month_dates = list(payload["month_dates"])
    staff_members = list(payload["staff_members"])
    staff_by_id = {staff["id"]: staff for staff in staff_members}
    expected_cells = {
        (staff_id, target_date)
        for staff_id in staff_by_id
        for target_date in month_dates
    }
    violations: list[dict] = []
    cells: dict[tuple[int, str], str] = {}
    duplicate_cells: set[tuple[int, str]] = set()
    for shift in shifts:
        key = (shift.get("staff_id"), shift.get("date"))
        if key in cells:
            duplicate_cells.add(key)
        cells[key] = shift.get("shift_type")

    _evaluate_cell_integrity(expected_cells, cells, duplicate_cells, violations)
    rules_by_date = {rule["date"]: rule for rule in payload["effective_rules"]}
    day_counts = _daily_counts(month_dates, staff_by_id, cells, "day")
    day_staffing_deltas = {
        target_date: day_counts[target_date]
        - (
            rules_by_date[target_date]["required_day_staff_override"]
            if rules_by_date[target_date]["required_day_staff_override"] is not None
            else rules_by_date[target_date]["required_day_staff"]
        )
        for target_date in month_dates
    }
    night_counts = {
        staff_id: sum(
            cells.get((staff_id, target_date)) == "night"
            for target_date in month_dates
        )
        for staff_id in staff_by_id
    }

    _evaluate_fixed_assignments(payload, cells, violations)
    _evaluate_daily_hard_constraints(
        month_dates,
        staff_by_id,
        rules_by_date,
        cells,
        violations,
    )
    _evaluate_night_sequences(payload, month_dates, staff_by_id, cells, violations)
    _evaluate_monthly_off_days(payload, month_dates, cells, violations)
    maximum_consecutive, consecutive_by_staff = _evaluate_consecutive_work(
        payload,
        month_dates,
        staff_by_id,
        cells,
        violations,
    )
    day_ability_totals, day_ability_deviations = _ability_metrics(
        month_dates=month_dates,
        staff_members=staff_members,
        cells=cells,
        shift_type="day",
    )
    night_eligible_staff = [
        staff for staff in staff_members if staff["can_night_shift"]
    ]
    night_ability_totals, night_ability_deviations = _ability_metrics(
        month_dates=month_dates,
        staff_members=night_eligible_staff,
        cells=cells,
        shift_type="night",
    )
    shift_counts = _shift_counts(month_dates, staff_by_id, cells)
    work_counts = [
        sum(counts.get(shift_type, 0) for shift_type in WORKLIKE_SHIFT_TYPES)
        for counts in shift_counts.values()
    ]
    off_counts = [
        sum(counts.get(shift_type, 0) for shift_type in MONTHLY_OFF_SHIFT_TYPES)
        for counts in shift_counts.values()
    ]
    night_values = list(night_counts.values())
    return QualityEvaluation(
        evaluator_version=EVALUATOR_VERSION,
        day_counts=day_counts,
        day_staffing_deltas=day_staffing_deltas,
        night_counts=night_counts,
        maximum_consecutive_work_days=maximum_consecutive,
        hard_violation_count=len(violations),
        violations=violations,
        day_ability_totals=day_ability_totals,
        night_ability_totals=night_ability_totals,
        day_ability_deviation_percentages=day_ability_deviations,
        night_ability_deviation_percentages=night_ability_deviations,
        shift_counts_by_staff=shift_counts,
        consecutive_work_days_by_staff=consecutive_by_staff,
        night_count_standard_deviation=(
            pstdev(night_values) if night_values else 0.0
        ),
        work_count_difference=_range(work_counts),
        off_count_difference=_range(off_counts),
    )


def _evaluate_cell_integrity(expected_cells, cells, duplicate_cells, violations) -> None:
    missing_cells = sorted(expected_cells - cells.keys())
    unexpected_cells = sorted(cells.keys() - expected_cells)
    invalid_cells = sorted(
        key for key, shift_type in cells.items() if shift_type not in KNOWN_SHIFT_TYPES
    )
    if missing_cells:
        violations.append({"code": "MISSING_SHIFT_CELLS", "cells": missing_cells})
    if unexpected_cells:
        violations.append({"code": "UNEXPECTED_SHIFT_CELLS", "cells": unexpected_cells})
    if duplicate_cells:
        violations.append(
            {"code": "DUPLICATE_SHIFT_CELLS", "cells": sorted(duplicate_cells)}
        )
    if invalid_cells:
        violations.append({"code": "INVALID_SHIFT_TYPES", "cells": invalid_cells})


def _daily_counts(month_dates, staff_by_id, cells, shift_type) -> dict[str, int]:
    return {
        target_date: sum(
            cells.get((staff_id, target_date)) == shift_type
            for staff_id in staff_by_id
        )
        for target_date in month_dates
    }


def _evaluate_fixed_assignments(payload, cells, violations) -> None:
    mismatches = [
        {
            "staff_id": assignment["staff_id"],
            "date": assignment["date"],
            "expected": assignment["shift_type"],
            "actual": cells.get((assignment["staff_id"], assignment["date"])),
        }
        for assignment in payload["fixed_assignments"]
        if cells.get((assignment["staff_id"], assignment["date"]))
        != assignment["shift_type"]
    ]
    if mismatches:
        violations.append({"code": "FIXED_ASSIGNMENT_MISMATCH", "items": mismatches})


def _evaluate_daily_hard_constraints(
    month_dates,
    staff_by_id,
    rules_by_date,
    cells,
    violations,
) -> None:
    night_mismatches = []
    leader_shortages = []
    ability_shortages = []
    ineligible_nights = []
    for target_date in month_dates:
        rule = rules_by_date[target_date]
        actual_night_count = sum(
            cells.get((staff_id, target_date)) == "night" for staff_id in staff_by_id
        )
        if actual_night_count != rule["required_night_staff"]:
            night_mismatches.append(
                {
                    "date": target_date,
                    "expected": rule["required_night_staff"],
                    "actual": actual_night_count,
                }
            )
        actual_leaders = sum(
            cells.get((staff_id, target_date)) == "day"
            for staff_id, staff in staff_by_id.items()
            if staff["role"] == "leader"
        )
        if actual_leaders < rule["required_leader_staff"]:
            leader_shortages.append(
                {
                    "date": target_date,
                    "required": rule["required_leader_staff"],
                    "actual": actual_leaders,
                }
            )
        minimum_level = rule["min_ability_level"]
        minimum_count = rule["min_ability_level_staff_count"]
        if minimum_level is not None and minimum_count is not None:
            actual_qualified = sum(
                cells.get((staff_id, target_date)) == "day"
                and staff["ability_level"] >= minimum_level
                for staff_id, staff in staff_by_id.items()
            )
            if actual_qualified < minimum_count:
                ability_shortages.append(
                    {
                        "date": target_date,
                        "minimum_level": minimum_level,
                        "required": minimum_count,
                        "actual": actual_qualified,
                    }
                )
        ineligible_nights.extend(
            {"date": target_date, "staff_id": staff_id}
            for staff_id, staff in staff_by_id.items()
            if not staff["can_night_shift"]
            and cells.get((staff_id, target_date)) == "night"
        )
    if night_mismatches:
        violations.append(
            {"code": "REQUIRED_NIGHT_STAFF_MISMATCH", "items": night_mismatches}
        )
    if leader_shortages:
        violations.append({"code": "REQUIRED_LEADER_SHORTAGE", "items": leader_shortages})
    if ability_shortages:
        violations.append(
            {"code": "MINIMUM_ABILITY_SHORTAGE", "items": ability_shortages}
        )
    if ineligible_nights:
        violations.append({"code": "NIGHT_SHIFT_NOT_ALLOWED", "items": ineligible_nights})


def _evaluate_night_sequences(
    payload,
    month_dates,
    staff_by_id,
    cells,
    violations,
) -> None:
    rules_by_date = {rule["date"]: rule for rule in payload["effective_rules"]}
    override_keys = {
        (item["staff_id"], item["date"])
        for item in payload["user_override_assignment_keys"]
    }
    after_night_mismatches = []
    off_mismatches = []
    for staff_id in staff_by_id:
        for index, target_date in enumerate(month_dates):
            if cells.get((staff_id, target_date)) != "night":
                continue
            if index + 1 < len(month_dates):
                next_date = month_dates[index + 1]
                if cells.get((staff_id, next_date)) != "after_night":
                    after_night_mismatches.append(
                        {"staff_id": staff_id, "night_date": target_date}
                    )
            if index + 2 >= len(month_dates):
                continue
            third_date = month_dates[index + 2]
            sequence_keys = {
                (staff_id, target_date),
                (staff_id, month_dates[index + 1]),
                (staff_id, third_date),
            }
            if sequence_keys <= override_keys:
                continue
            if (
                rules_by_date[target_date]["night_shift_next_day_off"]
                and cells.get((staff_id, third_date)) not in MONTHLY_OFF_SHIFT_TYPES
            ):
                off_mismatches.append(
                    {"staff_id": staff_id, "night_date": target_date}
                )
    if after_night_mismatches:
        violations.append(
            {"code": "NIGHT_AFTER_NIGHT_MISMATCH", "items": after_night_mismatches}
        )
    if off_mismatches:
        violations.append(
            {"code": "NIGHT_SEQUENCE_OFF_MISMATCH", "items": off_mismatches}
        )


def _evaluate_monthly_off_days(payload, month_dates, cells, violations) -> None:
    off_days_by_staff = {
        item["staff_id"]: item["off_days"] for item in payload["effective_off_days"]
    }
    mismatches = []
    for staff_id, expected_count in off_days_by_staff.items():
        actual_count = sum(
            cells.get((staff_id, target_date)) in MONTHLY_OFF_SHIFT_TYPES
            for target_date in month_dates
        )
        if actual_count != expected_count:
            mismatches.append(
                {
                    "staff_id": staff_id,
                    "expected": expected_count,
                    "actual": actual_count,
                }
            )
    if mismatches:
        violations.append({"code": "MONTHLY_OFF_COUNT_MISMATCH", "items": mismatches})


def _evaluate_consecutive_work(
    payload,
    month_dates,
    staff_by_id,
    cells,
    violations,
) -> tuple[int, dict[int, int]]:
    previous_counts = {
        item["staff_id"]: item["previous_consecutive_work_days"]
        for item in payload["previous_consecutive_work_days"]
    }
    override_keys = {
        (item["staff_id"], item["date"])
        for item in payload["user_override_assignment_keys"]
    }
    maximum_allowed = payload["effective_rules"][0]["max_consecutive_work_days"]
    staff_maximums: dict[int, int] = {}
    exceeded = []
    for staff_id in staff_by_id:
        prefix_count = min(previous_counts.get(staff_id, 0), maximum_allowed)
        timeline = [None] * prefix_count + month_dates
        work_values = [
            True
            if target_date is None
            else cells.get((staff_id, target_date)) in WORKLIKE_SHIFT_TYPES
            for target_date in timeline
        ]
        streak = 0
        maximum = 0
        for is_work in work_values:
            streak = streak + 1 if is_work else 0
            maximum = max(maximum, streak)
        staff_maximums[staff_id] = maximum
        window_size = maximum_allowed + 1
        violating_windows = []
        for start in range(len(timeline) - window_size + 1):
            window = timeline[start : start + window_size]
            if not all(work_values[start : start + window_size]):
                continue
            current_dates = [target_date for target_date in window if target_date]
            if current_dates and all(
                (staff_id, target_date) in override_keys
                for target_date in current_dates
            ):
                continue
            violating_windows.append(current_dates)
        if violating_windows:
            exceeded.append(
                {
                    "staff_id": staff_id,
                    "maximum": maximum,
                    "allowed": maximum_allowed,
                    "windows": violating_windows,
                }
            )
    if exceeded:
        violations.append({"code": "MAX_CONSECUTIVE_WORK_EXCEEDED", "items": exceeded})
    return max(staff_maximums.values(), default=0), staff_maximums


def _ability_metrics(
    *,
    month_dates: list[str],
    staff_members: list[dict],
    cells: dict,
    shift_type: str,
) -> tuple[dict[str, int], dict[str, float]]:
    staff_by_id = {staff["id"]: staff for staff in staff_members}
    average_ability = (
        sum(staff["ability_level"] for staff in staff_members) / len(staff_members)
        if staff_members
        else 0
    )
    totals = {}
    deviations = {}
    for target_date in month_dates:
        selected = [
            staff
            for staff_id, staff in staff_by_id.items()
            if cells.get((staff_id, target_date)) == shift_type
        ]
        actual = sum(staff["ability_level"] for staff in selected)
        expected = average_ability * len(selected)
        totals[target_date] = actual
        deviations[target_date] = (
            round((actual - expected) / expected * 100, 3) if expected else 0.0
        )
    return totals, deviations


def _shift_counts(month_dates, staff_by_id, cells) -> dict[int, dict[str, int]]:
    return {
        staff_id: dict(
            Counter(cells.get((staff_id, target_date)) for target_date in month_dates)
        )
        for staff_id in staff_by_id
    }


def _range(values: list[int]) -> int:
    return max(values) - min(values) if values else 0


def summarize_quality(evaluation: QualityEvaluation) -> dict:
    night_values = list(evaluation.night_counts.values())
    day_values = list(evaluation.day_counts.values())
    return {
        "minimum_day_staff": min(day_values, default=0),
        "maximum_day_staff": max(day_values, default=0),
        "night_count_min": min(night_values, default=0),
        "night_count_max": max(night_values, default=0),
        "night_count_difference": _range(night_values),
        "night_count_standard_deviation": evaluation.night_count_standard_deviation,
        "work_count_difference": evaluation.work_count_difference,
        "off_count_difference": evaluation.off_count_difference,
        "maximum_consecutive_work_days": evaluation.maximum_consecutive_work_days,
        "hard_violation_count": evaluation.hard_violation_count,
        "day_count_mode": Counter(day_values).most_common(1)[0][0] if day_values else 0,
    }
