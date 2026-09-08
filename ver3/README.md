# 朝一トーラーVer.3

実行ブランチ：`asaichi-torah-ver3`。Actions：`.github/workflows/asaichi-torah-ver3.yml`。
旧版ブランチと既存035・050は変更しない。Ver.2の画像master/profileをver3/configへ複製して独立運用する。

## 二段階の受け渡し

1. ChatGPTが当日NNN・標準年周期アリヤーのWLC範囲を確定し、`ver3/request.json`をコミットする。run_idは`036-20260907-r1`のような一意値。既存RUNを再利用する時は内容を変えない。
2. GitHub ActionsがNeonから`ver3/runs/{run_id}/json1.json`を取得し、`json1.1.json`を決定論的に抽出して同じブランチへコミットする。JSON1には本文、token ID、全形態segment、lexeme、reference mapping、source versionを保持する。
3. ChatGPTはActions成功とJSON1.1を確認して研究し、同じディレクトリへ`json2.json`をコミットする。JSON1の本文・形態・lemmaを生成・修正しない。JSON1.1のJSON1ハッシュをそのまま使い、JSON1.1全体をprepare.digestと同じ正規化方式でSHA256計算して記載する。
4. Actionsが章節・語ID・両ハッシュを確認し、自己完結HTML、節別r1/r2音声を作成・検証する。全節のHTMLをGitHub Pagesへ配置し、公開URLから取得したバイト列と生成HTMLが一致した後、URL embedへ統一する。添付方式へは戻さない。ルート確定後にJSON1とJSON2から`json3.json`を生成し、そのchildrenをNotion APIへ送る。
5. 全ブロックの順序・本文・項目末尾の引用リンク・音声URL・Pages埋め込みURLと公開HTML内容を再取得して検査し、`delivery.json`を記録する。ChatGPTはこれを最終画像/Gmail工程で参照する。GitHubからChatGPTを自動呼出しする仕組みではなく、スケジュール実行中のChatGPTがActions完了を待ちJSON1.1を読み取る。

## JSON request

`schema_version: "3.0-request"`, `run_id`, `sequence`（3桁）, `mode`（通常`publish`：JSON2到着前は取得だけで待機）, `source: "morphhb-wlc"`, `book`（OSIS）, `book_jp`, `refs`（WLCの全対象節を順序通り列挙）, `passage`（book英名・chapter・end_chapter・start_verse・end_verse・display）を指定する。検証用`acceptance`はNotion/Gmailへ出力しない。

## JSON2 schema（本文研究の三層）

```json
{
  "schema_version": "3.1-json2",
  "run_id": "036-20260907-r1",
  "json1_sha256": "JSON1.1内の値を転記",
  "json1_1_sha256": "JSON1.1全体の正規化SHA256",
  "title": "本文から導く表題",
  "summary": "青Callout用約200字",
  "conclusion": "アリヤー全体のまとめ",
  "verses": [{
    "ref": "Gen.25.19",
    "glosses": [{"token_id": 123, "ja": "文脈に即した逐語訳"}],
    "translation": "私訳",
    "short_commentary": "節固有の簡易な説明",
    "sections": [
      {"heading": "本文と文法", "body": "説明", "sources": [{"label": "著者・文献名・章節／頁", "url": "https://example.org/source"}]},
      {"heading": "デボーショナルな受けとめ", "body": "当該節に根拠を置く受けとめ", "sources": []}
    ]
  }],
  "chunks": [{
    "id": "prosperity-and-expulsion",
    "heading": "26:13–16を深める",
    "refs": ["Gen.26.13", "Gen.26.14", "Gen.26.15", "Gen.26.16"],
    "after_ref": "Gen.26.16",
    "body": "数節を横断する議論・釈義・受容史。節の表示を繰り返さず、このまとまりを読み終えた位置に置く。",
    "sources": [{"label": "著者・文献名・章節／頁", "url": "https://example.org/source"}]
  }],
  "aliyah_research": [{
    "heading": "文学・編集研究",
    "body": "アリヤー全体を横断する研究ノート。本文の一節へ無理に還元しない。",
    "sources": [{"label": "著者・文献名・章節／頁", "url": "https://example.org/source"}]
  }]
}
```

