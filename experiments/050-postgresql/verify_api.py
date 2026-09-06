#!/usr/bin/env python3
"""Verify the running DTWorks FastAPI service against the Genesis POC database."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def get(path: str, params: dict | None = None, origin: str | None = None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    if origin:
        req.add_header("Origin", origin)
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.status, dict(response.headers), json.loads(response.read().decode("utf-8"))


status, headers, health = get("/health")
assert status == 200, health
assert health["status"] == "ok", health
assert health["tokens"] == 20629, health
assert health["source_commit"] == health["expected_morphhb_commit"], health
print("health OK:", health)

status, headers, data = get(
    "/search",
    {
        "strong": 7971,
        "stem": "q",
        "conjugation": "w",
        "books": "Gen",
        "limit": 100,
    },
    origin="https://www.notion.so",
)
assert status == 200, data
assert data["total"] == 15, data["total"]
assert any(
    row["osis_wlc"] == "Gen.32.4"
    and row["primary_strong"] == 7971
    and row["main_stem_code"] == "q"
    and row["main_conjugation_code"] == "w"
    for row in data["results"]
), data
assert headers.get("Access-Control-Allow-Origin") == "*", headers
print("lemma + Qal + wayyiqtol API search OK: total=15; Gen.32.4 included")

status, _, form_data = get(
    "/search",
    {
        "form": "וַיִּשְׁלַ֨ח",
        "books": "Gen",
        "limit": 100,
    },
)
assert status == 200, form_data
assert form_data["total"] >= 1, form_data
assert any(row["osis_wlc"] == "Gen.32.4" for row in form_data["results"]), form_data
print("Form normalization API search OK: Gen.32.4 included")

status, _, morph_data = get(
    "/search",
    {"stem": "q", "conjugation": "w", "books": "Gen", "limit": 5},
)
assert status == 200, morph_data
assert morph_data["total"] > 100, morph_data["total"]
assert len(morph_data["results"]) == 5, len(morph_data["results"])
print("morphology-only API search OK; pagination/limit OK")

status, _, books_data = get("/books")
assert status == 200, books_data
assert len(books_data["books"]) == 39, len(books_data["books"])
assert books_data["books"][0]["book"] == "Gen", books_data["books"][0]
print("book metadata API OK: 39 books")

try:
    get("/search", {"books": "Gen"})
except urllib.error.HTTPError as exc:
    assert exc.code == 400, exc.code
    error = json.loads(exc.read().decode("utf-8"))
    assert "at least one" in error["detail"], error
    print("empty-search guard OK: HTTP 400")
else:
    raise AssertionError("search without a search condition should fail")

print("DTWorks FastAPI POC contract: PASS")
