from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_streamlit_phase2_screen_renders(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BENCHMARK_DB_PATH", str(tmp_path / "benchmark.db"))
    monkeypatch.setenv("BENCHMARK_ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    app = AppTest.from_file(Path(__file__).parents[1] / "app.py").run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "Optimizer Benchmark"
    assert [tab.label for tab in app.tabs] == [
        "Phase 2 一括測定",
        "Phase 1 単体測定",
    ]
    assert any(button.label == "新規に一括実行" for button in app.button)
