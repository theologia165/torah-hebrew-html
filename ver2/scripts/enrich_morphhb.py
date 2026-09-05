#!/usr/bin/env python3
import json, re, sys, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

MORPHHB_SHA="3d15126fb1ef74867fc1434be1942e837932691f"
STRONGS_SHA="0acd2f251c2d35ff8db2dece4e0593979d3ac223"
GEN_URL=f"https://raw.githubusercontent.com/openscriptures/morphhb/{MORPHHB_SHA}/wlc/Gen.xml"
STRONGS_URL=f"https://raw.githubusercontent.com/openscriptures/strongs/{STRONGS_SHA}/hebrew/strongs-hebrew-dictionary.js"
NS={"o":"http://www.bibletechnologies.net/2003/OSIS/namespace"}
PREFIX_LEMMA={"c":"וְ","l":"לְ","b":"בְּ","m":"מִן","k":"כְּ","d":"הַ"}
STEMS={"q":"Qal","N":"Niphal","p":"Piel","P":"Pual","h":"Hiphil","H":"Hophal","t":"Hithpael","o":"Polel","O":"Polal","r":"Hithpolel","m":"Poel","M":"Poal","k":"Palel","K":"Pulal","Q":"Qal passive"}
ASPECTS={"p":"完了形","q":"連続完了形","i":"未完了形","w":"wayyiqtol","h":"コホルタティブ系","v":"命令形","r":"分詞","a":"不定詞絶対形","c":"不定詞連語形"}
GENDER={"m":"男性","f":"女性","b":"両性","c":"共通"}; NUMBER={"s":"単数","p":"複数","d":"双数"}; STATE={"a":"絶対形","c":"連語形","d":"限定形"}

def get(url):
    req=urllib.request.Request(url,headers={"User-Agent":"asaichi-torah-ver2"})
    with urllib.request.urlopen(req,timeout=45) as r:return r.read()

def strong_dict(raw):
    t=raw.decode("utf-8"); return json.loads(t[t.index("{"):t.rfind("}")+1])

def lemma_hebrew(code,strongs):
    parts=code.split("/")
    for part in reversed(parts):
        m=re.match(r"^(\d+)",part.strip())
        if m:
            k="H"+str(int(m.group(1)))
            if k in strongs:return strongs[k]["lemma"]
    return PREFIX_LEMMA.get(parts[-1].strip(),parts[-1].strip())

def pos_ja(code):
    comps=(code[1:] if code.startswith("H") else code).split("/"); lexical=None
    for c in reversed(comps):
        if not c.startswith("S"): lexical=c; break
    if not lexical:return "未分類"
    if lexical.startswith("V"):return "動詞"
    if lexical.startswith("N"):return "固有名詞" if len(lexical)>1 and lexical[1] in ("p","g") else "名詞"
    if lexical.startswith("A"):return "数詞・形容詞"
    if lexical.startswith("P"):return "代名詞"
    if lexical.startswith("R"):return "前置詞"
    if lexical.startswith("C"):return "接続詞"
    if lexical.startswith("D"):return "副詞"
    if lexical.startswith("T"):return {"To":"対格標識","Td":"定冠詞","Tr":"関係詞","Te":"小辞","Tn":"否定辞","Ti":"疑問詞","Ta":"副詞的小辞"}.get(lexical[:2],"機能語")
    return "機能語"

