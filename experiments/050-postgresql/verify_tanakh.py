#!/usr/bin/env python3
"""Capacity gate and post-import verification for the DTWorks 2 Tanakh corpus."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import import_morphhb as imp

FREE_LIMIT_BYTES = 512 * 1024 * 1024
MINIMUM_RESERVE_BYTES = 64 * 1024 * 1024
FIXED_CONTINGENCY_BYTES = 16 * 1024 * 1024
GROWTH_CONTINGENCY = 1.20


def corpus_inventory(source_dir: Path) -> dict:
    verse_map = imp.parse_verse_map((source_dir / "VerseMap.xml").read_bytes())
    totals = [0, 0, 0, 0]
    books: dict[str, dict[str, int]] = {}
    lexeme_keys: set[str] = set()
    for book in imp.BOOK_CODES:
        verses = imp.parse_book((source_dir / f"{book}.xml").read_bytes(), verse_map, book)
        book_counts = imp.counts(verses)
        books[book] = dict(zip(("verses", "tokens", "lemmas", "morph_segments"), book_counts))
        totals = [left + right for left, right in zip(totals, book_counts)]
        for verse in verses:
            for token in verse.tokens:
                for lemma in token.lemmas:
                    key = imp.normalize_lexeme_key(lemma.raw_component)
                    if key:
                        lexeme_keys.add(key)
    return {
        "books": books,
        "book_count": len(books),
        "verses": totals[0],
        "tokens": totals[1],
        "lemmas": totals[2],
        "morph_segments": totals[3],
        "lexemes": len(lexeme_keys),
    }


def capacity_report(conn, inventory: dict, limit_bytes: int) -> dict:
    targets = {
        "dtworks.verses": inventory["verses"],
        "dtworks.tokens": inventory["tokens"],
        "dtworks.token_lemmas": inventory["lemmas"],
        "dtworks.morph_segments": inventory["morph_segments"],
        "core.reference_passages": inventory["verses"] * 2,
        "core.passage_mappings": inventory["verses"],
        "core.source_passages": inventory["verses"],
        "core.lexemes": inventory["lexemes"],
    }
    current_rows_sql = {
        "dtworks.verses": "SELECT count(*) FROM dtworks.verses",
        "dtworks.tokens": "SELECT count(*) FROM dtworks.tokens",
        "dtworks.token_lemmas": "SELECT count(*) FROM dtworks.token_lemmas",
        "dtworks.morph_segments": "SELECT count(*) FROM dtworks.morph_segments",
        "core.reference_passages": "SELECT count(*) FROM core.reference_passages",
        "core.passage_mappings": "SELECT count(*) FROM core.passage_mappings",
        "core.source_passages": "SELECT count(*) FROM core.source_passages",
        "core.lexemes": "SELECT count(*) FROM core.lexemes",
    }
    relations = []
    incremental_bytes = 0.0
    with conn.cursor() as cur:
        cur.execute("SELECT pg_database_size(current_database())")
        database_bytes = int(cur.fetchone()[0])
        for relation, target_rows in targets.items():
            cur.execute(current_rows_sql[relation])
            current_rows = int(cur.fetchone()[0])
            cur.execute("SELECT pg_total_relation_size(%s::regclass)", (relation,))
            current_bytes = int(cur.fetchone()[0])
            if current_rows <= 0:
                raise RuntimeError(f"capacity baseline unavailable: {relation} has no rows")
            bytes_per_row = current_bytes / current_rows
            added_rows = max(0, target_rows - current_rows)
            projected_increment = bytes_per_row * added_rows
            incremental_bytes += projected_increment
            relations.append({
                "relation": relation,
                "current_rows": current_rows,
                "target_rows": target_rows,
                "current_bytes": current_bytes,
                "bytes_per_row": round(bytes_per_row, 2),
                "projected_increment_bytes": round(projected_increment),
            })

    projected_bytes = database_bytes + incremental_bytes
    guarded_bytes = database_bytes + incremental_bytes * GROWTH_CONTINGENCY + FIXED_CONTINGENCY_BYTES
    remaining_bytes = limit_bytes - guarded_bytes
    passed = guarded_bytes <= limit_bytes and remaining_bytes >= MINIMUM_RESERVE_BYTES
    return {
        "passed": passed,
        "limit_bytes": limit_bytes,
        "current_database_bytes": database_bytes,
        "projected_database_bytes": round(projected_bytes),
        "guarded_projected_bytes": round(guarded_bytes),
        "remaining_after_guard_bytes": round(remaining_bytes),
        "minimum_reserve_bytes": MINIMUM_RESERVE_BYTES,
        "growth_contingency": GROWTH_CONTINGENCY,
        "fixed_contingency_bytes": FIXED_CONTINGENCY_BYTES,
        "relations": relations,
    }


def verify_database(conn, inventory: dict) -> dict:
    expected = {
        "books": 39,
        "verses": inventory["verses"],
        "tokens": inventory["tokens"],
        "lemmas": inventory["lemmas"],
        "morph_segments": inventory["morph_segments"],
    }
    sql = """
    SELECT
      (SELECT count(*) FROM dtworks.books b WHERE EXISTS (
         SELECT 1 FROM dtworks.verses v WHERE v.book_id=b.id)) AS books,
      (SELECT count(*) FROM dtworks.verses) AS verses,
      (SELECT count(*) FROM dtworks.tokens) AS tokens,
      (SELECT count(*) FROM dtworks.token_lemmas) AS lemmas,
      (SELECT count(*) FROM dtworks.morph_segments) AS morph_segments,
      (SELECT count(*) FROM core.source_passages) AS source_passages,
      (SELECT count(*) FROM core.passage_mappings) AS passage_mappings,
      (SELECT count(*) FROM core.reference_passages rp
        JOIN core.reference_systems rs ON rs.id=rp.reference_system_id
       WHERE rs.code='WLC') AS wlc_passages,
      (SELECT count(*) FROM dtworks.tokens
       WHERE primary_strong IS NOT NULL AND primary_lexeme_id IS NULL) AS unlinked_primary,
      (SELECT count(*) FROM dtworks.token_lemmas
       WHERE strong_number IS NOT NULL AND lexeme_id IS NULL) AS unlinked_components,
      (SELECT count(*) FROM dtworks.tokens t JOIN core.lexemes lx ON lx.id=t.primary_lexeme_id
       WHERE lx.lemma_text IS NULL) AS unlabeled_primary,
      (SELECT count(*) FROM dtworks.search_tokens
       WHERE book='Gen' AND chapter_wlc=32 AND verse_wlc=4
         AND lexeme_key='7971' AND main_stem_code='q' AND main_conjugation_code='w') AS benchmark,
      (SELECT count(*) FROM core.source_passages sp
       JOIN core.reference_passages rp ON rp.id=sp.reference_passage_id
       WHERE rp.osis_ref IN ('Exod.1.1','Dan.1.1','2Chr.36.23')) AS passage_smoke
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        columns = [item.name for item in cur.description]
        actual = dict(zip(columns, (int(value) for value in cur.fetchone())))
        cur.execute(
            """
            SELECT b.osis_code,count(DISTINCT v.id),count(DISTINCT t.id)
              FROM dtworks.books b
              JOIN dtworks.verses v ON v.book_id=b.id
              JOIN dtworks.tokens t ON t.verse_id=v.id
             GROUP BY b.id,b.osis_code,b.canonical_order
             ORDER BY b.canonical_order
            """
        )
        book_rows = {book: {"verses": int(verses), "tokens": int(tokens)} for book, verses, tokens in cur}

    failures = []
    for key, value in expected.items():
        if actual[key] != value:
            failures.append(f"{key}: expected {value}, got {actual[key]}")
    for key in ("source_passages", "passage_mappings", "wlc_passages"):
        if actual[key] != inventory["verses"]:
            failures.append(f"{key}: expected {inventory['verses']}, got {actual[key]}")
    for key in ("unlinked_primary", "unlinked_components", "unlabeled_primary"):
        if actual[key] != 0:
            failures.append(f"{key}: expected 0, got {actual[key]}")
    if actual["benchmark"] < 1:
        failures.append("Genesis 32:4 lexeme/Qal/wayyiqtol benchmark missing")
    if actual["passage_smoke"] != 3:
        failures.append(f"passage smoke references: expected 3, got {actual['passage_smoke']}")
    for book, source_counts in inventory["books"].items():
        if book_rows.get(book) != {"verses": source_counts["verses"], "tokens": source_counts["tokens"]}:
            failures.append(f"{book}: source/database verse or token count mismatch")
    return {"passed": not failures, "expected": expected, "actual": actual, "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("capacity", "verify"))
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--limit-bytes", type=int, default=FREE_LIMIT_BYTES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL or --database-url is required")

    import psycopg

    inventory = corpus_inventory(args.source_dir)
    if inventory["book_count"] != 39:
        raise RuntimeError(f"expected 39 books, got {inventory['book_count']}")
    with psycopg.connect(args.database_url) as conn:
        report = capacity_report(conn, inventory, args.limit_bytes) if args.mode == "capacity" else verify_database(conn, inventory)
    result = {"mode": args.mode, "source": {k: v for k, v in inventory.items() if k != "books"}, "report": report}
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
