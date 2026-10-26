"""Stage repair candidates, review exact bytes, then replace existing audio."""
import re
import shutil
import subprocess
import sys
from pathlib import Path

from audio.manifest import digest, write_json_atomic
from audio.quality import file_sha, read


def pending(run):
    run = Path(run)
    request = read(run / 'audio-repair.json')
    if not request:
        return False
    done = read(run / 'audio-repair.done.json', {})
    if not done:
        return True
    # Preserve already completed legacy repairs; new repairs are request-bound.
    return bool(request.get('repair_id') and done.get('request_sha256') != digest(request))


def execute(run, commit_run):
    try:
        return _execute(run, commit_run)
    except Exception as error:
        from handoff import pipeline_failure
        run = Path(run)
        write_json_atomic(run / 'audio-repair-failure.json', {
            'status': 'BLOCKED', 'run_id': run.name,
            'operation': 'AUDIO_QUALITY_REPAIR',
            'error_type': type(error).__name__, 'message': str(error)[-2000:],
            'repair_completed': False,
        })
        pipeline_failure(run, error, 'AUDIO_QUALITY_REPAIR')
        commit_run(run, 'Record unresolved audio quality repair failure')
        raise


def _execute(run, commit_run):
    from audio_quality import inspect_audio
    from handoff import waiting_for_audio_quality

    run = Path(run)
    request = read(run / 'audio-repair.json')
    delivery = read(run / 'delivery.json', {})
    repair_id = request.get('repair_id')
    # Legacy unresolved requests enter the desk as a new candidate too.
    repair_id = repair_id or 'legacy-' + digest(request)[:12]
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', repair_id):
        raise ValueError('Unsafe repair_id')
    if (request.get('operation') != 'AUDIO_ONLY_REPLACE'
            or request.get('run_id') != run.name
            or request.get('page_id') != delivery.get('page_id')
            or not delivery.get('page_id')):
        raise ValueError('Repair identity or existing page mismatch')
    if not request.get('audio_only_repair') or request.get('update_page_id') != delivery['page_id']:
        raise ValueError('Repair must explicitly target only existing page media')

    desk = run / 'audio-repairs' / repair_id
    desk.mkdir(parents=True, exist_ok=True)
    context_path = desk / 'context.json'
    context = {'request_sha256': digest(request),
               'input_sha256': file_sha(run / 'audio-input.json')}
    if context_path.exists() and read(context_path) != context:
        raise ValueError('Repair inputs changed; use a new repair_id')
    write_json_atomic(context_path, context)
    candidate_run = desk / run.name
    candidate_run.mkdir(exist_ok=True)
    shutil.copyfile(run / 'audio-input.json', candidate_run / 'audio-input.json')
    candidate = candidate_run / 'audio'
    def command(script, *args):
        subprocess.run([sys.executable, 'ver3/scripts/' + script,
                        *map(str, args)], check=True)
    if not (candidate / 'audio_manifest.json').exists():
        try:
            command('build_audio.py', run / 'audio-input.json', candidate)
            if read(candidate / 'audio_manifest.json').get('failed_verses'):
                command('resolve_audio.py', candidate_run)
        finally:
            for path in candidate.glob('*_source.mp3'):
                path.unlink()
        # Fresh filenames avoid stale Notion/browser audio caches.
        manifest = read(candidate / 'audio_manifest.json')
        for verse in manifest.get('verses', []):
            for key in ('r1', 'r2'):
                old = candidate / verse[key]
                suffix = '_' + key + '.mp3'
                name = f'{old.name[:-len(suffix)]}_{repair_id}_{file_sha(old)[:12]}{suffix}'
                old.rename(candidate / name)
                verse[key] = name
        manifest['repair_id'] = repair_id
        write_json_atomic(candidate / 'audio_manifest.json', manifest)
    report_path = desk / 'audio-quality.json'
    review_path = desk / 'audio-content-review.json'
    from audio.model_review import collect
    collect(run, desk, candidate)
    report = inspect_audio(run, candidate, review_path, report_path)
    if report['status'] != 'PASS':
        waiting_for_audio_quality(run, report_path, review_path, report)
        commit_run(run, 'Stage audio repair candidate for content and boundary review')
        print('WAITING_FOR_AUDIO_QUALITY: candidate kept separate from published audio')
        return False

    # Keep rollback evidence once per repair, including the old MP3 bytes.
    previous = desk / 'before'
    if not previous.exists():
        shutil.copytree(run / 'audio', previous)
        shutil.copyfile(run / 'delivery.json', desk / 'delivery-before.json')
    shutil.copytree(candidate, run / 'audio', dirs_exist_ok=True)
    # Keep old URLs working until Notion switches. Only candidate records
    # enter the manifest; historical bytes are never selected as substitutes.
    published_quality = inspect_audio(run, run / 'audio', review_path)
    if published_quality['status'] != 'PASS':
        raise ValueError('Published candidate differs from reviewed audio')
    commit_run(run, 'Publish content-reviewed audio repair bytes before Notion update')
    command('deliver.py', run, run / 'audio-repair.json')
    repaired = read(run / 'delivery.json')
    if (repaired.get('status') != 'PASS'
            or repaired.get('operation') != 'AUDIO_ONLY_REPLACE'
            or repaired.get('page_id') != request['page_id']
            or repaired.get('AUDIO_IMPLEMENTED_COUNT') != len(report['verses'])):
        raise ValueError('Repaired Notion delivery has not passed')
    receipt = {
        'schema_version': '1.0-audio-repair-receipt', 'status': 'PASS',
        'operation': 'AUDIO_ONLY_REPLACE', 'run_id': run.name,
        'repair_id': repair_id, 'request_sha256': digest(request),
        'page_id': request['page_id'], 'audio_implemented_count': len(report['verses']),
        'quality_report_sha256': file_sha(report_path),
        'content_review_sha256': file_sha(review_path),
        'input_sha256': report['input_sha256'],
        'manifest_sha256': report['manifest_sha256'],
        'delivery_sha256': file_sha(run / 'delivery.json'),
        'audio_sha256': {v['ref']: v['r2_sha256'] for v in report['verses']},
        'public_bytes_and_existing_page_verified_by': 'ver3/scripts/deliver.py',
        'incident_ids': request.get('incident_ids', []),
        'speed_policy': 'SLOWDOWN_ONLY_NO_ACCELERATION', 'max_atempo': 1.0,
    }
    write_json_atomic(desk / 'closed.json', receipt)
    write_json_atomic(run / 'audio-repair.done.json', receipt)
    from handoff import no_action
    no_action(run)
    commit_run(run, 'Close verified audio repair with byte-bound content and delivery evidence')
    print('PASS: audio quality repair closed on the existing page')
    return True
