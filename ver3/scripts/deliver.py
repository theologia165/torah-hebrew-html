"""Build JSON3, send exactly that payload through Actions, verify Notion blocks."""
import json, os, sys, time
from pathlib import Path
import requests
from prepare import digest, save
from compose import validate
from notion_frames import ensure_upload, creation_blocks, finalize_frames
from prepare_notion_html import request_json

def rt(text, url=None):
    return [{'type':'text','text':dict(content=text,**({'link':{'url':url}} if url else {}))}]
def block(kind,text):
    return {'object':'block','type':kind,kind:{'rich_text':rt(text)}}
def paragraph(text): return block('paragraph',text)
def children(page, token):
    out=[]; cursor=''
    while True:
        d=request_json('GET',f'/blocks/{page}/children?page_size=100'+(f'&start_cursor={cursor}' if cursor else ''),token)
        out+=d['results']
        if not d['has_more']: return out
        cursor=d['next_cursor']

def json3(j,c,routes,audio_urls):
    validate(j,c); req=j['request']; r=req['passage']; default_ch=r['chapter']
    title=f'{req["sequence"]}｜{r["display"].split("｜")[-1]}'
    blocks=[]; verse_handoff=[]
    for text in (r['display'],c['summary']):
        b=block('callout',text); b['callout']['color']='blue_background'; blocks.append(b)
    blocks.append(block('heading_2',c['title']))
    for raw,v,route,audio in zip(j['verses'],c['verses'],routes,audio_urls):
        assert route['ref']==raw['ref']
        _,ch,n=raw['ref'].split('.')
        assert audio.endswith('_r2.mp3'), 'Only physical per-verse study-speed MP3 is deliverable'
        assert route['mode']=='GITHUB_PAGES', 'Ver.3 only embeds GitHub Pages URLs'
        assert route['url'].startswith('https://theologia165.github.io/torah-hebrew-html/ver3-public/')
        embed={'object':'block','type':'embed','embed':{'url':route['url'],'caption':[]}}
        verse_handoff.append({'ref':raw['ref'],'tokens':[{'token_id':t['id'],'token_index':t['token_index'],'surface':t['surface'],'ja':g['ja']} for t,g in zip(raw['tokens'],v['glosses'])]})
        detail=[]
        for section in v['sections']:
            detail.append(block('heading_3',section['heading']))
            for p in section['body'].split('\n\n'):
                detail.append(paragraph(p))
            if section['sources']:
                references=rt('参照：')
                for i,s in enumerate(section['sources']):
                    if i: references+=rt(' ／ ')
                    references+=rt(s['label'],s['url'])
                detail.append({'object':'block','type':'paragraph','paragraph':{'rich_text':references}})
        assert len(detail)<=100, 'Notion toggle children limit exceeded'
        blocks += [block('heading_2',f'{req["book_jp"]} {ch}:{n}'),
                   {'object':'block','type':'audio','audio':{'type':'external','external':{'url':audio},'caption':[]}},
                   paragraph('私訳：'+v['translation']),block('heading_3','ヘブライ語'),embed,
                   paragraph('簡易な説明：'+v['short_commentary']),
                   {'object':'block','type':'toggle','toggle':{'rich_text':rt('詳しい解説'),'children':detail}}]
    blocks += [block('heading_2','まとめ'),paragraph(c['conclusion'])]
    # Required source attribution lives in a compact reference section, never in the HTML footer.
    b=paragraph('本文資料：Open Scriptures Hebrew Bible / MorphHB (WLC), CC BY 4.0')
    b['paragraph']['rich_text']=rt('本文資料：Open Scriptures Hebrew Bible / MorphHB (WLC), CC BY 4.0','https://github.com/openscriptures/morphhb')
    blocks.append(b)
    assert len(routes)==len(audio_urls)==len(j['verses'])
    return {'schema_version':'3.0-json3','run_id':req['run_id'],'json1_sha256':digest(j),
            'json2_sha256':digest(c),'title':title,'verses':verse_handoff,'children':blocks}

def plain(b):
    p=b[b['type']]
    return ''.join(x.get('plain_text',x.get('text',{}).get('content','')) for x in p.get('rich_text',[]))

