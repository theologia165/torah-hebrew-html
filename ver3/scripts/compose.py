"""Join immutable Neon JSON1 with token-ID keyed ChatGPT JSON2."""
import html, json, re, sys
from pathlib import Path
from prepare import digest, save, compact

ROOT=Path(__file__).resolve().parents[1]
def prose(s):
    assert isinstance(s,str) and s.strip(), 'Empty editorial text'
    assert not any(x in s for x in ('準備済み','TODO','TEST','展開試験用')), 'Placeholder text'
    for line in s.splitlines():
        if re.match(r'^[\s*#>0-9.()\-]*[\u0590-\u05ff]',line):
            raise ValueError('Japanese paragraph must start with ヘブライ語の: '+line[:45])
    return s

def validate(j,c):
    r=j['request']
    assert c['schema_version']=='3.0-json2' and c['run_id']==r['run_id']
    assert c['json1_sha256']==digest(j), 'JSON2 was written from a different JSON1'
    assert c['json1_1_sha256']==digest(compact(j)), 'JSON1.1 handoff mismatch'
    prose(c['title']); prose(c['summary']); prose(c['conclusion'])
    assert [v['ref'] for v in c['verses']]==r['refs'], 'Verse coverage mismatch'
    seen=set()
    for raw,v in zip(j['verses'],c['verses']):
        assert [x['token_id'] for x in v['glosses']]==[t['id'] for t in raw['tokens']], 'Token IDs/order mismatch'
        for g in v['glosses']: prose(g['ja'])
        prose(v['translation']); prose(v['short_commentary'])
        headings=[s['heading'] for s in v['sections']]
        assert headings.count('デボーショナルな受けとめ')==1
        assert headings[-1]=='デボーショナルな受けとめ'
        for s in v['sections']:
            prose(s['heading']); prose(s['body'])
            assert s['heading'] not in ('ラビ・教父','ユダヤ・教父')
            normalized=re.sub(r'\s+','',s['body'])
            assert normalized not in seen, 'Repeated commentary across verses'
            seen.add(normalized)
            assert isinstance(s['sources'],list)
            for source in s['sources']:
                prose(source['label']); assert source['url'].startswith('https://')
    return True

def ui_token(t):
    lx=t['lexeme'] or {}
    return dict(t,lexeme={'key':lx.get('source_lexeme_key'),'lemma':lx.get('lemma_text')})

def render(raw,v,book):
    esc=lambda x:html.escape(str(x),quote=True)
    display_text=''.join(w['surface']+w['separator_after'] for w in raw['layout']['words'])
    pieces=[]
    for t,w,g in zip(raw['tokens'],raw['layout']['words'],v['glosses']):
        label='ケティーブ' if not w.get('read_aloud',True) else ('ケレー' if w.get('reading_role')=='qere' else '')
        reading_label=f'<span class="reading-label" dir="ltr">{label}</span>' if label else ''
        pieces.append(f'<button class="token" type="button" data-index="{t["token_index"]}">{reading_label}<span class="he">{esc(t["surface"])}</span><span class="gloss">{esc(g["ja"])}</span></button>')
        pieces.append(f'<span class="separator" aria-hidden="true">{esc(w["separator_after"])}</span>')
    js=(ROOT/'templates/search.js').read_text().replace('__REF__',json.dumps(raw['ref'])).replace('__BOOK__',json.dumps(book))
    css=(ROOT/'templates/style.css').read_text(); controls=(ROOT/'templates/controls.html').read_text()
    data=json.dumps({'tokens':[ui_token(t) for t in raw['tokens']]},ensure_ascii=False).replace('<','\\u003c')
    out=f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(raw["ref"])}</title><style>{css}</style></head><body><main class="wrap"><section class="hebrew-card"><div id="verse" class="verse" dir="rtl" data-wlc="{esc(raw["layout"]["hebrew"])}" data-display-text="{esc(display_text)}">'+''.join(pieces)+f'</div></section>{controls}</main><div id="hover" class="hover" hidden></div><script id="verse-data" type="application/json">{data}</script><script>{js}</script></body></html>'
    from bs4 import BeautifulSoup
    soup=BeautifulSoup(out,'html.parser')
    verse=soup.select_one('#verse')
    reconstructed=''.join(n.select_one('.he').text if 'token' in n.get('class',[]) else n.text for n in verse.children)
    assert reconstructed==display_text, 'HTML ketiv/qere text differs from DB'
    assert ''.join(w['surface']+w['separator_after'] for w in raw['layout']['words'] if w.get('read_aloud',True))==raw['layout']['hebrew'], 'Reading text differs from DB'
    assert len(soup.select('#verse .token'))==len(raw['tokens'])
    assert not soup.select('script[src],link[rel=stylesheet],.hint,.status,.src,audio')
    assert not soup.select('#scopeSelect option[disabled]')
    return out

def main():
    run=Path(sys.argv[1]); j=json.loads((run/'json1.json').read_text()); c=json.loads((run/'json2.json').read_text()); validate(j,c)
    r=j['request']; p=r['passage']; out=dict(schema_version='2.0',sequence=r['sequence'],passage=p,summary=c['summary'],verses=[])
    for raw,v in zip(j['verses'],c['verses']):
        _,ch,n=v['ref'].split('.')
        html_path=run/'html'/f'{p["book"].lower()}-{ch}-{n}.html'; html_path.parent.mkdir(exist_ok=True)
        rendered=render(raw,v,r['book'])
        if html_path.exists(): assert html_path.read_text()==rendered,'Existing HTML differs'
        html_path.write_text(rendered)
        out['verses'].append({'chapter':int(ch),'verse':int(n),'words':[t for t,w in zip(raw['tokens'],raw['layout']['words']) if w.get('read_aloud',True)]})
    save(run/'audio-input.json',out)
    print('PASS: JSON1/JSON1.1/JSON2 hashes, coverage, token identity, commentary, exact HTML WLC')

if __name__=='__main__': main()
