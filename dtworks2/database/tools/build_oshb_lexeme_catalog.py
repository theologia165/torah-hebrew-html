#!/usr/bin/env python3
"""Build a deterministic OSHB lexeme catalog and idempotent SQL chunks.

Source of truth is the pinned Open Scriptures Hebrew Lexicon commit. This script
never calls ChatGPT and never writes to Neon. GitHub Actions can rebuild the
catalog artifact, and a controlled database step can apply the generated SQL.
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
REPO_RAW = f"https://raw.githubusercontent.com/openscriptures/HebrewLexicon/{LEXICON_COMMIT}"
SOURCE_CODE = "oshb-hebrew-lexicon"
SOURCE_LICENSE = "CC BY 4.0"

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
LEADING_DIGITS = re.compile(r"^(\d+)")
LANGUAGE_CODES = {"heb": "he", "arc": "arc"}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def fetch_bytes(filename: str) -> bytes:
    req = urllib.request.Request(
        f"{REPO_RAW}/{filename}",
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


def parse_lexical_index(xml_bytes: bytes) -> dict[str, dict]:
    root = ET.fromstring(xml_bytes)
    entries: dict[str, dict] = {}

    for part in root.iter():
        if local_name(part.tag) != "part":
            continue
        language_code = LANGUAGE_CODES.get(part.attrib.get(XML_LANG, ""), part.attrib.get(XML_LANG, "und"))
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


def sql_literal(value: object | None) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def row_sql(row: dict) -> str:
    fields = [
        row["source_lexeme_key"],
        row["source_entry_id"],
        row["language_code"],
        row["lemma_text"],
        row["lemma_search"],
        row["transliteration"],
        row["strong_number"],
        row["pos_code"],
    ]
    return "(" + ",".join(sql_literal(v) for v in fields) + ")"


def write_sql_chunks(rows: list[dict], output_dir: Path, chunk_size: int) -> list[dict]:
    chunks: list[dict] = []
    for number, start in enumerate(range(0, len(rows), chunk_size), start=1):
        chunk = rows[start : start + chunk_size]
        values = ",\n".join(row_sql(row) for row in chunk)
        sql = f"""-- Generated from Open Scriptures Hebrew Lexicon {LEXICON_COMMIT}\nWITH src AS (\n    SELECT id FROM core.lexicon_sources WHERE code = '{SOURCE_CODE}'\n), data(\n    source_lexeme_key, source_entry_id, language_code, lemma_text, lemma_search,\n    transliteration, strong_number, pos_code\n) AS (\n    VALUES\n{values}\n)\nINSERT INTO core.lexemes (\n    lexicon_source_id, source_lexeme_key, source_entry_id, language_code,\n    lemma_text, lemma_search, transliteration, strong_number, pos_code\n)\nSELECT\n    src.id, data.source_lexeme_key, data.source_entry_id, data.language_code,\n    data.lemma_text, data.lemma_search, data.transliteration,\n    data.strong_number, data.pos_code\nFROM src CROSS JOIN data\nON CONFLICT (lexicon_source_id, source_lexeme_key) DO UPDATE SET\n    source_entry_id = EXCLUDED.source_entry_id,\n    language_code = EXCLUDED.language_code,\n    lemma_text = EXCLUDED.lemma_text,\n    lemma_search = EXCLUDED.lemma_search,\n    transliteration = EXCLUDED.transliteration,\n    strong_number = EXCLUDED.strong_number,\n    pos_code = EXCLUDED.pos_code,\n    updated_at = now();\n"""
        filename = f"oshb-lexemes-{number:03d}.sql"
        path = output_dir / filename
        path.write_text(sql, encoding="utf-8")
        chunks.append({
            "file": filename,
            "rows": len(chunk),
            "sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        })
    return chunks


def build(output_dir: Path, chunk_size: int) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    aug_bytes = fetch_bytes("AugIndex.xml")
    lexical_bytes = fetch_bytes("LexicalIndex.xml")

    lexical = parse_lexical_index(lexical_bytes)
    aug = parse_aug_index(aug_bytes)

    rows: list[dict] = []
    missing: list[dict] = []
    for key, entry_id in aug:
        entry = lexical.get(entry_id)
        if not entry:
            missing.append({"source_lexeme_key": key, "source_entry_id": entry_id})
            continue
        match = LEADING_DIGITS.match(key)
        rows.append({
            "source_lexeme_key": key,
            **entry,
            "strong_number": int(match.group(1)) if match else None,
        })

    rows.sort(key=lambda row: (row["strong_number"] or 10**9, row["source_lexeme_key"]))

    by_key = {row["source_lexeme_key"]: row for row in rows}
    benchmark = by_key.get("7971")
    if not benchmark or benchmark.get("lemma_text") != "שָׁלַח":
        raise RuntimeError(f"OSHB benchmark 7971 mismatch: {benchmark!r}")

    jsonl_path = output_dir / "oshb-lexemes.jsonl"
    jsonl = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    jsonl_path.write_text(jsonl, encoding="utf-8")

    chunks = write_sql_chunks(rows, output_dir, chunk_size)
    manifest = {
        "schema_version": 1,
        "source": {
            "code": SOURCE_CODE,
            "commit": LEXICON_COMMIT,
            "license": SOURCE_LICENSE,
            "files": ["AugIndex.xml", "LexicalIndex.xml"],
        },
        "rows": len(rows),
        "missing_entries": missing,
        "jsonl_sha256": hashlib.sha256(jsonl.encode("utf-8")).hexdigest(),
        "sql_chunks": chunks,
        "benchmark": {
            "source_lexeme_key": "7971",
            "source_entry_id": benchmark["source_entry_id"],
            "lemma_text": benchmark["lemma_text"],
            "lemma_search": benchmark["lemma_search"],
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--chunk-size", type=int, default=750)
    args = parser.parse_args()
    if args.chunk_size < 100 or args.chunk_size > 2000:
        raise SystemExit("chunk-size must be between 100 and 2000")
    manifest = build(args.output_dir, args.chunk_size)
    print(json.dumps({
        "ok": True,
        "rows": manifest["rows"],
        "missing_entries": len(manifest["missing_entries"]),
        "chunks": len(manifest["sql_chunks"]),
        "benchmark": manifest["benchmark"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
