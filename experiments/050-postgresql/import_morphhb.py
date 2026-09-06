#!/usr/bin/env python3
"""DTWorks 2 MorphHB -> PostgreSQL importer for all 39 Tanakh books.

The canonical biblical source remains the pinned Open Scriptures Hebrew Bible /
MorphHB Git commit. PostgreSQL is a derived search index that can be rebuilt.

The importer can:

1. download/read the pinned 39 book XML files and VerseMap.xml,
2. normalize Form search values,
3. parse Strong/lemma and MorphHB morphology segments,
4. verify the 050 test token in WLC Genesis 32:4,
5. bulk-load idempotent book slices into the dtworks PostgreSQL schema,
6. link token occurrences to the existing core lexeme layer, and
7. verify every imported book before committing the next one.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import re
import sys
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Optional

MORPHHB_COMMIT = "3d15126fb1ef74867fc1434be1942e837932691f"
SOURCE_NAME = "Open Scriptures Hebrew Bible / MorphHB"
SOURCE_LICENSE = "CC BY 4.0"
RAW_BASE = f"https://raw.githubusercontent.com/openscriptures/morphhb/{MORPHHB_COMMIT}/wlc"
DEFAULT_BOOK = "Gen"
BOOK_CODES = (
    "Gen", "Exod", "Lev", "Num", "Deut", "Josh", "Judg", "1Sam", "2Sam",
    "1Kgs", "2Kgs", "Isa", "Jer", "Ezek", "Hos", "Joel", "Amos", "Obad",
    "Jonah", "Mic", "Nah", "Hab", "Zeph", "Hag", "Zech", "Mal", "Ps",
    "Job", "Prov", "Ruth", "Song", "Eccl", "Lam", "Esth", "Dan", "Ezra",
    "Neh", "1Chr", "2Chr",
)

# MorphHB POS codes that are strongly indicative of the lexical core. Prefixes
# such as conjunctions/prepositions and suffixes should not win over these.
MAIN_POS_PRIORITY = {
    "V": 100,
    "N": 95,
    "A": 90,
    "P": 80,
    "D": 70,
    "T": 50,
    "R": 30,
    "C": 20,
    "S": 10,
}

FINITE_VERB_TYPES = set("pqiwhjv")
PARTICIPLE_TYPES = set("rs")

HEBREW_CANTILLATION = re.compile(r"[\u0591-\u05AF]")
HEBREW_METEG = re.compile(r"\u05BD")
# Niqqud/points removed for consonantal search. Maqaf and punctuation are not
# included because they are not combining vowel/point marks.
HEBREW_POINTS = re.compile(r"[\u05B0-\u05BD\u05BF\u05C1-\u05C2\u05C4-\u05C5\u05C7]")
LEADING_STRONG = re.compile(r"^(\d+)")
SIMPLE_OSIS = re.compile(r"^([^.]+)\.(\d+)\.(\d+)$")
OSIS_SEGMENT = re.compile(r"^([^.]+\.\d+\.\d+)(?:![A-Za-z0-9]+)?$")


@dataclasses.dataclass(frozen=True)
class MorphSegment:
    segment_index: int
    is_main: bool
    morph_code: str
    language_code: str
    pos_code: Optional[str] = None
    subtype_code: Optional[str] = None
    verb_stem_code: Optional[str] = None
    verb_conjugation_code: Optional[str] = None
    person_code: Optional[str] = None
    gender_code: Optional[str] = None
    number_code: Optional[str] = None
    state_code: Optional[str] = None


@dataclasses.dataclass(frozen=True)
class LemmaComponent:
    lemma_index: int
    raw_component: str
    strong_number: Optional[int]
    is_primary: bool


@dataclasses.dataclass(frozen=True)
class TokenRecord:
    token_index: int
    surface: str
    form_search: str
    form_consonantal: str
    lemma_raw: str
    primary_strong: Optional[int]
    lemma_display: Optional[str]
    morph_raw: str
    language_code: str
    main_pos_code: Optional[str]
    main_stem_code: Optional[str]
    main_conjugation_code: Optional[str]
    person_code: Optional[str]
    gender_code: Optional[str]
    number_code: Optional[str]
    state_code: Optional[str]
    lemmas: tuple[LemmaComponent, ...]
    morph_segments: tuple[MorphSegment, ...]


@dataclasses.dataclass(frozen=True)
class VerseRecord:
    book: str
    chapter_wlc: int
    verse_wlc: int
    osis_wlc: str
    chapter_kjv: Optional[int]
    verse_kjv: Optional[int]
    osis_kjv: Optional[str]
    tokens: tuple[TokenRecord, ...]


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_url(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Nishihara-Midrash-Lab-DTWorks2/0.1"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def source_bytes(source_dir: Optional[Path], filename: str) -> bytes:
    if source_dir:
        path = source_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"source file not found: {path}")
        return path.read_bytes()
    return read_url(f"{RAW_BASE}/{filename}")


def strip_slashes(value: str) -> str:
    return value.replace("/", "")


def normalize_form(value: str) -> str:
    """Same-Form key: keep niqqud; ignore cantillation and meteg."""
    value = unicodedata.normalize("NFD", strip_slashes(value))
    value = HEBREW_CANTILLATION.sub("", value)
    value = HEBREW_METEG.sub("", value)
    return value.replace("\u200e", "").replace("\u200f", "")


def normalize_consonantal(value: str) -> str:
    """Consonantal key reserved for a future 'ignore vowels' search."""
    value = unicodedata.normalize("NFD", strip_slashes(value))
    value = HEBREW_CANTILLATION.sub("", value)
    value = HEBREW_POINTS.sub("", value)
    return value.replace("\u200e", "").replace("\u200f", "")


def extract_strong(component: str) -> Optional[int]:
    match = LEADING_STRONG.match(component.strip())
    return int(match.group(1)) if match else None


def normalize_lexeme_key(component: str) -> Optional[str]:
    value = re.sub(r"\s+", "", component.strip())
    if value.endswith("+"):
        value = value[:-1]
    return value if LEADING_STRONG.match(value) else None


def _parse_segment_fields(raw_segment: str, inherited_language: str) -> dict:
    """Parse one slash-delimited MorphHB morphology segment.

    MorphHB prefixes one language code (H/A) to the parsing string. We also
    tolerate a language prefix repeated on a later segment.
    """
    code = raw_segment.strip()
    language = inherited_language
    if code[:1] in {"H", "A"}:
        language = code[0]
        code = code[1:]

    fields = {
        "language_code": language,
        "pos_code": None,
        "subtype_code": None,
        "verb_stem_code": None,
        "verb_conjugation_code": None,
        "person_code": None,
        "gender_code": None,
        "number_code": None,
        "state_code": None,
    }
    if not code:
        return fields

    pos = code[0]
    fields["pos_code"] = pos

    if pos == "V":
        fields["verb_stem_code"] = code[1] if len(code) > 1 else None
        conjugation = code[2] if len(code) > 2 else None
        fields["verb_conjugation_code"] = conjugation
        rest = code[3:]
        if conjugation in FINITE_VERB_TYPES:
            fields["person_code"] = rest[0] if len(rest) > 0 else None
            fields["gender_code"] = rest[1] if len(rest) > 1 else None
            fields["number_code"] = rest[2] if len(rest) > 2 else None
            fields["state_code"] = rest[3] if len(rest) > 3 else None
        elif conjugation in PARTICIPLE_TYPES:
            fields["gender_code"] = rest[0] if len(rest) > 0 else None
            fields["number_code"] = rest[1] if len(rest) > 1 else None
            fields["state_code"] = rest[2] if len(rest) > 2 else None
        return fields

    if pos in {"N", "A"}:
        fields["subtype_code"] = code[1] if len(code) > 1 else None
        fields["gender_code"] = code[2] if len(code) > 2 else None
        fields["number_code"] = code[3] if len(code) > 3 else None
        fields["state_code"] = code[4] if len(code) > 4 else None
    elif pos == "P":
        fields["subtype_code"] = code[1] if len(code) > 1 else None
        fields["person_code"] = code[2] if len(code) > 2 else None
        fields["gender_code"] = code[3] if len(code) > 3 else None
        fields["number_code"] = code[4] if len(code) > 4 else None
    elif pos == "S":
        fields["subtype_code"] = code[1] if len(code) > 1 else None
        fields["person_code"] = code[2] if len(code) > 2 else None
        fields["gender_code"] = code[3] if len(code) > 3 else None
        fields["number_code"] = code[4] if len(code) > 4 else None
    elif pos in {"R", "T"}:
        fields["subtype_code"] = code[1] if len(code) > 1 else None

    return fields


def parse_morphology(morph_raw: str) -> tuple[tuple[MorphSegment, ...], Optional[MorphSegment]]:
    raw_parts = [part for part in morph_raw.split("/") if part != ""]
    if not raw_parts:
        return tuple(), None

    first = raw_parts[0].strip()
    language = first[0] if first[:1] in {"H", "A"} else "H"
    parsed: list[dict] = []
    for raw in raw_parts:
        fields = _parse_segment_fields(raw, language)
        language = fields["language_code"]
        parsed.append({"raw": raw, **fields})

    def priority(item: tuple[int, dict]) -> tuple[int, int]:
        index, fields = item
        # Prefer lexical POS; for equal priority prefer a later segment because
        # prefixes normally precede the lexical core.
        return MAIN_POS_PRIORITY.get(fields["pos_code"], 0), index

    main_zero_index = max(enumerate(parsed), key=priority)[0]
    segments: list[MorphSegment] = []
    for i, fields in enumerate(parsed, start=1):
        segments.append(
            MorphSegment(
                segment_index=i,
                is_main=(i - 1 == main_zero_index),
                morph_code=fields["raw"],
                language_code=fields["language_code"],
                pos_code=fields["pos_code"],
                subtype_code=fields["subtype_code"],
                verb_stem_code=fields["verb_stem_code"],
                verb_conjugation_code=fields["verb_conjugation_code"],
                person_code=fields["person_code"],
                gender_code=fields["gender_code"],
                number_code=fields["number_code"],
                state_code=fields["state_code"],
            )
        )
    main = segments[main_zero_index]
    return tuple(segments), main


def parse_lemmas(lemma_raw: str, main_segment_index: Optional[int]) -> tuple[tuple[LemmaComponent, ...], Optional[int]]:
    parts = lemma_raw.split("/") if lemma_raw else []
    strongs = [extract_strong(part) for part in parts]

    primary_index: Optional[int] = None
    if main_segment_index and main_segment_index <= len(parts):
        candidate = strongs[main_segment_index - 1]
        if candidate is not None:
            primary_index = main_segment_index

    if primary_index is None:
        # Fallback: the lexical Strong component normally follows prefix codes,
        # so the last numeric component is the safest stable fallback.
        for idx in range(len(parts), 0, -1):
            if strongs[idx - 1] is not None:
                primary_index = idx
                break

    components = tuple(
        LemmaComponent(
            lemma_index=i,
            raw_component=part,
            strong_number=strongs[i - 1],
            is_primary=(i == primary_index),
        )
        for i, part in enumerate(parts, start=1)
    )
    primary_strong = strongs[primary_index - 1] if primary_index else None
    return components, primary_strong


def element_text(element: ET.Element) -> str:
    return "".join(element.itertext())


def parse_osis(osis: str) -> tuple[Optional[str], Optional[int], Optional[int]]:
    match = SIMPLE_OSIS.match(osis or "")
    if not match:
        return None, None, None
    return match.group(1), int(match.group(2)), int(match.group(3))


def parse_verse_map(xml_bytes: bytes) -> dict[str, str]:
    root = ET.fromstring(xml_bytes)
    mapping: dict[str, str] = {}
    for element in root.iter():
        if local_name(element.tag) != "verse":
            continue
        wlc = element.attrib.get("wlc")
        kjv = element.attrib.get("kjv")
        # dtworks.verses is verse-granular. Segment-only correspondences are
        # preserved by the generic reference layer, not forced into this
        # one-reference compatibility column. A segment suffix on the KJV side
        # of a full WLC verse is safely reduced to its containing verse here.
        if wlc and kjv and "!" not in wlc:
            kjv_match = OSIS_SEGMENT.match(kjv)
            if kjv_match:
                mapping[wlc] = kjv_match.group(1)
    return mapping


def parse_book(xml_bytes: bytes, verse_map: dict[str, str], expected_book: str = DEFAULT_BOOK) -> tuple[VerseRecord, ...]:
    root = ET.fromstring(xml_bytes)
    verses: list[VerseRecord] = []

    for verse_el in root.iter():
        if local_name(verse_el.tag) != "verse":
            continue
        osis_wlc = verse_el.attrib.get("osisID", "")
        book, chapter_wlc, verse_wlc = parse_osis(osis_wlc)
        if book != expected_book or chapter_wlc is None or verse_wlc is None:
            continue

        osis_kjv = verse_map.get(osis_wlc)
        _, chapter_kjv, verse_kjv = parse_osis(osis_kjv or "")

        tokens: list[TokenRecord] = []
        token_index = 0
        for word_el in verse_el.iter():
            if local_name(word_el.tag) != "w":
                continue
            token_index += 1
            source_surface = element_text(word_el)
            surface = strip_slashes(source_surface)
            lemma_raw = word_el.attrib.get("lemma", "")
            morph_raw = word_el.attrib.get("morph", "")
            morph_segments, main = parse_morphology(morph_raw)
            main_index = main.segment_index if main else None
            lemmas, primary_strong = parse_lemmas(lemma_raw, main_index)
            language = main.language_code if main else (morph_raw[:1] if morph_raw[:1] in {"H", "A"} else "H")

            tokens.append(
                TokenRecord(
                    token_index=token_index,
                    surface=surface,
                    form_search=normalize_form(source_surface),
                    form_consonantal=normalize_consonantal(source_surface),
                    lemma_raw=lemma_raw,
                    primary_strong=primary_strong,
                    lemma_display=None,
                    morph_raw=morph_raw,
                    language_code=language,
                    main_pos_code=main.pos_code if main else None,
                    main_stem_code=main.verb_stem_code if main else None,
                    main_conjugation_code=main.verb_conjugation_code if main else None,
                    person_code=main.person_code if main else None,
                    gender_code=main.gender_code if main else None,
                    number_code=main.number_code if main else None,
                    state_code=main.state_code if main else None,
                    lemmas=lemmas,
                    morph_segments=morph_segments,
                )
            )

        verses.append(
            VerseRecord(
                book=book,
                chapter_wlc=chapter_wlc,
                verse_wlc=verse_wlc,
                osis_wlc=osis_wlc,
                chapter_kjv=chapter_kjv,
                verse_kjv=verse_kjv,
                osis_kjv=osis_kjv,
                tokens=tuple(tokens),
            )
        )

    if not verses:
        raise ValueError(f"no verses parsed for {expected_book}")
    return tuple(verses)


def verify_050(verses: Iterable[VerseRecord]) -> TokenRecord:
    """Assert the actual pinned Genesis data supports the 050 search model."""
    target_verse = next((v for v in verses if v.osis_wlc == "Gen.32.4"), None)
    if target_verse is None:
        raise AssertionError("Gen.32.4 not found in pinned MorphHB source")

    candidates = [t for t in target_verse.tokens if t.primary_strong == 7971]
    if not candidates:
        raise AssertionError("Strong 7971 not found in WLC Gen.32.4")
    target = candidates[0]
    if target.main_pos_code != "V":
        raise AssertionError(f"Gen.32.4 Strong 7971 POS expected V, got {target.main_pos_code!r}")
    if target.main_stem_code != "q":
        raise AssertionError(f"Gen.32.4 Strong 7971 stem expected q/Qal, got {target.main_stem_code!r}")
    if target.main_conjugation_code != "w":
        raise AssertionError(
            "Gen.32.4 Strong 7971 conjugation expected w/wayyiqtol, "
            f"got {target.main_conjugation_code!r}"
        )
    return target


def counts(verses: Iterable[VerseRecord]) -> tuple[int, int, int, int]:
    verse_count = token_count = lemma_count = morph_count = 0
    for verse in verses:
        verse_count += 1
        token_count += len(verse.tokens)
        lemma_count += sum(len(token.lemmas) for token in verse.tokens)
        morph_count += sum(len(token.morph_segments) for token in verse.tokens)
    return verse_count, token_count, lemma_count, morph_count


def _copy_rows(cur, statement: str, rows: Iterable[tuple]) -> None:
    with cur.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)


def _create_staging_tables(cur) -> None:
    statements = (
        """
        CREATE TEMP TABLE IF NOT EXISTS stage_verses (
            osis_wlc TEXT PRIMARY KEY, chapter_wlc SMALLINT, verse_wlc SMALLINT,
            chapter_kjv SMALLINT, verse_kjv SMALLINT, osis_kjv TEXT
        ) ON COMMIT PRESERVE ROWS
        """,
        """
        CREATE TEMP TABLE IF NOT EXISTS stage_tokens (
            osis_wlc TEXT, token_index SMALLINT, surface TEXT, form_search TEXT,
            form_consonantal TEXT, lemma_raw TEXT, primary_strong INTEGER,
            primary_lexeme_key TEXT, lemma_display TEXT, morph_raw TEXT,
            language_code CHAR(1), main_pos_code CHAR(1), main_stem_code CHAR(1),
            main_conjugation_code CHAR(1), person_code CHAR(1), gender_code CHAR(1),
            number_code CHAR(1), state_code CHAR(1)
        ) ON COMMIT PRESERVE ROWS
        """,
        """
        CREATE TEMP TABLE IF NOT EXISTS stage_lemmas (
            osis_wlc TEXT, token_index SMALLINT, lemma_index SMALLINT,
            raw_component TEXT, strong_number INTEGER, lexeme_key TEXT,
            is_primary BOOLEAN
        ) ON COMMIT PRESERVE ROWS
        """,
        """
        CREATE TEMP TABLE IF NOT EXISTS stage_morph (
            osis_wlc TEXT, token_index SMALLINT, segment_index SMALLINT,
            is_main BOOLEAN, morph_code TEXT, language_code CHAR(1),
            pos_code CHAR(1), subtype_code CHAR(1), verb_stem_code CHAR(1),
            verb_conjugation_code CHAR(1), person_code CHAR(1), gender_code CHAR(1),
            number_code CHAR(1), state_code CHAR(1)
        ) ON COMMIT PRESERVE ROWS
        """,
    )
    for statement in statements:
        cur.execute(statement)


def _book_database_counts(cur, source_version_id: int, book_id: int) -> tuple[int, int, int, int]:
    cur.execute(
        """
        WITH selected_verses AS (
            SELECT id FROM dtworks.verses WHERE source_version_id=%s AND book_id=%s
        ), selected_tokens AS (
            SELECT t.id FROM dtworks.tokens t JOIN selected_verses v ON v.id=t.verse_id
        )
        SELECT
          (SELECT count(*) FROM selected_verses),
          (SELECT count(*) FROM selected_tokens),
          (SELECT count(*) FROM dtworks.token_lemmas tl JOIN selected_tokens t ON t.id=tl.token_id),
          (SELECT count(*) FROM dtworks.morph_segments ms JOIN selected_tokens t ON t.id=ms.token_id)
        """,
        (source_version_id, book_id),
    )
    return tuple(int(value) for value in cur.fetchone())


def import_postgres(
    database_url: str,
    books: list[tuple[str, tuple[VerseRecord, ...]]],
    replace_existing: bool = False,
) -> None:
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - exercised in integration CI
        raise RuntimeError(
            "PostgreSQL import requires psycopg 3. Install requirements.txt first."
        ) from exc

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            _create_staging_tables(cur)
            conn.commit()

        for book_code, verses in books:
            expected = counts(verses)
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                    """
                    INSERT INTO dtworks.source_versions
                        (source_name, source_commit, source_license, notes)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (source_name, source_commit) DO UPDATE SET
                        source_license = EXCLUDED.source_license,
                        notes = EXCLUDED.notes
                    RETURNING id
                    """,
                    (SOURCE_NAME, MORPHHB_COMMIT, SOURCE_LICENSE, "DTWorks 2 reproducible MorphHB Tanakh import"),
                    )
                    source_version_id = cur.fetchone()[0]

                    cur.execute("SELECT id FROM dtworks.books WHERE osis_code = %s", (book_code,))
                    row = cur.fetchone()
                    if not row:
                        raise RuntimeError(
                            f"Book {book_code!r} is not seeded. Run seed_books.sql before importing."
                        )
                    book_id = row[0]

                    existing = _book_database_counts(cur, source_version_id, book_id)
                    if existing == expected and not replace_existing:
                        print(f"{book_code}: already complete; verified and skipped")
                        continue
                    if existing[0] and not replace_existing:
                        raise RuntimeError(
                            f"{book_code}: partial/mismatched existing slice {existing}; "
                            "rerun with --replace-existing after review"
                        )

                    cur.execute(
                        "DELETE FROM dtworks.verses WHERE source_version_id = %s AND book_id = %s",
                        (source_version_id, book_id),
                    )
                    cur.execute("TRUNCATE stage_verses, stage_tokens, stage_lemmas, stage_morph")

                    _copy_rows(
                        cur,
                        "COPY stage_verses (osis_wlc,chapter_wlc,verse_wlc,chapter_kjv,verse_kjv,osis_kjv) FROM STDIN",
                        (
                            (v.osis_wlc, v.chapter_wlc, v.verse_wlc, v.chapter_kjv, v.verse_kjv, v.osis_kjv)
                            for v in verses
                        ),
                    )
                    _copy_rows(
                        cur,
                        """COPY stage_tokens (
                            osis_wlc,token_index,surface,form_search,form_consonantal,
                            lemma_raw,primary_strong,primary_lexeme_key,lemma_display,
                            morph_raw,language_code,main_pos_code,main_stem_code,
                            main_conjugation_code,person_code,gender_code,number_code,state_code
                        ) FROM STDIN""",
                        (
                            (
                                v.osis_wlc, t.token_index, t.surface, t.form_search,
                                t.form_consonantal, t.lemma_raw, t.primary_strong,
                                next((normalize_lexeme_key(l.raw_component) for l in t.lemmas if l.is_primary), None),
                                t.lemma_display, t.morph_raw, t.language_code,
                                t.main_pos_code, t.main_stem_code, t.main_conjugation_code,
                                t.person_code, t.gender_code, t.number_code, t.state_code,
                            )
                            for v in verses for t in v.tokens
                        ),
                    )
                    _copy_rows(
                        cur,
                        """COPY stage_lemmas (
                            osis_wlc,token_index,lemma_index,raw_component,strong_number,
                            lexeme_key,is_primary
                        ) FROM STDIN""",
                        (
                            (
                                v.osis_wlc, t.token_index, l.lemma_index, l.raw_component,
                                l.strong_number, normalize_lexeme_key(l.raw_component), l.is_primary,
                            )
                            for v in verses for t in v.tokens for l in t.lemmas
                        ),
                    )
                    _copy_rows(
                        cur,
                        """COPY stage_morph (
                            osis_wlc,token_index,segment_index,is_main,morph_code,
                            language_code,pos_code,subtype_code,verb_stem_code,
                            verb_conjugation_code,person_code,gender_code,number_code,state_code
                        ) FROM STDIN""",
                        (
                            (
                                v.osis_wlc, t.token_index, s.segment_index, s.is_main,
                                s.morph_code, s.language_code, s.pos_code, s.subtype_code,
                                s.verb_stem_code, s.verb_conjugation_code, s.person_code,
                                s.gender_code, s.number_code, s.state_code,
                            )
                            for v in verses for t in v.tokens for s in t.morph_segments
                        ),
                    )

                    cur.execute(
                        """
                        INSERT INTO dtworks.verses
                            (source_version_id, book_id, chapter_wlc, verse_wlc, osis_wlc,
                             chapter_kjv, verse_kjv, osis_kjv)
                        SELECT %s, %s, chapter_wlc, verse_wlc, osis_wlc,
                               chapter_kjv, verse_kjv, osis_kjv
                          FROM stage_verses
                         ORDER BY chapter_wlc, verse_wlc
                        """,
                        (source_version_id, book_id),
                    )
                    cur.execute(
                        """
                        WITH src AS (
                            SELECT id FROM core.lexicon_sources WHERE code='oshb-hebrew-lexicon'
                        ), observed AS (
                            SELECT lexeme_key, min(strong_number) AS strong_number,
                                   CASE WHEN bool_or(t.language_code='A') THEN 'arc' ELSE 'he' END AS language_code
                              FROM stage_lemmas l
                              LEFT JOIN stage_tokens t USING (osis_wlc,token_index)
                             WHERE lexeme_key IS NOT NULL GROUP BY lexeme_key
                        )
                        INSERT INTO core.lexemes (lexicon_source_id,source_lexeme_key,language_code,strong_number)
                        SELECT src.id,observed.lexeme_key,observed.language_code,observed.strong_number
                          FROM src CROSS JOIN observed
                        ON CONFLICT (lexicon_source_id,source_lexeme_key) DO UPDATE SET
                            language_code=EXCLUDED.language_code,
                            strong_number=EXCLUDED.strong_number,
                            updated_at=now()
                        """
                    )
                    cur.execute(
                        """
                        INSERT INTO dtworks.tokens (
                            verse_id,token_index,surface,form_search,form_consonantal,
                            lemma_raw,primary_strong,primary_lexeme_id,lemma_display,morph_raw,
                            language_code,main_pos_code,main_stem_code,main_conjugation_code,
                            person_code,gender_code,number_code,state_code
                        )
                        SELECT v.id,s.token_index,s.surface,s.form_search,s.form_consonantal,
                               s.lemma_raw,s.primary_strong,lx.id,s.lemma_display,s.morph_raw,
                               s.language_code,s.main_pos_code,s.main_stem_code,s.main_conjugation_code,
                               s.person_code,s.gender_code,s.number_code,s.state_code
                          FROM stage_tokens s
                          JOIN dtworks.verses v ON v.source_version_id=%s AND v.osis_wlc=s.osis_wlc
                          LEFT JOIN core.lexicon_sources lxs ON lxs.code='oshb-hebrew-lexicon'
                          LEFT JOIN core.lexemes lx ON lx.lexicon_source_id=lxs.id
                                                   AND lx.source_lexeme_key=s.primary_lexeme_key
                         ORDER BY s.osis_wlc,s.token_index
                        """,
                        (source_version_id,),
                    )
                    cur.execute(
                        """
                        INSERT INTO dtworks.token_lemmas
                            (token_id,lemma_index,raw_component,strong_number,is_primary,lexeme_id)
                        SELECT t.id,s.lemma_index,s.raw_component,s.strong_number,s.is_primary,lx.id
                          FROM stage_lemmas s
                          JOIN dtworks.verses v ON v.source_version_id=%s AND v.osis_wlc=s.osis_wlc
                          JOIN dtworks.tokens t ON t.verse_id=v.id AND t.token_index=s.token_index
                          LEFT JOIN core.lexicon_sources lxs ON lxs.code='oshb-hebrew-lexicon'
                          LEFT JOIN core.lexemes lx ON lx.lexicon_source_id=lxs.id
                                                   AND lx.source_lexeme_key=s.lexeme_key
                        """,
                        (source_version_id,),
                    )
                    cur.execute(
                        """
                        INSERT INTO dtworks.morph_segments
                            (token_id,segment_index,is_main,morph_code,language_code,pos_code,
                             subtype_code,verb_stem_code,verb_conjugation_code,person_code,
                             gender_code,number_code,state_code)
                        SELECT t.id,s.segment_index,s.is_main,s.morph_code,s.language_code,s.pos_code,
                               s.subtype_code,s.verb_stem_code,s.verb_conjugation_code,s.person_code,
                               s.gender_code,s.number_code,s.state_code
                          FROM stage_morph s
                          JOIN dtworks.verses v ON v.source_version_id=%s AND v.osis_wlc=s.osis_wlc
                          JOIN dtworks.tokens t ON t.verse_id=v.id AND t.token_index=s.token_index
                        """,
                        (source_version_id,),
                    )

                    actual = _book_database_counts(cur, source_version_id, book_id)
                    if actual != expected:
                        raise AssertionError(f"{book_code}: expected {expected}, imported {actual}")
                    print(
                        f"{book_code}: imported and verified {actual[0]:,} verses / "
                        f"{actual[1]:,} tokens / {actual[2]:,} lemmas / {actual[3]:,} morph segments"
                    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--books",
        default=DEFAULT_BOOK,
        help="Comma-separated OSIS book codes, or 'all' for the complete 39-book Tanakh",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        help="Optional directory containing book XML files and VerseMap.xml; otherwise download pinned GitHub source",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL connection URL. Omit for parse/verify-only dry run.",
    )
    parser.add_argument("--verify-050", action="store_true", help="Assert Gen.32.4 Strong 7971 = Qal wayyiqtol")
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Replace mismatched existing book slices. Complete matching slices are otherwise verified and skipped.",
    )
    return parser


def requested_books(value: str) -> tuple[str, ...]:
    if value.strip().lower() == "all":
        return BOOK_CODES
    selected = tuple(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))
    invalid = [book for book in selected if book not in BOOK_CODES]
    if not selected or invalid:
        raise ValueError(f"unsupported --books value; invalid codes: {invalid!r}")
    return selected


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    selected = requested_books(args.books)
    print(f"MorphHB commit: {MORPHHB_COMMIT}")
    print(f"Loading VerseMap.xml and {len(selected)} book XML file(s)...")
    verse_map = parse_verse_map(source_bytes(args.source_dir, "VerseMap.xml"))
    parsed_books = [
        (book, parse_book(source_bytes(args.source_dir, f"{book}.xml"), verse_map, book))
        for book in selected
    ]
    totals = [0, 0, 0, 0]
    for _, verses in parsed_books:
        totals = [left + right for left, right in zip(totals, counts(verses))]
    verse_count, token_count, lemma_count, morph_count = totals
    print(
        f"Parsed {verse_count:,} verses / {token_count:,} tokens / "
        f"{lemma_count:,} lemma segments / {morph_count:,} morphology segments"
    )

    if args.verify_050:
        genesis = next((verses for book, verses in parsed_books if book == "Gen"), None)
        if genesis is None:
            raise ValueError("--verify-050 requires Gen in --books")
        target = verify_050(genesis)
        print(
            "050 verification OK: Gen.32.4 / "
            f"{target.surface} / Strong {target.primary_strong} / "
            f"stem={target.main_stem_code} (Qal) / "
            f"conjugation={target.main_conjugation_code} (wayyiqtol) / "
            f"morph={target.morph_raw}"
        )

    if args.database_url:
        print(f"Importing {len(parsed_books)} book(s) into PostgreSQL...")
        import_postgres(args.database_url, parsed_books, args.replace_existing)
        print("PostgreSQL import and per-book verification complete.")
    else:
        print("No --database-url supplied: parse/verification only; PostgreSQL was not modified.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
