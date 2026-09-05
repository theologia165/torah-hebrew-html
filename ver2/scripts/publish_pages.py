#!/usr/bin/env python3
import json, shutil, sys
from pathlib import Path


def choose_destination(src: Path, dest_dir: Path):
    base = dest_dir / src.name
    if not base.exists():
        return base, "new"
    if src.read_bytes() == base.read_bytes():
        return base, "reuse"
    stem = src.stem
    n = 2
    while True:
        candidate = dest_dir / f"{stem}-r{n}{src.suffix}"
        if not candidate.exists():
            return candidate, "revision"
        if src.read_bytes() == candidate.read_bytes():
            return candidate, "reuse_revision"
        n += 1


def main():
    if len(sys.argv) != 6:
        raise SystemExit("usage: publish_pages.py enriched_json src_dir pages_checkout pages_base manifest_path")
    enriched_path, src_dir, pages_checkout, pages_base, manifest_path = map(Path, sys.argv[1:5]) + (None,)

if __name__ == "__main__":
    pass
