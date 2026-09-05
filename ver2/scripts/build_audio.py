#!/usr/bin/env python3
import json
import math
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

POCKETTORAH_SHA = "8a23287221dd535966ee9914de9a03e71769a469"
BASE_RAW = f"https://raw.githubusercontent.com/rneiss/PocketTorah/{POCKETTORAH_SHA}"
ALIYAH_URL = f"{BASE_RAW}/data/aliyah.json"
TARGET_WPS = 0.79306
SILENCE_NOISE_DB = -38
SILENCE_MIN_D = 0.08
BOUNDARY_WINDOW = 1.25


def fail(msg: str):
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def get_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "asaichi-torah-ver2"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def run(cmd):
    p = subprocess.run(cmd, text=True, capture_output=True)
    if p.returncode != 0:
        fail(f"command failed: {' '.join(cmd)}\n{p.stderr}")
    return p


def ffprobe_duration(path: Path) -> float:
    p = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nokey=1:noprint_wrappers=1", str(path)
    ])
    return float(p.stdout.strip())


def mean_volume_db(path: Path) -> float:
    p = subprocess.run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-af", "volumedetect", "-f", "null", "-"
    ], text=True, capture_output=True)
    text = p.stderr
    m = re.search(r"mean_volume:\s*(-?[0-9.]+) dB", text)
    return float(m.group(1)) if m else -999.0


def detect_silences(path: Path):
    p = subprocess.run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-af", f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_D}",
        "-f", "null", "-"
    ], text=True, capture_output=True)
    starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", p.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", p.stderr)]
    out = []
    for i, st in enumerate(starts):
        en = ends[i] if i < len(ends) else None
        if en is not None and en >= st:
            out.append((st, en))
    return out


def choose_boundary(candidate: float, silences):
    # Existing rule: labels guide; real signal decides. Prefer the end side of a
    # real pause, but never cross the next-word onset candidate.
    eligible = []
    for st, en in silences:
        if en < candidate - BOUNDARY_WINDOW or st > candidate + 0.08:
            continue
        boundary = min(en, candidate)
        if boundary >= candidate - BOUNDARY_WINDOW:
            eligible.append((abs(candidate - boundary), boundary, st, en))
    if not eligible:
        return candidate, "label_onset", None
    _, boundary, st, en = min(eligible, key=lambda x: x[0])
    return boundary, "signal_pause_end", {"silence_start": st, "silence_end": en}


def parse_ref(s: str):
    a, b = s.split(":")
    return int(a), int(b)


def resolve_source(data):
    raw = get_bytes(ALIYAH_URL).decode("utf-8-sig")
    aliyah = json.loads(raw)
    p = data["passage"]
    begin = f"{p['chapter']}:{p['start_verse']}"
    end = f"{p['chapter']}:{p['end_verse']}"
    matches = []
    for parsha in aliyah["parshiot"]["parsha"]:
        for a in parsha.get("fullkriyah", {}).get("aliyah", []):
            if a.get("_begin") == begin and a.get("_end") == end and a.get("_num") != "M":
                matches.append((parsha["_id"], a["_num"]))
    if len(matches) != 1:
        fail(f"PocketTorah aliyah mapping expected 1 match for {begin}-{end}, got {matches}")
    parsha, num = matches[0]
    base = f"{parsha}-{num}"
    return {
        "parsha": parsha,
        "aliyah": num,
        "base": base,
        "audio_url": f"{BASE_RAW}/data/audio/{base}.mp3",
        "labels_url": f"{BASE_RAW}/data/torah/labels/{base}.txt"
    }


def split_mp3(source: Path, start: float, end: float, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source),
        "-af", f"atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS",
        "-c:a", "libmp3lame", "-q:a", "2", str(out)
    ])


def atempo_chain(factor: float) -> str:
    # ffmpeg supports a broad range today, but decomposing keeps behavior stable.
    if factor <= 0:
        fail(f"invalid atempo {factor}")
    parts = []
    x = factor
    while x < 0.5:
        parts.append(0.5)
        x /= 0.5
    while x > 2.0:
        parts.append(2.0)
        x /= 2.0
    parts.append(x)
    return ",".join(f"atempo={v:.9f}" for v in parts)


def speed_mp3(src: Path, factor: float, out: Path):
    run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src), "-af", atempo_chain(factor),
        "-c:a", "libmp3lame", "-q:a", "2", str(out)
    ])


