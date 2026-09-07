"""Two-phase Actions entry point. The ChatGPT handoff is a committed JSON1.1."""
import json, os, subprocess, sys
from pathlib import Path
from prepare import validate_request

def cmd(*args): subprocess.run(args,check=True)
def commit_run(run,message):
    if not os.getenv('GITHUB_ACTIONS'): return
    cmd('git','config','user.name','github-actions[bot]')
    cmd('git','config','user.email','41898282+github-actions[bot]@users.noreply.github.com')
    cmd('git','add',str(run))
    if subprocess.run(['git','diff','--cached','--quiet']).returncode:
        cmd('git','commit','-m',message)
        cmd('git','push','origin','HEAD:asaichi-torah-ver3')

def publish_pages(run,routes):
    assert all(r['mode']=='GITHUB_PAGES' for r in routes), 'Ver.3 requires Pages for every verse'
    pending=routes
    if not pending: return
    import requests
    checkout=Path('/tmp/torah-ver3-pages')
    cmd('git','fetch','origin','main')
    cmd('git','worktree','add',str(checkout),'origin/main')
    j=json.loads((run/'json1.json').read_text())
    destination=checkout/'ver3-public'/run.name; destination.mkdir(parents=True,exist_ok=True)
    for r in pending:
        _,ch,n=r['ref'].split('.')
        filename=f'{j["request"]["passage"]["book"].lower()}-{ch}-{n}.html'
        source=run/'html'/filename; target=destination/filename
        if target.exists(): assert target.read_bytes()==source.read_bytes(), 'Immutable Pages conflict'
        else: target.write_bytes(source.read_bytes())
        r['url']=f'https://theologia165.github.io/torah-hebrew-html/ver3-public/{run.name}/{filename}'
    cmd('git','-C',str(checkout),'add','ver3-public')
    if subprocess.run(['git','-C',str(checkout),'diff','--cached','--quiet']).returncode:
        cmd('git','-C',str(checkout),'commit','-m','Publish all Ver.3 verse HTML to GitHub Pages')
        cmd('git','-C',str(checkout),'push','origin','HEAD:main')
    # GITHUB_TOKEN pushes do not trigger branch-based Pages builds automatically.
    response=requests.post('https://api.github.com/repos/theologia165/torah-hebrew-html/pages/builds',
        headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],
                 'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'},timeout=30)
    response.raise_for_status()
    import time
    for r in pending:
        _,ch,n=r['ref'].split('.')
        expected=(destination/f'{j["request"]["passage"]["book"].lower()}-{ch}-{n}.html').read_bytes()
        for attempt in range(30):
            try:
                response=requests.get(r['url'],timeout=30)
                if response.ok and response.content==expected: break
            except requests.RequestException:
                pass
            time.sleep(10)
        else: raise ValueError('Pages HTML not yet published: '+r['ref'])
    (run/'html-route.json').write_text(json.dumps(routes,ensure_ascii=False,indent=2)+'\n')

def main():
    request=Path('ver3/request.json'); r=json.loads(request.read_text()); validate_request(r)
    assert r['mode'] in ('prepare','publish','acceptance')
    run=Path('ver3/runs')/r['run_id']; run.mkdir(parents=True,exist_ok=True)
    state_path=run/'delivery.json'
    if state_path.exists() and json.loads(state_path.read_text()).get('status')=='PASS':
        # Completed pages can include user-approved edits. Never replay the old JSON3.
        cmd(sys.executable,'ver3/scripts/test_contracts.py',str(run))
        print('SKIP_COMPLETED_DELIVERY: contract tests passed; existing Notion page unchanged')
        return
    try:
        cmd(sys.executable,'ver3/scripts/prepare.py',str(request))
        commit_run(run,'Export Neon JSON1 and ChatGPT JSON1.1')
        if r['mode']=='acceptance':
            cmd(sys.executable,'ver3/scripts/test_contracts.py',str(run))
            # Full-aliyah source -> independent per-verse MP3, using DB token counts.
            j=json.loads((run/'json1.json').read_text())
            audio_input={'sequence':r['sequence'],'passage':r['passage'],'verses':[
              {'chapter':int(v['ref'].split('.')[1]),'verse':int(v['ref'].split('.')[2]),'words':[t for t,w in zip(v['tokens'],v['layout']['words']) if w.get('read_aloud',True)]} for v in j['verses']]}
            tmp=Path('/tmp/ver3-audio-input.json'); tmp.write_text(json.dumps(audio_input))
            cmd(sys.executable,'ver3/scripts/build_audio.py',str(tmp),'/tmp/ver3-audio')
            cmd(sys.executable,'ver3/scripts/verify_audio.py','/tmp/ver3-audio')
            manifest=json.loads(Path('/tmp/ver3-audio/audio_manifest.json').read_text())
            (run/'audio-acceptance.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
            print('PASS: acceptance only; no Notion page or email created')
            return
        if not (run/'json2.json').exists():
            print('WAITING_FOR_JSON2: ChatGPT must read '+str(run/'json1.1.json')); return
        cmd(sys.executable,'ver3/scripts/compose.py',str(run))
        audio=run/'audio'
        if not (audio/'audio_manifest.json').exists():
            cmd(sys.executable,'ver3/scripts/build_audio.py',str(run/'audio-input.json'),str(audio))
            # Keep r1 and r2, omit the large continuous source from GitHub artifacts.
            for p in audio.glob('*_source.mp3'): p.unlink()
        cmd(sys.executable,'ver3/scripts/verify_audio.py',str(audio))
        commit_run(run,'Build verified Ver.3 HTML and per-verse audio')
        if r['mode']=='publish': cmd(sys.executable,'ver3/scripts/deliver.py',str(run))
    finally:
        commit_run(run,'Record Ver.3 handoff and delivery audit')

if __name__=='__main__': main()
