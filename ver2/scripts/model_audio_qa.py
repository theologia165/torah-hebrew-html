#!/usr/bin/env python3
import difflib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

def fail(msg: str):
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)

def hebrew_letters(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in text if "HEBREW LETTER" in unicodedata.name(ch, ""))

def token_letters(text: str):
    out=[]
    for raw in re.split(r"\s+", text.strip()):
        t=hebrew_letters(raw)
        if t:
            out.append(t)
    return out

def ratio(a: str,b: str)->float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None,a,b).ratio()

def best_token_ratio(expected: str, observed_tokens)->float:
    if not expected or not observed_tokens:
        return 0.0
    return max(ratio(expected,t) for t in observed_tokens)

def main():
    if len(sys.argv)!=3:
        fail("usage: model_audio_qa.py <enriched.json> <audio-output-dir>")
    data=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out=Path(sys.argv[2])
    manifest_path=out/"audio_manifest.json"
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    qa=manifest.setdefault("qa",{})
    required_refs=list(qa.get("model_audio_required_refs") or [])
    if not qa.get("model_audio_required") or not required_refs:
        print("SKIP: deterministic audio QA found no anomaly; MODEL_AUDIO is not required")
        return 0

    key=os.environ.get("OPENAI_API_KEY","").strip()
    if not key:
        fail("MODEL_AUDIO insurance is required for anomaly refs, but OPENAI_API_KEY is not configured")

    from openai import OpenAI
    client=OpenAI(api_key=key)

    verses=data["verses"]
    by_ref={f"{int(v.get('chapter',data['passage']['chapter']))}:{int(v['verse'])}":(i,v) for i,v in enumerate(verses)}
    manifest_by_ref={v["ref"]:v for v in manifest.get("verses",[])}

    results=[]
    all_pass=True
    for ref in required_refs:
        if ref not in by_ref or ref not in manifest_by_ref:
            fail(f"MODEL_AUDIO required ref missing from data/manifest: {ref}")
        i,verse=by_ref[ref]
        rec=manifest_by_ref[ref]
        audio=out/rec["r2"]
        if not audio.exists():
            fail(f"verse {ref}: r2 audio missing")

        with audio.open("rb") as f:
            transcript_obj=client.audio.transcriptions.create(
                model="gpt-transcribe",
                file=f,
                language="he",
                prompt=(
                    "This is a Torah cantillation recording in Biblical Hebrew. "
                    "Transcribe only the Hebrew that is audibly present. Do not infer or add missing words."
                ),
                response_format="text",
            )
        transcript=transcript_obj if isinstance(transcript_obj,str) else getattr(transcript_obj,"text",str(transcript_obj))

        expected_all=hebrew_letters(verse["hebrew"])
        observed_all=hebrew_letters(transcript)
        expected_tokens=[hebrew_letters(w["surface"]) for w in verse["words"]]
        observed_tokens=token_letters(transcript)
        first_expected=expected_tokens[0]
        last_expected=expected_tokens[-1]
        overall=ratio(expected_all,observed_all)
        first_score=best_token_ratio(first_expected,observed_tokens[:4])
        last_score=best_token_ratio(last_expected,observed_tokens[-4:])

        prev_last=None
        next_first=None
        prev_intrusion=0.0
        next_intrusion=0.0
        if i>0:
            prev_last=hebrew_letters(verses[i-1]["words"][-1]["surface"])
            prev_intrusion=best_token_ratio(prev_last,observed_tokens[:2])
        if i+1<len(verses):
            next_first=hebrew_letters(verses[i+1]["words"][0]["surface"])
            next_intrusion=best_token_ratio(next_first,observed_tokens[-2:])

        verse_pass=(
            overall>=0.62
            and first_score>=0.58
            and last_score>=0.58
            and prev_intrusion<0.94
            and next_intrusion<0.94
        )
        all_pass=all_pass and verse_pass
        results.append({
            "ref":ref,
            "audio_file":audio.name,
            "trigger_reasons":rec.get("model_audio_reasons",[]),
            "transcript":transcript,
            "expected_consonants":expected_all,
            "observed_consonants":observed_all,
            "overall_similarity":overall,
            "first_expected":first_expected,
            "first_score":first_score,
            "last_expected":last_expected,
            "last_score":last_score,
            "previous_last_expected":prev_last,
            "previous_word_intrusion_score":prev_intrusion,
            "next_first_expected":next_first,
            "next_word_intrusion_score":next_intrusion,
            "pass":verse_pass,
        })
        print(
            f"MODEL_AUDIO ref={ref} pass={verse_pass} overall={overall:.3f} "
            f"first={first_score:.3f} last={last_score:.3f} "
            f"prev_intrusion={prev_intrusion:.3f} next_intrusion={next_intrusion:.3f}"
        )

    report={
        "model":"gpt-transcribe",
        "audio_revision":"r2",
        "scope":"anomaly refs only",
        "required_refs":required_refs,
        "method":"delivered r2 transcription + consonantal similarity + first/last word + adjacent-word intrusion checks",
        "pass":all_pass,
        "verses":results,
    }
    (out/"model_audio_qa.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    qa["MODEL_AUDIO_CHECKED"]=bool(all_pass)
    qa["model_audio_model"]="gpt-transcribe"
    qa["model_audio_revision"]="r2"
    qa["model_audio_report"]="model_audio_qa.json"
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    if not all_pass:
        bad=[x["ref"] for x in results if not x["pass"]]
        fail("MODEL_AUDIO failed refs="+",".join(bad))
    print(f"PASS: MODEL_AUDIO insurance refs={len(results)} model=gpt-transcribe revision=r2")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
