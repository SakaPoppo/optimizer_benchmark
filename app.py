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

    st.markdown("#### Phase 1では未計測")
    st.dataframe(
        [
            {"項目": "API内部処理時間・フェーズ別時間", "値": "未計測"},
            {"項目": "CPU使用率", "値": "未計測"},
            {"項目": "ピークメモリ", "値": "未計測"},
            {"項目": "OR-Toolsバージョン・worker数・solver seed", "値": "未計測"},
        ],
        width="stretch",
        hide_index=True,
    )
    st.caption(
        f"入力原本: {report.get('input_path')} / 応答原本: "
        f"{report.get('response_path') or '未取得'}"
    )


def render_suite_report(report: dict) -> None:
    st.subheader(f"Suite #{report['id']} 測定レポート")
    st.caption(
        f"{report['version_name']} / {report['mode']} / "
        f"dataset={report['dataset_generation']} / "
        f"hash={report['dataset_hash'][:12]}…"
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
                    "平均制約違反": row["average_hard_violations"],
                }
                for row in case_results
            ],
            width="stretch",
            hide_index=True,
        )


settings = Settings.from_env()
storage = get_storage(str(settings.database_path))

st.title("Optimizer Benchmark")
st.caption("Phase 2: 固定16ケースのQuick / Standard / Full測定")

suite_tab, legacy_tab = st.tabs(["Phase 2 一括測定", "Phase 1 単体測定"])

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
            value="Phase 2 benchmark",
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
            value="Phase 1 benchmark",
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
