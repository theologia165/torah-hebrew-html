#!/usr/bin/env python3
import json, shutil, sys
from pathlib import Path


def choose_destination(src: Path, dest_dir: Path):
    base = dest_dir / src.name
    src_bytes = src.read_bytes()
    if not base.exists():
        return base, "new"
    if src_bytes == base.read_bytes():
        return base, "reuse"
    stem = src.stem
    n = 2
    while True:
        candidate = dest_dir / f"{stem}-r{n}{src.suffix}"
        if not candidate.exists():
            return candidate, "revision"
        if src_bytes == candidate.read_bytes():
            return candidate, "reuse_revision"
        n += 1


def main():
    if len(sys.argv) not in (6, 7):
        raise SystemExit("usage: publish_pages.py enriched_json src_dir pages_checkout pages_base manifest_path [notion_route_json]")

    enriched_path = Path(sys.argv[1])
    src_dir = Path(sys.argv[2])
    pages_checkout = Path(sys.argv[3])
    pages_base = sys.argv[4].rstrip("/")
    manifest_path = Path(sys.argv[5])
    route_path = Path(sys.argv[6]) if len(sys.argv) == 7 else None

    data = json.loads(enriched_path.read_text(encoding="utf-8"))
    seq = data["sequence"]
    chapter = int(data["passage"]["chapter"])
    fallback_only = None
    if route_path:
        route = json.loads(route_path.read_text(encoding="utf-8"))
        fallback_only = {int(v) for v in route.get("fallback_needed", [])}

    dest_dir = pages_checkout / seq
    if fallback_only:
        dest_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    for verse_obj in data["verses"]:
        verse = int(verse_obj["verse"])
        if fallback_only is not None and verse not in fallback_only:
            continue
        expected = src_dir / f"genesis-{chapter}-{verse}.html"
        if not expected.exists():
            raise SystemExit(f"missing generated HTML: {expected}")
        dest, action = choose_destination(expected, dest_dir)
        if action in {"new", "revision"}:
            shutil.copy2(expected, dest)
        entries.append({
            "verse": verse,
            "source": str(expected),
            "filename": dest.name,
            "url": f"{pages_base}/{seq}/{dest.name}",
            "action": action
        })

    manifest = {
        "sequence": seq,
        "chapter": chapter,
        "pages_base_url": pages_base,
        "fallback_only": sorted(fallback_only) if fallback_only is not None else None,
        "entries": entries
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
