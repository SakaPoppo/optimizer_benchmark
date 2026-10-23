from __future__ import annotations


def minimal_payload() -> dict:
    dates = ["2026-11-01", "2026-11-02"]
    staff = [
        {
            "id": 1,
            "role": "leader",
            "ability_level": 5,
            "can_night_shift": True,
            "regular_days_off": [],
        },
        {
            "id": 2,
            "role": "member",
            "ability_level": 3,
            "can_night_shift": True,
            "regular_days_off": [],
        },
    ]
    return {
        "month_dates": dates,
        "staff_members": staff,
        "fixed_assignments": [],
        "effective_rules": [
            {
                "date": target_date,
                "required_day_staff": 1,
                "required_day_staff_override": None,
                "required_night_staff": 1,
                "required_leader_staff": 1,
                "min_ability_level": None,
                "min_ability_level_staff_count": None,
                "max_consecutive_work_days": 5,
                "night_shift_next_day_off": True,
            }
            for target_date in dates
        ],
        "previous_consecutive_work_days": [
            {"staff_id": 1, "previous_consecutive_work_days": 0},
            {"staff_id": 2, "previous_consecutive_work_days": 0},
        ],
        "effective_off_days": [
            {"staff_id": 1, "off_days": 0},
            {"staff_id": 2, "off_days": 0},
        ],
        "configured_off_days": [
            {"staff_id": 1, "off_days": 0},
            {"staff_id": 2, "off_days": 0},
        ],
        "user_override_assignment_keys": [],
    }


def successful_response(payload: dict) -> dict:
    shifts = []
    for target_date in payload["month_dates"]:
        shifts.extend(
            [
                {"staff_id": 1, "date": target_date, "shift_type": "day"},
                {"staff_id": 2, "date": target_date, "shift_type": "night"},
            ]
        )
    return {
        "status": "success",
        "solver_status": "OPTIMAL",
        "shifts": shifts,
        "phase_results": [
            {
                "name": "night_count_balance",
                "status": "OPTIMAL",
                "objective_value": 0,
                "optimal": True,
                "time_limit_seconds": 40,
                "wall_time_seconds": 0.2,
                "best_objective_bound": 0,
                "branches": 12,
                "conflicts": 1,
                "solution_found": True,
            }
        ],
        "issues": [],
        "metrics": {
            "internal_elapsed_seconds": 0.4,
            "context_build_seconds": 0.01,
            "model_build_seconds": 0.1,
            "result_build_seconds": 0.02,
            "cpu_time_seconds": 0.6,
            "cpu_percent": 150.0,
            "peak_memory_mb": 128.0,
            "logical_cpu_count": 8,
            "cpu_limit": 2.0,
            "ortools_version": "9.14.0",
            "num_search_workers": 2,
            "solver_seed": 1,
        },
    }
