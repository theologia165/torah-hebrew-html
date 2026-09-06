#!/usr/bin/env python3
"""DTWorks 2 MorphHB -> PostgreSQL importer (Genesis POC).

The canonical biblical source remains the pinned Open Scriptures Hebrew Bible /
MorphHB Git commit. PostgreSQL is a derived search index that can be rebuilt.

This first implementation intentionally defaults to Genesis only. It can:

1. download/read the pinned Gen.xml and VerseMap.xml,
2. normalize Form search values,
3. parse Strong/lemma and MorphHB morphology segments,
4. verify the 050 test token in WLC Genesis 32:4,
5. optionally load the derived records into the dtworks PostgreSQL schema.
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
        if wlc and kjv:
            mapping[wlc] = kjv
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


def import_postgres(database_url: str, verses: tuple[VerseRecord, ...], book_code: str) -> None:
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - exercised in integration CI
        raise RuntimeError(
            "PostgreSQL import requires psycopg 3. Install requirements.txt first."
        ) from exc

    with psycopg.connect(database_url) as conn:
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
                    (SOURCE_NAME, MORPHHB_COMMIT, SOURCE_LICENSE, "DTWorks 2 reproducible MorphHB import"),
                )
                source_version_id = cur.fetchone()[0]

                cur.execute("SELECT id FROM dtworks.books WHERE osis_code = %s", (book_code,))
                row = cur.fetchone()
                if not row:
                    raise RuntimeError(
                        f"Book {book_code!r} is not seeded. Run seed_books.sql before importing."
                    )
                book_id = row[0]

                # Idempotent rebuild for this source version + book. Cascades
                # remove dependent tokens/lemmas/morph segments.
                cur.execute(
                    "DELETE FROM dtworks.verses WHERE source_version_id = %s AND book_id = %s",
                    (source_version_id, book_id),
                )

                for verse in verses:
                    cur.execute(
                        """
                        INSERT INTO dtworks.verses
                            (source_version_id, book_id, chapter_wlc, verse_wlc, osis_wlc,
                             chapter_kjv, verse_kjv, osis_kjv)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        RETURNING id
                        """,
                        (
                            source_version_id,
                            book_id,
                            verse.chapter_wlc,
                            verse.verse_wlc,
                            verse.osis_wlc,
                            verse.chapter_kjv,
                            verse.verse_kjv,
                            verse.osis_kjv,
                        ),
                    )
                    verse_id = cur.fetchone()[0]

                    for token in verse.tokens:
                        cur.execute(
                            """
                            INSERT INTO dtworks.tokens
                                (verse_id, token_index, surface, form_search, form_consonantal,
                                 lemma_raw, primary_strong, lemma_display, morph_raw, language_code,
                                 main_pos_code, main_stem_code, main_conjugation_code,
                                 person_code, gender_code, number_code, state_code)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            RETURNING id
                            """,
                            (
                                verse_id,
                                token.token_index,
                                token.surface,
                                token.form_search,
                                token.form_consonantal,
                                token.lemma_raw,
                                token.primary_strong,
                                token.lemma_display,
                                token.morph_raw,
                                token.language_code,
                                token.main_pos_code,
                                token.main_stem_code,
                                token.main_conjugation_code,
                                token.person_code,
                                token.gender_code,
                                token.number_code,
                                token.state_code,
                            ),
                        )
                        token_id = cur.fetchone()[0]

                        if token.lemmas:
                            cur.executemany(
                                """
                                INSERT INTO dtworks.token_lemmas
                                    (token_id, lemma_index, raw_component, strong_number, is_primary)
                                VALUES (%s,%s,%s,%s,%s)
                                """,
                                [
                                    (
                                        token_id,
                                        lemma.lemma_index,
                                        lemma.raw_component,
                                        lemma.strong_number,
                                        lemma.is_primary,
                                    )
                                    for lemma in token.lemmas
                                ],
                            )

                        if token.morph_segments:
                            cur.executemany(
                                """
                                INSERT INTO dtworks.morph_segments
                                    (token_id, segment_index, is_main, morph_code, language_code,
                                     pos_code, subtype_code, verb_stem_code, verb_conjugation_code,
                                     person_code, gender_code, number_code, state_code)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                """,
                                [
                                    (
                                        token_id,
                                        seg.segment_index,
                                        seg.is_main,
                                        seg.morph_code,
                                        seg.language_code,
                                        seg.pos_code,
                                        seg.subtype_code,
                                        seg.verb_stem_code,
                                        seg.verb_conjugation_code,
                                        seg.person_code,
                                        seg.gender_code,
                                        seg.number_code,
                                        seg.state_code,
                                    )
                                    for seg in token.morph_segments
                                ],
                            )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", default=DEFAULT_BOOK, choices=[DEFAULT_BOOK], help="POC currently supports Genesis only")
    parser.add_argument(
        "--source-dir",
        type=Path,
        help="Optional directory containing Gen.xml and VerseMap.xml; otherwise download pinned GitHub source",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL connection URL. Omit for parse/verify-only dry run.",
    )
    parser.add_argument("--verify-050", action="store_true", help="Assert Gen.32.4 Strong 7971 = Qal wayyiqtol")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    print(f"MorphHB commit: {MORPHHB_COMMIT}")
    print("Loading VerseMap.xml and Gen.xml...")
    verse_map = parse_verse_map(source_bytes(args.source_dir, "VerseMap.xml"))
    verses = parse_book(source_bytes(args.source_dir, "Gen.xml"), verse_map, args.book)
    verse_count, token_count, lemma_count, morph_count = counts(verses)
    print(
        f"Parsed {verse_count:,} verses / {token_count:,} tokens / "
        f"{lemma_count:,} lemma segments / {morph_count:,} morphology segments"
    )

    if args.verify_050:
        target = verify_050(verses)
        print(
            "050 verification OK: Gen.32.4 / "
            f"{target.surface} / Strong {target.primary_strong} / "
            f"stem={target.main_stem_code} (Qal) / "
            f"conjugation={target.main_conjugation_code} (wayyiqtol) / "
            f"morph={target.morph_raw}"
        )

    if args.database_url:
        print("Importing Genesis into PostgreSQL...")
        import_postgres(args.database_url, verses, args.book)
        print("PostgreSQL import complete.")
    else:
        print("No --database-url supplied: parse/verification only; PostgreSQL was not modified.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
