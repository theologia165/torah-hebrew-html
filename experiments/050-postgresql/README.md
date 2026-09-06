# DTWorks 2 PostgreSQL POC — 050

## Goal

Translate the search behavior already proven in the Notion 050 experiment into a PostgreSQL data model without changing the production Ver.2 pipeline.

This branch does **not** provision Google Cloud, does **not** change `ver2/input/current.json`, and does **not** replace the working GitHub/XML search UI.

## Files

- `schema.sql` — PostgreSQL schema, indexes and stable `dtworks.search_tokens` view.
- `seed_books.sql` — 39-book Tanakh metadata and search groups.
- `query_examples.sql` — SQL equivalents of the current UI searches.
- `import_contract.md` — fixed transformation rules for the next Python importer step.

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

Keeps all slash-delimited morphology segments, including prefixes and suffixes. This avoids losing scholarly detail while the ordinary UI can still query the simpler `tokens` row.

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

The view `dtworks.search_tokens` is intended as the stable boundary used later by FastAPI. The browser should not need to know the physical database table layout.

## Why WLC and KJV references are both stored

MorphHB is WLC-based, and verse numbering is not identical to KJV-style numbering everywhere. For example, the pinned MorphHB `VerseMap.xml` maps WLC `Gen.32.4` to KJV `Gen.32.3`. DTWorks therefore stores both explicitly rather than silently changing references.

## Next implementation step

Write `import_morphhb.py` so that a clean PostgreSQL database can be reconstructed automatically from the pinned MorphHB commit. First validate the importer on Genesis only, then on all 39 books. After that, connect a small FastAPI endpoint and switch only the 050 experiment from XML search to SQL search for an A/B comparison.
