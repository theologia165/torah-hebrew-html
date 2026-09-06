# MorphHB全39書のNeon Free容量評価

評価日: 2026-09-06
対象: Neon project `DTWorks 2 Hebrew Search` / database `dtworks` / branch `main`

## 実測基準

- Neon Free logical-size limit: 536,870,912 bytes (512 MiB)
- 現在のbranch logical size: 65,699,840 bytes
- `pg_database_size(dtworks)`: 42,311,680 bytes (40.35 MiB)
- 現在のGenesis: 1,533節 / 20,629 tokens / 28,559 lemma components / 32,103 morphology segments

## 固定MorphHB commitの全書実数

- 39書
- 23,213節
- 306,785 tokens
- 423,030 lemma components
- 471,674 morphology segments
- 9,263 observed lexeme keys

## 事前推定

Genesisの各テーブル・索引の`pg_total_relation_size`を行数で割り、全書の実数へ外挿した。

- 通常推定: 363,766,731 bytes (346.91 MiB)
- 保守推定: 444,834,957 bytes (424.23 MiB)
- 保守推定後の残量: 92,035,955 bytes (87.77 MiB)

保守推定は、追加分を1.20倍し、さらに16 MiBを固定予備として加える。GitHub Actionsの容量ゲートは、保守推定が512 MiB以下で、かつ64 MiB以上の残量がある場合だけ本番投入を許可する。今回の事前評価はこの条件を満たす。

## 自動停止条件

`.github/workflows/import-morphhb-tanakh-neon.yml`は本番書込み前に同じ計算をライブDBへ再実行する。次のいずれかならschema適用・lexeme投入・本文投入を開始しない。

- 保守推定が512 MiBを超える
- 保守推定後の残量が64 MiB未満
- Genesis基準テーブルの実測行数が取得できない
- 固定sourceの39書、XML、lexeme manifestの検証が失敗する

本番投入後にも同じ容量評価と全件検証を実行し、非秘密のJSON reportをGitHub Actions artifactとして保存する。
