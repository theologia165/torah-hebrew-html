# DTWorks 2 Cloudflare Workers + Neon PostgreSQL — 050

## Goal

Provide a zero-fixed-cost-friendly public API for the DTWorks 2 biblical corpus while keeping the database reproducible from GitHub.

```text
Notion / later WordPress / independent research UI
        ↓
JavaScript
        ↓
Cloudflare Worker
        ↓
Neon PostgreSQL
        ↓
core.* reference layer + dtworks.* MorphHB corpus
```

The PostgreSQL database is a derived index. GitHub source, migrations, importers, and pinned upstream corpora are the reproducible source of truth.

## Current status

Live Worker:

`https://dtworks-hebrew-search.nishiharat.workers.dev`

The complete MorphHB Tanakh corpus is loaded:

- 39 books
- 23,213 WLC verses
- 306,785 MorphHB word tokens
- pinned MorphHB commit `3d15126fb1ef74867fc1434be1942e837932691f`
- WLC/KJV reference mappings loaded into the common `core.*` reference layer

The existing search baseline remains Strong 7971 + Qal + wayyiqtol in Genesis = 15 results.

## API contract

### `GET /health`

Returns runtime/database health, imported token count, and MorphHB source commit.

### `GET /books`

Returns biblical book metadata.

### `GET /search`

Current MorphHB search parameters:

- `strong=7971`
- `form=וַיִּשְׁלַח`
- `stem=q`
- `conjugation=w`
- `group=torah|former|latter|writings`
- `books=Gen,Exod`
- `limit=1..500`
- `offset=0..1000000`
- `versification=wlc|kjv`

At least one lexical/morphological condition is required.

Example:

```text
GET /search?strong=7971&stem=q&conjugation=w&books=Gen&limit=100
```

### `GET /passage`

`/passage` is source-aware and supports all 39 MorphHB/WLC books.

Single verse:

```text
GET /passage?source=morphhb-wlc&ref=Gen.32.4
```

Verse range:

```text
GET /passage?source=morphhb-wlc&start=Gen.32.4&end=Gen.32.8
```

`source` defaults to `morphhb-wlc` at this stage.

The response includes:

- corpus source metadata
- reference system (`WLC` currently)
- OSIS verse reference
- linked reference mappings, including KJV-style numbering where applicable
- ordered word tokens
- Strong / lemma / morphology fields already used by `/search`
- a convenience `text` assembled from the ordered MorphHB word tokens

The response deliberately identifies that convenience text as `joined-from-MorphHB-word-tokens`; token data remains authoritative for this stage.

Example conceptual response:

```json
{
  "api": "passage",
  "version": "1",
  "source": {
    "code": "morphhb-wlc",
    "reference_system": "WLC"
  },
  "requested": {
    "start": "Gen.32.4",
    "end": "Gen.32.4"
  },
  "passage_count": 1,
  "verses": [
    {
      "reference": {
        "system": "WLC",
        "osis": "Gen.32.4"
      },
      "mappings": [
        {"system": "KJV", "osis": "Gen.32.3", "relation": "renumbered"}
      ],
      "tokens": []
    }
  ]
}
```

## Long-term passage contract

The URL and response shape are designed so later corpora can use the same endpoint rather than receiving corpus-specific endpoints:

```text
/passage?source=morphhb-wlc&ref=Gen.1.1
/passage?source=lxx&ref=Gen.1.1
/passage?source=peshitta&ref=Gen.1.1
```

Future source codes are not accepted until their corpora are actually loaded.

The Worker resolves the source through `core.corpus_sources` and `core.source_passages`, so the public API is not conceptually tied to WLC verse IDs. The present final join to `dtworks.*` is isolated in `src/passage.ts`; a Greek or Syriac corpus may use different physical token/analysis tables while preserving the same API contract.

Reference-system differences are represented through `core.reference_passages` and `core.passage_mappings`, not by silently renumbering the source text.

## Relation to Asaichi Torah JSON

Future Asaichi Torah JSON should identify passages through a stable external reference pair, for example:

```json
{
  "reference": {
    "system": "WLC",
    "osis": "Gen.32.4"
  }
}
```

The `content.documents` and `content.document_passages` tables provide the database-side bridge from those GitHub JSON documents to the common passage reference layer. The JSON remains the canonical authored content; PostgreSQL provides linking, retrieval, and search indexes.

## SQL safety

Search and passage values use numbered PostgreSQL placeholders (`$1`, `$2`, ...). User-supplied values are not concatenated into SQL values.

## Secrets

Never commit the Neon connection URI. Runtime access uses the Cloudflare secret binding `DATABASE_URL`.

## Reproducibility

Long-term database design and migrations live under:

```text
dtworks2/database/
```

The current reference/content-layer migration is:

```text
dtworks2/database/migrations/001_reference_content_layer.sql
```

MorphHB import remains pinned to the recorded upstream Git commit. A lost Neon database must be reconstructible from GitHub + pinned upstream source rather than from a manually maintained database snapshot.
