# DTWorks 2 long-term database model

## Principle

DTWorks 2 treats PostgreSQL/Neon as a **rebuildable derived database**. GitHub remains the versioned source of truth for schema, migrations, importers, and Nishihara Midrash Lab JSON. External corpora remain pinned to explicit source versions/commits.

The long-term model separates five concerns:

1. **Reference layer (`core`)** — identifies scripture references using an explicit reference/versification system plus an OSIS reference.
2. **Corpus layer** — WLC/MorphHB now; LXX, Peshitta, and other textual corpora later.
3. **Lexeme layer (`core.lexicon_sources`, `core.lexemes`)** — original-script dictionary forms independent of token inflection and independent of Strong numbers.
4. **Content layer (`content`)** — 朝一トーラー and other Nishihara Midrash Lab JSON documents, linked to scripture references without making PostgreSQL the canonical manuscript store.
5. **API layer** — `/passage`, `/search`, later `/parallel` and commentary/content endpoints.

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

`core.reference_passages` and `core.source_passages` project imported MorphHB verses into the generic reference layer. For VerseMap entries, explicit KJV numbering is used. Where MorphHB VerseMap has no exception row, WLC and KJV numbering are treated as identical for the mapping projection.

This means the Genesis benchmark stays valid while the same cross-corpus reference layer covers all 39 Tanakh books.

## Lightweight lexeme layer

A token is an occurrence in a verse; a lexeme is the dictionary identity to which that occurrence belongs. DTWorks 2 therefore does not use a Strong number as the lexeme itself.

```text
dtworks.tokens.primary_lexeme_id
             ↓
core.lexemes
├─ source_lexeme_key
├─ source_entry_id
├─ language_code
├─ lemma_text          # original-script display form
├─ lemma_search        # compact normalized search key
├─ transliteration
├─ strong_number       # compatibility only
└─ pos_code
```

For MorphHB, `dtworks.token_lemmas.lexeme_id` preserves the component-level link and `tokens.primary_lexeme_id` gives the common fast path. The OSHB augmented lexical key is normalized once during import/sync; searches do not repeatedly parse `lemma_raw`.

The Hebrew lexical source is pinned to Open Scriptures Hebrew Lexicon commit `21c9add13bc727d3a951361778e97e3ff7afd1ce` (CC BY 4.0). `AugIndex.xml` maps MorphHB augmented Strong-style keys to `LexicalIndex.xml` entries. The generated lexeme catalog is derived data and can be rebuilt by GitHub Actions.

Only lightweight indexes are created initially: lexeme lookup, token→primary lexeme, and component→lexeme. A larger composite `(lexeme, stem, conjugation)` index should be added only after full-Tanakh query measurements show it is useful.

Future Greek and Syriac corpora can add their own `core.lexicon_sources` rows and lexemes without changing the token/lexeme concept.

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
4. load its language-appropriate lexicon into `core.lexicon_sources` + `core.lexemes`,
5. link tokens to lexemes,
6. load scholarly/curated cross-system correspondences into `core.passage_mappings`.

Language-specific morphology should remain in corpus-specific analysis tables rather than forcing Hebrew, Greek, and Syriac morphology into one oversized universal morphology table.

## API evolution

```text
/passage?source=morphhb-wlc&ref=Gen.32.4       -> source text + tokens + lexeme labels
/search?source=morphhb-wlc&...                  -> corpus search
/parallel?ref=Gen.32.4&base=WLC                 -> aligned WLC/LXX/Peshitta passages
/content?ref=Gen.32.4&system=WLC                -> 朝一トーラー / other content
```

The public API should expose `reference_system`, `osis_ref`, and original-script lemma labels; callers should not depend on physical table IDs or Strong numbers for display.

## Migration order

1. Existing Genesis MorphHB database.
2. `migrations/001_reference_content_layer.sql` — reference/content layer.
3. `/passage` against the reference-aware model.
4. `migrations/002_lexeme_layer.sql` — lightweight lexeme identity layer.
5. Build/import the pinned OSHB lexeme catalog and verify Genesis token→lexeme coverage.
6. Verify `/passage`, `/search`, and the Notion 050 hover/search UI against lexeme IDs.
7. Measure database/index size and query plans.
8. Expand MorphHB to all Tanakh books behind the measured Neon Free capacity gate.
9. Add LXX/Peshitta corpora, language-specific lexicons, and curated mappings.
10. Index 朝一トーラー JSON progressively through `content.documents` + `content.document_passages`.
