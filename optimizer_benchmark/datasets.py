"""固定ベンチマークケースを読み込み、原本ハッシュを計算する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import BenchmarkCase

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
