"""Restyle an already delivered page's research blocks without touching verse content or media."""
import json, os, sys
from pathlib import Path

from compose import validate
from deliver import children, json3, plain, verify
from prepare import digest, save
from prepare_notion_html import request_json

def archive(block_id, token):
    request_json('PATCH', f'/blocks/{block_id}', token, json={'archived': True})

def append_after(page_id, after_id, child, token):
    request_json('PATCH', f'/blocks/{page_id}/children', token,
                 json={'after': after_id, 'children': [child]})

def find_index(blocks, kind, text):
    for i, item in enumerate(blocks):
        if item['type'] == kind and plain(item) == text:
            return i
    raise AssertionError(f'Missing expected {kind}: {text}')

def new_payload(run, j, c, old):
    audios=[b['audio']['external']['url'] for b in old['children'] if b['type']=='audio']
    embeds=[b['embed']['url'] for b in old['children'] if b['type']=='embed']
    assert len(audios) == len(embeds) == len(j['verses'])
    routes=[{'ref':v['ref'], 'mode':'GITHUB_PAGES', 'url':url} for v,url in zip(j['verses'],embeds)]
    return json3(j,c,routes,audios)

def main():
    run=Path(sys.argv[1]); token=os.environ['NOTION_TOKEN']
    state_path=run/'delivery.json'
    state=json.loads(state_path.read_text())
    assert state.get('status')=='PASS' and state.get('page_id'), 'Only a delivered page may be restyled'
    j=json.loads((run/'json1.json').read_text())
    c=json.loads((run/'json2.json').read_text())
    validate(j,c)
    old=json.loads((run/'json3.json').read_text())
    expected=new_payload(run,j,c,old)
    page_id=state['page_id']
    current=children(page_id,token)
    verify(old['children'],current,token)

    # Insert each blue chunk callout at its existing location, then archive only its old title/body/source blocks.
    for chunk in c['chunks']:
        current=children(page_id,token)
        index=find_index(current,'heading_2',chunk['heading'])
        assert index > 0, 'Chunk cannot be the first page block'
        count=1 + len(chunk['body'].split('\n\n')) + (1 if chunk['sources'] else 0)
        old_group=current[index:index+count]
        assert len(old_group)==count
        replacement=next(b for b in expected['children']
                         if b['type']=='callout' and plain(b)==chunk['heading'])
        append_after(page_id,current[index-1]['id'],replacement,token)
        for item in old_group: archive(item['id'],token)

    # Keep the existing end-section heading. Replace only its research toggles with one blue Callout.
    current=children(page_id,token)
    index=find_index(current,'heading_2','このアリヤーをさらに学ぶ')
    old_notes=current[index+1:index+1+len(c['aliyah_research'])]
    assert len(old_notes)==len(c['aliyah_research']) and all(x['type']=='toggle' for x in old_notes)
    replacement=next(b for b in expected['children'] if b['type']=='callout' and plain(b)=='研究の窓')
    append_after(page_id,current[index]['id'],replacement,token)
    for item in old_notes: archive(item['id'],token)

    actual=children(page_id,token)
    verify(expected['children'],actual,token)
    save(run/'json3.json',expected)
    state['research_display']={'status':'PASS','chunk_style':'blue_background_callout',
        'aliyah_style':'blue_background_callout_with_toggles','operation':'DISPLAY_ONLY_RESTYLE'}
    state['json3_sha256']=digest(expected)
    state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
    print('PASS: research presentation restyled; verse text, embeds, audio and cover preserved')

if __name__=='__main__': main()
