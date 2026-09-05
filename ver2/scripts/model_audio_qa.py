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
    out = []
    for raw in re.split(r"\s+", text.strip()):
        t = hebrew_letters(raw)
        if t:
            out.append(t)
    return out


def ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def best_token_ratio(expected: str, observed_tokens) -> float:
    if not expected or not observed_tokens:
        return 0.0
    return max(ratio(expected, t) for t in observed_tokens)


def main():
    if len(sys.argv) != 3:
        fail("usage: model_audio_qa.py <enriched.json> <audio-output-dir>")
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        print("PENDING: OPENAI_API_KEY is not configured; MODEL_AUDIO remains false")
        return 0

    from openai import OpenAI

    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    manifest_path = out / "audio_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    client = OpenAI(api_key=key)

    results = []
    all_pass = True
    verses = data["verses"]
    for i, verse in enumerate(verses):
        n = verse["verse"]
        # QA the actual file delivered to the learner, not only the source-speed
        # split. Deterministic checks already validate r1 and the r1->r2 timing.
        audio = out / f"{data['sequence']}_{n}_r2.mp3"
        if not audio.exists():
            fail(f"verse {n}: r2 audio missing")

        with audio.open("rb") as f:
            transcript_obj = client.audio.transcriptions.create(
                model="gpt-transcribe",
                file=f,
                language="he",
                prompt=(
                    "This is a Torah cantillation recording in Biblical Hebrew. "
                    "Transcribe only the Hebrew that is audibly present. Do not infer or add missing words."
                ),
                response_format="text",
            )
        transcript = transcript_obj if isinstance(transcript_obj, str) else getattr(transcript_obj, "text", str(transcript_obj))

        expected_all = hebrew_letters(verse["hebrew"])
        observed_all = hebrew_letters(transcript)
        expected_tokens = [hebrew_letters(w["surface"]) for w in verse["words"]]
        observed_tokens = token_letters(transcript)
        first_expected = expected_tokens[0]
        last_expected = expected_tokens[-1]
        overall = ratio(expected_all, observed_all)
        first_score = best_token_ratio(first_expected, observed_tokens[:4])
        last_score = best_token_ratio(last_expected, observed_tokens[-4:])

        prev_last = None
        next_first = None
        prev_intrusion = 0.0
        next_intrusion = 0.0
        if i > 0:
            prev_last = hebrew_letters(verses[i-1]["words"][-1]["surface"])
            prev_intrusion = best_token_ratio(prev_last, observed_tokens[:2])
        if i + 1 < len(verses):
            next_first = hebrew_letters(verses[i+1]["words"][0]["surface"])
            next_intrusion = best_token_ratio(next_first, observed_tokens[-2:])

        verse_pass = (
            overall >= 0.62
            and first_score >= 0.58
            and last_score >= 0.58
            and prev_intrusion < 0.94
            and next_intrusion < 0.94
        )
        all_pass = all_pass and verse_pass
        results.append({
            "verse": n,
            "audio_file": audio.name,
            "transcript": transcript,
            "expected_consonants": expected_all,
            "observed_consonants": observed_all,
            "overall_similarity": overall,
            "first_expected": first_expected,
            "first_score": first_score,
            "last_expected": last_expected,
            "last_score": last_score,
            "previous_last_expected": prev_last,
            "previous_word_intrusion_score": prev_intrusion,
            "next_first_expected": next_first,
            "next_word_intrusion_score": next_intrusion,
            "pass": verse_pass,
        })
        print(
            f"MODEL_AUDIO verse={n} pass={verse_pass} overall={overall:.3f} "
            f"first={first_score:.3f} last={last_score:.3f} "
            f"prev_intrusion={prev_intrusion:.3f} next_intrusion={next_intrusion:.3f}"
        )

    report = {
        "model": "gpt-transcribe",
        "audio_revision": "r2",
        "method": "delivered r2 full-verse transcription + consonantal similarity + first/last word + adjacent-word intrusion checks",
        "pass": all_pass,
        "verses": results,
    }
    (out / "model_audio_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest["qa"]["MODEL_AUDIO_CHECKED"] = bool(all_pass)
    manifest["qa"]["model_audio_model"] = "gpt-transcribe"
    manifest["qa"]["model_audio_revision"] = "r2"
    manifest["qa"]["model_audio_report"] = "model_audio_qa.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not all_pass:
        bad = [str(x["verse"]) for x in results if not x["pass"]]
        fail("MODEL_AUDIO failed verses=" + ",".join(bad))
    print(f"PASS: MODEL_AUDIO verses={len(results)} model=gpt-transcribe revision=r2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
