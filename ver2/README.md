# 朝一トーラー Ver.2 — Production pipeline

Ver.2は、ChatGPTの研究・画像・Gmail工程と、GitHub Actionsの決定論的C-layerを分離して運用します。既存Ver.1、001–034、開発実験050、既存成果物は原則として削除・上書きしません。

## 責任分離

### ChatGPT

1. 当日アリヤー全節を研究する
2. 私訳、文脈的逐語訳、簡易説明、詳しい解説を作成する
3. `ver2/content/NNN-commentary.json` を `asaichi-torah-ver2` ブランチへsemantic handoffする
4. semantic handoff確定時点で、当日の研究データから一時的な CURRENT RUN IMAGE PACKAGE を組み立てる
5. GitHubから `ver2/config/image-master.json` と当該パラシャーの画像profileを取得し、GLOBAL MASTER + PARASHA PROFILE + CURRENT RUN IMAGE PACKAGE だけを使って画像生成する
6. GitHub delivery auditの `page_url` を取得し、最終Gmailを送信する

画像生成の前提としてNotionページを再取得しません。画像生成に必要な意味内容はsemantic handoff確定時点のChatGPT側データを正本とします。

ChatGPT側Notion connectorの `create_attachment` callable schemaは本番配送経路では使用しません。

### GitHub Actions

1. 固定OSHB/MorphHBからWLC・lemma・形態情報を結合
2. commentary merge、schema検証、placeholder拒否
3. 各節HTML生成・受入検査
4. PocketTorah音声r1/r2生成・検査
5. Notion File Upload APIへ各節HTMLを直接アップロードし、成功分を `embed.file_upload` として配置
6. attachment失敗節だけGitHub Pagesへfallback公開
7. Notion APIを直接呼び、本番ページを作成
8. 作成後のNotionページを再取得し、HTML・音声・toggle・デボーショナル項目等を検品
9. `ver2/state/NNN-notion-delivery.json` に監査結果、`page_id`、`page_url` を保存

GitHubは画像を生成しません。画像用の固定configを保管し、Notion完成後はdelivery auditを介して `page_url` をChatGPTへ引き渡します。

## HTML delivery router

通常経路は `NOTION_ATTACHMENT` です。

- 全節attachment成功: `HTML_MODE=NOTION_ATTACHMENT`
- 一部失敗: 成功attachmentを保持し、失敗節だけPagesへ公開して `HTML_MODE=MIXED`
- 全節失敗: `HTML_MODE=GITHUB_PAGES`
- Pagesでは既存同名が完全一致なら再利用し、不一致なら `-r2`, `-r3` ... を新規作成して既存版を上書きしない

## 画像生成の三層構造

### 1. GLOBAL IMAGE MASTER

`ver2/config/image-master.json`

全「朝一トーラー」共通の固定仕様を保持します。1200×630、左側情報領域＋右側本文場面、文字階層、禁止事項、fresh generation方針、QA基準等を含みます。

### 2. PARASHA IMAGE PROFILE

`ver2/config/parasha-image/index.json` で、日本語パラシャー名からprofileファイルを完全一致で解決します。

例:

- `ハイェイ・サラ` → `ver2/config/parasha-image/chayei-sarah.json`

profileには、そのパラシャー内で統一する配色、質感、光、雰囲気、古代世界の表現原則だけを保存します。過去回のNNN、場面、画像、gen_idは保存しません。

### 3. CURRENT RUN IMAGE PACKAGE

ChatGPTが当日のsemantic handoff確定時に、当日の全データから一時的に作成します。最低限、次を含みます。

- `IMAGE_NNN`
- `IMAGE_PARASHA`
- `IMAGE_ALIYAH`
- `IMAGE_RANGE`
- `IMAGE_CALLOUT2`
- `IMAGE_THEME`
- `IMAGE_SCENE_SUMMARY`
- `IMAGE_REQUIRED_TEXT`

CURRENT RUN IMAGE PACKAGEは画像生成のための当日データであり、専用監査JSONとしてGitHubへ恒久保存しません。

画像生成入力は必ず次の三層だけです。

1. GLOBAL IMAGE MASTER
2. CURRENT PARASHA PROFILE
3. CURRENT RUN IMAGE PACKAGE

Notionページ、過去画像、失敗画像、過去gen_idは画像生成の入力元にしません。

## 画像失敗情報

画像専用の監査JSONは新規作成しません。失敗・BLOCKED・QA不合格・再試行状況は、RUN最後の未完了Gmailに具体的原因を記録します。必要な場合はGmailの送信済み内容を監査記録として参照します。

## Notion delivery

GitHub ActionsがNotion APIを直接使用します。必要なGitHub Secretsは次の2点です。

- `NOTION_TOKEN`
- `NOTION_PARENT_PAGE_ID`

本番ページの基本構造は以下です。

- 青Callout: PARASHA / ALIYAH / RANGE
- 青Callout: 当日範囲の約200字要約
- 各節: 節見出し → r2音声 → 私訳 → HTML embed → 簡易な説明 → 詳しい解説toggle
- 各toggle末尾: `デボーショナルな受けとめ`

開発仕様やPASS/FAIL表は読者向けNotion本文へ表示しません。

## 主要ファイル

- `schema/current.schema.json` — semantic handoff契約
- `input/current.json` — 当日処理対象
- `content/NNN-commentary.json` — ChatGPT研究成果
- `config/image-master.json` — 全回共通画像MASTER
- `config/parasha-image/index.json` — パラシャー画像profile index
- `config/parasha-image/*.json` — パラシャー単位デザイン情報
- `scripts/enrich_morphhb.py` — 固定本文・形態情報結合
- `scripts/merge_commentary.py` — 研究結果結合
- `scripts/build_html.py` / `verify_html.py` — HTML生成・QA
- `scripts/build_audio.py` / `verify_audio.py` — 音声生成・QA
- `scripts/prepare_notion_html.py` — Notion File Upload API用HTML router
- `scripts/publish_pages.py` — fallback時のみimmutable Pages公開
- `scripts/notion_delivery.py` — GitHub-owned Notion API delivery / post-write QA
- `published/NNN/` — 本番生成資産
- `state/NNN-notion-html-route.json` — HTML route監査
- `state/NNN-pages-map.json` — fallback時のPages実URL監査
- `state/NNN-notion-delivery.json` — Notion配送監査・`page_url` handoff
- `state/production.json` — 本番連番状態

## 安全原則

- 050は開発実験であり、本番連番判定から除外する
- 本番連番は必要工程が完全成功したRUNだけ1つ進める
- 既存成功成果物を異なる内容で上書きしない
- Secretをrepository内のコード・JSON・ログへ書かない
- MODEL_AUDIO/GPT-Transcribeは通常工程の成功条件にしない
- 画像生成はNotion読込に依存させない
- 新規の画像監査JSONを作らない
