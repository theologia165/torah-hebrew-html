"""Import licensed verse-separated synthetic Hebrew, with independent ASR."""
import hashlib,io,json,re,sys,zipfile
from pathlib import Path
import requests
from build_media import ROOT,REFS,BRANCH,prepare,write,commit
from audio.processing import make_audio_record
from audio.text import spoken_text

def main():
    j=prepare();audio=ROOT/'audio';audio.mkdir(exist_ok=True)
    # Pinned ZIP blob identified through the owner's public repository.
    url='https://raw.githubusercontent.com/eliranwong/MP3_OpenHebrewGreekBible_slow/main/21_Ecclesiastes.zip'
    r=requests.get(url,timeout=120);r.raise_for_status();data=r.content
    assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()=='cf58f80a76951b44dced0eba8ac52f12f4b48291'
    archive=zipfile.ZipFile(io.BytesIO(data))
    from faster_whisper import WhisperModel
    model=WhisperModel('small',device='cpu',compute_type='int8',cpu_threads=4)
    manifest={'source':'OHGB_SYNTHETIC','source_url':url,'license':'CC BY 4.0','attribution':'Eliran Wong, MP3 Open Hebrew Greek Bible (slow), generated with Unique Bible App text-to-speech','disclosure':'合成音声：Eliran Wong / Open Hebrew Greek Bible（CC BY 4.0）','zip_sha256':hashlib.sha256(data).hexdigest(),'asr_model':'Systran/faster-whisper-small','verses':[],'status':'IN_PROGRESS'}
    try:
        for v in j['verses']:
            ref=v['ref'];_,ch,n=ref.split('.');entry=f'21_{ch}/OHGB_21_{ch}_{n}.mp3'
            stem=ref.replace('.','-').lower();r1=audio/(stem+'_ohgb_r1.mp3');r2=audio/(stem+'_ohgb_r2.mp3');r1.write_bytes(archive.read(entry))
            words=[t for t,w in zip(v['tokens'],v['layout']['words']) if w.get('read_aloud',True)]
            rec=make_audio_record(ref,{'words':words},r1,r2,'OHGB_SYNTHETIC',manifest['disclosure'])
            segments,info=model.transcribe(str(r2),language='he',beam_size=5,word_timestamps=True,condition_on_previous_text=False,vad_filter=False)
            ss=[{'start':s.start,'end':s.end,'text':s.text,'words':[{'start':w.start,'end':w.end,'word':w.word,'probability':w.probability} for w in (s.words or [])]} for s in segments]
            rec.update(osis_ref=ref,archive_entry=entry,expected_text=spoken_text(words),asr_text=' '.join(s['text'] for s in ss),asr_segments=ss,r1_sha256=hashlib.sha256(r1.read_bytes()).hexdigest(),r2_sha256=hashlib.sha256(r2.read_bytes()).hexdigest(),MODEL_AUDIO_STATUS='LOCAL_ASR_OBSERVED_AWAITING_WORK_REVIEW',audio_url=f'https://raw.githubusercontent.com/theologia165/torah-hebrew-html/{BRANCH}/{r2.as_posix()}')
            manifest['verses'].append(rec);write('audio_manifest.json',manifest)
            print(ref,rec['asr_text'],flush=True)
        manifest['status']='ASR_COMPLETE_AWAITING_WORK_REVIEW';write('audio_manifest.json',manifest)
    finally:commit('Import CC BY verse-separated Qohelet audio with independent ASR audit')

if __name__=='__main__':main()
