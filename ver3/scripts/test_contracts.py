"""Acceptance against real JSON1; synthetic prose is never eligible for delivery."""
import copy, json, sys
from pathlib import Path
from prepare import compact,digest
from compose import validate,render
from deliver import json3

def fixture(j):
    refs=j['request']['refs']
    return {'schema_version':'3.1-json2','run_id':j['request']['run_id'],
      'json1_sha256':digest(j),'json1_1_sha256':digest(compact(j)),
      'title':'受入検査専用','summary':'受入検査専用の文章です。','conclusion':'検証終了。',
      'verses':[{'ref':v['ref'],'translation':f'{v["ref"]} の検証訳。',
        'short_commentary':f'{v["ref"]} の検証説明。',
        'glosses':[{'token_id':t['id'],'ja':f'語{t["token_index"]}'} for t in v['tokens']],
        'sections':[{'heading':'本文と文法','body':f'{v["ref"]} の文法検証。',
                     'sources':[{'label':'MorphHB source','url':'https://github.com/openscriptures/morphhb'}]},
                    {'heading':'デボーショナルな受けとめ','body':f'{v["ref"]} の受入検査専用本文。','sources':[]}]}
        for v in j['verses']],
      'chunks':[{'id':'acceptance-chunk','heading':'受入検査のまとまり','refs':refs,
                 'after_ref':refs[-1],'body':'受入検査用のチャンク研究。',
                 'sources':[{'label':'MorphHB source','url':'https://github.com/openscriptures/morphhb'}]}],
      'aliyah_research':[{'heading':'受入検査の全体研究','body':'受入検査用の全体研究。',
                          'sources':[{'label':'MorphHB source','url':'https://github.com/openscriptures/morphhb'}]}]}

def main():
    run=Path(sys.argv[1]); j=json.loads((run/'json1.json').read_text()); c=fixture(j); assert validate(j,c)
    mutations=[lambda x:x.update(json1_sha256='wrong'),
      lambda x:x['verses'].pop(),
      lambda x:x['verses'][0]['glosses'][0].update(token_id=-1),
      lambda x:x['verses'][0]['glosses'][0].update(ja=j['verses'][0]['tokens'][0]['surface']),
      lambda x:x['verses'][0].update(translation='וַיֹּאמֶר は言った。'),
      lambda x:x['verses'][0]['sections'].pop(),
      lambda x:x['verses'][1]['sections'][0].update(body=x['verses'][0]['sections'][0]['body'])]
    for mutate in mutations:
        bad=copy.deepcopy(c); mutate(bad)
        try: validate(j,bad)
        except (AssertionError,ValueError): pass
        else: raise AssertionError('Invalid handoff accepted')
    html=[render(a,b,j['request']['book']) for a,b in zip(j['verses'],c['verses'])]
    for s in html:
        assert 'PC：語にマウス' not in s and 'GitHub JSON統合' not in s
        assert 'min-height:800' not in s and 'editorial.json?' not in s
    routes=[{'ref':v['ref'],'mode':'GITHUB_PAGES','url':f'https://theologia165.github.io/torah-hebrew-html/ver3-public/{run.name}/{v["ref"]}.html'} for v in j['verses']]
    audio={v['ref']:f'https://example.test/{i}_r2.mp3' for i,v in enumerate(j['verses'])}
    p=json3(j,c,routes,audio)
    assert all('file_upload' not in b['embed'] and b['embed'].get('url','').startswith('https://theologia165.github.io/torah-hebrew-html/ver3-public/') for b in p['children'] if b['type']=='embed')
    bad_routes=copy.deepcopy(routes); bad_routes[0]['mode']='NOTION_ATTACHMENT'
    try: json3(j,c,bad_routes,audio)
    except AssertionError: pass
    else: raise AssertionError('Attachment route accepted')
    assert sum(b['type']=='audio' for b in p['children'])==len(routes)
    assert sum(b['type']=='embed' for b in p['children'])==len(routes)
    assert all(not b[b['type']].get('caption') for b in p['children'] if b['type'] in ('audio','embed'))
    ai_ref=j['verses'][-1]['ref']
    with_ai=json3(j,c,routes,audio,audio_meta_by_ref={ai_ref:{'audio_origin':'OPENAI_TTS','ai_disclosure':'OpenAIによるAI生成音声'}})
    ai_audio=[b for b in with_ai['children'] if b['type']=='audio' and b['audio']['external']['url']==audio[ai_ref]]
    assert len(ai_audio)==1 and ai_audio[0]['audio']['caption'][0]['text']['content']=='OpenAIによるAI生成音声'
    assert not any(b['type']=='paragraph' and not b['paragraph']['rich_text'] for b in p['children'])
    partial_audio=dict(audio); partial_audio.pop(j['verses'][-1]['ref'])
    partial=json3(j,c,routes,partial_audio,{'audio_status':'PARTIAL','missing_audio_refs':[j['verses'][-1]['ref']]})
    assert sum(b['type']=='audio' for b in partial['children'])==len(routes)-1
    assert partial['media_status']['missing_audio_refs']==[j['verses'][-1]['ref']]
    print(f'PASS: {len(html)} exact DB Hebrew renderings, 6 corrupt handoffs rejected, JSON3 order/captions/citations')

if __name__=='__main__': main()