def verify(expected,actual,token):
    assert len(expected)==len(actual), 'Notion block count/order mismatch'
    for e,a in zip(expected,actual):
        t=e['type']; assert a['type']==t, f'Notion type mismatch: {t}'
        if t in ('paragraph','heading_2','heading_3','callout','toggle'):
            assert plain(e)==plain(a), f'Notion text differs: {plain(e)[:60]}'
            expected_links=[x['text'].get('link') for x in e[t].get('rich_text',[]) if x.get('text',{}).get('link')]
            actual_links=[x['text'].get('link') for x in a[t].get('rich_text',[]) if x.get('text',{}).get('link')]
            assert expected_links==actual_links, 'Citation links differ'
        if t=='toggle': verify(e[t]['children'],children(a['id'],token),token)
        if t in ('audio','embed'):
            assert not a[t].get('caption'), 'Unexpected media caption'
        if t=='audio': assert e[t]['external']['url']==a[t].get('external',{}).get('url')
        if t=='embed':
            if 'url' in e[t]: assert e[t]['url']==a[t].get('url')
            else:
                upload=e[t]['file_upload']['id']
                # Notion may expose a hosted URL after resolving file_upload.
                hosted=a[t].get('url') or a[t].get('file',{}).get('url')
                if not hosted: assert a[t].get('file_upload',{}).get('id')==upload
                else:
                    response=requests.get(hosted,timeout=45); response.raise_for_status()
                    expected_html=UPLOAD_HTML[upload]
                    assert response.content==expected_html, 'Attached HTML content mismatch'

UPLOAD_HTML={}

