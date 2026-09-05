#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
import requests

API = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"


def request_json(method, path, token, **kwargs):
    headers = kwargs.pop("headers", {})
    headers.update({"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION})
    if "json" in kwargs:
        headers["Content-Type"] = "application/json"
    r = requests.request(method, API + path, headers=headers, timeout=45, **kwargs)
    if r.status_code == 429:
        time.sleep(min(float(r.headers.get("Retry-After", "2")), 4.0))
        r = requests.request(method, API + path, headers=headers, timeout=45, **kwargs)
    if r.status_code >= 300:
        raise RuntimeError(f"Notion {method} {path}: {r.status_code} {r.text[:600]}")
    return r.json()


def upload_html(path: Path, token: str):
    created = request_json(
        "POST", "/file_uploads", token,
        json={"mode": "single_part", "filename": path.name, "content_type": "text/html"}
    )
    upload_id = created["id"]
    headers = {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION}
    with path.open("rb") as f:
        r = requests.post(
            API + f"/file_uploads/{upload_id}/send",
            headers=headers,
            files={"file": (path.name, f, "text/html")},
            timeout=60,
        )
    if r.status_code == 429:
        time.sleep(min(float(r.headers.get("Retry-After", "2")), 4.0))
        with path.open("rb") as f:
            r = requests.post(
                API + f"/file_uploads/{upload_id}/send",
                headers=headers,
                files={"file": (path.name, f, "text/html")},
                timeout=60,
            )
    if r.status_code >= 300:
        raise RuntimeError(f"Notion upload send: {r.status_code} {r.text[:600]}")
    sent = r.json()
    if sent.get("status") != "uploaded":
        raise RuntimeError(f"Notion upload status is not uploaded: {sent.get('status')}")
    return upload_id


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: prepare_notion_html.py enriched_json html_dir route_json")
    enriched_path = Path(sys.argv[1])
    html_dir = Path(sys.argv[2])
    route_path = Path(sys.argv[3])
    d = json.loads(enriched_path.read_text(encoding="utf-8"))
    seq = d["sequence"]
    ch = int(d["passage"]["chapter"])
    token = os.getenv("NOTION_TOKEN", "").strip()
    if not token:
        raise SystemExit("NOTION_TOKEN is not configured")

    route = {"sequence": seq, "notion_version": NOTION_VERSION, "entries": [], "attachment_success": [], "fallback_needed": [], "errors": {}}
    for v in d["verses"]:
        n = int(v["verse"])
        html_path = html_dir / f"genesis-{ch}-{n}.html"
        if not html_path.exists():
            raise SystemExit(f"missing generated HTML: {html_path}")
        entry = {"verse": n, "source": str(html_path), "mode": None, "file_upload_id": None, "error": None}
        try:
            upload_id = upload_html(html_path, token)
            entry.update({"mode": "NOTION_ATTACHMENT", "file_upload_id": upload_id})
            route["attachment_success"].append(n)
        except Exception as e:
            entry.update({"mode": "GITHUB_PAGES_FALLBACK", "error": str(e)[:800]})
            route["fallback_needed"].append(n)
            route["errors"][str(n)] = str(e)[:800]
        route["entries"].append(entry)

    if route["fallback_needed"] and route["attachment_success"]:
        route["html_mode"] = "MIXED"
    elif route["fallback_needed"]:
        route["html_mode"] = "GITHUB_PAGES"
    else:
        route["html_mode"] = "NOTION_ATTACHMENT"
    route_path.parent.mkdir(parents=True, exist_ok=True)
    route_path.write_text(json.dumps(route, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(route, ensure_ascii=False))


if __name__ == "__main__":
    main()
