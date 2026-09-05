#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path

TARGET_WPS = 0.79306
MAX_DURATION_ERROR = 0.052
MAX_WPS_ERROR = 0.0035


def fail(msg):
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def probe(path: Path) -> float:
    p = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nokey=1:noprint_wrappers=1", str(path)
    ], text=True, capture_output=True)
    if p.returncode != 0:
        fail(f"ffprobe failed for {path}: {p.stderr}")
    return float(p.stdout.strip())


def main():
    if len(sys.argv) != 2:
        fail("usage: verify_audio.py <audio-output-dir>")
    out = Path(sys.argv[1])
    manifest_path = out / "audio_manifest.json"
    if not manifest_path.exists():
        fail("audio_manifest.json missing")
    m = json.loads(manifest_path.read_text(encoding="utf-8"))

    qa = m.get("qa", {})
    if qa.get("MAPPING_CONFIRMED") is not True:
        fail("MAPPING_CONFIRMED is not true")
    if qa.get("SIGNAL_CHECKED") is not True:
        fail("SIGNAL_CHECKED is not true")
    if qa.get("MODEL_AUDIO_CHECKED") is not False:
        fail("MODEL_AUDIO_CHECKED must remain false until model/listening QA exists")

    verses = m.get("verses", [])
    p = m["passage"]
    expected = list(range(p["start_verse"], p["end_verse"] + 1))
    actual = [v["verse"] for v in verses]
    if actual != expected:
        fail(f"verse coverage mismatch: {actual} != {expected}")

    previous_end = None
    for v in verses:
        n = v["verse"]
        for key in ("r1", "r2"):
            path = out / v[key]
            if not path.exists() or path.stat().st_size < 1000:
                fail(f"verse {n}: missing/tiny {key} file")
        d1 = probe(out / v["r1"])
        d2 = probe(out / v["r2"])
        if abs(d1 - v["r1_duration"]) > 0.01:
            fail(f"verse {n}: r1 manifest duration drift")
        if abs(d2 - v["r2_duration"]) > 0.01:
            fail(f"verse {n}: r2 manifest duration drift")
        if v["r2_duration_error"] > MAX_DURATION_ERROR:
            fail(f"verse {n}: corrected duration error {v['r2_duration_error']:.6f}s > {MAX_DURATION_ERROR}")
        if abs(v["r2_wps"] - TARGET_WPS) > MAX_WPS_ERROR:
            fail(f"verse {n}: r2 WPS {v['r2_wps']:.6f} outside target {TARGET_WPS}")
        if not (0.25 <= v["atempo"] <= 4.0):
            fail(f"verse {n}: atempo outside safety range")
        if v["mean_volume_db"] < -55.0:
            fail(f"verse {n}: mean volume too low")
        if previous_end is not None and abs(v["boundary_start"] - previous_end) > 0.001:
            fail(f"verse {n}: non-shared adjacent boundary")
        if v["boundary_end"] <= v["boundary_start"]:
            fail(f"verse {n}: invalid boundary order")
        previous_end = v["boundary_end"]

    print(
        f"PASS: AUDIO acceptance verses={len(verses)} "
        f"MAPPING=PASS SIGNAL=PASS SPEED=PASS MODEL_AUDIO=PENDING"
    )


if __name__ == "__main__":
    main()
