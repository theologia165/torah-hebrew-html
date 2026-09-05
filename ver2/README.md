# 朝一トーラー Ver.2 — Production pipeline

Ver.2は、ChatGPTの研究工程とGitHub Actionsの決定論的C-layerを分離して運用します。既存Ver.1、001–034、開発実験050、既存成果物は削除・上書きしません。

## 責任分離

### ChatGPT

1. 当日アリヤー全節を研究する
2. 私訳、文脈的逐語訳、簡易説明、詳しい解説を作成する
3. `ver2/content/NNN-commentary.json` を `asaichi-torah-ver2` ブランチへsemantic handoffする
4. GitHub delivery auditで完成したNotionページを確認後、画像生成とGmail最終配信を行う

ChatGPT側Notion connectorの `create_attachment` callable schemaは本番配送経路では使用しません。

### GitHub Actions

1. 固定OSHB/MorphHBからWLC・lemma・形態情報を結合
2. commentary merge、schema検証、placeholder拒否
3. 各節HTML生成・受入検査
4. PocketTorah音声r1/r2生成・検査
5. HTMLをGitHub Pagesへ公開
6. `ver2/state/NNN-pages-map.json` に実際の公開URLを固定
7. Notion APIを直接呼び、本番ページを作成
8. 作成後のNotionページを再取得し、HTML embed・音声等を検品
9. `ver2/state/NNN-notion-delivery.json` に監査結果を保存

## GitHub Pagesの不変性

Pagesの公開元は `main` ブランチのrootです。

- 新規HTMLは `/{NNN}/genesis-X-Y.html` へ公開
- 同名既存ファイルと内容が完全一致すれば再利用
- 内容が異なる場合、既存ファイルを上書きせず `-r2`, `-r3` ... を新規作成
- Notionは固定URLを推測せず、必ず `NNN-pages-map.json` に記録された実URLをembedする

これにより、再RUNでも過去HTMLを破壊せず、Notionが古い版を誤参照することを防ぎます。

## Notion delivery

GitHub ActionsがNotion APIを直接使用します。必要なGitHub Actions設定は次の2点です。

- Secret: `NOTION_TOKEN`
- Secretまたはrepository configurationとして参照可能な値: `NOTION_PARENT_PAGE_ID`

現在のworkflowは両方をGitHub Secretsとして参照します。未設定の場合はChatGPT側で代替作成せず、`BLOCKED_MISSING_NOTION_SECRET` として監査記録を残し、本番連番を進めません。

本番ページの基本構造は以下です。

- 青Callout: PARASHA / ALIYAH / RANGE
- 青Callout: 当日範囲の約200字要約
- 各節: 節見出し → r2音声 → 私訳 → GitHub Pages HTML embed → 簡易な説明 → 詳しい解説

開発仕様やPASS/FAIL表は読者向けNotion本文へ表示しません。

## 主要ファイル

- `schema/current.schema.json` — semantic handoff契約
- `input/current.json` — 当日処理対象
- `content/NNN-commentary.json` — ChatGPT研究成果
- `scripts/enrich_morphhb.py` — 固定本文・形態情報結合
- `scripts/merge_commentary.py` — 研究結果結合
- `scripts/build_html.py` / `verify_html.py` — HTML生成・QA
- `scripts/build_audio.py` / `verify_audio.py` — 音声生成・QA
- `scripts/publish_pages.py` — immutable Pages公開とURL manifest生成
- `scripts/notion_delivery.py` — GitHub-owned Notion API delivery / post-write QA
- `published/NNN/` — 本番生成資産
- `state/NNN-pages-map.json` — Pages実URL監査
- `state/NNN-notion-delivery.json` — Notion配送監査
- `state/production.json` — 本番連番状態

## 安全原則

- 050は開発実験であり、本番連番判定から除外する
- 本番連番は必要工程が完全成功したRUNだけ1つ進める
- 既存ファイルを異なる内容で上書きしない
- Secretをrepository内のコード・JSON・ログへ書かない
- MODEL_AUDIO/GPT-Transcribeは通常工程の成功条件にしない
