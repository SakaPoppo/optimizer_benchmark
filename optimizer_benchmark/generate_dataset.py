"""Phase 2の固定16ケースを決定論的に生成する。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from .config import DEFAULT_DATASET_MANIFEST_PATH

GENERATION = "phase2-v1"
STAFF_COUNTS = (10, 20, 30, 40)
PATTERNS = ("baseline", "random_requests", "fixed_assignments", "stress")
PATTERN_LABELS = {
    "baseline": "追加希望休なし",
    "random_requests": "希望休を1人2日配置",
    "fixed_assignments": "希望休と固定勤務を配置",
    "stress": "希望休を1人3〜4日集中配置",
}
MONTH_DATES = tuple(date(2026, 11, day) for day in range(1, 31))


def generate_dataset(output_directory: Path) -> dict:
    cases_directory = output_directory / "cases"
    cases_directory.mkdir(parents=True, exist_ok=True)
    manifest_cases = []
    for staff_count in STAFF_COUNTS:
        for pattern_index, pattern in enumerate(PATTERNS):
            seed = 20261100 + staff_count * 10 + pattern_index
            payload = build_case_payload(staff_count, pattern, seed)
            validate_case_payload(payload)
            relative_path = Path("cases") / f"{staff_count}-{pattern}.json"
            case_path = output_directory / relative_path
            content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            case_path.write_text(content, encoding="utf-8")
            input_hash = hashlib.sha256(content.encode()).hexdigest()
            manifest_cases.append(
                {
                    "case_id": f"{GENERATION}-{staff_count}-{pattern}",
                    "name": f"{staff_count}人 {pattern}",
                    "staff_count": staff_count,
                    "pattern": pattern,
                    "seed": seed,
                    "path": relative_path.as_posix(),
                    "input_hash": input_hash,
                }
            )
    dataset_hash = hashlib.sha256(
        "\n".join(
            f"{item['case_id']}:{item['input_hash']}"
            for item in sorted(manifest_cases, key=lambda item: item["case_id"])
        ).encode()
    ).hexdigest()
    manifest = {
        "generation": GENERATION,
        "target_month": "2026-11",
        "case_count": len(manifest_cases),
        "dataset_hash": dataset_hash,
        "generation_policy": {
            "day_staff_ratio": "35%（四捨五入）",
            "night_staff_ratio": "15%（切り捨て、最低1人）",
            "leader_ratio": "45%（四捨五入）",
            "monthly_off_days": 10,
            "max_consecutive_work_days": 5,
            "patterns": PATTERN_LABELS,
        },
        "cases": manifest_cases,
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def build_case_payload(staff_count: int, pattern: str, seed: int) -> dict:
    if staff_count not in STAFF_COUNTS:
        raise ValueError(f"未対応のスタッフ数です: {staff_count}")
    if pattern not in PATTERNS:
        raise ValueError(f"未対応のパターンです: {pattern}")
    day_staff = _round_ratio(staff_count, 35)
    night_staff = max(1, staff_count * 15 // 100)
    leader_count = _round_ratio(staff_count, 45)
    staff_members = _build_staff(staff_count, leader_count)
    fixed = _build_baseline_assignments(staff_count, staff_members)
    user_override_keys: set[tuple[int, date]] = set()
    rng = random.Random(seed)
    if pattern in {"random_requests", "fixed_assignments"}:
        _add_off_requests(
            fixed,
            staff_count=staff_count,
            request_counts={staff_id: 2 for staff_id in range(1, staff_count + 1)},
            candidates=MONTH_DATES[2:],
            daily_cap=max(1, staff_count - day_staff - 2 * night_staff),
            rng=rng,
        )
    elif pattern == "stress":
        _add_off_requests(
            fixed,
            staff_count=staff_count,
            request_counts={
                staff_id: 3 + (staff_id % 2) for staff_id in range(1, staff_count + 1)
            },
            candidates=tuple(
                target_date
                for target_date in MONTH_DATES
                if target_date.day in {5, 6, 7, 12, 13, 14, 19, 20, 21, 26, 27, 28}
            ),
            daily_cap=max(1, staff_count - day_staff - 2 * night_staff),
            rng=rng,
        )
    if pattern == "fixed_assignments":
        _add_manual_assignments(
            fixed,
            user_override_keys,
            staff_count=staff_count,
        )
    return {
        "month_dates": [target_date.isoformat() for target_date in MONTH_DATES],
        "staff_members": staff_members,
        "fixed_assignments": [
            {
                "staff_id": staff_id,
                "date": target_date.isoformat(),
                "shift_type": shift_type,
            }
            for (staff_id, target_date), shift_type in sorted(fixed.items())
        ],
        "effective_rules": [
            {
                "date": target_date.isoformat(),
                "required_day_staff": day_staff,
                "required_day_staff_override": None,
                "required_night_staff": night_staff,
                "required_leader_staff": 1,
                "min_ability_level": None,
                "min_ability_level_staff_count": None,
                "max_consecutive_work_days": 5,
                "night_shift_next_day_off": True,
            }
            for target_date in MONTH_DATES
        ],
        "previous_consecutive_work_days": [
            {"staff_id": staff_id, "previous_consecutive_work_days": 0}
            for staff_id in range(1, staff_count + 1)
        ],
        "effective_off_days": [
            {"staff_id": staff_id, "off_days": 10}
            for staff_id in range(1, staff_count + 1)
        ],
        "configured_off_days": [
            {"staff_id": staff_id, "off_days": 10}
            for staff_id in range(1, staff_count + 1)
        ],
        "user_override_assignment_keys": [
            {"staff_id": staff_id, "date": target_date.isoformat()}
            for staff_id, target_date in sorted(user_override_keys)
        ],
    }


def validate_case_payload(payload: dict) -> None:
    staff_count = len(payload["staff_members"])
    staff_ids = {staff["id"] for staff in payload["staff_members"]}
    if staff_ids != set(range(1, staff_count + 1)):
        raise ValueError("スタッフIDが連番ではありません。")
    fixed = payload["fixed_assignments"]
    keys = [(item["staff_id"], item["date"]) for item in fixed]
    if len(keys) != len(set(keys)):
        raise ValueError("固定勤務セルが重複しています。")
    off_counts = Counter(
        item["staff_id"]
        for item in fixed
        if item["shift_type"] in {"off", "off_request"}
    )
    if max(off_counts.values(), default=0) > 10:
        raise ValueError("固定休が月休日数を超えています。")
    rules = {item["date"]: item for item in payload["effective_rules"]}
    fixed_by_date = Counter(
        item["date"]
        for item in fixed
        if item["shift_type"] in {"off", "off_request", "after_night"}
    )
    for target_date, unavailable in fixed_by_date.items():
        rule = rules[target_date]
        minimum_available = rule["required_day_staff"] + rule["required_night_staff"]
        if staff_count - unavailable < minimum_available:
            raise ValueError(f"{target_date}の固定休が多すぎます。")


def _build_staff(staff_count: int, leader_count: int) -> list[dict]:
    abilities = []
    ratios = {5: 10, 4: 20, 3: 25, 2: 25, 1: 20}
    counts = {level: staff_count * ratio // 100 for level, ratio in ratios.items()}
    remainder = staff_count - sum(counts.values())
    fractions = sorted(
        ratios,
        key=lambda level: (staff_count * ratios[level] % 100, level),
        reverse=True,
    )
    for level in fractions[:remainder]:
        counts[level] += 1
    for level in sorted(counts, reverse=True):
        abilities.extend([level] * counts[level])
    regular_count = _round_ratio(staff_count, 15)
    regular_staff = list(range(staff_count - regular_count + 1, staff_count + 1))
    weekdays = (2, 5, 6)
    return [
        {
            "id": staff_id,
            "role": "leader" if staff_id <= leader_count else "member",
            "ability_level": abilities[staff_id - 1],
            "can_night_shift": True,
            "regular_days_off": (
                [weekdays[regular_staff.index(staff_id) % len(weekdays)]]
                if staff_id in regular_staff
                else []
            ),
        }
        for staff_id in range(1, staff_count + 1)
    ]


def _build_baseline_assignments(staff_count: int, staff_members: list[dict]) -> dict:
    fixed = {
        (staff["id"], target_date): "off"
        for staff in staff_members
        for target_date in MONTH_DATES
        if target_date.weekday() in staff["regular_days_off"]
    }
    if staff_count == 20:
        previous_night_ids = (2, 9, 15)
        previous_after_night_ids = (4, 11, 17)
    else:
        boundary_count = _round_ratio(staff_count, 15)
        previous_night_ids = tuple(range(2, 2 + boundary_count * 2, 2))
        previous_after_night_ids = tuple(
            range(2 + boundary_count * 2, 2 + boundary_count * 4, 2)
        )
    for staff_id in previous_night_ids:
        fixed[(staff_id, MONTH_DATES[0])] = "after_night"
        fixed[(staff_id, MONTH_DATES[1])] = "off"
    for staff_id in previous_after_night_ids:
        fixed[(staff_id, MONTH_DATES[0])] = "off"
    return fixed


def _add_off_requests(
    fixed: dict,
    *,
    staff_count: int,
    request_counts: dict[int, int],
    candidates: tuple[date, ...],
    daily_cap: int,
    rng: random.Random,
) -> None:
    daily_counts = Counter(
        target_date
        for (_, target_date), shift_type in fixed.items()
        if shift_type in {"off", "off_request", "after_night"}
    )
    for staff_id in range(1, staff_count + 1):
        ordered_dates = list(candidates)
        rng.shuffle(ordered_dates)
        selected = 0
        for target_date in sorted(
            ordered_dates,
            key=lambda value: (daily_counts[value], ordered_dates.index(value)),
        ):
            if (staff_id, target_date) in fixed or daily_counts[target_date] >= daily_cap:
                continue
            fixed[(staff_id, target_date)] = "off_request"
            daily_counts[target_date] += 1
            selected += 1
            if selected == request_counts[staff_id]:
                break
        if selected != request_counts[staff_id]:
            raise ValueError(f"スタッフ{staff_id}の希望休を配置できません。")


def _add_manual_assignments(
    fixed: dict,
    user_override_keys: set[tuple[int, date]],
    *,
    staff_count: int,
) -> None:
    group_count = math.ceil(staff_count / 10)
    for group in range(group_count):
        first_staff = group * 10 + 1
        if first_staff > staff_count:
            break
        night_staff = first_staff
        night_date = MONTH_DATES[7 + group * 5]
        triplet = (
            (night_staff, night_date, "night"),
            (night_staff, night_date + timedelta(days=1), "after_night"),
            (night_staff, night_date + timedelta(days=2), "off"),
        )
        if all((staff_id, target_date) not in fixed for staff_id, target_date, _ in triplet):
            for staff_id, target_date, shift_type in triplet:
                fixed[(staff_id, target_date)] = shift_type
                user_override_keys.add((staff_id, target_date))
        day_staff = min(first_staff + 1, staff_count)
        day_date = MONTH_DATES[14 + group * 3]
        if (day_staff, day_date) not in fixed:
            fixed[(day_staff, day_date)] = "day"
            user_override_keys.add((day_staff, day_date))
        off_staff = min(first_staff + 2, staff_count)
        off_date = MONTH_DATES[23 + group]
        if (off_staff, off_date) not in fixed:
            fixed[(off_staff, off_date)] = "off"
            user_override_keys.add((off_staff, off_date))


def _round_ratio(value: int, percent: int) -> int:
    return (value * percent + 50) // 100


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2固定データセット生成")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_DATASET_MANIFEST_PATH.parent,
    )
    args = parser.parse_args()
    manifest = generate_dataset(args.output)
    print(
        f"generated {manifest['case_count']} cases: "
        f"{args.output / 'manifest.json'}"
    )


if __name__ == "__main__":
    main()
