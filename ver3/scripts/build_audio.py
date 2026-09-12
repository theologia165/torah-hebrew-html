#!/usr/bin/env python3
import json,re,subprocess,sys,urllib.request,urllib.parse
from pathlib import Path
POCKETTORAH_SHA='8a23287221dd535966ee9914de9a03e71769a469'; BASE_RAW=f'https://raw.githubusercontent.com/rneiss/PocketTorah/{POCKETTORAH_SHA}'; ALIYAH_URL=f'{BASE_RAW}/data/aliyah.json'; TARGET_WPS=0.79306; SILENCE_NOISE_DB=-38; SILENCE_MIN_D=0.08; SIGNAL_WINDOW=1.25
def fail(msg):print(f'FAIL: {msg}',file=sys.stderr);raise SystemExit(1)
def get_bytes(url):
    req=urllib.request.Request(url,headers={'User-Agent':'asaichi-torah-ver3'}); return urllib.request.urlopen(req,timeout=60).read()
def run(cmd):
    p=subprocess.run(cmd,text=True,capture_output=True)
    if p.returncode!=0:fail(f"command failed: {' '.join(cmd)}\n{p.stderr}")
    return p
def duration(path):return float(run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nokey=1:noprint_wrappers=1',str(path)]).stdout.strip())
def mean_volume_db(path):
    p=subprocess.run(['ffmpeg','-hide_banner','-nostats','-i',str(path),'-af','volumedetect','-f','null','-'],text=True,capture_output=True); m=re.search(r'mean_volume:\s*(-?[0-9.]+) dB',p.stderr); return float(m.group(1)) if m else -999.0
def detect_silences(path):
    p=subprocess.run(['ffmpeg','-hide_banner','-nostats','-i',str(path),'-af',f'silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_D}','-f','null','-'],text=True,capture_output=True); starts=[float(x) for x in re.findall(r'silence_start:\s*([0-9.]+)',p.stderr)]; ends=[float(x) for x in re.findall(r'silence_end:\s*([0-9.]+)',p.stderr)]; return [(st,ends[i]) for i,st in enumerate(starts) if i<len(ends) and ends[i]>=st]
def boundary_meta(candidate,silences):
    nearby=[]
    for st,en in silences:
        if en<candidate-SIGNAL_WINDOW or st>candidate+SIGNAL_WINDOW:continue
        nearby.append((min(abs(candidate-st),abs(candidate-en)),st,en))
    rec={'candidate':candidate,'refined':candidate,'method':'label_onset_model_pending'}
    if nearby:
        _,st,en=min(nearby,key=lambda x:x[0]); rec['signal']={'nearest_silence_start':st,'nearest_silence_end':en,'distance_to_silence_end':candidate-en}
    return rec
def resolve_source(data):
    aliyah=json.loads(get_bytes(ALIYAH_URL).decode('utf-8-sig')); p=data['passage']; start_ch=int(p['chapter']); end_ch=int(p.get('end_chapter',start_ch)); begin,end=f"{start_ch}:{p['start_verse']}",f"{end_ch}:{p['end_verse']}"; matches=[]
    for parsha in aliyah['parshiot']['parsha']:
        if not parsha.get('_verse','').startswith(p['book']+' '):continue
        for a in parsha.get('fullkriyah',{}).get('aliyah',[]):
            if a.get('_begin')==begin and a.get('_end')==end and a.get('_num')!='M':matches.append((parsha['_id'],a['_num']))
    if len(matches)!=1:fail(f'PocketTorah aliyah mapping expected 1 match for {begin}-{end}, got {matches}')
    parsha,num=matches[0]; base=f'{parsha}-{num}'; audio_base=re.sub(r"[\s'’]+",'',base); labels_base=base
    tree=json.loads(get_bytes(f'https://api.github.com/repos/rneiss/PocketTorah/git/trees/{POCKETTORAH_SHA}?recursive=1'))
    wanted=f'data/torah/labels/{base}.txt'
    exact=[x['path'] for x in tree['tree'] if x['path'].casefold()==wanted.casefold()]
    if len(exact)!=1: fail(f'Labels filename resolution expected 1 match for {wanted}, got {exact}')
    labels_base=Path(exact[0]).stem
    return {'parsha':parsha,'aliyah':num,'base':base,'audio_base':audio_base,'labels_base':labels_base,'audio_url':f"{BASE_RAW}/data/audio/{urllib.parse.quote(audio_base,safe='')}.mp3",'labels_url':f"{BASE_RAW}/data/torah/labels/{urllib.parse.quote(labels_base,safe='')}.txt"}
def split_mp3(source,start,end,out):run(['ffmpeg','-y','-hide_banner','-loglevel','error','-i',str(source),'-af',f'atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS','-c:a','libmp3lame','-q:a','2',str(out)])
def atempo_chain(factor):
    if factor<=0:fail(f'invalid atempo {factor}')
    values=[]; x=factor
    while x<0.5:values.append(0.5);x/=0.5
    while x>2.0:values.append(2.0);x/=2.0
    values.append(x);return ','.join(f'atempo={v:.9f}' for v in values)
def speed_mp3(src,factor,out):run(['ffmpeg','-y','-hide_banner','-loglevel','error','-i',str(src),'-af',atempo_chain(factor),'-c:a','libmp3lame','-q:a','2',str(out)])
def main():
    if len(sys.argv)!=3:fail('usage: build_audio.py <enriched.json> <audio-output-dir>')
    data=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')); out=Path(sys.argv[2]); out.mkdir(parents=True,exist_ok=True); p=data['passage']; default_ch=int(p['chapter']); cross=int(p.get('end_chapter',default_ch))!=default_ch
    source_meta=resolve_source(data); source=out/f"{source_meta['audio_base']}_source.mp3"; source.write_bytes(get_bytes(source_meta['audio_url'])); labels=[float(x) for x in get_bytes(source_meta['labels_url']).decode('utf-8-sig').strip().split(',') if x.strip()]
    word_counts=[len(v['words']) for v in data['verses']]; total_words=sum(word_counts)
    if len(labels) not in (total_words,total_words+1):fail(f'MAPPING: label count {len(labels)} incompatible with word count {total_words}')
    source_duration=duration(source)
    # Every word onset must exist inside the physical recording.  Some legacy
    # PocketTorah label sets extend beyond a truncated MP3; treating the MP3
    # end as the final verse boundary would create a tiny fragment and an
    # absurd atempo value while hiding the actual source defect.
    outside=[(i+1,t) for i,t in enumerate(labels[:total_words]) if t>source_duration]
    if len(labels)==total_words+1 and labels[-1]<=source_duration+0.25:word_onsets,explicit_end=labels[:-1],labels[-1]
    else:word_onsets,explicit_end=labels[:total_words],source_duration
    if len(word_onsets)!=total_words:fail('MAPPING: could not normalize PocketTorah label count')
    silences=detect_silences(source); cumulative=[0]
    for n in word_counts:cumulative.append(cumulative[-1]+n)
    boundaries=[]
    for i in range(len(data['verses'])+1):
        if i==0:boundaries.append({'candidate':word_onsets[0],'refined':word_onsets[0],'method':'first_word_onset'})
        elif i==len(data['verses']):boundaries.append({'candidate':explicit_end,'refined':explicit_end,'method':'source_end'})
        else:boundaries.append(boundary_meta(word_onsets[cumulative[i]],silences))
    for i in range(1,len(boundaries)):
        if boundaries[i]['refined']<=boundaries[i-1]['refined']:fail(f'SIGNAL: non-monotonic boundary {i}')
    seq=data['sequence']; records=[]; failed=[]
    for i,verse in enumerate(data['verses']):
        ch=int(verse.get('chapter',default_ch)); n=int(verse['verse']); start,end=boundaries[i]['refined'],boundaries[i+1]['refined']
        stem=f'{seq}_{ch}_{n}' if cross else f'{seq}_{n}'; r1,r2=out/f'{stem}_r1.mp3',out/f'{stem}_r2.mp3'
        word_start,word_end=cumulative[i],cumulative[i+1]
        verse_outside=[(k+1,labels[k]) for k in range(word_start,word_end) if k<len(labels) and labels[k]>source_duration]
        reason=None
        if verse_outside:
            first_i,first_t=verse_outside[0]
            reason=f'PocketTorah source truncated: label word {first_i}/{total_words} onset={first_t:.6f}s exceeds audio duration={source_duration:.6f}s; verse_out_of_audio_labels={len(verse_outside)}'
            failure_code='POCKETTORAH_SOURCE_TRUNCATED'
        elif end-start<0.4:
            reason=f'boundary duration too short: {end-start:.6f}s'
            failure_code='POCKETTORAH_BOUNDARY_TOO_SHORT'
        if reason:
            for path in (r1,r2):
                if path.exists(): path.unlink()
            failed.append({'chapter':ch,'verse':n,'ref':f'{ch}:{n}','word_count':len(verse['words']),
              'MAPPING_STATUS':'FAILED','SIGNAL_STATUS':'NOT_RUN','MODEL_AUDIO_STATUS':'NOT_RUN',
              'HIGHEST_VERIFIED_STAGE':'NONE','DELIVERY_STATUS':'NOT_IMPLEMENTED_FAILED',
              'FAILURE_CODE':failure_code,'LIMITATION_REASON':reason})
            continue
        split_mp3(source,start,end,r1); d1=duration(r1); source_wps=len(verse['words'])/d1; factor=TARGET_WPS/source_wps
        if not 0.25<=factor<=4.0:
            for path in (r1,r2):
                if path.exists(): path.unlink()
            failed.append({'chapter':ch,'verse':n,'ref':f'{ch}:{n}','word_count':len(verse['words']),
              'MAPPING_STATUS':'PASS','SIGNAL_STATUS':'FAILED','MODEL_AUDIO_STATUS':'NOT_RUN',
              'HIGHEST_VERIFIED_STAGE':'MAPPING_CONFIRMED','DELIVERY_STATUS':'NOT_IMPLEMENTED_FAILED',
              'FAILURE_CODE':'POCKETTORAH_ATEMPO_OUT_OF_RANGE','LIMITATION_REASON':f'unreasonable atempo={factor:.6f}'})
            continue
        speed_mp3(r1,factor,r2); d2=duration(r2); theoretical=d1/factor; mean_db=mean_volume_db(r1)
        if mean_db<-55.0:fail(f'SIGNAL: verse {ch}:{n} mean volume too low')
        records.append({'chapter':ch,'verse':n,'ref':f'{ch}:{n}','word_count':len(verse['words']),'boundary_start':start,'boundary_end':end,'boundary_start_meta':boundaries[i],'boundary_end_meta':boundaries[i+1],'r1':r1.name,'r1_duration':d1,'source_wps':source_wps,'target_wps':TARGET_WPS,'atempo':factor,'r2':r2.name,'r2_duration':d2,'r2_theoretical_duration':theoretical,'r2_duration_error':abs(d2-theoretical),'r2_wps':len(verse['words'])/d2,'mean_volume_db':mean_db,
          'MAPPING_STATUS':'PASS','SIGNAL_STATUS':'PASS','MODEL_AUDIO_STATUS':'NOT_RUN',
          'HIGHEST_VERIFIED_STAGE':'SIGNAL_CHECKED','DELIVERY_STATUS':'READY','LIMITATION_REASON':'',
          'audio_origin':'POCKETTORAH'})
    expected_refs=[f"{int(v.get('chapter',default_ch))}:{int(v['verse'])}" for v in data['verses']]
    status='PARTIAL' if failed else 'PASS'
    manifest={'schema_version':'audio-1.3','status':status,'sequence':seq,'passage':p,'expected_refs':expected_refs,
      'source':{**source_meta,'pockettorah_commit':POCKETTORAH_SHA,'source_file':source.name,'source_duration':source_duration,'label_count':len(labels),'word_count':total_words,'out_of_audio_label_count':len(outside)},
      'qa':{'MAPPING_CONFIRMED':not failed,'SIGNAL_CHECKED':not failed,'MODEL_AUDIO_CHECKED':False,'AUDIO_DELIVERY_COMPLETE':not failed,'AUDIO_VERIFICATION_COMPLETE':False,'target_wps':TARGET_WPS,'boundary_rule':'PocketTorah next-word onset is the deterministic shared boundary; signal pauses are annotations only until MODEL_AUDIO confirms prior-word completion and no next-verse contamination'},
      'verses':records,'failed_verses':failed}
    (out/'audio_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"{status}: AUDIO build implemented={len(records)} failed={len(failed)} words={total_words} source={source_meta['base']} target_wps={TARGET_WPS} model_audio=PENDING")
if __name__=='__main__':main()
