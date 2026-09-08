"""Restyle an already delivered page's research blocks without touching verse content or media."""
import json, os, sys
from pathlib import Path

from compose import validate
from deliver import children, plain, verify
from prepare import digest, save
from prepare_notion_html import request_json

def color(block, value='blue_background'):
    kind=block['type']
    block[kind]['color']=value

def patch_color(block, token):
    kind=block['type']
    request_json('PATCH', f'/blocks/{block["id"]}', token, json={kind:{'color':'blue_background'}})

def find_index(blocks, kind, text):
    for i, item in enumerate(blocks):
        if item['type'] == kind and plain(item) == text:
            return i
    raise AssertionError(f'Missing expected {kind}: {text}')

def main():
    run=Path(sys.argv[1]); token=os.environ['NOTION_TOKEN']
    state_path=run/'delivery.json'
    state=json.loads(state_path.read_text())
    assert state.get('status')=='PASS' and state.get('page_id'), 'Only a delivered page may be restyled'
    j=json.loads((run/'json1.json').read_text())
    c=json.loads((run/'json2.json').read_text())
    validate(j,c)
    payload=json.loads((run/'json3.json').read_text())
    page_id=state['page_id']
    actual=children(page_id,token)
    verify(payload['children'],actual,token)

    # Preserve every block and its order. Only add Notion's blue_background color attribute.
    for chunk in c['chunks']:
        index=find_index(payload['children'],'heading_2',chunk['heading'])
        count=1 + len(chunk['body'].split('\\n\\n')) + (1 if chunk['sources'] else 0)
        for expected, current in zip(payload['children'][index:index+count],actual[index:index+count]):
            color(expected)
            patch_color(current,token)

    index=find_index(payload['children'],'heading_2','このアリヤーをさらに学ぶ')
    color(payload['children'][index])
    patch_color(actual[index],token)
    for expected,current in zip(payload['children'][index+1:index+1+len(c['aliyah_research'])],
                                actual[index+1:index+1+len(c['aliyah_research'])]):
        assert expected['type']==current['type']=='toggle'
        color(expected)
        patch_color(current,token)

    actual=children(page_id,token)
    verify(payload['children'],actual,token)
    save(run/'json3.json',payload)
    state['research_display']={'status':'PASS','chunk_style':'blue_background_blocks',
        'aliyah_style':'blue_background_blocks','operation':'DISPLAY_ONLY_RESTYLE'}
    state['json3_sha256']=digest(payload)
    state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\\n')
    print('PASS: research backgrounds restyled; verse text, embeds, audio and cover preserved')

if __name__=='__main__': main()
