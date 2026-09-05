# 朝一トーラー Ver.2 — GitHub automation experiment

このディレクトリは既存の朝一トーラー（Ver.1）から独立した実験環境です。
`main` ブランチ上の既存HTMLを変更しません。

## 現在の接続範囲

1. ChatGPT Work が `input/current.json` を生成・更新する
2. GitHub Actions が JSON Schema を検証する
3. 論理検査（節範囲・必須項目等）を行う
4. 検査PASS時だけHTMLを自動生成する
5. 生成HTMLをWorkflow Artifactとして保存する

現段階では Notion投稿、音声処理、画像生成、メール送信は接続していません。

## Work → GitHub の契約

Workは自由形式の文章ではなく、`schema/current.schema.json` に適合するJSONだけを
`input/current.json` として渡します。GitHub側は内容を再解釈せず、決定論的に処理します。

## ディレクトリ

- `schema/current.schema.json` — Work出力の正式契約
- `input/current.example.json` — 参照例
- `input/current.json` — 自動処理対象
- `scripts/validate.py` — Schema・節範囲検査
- `scripts/build_html.py` — HTML自動生成
- `output/` — Actions実行時の生成先（Artifactに保存）

## 安全原則

- Ver.1の `030`〜`034` 等の既存ディレクトリは変更しない
- Schema検証に失敗した場合は後工程へ進まない
- SecretsをコードやJSONへ書かない
- Notionやメール等の外部書込みは、個別工程が安定してから追加する
