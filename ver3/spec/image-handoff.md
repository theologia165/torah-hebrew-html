# Work stage｜Image handoff

JSON2確定後、Notion完成を待たずに当日画像を作る。入力は次の三層だけであり、過去ページ・過去画像・失敗画像・過去gen_idを使わない。

1. `ver3/config/image-master.json`
2. `ver3/config/parasha-image/index.json`から日本語パラシャー名を完全一致して取得する当日profile
3. 当該RUNのJSON2から一時的に組むCURRENT RUN IMAGE PACKAGE

1200×630のfresh画像を生成し、NNN、パラシャー名、アリヤー、聖書箇所、本文由来主題句、必要時の補助コピー、誤字、別回混入、本文場面、寸法の10項目を目視確認する。不合格画像は参照・編集せず、最大3回fresh generationする。

PASS画像だけを`cover-upload.json`の短時間PUT URLへJPEGバイナリとして直接送る。画像バイナリをGitHubやWorkの文字コンテキストへ入れない。R2で1200×630 JPEGと取得可能性を確認し、当該RUNの`cover-ready.json`だけをコミットしてActionsを再起動する。画像監査専用JSONや恒久的なCURRENT RUN IMAGE PACKAGEは作成しない。

