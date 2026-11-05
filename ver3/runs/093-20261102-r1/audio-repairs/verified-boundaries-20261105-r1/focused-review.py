"""One-time, byte-bound independent listening of four disputed pronunciations."""
import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import requests

sys.path.insert(0, str(Path('ver3/scripts').resolve()))
from audio.manifest import digest, write_json_atomic
from audio.quality import read, file_sha, safe_audio_path
from runner import commit_run

run=Path('ver3/runs/093-20261102-r1')
desk=run/'audio-repairs/verified-boundaries-20261105-r1'
audio=desk/run.name/'audio'
manifest=read(audio/'audio_manifest.json')
audio_input=read(run/'audio-input.json')
assert digest(manifest)=='663b59f8fb348bc85fb112dcd9f12d3ae94d791063e551038eebb50f07c8fac0'
assert digest(audio_input)=='3b30add9ec657f6bbf40c5f9b763e0fa715daa9b9a89e15b4e25eafb2de7ed20'
questions={
 '6:15':'After the opening two words, is the next name audibly yemuel/yemual, yoel, or something else? Describe especially any medial m consonant; mark uncertainty rather than guessing.',
 '6:16':'In the name after Gershon, is reduced sheva in u-qehat/u-qhat a normal pronunciation variation, or is there evidence of actual clipping? The word is internal to the recording. Distinguish uncertain vowel recognition from an audio edit.',
 '6:18':'Before chayei, are the consonants sh-n audible in u-shnei, or do you hear u-shei? Distinguish coarticulation/cantillation from actual omission or clipping.',
 '6:24':'At the end, is the last word ha-qorchi/ha-qarhi ending in a vowel, or ha-qorchim with a distinct final m consonant? Do not infer number from grammar. Is any neighboring verse audible after it?'
}
path=desk/'model-audio-focused-observations.json'
audit=read(path) or dict(schema_version='1.0-focused-audio-observations',run_id=run.name,input_sha256=digest(audio_input),manifest_sha256=digest(manifest),model='gpt-audio',purpose='Independent observations only; no content PASS. Resolve first-pass disagreements without changing candidate bytes.',verses=[])
try:
 for verse in manifest['verses']:
  ref=verse['ref']
  if ref not in questions:continue
  hashes={key+'_sha256':file_sha(safe_audio_path(audio,verse[key])) for key in ('r1','r2')}
  if any(v['ref']==ref and all(v.get(k)==value for k,value in hashes.items()) for v in audit['verses']):continue
  prompt=('Listen to BOTH actual recordings of a Biblical Hebrew verse, r1 natural and r2 study speed. '
   'First transcribe the whole audible verse independently; no full reference transcript is supplied. '
   'Do not fill uncertain names from biblical memory. Normal traditional pronunciation, reduced sheva, '
   'and melodic vowel length are acceptable and are not by themselves audio truncation. r1 is allowed '
   'to be natural speed. Then address this concrete acoustic question: '+questions[ref]+
   ' Return JSON with heard_text_r1, heard_text_r2, acoustic_answer, audible_consonants, '
   'time_ranges_in_each_recording, actual_clipping_evidence, uncertainty, and confidence. '
   'Use UNCERTAIN when sounds do not distinguish alternatives. Do not return an overall quality PASS.')
  content=[dict(type='text',text=prompt)]
  for key in ('r1','r2'):
   content.append(dict(type='text',text='Recording '+key))
   content.append(dict(type='input_audio',input_audio=dict(format='mp3',data=base64.b64encode(safe_audio_path(audio,verse[key]).read_bytes()).decode())))
  res=requests.post('https://api.openai.com/v1/chat/completions',headers={'Authorization':'Bearer '+os.environ['OPENAI_API_KEY'],'Content-Type':'application/json'},json=dict(model='gpt-audio',modalities=['text'],temperature=0,max_tokens=2000,store=False,messages=[dict(role='user',content=content)]),timeout=180)
  if not res.ok:
   try:err=res.json().get('error',{})
   except ValueError:err={}
   raise RuntimeError(f'Focused listening HTTP={res.status_code} code={err.get("code","UNKNOWN")} type={err.get("type","UNKNOWN")}')
  payload=res.json();raw=payload['choices'][0]['message'].get('content') or '';clean=raw.strip()
  if clean.startswith('```'):clean=clean.split('\n',1)[-1].rsplit('```',1)[0].strip()
  try:observation=json.loads(clean)
  except ValueError:observation=dict(parse_status='UNSTRUCTURED',raw_text=raw)
  audit['verses'].append(dict(ref=ref,**hashes,model=payload.get('model'),observed_at=datetime.now(timezone.utc).isoformat(),api_request_id=res.headers.get('x-request-id'),response_id=payload.get('id'),usage=payload.get('usage'),question=questions[ref],observation=observation))
  write_json_atomic(path,audit)
  print('FOCUSED_AUDIO_OBSERVATION:',ref,'recorded; Work review required')
 audit['status']='OBSERVATIONS_COMPLETE_NOT_A_CONTENT_PASS'
finally:
 write_json_atomic(path,audit)
 commit_run(run,'Record independent listening of disputed 093 names and endings')

# A dedicated transcription endpoint is independent of the conversational
# listener, whose second pass hallucinated another biblical verse in 6:18.
# No reference transcript, spelling prompt, or expected words are supplied.
tpath=desk/'model-audio-transcription-observations.json'
transcriptions=read(tpath) or dict(schema_version='1.0-audio-transcription-observations',run_id=run.name,input_sha256=digest(audio_input),manifest_sha256=digest(manifest),model='gpt-transcribe',reference_prompt=False,purpose='Resolve disputed words from actual candidate audio; observations are not a quality PASS.',files=[])
try:
 for verse in manifest['verses']:
  if verse['ref'] not in questions:continue
  for key in ('r1','r2'):
   file=safe_audio_path(audio,verse[key]);fsha=file_sha(file)
   if any(row['filename']==file.name and row['sha256']==fsha for row in transcriptions['files']):continue
   with file.open('rb') as stream:
    res=requests.post('https://api.openai.com/v1/audio/transcriptions',headers={'Authorization':'Bearer '+os.environ['OPENAI_API_KEY']},data={'model':'gpt-transcribe'},files={'file':(file.name,stream,'audio/mpeg')},timeout=180)
   if not res.ok:
    try:err=res.json().get('error',{})
    except ValueError:err={}
    raise RuntimeError(f'Dedicated transcription HTTP={res.status_code} code={err.get("code","UNKNOWN")} type={err.get("type","UNKNOWN")}')
   transcriptions['files'].append(dict(ref=verse['ref'],speed=key,filename=file.name,sha256=fsha,observed_at=datetime.now(timezone.utc).isoformat(),api_request_id=res.headers.get('x-request-id'),response=res.json()))
   write_json_atomic(tpath,transcriptions)
   print('DEDICATED_TRANSCRIPTION:',verse['ref'],key,'recorded; Work review required')
 transcriptions['status']='OBSERVATIONS_COMPLETE_NOT_A_CONTENT_PASS'
finally:
 write_json_atomic(tpath,transcriptions)
 commit_run(run,'Record unprompted dedicated transcription of four disputed 093 verses')
