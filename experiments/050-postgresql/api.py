#!/usr/bin/env python3
"""DTWorks 2 FastAPI POC.

Thin HTTP boundary over the stable dtworks.search_tokens PostgreSQL view.
The browser/Notion UI should talk to this API, never directly to PostgreSQL.
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Literal

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL", "")
MORPHHB_COMMIT = "3d15126fb1ef74867fc1434be1942e837932691f"

HEBREW_CANTILLATION = re.compile(r"[\u0591-\u05AF]")
HEBREW_METEG = re.compile(r"\u05BD")
BOOK_CODE = re.compile(r"^[1-3]?[A-Za-z]+$")

app = FastAPI(
    title="DTWorks 2 Hebrew Search API",
    version="0.1.0-poc",
    description="SQL-backed Hebrew Bible token search for the 050 proof of concept.",
)

# POC: allow browser embeds from Notion/GitHub Pages. Before public production,
# replace '*' with the exact public site origins and add rate limiting upstream.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
    allow_credentials=False,
)


def normalize_form(value: str) -> str:
    """Match importer Form semantics: keep niqqud, remove accents/meteg."""
    value = unicodedata.normalize("NFD", value.replace("/", ""))
    value = HEBREW_CANTILLATION.sub("", value)
    value = HEBREW_METEG.sub("", value)
    return value.replace("\u200e", "").replace("\u200f", "")


def connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def parse_books(value: str | None) -> list[str]:
    if not value:
        return []
    books = [part.strip() for part in value.split(",") if part.strip()]
    if not books or any(not BOOK_CODE.fullmatch(book) for book in books):
        raise HTTPException(status_code=422, detail="books must be comma-separated OSIS book codes")
    # Stable de-duplication.
    return list(dict.fromkeys(books))


@app.get("/health")
def health():
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) AS tokens FROM dtworks.search_tokens")
            tokens = int(cur.fetchone()["tokens"])
            cur.execute(
                """
                SELECT source_commit
                FROM dtworks.source_versions
                ORDER BY imported_at DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
    except Exception as exc:  # pragma: no cover - exercised by deployment health checks
        raise HTTPException(status_code=503, detail=f"database unavailable: {exc}") from exc

    return {
        "status": "ok",
        "database": "postgresql",
        "tokens": tokens,
        "source_commit": row["source_commit"] if row else None,
        "expected_morphhb_commit": MORPHHB_COMMIT,
    }


@app.get("/books")
def books():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT osis_code AS book, english_name, japanese_name,
                   tanakh_group, canonical_order
            FROM dtworks.books
            ORDER BY canonical_order
            """
        )
        return {"books": cur.fetchall()}


@app.get("/search")
def search(
    strong: int | None = Query(default=None, ge=1),
    form: str | None = Query(default=None, min_length=1, max_length=80),
    stem: str | None = Query(default=None, min_length=1, max_length=1),
    conjugation: str | None = Query(default=None, min_length=1, max_length=1),
    group: Literal["torah", "former", "latter", "writings"] | None = None,
    books: str | None = Query(default=None, description="Comma-separated OSIS codes, e.g. Gen,Exod"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    versification: Literal["wlc", "kjv"] = "wlc",
):
    if strong is None and form is None and stem is None and conjugation is None:
        raise HTTPException(
            status_code=400,
            detail="Specify at least one of strong, form, stem, or conjugation.",
        )

    selected_books = parse_books(books)
    clauses: list[str] = []
    params: list[object] = []

    if strong is not None:
        clauses.append("primary_strong = %s")
        params.append(strong)
    if form is not None:
        clauses.append("form_search = %s")
        params.append(normalize_form(form))
    if stem is not None:
        clauses.append("main_stem_code = %s")
        params.append(stem)
    if conjugation is not None:
        clauses.append("main_conjugation_code = %s")
        params.append(conjugation)
    if group is not None:
        clauses.append("tanakh_group = %s")
        params.append(group)
    if selected_books:
        clauses.append("book = ANY(%s::text[])")
        params.append(selected_books)

    where_sql = " AND ".join(clauses)
    count_sql = f"SELECT count(*) AS total FROM dtworks.search_tokens WHERE {where_sql}"
    rows_sql = f"""
        SELECT book, english_name, japanese_name, tanakh_group, canonical_order,
               chapter_wlc, verse_wlc, osis_wlc,
               chapter_kjv, verse_kjv, osis_kjv,
               token_index, surface, form_search, form_consonantal,
               lemma_raw, primary_strong, lemma_display,
               morph_raw, language_code, main_pos_code,
               main_stem_code, main_conjugation_code,
               person_code, gender_code, number_code, state_code
        FROM dtworks.search_tokens
        WHERE {where_sql}
        ORDER BY canonical_order, chapter_wlc, verse_wlc, token_index
        LIMIT %s OFFSET %s
    """

    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(count_sql, params)
            total = int(cur.fetchone()["total"])
            cur.execute(rows_sql, [*params, limit, offset])
            rows = cur.fetchall()
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="database query failed") from exc

    results = []
    for row in rows:
        item = dict(row)
        item["wlc_ref"] = row["osis_wlc"]
        item["kjv_ref"] = row["osis_kjv"]
        if versification == "kjv" and row["osis_kjv"]:
            item["display_ref"] = row["osis_kjv"]
        else:
            item["display_ref"] = row["osis_wlc"]
        results.append(item)

    return {
        "query": {
            "strong": strong,
            "form": normalize_form(form) if form is not None else None,
            "stem": stem,
            "conjugation": conjugation,
            "group": group,
            "books": selected_books,
            "versification": versification,
        },
        "total": total,
        "limit": limit,
        "offset": offset,
        "results": results,
    }
