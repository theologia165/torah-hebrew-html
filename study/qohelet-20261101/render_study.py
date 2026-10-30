"""Render scholarly-only study assets, preserving every DB token and reading."""
import hashlib,html,json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[1]
PUBLIC='https://theologia165.github.io/torah-hebrew-html/study-public/qohelet-20261101/'

EXTRA_JS=r'''
function segmentDescription(s){
  const type=s.subtype_code;
  const p=s.pos_code;
  const sub={T:{d:'冠詞',a:'付加・副詞的助辞',r:'関係詞',i:'疑問辞',j:'間投詞',o:'目的語標識',n:'否定辞',m:'存在辞'},N:{c:'普通名詞',p:'固有名詞'},A:{a:'形容詞',c:'基数詞',o:'序数詞'},P:{p:'人称代名詞',d:'指示代名詞',r:'関係代名詞',i:'疑問代名詞'},S:{p:'接尾代名詞',d:'方向の ה',h:'付加の ה'},R:{d:'前置詞＋冠詞'}};
  const title=sub[p]?.[type]||POS[p]||p;
  const details=[s.verb_stem_code?STEM[s.verb_stem_code]||s.verb_stem_code:null,s.verb_conjugation_code?CONJ[s.verb_conjugation_code]||s.verb_conjugation_code:null,s.person_code?s.person_code+'人称':null,GENDER[s.gender_code],NUMBER[s.number_code],STATE[s.state_code]].filter(Boolean);
  return title+(details.length?'：'+details.join('・'):'')+' ['+s.morph_code+']';
}
hoverRows=function(t){
  const rows=[['レーマ',hebrewLemma(t),'lemma-value']];
  if(t.transliteration)rows.push(['転写（レーマ）',t.transliteration,'']);
  rows.push(['語彙番号',String(lexemeKey(t)||'—'),'']);
  if(t.reading_role)rows.push(['本文注記',t.reading_role==='ketiv'?'ケティーブ（書かれた形・非朗読）':'ケレー（読まれる形）','']);
  if(!lexemeKey(t))rows.push(['検索注記','独立した語彙キーがない前置詞です。フォーム検索を利用できます。','']);
  for(const s of t.morph_segments||[])rows.push(['分解 '+s.segment_index,segmentDescription(s),'']);
  rows.push(['原コード',t.morph_raw,'']);
  return rows;
};
'''

def render(raw,v):
    esc=lambda x:html.escape(str(x),quote=True)
    pieces=[];tokens=[]
    for t,w,g in zip(raw['tokens'],raw['layout']['words'],v['glosses']):
        assert t['id']==g['token_id'] and t['surface']==w['surface']
        role='ketiv' if not w.get('read_aloud',True) else ('qere' if w.get('reading_role')=='qere' else '')
        label={'ketiv':'ケティーブ','qere':'ケレー'}.get(role,'')
        prefix=f'<span class="reading-label" dir="ltr">{label}</span>' if label else ''
        pieces.append(f'<button class="token" type="button" data-index="{t["token_index"]}">{prefix}<span class="he">{esc(t["surface"])}</span><span class="gloss">{esc(g["ja"])}</span></button><span class="separator" aria-hidden="true">{esc(w["separator_after"])}</span>')
        lx=t['lexeme'] or {}
        tokens.append(dict(t,lexeme={'key':lx.get('source_lexeme_key'),'lemma':lx.get('lemma_text') or {'b':'בְּ（前置詞）','l':'לְ（前置詞）'}.get(t['lemma_raw'])},transliteration=lx.get('transliteration'),reading_role=role))
    templates=REPO/'ver3/templates'
    js=(templates/'search.js').read_text().replace('__REF__',json.dumps(raw['ref'])).replace('__BOOK__','"Eccl"')
    js=js.replace("t:'Hithpael'","t:'Hithpael',l:'Pilpel',L:'Polpal'").replace("c:'不定詞連語形'","c:'不定詞連語形',j:'指示形（Jussive）'")
    js=js.replace('box.hidden=false;placeHover(node);',"const lemmaButton=box.querySelector('[data-search-mode=lemma]');lemmaButton.disabled=!lexemeKey(t);box.hidden=false;placeHover(node);")
    js=js.replace('function cancelHide()',EXTRA_JS+'\nfunction cancelHide()')
    css=(templates/'style.css').read_text()+'\n.hover{max-height:calc(100vh - 24px);overflow:auto;max-width:calc(100vw - 24px)} .study-ref{font:14px system-ui;color:#475569;margin:0 0 12px} .wrap{padding-bottom:24px}'
    display=''.join(w['surface']+w['separator_after'] for w in raw['layout']['words'])
    assert ''.join(w['surface']+w['separator_after'] for w in raw['layout']['words'] if w.get('read_aloud',True))==raw['layout']['hebrew']
    data=json.dumps({'tokens':tokens},ensure_ascii=False).replace('<','\\u003c')
    out=f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(raw["ref"])}｜ヘブライ語分解・検索</title><style>{css}</style></head><body><main class="wrap"><p class="study-ref">{esc(raw["ref"])} ｜ 語をホバー・クリックすると分解と検索を表示</p><section class="hebrew-card"><div id="verse" class="verse" dir="rtl" data-wlc="{esc(raw["layout"]["hebrew"])}" data-display-text="{esc(display)}">'+''.join(pieces)+f'</div></section>{(templates/"controls.html").read_text()}</main><div id="hover" class="hover" hidden></div><script id="verse-data" type="application/json">{data}</script><script>{js}</script></body></html>'
    from bs4 import BeautifulSoup
    soup=BeautifulSoup(out,'html.parser');verse=soup.select_one('#verse')
    reconstructed=''.join(n.select_one('.he').text if 'token' in n.get('class',[]) else n.text for n in verse.children)
    assert reconstructed==display
    assert len(soup.select('.token'))==len(tokens)
    assert all(t['morph_segments'] for t in tokens)
    return out

def main():
    j=json.loads((ROOT/'json1.json').read_text());r=json.loads((ROOT/'research.json').read_text())
    canonical=json.dumps(j,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    assert hashlib.sha256(canonical).hexdigest()==r['json1_sha256']
    assert [v['ref'] for v in j['verses']]==[v['ref'] for v in r['verses']]
    dest=ROOT/'html';dest.mkdir(exist_ok=True)
    for raw,v in zip(j['verses'],r['verses']):
        (dest/(raw['ref'].replace('.','-').lower()+'.html')).write_text(render(raw,v))
    print('PASS: 22 verses, 215 tokens; exact WLC and ketiv/qere; segmented morphology and search rendered')

if __name__=='__main__':main()
