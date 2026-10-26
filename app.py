"""Optimizer BenchmarkのStreamlit UI。"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from optimizer_benchmark.artifacts import ArtifactStore
from optimizer_benchmark.config import Settings
from optimizer_benchmark.runner import MODE_TRIALS, BenchmarkRunner
from optimizer_benchmark.storage import BenchmarkStorage

st.set_page_config(page_title="Optimizer Benchmark", layout="wide")


@st.cache_resource
def get_storage(database_path: str) -> BenchmarkStorage:
    return BenchmarkStorage(Path(database_path))


def render_report(report: dict) -> None:
    st.subheader(f"Run #{report['run_id']} 測定レポート")
    st.caption(
        f"{report['version_name']} / {report['case_name']} / "
        f"dataset={report['dataset_generation']} / hash={report['input_hash'][:12]}…"
    )
    st.caption(
        f"ローカルAPIソースSHA="
        f"{report['git_sha'][:12] if report.get('git_sha') else '未取得'} / "
        f"未コミット変更="
        f"{'あり' if report.get('git_dirty') else 'なし' if report.get('git_dirty') is not None else '未取得'}"
    )
    first, second, third, fourth = st.columns(4)
    first.metric("試行状態", report.get("trial_status") or "未実行")
    second.metric("HTTP", report.get("http_status") or "未計測")
    elapsed = report.get("elapsed_seconds")
    third.metric("外部応答時間", f"{elapsed:.3f}秒" if elapsed is not None else "未計測")
    fourth.metric("Solver", report.get("solver_status") or "未計測")

    if report.get("error_message"):
        st.error(f"{report['error_type']}: {report['error_message']}")

    st.markdown("#### 基本品質")
    if report.get("evaluator_version"):
        day_counts = report.get("day_counts") or {}
        night_counts = report.get("night_counts") or {}
        quality_columns = st.columns(4)
        quality_columns[0].metric(
            "日勤人数範囲",
            f"{min(day_counts.values())}〜{max(day_counts.values())}" if day_counts else "未計測",
        )
        quality_columns[1].metric(
            "夜勤回数範囲",
            f"{min(night_counts.values())}〜{max(night_counts.values())}"
            if night_counts
            else "未計測",
        )
        quality_columns[2].metric(
            "最大連勤",
            report.get("maximum_consecutive_work_days", "未計測"),
        )
        quality_columns[3].metric(
            "独立評価の違反",
            report.get("hard_violation_count", "未計測"),
        )
        fairness_columns = st.columns(3)
        night_stddev = report.get("night_count_standard_deviation")
        fairness_columns[0].metric(
            "夜勤回数の標準偏差",
            f"{night_stddev:.3f}" if night_stddev is not None else "未計測",
        )
        fairness_columns[1].metric(
            "勤務日数の最大差",
            report.get("work_count_difference", "未計測"),
        )
        fairness_columns[2].metric(
            "休日数の最大差",
            report.get("off_count_difference", "未計測"),
        )
        st.write(f"評価器バージョン: `{report['evaluator_version']}`")
        st.dataframe(
            [
                {
                    "日付": target_date,
                    "日勤人数": count,
                    "必要人数との差": report["day_staffing_deltas"][target_date],
                }
                for target_date, count in day_counts.items()
            ],
            width="stretch",
            hide_index=True,
        )
        with st.expander("スタッフ別夜勤回数"):
            st.json(night_counts)
        with st.expander("日別能力合計と期待値からの偏差"):
            st.dataframe(
                [
                    {
                        "日付": target_date,
                        "日勤能力合計": total,
                        "日勤偏差%": (
                            report.get("day_ability_deviations", {}).get(target_date)
                        ),
                        "夜勤能力合計": (
                            report.get("night_ability_totals", {}).get(target_date)
                        ),
                        "夜勤偏差%": (
                            report.get("night_ability_deviations", {}).get(target_date)
                        ),
                    }
                    for target_date, total in (
                        report.get("day_ability_totals") or {}
                    ).items()
                ],
                width="stretch",
                hide_index=True,
            )
        with st.expander("スタッフ別勤務回数"):
            st.json(report.get("shift_counts_by_staff") or {})
        with st.expander("独立評価の制約違反"):
            st.json(report.get("violations") or [])
    else:
        st.info("生成結果がないため品質は未計測です。")

    st.markdown("#### API応答")
    st.dataframe(
        report.get("phase_results") or [],
        width="stretch",
        hide_index=True,
    )
    with st.expander("API issues"):
        st.json(report.get("issues") or [])

    st.markdown("#### API内部計測")
    if report.get("internal_elapsed_seconds") is None:
        st.info("この履歴はPhase 3計測導入前のため未計測です。")
    else:
        resource_columns = st.columns(4)
        resource_columns[0].metric(
            "API内部時間", f"{report['internal_elapsed_seconds']:.3f}秒"
        )
        resource_columns[1].metric(
            "CPU時間", f"{report['cpu_time_seconds']:.3f}秒"
        )
        resource_columns[2].metric(
            "CPU使用率", f"{report['cpu_percent']:.1f}%"
        )
        resource_columns[3].metric(
            "ピークメモリ", f"{report['peak_memory_mb']:.1f} MB"
        )
        st.dataframe(
            [
                {"項目": "コンテキスト構築", "秒": report["context_build_seconds"]},
                {"項目": "モデル構築", "秒": report["model_build_seconds"]},
                {"項目": "結果変換", "秒": report["result_build_seconds"]},
            ],
            width="stretch",
            hide_index=True,
        )
        st.caption(
            f"CPU上限={report.get('cpu_limit') or '未計測'} / "
            f"logical CPU={report.get('logical_cpu_count') or '未計測'} / "
            f"workers={report.get('optimizer_worker_count') or '未計測'} / "
            f"seed={report.get('solver_seed') if report.get('solver_seed') is not None else '未計測'} / "
            f"OR-Tools={report.get('ortools_version') or '未計測'}"
        )
    st.caption(
        f"入力原本: {report.get('input_path')} / 応答原本: "
        f"{report.get('response_path') or '未取得'}"
    )
    with st.expander("実行環境"):
        st.json(report.get("environment") or {})


def render_suite_report(report: dict) -> None:
    st.subheader(f"Suite #{report['id']} 測定レポート")
    st.caption(
        f"{report['version_name']} / {report['mode']} / "
        f"dataset={report['dataset_generation']} / "
        f"hash={report['dataset_hash'][:12]}…"
    )
    st.write(report.get("change_summary") or "変更概要なし")
    git_sha = report.get("git_sha")
    dirty_label = (
        "あり" if report.get("git_dirty") else "なし"
        if report.get("git_dirty") is not None
        else "未取得"
    )
    st.caption(
        f"ローカルAPIソースSHA={git_sha[:12] if git_sha else '未取得'} / "
        f"未コミット変更={dirty_label} / "
        "実際に動作したAPIプロセスとの一致は保証しません"
    )
    completed = int(report["completed_trials"])
    total = int(report["total_trials"])
    success_rate = report.get("success_rate")
    first, second, third, fourth = st.columns(4)
    first.metric("実行状態", report["status"])
    second.metric("進捗", f"{completed}/{total}")
    third.metric(
        "生成成功率",
        f"{success_rate * 100:.1f}%" if success_rate is not None else "未計測",
    )
    average = report.get("average_elapsed_seconds")
    fourth.metric(
        "平均応答時間",
        f"{average:.3f}秒" if average is not None else "未計測",
    )

    timing_columns = st.columns(2)
    median = report.get("median_elapsed_seconds")
    p95 = report.get("p95_elapsed_seconds")
    timing_columns[0].metric(
        "応答時間の中央値",
        f"{median:.3f}秒" if median is not None else "未計測",
    )
    timing_columns[1].metric(
        f"応答時間 p95（n={completed}）",
        f"{p95:.3f}秒" if p95 is not None else "未計測",
    )

    resources = report.get("resource_metrics") or {}
    if resources.get("average_internal_elapsed_seconds") is not None:
        st.markdown("#### API内部リソース")
        resource_columns = st.columns(4)
        resource_columns[0].metric(
            "平均API内部時間",
            f"{resources['average_internal_elapsed_seconds']:.3f}秒",
        )
        resource_columns[1].metric(
            "平均CPU時間",
            f"{resources['average_cpu_time_seconds']:.3f}秒",
        )
        resource_columns[2].metric(
            "平均CPU使用率",
            f"{resources['average_cpu_percent']:.1f}%",
        )
        resource_columns[3].metric(
            "最大ピークメモリ",
            f"{resources['maximum_peak_memory_mb']:.1f} MB",
        )
        st.caption(
            f"CPU上限={resources.get('cpu_limit') or '未計測'} / "
            f"logical CPU={resources.get('logical_cpu_count') or '未計測'} / "
            f"workers={resources.get('optimizer_worker_count') or '未計測'} / "
            f"seed={resources.get('solver_seed') if resources.get('solver_seed') is not None else '未計測'} / "
            f"OR-Tools={resources.get('ortools_version') or '未計測'}"
        )

    phase_metrics = report.get("phase_metrics") or []
    if phase_metrics:
        st.markdown("#### フェーズ別ボトルネック")
        st.bar_chart(
            phase_metrics,
            x="phase_name",
            y="average_wall_time_seconds",
        )
        st.dataframe(phase_metrics, width="stretch", hide_index=True)

    case_results = report.get("case_results") or []
    if case_results:
        st.markdown("#### ケース別応答時間")
        chart_rows = [
            {
                "ケース": row["case_name"],
                "平均応答時間（秒）": row["average_elapsed_seconds"],
            }
            for row in case_results
            if row["average_elapsed_seconds"] is not None
        ]
        if chart_rows:
            st.bar_chart(
                chart_rows,
                x="ケース",
                y="平均応答時間（秒）",
            )
        st.dataframe(
            [
                {
                    "ケース": row["case_name"],
                    "人数": row["staff_count"],
                    "パターン": row["pattern"],
                    "完了": f"{row['completed_trials']}/{row['planned_trials']}",
                    "成功": row["successful_trials"] or 0,
                    "平均秒": row["average_elapsed_seconds"],
                    "API内部秒": row["average_internal_elapsed_seconds"],
                    "CPU%": row["average_cpu_percent"],
                    "ピークMB": row["maximum_peak_memory_mb"],
                    "平均制約違反": row["average_hard_violations"],
                    "平均最大連勤": (
                        row["average_maximum_consecutive_work_days"]
                    ),
                    "夜勤標準偏差": (
                        row["average_night_count_standard_deviation"]
                    ),
                    "勤務日数差": row["average_work_count_difference"],
                    "休日数差": row["average_off_count_difference"],
                }
                for row in case_results
            ],
            width="stretch",
            hide_index=True,
        )

    with st.expander("実行環境と計測条件"):
        st.json(
            {
                "benchmark_environment": report.get("environment") or {},
                "api_metrics": report.get("resource_metrics") or {},
                "api_url": report.get("api_url"),
                "local_api_source_path": report.get("git_source_path"),
            }
        )

    trial_results = report.get("trial_results") or []
    if trial_results:
        with st.expander("試行明細"):
            st.dataframe(trial_results, width="stretch", hide_index=True)


def render_comparison(comparison: dict) -> None:
    baseline = comparison["baseline"]
    target = comparison["target"]
    st.subheader(
        f"Suite #{baseline['id']} → Suite #{target['id']} バージョン比較"
    )
    st.caption(
        f"{baseline['version_name']} ({baseline.get('git_sha') or 'SHA未取得'}) → "
        f"{target['version_name']} ({target.get('git_sha') or 'SHA未取得'})"
    )
    for warning in comparison["warnings"]:
        if warning["severity"] == "error":
            st.error(warning["message"])
        else:
            st.warning(warning["message"])

    summary = comparison["summary"]
    summary_columns = st.columns(4)
    summary_specs = (
        ("生成成功率", "success_rate", "percent"),
        ("平均応答時間", "average_elapsed_seconds", "seconds"),
        ("中央値", "median_elapsed_seconds", "seconds"),
        ("p95", "p95_elapsed_seconds", "seconds"),
    )
    for column, (label, key, kind) in zip(summary_columns, summary_specs):
        values = summary[key]
        target_value = values["target"]
        delta = values["delta"]
        if kind == "percent":
            value_label = (
                f"{target_value * 100:.1f}%"
                if target_value is not None
                else "未計測"
            )
            delta_label = f"{delta * 100:+.1f}pt" if delta is not None else None
        else:
            value_label = (
                f"{target_value:.3f}秒"
                if target_value is not None
                else "未計測"
            )
            percent_change = values.get("percent_change")
            delta_label = (
                f"{delta:+.3f}秒 ({percent_change:+.1f}%)"
                if delta is not None and percent_change is not None
                else f"{delta:+.3f}秒" if delta is not None else None
            )
        column.metric(label, value_label, delta_label, delta_color="inverse")

    rows = comparison.get("case_comparisons") or []
    if not rows:
        st.info("比較可能な同一ケースがありません。")
        return
    st.markdown("#### 同一ケース比較")
    st.dataframe(
        [
            {
                "ケース": row["case_name"],
                "人数": row["staff_count"],
                "パターン": row["pattern"],
                "元成功率": row["baseline_success_rate"],
                "先成功率": row["target_success_rate"],
                "成功率差": row["success_rate_delta"],
                "元平均秒": row["baseline_average_elapsed_seconds"],
                "先平均秒": row["target_average_elapsed_seconds"],
                "秒差": row["elapsed_seconds_delta"],
                "時間変化%": row["elapsed_percent_change"],
                "制約違反差": row["average_hard_violations_delta"],
                "最大連勤差": (
                    row["average_maximum_consecutive_work_days_delta"]
                ),
                "夜勤標準偏差差": (
                    row["average_night_count_standard_deviation_delta"]
                ),
                "勤務日数差の変化": row["average_work_count_difference_delta"],
                "休日数差の変化": row["average_off_count_difference_delta"],
            }
            for row in rows
        ],
        width="stretch",
        hide_index=True,
    )


def render_version_report(report: dict) -> None:
    st.subheader(f"{report['name']} バージョン別レポート")
    st.write(report.get("change_summary") or "変更概要なし")
    st.json(
        {
            "git_sha": report.get("git_sha"),
            "git_dirty": report.get("git_dirty"),
            "git_source_path": report.get("git_source_path"),
            "created_at": report.get("created_at"),
            "suite_count": report.get("suite_count"),
            "standalone_run_count": report.get("standalone_run_count"),
        }
    )
    suites = report.get("suites") or []
    if suites:
        st.markdown("#### 一括測定履歴")
        st.dataframe(
            [
                {
                    "Suite": suite["id"],
                    "開始": suite["started_at"],
                    "mode": suite["mode"],
                    "dataset": suite["dataset_generation"],
                    "状態": suite["status"],
                    "進捗": (
                        f"{suite['completed_trials']}/{suite['total_trials']}"
                    ),
                    "成功率": suite["success_rate"],
                    "平均秒": suite["average_elapsed_seconds"],
                    "中央値": suite["median_elapsed_seconds"],
                    "p95": suite["p95_elapsed_seconds"],
                }
                for suite in suites
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("このバージョンの一括測定はありません。")

    standalone_runs = report.get("standalone_runs") or []
    if standalone_runs:
        st.markdown("#### 単体測定履歴")
        st.dataframe(standalone_runs, width="stretch", hide_index=True)


settings = Settings.from_env()
storage = get_storage(str(settings.database_path))

st.title("Optimizer Benchmark")
st.caption("Phase 4: 保存済み結果のバージョン別レポート・比較")

suite_tab, legacy_tab, comparison_tab, version_tab = st.tabs(
    ["一括測定", "単体測定", "バージョン比較", "バージョン別レポート"]
)

with suite_tab:
    mode_labels = {
        "quick": "Quick（16ケース × 1試行 = 16回）",
        "standard": "Standard（16ケース × 3試行 = 48回）",
        "full": "Full（16ケース × 10試行 = 160回）",
    }
    with st.form("benchmark-suite"):
        suite_api_url = st.text_input(
            "Optimizer API URL",
            value=settings.api_url,
            key="suite-api-url",
        )
        suite_api_key = st.text_input(
            "Optimizer API Key",
            value=settings.api_key,
            type="password",
            key="suite-api-key",
        )
        suite_version_name = st.text_input(
            "バージョン名",
            value="local-current",
            key="suite-version-name",
        )
        suite_change_summary = st.text_area(
            "変更概要",
            value="Phase 4 benchmark",
            key="suite-change-summary",
        )
        suite_mode = st.selectbox(
            "実行モード",
            options=list(MODE_TRIALS),
            format_func=mode_labels.get,
        )
        suite_submitted = st.form_submit_button("新規に一括実行")

    if suite_submitted:
        if not suite_api_key:
            st.error("Optimizer API Keyを入力してください。")
        elif not suite_version_name.strip():
            st.error("バージョン名を入力してください。")
        else:
            progress = st.progress(0, text="一括測定を開始します。")

            def update_progress(
                completed: int,
                total: int,
                case_id: str,
                trial_number: int,
            ) -> None:
                ratio = completed / total if total else 0
                progress.progress(
                    ratio,
                    text=f"{completed}/{total} {case_id} trial-{trial_number}",
                )

            runner = BenchmarkRunner(
                storage=storage,
                artifacts=ArtifactStore(settings.artifacts_directory),
                api_url=suite_api_url,
                api_key=suite_api_key,
                timeout_seconds=settings.timeout_seconds,
                optimizer_source_directory=settings.optimizer_source_directory,
            )
            try:
                suite_report = runner.run_suite(
                    manifest_path=settings.dataset_manifest_path,
                    version_name=suite_version_name.strip(),
                    change_summary=suite_change_summary.strip(),
                    mode=suite_mode,
                    progress_callback=update_progress,
                )
            except Exception as error:
                st.exception(error)
            else:
                st.session_state["selected_suite_id"] = suite_report["id"]
                progress.progress(1.0, text="一括測定が完了しました。")
                st.success("全試行の測定結果を保存しました。")

    suites = storage.list_suites()
    if not suites:
        st.info("保存済みの一括測定はありません。")
    else:
        suite_ids = [suite["id"] for suite in suites]
        default_suite_id = st.session_state.get("selected_suite_id", suite_ids[0])
        suite_index = (
            suite_ids.index(default_suite_id) if default_suite_id in suite_ids else 0
        )
        selected_suite_id = st.selectbox(
            "保存済みの一括測定",
            options=suite_ids,
            index=suite_index,
            format_func=lambda suite_id: next(
                f"#{suite['id']} {suite['version_name']} / {suite['mode']} / "
                f"{suite['completed_trials']}/{suite['total_trials']} / "
                f"{suite['status']}"
                for suite in suites
                if suite["id"] == suite_id
            ),
        )
        selected_suite = next(
            suite for suite in suites if suite["id"] == selected_suite_id
        )
        if selected_suite["status"] != "completed":
            st.info("再開時は保存済み試行を飛ばし、未実行分から続行します。")
            if st.button("選択した一括測定を再開"):
                if not suite_api_key:
                    st.error("Optimizer API Keyを入力してください。")
                else:
                    resume_progress = st.progress(0, text="再開します。")

                    def update_resume_progress(
                        completed: int,
                        total: int,
                        case_id: str,
                        trial_number: int,
                    ) -> None:
                        ratio = completed / total if total else 0
                        resume_progress.progress(
                            ratio,
                            text=(
                                f"{completed}/{total} {case_id} "
                                f"trial-{trial_number}"
                            ),
                        )

                    runner = BenchmarkRunner(
                        storage=storage,
                        artifacts=ArtifactStore(settings.artifacts_directory),
                        api_url=suite_api_url,
                        api_key=suite_api_key,
                        timeout_seconds=settings.timeout_seconds,
                        optimizer_source_directory=(
                            settings.optimizer_source_directory
                        ),
                    )
                    try:
                        runner.resume_suite(
                            selected_suite_id,
                            progress_callback=update_resume_progress,
                        )
                    except Exception as error:
                        st.exception(error)
                    else:
                        st.session_state["selected_suite_id"] = selected_suite_id
                        st.success("一括測定を完了しました。")
                        st.rerun()
        render_suite_report(storage.get_suite_summary(selected_suite_id))

with legacy_tab:
    st.caption("Ns Shift Trial相当20人・baseline・1試行")
    with st.form("benchmark-run"):
        api_url = st.text_input(
            "Optimizer API URL",
            value=settings.api_url,
            key="legacy-api-url",
        )
        api_key = st.text_input(
            "Optimizer API Key",
            value=settings.api_key,
            type="password",
            key="legacy-api-key",
        )
        version_name = st.text_input(
            "バージョン名",
            value="local-current",
            key="legacy-version-name",
        )
        change_summary = st.text_area(
            "変更概要",
            value="Phase 4 benchmark",
            key="legacy-change-summary",
        )
        submitted = st.form_submit_button("1回実行")

    if submitted:
        if not api_key:
            st.error("Optimizer API Keyを入力してください。")
        elif not version_name.strip():
            st.error("バージョン名を入力してください。")
        else:
            runner = BenchmarkRunner(
                storage=storage,
                artifacts=ArtifactStore(settings.artifacts_directory),
                api_url=api_url,
                api_key=api_key,
                timeout_seconds=settings.timeout_seconds,
                optimizer_source_directory=settings.optimizer_source_directory,
            )
            with st.spinner("optimizer APIを実行しています..."):
                try:
                    report = runner.run_once(
                        case_path=settings.case_path,
                        version_name=version_name.strip(),
                        change_summary=change_summary.strip(),
                    )
                except Exception as error:
                    st.exception(error)
                else:
                    st.session_state["selected_run_id"] = report["run_id"]
                    st.success("測定結果を保存しました。")

    runs = storage.list_runs()
    if not runs:
        st.info("保存済みの単体測定はありません。")
    else:
        run_ids = [run["id"] for run in runs]
        selected_default = st.session_state.get("selected_run_id", run_ids[0])
        selected_index = (
            run_ids.index(selected_default) if selected_default in run_ids else 0
        )
        selected_run_id = st.selectbox(
            "保存済みの単体測定",
            options=run_ids,
            index=selected_index,
            format_func=lambda run_id: next(
                f"#{run['id']} {run['version_name']} / "
                f"{run['case_name']} / {run['status']}"
                for run in runs
                if run["id"] == run_id
            ),
        )
        render_report(storage.get_run_report(selected_run_id))

with comparison_tab:
    comparable_suites = storage.list_suites()
    if len(comparable_suites) < 2:
        st.info("比較には保存済みの一括測定が2件以上必要です。")
    else:
        comparable_suite_ids = [suite["id"] for suite in comparable_suites]

        def suite_label(suite_id: int) -> str:
            suite = next(
                item for item in comparable_suites if item["id"] == suite_id
            )
            return (
                f"#{suite['id']} {suite['version_name']} / {suite['mode']} / "
                f"{suite['dataset_generation']} / {suite['status']}"
            )

        comparison_columns = st.columns(2)
        with comparison_columns[0]:
            baseline_suite_id = st.selectbox(
                "比較元Suite",
                options=comparable_suite_ids,
                index=1,
                format_func=suite_label,
            )
        with comparison_columns[1]:
            target_options = [
                suite_id
                for suite_id in comparable_suite_ids
                if suite_id != baseline_suite_id
            ]
            target_suite_id = st.selectbox(
                "比較対象Suite",
                options=target_options,
                index=0,
                format_func=suite_label,
            )
        render_comparison(
            storage.compare_suites(baseline_suite_id, target_suite_id)
        )

with version_tab:
    versions = storage.list_versions()
    if not versions:
        st.info("保存済みのバージョンはありません。")
    else:
        version_ids = [version["id"] for version in versions]
        selected_version_id = st.selectbox(
            "保存済みバージョン",
            options=version_ids,
            format_func=lambda version_id: next(
                f"{version['name']} / Suite {version['suite_count']}件 / "
                f"単体 {version['standalone_run_count']}件"
                for version in versions
                if version["id"] == version_id
            ),
        )
        render_version_report(storage.get_version_report(selected_version_id))
