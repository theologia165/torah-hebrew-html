#!/usr/bin/env python3
import json
import sys
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schema" / "current.schema.json"
def fail(message):
    print(f"FAIL: {message}", file=sys.stderr); raise SystemExit(1)
def main():
    if len(sys.argv)!=2: fail("usage: validate.py <current.json>")
    data=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")); schema=json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors=sorted(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(data),key=lambda e:list(e.path))
    if errors:
        for error in errors:
            location=".".join(str(p) for p in error.path) or "root"; print(f"SCHEMA ERROR [{location}]: {error.message}",file=sys.stderr)
        raise SystemExit(1)
    p=data["passage"]; start_ch=int(p["chapter"]); end_ch=int(p.get("end_chapter",start_ch))
    actual=[(int(v.get("chapter",start_ch)),int(v["verse"])) for v in data["verses"]]
    if not actual or actual[0]!=(start_ch,int(p["start_verse"])) or actual[-1]!=(end_ch,int(p["end_verse"])):
        fail(f"range endpoints mismatch: expected {(start_ch,p['start_verse'])}..{(end_ch,p['end_verse'])}, got {actual[0] if actual else None}..{actual[-1] if actual else None}")
    for a,b in zip(actual,actual[1:]):
        if b[0]<a[0] or (b[0]==a[0] and b[1]!=a[1]+1) or b[0]>a[0]+1:
            fail(f"non-contiguous/unsorted verse refs: {a} -> {b}")
        if b[0]==a[0]+1 and b[1]!=1:
            fail(f"new chapter must begin at verse 1: {a} -> {b}")
    for verse in data["verses"]:
        ch=int(verse.get("chapter",start_ch)); n=int(verse["verse"])
        if not all(w["gloss"].strip() for w in verse["words"]):fail(f"verse {ch}:{n} contains an empty gloss")
        reconstructed="".join(w["surface"]+w["separator_after"] for w in verse["words"])
        if reconstructed!=verse["hebrew"]:fail(f"verse {ch}:{n} WLC reconstruction mismatch\nMASTER: {verse['hebrew']}\nTOKENS: {reconstructed}")
        if verse["words"][-1]["separator_after"]!="׃":fail(f"verse {ch}:{n} must end with sof pasuq")
    print(f"PASS: schema=2.0 sequence={data['sequence']} passage={p['display']} verses={len(data['verses'])} exact_wlc_reconstruction=PASS")
if __name__=="__main__":main()
