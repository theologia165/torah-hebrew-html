#!/usr/bin/env python3
import json, os, re, sys, time
from pathlib import Path
import requests

NOTION_VERSION = "2026-03-11"
API = "https://api.notion.com/v1"


def rt(text, bold=False):
    return [{"type": "text", "text": {"content": text}, "annotations": {"bold": bold}}]


def paragraph(text):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt(text)}}


def heading(level, text):
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": rt(text)}}


def callout(text):
    return {"object": "block", "type": "callout", "callout": {"rich_text": rt(text), "icon": {"type": "emoji", "emoji": "📘"}, "color": "blue_background"}}


def audio_external(url):
    return {"object": "block", "type": "audio", "audio": {"type": "external", "external": {"url": url}}}


def embed_external(url):
    return {"object": "block", "type": "embed", "embed": {"url": url}}


def embed_file_upload(upload_id):
    return {"object": "block", "type": "embed", "embed": {"type": "file_upload", "file_upload": {"id": upload_id}}}


def detailed_blocks(text):
    out = []
    for chunk in [x.strip() for x in text.split("\n\n") if x.strip()]:
        lines = chunk.splitlines()
        m = re.match(r"^\*\*(.+?)\*\*$", lines[0].strip())
        if m:
            out.append(heading(3, m.group(1)))
            body = "\n".join(lines[1:]).strip()
            if body:
                out.append(paragraph(body))
        else:
            out.append(paragraph(chunk.replace("**", "")))
    return out


def detailed_toggle(text):
    return {"object": "block", "type": "toggle", "toggle": {"rich_text": rt("詳しい解説"), "children": detailed_blocks(text)}}


