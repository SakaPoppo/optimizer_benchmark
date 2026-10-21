"""環境変数と既定パスから実行設定を構築する。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_PATH = PROJECT_ROOT / "data" / "cases" / "demo_20_baseline_v1.json"
DEFAULT_DATASET_MANIFEST_PATH = (
    PROJECT_ROOT / "data" / "datasets" / "phase2-v1" / "manifest.json"
)


def _resolve_path(value: str, default: Path) -> Path:
    path = Path(value) if value else default
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True)
class Settings:
    api_url: str
    api_key: str
    timeout_seconds: float
    database_path: Path
    artifacts_directory: Path
    case_path: Path = DEFAULT_CASE_PATH
    dataset_manifest_path: Path = DEFAULT_DATASET_MANIFEST_PATH

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_url=os.getenv("OPTIMIZER_API_URL", "http://localhost:8080"),
            api_key=os.getenv("OPTIMIZER_API_KEY", ""),
            timeout_seconds=float(
                os.getenv("OPTIMIZER_API_TIMEOUT_SECONDS", "300")
            ),
            database_path=_resolve_path(
                os.getenv("BENCHMARK_DB_PATH", ""),
                PROJECT_ROOT / "data" / "benchmark.db",
            ),
            artifacts_directory=_resolve_path(
                os.getenv("BENCHMARK_ARTIFACTS_DIR", ""),
                PROJECT_ROOT / "artifacts",
            ),
            dataset_manifest_path=_resolve_path(
                os.getenv("BENCHMARK_DATASET_MANIFEST", ""),
                DEFAULT_DATASET_MANIFEST_PATH,
            ),
        )
