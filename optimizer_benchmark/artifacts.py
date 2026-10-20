"""入力・API応答の原本JSONを試行単位で保存する。"""

from __future__ import annotations

import json
from pathlib import Path

from .models import BenchmarkCase


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save_input(self, run_id: int, case: BenchmarkCase) -> Path:
        trial_directory = self._trial_directory(run_id)
        path = trial_directory / "input.json"
        path.write_bytes(case.source_path.read_bytes())
        return path

    def save_response(self, run_id: int, response_body: dict) -> Path:
        trial_directory = self._trial_directory(run_id)
        path = trial_directory / "response.json"
        path.write_text(
            json.dumps(response_body, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def _trial_directory(self, run_id: int) -> Path:
        path = self.root / f"run-{run_id}" / "trial-1"
        path.mkdir(parents=True, exist_ok=True)
        return path