def main():
    if len(sys.argv) != 3:
        fail("usage: build_audio.py <enriched.json> <audio-output-dir>")
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)

    source_meta = resolve_source(data)
    source = out / f"{source_meta['base']}_source.mp3"
    source.write_bytes(get_bytes(source_meta["audio_url"]))
    labels_text = get_bytes(source_meta["labels_url"]).decode("utf-8-sig").strip()
    labels = [float(x) for x in labels_text.split(",") if x.strip()]

    word_counts = [len(v["words"]) for v in data["verses"]]
    total_words = sum(word_counts)
    if len(labels) not in (total_words, total_words + 1):
        fail(f"MAPPING: label count {len(labels)} incompatible with word count {total_words}")

    source_duration = ffprobe_duration(source)
    if len(labels) == total_words + 1 and labels[-1] <= source_duration + 0.25:
        word_onsets = labels[:-1]
        explicit_end = labels[-1]
    else:
        word_onsets = labels[:total_words]
        explicit_end = source_duration
    if len(word_onsets) != total_words:
        fail("MAPPING: could not normalize PocketTorah label count")

    silences = detect_silences(source)
    cumulative = [0]
    for n in word_counts:
        cumulative.append(cumulative[-1] + n)

    boundaries = []
    for i in range(len(data["verses"]) + 1):
        if i == 0:
            candidate = word_onsets[0]
            boundaries.append({"candidate": candidate, "refined": candidate, "method": "first_word_onset"})
        elif i == len(data["verses"]):
            boundaries.append({"candidate": explicit_end, "refined": explicit_end, "method": "source_end"})
        else:
            candidate = word_onsets[cumulative[i]]
            refined, method, signal = choose_boundary(candidate, silences)
            rec = {"candidate": candidate, "refined": refined, "method": method}
            if signal:
                rec["signal"] = signal
            boundaries.append(rec)

    for i in range(1, len(boundaries)):
        if boundaries[i]["refined"] <= boundaries[i-1]["refined"]:
            fail(f"SIGNAL: non-monotonic boundary {i}")

    seq = data["sequence"]
    verse_records = []
    for i, verse in enumerate(data["verses"]):
        n = verse["verse"]
        start = boundaries[i]["refined"]
        end = boundaries[i+1]["refined"]
        if end - start < 0.4:
            fail(f"SIGNAL: verse {n} boundary duration too short: {end-start:.3f}s")

        r1 = out / f"{seq}_{n}_r1.mp3"
        r2 = out / f"{seq}_{n}_r2.mp3"
        split_mp3(source, start, end, r1)
        dur1 = ffprobe_duration(r1)
        if dur1 <= 0:
            fail(f"SIGNAL: verse {n} r1 duration invalid")
        source_wps = len(verse["words"]) / dur1
        factor = TARGET_WPS / source_wps
        if not (0.25 <= factor <= 4.0):
            fail(f"SPEED: verse {n} unreasonable atempo={factor:.6f}")
        speed_mp3(r1, factor, r2)
        dur2 = ffprobe_duration(r2)
        theoretical = dur1 / factor
        corrected_wps = len(verse["words"]) / dur2
        mean_db = mean_volume_db(r1)
        if mean_db < -55.0:
            fail(f"SIGNAL: verse {n} mean volume too low: {mean_db:.2f} dB")

        verse_records.append({
            "verse": n,
            "word_count": len(verse["words"]),
            "boundary_start": start,
            "boundary_end": end,
            "boundary_start_meta": boundaries[i],
            "boundary_end_meta": boundaries[i+1],
            "r1": r1.name,
            "r1_duration": dur1,
            "source_wps": source_wps,
            "target_wps": TARGET_WPS,
            "atempo": factor,
            "r2": r2.name,
            "r2_duration": dur2,
            "r2_theoretical_duration": theoretical,
            "r2_duration_error": abs(dur2 - theoretical),
            "r2_wps": corrected_wps,
            "mean_volume_db": mean_db
        })

    manifest = {
        "schema_version": "audio-1.0",
        "sequence": seq,
        "passage": data["passage"],
        "source": {
            **source_meta,
            "pockettorah_commit": POCKETTORAH_SHA,
            "source_file": source.name,
            "source_duration": source_duration,
            "label_count": len(labels),
            "word_count": total_words
        },
        "qa": {
            "MAPPING_CONFIRMED": True,
            "SIGNAL_CHECKED": True,
            "MODEL_AUDIO_CHECKED": False,
            "target_wps": TARGET_WPS,
            "boundary_rule": "PocketTorah word-onset labels are candidates; prefer verified signal pause end without crossing next-word onset"
        },
        "verses": verse_records
    }
    (out / "audio_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: AUDIO build verses={len(verse_records)} words={total_words} source={source_meta['base']} target_wps={TARGET_WPS}")


if __name__ == "__main__":
    main()
