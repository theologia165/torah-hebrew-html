"""Publish only this new study's assets and upgrade only its new Notion frames."""
import hashlib,json,os,shutil,subprocess,sys,time
from pathlib import Path
import requests
from render_study import ROOT,REPO,PUBLIC,main as render

PAGE='4098aa46-08ae-81e9-8ba8-fab71338efdd'
sys.path.insert(0,str(REPO/'ver3/scripts'))
from prepare_notion_html import request_json
from notion_frames import ensure_upload,creation_blocks,finalize_frames

def cmd(*args):subprocess.run(args,check=True)
def children(page,token):
    out=[];cursor=''
    while True:
        r=request_json('GET',f'/blocks/{page}/children?page_size=100'+('&start_cursor='+cursor if cursor else ''),token)
        out+=r['results']
        if not r['has_more']:return out
        cursor=r['next_cursor']

def main():
    j=json.loads((ROOT/'json1.json').read_text());refs=[v['ref'] for v in j['verses']]
    render()
    cmd('git','config','user.name','github-actions[bot]');cmd('git','config','user.email','41898282+github-actions[bot]@users.noreply.github.com')
    cmd('git','fetch','origin','main')
    checkout=Path('/tmp/qohelet-study-pages-20261101')
    cmd('git','worktree','add',str(checkout),'origin/main')
    dest=checkout/'study-public/qohelet-20261101';dest.mkdir(parents=True,exist_ok=True)
    for path in (ROOT/'html').glob('*.html'):
        target=dest/path.name
        if target.exists():assert target.read_bytes()==path.read_bytes(),'Published immutable file conflict'
        else:shutil.copyfile(path,target)
    cmd('git','-C',str(checkout),'add','study-public/qohelet-20261101')
    if subprocess.run(['git','-C',str(checkout),'diff','--cached','--quiet']).returncode:
        cmd('git','-C',str(checkout),'commit','-m','Publish Qohelet 9:17–10:20 scholarly Hebrew study assets')
        cmd('git','-C',str(checkout),'push','origin','HEAD:main')
    r=requests.post('https://api.github.com/repos/theologia165/torah-hebrew-html/pages/builds',headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json'},timeout=30);r.raise_for_status()
    audit={'page_id':PAGE,'html':[],'audio':[]}
    for ref in refs:
        name=ref.replace('.','-').lower()+'.html';url=PUBLIC+name;expected=(ROOT/'html'/name).read_bytes()
        for attempt in range(30):
            r=requests.get(url,timeout=30)
            if r.ok and r.content==expected:break
            time.sleep(10)
        else:raise RuntimeError('Pages asset missing or different: '+ref)
        audit['html'].append({'ref':ref,'url':url,'sha256':hashlib.sha256(expected).hexdigest()})
    print('PASS: all 22 published HTML files byte-verified',flush=True)
    token=os.environ['NOTION_TOKEN'];blocks=children(PAGE,token)
    frames=[b for b in blocks if b['type']=='embed'];audios=[b for b in blocks if b['type']=='audio']
    assert len(frames)==len(audios)==22
    urls=[x['url'] for x in audit['html']]
    assert [b['embed']['url'] for b in frames]==urls
    manifest=json.loads((ROOT/'audio_manifest.json').read_text())
    assert len(manifest['verses'])==22
    for b,m in zip(audios,manifest['verses']):
        assert b['audio']['external']['url']==m['audio_url']
        r=requests.get(m['audio_url'],timeout=60);r.raise_for_status()
        assert hashlib.sha256(r.content).hexdigest()==m['r2_sha256']
        audit['audio'].append({'ref':m['osis_ref'],'sha256':m['r2_sha256']})
    done=ROOT/'frame-upgrade.json'
    if not done.exists():
        uid=ensure_upload(token,ROOT)
        for old,url in zip(frames,urls):
            expected={'object':'block','type':'embed','embed':{'url':url,'caption':[]}}
            created=request_json('PATCH',f'/blocks/{PAGE}/children',token,json={'position':{'type':'after_block','after_block':{'id':old['id']}},'children':creation_blocks([expected],uid)})['results'][0]
            finalize_frames([expected],[created],token)
            request_json('DELETE',f'/blocks/{old["id"]}',token)
        done.write_text(json.dumps({'page_id':PAGE,'status':'UPGRADED_22_HTML_BACKED_FRAMES'}))
    got=children(PAGE,token)
    assert [b['embed']['url'] for b in got if b['type']=='embed']==urls
    assert len([b for b in got if b['type']=='audio'])==22
    assert len([b for b in got if b['type']=='toggle'])==22
    audit['status']='HTML_AUDIO_NOTION_READBACK_PASS'
    (ROOT/'delivery-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
    cmd('git','add',str(ROOT/'frame-upgrade.json'),str(ROOT/'delivery-audit.json'))
    if subprocess.run(['git','diff','--cached','--quiet']).returncode:
        cmd('git','commit','-m','Verify 22 Notion Hebrew frames and verse audio assets')
        cmd('git','push','origin','HEAD:study/qohelet-9-17-10-20-20261030')
    print('PASS: Notion has 22 HTML-backed frames, 22 matching MP3s, 22 research toggles',flush=True)

if __name__=='__main__':main()
