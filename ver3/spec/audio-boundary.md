# Work stage｜配信前の音声境界検品

Actionsが抜粋・OpenAI観察・候補生成・機械検査・部分再検品を実行し、Workが原因、修復方針、採用音声、メール報告を判断する。利用者による発見を待たない。

**直せない・聞き取れない・API利用不能・予算到達でも、再生可能な従来音声で配信する。未解決をPASSへ変えず、メールで伝える。** 配信完了と修復完了は別に記録し、境界未解決だけで翌回の番号進行を止めない。従来からの媒体欠落によるPARTIALは別契約。既存audio-quality.mdの厳格な全節内容検品は、明示的に依頼された既完了ページ修復用として維持する。

## 通常検品と費用制御

正本は当該RUNのaudio-input.jsonの朗読対象語。配信用r2の全実装節の冒頭・末尾を各4秒調べる。8秒以下は重複を避け全体を一度だけ送る。期待する語は各3token。抜粋で作った内側の切断端は判定しない。朗唱・無音等で足りなければUNCERTAIN。比較用TTSは作らず、出力は短い判定・聞こえた語・音響上の根拠に限定する。Workは全件一覧と疑わしい箇所の根拠を読む。音声・base64を文字コンテキストへ展開しない。

設定はver3/config/audio-boundary.json。RUN合計で抜粋240秒、12要求、1要求6抜粋・出力900token、保守的見積0.40 USD。初回・詳査・再検品で同じ予算を共有する。USDはアプリの見積であり請求額の保証ではない。秒数・要求数・出力tokenも独立に制限する。認証・残高・通信・応答形式エラーは理由を保存し、そのRUNの追加API要求を止める。自動再試行しない。

要求を送信前にusage.jsonへ記録する。中断した要求も使用済みとし、Actions再実行で予算をリセットしない。同じ音声hash・抜粋範囲・期待本文・モデル・検品条件は結果を再利用する。manifestが変わっても未変更音声は継承。APIのusageがあれば実使用量と見積料金も記録する。

## Workの引き継ぎ

next_action=REVIEW_AUDIO_BOUNDARIESのrequired inputsを読む。decision-template.jsonを元に同じ場所のdecision.jsonを作る。必須はschema_version、run_id、現在のreport_sha256、action、reviewer、reviewed_at、具体的evidence。雛形を承認として扱わない。

| action | Workの指定と次の処理 |
|---|---|
| DELIVER_CURRENT | 観察を判断し現在の音声で配信。未解決でもこのactionを使い、メールへ残件を記載 |
| INSPECT_CONTEXT | 現在のproblem_edgesからedges（例 `["6:16/tail"]`）を指定。固定hash原音の切れ目前後各6秒を追加観察。1回まで |
| REQUEST_REPAIR | 根拠のあるcutsを指定。原音から変更節と共有境界の隣接節だけを作り直し、別置き候補を検査。1回まで |
| ADOPT_CANDIDATE | 改善を確認できた候補を採用。機械合格と変更節の境界観察PASSを再照合し、旧音声を保存して採用 |

指定例：`"cuts": [{"ref":"6:16","side":"tail","seconds":52.7}]`。secondsは原音全体の秒数。context.jsonのsuggested_cut_secondsは抜粋内なのでstartを加算する。モデルの提案をそのまま確定せず、聞こえた語・本文・無音・元の境界から判断する。共有境界は片側一件だけ指定しActionsが両節を更新する。最初・最後の外側境界も修正できる。一律の時間移動や別音源の補正は流用しない。

候補はaudio-boundary/candidate/へ保存し従来音声を上書きしない。未変更節のMP3・観察は再利用する。修復失敗・候補不合格・予算到達・試行上限ではDELIVER_CURRENTへ戻す。音声に不十分な点が残っても配信する。decisionのコミットで通常Actionsを再開する。対象は通常request.jsonで選択中のRUN。過去RUNは従来のaudio_quality_run_idを使う。

## 証明と完了

finalization.jsonは本文・manifest・全配信MP3のhash、Work判断、採用候補、修復試行、未解決、使用量記録を結ぶ。BOUNDARY_PASSは境界のみ確認、DELIVER_WITH_UNRESOLVED_BOUNDARIESは未解決のまま配信。どちらもfull_content_verified=false。全6項目の内容PASSやMODEL_AUDIO_CHECKEDへ昇格させない。節中央の脱落・全語順の正しさを保証しない。

メールには境界検品結果、修復有無、採用音声、未解決の節・冒頭/末尾・理由を記す。API障害・予算到達・修復失敗も省かない。媒体が揃えば未解決でも通常の配信完了メールへ音声残件を併記する。completion.jsonのaudio_boundary.finalization_sha256へ証明hashを転記し、必要な報告を実送信・Sent確認したらaudio_boundary.disclosed_in_email=trueとする。完了ゲートは報告証明の一致を確認するが、境界PASSは番号進行の条件にしない。

既完了RUNや093〜095の個別修復を、この機能導入のために再実行しない。新しい通常RUNから適用する。

## 明示依頼された既完了回の境界再検品

利用者が過去回を新方式で再検品・必要時修正するよう明示した場合だけ、対象RUNのaudio-boundary/history-request.jsonにoperation=BOUNDED_HISTORICAL_BOUNDARY_REVIEW、run_id、既存page_id、reason、repair_if_confirmed=true、before（現行音声のidentity）を記録する。このrequestまたは当該RUNのdecision.jsonのpushは、audio_boundary_history.pyが通常production requestと分離して対象回だけ処理する。既存のhandoff・delivery・completion・本番連番は保持し、再検品用handoffはhistory-handoff.jsonへ置く。予算・回数・候補採用条件は通常方式と同一。全内容PASSへ昇格しない。

採用候補がある場合だけ変更節の既存Notion audio blockを更新し、公開MP3実体・全audio URL・本文等の非音声blockとページ表紙の不変を読戻し確認する。候補がない場合は既存音声を検証するだけで変更しない。結果はhistory-closed.jsonへ残し、過去の配信完了証明は書き換えない。厳格な全内容修復は引き続きaudio_quality_run_idを使う。
