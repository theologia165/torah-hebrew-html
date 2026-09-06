# DTWorks 2 long-term database model

## Principle

DTWorks 2 treats PostgreSQL/Neon as a **rebuildable derived database**. GitHub remains the versioned source of truth for schema, migrations, importers, and Nishihara Midrash Lab JSON. External corpora remain pinned to explicit source versions/commits.

The long-term model separates four concerns:

1. **Reference layer (`core`)** — identifies scripture references using an explicit reference/versification system plus an OSIS reference.
2. **Corpus layer** — WLC/MorphHB now; LXX, Peshitta, and other textual corpora later.
3. **Content layer (`content`)** — 朝一トーラー and other Nishihara Midrash Lab JSON documents, linked to scripture references without making PostgreSQL the canonical manuscript store.
4. **API layer** — `/passage`, `/search`, later `/parallel` and commentary/content endpoints.

## No invented universal verse number

DTWorks 2 does **not** invent a universal `GEN-032-004` identifier and does not assume that `Gen.32.4` means the same atomic textual unit in every tradition.

A reference is identified by the pair:

```text
reference_system + OSIS reference

WLC + Gen.32.4
KJV + Gen.32.3
LXX + Gen.32.4
PESHITTA + Gen.32.4
```

`core.reference_passages.id` is only an internal database surrogate key. The portable identity is the unique pair `(reference_system_id, osis_ref)`.

Different systems are connected through `core.passage_mappings`. The mapping table permits equivalence, renumbering, overlap, containment, and approximate correspondence, so it is not restricted to one-to-one verse alignment.

## Current MorphHB compatibility

The existing `dtworks.books`, `dtworks.verses`, `dtworks.tokens`, `dtworks.token_lemmas`, and `dtworks.morph_segments` tables remain the WLC/MorphHB corpus module. They are not discarded.

`core.sync_morphhb_references()` projects every currently imported MorphHB verse into the generic reference layer. For VerseMap entries, explicit KJV numbering is used. Where MorphHB VerseMap has no exception row, WLC and KJV numbering are treated as identical for the mapping projection.

This means the present Genesis database stays valid while gaining the long-term cross-corpus reference layer.

## 朝一トーラー JSON contract

Future 朝一トーラー JSON should carry an explicit portable reference, for example:

```json
{
  "schema_version": 3,
  "reference": {
    "system": "WLC",
    "osis": "Gen.32.4"
  },
  "translation": "...",
  "interlinear": [],
  "commentary": {},
  "devotional": "..."
}
```

The JSON file remains canonical in GitHub. When indexed into PostgreSQL, `content.documents` records the document/version/path and `content.document_passages` links it to `core.reference_passages`.

Do not make a Neon row ID the only reference stored in JSON. Internal IDs may be cached, but `system + osis` must remain present so JSON can be re-imported into a fresh database.

## Future corpora

Add one row to `core.reference_systems` for each versification/reference system and one row to `core.corpus_sources` for each textual corpus/version. A future LXX or Peshitta importer should:

1. import its own text/token/morphology tables,
2. create/update `core.reference_passages` for its reference system,
3. create `core.source_passages`,
4. load scholarly/curated cross-system correspondences into `core.passage_mappings`.

Language-specific morphology should remain in corpus-specific analysis tables rather than forcing Hebrew, Greek, and Syriac morphology into one oversized universal morphology table.

## Planned API evolution

```text
/passsage or /passage?source=wlc&ref=Gen.32.4   -> source text + tokens
/search?source=wlc&...                           -> corpus search
/parallel?ref=Gen.32.4&base=WLC                  -> aligned WLC/LXX/Peshitta passages
/content?ref=Gen.32.4&system=WLC                 -> 朝一トーラー / other content
```

The public API should expose `reference_system` and `osis_ref`; callers should not depend on physical table IDs.

## Migration order

1. Existing Genesis MorphHB database (already built).
2. Apply `migrations/001_reference_content_layer.sql`.
3. Verify reference/source/mapping counts and Gen.32.4 -> KJV Gen.32.3.
4. Add `/passage` against this reference-aware model.
5. Expand MorphHB to all Tanakh books.
6. Add LXX/Peshitta importers and curated mappings.
7. Index 朝一トーラー JSON progressively through `content.documents` + `content.document_passages`.
