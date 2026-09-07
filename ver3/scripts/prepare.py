"""GitHub Actions: validate pinned layout against Neon, then export JSON1/1.1."""
import hashlib, json, os, re, sys, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if path.exists() and path.read_text() != text:
        raise ValueError(f'Immutable artifact differs: {path}; use a new run_id')
    path.write_text(text)

def validate_request(r):
    assert re.fullmatch(r'[0-9]{3}-[a-zA-Z0-9-]+', r['run_id'])
    assert re.fullmatch(r'[0-9]{3}', r['sequence'])
    assert r['run_id'].startswith(r['sequence']+'-')
    assert r['source'] == 'morphhb-wlc'
    assert r['book'] in ('Gen','Exod','Lev','Num','Deut')
    assert r['passage']['book']==dict(Gen='Genesis',Exod='Exodus',Lev='Leviticus',Num='Numbers',Deut='Deuteronomy')[r['book']]
    assert r['refs'] and len(r['refs']) == len(set(r['refs']))
    for ref in r['refs']:
        assert re.fullmatch(re.escape(r['book'])+r'\.[1-9][0-9]*\.[1-9][0-9]*',ref)
    p=r['passage']
    assert r['refs'][0]==f'{r["book"]}.{p["chapter"]}.{p["start_verse"]}'
    assert r['refs'][-1]==f'{r["book"]}.{p.get("end_chapter",p["chapter"])}.{p["end_verse"]}'

def source_layout(xml, refs):
    ns='{http://www.bibletechnologies.net/2003/OSIS/namespace}'
    all_verses=list(ET.fromstring(xml).iter(ns+'verse'))
    canonical=[v.get('osisID') for v in all_verses]
    assert canonical[canonical.index(refs[0]):canonical.index(refs[-1])+1]==refs, 'Requested verse coverage/order has gaps'
    result={}
    for v in all_verses:
        ref=v.get('osisID')
        if ref not in refs: continue
        words=[]; notes=[]
        for child in v:
            if child.tag==ns+'w':
                words.append({'surface':''.join(child.itertext()).replace('/',''),
                              'lemma_raw':child.get('lemma',''), 'morph_raw':child.get('morph',''),
                              'separator_after':' '})
            elif child.tag==ns+'seg' and words:
                marker=''.join(child.itertext())
                if marker:
                    if child.get('type') in ('x-maqqef','x-sof-pasuq'):
                        words[-1]['separator_after']=marker
                    else: words[-1]['separator_after']+=marker+' '
            elif child.tag==ns+'note':
                notes.append(ET.tostring(child,encoding='unicode'))
        result[ref]={'words':words,'notes_xml':notes,
                     'hebrew':''.join(w['surface']+w['separator_after'] for w in words)}
    assert set(result)==set(refs), 'Pinned source has missing verses'
    return result

def compact(j):
    return {'schema_version':'3.0-json1.1','run_id':j['request']['run_id'],
            'request':j['request'],'json1_sha256':digest(j),'source':j['source'],
            'verses':[{'ref':v['ref'],'hebrew':v['layout']['hebrew'],
                       'textual_notes':v['layout']['notes_xml'],'mapped_refs':v['mapped_refs'],
                       'tokens':[{'token_id':t['id'],'token_index':t['token_index'],
                                  'surface':t['surface'],'lemma_raw':t['lemma_raw'],
                                  'morph_raw':t['morph_raw'],'lexeme':t['lexeme'],
                                  'morph_segments':t['morph_segments']}
                                 for t in v['tokens']]} for v in j['verses']]}

