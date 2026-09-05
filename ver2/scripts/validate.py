#!/usr/bin/env python3
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schema" / "current.schema.json"


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: validate.py <current.json>")

    input_path = Path(sys.argv[1])
    data = json.loads(input_path.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(data),
        key=lambda e: list(e.path),
    )
    if errors:
        for error in errors:
            location = ".".join(str(p) for p in error.path) or "root"
            print(f"SCHEMA ERROR [{location}]: {error.message}", file=sys.stderr)
        raise SystemExit(1)

    p = data["passage"]
    expected = list(range(p["start_verse"], p["end_verse"] + 1))
    actual = [v["verse"] for v in data["verses"]]
    if actual != expected:
        fail(f"verse range mismatch: expected {expected}, got {actual}")

    for verse in data["verses"]:
        surfaces = [w["surface"] for w in verse["words"]]
        if len(surfaces) != len(set(surfaces)):
            print(f"WARN: verse {verse['verse']} contains repeated surface forms; this is allowed")
        if not all(w["gloss"].strip() for w in verse["words"]):
            fail(f"verse {verse['verse']} contains an empty gloss")

    print(
        f"PASS: schema=2.0 sequence={data['sequence']} passage={p['display']} "
        f"verses={len(data['verses'])}"
    )


if __name__ == "__main__":
    main()
