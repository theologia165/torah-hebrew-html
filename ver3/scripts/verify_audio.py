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
    m=json.loads(mp.read_text(encoding='utf-8')); qa=m.get('qa',{})
    if qa.get('MAPPING_CONFIRMED') is not True:fail('MAPPING_CONFIRMED is not true')
    if qa.get('SIGNAL_CHECKED') is not True:fail('SIGNAL_CHECKED is not true')
    if qa.get('MODEL_AUDIO_CHECKED') is not False:fail('MODEL_AUDIO_CHECKED must remain false until model/listening QA exists')
    verses=m.get('verses',[]); p=m['passage']; default_ch=int(p['chapter']); end_ch=int(p.get('end_chapter',default_ch)); actual=[(int(v.get('chapter',default_ch)),int(v['verse'])) for v in verses]
    if not actual or actual[0]!=(default_ch,int(p['start_verse'])) or actual[-1]!=(end_ch,int(p['end_verse'])):fail(f'audio range endpoints mismatch: {actual}')
    for a,b in zip(actual,actual[1:]):
        if b[0]<a[0] or (b[0]==a[0] and b[1]!=a[1]+1) or b[0]>a[0]+1 or (b[0]==a[0]+1 and b[1]!=1):fail(f'audio verse coverage is non-contiguous: {a}->{b}')
    previous_end=None
    for v in verses:
        ch=int(v.get('chapter',default_ch)); n=int(v['verse']); ref=f'{ch}:{n}'
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
        if previous_end is not None and abs(v['boundary_start']-previous_end)>0.001:fail(f'verse {ref}: non-shared adjacent boundary')
        if v['boundary_end']<=v['boundary_start']:fail(f'verse {ref}: invalid boundary order')
        previous_end=v['boundary_end']
    print(f"PASS: AUDIO acceptance verses={len(verses)} MAPPING=PASS SIGNAL=PASS SPEED=PASS MODEL_AUDIO=PENDING")
if __name__=='__main__':main()
