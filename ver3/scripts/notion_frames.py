"""Create wide HTML-backed frames using one reusable upload, then use Pages."""
import json
from pathlib import Path
import requests
from prepare_notion_html import request_json, upload_html

DUMMY = '<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Frame</title><style>html,body{margin:0;padding:0}</style></head><body></body></html>'
CONFIG = Path('ver3/config/notion-frame.json')

def ensure_upload(token, run):
    config = json.loads(CONFIG.read_text())
    uid = config['file_upload_id']
    info = request_json('GET', f'/file_uploads/{uid}', token)
    if info.get('status') == 'uploaded':
        return uid
    # Expired uploads cannot be reused; replace once per run, never once per verse.
    path = run/'frame-bootstrap.html'
    path.write_text(DUMMY, encoding='utf-8')
    return upload_html(path, token)

def creation_blocks(expected, uid):
    result = json.loads(json.dumps(expected))
    for b in result:
        if b['type'] == 'embed':
            b['embed'] = {'type':'file_upload','file_upload':{'id':uid},'caption':[]}
    return result

def finalize_frames(expected, actual, token):
    """Safe for partial append/resume; never replace an unrelated embed."""
    assert len(actual) <= len(expected), 'Unexpected extra Notion blocks'
    converted = []
    for e, a in zip(expected, actual):
        assert e['type'] == a['type'], 'Frame block order/type mismatch'
        if e['type'] != 'embed':
            continue
        wanted = e['embed']['url']
        current = a['embed'].get('url', '')
        if current == wanted:
            continue
        assert 'frame-bootstrap.html' in current, 'Unexpected embed source; refuse replacement'
        r = requests.get(current, timeout=45)
        r.raise_for_status()
        assert r.content == DUMMY.encode('utf-8'), 'Bootstrap HTML differs'
        request_json('PATCH', f'/blocks/{a["id"]}', token,
                     json={'embed':{'url':wanted,'caption':[]}})
        checked = request_json('GET', f'/blocks/{a["id"]}', token)
        assert checked['embed'].get('url') == wanted
        assert not checked['embed'].get('caption')
        converted.append(a['id'])
    return converted
