# Work stage｜Failure report

PARTIAL、BLOCKED、FAIL、SKIPが発生した場合は、`handoff.json`、`delivery.json`、該当する短いActions失敗出力から次を確定する。

1. 失敗工程名
2. 実行しようとした操作
3. error type、HTTP status、message
4. 対象ref、ファイル、API、ページまたは添付
5. 直前まで成功した工程
6. 再試行回数と各結果
7. 代替経路の実施有無と理由
8. 確定原因と推定原因の区別
9. 残作業

取得できない事項は「原因未確定」とし、推測を確定事項として書かない。正常な本文・HTML・cover・他節音声は保持し、欠落媒体だけを同じrun_id・page_idへ後日補う。未完了をPASSへ読み替えず、production stateを進めない。

