#!/usr/bin/env python3
"""One-off, guarded verification that Actions can set the Cover of run 037."""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests
from PIL import Image

from prepare_notion_html import API, NOTION_VERSION, request_json

RUN_ID = "037-20260907-r1"
PAGE_ID = "3d48aa46-08ae-81ab-a1a5-f3d469273f62"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upload_image(path, token):
    created = request_json(
        "POST", "/file_uploads", token,
        json={"mode": "single_part", "filename": path.name, "content_type": "image/jpeg"},
    )
    upload_id = created["id"]
    headers = {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION}
    for attempt in range(1, 3):
        with path.open("rb") as image:
            response = requests.post(
                API + f"/file_uploads/{upload_id}/send", headers=headers,
                files={"file": (path.name, image, "image/jpeg")}, timeout=60,
            )
        if response.status_code != 429:
            break
        time.sleep(min(float(response.headers.get("Retry-After", "2")), 4.0))
    if response.status_code >= 300:
        raise RuntimeError(f"Notion image upload send: {response.status_code} {response.text[:600]}")
    sent = response.json()
    if sent.get("status") != "uploaded":
        raise RuntimeError(f"Notion image upload status: {sent.get('status')}")
    return upload_id


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: test_notion_cover.py IMAGE_PATH AUDIT_PATH")
    image_path, audit_path = map(Path, sys.argv[1:])
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        raise SystemExit("NOTION_TOKEN is not configured")
    if not image_path.is_file():
        raise SystemExit(f"Missing test image: {image_path}")

    with Image.open(image_path) as image:
        image.verify()
    with Image.open(image_path) as image:
        assert image.format == "JPEG", f"Expected JPEG, got {image.format}"
        assert image.size == (1200, 630), f"Expected 1200x630, got {image.size}"

    audit = {
        "operation": "NOTION_COVER_TEST_ONLY",
        "run_id": RUN_ID,
        "page_id": PAGE_ID,
        "image_path": str(image_path),
        "image_sha256": sha256(image_path),
        "image_size_bytes": image_path.stat().st_size,
        "checks": {"jpeg": True, "dimensions_1200x630": True},
        "attempts": {"upload": 0, "cover_patch": 0},
    }
    try:
        before = request_json("GET", f"/pages/{PAGE_ID}", token)
        audit["page_url"] = before["url"]
        audit["cover_before"] = before.get("cover")
        if before.get("cover") is not None:
            raise RuntimeError("REFUSE_EXISTING_COVER: remove it manually before a replacement experiment")

        audit["attempts"]["upload"] = 1
        upload_id = upload_image(image_path, token)
        audit["notion_file_upload_id"] = upload_id

        audit["attempts"]["cover_patch"] = 1
        request_json(
            "PATCH", f"/pages/{PAGE_ID}", token,
            json={"cover": {"type": "file_upload", "file_upload": {"id": upload_id}}},
        )
        after = request_json("GET", f"/pages/{PAGE_ID}", token)
        audit["cover_after"] = after.get("cover")
        assert after.get("cover", {}).get("type") == "file", "Cover retrieval did not return a Notion file"
        audit["checks"]["notion_cover_is_file"] = True
        audit["status"] = "PASS"
        print("PASS: Actions uploaded 037 JPEG and set the existing Notion page Cover")
    except Exception as error:
        audit["status"] = "FAIL"
        audit["error"] = str(error)
        raise
    finally:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
