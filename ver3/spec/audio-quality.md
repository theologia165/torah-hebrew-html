# Work stage｜音声品質管理部

入口は`ver3/quality/audio/README.md`、障害・修正台帳は`ver3/quality/audio/incidents.json`、実行入口は`ver3/scripts/audio_quality.py`。音声問題の担当部署をここへ固定し、毎回独立した場当たり的な修正をしない。音声バイナリを文字コンテキストへ展開しない。聴取／ASRに渡す場合はローカルファイルとして扱う。

## 1. 受付と検品

症状、対象RUN・節、原音上の発生位置、期待する末尾語、実際に切れた語、影響範囲を確定し、台帳の過去事例と照合する。過去RUNの研究本文を入力にせず、運用監査だけを参照する。

```sh
python ver3/scripts/audio_quality.py inspect ver3/runs/{run_id}
```

既存の独立機械検査、当該RUNの朗読用token数、ファイル実体、台帳の既知障害を確認し、`audio-quality.json`と`audio-quality-review-template.json`を作る。未検品の雛形にPASSを自動記入しない。

全節を聴取するか、ASRと語・境界の実音声照合を行い、テンプレートを元に`audio-content-review.json`へ記録する。`reviewer`、`method`、`reviewed_at`、全節の6項目と節ごとの具体的根拠を必須とする。方法は`HUMAN_LISTENING`、`MODEL_AUDIO_LISTENING`、`ASR_WITH_BOUNDARY_REVIEW`。ASR出力だけ、波形だけ、語数だけでは全項目をPASSにしない。音声を扱う機能が使えない場合はPENDINGのまま理由を残す。

各節で確認するもの：冒頭語、末尾語、全語の順序、前後節の混入なし、語中・語尾の切断なし、学習用速度。最初と最後だけの抜き取りを全節検品としない。reviewのRUN・本文・manifest・r1/r2 hashは変更せず、対象を生成し直したら再検品する。

## 2. 原因分類と修正

物理欠損、ラベル形式／語対応、局所境界、速度、取得エラー、検品の漏れを区別する。ラベルがN個かN+1個か、先頭0かだけで形式を断定しない。原音の冒頭・末尾・複数の節境界と本文を照合する。未確認の境界問題を物理欠損へ読み替えてTTSで隠さない。代替方針の正本は`ver3/config/audio-fallback.json`と既存resolverである。

実装変更後は台帳の回帰コマンドを実行する。再発事例をテストに追加し、実装状態と音声再配信の状態を別々に記録する。修正コードを書いただけで案件をCLOSEDにしない。

## 3. 既完了ページの修復

```sh
python ver3/scripts/audio_quality.py request-repair ver3/runs/{run_id} \
  --repair-id boundary-r1 --incident AUDIO-085-LABEL-OFFSET \
  --reason '第1節末からの語対応ずれを修復'
```

同じrepair_idを再利用しない。未解決の依頼を別依頼で上書きしない。依頼をコミットした後、Ver.3 Actionsの`audio_quality_run_id`へ対象run_idを指定して実行する。通常のrequest.jsonやproduction stateを別RUNへ巻き戻さない。

Actionsは当該RUNから候補を生成し、`audio-repairs/{repair_id}/`へ保存する。`next_action=REVIEW_AND_REPAIR_AUDIO`では、handoff指定の報告・雛形・当該RUNのaudio-inputだけを基に候補を検品し、同じrepairディレクトリの`audio-content-review.json`をコミットする。再び同じActions入力で実行する。過去RUNを修復する場合はレビューのpushだけでは別RUNの通常実行となり得るため、必ず対象run_idを指定する。

候補がBLOCKEDなら原因修正を先に行い、`audio_quality.py cancel-repair ver3/runs/{run_id} --reason '原因・中止理由'`で中止履歴を残してから、新しいrepair_idで候補を再生成する。CANCELLEDを修復成功と扱わない。既存候補のmanifestや音声を都合よく改変して旧検品を流用しない。

機械検査＋全節の内容検品がPASSになるまで公開音声を差し替えない。合格後だけ旧MP3とmanifestを`before/`へ保存し、同じpage_idの音声を更新する。公開バイト列とNotionの再取得検証後、`closed.json`と`audio-repair.done.json`へ証明を残す。本文・HTML・画像・メール・production stateを修復のために再作成しない。

## 4. 報告

必ず「機械検査」「内容検品」「修復・公開」の三つを別に述べる。既存の通常配信で内容検品がPENDINGなら、メールでもその事実を省かず、音声品質全件合格と書かない。完全に検品できない場合は検品方法の制約と残作業を明記する。
