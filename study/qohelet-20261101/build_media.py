"""Isolated Qohelet study media. Never reads/writes daily request or state."""
import base64, hashlib, json, os, re, subprocess, sys, unicodedata
from pathlib import Path
import requests

ROOT=Path('study/qohelet-20261101')
REFS=['Eccl.9.17','Eccl.9.18']+[f'Eccl.10.{n}' for n in range(1,21)]
BRANCH='study/qohelet-9-17-10-20-20261030'
sys.path.insert(0,str(Path('ver3/scripts').resolve()))
from prepare import source_layout, compact, digest
from audio.processing import make_audio_record
from audio.text import spoken_text

def write(name,data):
    p=ROOT/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')

def commit(message):
    subprocess.run(['git','config','user.name','github-actions[bot]'],check=True)
    subprocess.run(['git','config','user.email','41898282+github-actions[bot]@users.noreply.github.com'],check=True)
    subprocess.run(['git','add',str(ROOT)],check=True)
    if subprocess.run(['git','diff','--cached','--quiet']).returncode:
        subprocess.run(['git','commit','-m',message],check=True)
        subprocess.run(['git','push','origin',f'HEAD:{BRANCH}'],check=True)

def prepare():
    import psycopg
    from psycopg.rows import dict_row
    if (ROOT/'json1.json').exists():return json.loads((ROOT/'json1.json').read_text())
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        source=conn.execute("SELECT code,source_version,license FROM core.corpus_sources WHERE code='morphhb-wlc'").fetchone()
        versions=conn.execute('SELECT DISTINCT sv.source_commit FROM dtworks.source_versions sv JOIN dtworks.verses v ON v.source_version_id=sv.id WHERE v.osis_wlc=ANY(%s)',(REFS,)).fetchall()
        assert len(versions)==1
        sha=versions[0]['source_commit'];assert re.fullmatch('[0-9a-f]{40}',sha)
        response=requests.get(f'https://raw.githubusercontent.com/openscriptures/morphhb/{sha}/wlc/Eccl.xml',timeout=60);response.raise_for_status()
        layouts=source_layout(response.content,REFS)
        tokens=conn.execute('''SELECT t.*,
        (SELECT to_jsonb(l) FROM core.lexemes l WHERE l.id=t.primary_lexeme_id) AS lexeme,
        COALESCE((SELECT jsonb_agg(to_jsonb(m) ORDER BY m.segment_index) FROM dtworks.morph_segments m WHERE m.token_id=t.id),'[]') AS morph_segments,
        COALESCE((SELECT jsonb_agg(to_jsonb(l) ORDER BY l.lemma_index) FROM dtworks.token_lemmas l WHERE l.token_id=t.id),'[]') AS lemma_components,
        v.osis_wlc AS ref FROM dtworks.tokens t JOIN dtworks.verses v ON v.id=t.verse_id
        WHERE v.osis_wlc=ANY(%s) ORDER BY v.chapter_wlc,v.verse_wlc,t.token_index''',(REFS,)).fetchall()
        grouped={ref:[] for ref in REFS}
        for t in tokens:grouped[t.pop('ref')].append(t)
        verses=[]
        for ref in REFS:
            ts=grouped[ref];ws=layouts[ref]['words'];assert len(ts)==len(ws)>0,ref
            for i,(t,w) in enumerate(zip(ts,ws),1):
                assert t['token_index']==i
                assert all(t[k]==w[k] for k in ('surface','lemma_raw','morph_raw')),f'{ref}:{i}'
            verses.append({'ref':ref,'reference_system':'WLC','layout':layouts[ref],'mapped_refs':[],'tokens':ts})
        j={'schema_version':'3.0-json1','generated_by':'isolated-study-read-only-neon','request':{'run_id':'901-qohelet-20261101-r1','sequence':'901','source':'morphhb-wlc','book':'Eccl','book_jp':'伝道者の書','refs':REFS,'passage':{'book':'Ecclesiastes','chapter':9,'end_chapter':10,'start_verse':17,'end_verse':20,'display':'伝道者の書9:17–10:20'}},'source':dict(source,morphhb_commit=sha),'verses':verses}
    write('json1.json',j);write('json1.1.json',compact(j))
    commit('Export read-only Neon text for Qohelet 9:17–10:20 study')
    return j

