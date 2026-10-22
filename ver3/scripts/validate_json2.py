"""Read-only preflight of the real JSON2 using the production composer contract.

This verifies structure and identity, not the Work-owned semantic quality audit.
It never generates or changes JSON1, HTML, audio, or Notion content.
"""
import json
import sys
from pathlib import Path

from compose import validate
from prepare import compact, digest


def main():
    run = Path(sys.argv[1])
    j = json.loads((run / 'json1.json').read_text(encoding='utf-8'))
    j11 = json.loads((run / 'json1.1.json').read_text(encoding='utf-8'))
    c = json.loads((run / 'json2.json').read_text(encoding='utf-8'))
    assert j11 == compact(j), 'JSON1.1 differs from the immutable JSON1 export'
    validate(j, c)
    print(f'STRUCTURE_PASS: {len(c["verses"])} verses; JSON1.1 SHA256={digest(j11)}')
    print('Semantic quality is not certified by this command; Work must audit it separately.')


if __name__ == '__main__':
    main()
