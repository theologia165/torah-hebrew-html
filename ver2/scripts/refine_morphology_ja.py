#!/usr/bin/env python3
import json, sys
from pathlib import Path

G={"m":"男性","f":"女性","b":"両性","c":"共通","x":"不定"}
N={"s":"単数","p":"複数","d":"双数","x":"不定"}
S={"a":"絶対形","c":"連語形","d":"限定形"}
AT={"c":"基数詞","o":"序数詞","a":"形容詞","g":"地名形容詞"}
PT={"p":"人称代名詞","d":"指示代名詞","i":"疑問代名詞","r":"関係代名詞"}

def dec_a(c):
    # A + type + gender + number + state
    r=c[1:]
    bits=[AT.get(r[0],"形容詞・数詞")]; r=r[1:]
    if r and r[0] in G: bits.append(G[r[0]]); r=r[1:]
    if r and r[0] in N: bits.append(N[r[0]]); r=r[1:]
    if r and r[0] in S: bits.append(S[r[0]])
    return "・".join(bits)

def dec_p(c):
    # P + type + [person] + gender + number
    r=c[1:]
    bits=[PT.get(r[0],"代名詞")]; r=r[1:]
    if r and r[0].isdigit(): bits.append(r[0]+"人称"); r=r[1:]
    if r and r[0] in G: bits.append(G[r[0]]); r=r[1:]
    if r and r[0] in N: bits.append(N[r[0]])
    return "・".join(bits)

def refine(w):
    code=w['morph_code']; body=code[1:] if code.startswith('H') else code
    comps=body.split('/')
    rendered=[]
    for c in comps:
        if c.startswith('A'): rendered.append(dec_a(c))
        elif c.startswith('P'): rendered.append(dec_p(c))
        else:
            # retain the already-humanized corresponding component
            old=w['morph'].split('／')
            rendered.append(old[len(rendered)] if len(old)>len(rendered) else c)
    w['morph']='／'.join(rendered)
    lexical=next((c for c in reversed(comps) if not c.startswith('S')), '')
    if lexical.startswith('A'):
        w['pos']='数詞' if len(lexical)>1 and lexical[1] in ('c','o') else '形容詞'

def main():
    if len(sys.argv)!=2: raise SystemExit('usage: refine_morphology_ja.py <enriched.json>')
    p=Path(sys.argv[1]); d=json.loads(p.read_text(encoding='utf-8'))
    for v in d['verses']:
        for w in v['words']: refine(w)
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PASS: Japanese numeral/pronoun morphology refined')
if __name__=='__main__': main()
