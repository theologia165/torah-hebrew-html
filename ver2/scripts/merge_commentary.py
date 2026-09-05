#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def fail(msg):
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def main():
    if len(sys.argv) != 3:
        fail("usage: merge_commentary.py <enriched.json> <commentary.json>")
    enriched_path = Path(sys.argv[1])
    commentary_path = Path(sys.argv[2])
    data = json.loads(enriched_path.read_text(encoding="utf-8"))
    if not commentary_path.exists():
        print(f"SKIP: commentary file not found: {commentary_path}")
        return
    c = json.loads(commentary_path.read_text(encoding="utf-8"))
    if str(c.get("sequence")) != str(data.get("sequence")):
        fail(f"sequence mismatch commentary={c.get('sequence')} data={data.get('sequence')}")
    by_verse = c.get("verses", {})
    expected = {str(v["verse"]) for v in data["verses"]}
    actual = set(by_verse.keys())
    if expected != actual:
        fail(f"commentary verse coverage mismatch missing={sorted(expected-actual)} extra={sorted(actual-expected)}")
    for verse in data["verses"]:
        item = by_verse[str(verse["verse"])]
        short = item.get("short_commentary", "").strip()
        detailed = item.get("detailed_commentary", "").strip()
        if not short or not detailed:
            fail(f"verse {verse['verse']}: empty commentary")
        if "構造展開試験" in short or "本番用の節固有解説" in detailed:
            fail(f"verse {verse['verse']}: placeholder commentary remains")
        verse["short_commentary"] = short
        verse["detailed_commentary"] = detailed
    data.setdefault("content_provenance", {})["commentary_file"] = str(commentary_path)
    data["content_provenance"]["commentary_status"] = c.get("status", "unknown")
    enriched_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: merged researched commentary verses={len(data['verses'])}")


if __name__ == "__main__":
    main()
