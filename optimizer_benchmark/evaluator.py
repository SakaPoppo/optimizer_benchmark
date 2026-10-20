"""APIのissuesに依存せず、入力条件と完成シフトから品質を再計算する。"""

from __future__ import annotations

from collections import Counter

from .models import QualityEvaluation

EVALUATOR_VERSION = "phase1-v1"
WORKLIKE_SHIFT_TYPES = {"day", "night", "after_night", "training"}
MONTHLY_OFF_SHIFT_TYPES = {"off", "off_request"}


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

    missing_cells = sorted(expected_cells - cells.keys())
    unexpected_cells = sorted(cells.keys() - expected_cells)
    if missing_cells:
        violations.append(
            {"code": "MISSING_SHIFT_CELLS", "cells": missing_cells}
        )
    if unexpected_cells:
        violations.append(
            {"code": "UNEXPECTED_SHIFT_CELLS", "cells": unexpected_cells}
        )
    if duplicate_cells:
        violations.append(
            {"code": "DUPLICATE_SHIFT_CELLS", "cells": sorted(duplicate_cells)}
        )

    rules_by_date = {rule["date"]: rule for rule in payload["effective_rules"]}
    day_counts = {
        target_date: sum(
            cells.get((staff_id, target_date)) == "day" for staff_id in staff_by_id
        )
        for target_date in month_dates
    }
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
    _evaluate_monthly_off_days(payload, month_dates, cells, violations)
    maximum_consecutive = _evaluate_consecutive_work(
        payload,
        month_dates,
        staff_by_id,
        cells,
        violations,
    )
    return QualityEvaluation(
        evaluator_version=EVALUATOR_VERSION,
        day_counts=day_counts,
        day_staffing_deltas=day_staffing_deltas,
        night_counts=night_counts,
        maximum_consecutive_work_days=maximum_consecutive,
        hard_violation_count=len(violations),
        violations=violations,
    )


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
        ineligible_nights.extend(
            {"date": target_date, "staff_id": staff_id}
            for staff_id, staff in staff_by_id.items()
            if not staff["can_night_shift"]
            and cells.get((staff_id, target_date)) == "night"
        )
    if night_mismatches:
        violations.append({"code": "REQUIRED_NIGHT_STAFF_MISMATCH", "items": night_mismatches})
    if leader_shortages:
        violations.append({"code": "REQUIRED_LEADER_SHORTAGE", "items": leader_shortages})
    if ineligible_nights:
        violations.append({"code": "NIGHT_SHIFT_NOT_ALLOWED", "items": ineligible_nights})


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
) -> int:
    previous_counts = {
        item["staff_id"]: item["previous_consecutive_work_days"]
        for item in payload["previous_consecutive_work_days"]
    }
    maximum_allowed = payload["effective_rules"][0]["max_consecutive_work_days"]
    staff_maximums: dict[int, int] = {}
    exceeded = []
    for staff_id in staff_by_id:
        streak = previous_counts.get(staff_id, 0)
        maximum = streak
        for target_date in month_dates:
            if cells.get((staff_id, target_date)) in WORKLIKE_SHIFT_TYPES:
                streak += 1
                maximum = max(maximum, streak)
            else:
                streak = 0
        staff_maximums[staff_id] = maximum
        if maximum > maximum_allowed:
            exceeded.append(
                {
                    "staff_id": staff_id,
                    "maximum": maximum,
                    "allowed": maximum_allowed,
                }
            )
    if exceeded:
        violations.append({"code": "MAX_CONSECUTIVE_WORK_EXCEEDED", "items": exceeded})
    return max(staff_maximums.values(), default=0)


def summarize_quality(evaluation: QualityEvaluation) -> dict:
    night_values = list(evaluation.night_counts.values())
    day_values = list(evaluation.day_counts.values())
    return {
        "minimum_day_staff": min(day_values, default=0),
        "maximum_day_staff": max(day_values, default=0),
        "night_count_min": min(night_values, default=0),
        "night_count_max": max(night_values, default=0),
        "night_count_difference": (
            max(night_values) - min(night_values) if night_values else 0
        ),
        "maximum_consecutive_work_days": evaluation.maximum_consecutive_work_days,
        "hard_violation_count": evaluation.hard_violation_count,
        "day_count_mode": Counter(day_values).most_common(1)[0][0] if day_values else 0,
    }
