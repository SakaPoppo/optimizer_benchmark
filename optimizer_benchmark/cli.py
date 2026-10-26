"""Streamlitを使わずベンチマークを実行・参照するCLI。"""

from __future__ import annotations

import argparse
import json

from .artifacts import ArtifactStore
from .config import Settings
from .runner import MODE_TRIALS, BenchmarkRunner
from .storage import BenchmarkStorage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Optimizer Benchmark")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="固定ケースを1回実行する")
    run_parser.add_argument("--version-name", required=True)
    run_parser.add_argument("--change-summary", default="")
    suite_parser = subparsers.add_parser(
        "run-suite", help="Phase 2データセットを指定モードで実行する"
    )
    suite_parser.add_argument("--version-name", required=True)
    suite_parser.add_argument("--change-summary", default="")
    suite_parser.add_argument("--mode", choices=MODE_TRIALS, required=True)
    resume_parser = subparsers.add_parser(
        "resume-suite", help="中断したPhase 2実行を再開する"
    )
    resume_parser.add_argument("--suite-id", type=int, required=True)
    subparsers.add_parser("history", help="保存済み実行を一覧表示する")
    subparsers.add_parser("suites", help="保存済み一括実行を一覧表示する")
    subparsers.add_parser("versions", help="保存済みバージョンを一覧表示する")
    version_report_parser = subparsers.add_parser(
        "version-report", help="保存済みバージョンの詳細を表示する"
    )
    version_report_parser.add_argument("--version-id", type=int, required=True)
    compare_parser = subparsers.add_parser(
        "compare-suites", help="保存済み一括実行を比較する"
    )
    compare_parser.add_argument("--baseline-suite-id", type=int, required=True)
    compare_parser.add_argument("--target-suite-id", type=int, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_env()
    storage = BenchmarkStorage(settings.database_path)
    if args.command == "history":
        print(json.dumps(storage.list_runs(), ensure_ascii=False, indent=2))
        return
    if args.command == "suites":
        print(json.dumps(storage.list_suites(), ensure_ascii=False, indent=2))
        return
    if args.command == "versions":
        print(json.dumps(storage.list_versions(), ensure_ascii=False, indent=2))
        return
    if args.command == "version-report":
        report = storage.get_version_report(args.version_id)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    if args.command == "compare-suites":
        comparison = storage.compare_suites(
            args.baseline_suite_id,
            args.target_suite_id,
        )
        print(json.dumps(comparison, ensure_ascii=False, indent=2))
        return
    if not settings.api_key:
        raise SystemExit("OPTIMIZER_API_KEYを設定してください。")
    runner = BenchmarkRunner(
        storage=storage,
        artifacts=ArtifactStore(settings.artifacts_directory),
        api_url=settings.api_url,
        api_key=settings.api_key,
        timeout_seconds=settings.timeout_seconds,
        optimizer_source_directory=settings.optimizer_source_directory,
    )
    if args.command == "run":
        report = runner.run_once(
            case_path=settings.case_path,
            version_name=args.version_name,
            change_summary=args.change_summary,
        )
    elif args.command == "run-suite":
        report = runner.run_suite(
            manifest_path=settings.dataset_manifest_path,
            version_name=args.version_name,
            change_summary=args.change_summary,
            mode=args.mode,
            progress_callback=_print_progress,
        )
    else:
        report = runner.resume_suite(
            args.suite_id,
            progress_callback=_print_progress,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _print_progress(completed: int, total: int, case_id: str, trial_number: int) -> None:
    print(f"[{completed}/{total}] {case_id} trial-{trial_number}", flush=True)


if __name__ == "__main__":
    main()
