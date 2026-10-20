# GitHub開発ワークフロー

Optimizer Benchmarkの開発では、Issue、作業ブランチ、Pull Request、GitHub Actionsを一連の流れとして使用します。PRのマージは開発者が手動で行います。

## Issue管理

- 新しい作業を始める前に既存Issueを検索し、重複するIssueを作成しない。
- Issueには作業の目的、背景、実装内容、完了条件、関連仕様を記載する。
- 必要に応じて `feature`、`bug`、`refactor`、`test`、`documentation` などのラベルを使用する。
- 必要なラベルが存在しない場合は、作成権限があれば追加する。権限がない場合はラベルなしで作成し、その旨を報告する。

## ブランチ管理

- mainを最新状態にしてから作業ブランチを作成する。
- mainへ直接コミット・直接pushしない。
- 既存の未コミット変更を破棄しない。作業範囲外の変更は同一PRへ含めない。
- ブランチ名は `種類/Issue番号-作業内容` とし、Issue番号を必ず含める。
- 作業内容には英小文字を使用し、単語をハイフンで区切る。

例：

- `feat/123-add-benchmark-runner`
- `fix/124-fix-metrics-calculation`
- `refactor/125-refactor-quality-evaluator`
- `test/126-add-runner-tests`
- `docs/127-update-specification`
- `chore/128-update-ci`

## コミット管理

コミットメッセージにはConventional Commits形式を使用します。

```text
type: description
```

例：

- `feat: add benchmark runner`
- `fix: correct night shift deviation calculation`
- `test: add quality evaluator tests`
- `docs: update benchmark specification`
- `ci: add GitHub Actions workflow`

## Pull Request管理

1つのIssueに対して、原則として1つのPRを作成します。

PRタイトルは次の形式に統一します。

```text
feat: ベンチマーク実行機能を追加 (#123)
```

PR本文には次の内容を記載します。

- 概要
- 関連Issue（`Closes #123`）
- 変更内容
- テスト結果
- 仕様への影響
- レビュー時の確認事項

PR作成後はGitHub Actionsの結果を確認します。CIが失敗した場合は原因を調査し、テストやチェックを弱めずに修正します。

## マージ管理

- CI成功をマージの前提条件とする。
- PRのマージは必ず開発者が手動で行い、Codexは自動マージしない。
- 原則としてSquash mergeを使用する。
- PR本文に `Closes #番号` を記載し、マージ後にIssueが自動クローズされるようにする。
- マージ後は不要になった作業ブランチを削除する。

## Codexによる標準作業手順

1. `AGENTS.md`、`docs/SPECIFICATION.md`、`docs/DEVELOPMENT_PLAN.md`、本書を確認する。
2. 対応する既存Issueを検索し、必要な場合だけ新規Issueを作成する。
3. Issue番号を含む作業ブランチを作成する。
4. 仕様と作業範囲に従って実装する。
5. Ruff、pytest、関連する動作確認を実行する。
6. 変更をコミットして作業ブランチへpushする。
7. 関連Issueを紐付けたPRを作成する。
8. GitHub Actionsの完了を待ち、失敗した場合は原因を修正する。
9. CI成功後にIssue、PR、CIのURLと作業結果を報告する。

次の変更は実装前に開発者へ確認します。

- optimizerAPI本体の仕様変更
- データベースの破壊的変更
- 大きなアーキテクチャ変更
- 既存機能の削除
- 仕様書に記載のない大規模な機能追加

GitHubの認証・権限不足で操作できない場合は、操作を実行したと扱わず、未完了の操作と必要な設定を報告します。
