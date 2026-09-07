"""Acceptance against real JSON1; synthetic prose is never eligible for delivery."""
import copy, json, sys
from pathlib import Path
from prepare import compact,digest
from compose import validate,render
from deliver import json3

def fixture(j):
    return {'schema_version':'3.0-json2','run_id':j['request']['run_id'],
      'json1_sha256':digest(j),'json1_1_sha256':digest(compact(j)),
      'title':'受入検査専用','summary':'受入検査専用の文章です。','conclusion':'検証終了。',
      'verses':[{'ref':v['ref'],'translation':f'{v["ref"]} の検証訳。',
        'short_commentary':f'{v["ref"]} の検証説明。',
        'glosses':[{'token_id':t['id'],'ja':f'語{t["token_index"]}'} for t in v['tokens']],
        'sections':[{'heading':'本文と文法','body':f'{v["ref"]} の文法検証。',
                     'sources':[{'label':'MorphHB source','url':'https://github.com/openscriptures/morphhb'}]},
                    {'heading':'デボーショナルな受けとめ','body':f'{v["ref"]} の受入検査専用本文。','sources':[]}]}
        for v in j['verses']]}

def main():
    run=Path(sys.argv[1]); j=json.loads((run/'json1.json').read_text()); c=fixture(j); assert validate(j,c)
    mutations=[lambda x:x.update(json1_sha256='wrong'),
      lambda x:x['verses'].pop(),
      lambda x:x['verses'][0]['glosses'][0].update(token_id=-1),
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
    p=json3(j,c,routes,[f'https://example.test/{i}_r2.mp3' for i in range(len(routes))])
    assert all('file_upload' not in b['embed'] and b['embed'].get('url','').startswith('https://theologia165.github.io/torah-hebrew-html/ver3-public/') for b in p['children'] if b['type']=='embed')
    bad_routes=copy.deepcopy(routes); bad_routes[0]['mode']='NOTION_ATTACHMENT'
    try: json3(j,c,bad_routes,[f'https://example.test/{i}_r2.mp3' for i in range(len(routes))])
    except AssertionError: pass
    else: raise AssertionError('Attachment route accepted')
    assert sum(b['type']=='audio' for b in p['children'])==len(routes)
    assert sum(b['type']=='embed' for b in p['children'])==len(routes)
    assert all(not b[b['type']].get('caption') for b in p['children'] if b['type'] in ('audio','embed'))
    assert not any(b['type']=='paragraph' and not b['paragraph']['rich_text'] for b in p['children'])
    print(f'PASS: {len(html)} exact DB Hebrew renderings, 6 corrupt handoffs rejected, JSON3 order/captions/citations')

if __name__=='__main__': main()
