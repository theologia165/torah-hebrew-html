#!/usr/bin/env python3
import json,sys
from html.parser import HTMLParser
from pathlib import Path
class VerseParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.tokens=[]; self.glosses=[]; self.separators=[]; self.token_depth=0; self.nested_token=False; self.current_class=None; self.current_attrs={}; self.verse_wlc=None
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs); classes=attrs.get('class','').split()
        if tag=='div' and 'verse' in classes:self.verse_wlc=attrs.get('data-wlc')
        if tag=='span' and 'tok' in classes:
            if self.token_depth:self.nested_token=True
            self.token_depth+=1; self.current_class='tok'; self.current_attrs=attrs
        elif tag=='span' and 'gloss' in classes:self.current_class='gloss'; self.current_attrs=attrs
        elif tag=='span' and 'sep' in classes:self.current_class='sep'; self.current_attrs=attrs
    def handle_endtag(self,tag):
        if tag=='span' and self.current_class=='tok':self.token_depth=max(0,self.token_depth-1)
        self.current_class=None; self.current_attrs={}
    def handle_data(self,data):
        if self.current_class=='tok':self.tokens.append((data,dict(self.current_attrs)))
        elif self.current_class=='gloss':self.glosses.append(data)
        elif self.current_class=='sep':self.separators.append(data)
def fail(msg):print(f'FAIL: {msg}',file=sys.stderr);raise SystemExit(1)
def main():
    if len(sys.argv)!=3:fail('usage: verify_html.py <current.json> <output-dir>')
    data=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')); out=Path(sys.argv[2]); p=data['passage']; slug=p['book'].lower().replace(' ','-'); default_ch=int(p['chapter'])
    for verse in data['verses']:
        ch=int(verse.get('chapter',default_ch)); n=int(verse['verse']); path=out/data['sequence']/f'{slug}-{ch}-{n}.html'
        if not path.exists():fail(f'missing generated HTML: {path}')
        source=path.read_text(encoding='utf-8'); parser=VerseParser(); parser.feed(source)
        if parser.nested_token:fail(f'verse {ch}:{n}: nested .tok span detected')
        if parser.verse_wlc!=verse['hebrew']:fail(f'verse {ch}:{n}: data-wlc mismatch')
        if len(parser.tokens)!=len(verse['words']):fail(f'verse {ch}:{n}: token count mismatch')
        if len(parser.glosses)!=len(verse['words']):fail(f'verse {ch}:{n}: gloss count mismatch')
        for i,(parsed,attrs) in enumerate(parser.tokens):
            expected=verse['words'][i]
            if parsed!=expected['surface']:fail(f'verse {ch}:{n} token {i+1}: surface mismatch')
            if attrs.get('data-lemma')!=expected['lemma']:fail(f'verse {ch}:{n} token {i+1}: lemma mismatch')
            if attrs.get('data-pos')!=expected['pos']:fail(f'verse {ch}:{n} token {i+1}: POS mismatch')
            if attrs.get('data-morph')!=expected['morph']:fail(f'verse {ch}:{n} token {i+1}: Japanese morph mismatch')
            if attrs.get('data-morph-code')!=expected['morph_code']:fail(f'verse {ch}:{n} token {i+1}: audit morph code mismatch')
            if parser.glosses[i]!=expected['gloss']:fail(f'verse {ch}:{n} token {i+1}: gloss mismatch')
        if 'dataset.morphCode' in source or 'data-morph-code：</b>' in source:fail(f'verse {ch}:{n}: raw morph code exposed in popup')
        if 'max-height:calc(100vh - 16px)' not in source:fail(f'verse {ch}:{n}: viewport popup clamp missing')
        if '@media(pointer:coarse)' not in source:fail(f'verse {ch}:{n}: coarse pointer support missing')
        if '<span class="gloss">' not in source:fail(f'verse {ch}:{n}: under-word gloss missing')
    print(f"PASS: HTML acceptance verses={len(data['verses'])} golden_contract=PASS")
if __name__=='__main__':main()
