# Work entry｜朝一トーラーVer.3

これは定期実行時にWorkが最初に読む短い入口である。詳細仕様を最初から一括で読まず、当該RUNの`handoff.json`が指定するstage specとrequired inputsだけを読む。

## 不変の責任分界

- Neon／ActionsはWLC本文、token ID、lemma、形態、媒体変換と機械検査を担当する。
- Workは当該RUNのJSON1.1だけから逐語訳、私訳、解説、三層研究、出典、デボーショナルな受けとめを作り、JSON2の意味品質をコミット前に保証する。
- Actionsの構造PASSをJSON2の意味内容PASSへ読み替えない。
- 過去RUNのJSON2／JSON3、Notionページ、画像、メールを研究材料として読まない。過去RUNから継承できるのは失敗code、HTTP status、page_id等の運用監査だけである。
- PARTIALでも正常な本文・HTML・cover・他節音声を配信する。全条件PASSまでproduction stateを進めない。

## 実行

1. `ver3/state/production.json`と当日Sent、実行中Actions、対象RUNのdeliveryを照合し、完了済みNNNを複製しない。
2. 対象RUNが未作成ならproduction stateの範囲から固有run_idの`ver3/request.json`を作り、コミットしてVer.3 Actionsを起動する。
3. RUN作成後は`ver3/runs/{run_id}/handoff.json`の`next_action`だけを実行する。
4. `CREATE_JSON2`では`json2-quality.md`、`GENERATE_QA_AND_UPLOAD_COVER`では`image-handoff.md`、メール工程では`email-delivery.md`だけを追加で読む。
5. BLOCKED／PARTIALでは`failure-report.md`に従って詳細を残す。同じ失敗操作を根拠なく反復しない。
6. 必要な入力・監査結果をコミットし、Ver.3 Actionsを起動して次のhandoffまたはdelivery確定まで確認する。

旧Ver.2ブランチ、既存035、実験050は変更しない。「静かに〜」という表現は使用しない。

