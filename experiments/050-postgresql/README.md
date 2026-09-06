# DTWorks 2 PostgreSQL POC — 050

## Status

**Genesis PostgreSQL proof-of-concept: PASS**

The POC now executes the full path below in GitHub Actions without provisioning Google Cloud:

```text
Pinned MorphHB / VerseMap
        ↓
import_morphhb.py
        ↓
PostgreSQL 16 (temporary CI service)
        ↓
dtworks.search_tokens
        ↓
050-style SQL search
```

Latest verified Genesis import:

- 1,533 WLC verses
- 20,629 orthographic tokens
- 28,559 lemma segments
- 32,103 morphology segments
- WLC `Gen.32.4` → KJV `Gen.32.3` confirmed through `VerseMap.xml`
- 050 target confirmed from the pinned source:
  - surface: `וַיִּשְׁלַ֨ח`
  - Strong: `7971`
  - POS: `V`
  - stem: `q` = Qal
  - conjugation: `w` = wayyiqtol
  - raw MorphHB morphology: `HC/Vqw3ms`

The SQL assertion for those conditions returns exactly one matching token in WLC Genesis 32:4.

## Safety boundary

This branch does **not** provision Google Cloud, does **not** change `ver2/input/current.json`, and does **not** replace the working GitHub/XML search UI in Notion 050.

All PostgreSQL work is isolated on branch:

`dtworks-postgresql-poc`

The current production/main branch remains independent.

## Files

- `schema.sql` — PostgreSQL schema, indexes and stable `dtworks.search_tokens` view.
- `seed_books.sql` — 39-book Tanakh metadata and search groups.
- `query_examples.sql` — SQL equivalents of the current 050 UI searches.
- `import_contract.md` — MorphHB → PostgreSQL transformation contract.
- `import_morphhb.py` — reproducible importer; POC currently defaults to Genesis.
- `test_import_morphhb.py` — Unicode, morphology, lemma and synthetic 050 unit tests.
- `requirements.txt` — PostgreSQL Python dependency (`psycopg`).
- `.github/workflows/dtworks-postgresql-poc.yml` — temporary PostgreSQL integration test.

## Data model

```text
source_versions
      |
      v
    verses <----- books
      |
      v
    tokens --------------------+
      |                         |
      +--> token_lemmas         +--> morph_segments
```

### `tokens`

One row per orthographic MorphHB `<w>` token. It contains the fields needed for fast everyday searches:

- surface
- normalized Form
- primary Strong/lemma id
- raw morphology
- main POS
- verb stem
- conjugation/type
- person / gender / number / state

### `token_lemmas`

Keeps every lemma component when MorphHB encodes more than one component.

### `morph_segments`

Keeps all slash-delimited morphology segments, including prefixes and suffixes. This matters for the 050 target itself: MorphHB encodes it as `HC/Vqw3ms`, so the conjunction segment and the lexical verb segment are both preserved while the ordinary search row exposes Qal + wayyiqtol directly.

## Current 050 UI → SQL

| UI action | SQL field(s) |
|---|---|
| same lemma | `primary_strong` |
| same Form | `form_search` |
| Qal | `main_stem_code = 'q'` |
| wayyiqtol | `main_conjugation_code = 'w'` |
| Qal + wayyiqtol | both conditions with `AND` |
| Torah / Prophets / Writings | `tanakh_group` |
| current book / selected books | `book` |

Example corresponding to the most specific 050 preset:

```sql
SELECT *
FROM dtworks.search_tokens
WHERE primary_strong = 7971
  AND main_stem_code = 'q'
  AND main_conjugation_code = 'w'
  AND tanakh_group = 'torah';
```

The view `dtworks.search_tokens` is the stable boundary intended for the later FastAPI service. The browser should not depend on the physical database table layout.

## Reproducibility

The live database is not the canonical biblical source. A clean database can be rebuilt from:

1. this repository's SQL schema,
2. the pinned MorphHB commit,
3. `import_morphhb.py`,
4. `VerseMap.xml`.

The importer deletes and rebuilds one source-version/book slice transactionally, so rerunning the Genesis POC does not duplicate Genesis rows.

## Next implementation step

The database/import layer is now proven for Genesis. The next useful step is **not yet Cloud SQL**. It is to add a small FastAPI search endpoint against PostgreSQL and make a separate 050 SQL-backed experiment call that endpoint. That will allow an A/B comparison:

```text
current 050: Notion → JavaScript → GitHub MorphHB XML

SQL POC:     Notion → JavaScript → FastAPI → PostgreSQL
```

After the API boundary is proven, extend the importer from Genesis to all 39 books and then choose the permanent Google Cloud deployment (`Cloud Run + Cloud SQL`).
