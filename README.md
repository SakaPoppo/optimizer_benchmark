# Optimizer Benchmark

Ns Shiftのoptimizer APIを、固定入力で実行して応答時間と基本品質を保存・表示する開発者向けツールです。Phase 2では10・20・30・40人×4パターンの固定16ケースを、Quick / Standard / Fullの3モードで実行できます。

## 構成

- `httpx`による認証付き`POST /generate`
- Runner側での外部応答時間計測
- APIの`issues`から独立した基本品質評価
- SQLiteへのバージョン・実行・試行・品質メトリクス保存
- JSONファイルへの入力・API応答原本の保存
- CLI実行とStreamlitレポート
- seed・入力ハッシュ付きの固定16ケース
- Quick 16回 / Standard 48回 / Full 160回の逐次実行
- 1試行ごとの保存、中断後の未実行分からの再開
- 実行状態・成功率・平均・中央値・p95・ケース別の基本集計

固定ケースは`data/cases/demo_20_baseline_v1.json`です。Ns Shift Trialの実コードから2026年11月分を生成して固定しています。対象年月は仕様上未決定のため、Phase 1の暫定値です。

API内部のフェーズ時間、CPU、メモリ、OR-Toolsバージョン、worker数、solver seedはPhase 1では取得せず「未計測」と表示します。

## セットアップ

Python 3.12以上を使用します。

optimizer APIを先に起動します。

```bash
cd ../ns-shift-optimizer-api
docker compose up --build
```

Benchmarkの環境を用意します。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

`.env`の`OPTIMIZER_API_KEY`には、optimizer APIと同じローカル開発用キーを設定します。キーはGitにコミットしません。

## CLIで一括実行

環境変数を読み込んで実行します。

```bash
set -a
source .env
set +a
python -m optimizer_benchmark.cli run-suite \
  --version-name local-current \
  --change-summary "Phase 2 benchmark" \
  --mode quick
```

一括測定の履歴と、中断した実行の再開は次のコマンドで操作できます。

```bash
python -m optimizer_benchmark.cli suites
python -m optimizer_benchmark.cli resume-suite --suite-id 1
```

Phase 1の単体測定は `run`、履歴表示は `history`で引き続き利用できます。

## Streamlit

```bash
streamlit run app.py
```

画面からAPI URL、APIキー、バージョン名、変更概要、実行モードを入力して一括測定できます。結果はSQLiteに保存されるため、Streamlitを再起動しても履歴から再表示・再開できます。

## 開発用チェック

```bash
ruff check .
python -m pytest
```
