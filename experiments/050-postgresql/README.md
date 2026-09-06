# DTWorks 2 PostgreSQL / FastAPI POC — 050

## Status

**Genesis PostgreSQL proof-of-concept: PASS**  
**FastAPI HTTP proof-of-concept: PASS**

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
FastAPI /search
        ↓
HTTP JSON response for the 050 UI
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

The HTTP contract test also confirms:

- `/health` returns PostgreSQL status, 20,629 imported Genesis tokens and the pinned MorphHB commit.
- `/search?strong=7971&stem=q&conjugation=w&books=Gen` returns 15 Genesis matches and includes `Gen.32.4`.
- Form search normalizes cantillation/meteg and still finds `Gen.32.4`.
- morphology-only search (`stem=q&conjugation=w`) works with pagination/limit.
- `/books` returns all 39 Tanakh book metadata rows.
- browser CORS response is present for the Notion experiment.
- a scope-only request with no lexical/form/morphology condition is rejected with HTTP 400.

## Safety boundary

This branch does **not** provision Google Cloud, does **not** change `ver2/input/current.json`, and does **not** replace the working GitHub/XML search UI in Notion 050.

All PostgreSQL/FastAPI work is isolated on branch:

`dtworks-postgresql-poc`

The current production/main branch remains independent.

The GitHub Actions FastAPI process is temporary and disappears when CI finishes. Therefore the current Notion page cannot yet use this SQL API persistently. A permanent host is required for that next step.

## Files

- `schema.sql` — PostgreSQL schema, indexes and stable `dtworks.search_tokens` view.
- `seed_books.sql` — 39-book Tanakh metadata and search groups.
- `query_examples.sql` — SQL equivalents of the current 050 UI searches.
- `import_contract.md` — MorphHB → PostgreSQL transformation contract.
- `import_morphhb.py` — reproducible importer; POC currently defaults to Genesis.
- `test_import_morphhb.py` — Unicode, morphology, lemma and synthetic 050 unit tests.
- `api.py` — FastAPI HTTP service over `dtworks.search_tokens`.
- `verify_api.py` — live HTTP contract verification against PostgreSQL.
- `requirements.txt` — `psycopg`, FastAPI and Uvicorn dependencies.
- `.github/workflows/dtworks-postgresql-poc.yml` — temporary PostgreSQL + FastAPI integration test.

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

## Current 050 UI → SQL → HTTP

| UI action | SQL field(s) | API parameter |
|---|---|---|
| same lemma | `primary_strong` | `strong=7971` |
| same Form | `form_search` | `form=...` |
| Qal | `main_stem_code = 'q'` | `stem=q` |
| wayyiqtol | `main_conjugation_code = 'w'` | `conjugation=w` |
| Qal + wayyiqtol | both with `AND` | `stem=q&conjugation=w` |
| Torah / Prophets / Writings | `tanakh_group` | `group=torah` etc. |
| current / selected books | `book` | `books=Gen,Exod` |

Example corresponding to the most specific 050 preset:

```text
GET /search?strong=7971&stem=q&conjugation=w&books=Gen&limit=100
```

The API uses parameter-bound SQL. Browser-provided values are never concatenated into SQL values. The browser therefore depends on the HTTP contract, not on the physical database table layout.

### Main endpoints

- `GET /health` — API/database/source-version health.
- `GET /books` — canonical book metadata and groups.
- `GET /search` — lemma/Form/morphology/scope search with `limit` and `offset`.
- `/docs` — FastAPI-generated interactive API documentation when the service is running.

Search results include both WLC and KJV references plus surface form, normalized Form, Strong, raw MorphHB code and decomposed morphology fields.

## Reproducibility

The live database is not the canonical biblical source. A clean database can be rebuilt from:

1. this repository's SQL schema,
2. the pinned MorphHB commit,
3. `import_morphhb.py`,
4. `VerseMap.xml`.

The importer deletes and rebuilds one source-version/book slice transactionally, so rerunning the Genesis POC does not duplicate Genesis rows.

## Next implementation step

The **database/import/API boundary is now proven for Genesis**.

The next useful step is to give the FastAPI process a permanent HTTPS URL and point a separate 050 experiment at it. The intended A/B comparison is:

```text
current 050: Notion → JavaScript → GitHub MorphHB XML

SQL 050:     Notion → JavaScript → HTTPS FastAPI → PostgreSQL
```

At that point a permanent backend is needed. The planned Google Cloud deployment is:

```text
Cloud Run  → FastAPI
Cloud SQL  → PostgreSQL
```

For a cost-controlled first deployment, load Genesis only, connect the 050 experiment, confirm browser behavior and latency, then expand the importer to all 39 books.