def main():
    run=Path(sys.argv[1]); token=os.environ['NOTION_TOKEN']; parent=os.environ['NOTION_PARENT_PAGE_ID']
    j=json.loads((run/'json1.json').read_text()); c=json.loads((run/'json2.json').read_text()); validate(j,c)
    req=j['request']; seq=req['sequence']; routes=[]; audio_urls=[]
    state_path=run/'delivery.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else {'status':'PENDING','run_id':req['run_id']}
    def checkpoint(): state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
    if state.get('status')=='PASS':
        print('SKIP_COMPLETED_DELIVERY: existing page preserved'); return
    if state.get('page_id'):
        prior_payload=json.loads((run/'json3.json').read_text())
        assert all('url' in b['embed'] and b['embed']['url'].startswith('https://theologia165.github.io/torah-hebrew-html/ver3-public/')
                   for b in prior_payload['children'] if b['type']=='embed'), 'LEGACY_PARTIAL_DELIVERY: reconcile attachments explicitly before resume'
    try:
        # Page ID is persisted before append; a retry resumes this exact run instead of duplicating it.
        if not state.get('page_id'):
            wanted=f'{seq}｜{req["passage"]["display"].split("｜")[-1]}'
            existing=[b for b in children(parent,token) if b['type']=='child_page' and b['child_page']['title']==wanted]
            target=req.get('update_page_id')
            if target:
                assert len(existing)==1 and existing[0]['id'].replace('-','')==target.replace('-',''), 'UPDATE_TARGET_MISMATCH'
            else:
                assert not existing, 'SKIP_EXISTING_PAGE: reconcile prior production run; do not duplicate'
        routes=[{'ref':v['ref'],'mode':'GITHUB_PAGES'} for v in j['verses']]
        from runner import publish_pages
        publish_pages(run,routes)
        manifest=json.loads((run/'audio/audio_manifest.json').read_text())
        assert [v['ref'] for v in manifest['verses']]==['.'.join(x.split('.')[1:]).replace('.',':') for x in req['refs']]
        for v in manifest['verses']:
            url=f'https://raw.githubusercontent.com/theologia165/torah-hebrew-html/asaichi-torah-ver3/{run.as_posix()}/audio/{v["r2"]}'
            response=requests.get(url,timeout=45); response.raise_for_status()
            assert response.content==(run/'audio'/v['r2']).read_bytes(), 'Published audio differs'
            audio_urls.append(url)
        payload=json3(j,c,routes,audio_urls)
        if req.get('update_page_id'):
            # Explicit update: preserve the page and all non-media blocks.
            page_id=req['update_page_id']
            page=request_json('GET',f'/pages/{page_id}',token)
            assert page['parent'].get('page_id','').replace('-','')==parent.replace('-',''), 'Wrong update parent'
            assert ''.join(t.get('plain_text',t.get('text',{}).get('content','')) for t in page['properties']['title']['title'])==payload['title'], 'Wrong update title'
            got=children(page_id,token)
            assert len(got)==len(payload['children']), 'Existing page structure differs'
            for expected,actual in zip(payload['children'],got):
                assert expected['type']==actual['type'], 'Existing block type differs'
                if expected['type'] not in ('audio','embed'):
                    verify([expected],[actual],token)
            save(run/'json3.json',payload); save(run/'original-routes.json',routes)
            snapshot=run/'previous-media.json'
            if not snapshot.exists():
                save(snapshot,{'page_id':page_id,'blocks':[{'id':b['id'],'type':b['type'],b['type']:b[b['type']]} for b in got if b['type'] in ('audio','embed')]})
            state.update(page_id=page_id,page_url=page['url'],status='UPDATING'); checkpoint()
            from runner import commit_run
            commit_run(run,'Checkpoint authorized 050 media update before Notion writes')
            for expected,actual in zip(payload['children'],got):
                kind=expected['type']
                if kind in ('audio','embed'):
                    update={k:v for k,v in expected[kind].items() if k!='type'}
                    request_json('PATCH',f'/blocks/{actual["id"]}',token,json={kind:update})
            verify(payload['children'],children(page_id,token),token)
            state.pop('error',None)
            state.update(status='PASS',verse_count=len(j['verses']),json3_sha256=digest(payload),operation='UPDATE_EXISTING_PAGE'); checkpoint()
            from r2_cover import apply as apply_cover
            apply_cover(req['run_id'],page_id,state_path)
            print('PASS: updated existing page; all text, citations and 10 Pages embeds verified')
            return
        # A resumed page must use its original JSON3 and original attachments.
        if state.get('page_id'):
            payload=json.loads((run/'json3.json').read_text())
            assert payload['json1_sha256']==digest(j) and payload['json2_sha256']==digest(c)
            prior=json.loads((run/'original-routes.json').read_text())
            for r in prior:
                if r['mode']=='NOTION_ATTACHMENT':
                    _,ch,n=r['ref'].split('.')
                    UPLOAD_HTML[r['file_upload_id']]=(run/'html'/f'{req["passage"]["book"].lower()}-{ch}-{n}.html').read_bytes()
        else:
            save(run/'json3.json',payload); save(run/'original-routes.json',routes)
            page=request_json('POST','/pages',token,json={'parent':{'page_id':parent},'properties':{'title':{'type':'title','title':rt(payload['title'])}}})
            state.update(page_id=page['id'],page_url=page['url'],status='CREATED'); checkpoint()
            from runner import commit_run
            commit_run(run,'Checkpoint Ver.3 Notion page identity')
        page_id=state['page_id']; got=children(page_id,token)
        # A previous attempt may have stopped after creating an HTML-backed frame.
        finalize_frames(payload['children'],got,token)
        got=children(page_id,token)
        verify(payload['children'][:len(got)],got,token)
        remaining=payload['children'][len(got):]
        if any(b['type']=='embed' for b in remaining):
            uid=state.get('frame_upload_id') or ensure_upload(token,run)
            state.update(frame_upload_id=uid,frame_method='SHARED_DUMMY_THEN_PAGES')
            checkpoint()
        else:
            uid=None
        while remaining:
            chunk,remaining=remaining[:100],remaining[100:]
            request_json('PATCH',f'/blocks/{page_id}/children',token,json={'children':creation_blocks(chunk,uid)})
            finalize_frames(payload['children'],children(page_id,token),token)
        verify(payload['children'],children(page_id,token),token)
        state.update(status='PASS',verse_count=len(j['verses']),json3_sha256=digest(payload)); checkpoint()
        from r2_cover import apply as apply_cover
        apply_cover(req['run_id'],page_id,state_path)
        print('PASS: JSON3 delivered and every Notion block/text/link/media verified')
    except Exception as e:
        state.update(status='FAIL',error=str(e)); checkpoint(); raise

if __name__=='__main__': main()
