"""Optimizer BenchmarkのStreamlit UI。"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from optimizer_benchmark.artifacts import ArtifactStore
from optimizer_benchmark.config import Settings
from optimizer_benchmark.runner import BenchmarkRunner
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


settings = Settings.from_env()
storage = get_storage(str(settings.database_path))

st.title("Optimizer Benchmark")
st.caption("Phase 1: Ns Shift Trial相当20人・baseline・1試行")

with st.form("benchmark-run"):
    api_url = st.text_input("Optimizer API URL", value=settings.api_url)
    api_key = st.text_input(
        "Optimizer API Key",
        value=settings.api_key,
        type="password",
    )
    version_name = st.text_input("バージョン名", value="local-current")
    change_summary = st.text_area("変更概要", value="Phase 1 benchmark")
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
    st.info("保存済みの測定履歴はありません。")
else:
    run_ids = [run["id"] for run in runs]
    selected_default = st.session_state.get("selected_run_id", run_ids[0])
    selected_index = run_ids.index(selected_default) if selected_default in run_ids else 0
    selected_run_id = st.selectbox(
        "保存済みの測定履歴",
        options=run_ids,
        index=selected_index,
        format_func=lambda run_id: next(
            f"#{run['id']} {run['version_name']} / {run['case_name']} / {run['status']}"
            for run in runs
            if run["id"] == run_id
        ),
    )
    render_report(storage.get_run_report(selected_run_id))
