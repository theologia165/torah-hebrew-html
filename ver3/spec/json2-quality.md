# Work stage｜JSON2 quality gate

JSON2は朝一トーラーの知的・牧会的価値を担う中核成果物である。画像、音声、Notion、メールの進捗を理由に簡素化しない。対象RUNの`json1.1.json`以外の過去成果物を研究入力にしない。

## 入力確認

最初に実データで各tokenの`token_id`、`token_index`、`surface`、`lemma_raw`、`morph_raw`、`lexeme`、`morph_segments`の存在・型を確認する。Strong Numberを使う場合は実際の`token.lexeme.strong_number`を確認し、別のキーや`H7200`形式を仮定しない。本文、lemma、形態、語IDをWorkが生成・補完・上書きしてはならない。

## 逐語訳

全tokenをtoken_id順に扱い、同一tokenのsurface、lemma、morph_segmentsと節全体の構文を合わせて一語ずつ日本語化する。接続詞、前置詞、定冠詞、接尾辞人称、動詞語幹・活用を表層形の意味へ反映する。辞書対応表は補助に限り、JSON1.1より優先しない。空欄、ヘブライ語転記、「機能語」「未詳」「文脈をつなぐ語」等のfallbackで穴埋めしない。一語でも確定できなければコミットせず、ref、token_id、surface、lemma、morph、未解決理由を記録する。

## 三層研究

- `verses[].sections`：当該節の語・構文・行為・場面を離れると根拠を失う内容。末尾に節固有の「デボーショナルな受けとめ」を一件置き、その`sources`は必ず空配列にする。
- `chunks[]`：連続する複数節の反復、対比、物語展開、限定的な注解・受容史。`refs`を本文順にし、最終節と`after_ref`を一致させる。
- `aliyah_research[]`：複数チャンクを横断する文学・編集研究、ユダヤ教解釈伝統、キリスト教受容史等。関連が薄い伝統を穴埋めせず、扱わない理由を研究記録に残す。

必要な箇所ではラビ／中世ユダヤ注解、教父、現代研究を実際に調べ、peshat、ミドラシュ、教父を混同しない。出典をAlterとSefariaだけへ収束させない。各学術項目の`sources`には実際に確認した著者、著作、章節または頁、URLを置き、推測しない。

## コミット前の意味監査

次をすべてWork自身が確認する。

1. 全節・全tokenの`token_id / surface / lemma / morphology / glosses[].ja`対応が正しい。
2. lookup miss、仮文、空欄、表層ヘブライ語の代入、不自然な一律訳、異常な同文反復が0件である。
3. 私訳が逐語訳とヘブライ語構文に整合する。
4. 全節の詳説が、その節固有の語・構文・行為・緊張から始まる。
5. アリヤー全体で複数の異なる学術的論点を扱う。
6. 出典は実在確認され、記述内容を実際に支える。
7. デボーショナルな受けとめは節ごとに異なり、`sources: []`である。
8. 日本語段落をヘブライ語から始めず「ヘブライ語の…」等で始め、LTRを保つ。「静かに〜」を使わない。
9. JSON1 hashを転記し、JSON1.1 hashを指定の正規化方式で正確に計算する。

全項目合格時だけ`WORK_JSON2_QUALITY=PASS`として`json2.json`をコミットする。構造validatorのPASSは意味監査の代替ではない。未解決が一件でもあれば`JSON2_QUALITY_BLOCKED`としてActionsへ渡さない。

