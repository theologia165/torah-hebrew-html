# Work stage｜Gmail delivery and state

RUNの最後に、途中失敗があっても接続済みGmail自身（to: me）へ実送信する。送信前に同日・同NNN・同件名のSentを検索し、重複を防ぐ。

- `delivery.json.status == PASS`：`ver3/templates/gmail-success.txt`を使い、件名をNotionページ名に一致させる。page_url、CALLOUT2、完了、FANBOX、Facebookを記し、合格画像を添付する。
- `PARTIAL / BLOCKED / FAIL`：`ver3/templates/gmail-partial.txt`を使い、「【未完了】＋Notionページ名」で送る。成功成果物、失敗工程、status・message、対象、直前成功工程、再試行、代替経路、確定／推定原因、残作業、媒体別実装数を具体的に記す。合格画像だけ添付し、別回画像を代用しない。

一時的送信失敗はSentに存在しないことを確認して最大2回再試行する。認証・権限・ツール不存在では同じ操作を連打しない。

送信後はSentを再確認する。全条件PASSかつ送信確認済みの場合だけ、次の二つを同一コミットで記録する。

1. `ver3/runs/{run_id}/completion.json`を作成する。`schema_version`は`1.0-work-completion`、`run_id`、3桁`sequence`、`delivery_status: PASS`、deliveryと同じ`page_id`／`page_url`、`gmail.message_id`／`gmail.subject`／`gmail.sent_verified: true`、UTCの`completed_at`を必須とする。
2. `ver3/state/production.json`の`last_completed`へ同じrun_id・page・Gmail証明を記録し、`next_sequence`と`next_passage`を次の標準アリヤーへ一つだけ進める。

`delivery.json=PASS`だけでは完了ではない。Actionsの最終完了ゲートは、delivery、completion.json、production stateの三者とGmail証明が一致した場合だけ`next_action=NONE`を返す。不一致時は同じNotionページを再作成せず、`SEND_SUCCESS_EMAIL_AND_ADVANCE_STATE`へ戻す。
