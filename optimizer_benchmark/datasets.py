"""固定ベンチマークケースを読み込み、原本ハッシュを計算する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import BenchmarkCase, BenchmarkDataset

REQUIRED_PAYLOAD_KEYS = {
    "month_dates",
    "staff_members",
    "fixed_assignments",
    "effective_rules",
    "previous_consecutive_work_days",
    "effective_off_days",
    "configured_off_days",
    "user_override_assignment_keys",
}


def load_fixed_case(path: Path) -> BenchmarkCase:
    raw_bytes = path.read_bytes()
    payload = json.loads(raw_bytes)
    if not isinstance(payload, dict):
        raise ValueError("固定ケースのJSONルートはオブジェクトである必要があります。")
    missing_keys = REQUIRED_PAYLOAD_KEYS - payload.keys()
    if missing_keys:
        raise ValueError(
            "固定ケースに必須フィールドがありません: "
            + ", ".join(sorted(missing_keys))
        )
    staff_count = len(payload["staff_members"])
    if staff_count != 20:
        raise ValueError(f"Phase 1の固定ケースは20人必要です: {staff_count}人")
    return BenchmarkCase(
        case_id="demo-20-baseline-v1",
        name="Ns Shift Trial相当 20人 baseline",
        staff_count=staff_count,
        pattern="baseline",
        dataset_generation="demo-v1",
        seed=0,
        source_path=path,
        input_hash=hashlib.sha256(raw_bytes).hexdigest(),
        payload=payload,
    )


def load_dataset(manifest_path: Path) -> BenchmarkDataset:
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict):
        raise ValueError("データセットmanifestのJSONルートはオブジェクトが必要です。")
    generation = str(manifest["generation"])
    cases = tuple(
        _load_manifest_case(manifest_path.parent, generation, item)
        for item in manifest["cases"]
    )
    if len(cases) != 16:
        raise ValueError(f"Phase 2データセットは16ケース必要です: {len(cases)}件")
    case_ids = {case.case_id for case in cases}
    if len(case_ids) != len(cases):
        raise ValueError("データセット内のcase_idが重複しています。")
    dataset_hash = _dataset_hash(cases)
    if dataset_hash != manifest["dataset_hash"]:
        raise ValueError("データセット全体のハッシュがmanifestと一致しません。")
    return BenchmarkDataset(
        generation=generation,
        manifest_path=manifest_path,
        manifest_hash=hashlib.sha256(manifest_bytes).hexdigest(),
        dataset_hash=dataset_hash,
        cases=cases,
    )


def _load_manifest_case(
    dataset_directory: Path,
    generation: str,
    item: dict,
) -> BenchmarkCase:
    path = dataset_directory / item["path"]
    raw_bytes = path.read_bytes()
    input_hash = hashlib.sha256(raw_bytes).hexdigest()
    if input_hash != item["input_hash"]:
        raise ValueError(f"{item['case_id']}の入力ハッシュが一致しません。")
    payload = json.loads(raw_bytes)
    _validate_payload(payload, expected_staff_count=int(item["staff_count"]))
    return BenchmarkCase(
        case_id=str(item["case_id"]),
        name=str(item["name"]),
        staff_count=int(item["staff_count"]),
        pattern=str(item["pattern"]),
        dataset_generation=generation,
        seed=int(item["seed"]),
        source_path=path,
        input_hash=input_hash,
        payload=payload,
    )


def _validate_payload(payload: dict, *, expected_staff_count: int) -> None:
    if not isinstance(payload, dict):
        raise ValueError("固定ケースのJSONルートはオブジェクトである必要があります。")
    missing_keys = REQUIRED_PAYLOAD_KEYS - payload.keys()
    if missing_keys:
        raise ValueError(
            "固定ケースに必須フィールドがありません: "
            + ", ".join(sorted(missing_keys))
        )
    staff_count = len(payload["staff_members"])
    if staff_count != expected_staff_count:
        raise ValueError(
            f"manifestと固定ケースの人数が一致しません: "
            f"{expected_staff_count}人 / {staff_count}人"
        )
    if len(payload["month_dates"]) != len(payload["effective_rules"]):
        raise ValueError("対象日と実効ルールの件数が一致しません。")


def _dataset_hash(cases: tuple[BenchmarkCase, ...]) -> str:
    value = "\n".join(
        f"{case.case_id}:{case.input_hash}" for case in sorted(cases, key=lambda x: x.case_id)
    )
    return hashlib.sha256(value.encode()).hexdigest()
