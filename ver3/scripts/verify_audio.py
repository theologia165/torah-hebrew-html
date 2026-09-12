#!/usr/bin/env python3
import json,subprocess,sys
from pathlib import Path
TARGET_WPS=0.79306; MAX_DURATION_ERROR=0.090; MAX_WPS_ERROR=0.020
def fail(msg):print(f'FAIL: {msg}',file=sys.stderr);raise SystemExit(1)
def probe(path):
    p=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nokey=1:noprint_wrappers=1',str(path)],text=True,capture_output=True)
    if p.returncode!=0:fail(f'ffprobe failed for {path}: {p.stderr}')
    return float(p.stdout.strip())
def main():
    if len(sys.argv)!=2:fail('usage: verify_audio.py <audio-output-dir>')
    out=Path(sys.argv[1]); mp=out/'audio_manifest.json'
    if not mp.exists():fail('audio_manifest.json missing')
    m=json.loads(mp.read_text(encoding='utf-8')); qa=m.get('qa',{}); status=m.get('status','PASS')
    if status not in ('PASS','PARTIAL'):fail(f'unsupported audio status: {status}')
    if status=='PASS' and qa.get('MAPPING_CONFIRMED') is not True:fail('MAPPING_CONFIRMED is not true')
    if status=='PASS' and qa.get('SIGNAL_CHECKED') is not True:fail('SIGNAL_CHECKED is not true')
    if qa.get('MODEL_AUDIO_CHECKED') is not False:fail('MODEL_AUDIO_CHECKED must remain false until model/listening QA exists')
    verses=m.get('verses',[]); failed=m.get('failed_verses',[]); p=m['passage']; default_ch=int(p['chapter']); end_ch=int(p.get('end_chapter',default_ch)); actual=[(int(v.get('chapter',default_ch)),int(v['verse'])) for v in verses]
    expected=m.get('expected_refs') or [v['ref'] for v in verses]
    implemented_refs=[v['ref'] for v in verses]; failed_refs=[v['ref'] for v in failed]
    if len(implemented_refs)!=len(set(implemented_refs)):fail('duplicate implemented audio refs')
    if len(failed_refs)!=len(set(failed_refs)):fail('duplicate failed audio refs')
    if set(implemented_refs)&set(failed_refs):fail('same ref is both implemented and failed')
    if (status=='PASS') != (not failed):fail('audio status does not match failed_verses')
    if ('AUDIO_DELIVERY_COMPLETE' in qa
            and qa.get('AUDIO_DELIVERY_COMPLETE') is not (not failed)):
        fail('AUDIO_DELIVERY_COMPLETE does not match failed_verses')
    union=set(implemented_refs)|set(failed_refs)
    if union!=set(expected):fail(f'audio PASS/FAILED coverage mismatch: expected={expected} actual={sorted(union)}')
    if status=='PASS' and (not actual or actual[0]!=(default_ch,int(p['start_verse'])) or actual[-1]!=(end_ch,int(p['end_verse']))):fail(f'audio range endpoints mismatch: {actual}')
    previous_end=None; previous_scope=None
    for v in verses:
        ch=int(v.get('chapter',default_ch)); n=int(v['verse']); ref=f'{ch}:{n}'
        origin=v.get('audio_origin','POCKETTORAH')
        if origin not in ('POCKETTORAH','OPEN_BIBLE','OPENAI_TTS'):fail(f'verse {ref}: unsupported audio_origin {origin}')
        if origin=='OPENAI_TTS' and not v.get('ai_disclosure'):fail(f'verse {ref}: AI disclosure missing')
        if origin=='OPEN_BIBLE':
            for key in ('source_url','source_audio_sha256','source_license','source_attribution_label','source_attribution_url','source_verified_on'):
                if not v.get(key):fail(f'verse {ref}: Open.Bible {key} missing')
            if not v['source_url'].startswith('https://') or not v['source_attribution_url'].startswith('https://'):fail(f'verse {ref}: Open.Bible source/attribution URL invalid')
            if len(v['source_audio_sha256'])!=64:fail(f'verse {ref}: Open.Bible source hash invalid')
        for key in ('r1','r2'):
            path=out/v[key]
            if not path.exists() or path.stat().st_size<1000:fail(f'verse {ref}: missing/tiny {key} file')
        d1=probe(out/v['r1']); d2=probe(out/v['r2'])
        if abs(d1-v['r1_duration'])>0.01:fail(f'verse {ref}: r1 manifest duration drift')
        if abs(d2-v['r2_duration'])>0.01:fail(f'verse {ref}: r2 manifest duration drift')
        if v['r2_duration_error']>MAX_DURATION_ERROR:fail(f"verse {ref}: corrected duration error {v['r2_duration_error']:.6f}s > {MAX_DURATION_ERROR}")
        if abs(v['r2_wps']-TARGET_WPS)>MAX_WPS_ERROR:fail(f"verse {ref}: r2 WPS {v['r2_wps']:.6f} outside target {TARGET_WPS}")
        if not 0.25<=v['atempo']<=4.0:fail(f'verse {ref}: atempo outside safety range')
        if v['mean_volume_db']<-55.0:fail(f'verse {ref}: mean volume too low')
        scope=v.get('boundary_scope','POCKETTORAH_CONTINUOUS')
        if previous_end is not None and scope==previous_scope=='POCKETTORAH_CONTINUOUS' and abs(v['boundary_start']-previous_end)>0.001:fail(f'verse {ref}: non-shared adjacent boundary')
        if v['boundary_end']<=v['boundary_start']:fail(f'verse {ref}: invalid boundary order')
        previous_end=v['boundary_end']; previous_scope=scope
    ai_count=sum(v.get('audio_origin')=='OPENAI_TTS' for v in verses)
    open_bible_count=sum(v.get('audio_origin')=='OPEN_BIBLE' for v in verses)
    if bool(ai_count)!=bool(qa.get('AI_DISCLOSURE_REQUIRED',False)):fail('AI_DISCLOSURE_REQUIRED does not match implemented AI audio')
    if ai_count and not (out.parent/'ai-audio-audit.json').exists():fail('AI fallback audit is missing')
    print(f"{status}: AUDIO acceptance implemented={len(verses)} failed={len(failed)} pockettorah={len(verses)-ai_count-open_bible_count} open_bible={open_bible_count} ai={ai_count} MAPPING={'PASS' if status=='PASS' else 'PARTIAL'} SIGNAL={'PASS' if status=='PASS' else 'PARTIAL'} SPEED=PASS_FOR_IMPLEMENTED MODEL_AUDIO=PENDING")
if __name__=='__main__':main()
