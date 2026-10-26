"""1ケース・1試行の実行、評価、永続化を順番に調整する。"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import httpx

from .artifacts import ArtifactStore
from .client import OptimizerClient
from .datasets import load_dataset, load_fixed_case
from .evaluator import evaluate_schedule
from .storage import BenchmarkStorage

MODE_TRIALS = {"quick": 1, "standard": 3, "full": 10}
ProgressCallback = Callable[[int, int, str, int], None]


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
        optimizer_source_directory: Path | None = None,
    ) -> None:
        self.storage = storage
        self.artifacts = artifacts
        self.api_url = api_url
        self.optimizer_source_directory = optimizer_source_directory
        self.client = OptimizerClient(
            api_url=api_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )

    def run_once(self, *, case_path, version_name: str, change_summary: str) -> dict:
        case = load_fixed_case(case_path)
        self.storage.register_case(case)
        version_id = self.storage.get_or_create_version(
            version_name,
            change_summary,
            **_git_snapshot(self.optimizer_source_directory),
        )
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

    def run_suite(
        self,
        *,
        manifest_path: Path,
        version_name: str,
        change_summary: str,
        mode: str,
        progress_callback: ProgressCallback | None = None,
    ) -> dict:
        if mode not in MODE_TRIALS:
            raise ValueError(f"未対応の実行モードです: {mode}")
        dataset = load_dataset(manifest_path)
        self.storage.register_dataset(dataset)
        for case in dataset.cases:
            self.storage.register_case(case)
        version_id = self.storage.get_or_create_version(
            version_name,
            change_summary,
            **_git_snapshot(self.optimizer_source_directory),
        )
        environment = _environment_snapshot()
        trials_per_case = MODE_TRIALS[mode]
        suite_id = self.storage.create_suite(
            version_id=version_id,
            dataset=dataset,
            mode=mode,
            trials_per_case=trials_per_case,
            api_url=self.api_url,
            environment=environment,
        )
        for case in dataset.cases:
            self.storage.create_run(
                version_id=version_id,
                case=case,
                api_url=self.api_url,
                environment=environment,
                suite_id=suite_id,
                planned_trials=trials_per_case,
            )
        return self._execute_suite(
            suite_id=suite_id,
            dataset_cases={case.case_id: case for case in dataset.cases},
            progress_callback=progress_callback,
        )

    def resume_suite(
        self,
        suite_id: int,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> dict:
        suite = self.storage.get_suite(suite_id)
        if suite["api_url"] != self.api_url:
            raise ValueError(
                "再開時のAPI URLが保存済み実行と一致しません: "
                f"{suite['api_url']}"
            )
        dataset = load_dataset(Path(suite["manifest_path"]))
        if dataset.generation != suite["dataset_generation"]:
            raise ValueError("保存済み実行とデータセット世代が一致しません。")
        if dataset.manifest_hash != suite["manifest_hash"]:
            raise ValueError("保存済み実行とmanifestハッシュが一致しません。")
        self.storage.set_suite_status(suite_id, "running")
        return self._execute_suite(
            suite_id=suite_id,
            dataset_cases={case.case_id: case for case in dataset.cases},
            progress_callback=progress_callback,
        )

    def _execute_suite(
        self,
        *,
        suite_id: int,
        dataset_cases: dict,
        progress_callback: ProgressCallback | None,
    ) -> dict:
        work_items = self.storage.get_suite_work_items(suite_id)
        total = sum(int(item["planned_trials"]) for item in work_items)
        completed = sum(len(item["completed_trial_numbers"]) for item in work_items)
        try:
            for item in work_items:
                case = dataset_cases[item["case_id"]]
                for trial_number in range(1, int(item["planned_trials"]) + 1):
                    if trial_number in item["completed_trial_numbers"]:
                        continue
                    if progress_callback:
                        progress_callback(completed, total, case.case_id, trial_number)
                    self._execute_trial(
                        run_id=int(item["run_id"]),
                        case=case,
                        trial_number=trial_number,
                    )
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, total, case.case_id, trial_number)
                self.storage.finish_run(int(item["run_id"]))
        except (KeyboardInterrupt, Exception):
            self.storage.set_suite_status(suite_id, "interrupted")
            raise
        self.storage.set_suite_status(suite_id, "completed")
        return self.storage.get_suite_summary(suite_id)

    def _execute_trial(
        self,
        *,
        run_id: int,
        case,
        trial_number: int,
    ) -> None:
        input_path = self.artifacts.save_input(run_id, case, trial_number)
        result = self.client.generate(case.payload)
        response_path = (
            self.artifacts.save_response(run_id, result.response_body, trial_number)
            if result.response_body is not None
            else None
        )
        trial_id = self.storage.record_trial(
            run_id=run_id,
            result=result,
            input_path=input_path,
            response_path=response_path,
            trial_number=trial_number,
        )
        if result.generation_succeeded and result.response_body is not None:
            quality = evaluate_schedule(
                case.payload,
                result.response_body.get("shifts", []),
            )
            self.storage.record_quality(trial_id, quality)


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


def _git_snapshot(source_directory: Path | None) -> dict:
    snapshot = {
        "git_sha": None,
        "git_dirty": None,
        "git_source_path": None,
    }
    if source_directory is None:
        return snapshot
    resolved = source_directory.resolve()
    snapshot["git_source_path"] = str(resolved)
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=resolved,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=resolved,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return snapshot
    snapshot["git_sha"] = sha or None
    snapshot["git_dirty"] = bool(status.strip())
    return snapshot