def req(method, path, token, **kwargs):
    headers = kwargs.pop("headers", {})
    headers.update({"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION})
    if "json" in kwargs:
        headers["Content-Type"] = "application/json"
    r = requests.request(method, API + path, headers=headers, timeout=45, **kwargs)
    if r.status_code == 429:
        time.sleep(min(float(r.headers.get("Retry-After", "2")), 4.0))
        r = requests.request(method, API + path, headers=headers, timeout=45, **kwargs)
    if r.status_code >= 300:
        raise RuntimeError(f"Notion {method} {path}: {r.status_code} {r.text[:800]}")
    return r.json()


def title_for(d):
    p = d["passage"]
    return f'{d["sequence"]}｜創世記{p["chapter"]}:{p["start_verse"]}–{p["end_verse"]}'


def parasha_aliyah(d):
    parts = d["passage"].get("display", "").split("｜")
    parasha = parts[0] if parts else ""
    aliyah = parts[1] if len(parts) > 1 else ""
    rng = f'創世記{d["passage"]["chapter"]}:{d["passage"]["start_verse"]}–{d["passage"]["end_verse"]}'
    return parasha, aliyah, rng


def find_existing_child(parent, wanted_title, token):
    cursor = None
    while True:
        path = f"/blocks/{parent}/children?page_size=100" + (f"&start_cursor={cursor}" if cursor else "")
        r = req("GET", path, token)
        for b in r.get("results", []):
            if b.get("type") == "child_page" and b.get("child_page", {}).get("title") == wanted_title:
                return b.get("id")
        if not r.get("has_more"):
            return None
        cursor = r.get("next_cursor")


def load_route(seq, path):
    route = json.loads(Path(path).read_text(encoding="utf-8"))
    if route.get("sequence") != seq:
        raise RuntimeError("Notion HTML route sequence mismatch")
    return {int(e["verse"]): e for e in route.get("entries", [])}, route


def load_pages_map(seq):
    path = Path(f"ver2/state/{seq}-pages-map.json")
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {int(e["verse"]): e["url"] for e in data.get("entries", [])}


def fetch_children(block_id, token):
    out = []
    cursor = None
    while True:
        path = f"/blocks/{block_id}/children?page_size=100" + (f"&start_cursor={cursor}" if cursor else "")
        r = req("GET", path, token)
        out.extend(r.get("results", []))
        if not r.get("has_more"):
            return out
        cursor = r.get("next_cursor")


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: notion_delivery.py enriched_json notion_html_route_json")
    d = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    seq = d["sequence"]
    token = os.getenv("NOTION_TOKEN", "").strip()
    parent = os.getenv("NOTION_PARENT_PAGE_ID", "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", "theologia165/torah-hebrew-html")
    branch = os.getenv("VER2_BRANCH", "asaichi-torah-ver2")
    state_path = Path(f"ver2/state/{seq}-notion-delivery.json")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {"sequence": seq, "owner": "GITHUB_ACTIONS", "notion_version": NOTION_VERSION, "status": "PENDING", "html_mode": None, "page_id": None, "page_url": None, "errors": []}
    if not token or not parent:
        state["status"] = "BLOCKED_MISSING_NOTION_SECRET"
        state["errors"].append("NOTION_TOKEN and/or NOTION_PARENT_PAGE_ID is not configured")
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(state, ensure_ascii=False))
        return 3

    route_map, route = load_route(seq, sys.argv[2])
    pages_map = load_pages_map(seq)
    wanted_verses = {int(v["verse"]) for v in d["verses"]}
    if set(route_map) != wanted_verses:
        raise RuntimeError(f"Route verse mismatch: expected={sorted(wanted_verses)} actual={sorted(route_map)}")
    for n, entry in route_map.items():
        if entry.get("mode") == "GITHUB_PAGES_FALLBACK" and n not in pages_map:
            raise RuntimeError(f"Missing Pages fallback URL for verse {n}")

    wanted_title = title_for(d)
    existing = find_existing_child(parent, wanted_title, token)
    if existing and os.getenv("NOTION_UPDATE_EXISTING", "false").lower() != "true":
        page = req("GET", f"/pages/{existing}", token)
        state.update({"status": "SKIP_EXISTING_PAGE", "page_id": existing, "page_url": page.get("url"), "html_mode": route.get("html_mode")})
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(state, ensure_ascii=False))
        return 0

    parasha, aliyah, rng = parasha_aliyah(d)
    children = [callout(f"PARASHA：{parasha}　/　ALIYAH：{aliyah}　/　RANGE：{rng}"), callout(d["summary"])]
    audio_urls = []
    fallback_urls = []
    ch = int(d["passage"]["chapter"])
    attachment_verses = []
    fallback_verses = []
    for v in d["verses"]:
        n = int(v["verse"])
        audio_url = f"https://raw.githubusercontent.com/{repo}/{branch}/ver2/published/{seq}/audio/{seq}_{n}_r2.mp3"
        audio_urls.append(audio_url)
        entry = route_map[n]
        if entry.get("mode") == "NOTION_ATTACHMENT":
            html_block = embed_file_upload(entry["file_upload_id"])
            attachment_verses.append(n)
        else:
            html_url = pages_map[n]
            html_block = embed_external(html_url)
            fallback_urls.append(html_url)
            fallback_verses.append(n)
        children += [
            heading(2, f"創世記 {ch}:{n}"),
            audio_external(audio_url),
            heading(3, "私訳"), paragraph(v["translation"]),
            heading(3, "ヘブライ語"), html_block,
            heading(3, "簡易な説明"), paragraph(v["short_commentary"]),
            detailed_toggle(v["detailed_commentary"]),
        ]

    payload = {"parent": {"page_id": parent}, "properties": {"title": {"type": "title", "title": rt(wanted_title)}}, "children": children[:100]}
    page = req("POST", "/pages", token, json=payload)
    page_id = page["id"]
    rest = children[100:]
    while rest:
        chunk, rest = rest[:100], rest[100:]
        req("PATCH", f"/blocks/{page_id}/children", token, json={"children": chunk})

    got = fetch_children(page_id, token)
    embeds = [b for b in got if b.get("type") == "embed"]
    audios = [b.get("audio", {}).get("external", {}).get("url") for b in got if b.get("type") == "audio"]
    toggles = [b for b in got if b.get("type") == "toggle" and "詳しい解説" in "".join(x.get("plain_text", "") for x in b.get("toggle", {}).get("rich_text", []))]
    toggle_children_ok = True
    for t in toggles:
        if not fetch_children(t["id"], token):
            toggle_children_ok = False
            break
    embed_urls = [b.get("embed", {}).get("url") for b in embeds]
    missing_fallback = [u for u in fallback_urls if u not in embed_urls]
    missing_audio = [u for u in audio_urls if u not in audios]
    state.update({
        "html_mode": route.get("html_mode"),
        "page_id": page_id,
        "page_url": page.get("url"),
        "verse_count": len(d["verses"]),
        "embed_count": len(embeds),
        "attachment_count": len(attachment_verses),
        "fallback_count": len(fallback_verses),
        "attachment_verses": attachment_verses,
        "fallback_verses": fallback_verses,
        "audio_count": len(audios),
        "toggle_count": len(toggles),
        "toggle_children_ok": toggle_children_ok,
        "missing_fallback_html": missing_fallback,
        "missing_audio": missing_audio,
        "route_manifest": f"ver2/state/{seq}-notion-html-route.json",
        "pages_manifest": f"ver2/state/{seq}-pages-map.json" if fallback_verses else None,
    })
    ok = len(embeds) == len(d["verses"]) and not missing_fallback and not missing_audio and len(toggles) == len(d["verses"]) and toggle_children_ok
    state["status"] = "PASS" if ok else "FAIL_VERIFY"
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(state, ensure_ascii=False))
    return 0 if ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
