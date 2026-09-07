"""Finalize a verified replacement without touching any other Torah page."""
import json, os, sys
from pathlib import Path
from prepare_notion_html import request_json

run=Path(sys.argv[1]); old_id=sys.argv[2]; new_id=sys.argv[3]; title=sys.argv[4]
token=os.environ['NOTION_TOKEN']
old=request_json('GET',f'/pages/{old_id}',token)
assert not old.get('archived'), 'Old page is already archived'
new=request_json('GET',f'/pages/{new_id}',token)
assert new.get('cover',{}).get('type')=='file', 'Replacement cover is not verified'
request_json('PATCH',f'/pages/{old_id}',token,json={'archived':True})
request_json('PATCH',f'/pages/{new_id}',token,json={'properties':{'title':{'title':[{'type':'text','text':{'content':title}}]}}})
old_after=request_json('GET',f'/pages/{old_id}',token)
new_after=request_json('GET',f'/pages/{new_id}',token)
assert old_after.get('archived') is True, 'Old page archive readback failed'
actual=''.join(x.get('plain_text','') for x in new_after['properties']['title']['title'])
assert actual==title, f'Replacement title mismatch: {actual}'
p=run/'delivery.json'; state=json.loads(p.read_text())
state['replacement']={'status':'PASS','archived_page_id':old_id,'canonical_title':title}
p.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
print('PASS: old page archived and replacement renamed')