全節・全語をJSON1.1と同順で含める。日本語段落をヘブライ語で始める時は「ヘブライ語の」を補う。出典は実際に確認した資料を使い、対応する`sections`、`chunks`、`aliyah_research`の`sources`へ格納する。引用文・文献・URLを推測しない。ユダヤ教と教父の伝統項目は分離する。節固有情報がない任意項目は省略し、デボーショナルな受けとめを各節末尾に1つ置く。反復・仮文は不合格。

### 研究内容の配置契約

JSON2を作るChatGPTは、調査で得た内容を先に次の三層へ分類してから文章化する。分量ではなく、本文との根拠関係で置き場所を決める。GitHub Actionsはこの分類を評価・創作せず、JSON2の指定位置へJSON1とともにJSON3を構成する。

| 層 | JSON2の置き場 | 置く基準 | Notionでの位置 |
|---|---|---|---|
| 節 | `verses[].sections` | その語・構文・行為・場面を離れると根拠を失う内容 | その節の「詳しい解説」 |
| チャンク | `chunks[]` | 複数節の反復、対比、物語展開、限定的な注解・受容史 | `after_ref`の節の直後。節本文は重複表示しない |
| アリヤー全体 | `aliyah_research[]` | 複数チャンクを横断する文学・編集研究、解釈伝統、受容史 | ページ末尾「このアリヤーをさらに学ぶ」 |

`chunks[].refs`はrequestの連続した対象節だけを順番通り記す。 `after_ref`はその最後の節と一致させ、同一位置に複数のチャンクを置かない。たとえば26:15–19を扱うノートは26:19の後へ置け、15節や17節の表示を二度作らない。チャンクの研究ノートは節表示の後に置く。日々の読者がまず御言葉、私訳、節固有の受けとめに触れられる順序を守るためである。

`aliyah_research`は少なくとも一項目を必須とし、各項目を独立した題目・本文・検証済み出典で作る。見出しは「文学・編集研究」「ユダヤ教解釈伝統」「キリスト教受容史」など内容を表すものとする。ただし、本文との関係を実際に調べた結果薄い伝統を、形式上の穴埋めで置いてはならない。その場合はChatGPTの研究記録で関連が薄い理由を明示し、無理に本文へ挿入しない。

## JSON2研究責任（ChatGPT側の必須工程）

JSON2は媒体生成の前処理ではなく、この日課の研究・牧会的価値を担う中核成果物である。GitHub ActionsはJSONハッシュ、語ID、HTML、音声、Notion媒体の整合だけを担い、研究内容を簡素化したJSON2を後から機械的に救済する役にはさせない。

JSON2をGitHubへ渡す前に、ChatGPTは全節を横断して次を自ら完了・確認する。

- 各節の詳説を、当該節の語、構文、行為、対話、場面転換、あるいは物語上の緊張という具体的根拠から書く。一般論・前節の言換え・資料名だけの列挙は渡さない。
- 当該アリヤーで有意義な論点がある場合、本文研究・現代注解／論文、ラビ・中世ユダヤ注解（ラシー、タルムード、マイモニデス等を含み得る）、教父解釈を**別々に実地確認**する。すべてを各節へ機械的に付加する必要はないが、扱わない伝統を「未調査のため」省略してはならない。
- ユダヤ教解釈はpeshatとミドラシュ的読解を区別し、教父解釈は人物・著作・当該箇所との関係を確認する。資料が当該節を直接扱わない場合は、そのように限定して書く。
- 一つの通読用サイト又は一人の注解者に出典が収束していないかを横断確認する。Sefaria本文ページは本文確認の入口であって、個別のラビ資料を確認した根拠には数えない。
- sections.sourcesには、実際に開いて確認した著者、著作、章節または頁、URLを入れる。推測した書誌・頁・URL、または本文に用いていない飾りの出典を置かない。
- 各節末尾の「デボーショナルな受けとめ」は、当該節固有の語・行為・緊張から導き、学術説明を感傷的な一般論へ短絡させない。
- 逐語訳はJSON1.1のtoken_id順を保ち、文脈に即した日本語を与える。ヘブライ語表層形を逐語訳欄へ転記してはならない。

