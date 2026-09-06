-- DTWorks 2 migration 001
-- Add a reference-system-aware layer above the existing WLC/MorphHB corpus.
-- Safe/idempotent: existing dtworks.* corpus tables and token data are preserved.

BEGIN;

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

INSERT INTO core.reference_systems (code, label, description)
VALUES
    ('WLC', 'Westminster Leningrad Codex versification', 'Reference system used by the MorphHB WLC source.'),
    ('KJV', 'KJV-style versification', 'KJV-style chapter/verse numbering mapped by MorphHB VerseMap.xml.')
ON CONFLICT (code) DO UPDATE SET
    label = EXCLUDED.label,
    description = EXCLUDED.description;

INSERT INTO core.corpus_sources
    (code, label, language_code, reference_system_id, source_version, source_uri, license, metadata)
SELECT
    'morphhb-wlc',
    'Open Scriptures Hebrew Bible / MorphHB (WLC)',
    'he',
    rs.id,
    '3d15126fb1ef74867fc1434be1942e837932691f',
    'https://github.com/openscriptures/morphhb',
    'CC BY 4.0',
    jsonb_build_object('derived_table_schema', 'dtworks')
FROM core.reference_systems rs
WHERE rs.code = 'WLC'
ON CONFLICT (code) DO UPDATE SET
    label = EXCLUDED.label,
    language_code = EXCLUDED.language_code,
    reference_system_id = EXCLUDED.reference_system_id,
    source_version = EXCLUDED.source_version,
    source_uri = EXCLUDED.source_uri,
    license = EXCLUDED.license,
    metadata = EXCLUDED.metadata;

-- Project every currently imported MorphHB verse into the generic reference layer.
INSERT INTO core.reference_passages
    (reference_system_id, osis_ref, book_osis, chapter, verse)
SELECT DISTINCT
    rs.id,
    v.osis_wlc,
    b.osis_code,
    v.chapter_wlc,
    v.verse_wlc
FROM dtworks.verses v
JOIN dtworks.books b ON b.id = v.book_id
JOIN core.reference_systems rs ON rs.code = 'WLC'
ON CONFLICT (reference_system_id, osis_ref) DO UPDATE SET
    book_osis = EXCLUDED.book_osis,
    chapter = EXCLUDED.chapter,
    verse = EXCLUDED.verse;

-- MorphHB VerseMap.xml records exceptions. If no KJV exception exists,
-- the KJV-style reference is treated as identical to the WLC reference.
INSERT INTO core.reference_passages
    (reference_system_id, osis_ref, book_osis, chapter, verse)
SELECT DISTINCT
    rs.id,
    COALESCE(v.osis_kjv, v.osis_wlc),
    split_part(COALESCE(v.osis_kjv, v.osis_wlc), '.', 1),
    split_part(COALESCE(v.osis_kjv, v.osis_wlc), '.', 2)::INTEGER,
    split_part(COALESCE(v.osis_kjv, v.osis_wlc), '.', 3)::INTEGER
FROM dtworks.verses v
JOIN core.reference_systems rs ON rs.code = 'KJV'
ON CONFLICT (reference_system_id, osis_ref) DO UPDATE SET
    book_osis = EXCLUDED.book_osis,
    chapter = EXCLUDED.chapter,
    verse = EXCLUDED.verse;

INSERT INTO core.source_passages
    (corpus_source_id, source_key, reference_passage_id, source_version, metadata)
SELECT
    cs.id,
    v.osis_wlc,
    rp.id,
    sv.source_commit,
    jsonb_build_object('source_name', sv.source_name)
FROM dtworks.verses v
JOIN dtworks.source_versions sv ON sv.id = v.source_version_id
JOIN core.corpus_sources cs ON cs.code = 'morphhb-wlc'
JOIN core.reference_systems rs ON rs.code = 'WLC' AND rs.id = cs.reference_system_id
JOIN core.reference_passages rp
  ON rp.reference_system_id = rs.id
 AND rp.osis_ref = v.osis_wlc
ON CONFLICT (corpus_source_id, source_key) DO UPDATE SET
    reference_passage_id = EXCLUDED.reference_passage_id,
    source_version = EXCLUDED.source_version,
    metadata = EXCLUDED.metadata;

INSERT INTO core.passage_mappings
    (from_passage_id, to_passage_id, relation_type, authority, notes)
SELECT
    wlc.id,
    kjv.id,
    CASE
        WHEN COALESCE(v.osis_kjv, v.osis_wlc) = v.osis_wlc THEN 'equivalent'
        ELSE 'renumbered'
    END,
    'Open Scriptures Hebrew Bible / MorphHB VerseMap.xml',
    CASE
        WHEN v.osis_kjv IS NULL THEN 'No VerseMap exception: numbering treated as identical.'
        ELSE 'Explicit VerseMap correspondence.'
    END
FROM dtworks.verses v
JOIN core.reference_systems wlc_rs ON wlc_rs.code = 'WLC'
JOIN core.reference_systems kjv_rs ON kjv_rs.code = 'KJV'
JOIN core.reference_passages wlc
  ON wlc.reference_system_id = wlc_rs.id
 AND wlc.osis_ref = v.osis_wlc
JOIN core.reference_passages kjv
  ON kjv.reference_system_id = kjv_rs.id
 AND kjv.osis_ref = COALESCE(v.osis_kjv, v.osis_wlc)
ON CONFLICT (from_passage_id, to_passage_id, relation_type) DO UPDATE SET
    authority = EXCLUDED.authority,
    notes = EXCLUDED.notes;

COMMIT;