def dec(c):
    if c=="C":return "接続詞"
    if c in ("R","Rd"):return "前置詞"+("・定冠詞融合" if c=="Rd" else "")
    if c=="To":return "対格標識"
    if c=="Td":return "定冠詞"
    if c=="Tr":return "関係詞"
    if c=="Te":return "小辞"
    if c=="Tn":return "否定辞"
    if c=="Ti":return "疑問詞"
    if c=="Ta":return "副詞的小辞"
    if c=="D":return "副詞"
    if c.startswith("Sp") and len(c)>=5:return f"人称代名詞接尾辞・{c[2]}人称・{GENDER.get(c[3],c[3])}・{NUMBER.get(c[4],c[4])}"
    if c=="Sn":return "語尾のヌン"
    if c in ("Sh","Sd"):return "方向接尾辞 ה"
    if c.startswith("V") and len(c)>=3:
        stem=STEMS.get(c[1],c[1]); asp=ASPECTS.get(c[2],c[2]); rest=c[3:]; bits=[f"動詞・語幹：{stem}",f"形：{asp}"]
        if rest and rest[0].isdigit():bits.append(f"{rest[0]}人称");rest=rest[1:]
        if rest and rest[0] in GENDER:bits.append(GENDER[rest[0]]);rest=rest[1:]
        if rest and rest[0] in NUMBER:bits.append(NUMBER[rest[0]]);rest=rest[1:]
        if rest and rest[0] in STATE:bits.append(STATE[rest[0]])
        return "・".join(bits)
    if c.startswith("N"):
        if len(c)>1 and c[1] in ("p","g"):return "固有名詞"
        rest=c[2:] if len(c)>1 else ""; bits=["名詞"]
        if rest and rest[0] in GENDER:bits.append(GENDER[rest[0]]);rest=rest[1:]
        if rest and rest[0] in NUMBER:bits.append(NUMBER[rest[0]]);rest=rest[1:]
        if rest and rest[0] in STATE:bits.append(STATE[rest[0]])
        return "・".join(bits)
    if c.startswith("A"):return "数詞/形容詞・"+c[1:]
    if c.startswith("P"):return "代名詞・"+c[1:]
    return c

def morph_ja(code):return "／".join(dec(c) for c in (code[1:] if code.startswith("H") else code).split("/"))

def extract(xml_bytes,chapter,start,end):
    root=ET.fromstring(xml_bytes); result={}
    for v in root.findall(".//o:verse",NS):
        oid=v.attrib.get("osisID","")
        if not oid.startswith(f"Gen.{chapter}."):continue
        n=int(oid.rsplit(".",1)[1])
        if not start<=n<=end:continue
        children=list(v); rows=[]
        for i,ch in enumerate(children):
            if ch.tag!="{http://www.bibletechnologies.net/2003/OSIS/namespace}w":continue
            sep=" "; j=i+1
            while j<len(children) and children[j].tag!="{http://www.bibletechnologies.net/2003/OSIS/namespace}w":
                typ=children[j].attrib.get("type")
                if typ=="x-maqqef":sep="־";break
                if typ=="x-sof-pasuq":sep="׃";break
                j+=1
            rows.append({"surface":(ch.text or "").replace("/",""),"separator_after":sep,"lemma_code":ch.attrib.get("lemma",""),"morph_code":ch.attrib.get("morph","")})
        result[n]=rows
    return result

def main():
    if len(sys.argv)!=3:raise SystemExit("usage: enrich_morphhb.py <input-current.json> <output-current.json>")
    src=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")); p=src["passage"]
    if p["book"]!="Genesis":raise SystemExit("enricher currently supports Genesis only")
    extracted=extract(get(GEN_URL),p["chapter"],p["start_verse"],p["end_verse"]); strongs=strong_dict(get(STRONGS_URL))
    for verse in src["verses"]:
        n=verse["verse"]; rows=extracted.get(n); glosses=verse.pop("glosses",None)
        if rows is None:raise SystemExit(f"missing MorphHB verse {n}")
        if glosses is None or len(glosses)!=len(rows):raise SystemExit(f"verse {n}: contextual gloss count {0 if glosses is None else len(glosses)} != MorphHB word count {len(rows)}")
        verse["words"]=[{"surface":r["surface"],"separator_after":r["separator_after"],"gloss":g,"lemma":lemma_hebrew(r["lemma_code"],strongs),"pos":pos_ja(r["morph_code"]),"morph":morph_ja(r["morph_code"]),"morph_code":r["morph_code"]} for r,g in zip(rows,glosses)]
        verse["hebrew"]="".join(w["surface"]+w["separator_after"] for w in verse["words"])
    src["summary"]=src.get("summary","")
    Path(sys.argv[2]).parent.mkdir(parents=True,exist_ok=True); Path(sys.argv[2]).write_text(json.dumps(src,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"PASS: enriched verses={len(src['verses'])} morphhb={MORPHHB_SHA[:12]} strongs={STRONGS_SHA[:12]}")
if __name__=="__main__":main()
