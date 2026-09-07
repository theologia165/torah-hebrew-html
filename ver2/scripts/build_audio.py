#!/usr/bin/env python3
import array,json,math,re,statistics,subprocess,sys,urllib.request,urllib.parse
from pathlib import Path

POCKETTORAH_SHA='8a23287221dd535966ee9914de9a03e71769a469'
BASE_RAW=f'https://raw.githubusercontent.com/rneiss/PocketTorah/{POCKETTORAH_SHA}'
ALIYAH_URL=f'{BASE_RAW}/data/aliyah.json'
TARGET_WPS=0.79306
SILENCE_NOISE_DB=-38
SILENCE_MIN_D=0.08
SIGNAL_WINDOW=1.25
PCM_RATE=16000

def fail(msg):
    print(f'FAIL: {msg}',file=sys.stderr)
    raise SystemExit(1)

def get_bytes(url):
    req=urllib.request.Request(url,headers={'User-Agent':'asaichi-torah-ver2'})
    return urllib.request.urlopen(req,timeout=60).read()

def run(cmd):
    p=subprocess.run(cmd,text=True,capture_output=True)
    if p.returncode!=0:
        fail(f"command failed: {' '.join(cmd)}\n{p.stderr}")
    return p

def duration(path):
    return float(run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nokey=1:noprint_wrappers=1',str(path)]).stdout.strip())

def mean_volume_db(path):
    p=subprocess.run(['ffmpeg','-hide_banner','-nostats','-i',str(path),'-af','volumedetect','-f','null','-'],text=True,capture_output=True)
    m=re.search(r'mean_volume:\s*(-?[0-9.]+) dB',p.stderr)
    return float(m.group(1)) if m else -999.0

def detect_silences(path):
    p=subprocess.run(
        ['ffmpeg','-hide_banner','-nostats','-i',str(path),'-af',f'silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_D}','-f','null','-'],
        text=True,capture_output=True
    )
    starts=[float(x) for x in re.findall(r'silence_start:\s*([0-9.]+)',p.stderr)]
    ends=[float(x) for x in re.findall(r'silence_end:\s*([0-9.]+)',p.stderr)]
    return [(st,ends[i]) for i,st in enumerate(starts) if i<len(ends) and ends[i]>=st]

def decode_pcm(path):
    p=subprocess.run(
        ['ffmpeg','-hide_banner','-loglevel','error','-i',str(path),'-ac','1','-ar',str(PCM_RATE),'-f','s16le','-'],
        capture_output=True
    )
    if p.returncode!=0:
        fail(f'PCM decode failed for {path}: {p.stderr.decode("utf-8","replace")}')
    samples=array.array('h')
    samples.frombytes(p.stdout)
    return samples

def rms_window(samples,start_sec,end_sec):
    lo=max(0,int(start_sec*PCM_RATE))
    hi=min(len(samples),int(end_sec*PCM_RATE))
    if hi<=lo:
        return 0.0
    step=max(1,(hi-lo)//4000)
    vals=samples[lo:hi:step]
    if not vals:
        return 0.0
    return math.sqrt(sum(int(x)*int(x) for x in vals)/len(vals))

def boundary_meta(candidate,silences,samples):
    nearby=[]
    for st,en in silences:
        if en<candidate-SIGNAL_WINDOW or st>candidate+SIGNAL_WINDOW:
            continue
        distance=min(abs(candidate-st),abs(candidate-en))
        nearby.append((distance,st,en))
    rec={
        'candidate':candidate,
        'refined':candidate,
        'method':'PocketTorah word-onset mapping + waveform/silence observation',
        'rms_pre':rms_window(samples,candidate-0.14,candidate-0.02),
        'rms_center':rms_window(samples,candidate-0.03,candidate+0.03),
        'rms_post':rms_window(samples,candidate+0.02,candidate+0.14),
    }
    if nearby:
        distance,st,en=min(nearby,key=lambda x:x[0])
        rec['nearest_silence']={'start':st,'end':en,'distance':distance}
    else:
        rec['nearest_silence']=None
    return rec

def signal_meta(path):
    d=duration(path)
    silences=detect_silences(path)
    leading=0.0
    trailing=0.0
    internal=[]
    for st,en in silences:
        span=max(0.0,en-st)
        if st<=0.03:
            leading=max(leading,en)
        elif en>=d-0.03:
            trailing=max(trailing,d-st)
        else:
            internal.append(span)
    mean_db=mean_volume_db(path)
    max_internal=max(internal) if internal else 0.0
    passed=(
        d>=0.40 and
        mean_db>=-55.0 and
        leading<=0.45 and
        trailing<=0.65 and
        max_internal<=1.80
    )
    return {
        'duration':d,
        'mean_volume_db':mean_db,
        'leading_silence':leading,
        'trailing_silence':trailing,
        'max_internal_silence':max_internal,
        'pass':passed,
    }

def resolve_source(data):
    aliyah=json.loads(get_bytes(ALIYAH_URL).decode('utf-8-sig'))
    p=data['passage']
    start_ch=int(p['chapter'])
    end_ch=int(p.get('end_chapter',start_ch))
    begin,end=f"{start_ch}:{p['start_verse']}",f"{end_ch}:{p['end_verse']}"
    matches=[]
    for parsha in aliyah['parshiot']['parsha']:
        for a in parsha.get('fullkriyah',{}).get('aliyah',[]):
            if a.get('_begin')==begin and a.get('_end')==end and a.get('_num')!='M':
                matches.append((parsha['_id'],a['_num']))
    if len(matches)!=1:
        fail(f'PocketTorah aliyah mapping expected 1 match for {begin}-{end}, got {matches}')
    parsha,num=matches[0]
    base=f'{parsha}-{num}'
    audio_base=re.sub(r"[\s'’]+",'',base)
    labels_base=base
    return {
        'parsha':parsha,'aliyah':num,'base':base,
        'audio_base':audio_base,'labels_base':labels_base,
        'audio_url':f"{BASE_RAW}/data/audio/{urllib.parse.quote(audio_base,safe='')}.mp3",
        'labels_url':f"{BASE_RAW}/data/torah/labels/{urllib.parse.quote(labels_base,safe='')}.txt"
    }

def split_mp3(source,start,end,out):
    run(['ffmpeg','-y','-hide_banner','-loglevel','error','-i',str(source),'-af',f'atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS','-c:a','libmp3lame','-q:a','2',str(out)])

def atempo_chain(factor):
    if factor<=0:
        fail(f'invalid atempo {factor}')
    values=[]
    x=factor
    while x<0.5:
        values.append(0.5)
        x/=0.5
    while x>2.0:
        values.append(2.0)
        x/=2.0
    values.append(x)
    return ','.join(f'atempo={v:.9f}' for v in values)

def speed_mp3(src,factor,out):
    run(['ffmpeg','-y','-hide_banner','-loglevel','error','-i',str(src),'-af',atempo_chain(factor),'-c:a','libmp3lame','-q:a','2',str(out)])

def main():
    if len(sys.argv)!=3:
        fail('usage: build_audio.py <enriched.json> <audio-output-dir>')
    data=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    out=Path(sys.argv[2])
    out.mkdir(parents=True,exist_ok=True)
    p=data['passage']
    default_ch=int(p['chapter'])
    cross=int(p.get('end_chapter',default_ch))!=default_ch

    # MAPPING: labels are candidate word onsets, not an unquestioned verse-boundary oracle.
    source_meta=resolve_source(data)
    source=out/f"{source_meta['audio_base']}_source.mp3"
    source.write_bytes(get_bytes(source_meta['audio_url']))
    labels=[float(x) for x in get_bytes(source_meta['labels_url']).decode('utf-8-sig').strip().split(',') if x.strip()]
    word_counts=[len(v['words']) for v in data['verses']]
    total_words=sum(word_counts)
    if len(labels) not in (total_words,total_words+1):
        fail(f'MAPPING: label count {len(labels)} incompatible with word count {total_words}')
    source_duration=duration(source)
    if len(labels)==total_words+1 and labels[-1]<=source_duration+0.25:
        word_onsets,explicit_end=labels[:-1],labels[-1]
    else:
        word_onsets,explicit_end=labels[:total_words],source_duration
    if len(word_onsets)!=total_words:
        fail('MAPPING: could not normalize PocketTorah label count')
    if not all(b>a for a,b in zip(word_onsets,word_onsets[1:])):
        fail('MAPPING: word-position labels are not strictly increasing')

    # SIGNAL: inspect the actual waveform/silence context at every shared boundary.
    source_silences=detect_silences(source)
    source_pcm=decode_pcm(source)
    cumulative=[0]
    for n in word_counts:
        cumulative.append(cumulative[-1]+n)
    boundaries=[]
    for i in range(len(data['verses'])+1):
        if i==0:
            boundaries.append({
                'candidate':word_onsets[0],'refined':word_onsets[0],
                'method':'first mapped word onset',
                'rms_pre':rms_window(source_pcm,word_onsets[0]-0.14,word_onsets[0]-0.02),
                'rms_center':rms_window(source_pcm,word_onsets[0]-0.03,word_onsets[0]+0.03),
                'rms_post':rms_window(source_pcm,word_onsets[0]+0.02,word_onsets[0]+0.14),
                'nearest_silence':None
            })
        elif i==len(data['verses']):
            boundaries.append({
                'candidate':explicit_end,'refined':explicit_end,'method':'mapped/source end',
                'rms_pre':rms_window(source_pcm,explicit_end-0.14,explicit_end-0.02),
                'rms_center':rms_window(source_pcm,explicit_end-0.03,explicit_end+0.03),
                'rms_post':rms_window(source_pcm,explicit_end+0.02,explicit_end+0.14),
                'nearest_silence':None
            })
        else:
            boundaries.append(boundary_meta(word_onsets[cumulative[i]],source_silences,source_pcm))
    for i in range(1,len(boundaries)):
        if boundaries[i]['refined']<=boundaries[i-1]['refined']:
            fail(f'SIGNAL: non-monotonic boundary {i}')

    seq=data['sequence']
    records=[]
    for i,verse in enumerate(data['verses']):
        ch=int(verse.get('chapter',default_ch))
        n=int(verse['verse'])
        start,end=boundaries[i]['refined'],boundaries[i+1]['refined']
        if end-start<0.40:
            fail(f'SIGNAL: verse {ch}:{n} boundary duration too short')
        stem=f'{seq}_{ch}_{n}' if cross else f'{seq}_{n}'
        r1=out/f'{stem}_r1.mp3'
        r2=out/f'{stem}_r2.mp3'

        split_mp3(source,start,end,r1)
        r1_signal=signal_meta(r1)
        if not r1_signal['pass']:
            fail(f"SIGNAL: verse {ch}:{n} r1 acoustic integrity failed {r1_signal}")

        # SPEED is applied only after the verified physical r1 verse split.
        d1=r1_signal['duration']
        source_wps=len(verse['words'])/d1
        factor=TARGET_WPS/source_wps
        if not 0.25<=factor<=4.0:
            fail(f'SPEED: verse {ch}:{n} unreasonable atempo={factor:.6f}')
        speed_mp3(r1,factor,r2)
        r2_signal=signal_meta(r2)
        theoretical=d1/factor
        d2=r2_signal['duration']
        if not r2_signal['pass']:
            fail(f"SPEED/SIGNAL: verse {ch}:{n} r2 acoustic integrity failed {r2_signal}")

        records.append({
            'chapter':ch,'verse':n,'ref':f'{ch}:{n}',
            'word_count':len(verse['words']),
            'boundary_start':start,'boundary_end':end,
            'boundary_start_meta':boundaries[i],
            'boundary_end_meta':boundaries[i+1],
            'r1':r1.name,'r1_duration':d1,
            'source_wps':source_wps,
            'target_wps':TARGET_WPS,'atempo':factor,
            'r2':r2.name,'r2_duration':d2,
            'r2_theoretical_duration':theoretical,
            'r2_duration_error':abs(d2-theoretical),
            'r2_wps':len(verse['words'])/d2,
            'r1_signal':r1_signal,
            'r2_signal':r2_signal,
        })

    # Rare anomaly gate: semantic listening/transcription is insurance, not a normal prerequisite.
    median_wps=statistics.median(v['source_wps'] for v in records)
    model_refs=[]
    for v in records:
        reasons=[]
        ratio=v['source_wps']/median_wps if median_wps else 1.0
        if ratio<0.40 or ratio>2.50:
            reasons.append(f'source_wps_outlier_ratio={ratio:.3f}')
        end_meta=v['boundary_end_meta']
        if end_meta.get('nearest_silence') is None and v is not records[-1] and (ratio<0.65 or ratio>1.75):
            reasons.append('boundary_has_no_nearby_silence_and_wps_is_unusual')
        if v['r1_signal']['leading_silence']>0.30 or v['r1_signal']['trailing_silence']>0.45:
            reasons.append('edge_silence_near_signal_limit')
        v['model_audio_reasons']=reasons
        if reasons:
            model_refs.append(v['ref'])

    manifest={
        'schema_version':'audio-1.3',
        'sequence':seq,
        'passage':p,
        'source':{
            **source_meta,
            'pockettorah_commit':POCKETTORAH_SHA,
            'source_file':source.name,
            'source_duration':source_duration,
            'label_count':len(labels),
            'word_count':total_words
        },
        'qa':{
            'MAPPING_CONFIRMED':True,
            'SIGNAL_CHECKED':True,
            'SPEED_CHECKED':True,
            'MODEL_AUDIO_CHECKED':False,
            'model_audio_required':bool(model_refs),
            'model_audio_required_refs':model_refs,
            'target_wps':TARGET_WPS,
            'source_median_wps':median_wps,
            'boundary_rule':(
                'PocketTorah word-position labels define mapped word-onset candidates. '
                'Every shared verse boundary is then inspected against the decoded waveform and silence map. '
                'Physical r1 verse files are signal-checked before speed correction; r2 files are re-checked after atempo. '
                'MODEL_AUDIO/GPT-Transcribe is invoked only for anomaly refs.'
            )
        },
        'verses':records
    }
    (out/'audio_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(
        f"PASS: AUDIO build verses={len(records)} words={total_words} "
        f"source={source_meta['base']} MAPPING=PASS SIGNAL=PASS SPEED=PASS "
        f"model_audio_required={bool(model_refs)} refs={','.join(model_refs) if model_refs else '-'}"
    )

if __name__=='__main__':
    main()
