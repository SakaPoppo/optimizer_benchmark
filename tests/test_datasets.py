from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from optimizer_benchmark.config import DEFAULT_CASE_PATH
from optimizer_benchmark.datasets import load_dataset, load_fixed_case
from optimizer_benchmark.generate_dataset import generate_dataset

DATASET_DIRECTORY = Path("data/datasets/phase2-v1")


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


def test_phase2_dataset_contains_fixed_16_cases() -> None:
    dataset = load_dataset(DATASET_DIRECTORY / "manifest.json")

    assert dataset.generation == "phase2-v1"
    assert len(dataset.cases) == 16
    assert {
        (case.staff_count, case.pattern) for case in dataset.cases
    } == {
        (staff_count, pattern)
        for staff_count in (10, 20, 30, 40)
        for pattern in (
            "baseline",
            "random_requests",
            "fixed_assignments",
            "stress",
        )
    }
    assert len(dataset.dataset_hash) == 64
    assert all(len(case.input_hash) == 64 for case in dataset.cases)


def test_phase2_dataset_is_reproducible(tmp_path) -> None:
    generated_directory = tmp_path / "phase2-v1"
    generate_dataset(generated_directory)

    expected_files = sorted(
        path.relative_to(DATASET_DIRECTORY)
        for path in DATASET_DIRECTORY.rglob("*.json")
    )
    generated_files = sorted(
        path.relative_to(generated_directory)
        for path in generated_directory.rglob("*.json")
    )
    assert generated_files == expected_files
    for relative_path in expected_files:
        assert (generated_directory / relative_path).read_bytes() == (
            DATASET_DIRECTORY / relative_path
        ).read_bytes()


def test_phase2_patterns_have_expected_fixed_assignments() -> None:
    dataset = load_dataset(DATASET_DIRECTORY / "manifest.json")

    for case in dataset.cases:
        assignments = case.payload["fixed_assignments"]
        off_request_counts = Counter(
            item["staff_id"]
            for item in assignments
            if item["shift_type"] == "off_request"
        )
        if case.pattern in {"random_requests", "fixed_assignments"}:
            assert set(off_request_counts.values()) == {2}
            assert len(off_request_counts) == case.staff_count
        elif case.pattern == "stress":
            assert set(off_request_counts.values()) <= {3, 4}
            assert len(off_request_counts) == case.staff_count
        else:
            assert not off_request_counts

        if case.pattern == "fixed_assignments":
            override_keys = {
                (item["staff_id"], item["date"])
                for item in case.payload["user_override_assignment_keys"]
            }
            override_types = {
                item["shift_type"]
                for item in assignments
                if (item["staff_id"], item["date"]) in override_keys
            }
            assert {"day", "night", "after_night", "off"} <= override_types


def test_manifest_hashes_match_case_files() -> None:
    manifest = json.loads(
        (DATASET_DIRECTORY / "manifest.json").read_text(encoding="utf-8")
    )
    dataset = load_dataset(DATASET_DIRECTORY / "manifest.json")

    assert manifest["case_count"] == 16
    assert manifest["dataset_hash"] == dataset.dataset_hash
    assert {item["seed"] for item in manifest["cases"]} == {
        20261100 + staff_count * 10 + pattern_index
        for staff_count in (10, 20, 30, 40)
        for pattern_index in range(4)
    }
