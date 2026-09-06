-- DTWorks 2 long-term database model
-- Portable scripture identity = (reference_system, OSIS reference).
-- Internal BIGINT ids are surrogate keys only.

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS content;

CREATE TABLE IF NOT EXISTS core.reference_systems (
    id                  SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code                TEXT NOT NULL UNIQUE,
    osis_ref_system     TEXT,
    label               TEXT NOT NULL,
    description         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.reference_passages (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reference_system_id SMALLINT NOT NULL REFERENCES core.reference_systems(id) ON DELETE RESTRICT,
    osis_ref            TEXT NOT NULL,
    book_osis           TEXT NOT NULL,
    chapter             INTEGER NOT NULL CHECK (chapter > 0),
    verse               INTEGER NOT NULL CHECK (verse > 0),
    segment             TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (reference_system_id, osis_ref)
);

CREATE INDEX IF NOT EXISTS idx_reference_passages_lookup
    ON core.reference_passages (reference_system_id, book_osis, chapter, verse);

CREATE TABLE IF NOT EXISTS core.passage_mappings (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    from_passage_id     BIGINT NOT NULL REFERENCES core.reference_passages(id) ON DELETE CASCADE,
    to_passage_id       BIGINT NOT NULL REFERENCES core.reference_passages(id) ON DELETE CASCADE,
    relation_type       TEXT NOT NULL CHECK (relation_type IN (
                            'equivalent', 'renumbered', 'overlaps',
                            'contains', 'contained_by', 'approximate'
                        )),
    authority           TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (from_passage_id <> to_passage_id),
    UNIQUE (from_passage_id, to_passage_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_passage_mappings_from ON core.passage_mappings (from_passage_id);
CREATE INDEX IF NOT EXISTS idx_passage_mappings_to   ON core.passage_mappings (to_passage_id);

CREATE OR REPLACE VIEW core.reference_links AS
SELECT from_passage_id AS passage_id,
       to_passage_id AS linked_passage_id,
       relation_type,
       authority,
       notes
FROM core.passage_mappings
UNION ALL
SELECT to_passage_id AS passage_id,
       from_passage_id AS linked_passage_id,
       CASE relation_type
           WHEN 'contains' THEN 'contained_by'
           WHEN 'contained_by' THEN 'contains'
           ELSE relation_type
       END AS relation_type,
       authority,
       notes
FROM core.passage_mappings;

CREATE TABLE IF NOT EXISTS core.corpus_sources (
    id                  SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code                TEXT NOT NULL UNIQUE,
    label               TEXT NOT NULL,
    language_code       TEXT,
    reference_system_id SMALLINT NOT NULL REFERENCES core.reference_systems(id) ON DELETE RESTRICT,
    source_version      TEXT,
    source_uri          TEXT,
    license             TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.source_passages (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    corpus_source_id    SMALLINT NOT NULL REFERENCES core.corpus_sources(id) ON DELETE CASCADE,
    source_key          TEXT NOT NULL,
    reference_passage_id BIGINT NOT NULL REFERENCES core.reference_passages(id) ON DELETE RESTRICT,
    source_version      TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (corpus_source_id, source_key)
);

CREATE INDEX IF NOT EXISTS idx_source_passages_reference
    ON core.source_passages (reference_passage_id);

-- Lexical identity is separate from token morphology and from Strong numbers.
-- A lexicon source supplies source-specific lexical keys and original-script
-- lemma labels. Strong is retained only as an optional compatibility key.
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

CREATE TABLE IF NOT EXISTS content.documents (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_key        TEXT NOT NULL UNIQUE,
    content_type        TEXT NOT NULL,
    schema_version      INTEGER NOT NULL CHECK (schema_version > 0),
    source_json_path    TEXT,
    title               TEXT,
    publication_status  TEXT NOT NULL DEFAULT 'draft' CHECK (publication_status IN ('draft','published','archived')),
    checksum            TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS content.document_passages (
    document_id         BIGINT NOT NULL REFERENCES content.documents(id) ON DELETE CASCADE,
    reference_passage_id BIGINT NOT NULL REFERENCES core.reference_passages(id) ON DELETE RESTRICT,
    role                TEXT NOT NULL DEFAULT 'primary' CHECK (role IN ('primary','context','citation')),
    ordinal             INTEGER NOT NULL DEFAULT 1 CHECK (ordinal > 0),
    PRIMARY KEY (document_id, reference_passage_id, role)
);

CREATE INDEX IF NOT EXISTS idx_document_passages_reference
    ON content.document_passages (reference_passage_id, role);
