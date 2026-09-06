-- DTWorks 2 lexeme layer
-- Adds a language-neutral lexical identity layer without changing the canonical
-- MorphHB token source. GitHub/source corpora remain canonical; Neon is derived.

BEGIN;

CREATE TABLE IF NOT EXISTS core.lexicon_sources (
    id              SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code            TEXT NOT NULL UNIQUE,
    label           TEXT NOT NULL,
    source_version  TEXT,
    source_uri      TEXT,
    license         TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.lexemes (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lexicon_source_id   SMALLINT NOT NULL REFERENCES core.lexicon_sources(id) ON DELETE RESTRICT,
    source_lexeme_key   TEXT NOT NULL,
    source_entry_id     TEXT,
    language_code       TEXT NOT NULL,
    lemma_text          TEXT,
    lemma_search        TEXT,
    transliteration     TEXT,
    strong_number       INTEGER,
    pos_code            TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (lexicon_source_id, source_lexeme_key)
);

CREATE INDEX IF NOT EXISTS idx_lexemes_strong
    ON core.lexemes (strong_number)
    WHERE strong_number IS NOT NULL;

INSERT INTO core.lexicon_sources
    (code, label, source_version, source_uri, license, metadata)
VALUES
    ('oshb-hebrew-lexicon',
     'Open Scriptures Hebrew Lexicon',
     '21c9add13bc727d3a951361778e97e3ff7afd1ce',
     'https://github.com/openscriptures/HebrewLexicon',
     'CC BY 4.0',
     jsonb_build_object(
         'augmented_index', 'AugIndex.xml',
         'lexical_index', 'LexicalIndex.xml'
     ))
ON CONFLICT (code) DO UPDATE SET
    label = EXCLUDED.label,
    source_version = EXCLUDED.source_version,
    source_uri = EXCLUDED.source_uri,
    license = EXCLUDED.license,
    metadata = EXCLUDED.metadata;

ALTER TABLE dtworks.token_lemmas
    ADD COLUMN IF NOT EXISTS lexeme_id BIGINT REFERENCES core.lexemes(id) ON DELETE RESTRICT;

ALTER TABLE dtworks.tokens
    ADD COLUMN IF NOT EXISTS primary_lexeme_id BIGINT REFERENCES core.lexemes(id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS idx_token_lemmas_lexeme
    ON dtworks.token_lemmas (lexeme_id, token_id)
    WHERE lexeme_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_tokens_primary_lexeme
    ON dtworks.tokens (primary_lexeme_id)
    WHERE primary_lexeme_id IS NOT NULL;

-- Create lightweight placeholder lexemes from the MorphHB augmented-Strong
-- components already present in the corpus. The deterministic OSHB lexicon
-- catalog build fills lemma_text/source_entry_id afterward.
--
-- MorphHB writes augmented keys such as "1121 a" while AugIndex.xml uses
-- "1121a". A trailing '+' marks the first token of a compound proper name;
-- lexical identity is the same base augmented key, so it is removed here.
WITH src AS (
    SELECT id FROM core.lexicon_sources WHERE code = 'oshb-hebrew-lexicon'
), observed AS (
    SELECT
        regexp_replace(
            regexp_replace(btrim(tl.raw_component), '[[:space:]]+', '', 'g'),
            '[+]$', ''
        ) AS source_lexeme_key,
        min(tl.strong_number) AS strong_number,
        CASE WHEN bool_or(t.language_code = 'A') THEN 'arc' ELSE 'he' END AS language_code
    FROM dtworks.token_lemmas tl
    JOIN dtworks.tokens t ON t.id = tl.token_id
    WHERE tl.strong_number IS NOT NULL
    GROUP BY 1
)
INSERT INTO core.lexemes
    (lexicon_source_id, source_lexeme_key, language_code, strong_number)
SELECT src.id, observed.source_lexeme_key, observed.language_code, observed.strong_number
FROM src CROSS JOIN observed
WHERE observed.source_lexeme_key <> ''
ON CONFLICT (lexicon_source_id, source_lexeme_key) DO UPDATE SET
    language_code = EXCLUDED.language_code,
    strong_number = EXCLUDED.strong_number,
    updated_at = now();

-- Link every numeric MorphHB lemma component to the normalized lexeme key.
UPDATE dtworks.token_lemmas tl
SET lexeme_id = lx.id
FROM core.lexemes lx
JOIN core.lexicon_sources src ON src.id = lx.lexicon_source_id
WHERE src.code = 'oshb-hebrew-lexicon'
  AND tl.strong_number IS NOT NULL
  AND lx.source_lexeme_key = regexp_replace(
        regexp_replace(btrim(tl.raw_component), '[[:space:]]+', '', 'g'),
        '[+]$', ''
      )
  AND tl.lexeme_id IS DISTINCT FROM lx.id;

-- The token carries a direct pointer for the common one-lexeme search path.
UPDATE dtworks.tokens t
SET primary_lexeme_id = tl.lexeme_id
FROM dtworks.token_lemmas tl
WHERE tl.token_id = t.id
  AND tl.is_primary
  AND tl.lexeme_id IS NOT NULL
  AND t.primary_lexeme_id IS DISTINCT FROM tl.lexeme_id;

-- Keep the existing stable search view contract and append lexical fields.
CREATE OR REPLACE VIEW dtworks.search_tokens AS
SELECT
    t.id AS token_id,
    b.osis_code AS book,
    b.english_name,
    b.japanese_name,
    b.tanakh_group,
    b.canonical_order,
    v.chapter_wlc,
    v.verse_wlc,
    v.osis_wlc,
    v.chapter_kjv,
    v.verse_kjv,
    v.osis_kjv,
    t.token_index,
    t.surface,
    t.form_search,
    t.form_consonantal,
    t.lemma_raw,
    t.primary_strong,
    t.lemma_display,
    t.morph_raw,
    t.language_code,
    t.main_pos_code,
    t.main_stem_code,
    t.main_conjugation_code,
    t.person_code,
    t.gender_code,
    t.number_code,
    t.state_code,
    t.primary_lexeme_id,
    lx.source_lexeme_key AS lexeme_key,
    lx.lemma_text AS lexeme_lemma,
    lx.lemma_search AS lexeme_search,
    lx.transliteration AS lexeme_transliteration,
    lx.pos_code AS lexeme_pos_code,
    lxs.code AS lexicon_source_code
FROM dtworks.tokens t
JOIN dtworks.verses v ON v.id = t.verse_id
JOIN dtworks.books b ON b.id = v.book_id
LEFT JOIN core.lexemes lx ON lx.id = t.primary_lexeme_id
LEFT JOIN core.lexicon_sources lxs ON lxs.id = lx.lexicon_source_id;

COMMIT;
