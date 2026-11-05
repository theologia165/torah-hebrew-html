"""One-time 093 boundary repair under the user's report-and-publish policy.

Never converts pending word identification to a content PASS. This operation is
limited to the already reviewed, immutable candidate and the existing page.
"""
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0,str(Path('ver3/scripts').resolve()))
from audio.manifest import digest, write_json_atomic
from audio.quality import read, file_sha
from audio_quality import inspect_audio
from runner import commit_run

run=Path('ver3/runs/093-20261102-r1')
desk=run/'audio-repairs/verified-boundaries-20261105-r1'
candidate=desk/run.name/'audio'
request=read(run/'audio-repair.json')
review_path=desk/'audio-content-review.json'
manifest=read(candidate/'audio_manifest.json')
state_path=Path('ver3/state/production.json')
state_before=file_sha(state_path)
page_id='40c8aa46-08ae-8117-a4a7-d121683caa1e'
receipt_path=desk/'published-partial.json'
existing=read(receipt_path,{})
if existing.get('boundary_repair_status')=='PUBLISHED_VERIFIED':
 assert existing['candidate_manifest_sha256']==digest(manifest)
 assert existing['page_id']==page_id
 print('ALREADY_PUBLISHED: exact 093 partial boundary repair; no second replacement')
 sys.exit(0)
assert request['operation']=='AUDIO_ONLY_REPLACE' and request['audio_only_repair'] is True
assert request['page_id']==request['update_page_id']==page_id
assert digest(manifest)=='663b59f8fb348bc85fb112dcd9f12d3ae94d791063e551038eebb50f07c8fac0'
assert digest(read(run/'audio-input.json'))=='3b30add9ec657f6bbf40c5f9b763e0fa715daa9b9a89e15b4e25eafb2de7ed20'
quality=inspect_audio(run,candidate,review_path,desk/'partial-release-quality.json')
assert quality['machine_status']=='PASS'
assert not quality['blocking_refs'] and not quality['failed_refs']
assert quality['pending_refs']==['6:24']
assert len(quality['verses'])==15
assert sum(row['content_status']=='PASS' for row in quality['verses'])==14
review=read(review_path)
for row in review['verses']:
 for check in ['first_word','no_other_verse','no_truncation','study_speed']:
  assert row['checks'][check]=='PASS',(row['ref'],check)
assert read(desk/'human-listening-feedback-20261105.json')['reported_issue']['target_audio']=='NOTION_PUBLISHED_ORIGINAL'
authorization={
 'scope':'093 existing-page boundary repair only; not a global policy change',
 'user_policy_quote':'どうしても問題解決出来ない場合は、その旨をメールで伝え、とりあえず不十分な音声のまま実装はする',
 'quality_status':'CONTENT_REVIEW_PENDING',
 'unresolved_ref':'6:24',
 'unresolved_issue':'Original-source final-word identification; no confirmed candidate boundary failure',
 'not_a_content_pass':True,
 'notification_required':True,
}
write_json_atomic(desk/'partial-release-policy.json',authorization)
before=desk/'before'
if not before.exists():
 shutil.copytree(run/'audio',before)
 shutil.copyfile(run/'delivery.json',desk/'delivery-before.json')
shutil.copytree(candidate,run/'audio',dirs_exist_ok=True)
published=inspect_audio(run,run/'audio',review_path)
assert published['machine_status']=='PASS' and published['pending_refs']==['6:24']
assert not published['blocking_refs'] and not published['failed_refs']
assert published['manifest_sha256']==quality['manifest_sha256']
commit_run(run,'Publish 093 boundary-repair bytes with explicit unresolved-word quality status')
subprocess.run([sys.executable,'ver3/scripts/deliver.py',str(run),str(run/'audio-repair.json')],check=True)
delivery=read(run/'delivery.json')
assert delivery['status']=='PASS' and delivery['operation']=='AUDIO_ONLY_REPLACE'
assert delivery['page_id']==page_id and delivery['AUDIO_IMPLEMENTED_COUNT']==15
assert not delivery['missing_audio_refs']
assert file_sha(state_path)==state_before,'Audio repair changed production state'
delivery.update(audio_quality_status='CONTENT_REVIEW_PENDING',audio_content_verified=False,audio_boundary_repair_status='PUBLISHED_VERIFIED')
write_json_atomic(run/'delivery.json',delivery)
receipt={
 'schema_version':'1.0-partial-audio-repair-receipt','status':'PARTIAL',
 'operation':'AUDIO_ONLY_REPLACE','run_id':run.name,'repair_id':request['repair_id'],
 'request_sha256':digest(request),'page_id':page_id,'page_url':delivery['page_url'],
 'boundary_repair_status':'PUBLISHED_VERIFIED','audio_implemented_count':15,
 'machine_status':'PASS','content_status':'CONTENT_REVIEW_PENDING',
 'full_content_pass_verses':14,'pending_refs':['6:24'],
 'candidate_manifest_sha256':digest(manifest),'input_sha256':quality['input_sha256'],
 'content_review_sha256':file_sha(review_path),'quality_report_sha256':file_sha(run/'audio-quality.json'),
 'delivery_sha256':file_sha(run/'delivery.json'),
 'audio_sha256':{v['ref']:{'r1':v['r1_sha256'],'r2':v['r2_sha256']} for v in published['verses']},
 'public_bytes_and_existing_page_verified_by':'ver3/scripts/deliver.py',
 'production_state_unchanged':True,'production_state_sha256':state_before,
 'notification_status':'GMAIL_SENT_PROOF_PENDING',
 'published_at':datetime.now(timezone.utc).isoformat(),
}
write_json_atomic(receipt_path,receipt)
handoff=read(run/'handoff.json')
handoff.update(phase='AUDIO_QUALITY',status='PARTIAL',next_action='REVIEW_AND_REPAIR_AUDIO')
handoff['details'].update(quality_status='CONTENT_REVIEW_PENDING',pending_refs=['6:24'],published_audio_unchanged=False,boundary_repair_status='PUBLISHED_VERIFIED',full_content_pass_verses=14,notification_status='GMAIL_SENT_PROOF_PENDING')
write_json_atomic(run/'handoff.json',handoff)
commit_run(run,'Record partial 093 boundary repair without claiming all-content quality PASS')
print('PARTIAL: 093 boundaries replaced and public bytes verified;6:24 word review remains pending')
