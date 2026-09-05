#!/usr/bin/env python3
import html
import json
import sys
from pathlib import Path

CSS = r'''*{box-sizing:border-box}html,body{margin:0;background:#fff;color:#12233f;font-family:"Noto Sans Hebrew","Times New Roman",serif}
body{padding:50px 12px 86px;overflow-x:hidden}.verse{direction:rtl;text-align:center;font-size:clamp(27px,5.5vw,47px);line-height:1.55}
.word{display:inline-flex;flex-direction:column;align-items:center;vertical-align:top;margin:.08em .04em .28em}.tok{display:inline-block;cursor:pointer;border-radius:7px;padding:1px 4px;outline:none;transition:background-color .12s ease,box-shadow .12s ease}
.tok:hover,.tok:focus,.tok.active{background:#dbeafe;box-shadow:0 0 0 1px #93c5fd}.gloss{direction:ltr;font:500 clamp(11px,2.2vw,15px)/1.25 system-ui,sans-serif;color:#34445f;white-space:nowrap;margin-top:2px}
.popup{position:fixed;display:none;direction:ltr;text-align:left;width:min(350px,calc(100vw - 16px));max-height:calc(100vh - 16px);overflow:auto;background:#fff;color:#15243b;border:1px solid #cbd5e1;border-radius:11px;box-shadow:0 10px 30px #0003;padding:13px 15px;z-index:9999;font:14px/1.55 system-ui,sans-serif}.popup.open{display:block}.popup b{color:#163a70}.popup [dir=rtl]{font-size:18px}.src{margin-top:20px;text-align:center;font:12px/1.4 system-ui,sans-serif;color:#667085}@media(pointer:coarse){.tok{padding:4px 6px}.verse{line-height:1.7}}'''

JS = r'''const popup=document.getElementById('popup');let active=null;
function closePopup(){popup.classList.remove('open');if(active)active.classList.remove('active');active=null}
function showPopup(token){if(active&&active!==token)active.classList.remove('active');active=token;token.classList.add('active');popup.innerHTML='<b>lemma：</b><span dir="rtl">'+token.dataset.lemma+'</span><br><b>品詞：</b>'+token.dataset.pos+'<br><b>形態：</b>'+token.dataset.morph;popup.classList.add('open');requestAnimationFrame(()=>{const r=token.getBoundingClientRect(),p=popup.getBoundingClientRect(),gap=8,margin=8;let left=r.left+r.width/2-p.width/2;left=Math.max(margin,Math.min(left,innerWidth-p.width-margin));let top=r.bottom+gap;if(top+p.height>innerHeight-margin)top=r.top-p.height-gap;top=Math.max(margin,Math.min(top,innerHeight-p.height-margin));popup.style.left=left+'px';popup.style.top=top+'px'})}
document.querySelectorAll('.tok').forEach(token=>{token.addEventListener('mouseenter',()=>{if(matchMedia('(pointer:fine)').matches)showPopup(token)});token.addEventListener('mouseleave',()=>{if(matchMedia('(pointer:fine)').matches&&!token.matches(':focus'))closePopup()});token.addEventListener('focus',()=>showPopup(token));token.addEventListener('blur',()=>{if(matchMedia('(pointer:fine)').matches)closePopup()});token.addEventListener('click',event=>{event.stopPropagation();showPopup(token)})});document.addEventListener('click',closePopup);addEventListener('resize',closePopup);addEventListener('scroll',closePopup,{passive:true});'''


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def render_verse(book: str, chapter: int, verse: dict) -> str:
    spans = []
    for word in verse["words"]:
        spans.append(
            '<span class="word">'
            f'<span class="tok" tabindex="0" data-lemma="{esc(word["lemma"])}" '
            f'data-pos="{esc(word["pos"])}" data-morph="{esc(word["morph"])}">{esc(word["surface"])}</span>'
            f'<span class="gloss">{esc(word["gloss"])}</span>'
            '</span>'
        )
    ref = f"{book} {chapter}:{verse['verse']}"
    body = " ".join(spans)
    return (
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{esc(ref)}</title><style>{CSS}</style></head><body>'
        f'<div class="verse" aria-label="{esc(ref)}">{body}</div>'
        '<div id="popup" class="popup" role="dialog" aria-live="polite"></div>'
        '<div class="src">Open Scriptures Hebrew Bible / MorphHB (WLC), CC BY 4.0</div>'
        f'<script>{JS}</script></body></html>'
    )


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: build_html.py <current.json> <output-dir>")
    input_path = Path(sys.argv[1])
    output_root = Path(sys.argv[2])
    data = json.loads(input_path.read_text(encoding="utf-8"))
    p = data["passage"]
    sequence_dir = output_root / data["sequence"]
    sequence_dir.mkdir(parents=True, exist_ok=True)
    book_slug = p["book"].lower().replace(" ", "-")
    for verse in data["verses"]:
        filename = f"{book_slug}-{p['chapter']}-{verse['verse']}.html"
        rendered = render_verse(p["book"], p["chapter"], verse)
        (sequence_dir / filename).write_text(rendered, encoding="utf-8")
        print(f"BUILT: {sequence_dir / filename}")


if __name__ == "__main__":
    main()
