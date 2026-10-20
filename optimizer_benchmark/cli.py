"""Streamlitを使わずベンチマークを実行・参照するCLI。"""

from __future__ import annotations

import argparse
import json

from .artifacts import ArtifactStore
from .config import Settings
from .runner import BenchmarkRunner
from .storage import BenchmarkStorage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Optimizer Benchmark")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="固定ケースを1回実行する")
    run_parser.add_argument("--version-name", required=True)
    run_parser.add_argument("--change-summary", default="")
    subparsers.add_parser("history", help="保存済み実行を一覧表示する")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_env()
    storage = BenchmarkStorage(settings.database_path)
    if args.command == "history":
        print(json.dumps(storage.list_runs(), ensure_ascii=False, indent=2))
        return
    if not settings.api_key:
        raise SystemExit("OPTIMIZER_API_KEYを設定してください。")
    runner = BenchmarkRunner(
        storage=storage,
        artifacts=ArtifactStore(settings.artifacts_directory),
        api_url=settings.api_url,
        api_key=settings.api_key,
        timeout_seconds=settings.timeout_seconds,
    )
    report = runner.run_once(
        case_path=settings.case_path,
        version_name=args.version_name,
        change_summary=args.change_summary,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
