# MorphHB → PostgreSQL import contract

This document fixes the transformation rules before an importer is written.
The importer will target the pinned MorphHB commit already used by Ver.2 and the 050 browser experiment:

`3d15126fb1ef74867fc1434be1942e837932691f`

## 1. Source identity

Every import creates or reuses one `dtworks.source_versions` row. The source commit is mandatory so the database can always be reconstructed from GitHub.

## 2. Verse identity and versification

- `osis_wlc`, `chapter_wlc`, `verse_wlc`: taken from MorphHB/WLC OSIS.
- KJV-style reference: taken from `wlc/VerseMap.xml` when a mapping exists.
- Never overwrite WLC numbering with another versification.
- Example confirmed by the pinned VerseMap: `Gen.32.4` (WLC) corresponds to `Gen.32.3` in the KJV mapping.

## 3. Token identity

Each MorphHB `<w>` becomes one `dtworks.tokens` row.

- `token_index`: 1-based order inside the WLC verse.
- `surface`: visible Hebrew text, preserving source spelling/pointing.
- `lemma_raw`: full MorphHB `lemma` attribute.
- `morph_raw`: full MorphHB `morph` attribute.

## 4. Form normalization

The importer, not PostgreSQL, creates stable search forms.

### `form_search`

Purpose: current 050 "same Form" search.

1. Unicode NFD normalization.
2. Remove `/` separators.
3. Remove Hebrew cantillation U+0591–U+05AF.
4. Remove meteg U+05BD.
5. Retain niqqud and consonants.

Thus cantillation placement does not prevent a Form match, while a different vocalization remains a different Form.

### `form_consonantal`

Reserved for a later "ignore vowels" search.

Starting from the NFD token, remove cantillation, meteg and Hebrew vowel/point marks while retaining consonants.

## 5. Lemmas

MorphHB lemma attributes can contain slash-delimited components.

- Preserve the original string in `tokens.lemma_raw`.
- Create one `token_lemmas` row per component.
- Extract the leading numeric Strong/lexeme number where present.
- `primary_strong` is the numeric lexeme associated with the lexical core used by the ordinary UI lemma search.
- `lemma_display` is optional display Hebrew; it is not required for search identity. The stable search key is the numeric lexeme id.

## 6. Morphology

MorphHB morphology strings begin with a language code (`H` Hebrew, `A` Aramaic) and may contain slash-delimited segments for prefixes/core/suffixes.

For every segment create a `morph_segments` row. Identify the lexical/main segment and copy its common search fields onto `tokens`.

For Hebrew verbs MorphHB defines, among others:

- stem `q` = Qal
- stem `N` = Niphal
- stem `p` = Piel
- stem `P` = Pual
- stem `h` = Hiphil
- stem `H` = Hophal
- stem `t` = Hithpael

Conjugation/type codes include:

- `p` = perfect (qatal)
- `q` = sequential perfect (weqatal)
- `i` = imperfect (yiqtol)
- `w` = sequential imperfect (wayyiqtol)
- `h` = cohortative
- `j` = jussive
- `v` = imperative
- `r` = active participle
- `s` = passive participle
- `a` = infinitive absolute
- `c` = infinitive construct

Person/gender/number/state codes are preserved independently.

## 7. Import must be reproducible

A clean database must be rebuildable from:

1. this repository's SQL schema,
2. the pinned MorphHB commit,
3. the future importer script,
4. `VerseMap.xml` for alternate versification.

The live PostgreSQL instance is therefore a derived/search asset, not the canonical source of the biblical data.
