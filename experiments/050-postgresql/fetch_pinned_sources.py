#!/usr/bin/env python3
"""Fetch and XML-validate the pinned MorphHB and OSHB lexicon sources."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from import_morphhb import BOOK_CODES, MORPHHB_COMMIT, RAW_BASE

LEXICON_COMMIT = "21c9add13bc727d3a951361778e97e3ff7afd1ce"
LEXICON_RAW = f"https://raw.githubusercontent.com/openscriptures/HebrewLexicon/{LEXICON_COMMIT}"
LEXICON_FILES = ("AugIndex.xml", "LexicalIndex.xml", "HebrewStrong.xml")


def fetch_one(url: str, destination: Path) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "Nishihara-Midrash-Lab-DTWorks2/source-fetch"})
    last_error: Exception | None = None
    for _ in range(4):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read()
            ET.fromstring(data)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            return {"file": destination.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        except Exception as error:  # retry transient network/truncated XML failures
            last_error = error
    raise RuntimeError(f"failed to fetch valid XML from {url}: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--morphhb-dir", type=Path, required=True)
    parser.add_argument("--lexicon-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    jobs = [
        (f"{RAW_BASE}/{name}", args.morphhb_dir / name)
        for name in (*[f"{book}.xml" for book in BOOK_CODES], "VerseMap.xml")
    ] + [
        (f"{LEXICON_RAW}/{name}", args.lexicon_dir / name)
        for name in LEXICON_FILES
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        files = list(pool.map(lambda item: fetch_one(*item), jobs))
    files.sort(key=lambda row: row["file"])
    manifest = {
        "ok": True,
        "morphhb_commit": MORPHHB_COMMIT,
        "lexicon_commit": LEXICON_COMMIT,
        "book_count": len(BOOK_CODES),
        "xml_file_count": len(files),
        "files": files,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("ok", "morphhb_commit", "lexicon_commit", "book_count", "xml_file_count")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
