#!/usr/bin/env python3
import json, os, re, sys, time
from pathlib import Path
import requests

NOTION_VERSION = "2026-03-11"
API = "https://api.notion.com/v1"


def rt(text, bold=False):
    return [{"type":"text","text":{"content":text},"annotations":{"bold":bold}}]

def paragraph(text):
    return {"object":"block","type":"paragraph","paragraph":{"rich_text":rt(text)}}

def heading(level, text):
    key=f"heading_{level}"; return {"object":"block","type":key,key:{"rich_text":rt(text)}}

def callout(text):
    return {"object":"block","type":"callout","callout":{"rich_text":rt(text),"icon":{"type":"emoji","emoji":"📘"},"color":"blue_background"}}

def audio_external(url):
    return {"object":"block","type":"audio","audio":{"type":"external","external":{"url":url}}}

def embed_external(url):
    return {"object":"block","type":"embed","embed":{"url":url}}

def detailed_blocks(text):
    out=[]
    for chunk in [x.strip() for x in text.split("\n\n") if x.strip()]:
        lines=chunk.splitlines(); m=re.match(r"^\*\*(.+?)\*\*$", lines[0].strip())
        if m:
            out.append(heading(3,m.group(1))); body="\n".join(lines[1:]).strip()
            if body: out.append(paragraph(body))
        else: out.append(paragraph(chunk.replace("**","")))
    return out

def req(method,path,token,**kwargs):
    headers=kwargs.pop("headers",{}); headers.update({"Authorization":f"Bearer {token}","Notion-Version":NOTION_VERSION})
    if "json" in kwargs: headers["Content-Type"]="application/json"
    r=requests.request(method,API+path,headers=headers,timeout=45,**kwargs)
    if r.status_code==429:
        time.sleep(min(float(r.headers.get("Retry-After","2")),4.0)); r=requests.request(method,API+path,headers=headers,timeout=45,**kwargs)
    if r.status_code>=300: raise RuntimeError(f"Notion {method} {path}: {r.status_code} {r.text[:800]}")
    return r.json()

def title_for(d):
    p=d["passage"]; return f'{d["sequence"]}｜創世記{p["chapter"]}:{p["start_verse"]}–{p["end_verse"]}'

def parasha_aliyah(d):
    parts=d["passage"].get("display","").split("｜"); parasha=parts[0] if parts else ""; aliyah=parts[1] if len(parts)>1 else ""
    rng=f'創世記{d["passage"]["chapter"]}:{d["passage"]["start_verse"]}–{d["passage"]["end_verse"]}'
    return parasha,aliyah,rng

def find_existing_child(parent, wanted_title, token):
    cursor=None
    while True:
        path=f"/blocks/{parent}/children?page_size=100" + (f"&start_cursor={cursor}" if cursor else "")
        r=req("GET",path,token)
        for b in r.get("results",[]):
            if b.get("type")=="child_page" and b.get("child_page",{}).get("title")==wanted_title:
                return b.get("id")
        if not r.get("has_more"): return None
        cursor=r.get("next_cursor")

def main():
    if len(sys.argv)!=2: raise SystemExit("usage: notion_delivery.py ver2/published/NNN/current.enriched.json")
    d=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")); seq=d["sequence"]
    token=os.getenv("NOTION_TOKEN","").strip(); parent=os.getenv("NOTION_PARENT_PAGE_ID","").strip()
    pages_base=os.getenv("PAGES_BASE_URL","https://theologia165.github.io/torah-hebrew-html").rstrip("/")
    repo=os.getenv("GITHUB_REPOSITORY","theologia165/torah-hebrew-html"); branch=os.getenv("VER2_BRANCH","asaichi-torah-ver2")
    state_path=Path(f"ver2/state/{seq}-notion-delivery.json"); state_path.parent.mkdir(parents=True,exist_ok=True)
    state={"sequence":seq,"owner":"GITHUB_ACTIONS","notion_version":NOTION_VERSION,"status":"PENDING","html_mode":"GITHUB_PAGES","page_id":None,"page_url":None,"errors":[]}
    if not token or not parent:
        state["status"]="BLOCKED_MISSING_NOTION_SECRET"; state["errors"].append("NOTION_TOKEN and/or NOTION_PARENT_PAGE_ID is not configured")
        state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(state,ensure_ascii=False)); return 3

    wanted_title=title_for(d); existing=find_existing_child(parent,wanted_title,token)
    if existing and os.getenv("NOTION_UPDATE_EXISTING","false").lower()!="true":
        page=req("GET",f"/pages/{existing}",token); state.update({"status":"SKIP_EXISTING_PAGE","page_id":existing,"page_url":page.get("url")})
        state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(state,ensure_ascii=False)); return 0

    parasha,aliyah,rng=parasha_aliyah(d)
    children=[callout(f"PARASHA：{parasha}　/　ALIYAH：{aliyah}　/　RANGE：{rng}"),callout(d["summary"])]
    html_urls=[]; audio_urls=[]; ch=d["passage"]["chapter"]
    for v in d["verses"]:
        n=v["verse"]; html_url=f"{pages_base}/{seq}/genesis-{ch}-{n}.html"; audio_url=f"https://raw.githubusercontent.com/{repo}/{branch}/ver2/published/{seq}/audio/{seq}_{n}_r2.mp3"
        html_urls.append(html_url); audio_urls.append(audio_url)
        children += [heading(2,f"創世記 {ch}:{n}"),audio_external(audio_url),heading(3,"私訳"),paragraph(v["translation"]),heading(3,"ヘブライ語"),embed_external(html_url),heading(3,"簡易な説明"),paragraph(v["short_commentary"]),heading(3,"詳しい解説")]
        children += detailed_blocks(v["detailed_commentary"])

    if existing:
        raise RuntimeError("Existing-page update is intentionally blocked until a safe replace strategy is implemented")
    payload={"parent":{"page_id":parent},"properties":{"title":{"type":"title","title":rt(wanted_title)}},"children":children[:100]}
    page=req("POST","/pages",token,json=payload); page_id=page["id"]; rest=children[100:]
    while rest:
        chunk,rest=rest[:100],rest[100:]; req("PATCH",f"/blocks/{page_id}/children",token,json={"children":chunk})

    got=[]; cursor=None
    while True:
        path=f"/blocks/{page_id}/children?page_size=100"+(f"&start_cursor={cursor}" if cursor else ""); r=req("GET",path,token); got.extend(r.get("results",[]))
        if not r.get("has_more"): break
        cursor=r.get("next_cursor")
    embeds=[b.get("embed",{}).get("url") for b in got if b.get("type")=="embed"]; audios=[b.get("audio",{}).get("external",{}).get("url") for b in got if b.get("type")=="audio"]
    missing_html=[u for u in html_urls if u not in embeds]; missing_audio=[u for u in audio_urls if u not in audios]
    state.update({"page_id":page_id,"page_url":page.get("url"),"verse_count":len(d["verses"]),"embed_count":len(embeds),"audio_count":len(audios),"missing_html":missing_html,"missing_audio":missing_audio})
    state["status"]="PASS" if not missing_html and not missing_audio else "FAIL_VERIFY"
    state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(state,ensure_ascii=False)); return 0 if state["status"]=="PASS" else 4

if __name__=="__main__": raise SystemExit(main())