この自己監査を、画像生成・Notion・音声・メールなどの進捗と交換してはならない。技術的な障害があっても、JSON2の研究工程を短縮する理由にはならない。

## 本文・音声・表示

現在のNeon語テーブルに不足する語間記号・本文注だけは、DB source_commitと同じ固定MorphHB XMLを全対象語と照合した後、追加専用`dtworks.verse_layout_v3`へ格納する。JSON1はその補助表もDBから再取得する。token/lemma/morph不一致時はトランザクション全体をロールバックする。480MB未満の保守的容量ゲートを設ける。既存語・lexeme/reference・/passage・/searchを変更しない。

音声はVer.2の固定PocketTorahと語位置ラベルを使用し、節専用MP3 r1を切り出して0.79306語/秒のr2へ調整する。全節・共有境界・実測duration・音量・速度を検証する。連続音源をNotionへ埋め込まない。r1/r2は保持し、MODEL_AUDIO未実施を聴取済みとしない。

各節は「節見出し→音声→私訳→ヘブライ語HTML→簡易な説明→閉じた詳しい解説toggle」。音声/HTMLのcaptionは空。音声用HTML・空のHTMLブロック・操作説明・技術ステータス・「対話型ヘブライ語」captionを追加しない。HTMLに固定の大きな高さや上下余白を持たせない。ただしNotionの外側iframeの手動サイズはNotion側の制約であり、自動制御できると断言しない。

HTMLはJS/CSS/本文データをすべて内包する。検索のみ既存DTWorks APIを呼び出す。全タナハ・トーラー・前預言者・後預言者・諸書・任意書、lemma/form、Qal、同じ活用を維持する。必要な資料帰属はページ末尾の本文資料欄に配置する。

## 再実行と進行

JSON1/1.1/HTML/JSON3は不一致上書きを拒否する。Notion作成直後にpage_idを保存し、部分失敗は同じJSON3・同じページから再開する。既存同名ページを複製しない。delivery PASSだけでは番号を進めない。画像とGmailまで成功した後、ChatGPTがver3/state/production.jsonを更新する。開始時にVer.2の036進行・既存ページを照合し、035や実験050から再開しない。

## HTML配信方針（2026-09-07更新）
全節をGITHUB_PAGES方式とする。publish_pagesがmainのver3-public/{run_id}/だけへHTMLを追加し、Pages build APIを明示的に起動して公開内容を照合する。公開に失敗した場合はNotion投稿前に停止する。完了済みdelivery PASSのRUNは契約検査のみ行い、既存Notionページを再投稿・変更しない。未完了の旧添付RUNは自動移行せず明示的な照合を要求する。既存050の32:4はユーザー確認済みのPages実験で、他の節の一括移行はこの設定変更では行わない。


## ケティーブ・ケレー（2026-09-07）
ケティーブとケレーがDBに併存する場合は、JSON1・JSON1.1に両方の語ID・本文・分解情報を保持し、HTMLには「ケティーブ」「ケレー」のラベル付きで両方を表示する。朗読用テキスト・音声語数照合・速度計算にはケレーのみを用い、ケティーブを重複して読まない。


【Notionのヘブライ語枠：共通ダミーHTML方式】全節の最終表示はGitHub Pages URL embedとする。新規枠はver3/config/notion-frame.jsonのアップロード済み共通frame-bootstrap.htmlのfile_upload_idを再利用して作成し、同じブロックを各節のPages URLへ更新する。本文HTMLを節ごとにNotionへアップロードしない。共有IDが失効した場合だけ小さなダミーを当該RUNで一度再アップロードする。途中停止した添付枠はダミー内容を照合してPagesへ切り替えてから通常検証を行う。JSON3は最終Pages URLを正本とし、ダミーのまま配信完了としない。
