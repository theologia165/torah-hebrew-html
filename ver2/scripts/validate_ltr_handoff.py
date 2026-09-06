#!/usr/bin/env python3
"""Fail semantic handoff when mixed Japanese/Hebrew prose starts with Hebrew.

Hebrew-only source lines are allowed. The guard applies to Japanese prose fields that
contain Hebrew and Japanese on the same rendered line. Starting such a line with a
Hebrew character can make downstream Notion rich-text inherit RTL paragraph direction.

The fix belongs in the semantic source: prefix the sentence with natural Japanese such
as 「ヘブライ語の 」 rather than normalizing or rewriting the Hebrew text downstream.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

HEBREW_START = re.compile(r"^[\u0590-\u05FF\uFB1D-\uFB4F]")
JAPANESE = re.compile(r"[\u3040-\u30FF\u3400-\u9FFF]")

# Markdown markers that do not count as the first visible content character.
BLOCK_PREFIXES = (
    re.compile(r"^>\s*"),
    re.compile(r"^#{1,6}\s+"),
    re.compile(r"^(?:[-+*])\s+"),
    re.compile(r"^\d+[.)]\s+"),
)
INLINE_OPENERS = re.compile(r"^(?:\*\*|__|~~|`+|\*|_)+")


def first_visible_content(line: str) -> str:
    """Return a line with leading whitespace/Markdown decoration removed."""
    s = line.lstrip()
    changed = True
    while s and changed:
        changed = False
        for pattern in BLOCK_PREFIXES:
            new = pattern.sub("", s, count=1)
            if new != s:
                s = new.lstrip()
                changed = True
                break
    s = INLINE_OPENERS.sub("", s).lstrip()
    return s


def mixed_line_starts_hebrew(line: str) -> bool:
    visible = first_visible_content(line)
    return bool(visible and HEBREW_START.search(visible) and JAPANESE.search(visible))


def check_text(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value:
        return
    for line_no, line in enumerate(value.splitlines(), start=1):
        if not line.strip() or not mixed_line_starts_hebrew(line):
            continue
        visible = first_visible_content(line)
        snippet = visible.replace("\t", " ")[:90]
        errors.append(
            f"{path}:line{line_no}: mixed Japanese/Hebrew prose begins with Hebrew: {snippet!r}"
        )


def check_current(data: dict[str, Any], errors: list[str]) -> None:
    check_text(data.get("summary"), "current.summary", errors)
    verses = data.get("verses", [])
    if not isinstance(verses, list):
        return
    for verse in verses:
        if not isinstance(verse, dict):
            continue
        ref = verse.get("verse", "?")
        for field in ("translation", "short_commentary", "detailed_commentary"):
            check_text(verse.get(field), f"current.verses[{ref}].{field}", errors)


def check_commentary(data: dict[str, Any], errors: list[str]) -> None:
    check_text(data.get("summary"), "commentary.summary", errors)
    verses = data.get("verses", {})
    if isinstance(verses, dict):
        iterator = verses.items()
    elif isinstance(verses, list):
        iterator = ((str(v.get("verse", "?")), v) for v in verses if isinstance(v, dict))
    else:
        return
    for ref, verse in iterator:
        if not isinstance(verse, dict):
            continue
        for field in ("translation", "short_commentary", "detailed_commentary"):
            check_text(verse.get(field), f"commentary.verses[{ref}].{field}", errors)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise SystemExit(f"FAIL LTR semantic handoff: top-level JSON must be an object: {path}")
    return value


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "usage: validate_ltr_handoff.py ver2/input/current.json "
            "ver2/content/NNN-commentary.json",
            file=sys.stderr,
        )
        return 2

    current_path = Path(sys.argv[1])
    commentary_path = Path(sys.argv[2])
    if not current_path.is_file():
        print(f"FAIL LTR semantic handoff: missing {current_path}", file=sys.stderr)
        return 2
    if not commentary_path.is_file():
        print(f"FAIL LTR semantic handoff: missing {commentary_path}", file=sys.stderr)
        return 2

    current = load_json(current_path)
    commentary = load_json(commentary_path)
    errors: list[str] = []
    check_current(current, errors)
    check_commentary(commentary, errors)

    if errors:
        print("FAIL LTR semantic handoff:", file=sys.stderr)
        for error in errors:
            print(f" - {error}", file=sys.stderr)
        print(
            "Fix the semantic source so mixed Japanese/Hebrew prose begins with Japanese/ASCII "
            "(for example, prefix naturally with 'ヘブライ語の '). Hebrew-only source lines remain RTL and are allowed.",
            file=sys.stderr,
        )
        return 1

    print("PASS: semantic handoff LTR safety (mixed Japanese/Hebrew prose does not begin with Hebrew)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
