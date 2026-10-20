"""1ケース・1試行の実行、評価、永続化を順番に調整する。"""

from __future__ import annotations

import os
import platform
import sys

import httpx

from .artifacts import ArtifactStore
from .client import OptimizerClient
from .datasets import load_fixed_case
from .evaluator import evaluate_schedule
from .storage import BenchmarkStorage


class BenchmarkRunner:
    def __init__(
        self,
        *,
        storage: BenchmarkStorage,
        artifacts: ArtifactStore,
        api_url: str,
        api_key: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.storage = storage
        self.artifacts = artifacts
        self.api_url = api_url
        self.client = OptimizerClient(
            api_url=api_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )

    def run_once(self, *, case_path, version_name: str, change_summary: str) -> dict:
        case = load_fixed_case(case_path)
        self.storage.register_case(case)
        version_id = self.storage.get_or_create_version(version_name, change_summary)
        run_id = self.storage.create_run(
            version_id=version_id,
            case=case,
            api_url=self.api_url,
            environment=_environment_snapshot(),
        )
        try:
            input_path = self.artifacts.save_input(run_id, case)
            result = self.client.generate(case.payload)
            response_path = (
                self.artifacts.save_response(run_id, result.response_body)
                if result.response_body is not None
                else None
            )
            trial_id = self.storage.record_trial(
                run_id=run_id,
                result=result,
                input_path=input_path,
                response_path=response_path,
            )
            if result.generation_succeeded and result.response_body is not None:
                quality = evaluate_schedule(
                    case.payload,
                    result.response_body.get("shifts", []),
                )
                self.storage.record_quality(trial_id, quality)
            self.storage.finish_run(run_id)
        except Exception:
            self.storage.finish_run(run_id, status="interrupted")
            raise
        return self.storage.get_run_report(run_id)


def _environment_snapshot() -> dict:
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor() or None,
        "cpu_count": os.cpu_count(),
        "benchmark_python_executable": sys.executable,
        "ortools_version": None,
        "optimizer_worker_count": None,
        "solver_seed": None,
    }