def main():
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
    request=json.loads(Path(sys.argv[1]).read_text()); validate_request(request)
    dest=Path('ver3/runs')/request['run_id']
    if (dest/'json1.json').exists():
        j=json.loads((dest/'json1.json').read_text()); assert j['request']==request
        save(dest/'json1.1.json',compact(j)); print('PASS: immutable JSON1 reused'); return
    # No credentials are written into artifacts or logs.
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        source=conn.execute('SELECT code,source_version,license FROM core.corpus_sources WHERE code=%s',(request['source'],)).fetchone()
        assert source and source['source_version']
        versions=conn.execute('SELECT DISTINCT sv.source_commit FROM dtworks.source_versions sv JOIN dtworks.verses v ON v.source_version_id=sv.id WHERE v.osis_wlc=ANY(%s)',(request['refs'],)).fetchall()
        assert len(versions)==1 and re.fullmatch('[0-9a-f]{40}',versions[0]['source_commit'])
        sha=versions[0]['source_commit']
        url=f'https://raw.githubusercontent.com/openscriptures/morphhb/{sha}/wlc/{request["book"]}.xml'
        with urllib.request.urlopen(url,timeout=60) as response: xml=response.read()
        layouts=source_layout(xml,request['refs'])
        tokens=conn.execute('''SELECT t.*,
          (SELECT to_jsonb(l) FROM core.lexemes l WHERE l.id=t.primary_lexeme_id) AS lexeme,
          COALESCE((SELECT jsonb_agg(to_jsonb(m) ORDER BY m.segment_index) FROM dtworks.morph_segments m WHERE m.token_id=t.id),'[]') AS morph_segments,
          COALESCE((SELECT jsonb_agg(to_jsonb(l) ORDER BY l.lemma_index) FROM dtworks.token_lemmas l WHERE l.token_id=t.id),'[]') AS lemma_components,
          v.osis_wlc AS ref
          FROM dtworks.tokens t JOIN dtworks.verses v ON v.id=t.verse_id
          WHERE v.osis_wlc=ANY(%s) ORDER BY v.chapter_wlc,v.verse_wlc,t.token_index''',(request['refs'],)).fetchall()
        grouped={ref:[] for ref in request['refs']}
        for t in tokens: grouped[t.pop('ref')].append(t)
        for ref, ts in grouped.items():
            ws=layouts[ref]['words']; assert len(ts)==len(ws)>0, f'Token count mismatch: {ref}'
            for i,(t,w) in enumerate(zip(ts,ws),1):
                assert t['token_index']==i
                assert all(t[k]==w[k] for k in ('surface','lemma_raw','morph_raw')), f'Neon/source mismatch: {ref}:{i}'
        # Only additive layout data for this run. Legacy corpus/search/reference layers stay intact.
        size=conn.execute('SELECT pg_database_size(current_database()) AS size').fetchone()['size']
        assert size+len(xml)+10_000_000 < 480_000_000, 'Insufficient storage headroom for layout cache'
        conn.execute('''CREATE TABLE IF NOT EXISTS dtworks.verse_layout_v3 (
          source_commit text NOT NULL, osis_ref text NOT NULL, layout jsonb NOT NULL,
          PRIMARY KEY(source_commit,osis_ref))''')
        verses=[]
        for ref in request['refs']:
            conn.execute('INSERT INTO dtworks.verse_layout_v3 VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',(sha,ref,Jsonb(layouts[ref])))
            layout=conn.execute('SELECT layout FROM dtworks.verse_layout_v3 WHERE source_commit=%s AND osis_ref=%s',(sha,ref)).fetchone()['layout']
            assert layout==layouts[ref], f'Existing layout differs: {ref}'
            mappings=conn.execute('''SELECT rs.code AS system,rp.osis_ref AS ref,rl.relation_type AS relation
              FROM core.reference_links rl JOIN core.reference_passages rp ON rp.id=rl.linked_passage_id
              JOIN core.reference_systems rs ON rs.id=rp.reference_system_id
              WHERE rl.passage_id=(SELECT rp2.id FROM core.reference_passages rp2
                JOIN core.reference_systems rs2 ON rs2.id=rp2.reference_system_id
                WHERE rp2.osis_ref=%s AND rs2.code='WLC') ORDER BY rs.code,rp.osis_ref''',(ref,)).fetchall()
            verses.append({'ref':ref,'reference_system':'WLC','layout':layout,'mapped_refs':mappings,'tokens':grouped[ref]})
        j={'schema_version':'3.0-json1','generated_by':'github-actions-neon','request':request,
           'source':dict(source, morphhb_commit=sha),'verses':verses}
    save(dest/'json1.json',j); save(dest/'json1.1.json',compact(j))
    print(f'PASS: JSON1 -> JSON1.1: {len(verses)} verses; database bytes before layout={size}')

if __name__=='__main__': main()