def observe(path,expected):
    prompt=('Listen to the actual Biblical Hebrew recording. Transcribe only what is audible before comparing. Do not fill omissions from the supplied reference. Return JSON only: heard_text, first_word, last_word, missing_words, extra_words, clipped_words, word_order (PASS/FAIL/UNCERTAIN), no_other_verse (PASS/FAIL/UNCERTAIN), no_truncation (PASS/FAIL/UNCERTAIN), intelligibility (PASS/FAIL/UNCERTAIN), evidence. Standard Israeli/Biblical pronunciation and mater-lectionis spelling variants are not errors. Reference: '+expected)
    response=requests.post('https://api.openai.com/v1/chat/completions',headers={'Authorization':'Bearer '+os.environ['OPENAI_API_KEY']},json={'model':'gpt-audio','modalities':['text'],'temperature':0,'max_tokens':1800,'store':False,'messages':[{'role':'user','content':[{'type':'text','text':prompt},{'type':'input_audio','input_audio':{'format':'mp3','data':base64.b64encode(path.read_bytes()).decode()}}]}]},timeout=180)
    response.raise_for_status();payload=response.json();raw=payload['choices'][0]['message']['content'].strip()
    if raw.startswith('```'):raw=raw.split('\n',1)[1].rsplit('```',1)[0]
    return {'observation':json.loads(raw),'model':payload['model'],'request_id':response.headers.get('x-request-id'),'response_id':payload['id']}

def main():
    ROOT.mkdir(parents=True,exist_ok=True);j=prepare()
    policy=json.loads(Path('ver3/config/audio-fallback.json').read_text())['openai_tts']
    audio=ROOT/'audio';audio.mkdir(exist_ok=True)
    manifest=json.loads((ROOT/'audio_manifest.json').read_text()) if (ROOT/'audio_manifest.json').exists() else {'source':'OPENAI_TTS','source_reason':'PocketTorah covers Torah, not Qohelet; no approved verse-separated Qohelet source in the production registry','disclosure':policy['required_disclosure'],'verses':[],'status':'IN_PROGRESS'}
    byref={x['osis_ref']:x for x in manifest['verses']}
    try:
        for v in j['verses']:
            ref=v['ref']
            if ref in byref:continue
            words=[t for t,w in zip(v['tokens'],v['layout']['words']) if w.get('read_aloud',True)]
            expected=spoken_text(words);stem=ref.replace('.','-').lower();r1=audio/(stem+'_ai_r1.mp3');r2=audio/(stem+'_ai_r2.mp3')
            response=requests.post('https://api.openai.com/v1/audio/speech',headers={'Authorization':'Bearer '+os.environ['OPENAI_API_KEY']},json={'model':policy['model'],'voice':policy['voice'],'input':expected,'instructions':policy['instructions']+' Speak at a deliberate, clear pace. Finish the entire final word naturally.','response_format':'mp3'},timeout=180)
            response.raise_for_status();r1.write_bytes(response.content)
            rec=make_audio_record(ref,{'words':words},r1,r2,'OPENAI_TTS',policy['required_disclosure'],{'ai_model':policy['model'],'ai_voice':policy['voice'],'openai_request_id':response.headers.get('x-request-id')})
            review=observe(r2,expected)
            rec.update(osis_ref=ref,expected_text=expected,spoken_text_sha256=hashlib.sha256(expected.encode()).hexdigest(),r1_sha256=hashlib.sha256(r1.read_bytes()).hexdigest(),r2_sha256=hashlib.sha256(r2.read_bytes()).hexdigest(),model_observation=review,MODEL_AUDIO_STATUS='OBSERVED_AWAITING_WORK_REVIEW',audio_url=f'https://raw.githubusercontent.com/theologia165/torah-hebrew-html/{BRANCH}/{r2.as_posix()}')
            manifest['verses'].append(rec);write('audio_manifest.json',manifest)
            commit('Save independently verified Qohelet verse audio '+ref)
            print('AUDIO_OBSERVED',ref,review['observation'].get('no_truncation'),flush=True)
        manifest['status']='OBSERVATIONS_COMPLETE_AWAITING_WORK_REVIEW';write('audio_manifest.json',manifest)
    finally:commit('Checkpoint isolated Qohelet study audio and observations')

if __name__=='__main__':main()
