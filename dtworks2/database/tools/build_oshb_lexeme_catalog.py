#!/usr/bin/env python3
"""Build deterministic OSHB lexeme catalog artifacts.

The full lexical catalog is derived from a pinned Open Scriptures Hebrew Lexicon
commit. SQL chunks are filtered to lexical keys actually observed in either
Genesis or the complete 39-book MorphHB Tanakh. No authored content and no live
database access are involved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

LEXICON_COMMIT = "21c9add13bc727d3a951361778e97e3ff7afd1ce"
LEXICON_RAW = f"https://raw.githubusercontent.com/openscriptures/HebrewLexicon/{LEXICON_COMMIT}"
MORPHHB_COMMIT = "3d15126fb1ef74867fc1434be1942e837932691f"
MORPHHB_RAW = f"https://raw.githubusercontent.com/openscriptures/morphhb/{MORPHHB_COMMIT}/wlc"
SOURCE_CODE = "oshb-hebrew-lexicon"
SOURCE_LICENSE = "CC BY 4.0"
BOOK_CODES = (
    "Gen", "Exod", "Lev", "Num", "Deut", "Josh", "Judg", "1Sam", "2Sam",
    "1Kgs", "2Kgs", "Isa", "Jer", "Ezek", "Hos", "Joel", "Amos", "Obad",
    "Jonah", "Mic", "Nah", "Hab", "Zeph", "Hag", "Zech", "Mal", "Ps",
    "Job", "Prov", "Ruth", "Song", "Eccl", "Lam", "Esth", "Dan", "Ezra",
    "Neh", "1Chr", "2Chr",
)

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
LEADING_DIGITS = re.compile(r"^(\d+)")
LANGUAGE_CODES = {"heb": "he", "arc": "arc"}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Nishihara-Midrash-Lab-DTWorks2/lexeme-builder"},
    )
    with urllib.request.urlopen(req, timeout=90) as response:
        return response.read()


def text_of(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    value = "".join(element.itertext()).strip()
    return value or None


def direct_child(entry: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in entry if local_name(child.tag) == name), None)


def lemma_search_key(value: str | None) -> str | None:
    if not value:
        return None
    nfd = unicodedata.normalize("NFD", value)
    stripped = "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", stripped)


def normalize_morphhb_lexeme_key(raw: str) -> str | None:
    value = re.sub(r"\s+", "", raw.strip())
    value = value[:-1] if value.endswith("+") else value
    return value if LEADING_DIGITS.match(value) else None


def parse_morphhb_keys(xml_bytes: bytes) -> set[str]:
    root = ET.fromstring(xml_bytes)
    keys: set[str] = set()
    for element in root.iter():
        if local_name(element.tag) != "w":
            continue
        for component in element.attrib.get("lemma", "").split("/"):
            key = normalize_morphhb_lexeme_key(component)
            if key:
                keys.add(key)
    return keys


def parse_lexical_index(xml_bytes: bytes) -> dict[str, dict]:
    root = ET.fromstring(xml_bytes)
    entries: dict[str, dict] = {}
    for part in root.iter():
        if local_name(part.tag) != "part":
            continue
        xml_language = part.attrib.get(XML_LANG, "")
        language_code = LANGUAGE_CODES.get(xml_language, xml_language or "und")
        for entry in part:
            if local_name(entry.tag) != "entry":
                continue
            entry_id = entry.attrib.get("id")
            if not entry_id:
                continue
            word = direct_child(entry, "w")
            pos = direct_child(entry, "pos")
            lemma = text_of(word)
            entries[entry_id] = {
                "source_entry_id": entry_id,
                "language_code": language_code,
                "lemma_text": lemma,
                "lemma_search": lemma_search_key(lemma),
                "transliteration": word.attrib.get("xlit") if word is not None else None,
                "pos_code": text_of(pos),
            }
    return entries


def parse_aug_index(xml_bytes: bytes) -> list[tuple[str, str]]:
    root = ET.fromstring(xml_bytes)
    rows: list[tuple[str, str]] = []
    for element in root.iter():
        if local_name(element.tag) != "w":
            continue
        key = element.attrib.get("aug")
        entry_id = text_of(element)
        if key and entry_id:
            rows.append((key.strip(), entry_id.strip()))
    return rows


def parse_strong_index(xml_bytes: bytes) -> dict[str, dict]:
    root = ET.fromstring(xml_bytes)
    rows: dict[str, dict] = {}
    for entry in root.iter():
        if local_name(entry.tag) != "entry":
            continue
        entry_id = entry.attrib.get("id", "")
        if not entry_id.startswith("H") or not entry_id[1:].isdigit():
            continue
        word = direct_child(entry, "w")
        lemma = text_of(word)
        xml_language = word.attrib.get(XML_LANG, "") if word is not None else ""
        rows[entry_id[1:]] = {
            "source_entry_id": entry_id,
            "language_code": LANGUAGE_CODES.get(xml_language, "he" if xml_language == "x-pn" else xml_language or "und"),
            "lemma_text": lemma,
            "lemma_search": lemma_search_key(lemma),
            "transliteration": word.attrib.get("xlit") if word is not None else None,
            "pos_code": word.attrib.get("pos") if word is not None else None,
        }
    return rows


def sql_literal(value: object | None) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def row_sql(row: dict) -> str:
    fields = [
        row["source_lexeme_key"], row["source_entry_id"], row["language_code"],
        row["lemma_text"], row["lemma_search"], row["transliteration"],
        row["strong_number"], row["pos_code"],
    ]
    return "(" + ",".join(sql_literal(v) for v in fields) + ")"


def write_sql_chunks(rows: list[dict], output_dir: Path, chunk_size: int, scope: str) -> list[dict]:
    chunks: list[dict] = []
    for number, start in enumerate(range(0, len(rows), chunk_size), start=1):
        chunk = rows[start : start + chunk_size]
        values = ",\n".join(row_sql(row) for row in chunk)
        sql = f"""-- Generated {scope} lexeme rows from pinned OSHB sources\nWITH src AS (\n    SELECT id FROM core.lexicon_sources WHERE code = '{SOURCE_CODE}'\n), data(\n    source_lexeme_key, source_entry_id, language_code, lemma_text, lemma_search,\n    transliteration, strong_number, pos_code\n) AS (\n    VALUES\n{values}\n)\nINSERT INTO core.lexemes (\n    lexicon_source_id, source_lexeme_key, source_entry_id, language_code,\n    lemma_text, lemma_search, transliteration, strong_number, pos_code\n)\nSELECT\n    src.id, data.source_lexeme_key, data.source_entry_id, data.language_code,\n    data.lemma_text, data.lemma_search, data.transliteration,\n    data.strong_number, data.pos_code\nFROM src CROSS JOIN data\nON CONFLICT (lexicon_source_id, source_lexeme_key) DO UPDATE SET\n    source_entry_id = EXCLUDED.source_entry_id,\n    language_code = EXCLUDED.language_code,\n    lemma_text = EXCLUDED.lemma_text,\n    lemma_search = EXCLUDED.lemma_search,\n    transliteration = EXCLUDED.transliteration,\n    strong_number = EXCLUDED.strong_number,\n    pos_code = EXCLUDED.pos_code,\n    updated_at = now();\n"""
        filename = f"{scope}-lexemes-{number:03d}.sql"
        path = output_dir / filename
        path.write_text(sql, encoding="utf-8")
        chunks.append({"file": filename, "rows": len(chunk), "sha256": hashlib.sha256(sql.encode()).hexdigest()})
    return chunks


def build(
    output_dir: Path,
    chunk_size: int,
    scope: str = "genesis",
    morphhb_dir: Path | None = None,
    lexicon_dir: Path | None = None,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    aug_bytes = (lexicon_dir / "AugIndex.xml").read_bytes() if lexicon_dir else fetch_bytes(f"{LEXICON_RAW}/AugIndex.xml")
    lexical_bytes = (lexicon_dir / "LexicalIndex.xml").read_bytes() if lexicon_dir else fetch_bytes(f"{LEXICON_RAW}/LexicalIndex.xml")
    strong_bytes = (lexicon_dir / "HebrewStrong.xml").read_bytes() if lexicon_dir else fetch_bytes(f"{LEXICON_RAW}/HebrewStrong.xml")

    lexical = parse_lexical_index(lexical_bytes)
    aug = parse_aug_index(aug_bytes)
    strong = parse_strong_index(strong_bytes)
    selected_books = ("Gen",) if scope == "genesis" else BOOK_CODES
    observed_keys: set[str] = set()
    for book in selected_books:
        xml_bytes = (morphhb_dir / f"{book}.xml").read_bytes() if morphhb_dir else fetch_bytes(f"{MORPHHB_RAW}/{book}.xml")
        observed_keys.update(parse_morphhb_keys(xml_bytes))

    rows: list[dict] = []
    missing_entries: list[dict] = []
    for key, entry_id in aug:
        entry = lexical.get(entry_id)
        if not entry:
            missing_entries.append({"source_lexeme_key": key, "source_entry_id": entry_id})
            continue
        match = LEADING_DIGITS.match(key)
        rows.append({"source_lexeme_key": key, **entry, "strong_number": int(match.group(1)) if match else None})
    rows.sort(key=lambda row: (row["strong_number"] or 10**9, row["source_lexeme_key"]))

    by_key = {row["source_lexeme_key"]: row for row in rows}
    benchmark = by_key.get("7971")
    if not benchmark or benchmark.get("lemma_text") != "שָׁלַח":
        raise RuntimeError(f"OSHB benchmark 7971 mismatch: {benchmark!r}")

    lexical_fallbacks: list[str] = []
    scope_missing = sorted(key for key in observed_keys if key not in by_key)
    for key in scope_missing:
        fallback = strong.get(key) if key.isdigit() else None
        if fallback:
            by_key[key] = {"source_lexeme_key": key, **fallback, "strong_number": int(key)}
            lexical_fallbacks.append(key)
    scope_missing = sorted(key for key in observed_keys if key not in by_key)
    if scope_missing:
        raise RuntimeError(f"{scope} lexical keys missing from OSHB indexes: {scope_missing[:20]!r}")
    scope_rows = [by_key[key] for key in sorted(observed_keys, key=lambda k: (int(LEADING_DIGITS.match(k).group(1)), k))]

    full_jsonl = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    (output_dir / "oshb-lexemes.jsonl").write_text(full_jsonl, encoding="utf-8")
    scope_jsonl = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in scope_rows)
    (output_dir / f"{scope}-lexemes.jsonl").write_text(scope_jsonl, encoding="utf-8")

    chunks = write_sql_chunks(scope_rows, output_dir, chunk_size, scope)
    manifest = {
        "schema_version": 3,
        "scope": scope,
        "books": list(selected_books),
        "source": {
            "code": SOURCE_CODE,
            "lexicon_commit": LEXICON_COMMIT,
            "morphhb_commit": MORPHHB_COMMIT,
            "license": SOURCE_LICENSE,
        },
        "catalog_rows": len(rows),
        "scope_rows": len(scope_rows),
        "scope_keys": len(observed_keys),
        "missing_entries": missing_entries,
        "scope_missing": scope_missing,
        "hebrew_strong_fallback_keys": lexical_fallbacks,
        "full_jsonl_sha256": hashlib.sha256(full_jsonl.encode()).hexdigest(),
        "scope_jsonl_sha256": hashlib.sha256(scope_jsonl.encode()).hexdigest(),
        "sql_chunks": chunks,
        "benchmark": {
            "source_lexeme_key": "7971",
            "source_entry_id": benchmark["source_entry_id"],
            "lemma_text": benchmark["lemma_text"],
            "lemma_search": benchmark["lemma_search"],
        },
    }
    if scope == "genesis":
        # Backward-compatible manifest aliases for the existing Genesis CI.
        manifest.update({
            "genesis_rows": len(scope_rows),
            "genesis_keys": len(observed_keys),
            "genesis_missing": scope_missing,
            "genesis_jsonl_sha256": hashlib.sha256(scope_jsonl.encode()).hexdigest(),
        })
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--chunk-size", type=int, default=750)
    parser.add_argument("--scope", choices=("genesis", "tanakh"), default="genesis")
    parser.add_argument("--morphhb-dir", type=Path)
    parser.add_argument("--lexicon-dir", type=Path)
    args = parser.parse_args()
    if args.chunk_size < 100 or args.chunk_size > 2000:
        raise SystemExit("chunk-size must be between 100 and 2000")
    manifest = build(args.output_dir, args.chunk_size, args.scope, args.morphhb_dir, args.lexicon_dir)
    print(json.dumps({
        "ok": True,
        "catalog_rows": manifest["catalog_rows"],
        "scope": manifest["scope"],
        "scope_rows": manifest["scope_rows"],
        "chunks": len(manifest["sql_chunks"]),
        "benchmark": manifest["benchmark"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
