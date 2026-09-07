"""Finalize a verified replacement without touching any other Torah page."""
import json, os, sys, traceback
from pathlib import Path
from prepare_notion_html import request_json

run=Path(sys.argv[1]); old_id=sys.argv[2]; new_id=sys.argv[3]; title=sys.argv[4]
error_path=run/'replacement-finalize-error.json'
try:
    token=os.environ['NOTION_TOKEN']
    old=request_json('GET',f'/pages/{old_id}',token)
    new=request_json('GET',f'/pages/{new_id}',token)
    assert new.get('cover',{}).get('type')=='file', 'Replacement cover is not verified'
    if not old.get('in_trash'):
        request_json('PATCH',f'/pages/{old_id}',token,json={'in_trash':True})

    title_key=next((name for name,value in new.get('properties',{}).items()
                    if value.get('type')=='title'), None)
    assert title_key, 'Replacement title property is missing'
    request_json('PATCH',f'/pages/{new_id}',token,json={'properties':{
        title_key:{'title':[{'type':'text','text':{'content':title}}]}
    }})

    old_after=request_json('GET',f'/pages/{old_id}',token)
    new_after=request_json('GET',f'/pages/{new_id}',token)
    assert old_after.get('in_trash') is True, 'Old page trash readback failed'
    actual=''.join(x.get('plain_text','') for x in new_after['properties'][title_key]['title'])
    assert actual==title, f'Replacement title mismatch: {actual}'
    p=run/'delivery.json'; state=json.loads(p.read_text())
    state['replacement']={'status':'PASS','archived_page_id':old_id,'canonical_title':title}
    p.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
    error_path.unlink(missing_ok=True)
    print('PASS: old page archived and replacement renamed')
except Exception as exc:
    error_path.write_text(json.dumps({
        'operation':'FINALIZE_VERIFIED_REPLACEMENT',
        'status':'FAIL',
        'error_type':type(exc).__name__,
        'message':str(exc),
        'old_page_id':old_id,'new_page_id':new_id
    },ensure_ascii=False,indent=2)+'\n')
    raise
