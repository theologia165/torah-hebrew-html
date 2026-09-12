#!/usr/bin/env python3
"""Resolve audited PocketTorah defects through the approved audio hierarchy.

Normal production order is PocketTorah, an allow-listed exact Open.Bible verse,
then OpenAI TTS. Every fallback is tied to the current RUN's audio-input token
sequence; no request may supply free-form Hebrew. A fallback failure remains a
PARTIAL media failure so the other validated media can still be delivered.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import requests

TARGET_WPS = 0.79306
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / 'config' / 'audio-fallback.json'


def fail(message):
    raise RuntimeError(message)


def run(*args):
    subprocess.run(args, check=True)


def digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def duration(path):
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=nokey=1:noprint_wrappers=1', str(path)],
        text=True, capture_output=True, check=True)
    return float(result.stdout.strip())


def mean_volume_db(path):
    result = subprocess.run(
        ['ffmpeg', '-hide_banner', '-i', str(path), '-af', 'volumedetect',
         '-f', 'null', '-'], text=True, capture_output=True)
    match = re.search(r'mean_volume:\s*(-?[0-9.]+) dB', result.stderr)
    if not match:
        fail(f'Could not measure mean volume for {path}')
    return float(match.group(1))


def atempo_chain(factor):
    values = []
    while factor < 0.5:
        values.append(0.5)
        factor /= 0.5
    while factor > 2.0:
        values.append(2.0)
        factor /= 2.0
    values.append(factor)
    return ','.join(f'atempo={value:.9f}' for value in values)


def spoken_text(words):
    # Remove cantillation while retaining niqqud/dagesh. The words are the
    # current RUN's read-aloud tokens (qere only where applicable).
    return ' '.join(re.sub(r'[\u0591-\u05af]', '', word['surface'])
                    for word in words)


def classify_failure(item):
    """Return a stable code while remaining compatible with legacy manifests."""
    if item.get('FAILURE_CODE'):
        return item['FAILURE_CODE']
    reason = item.get('LIMITATION_REASON', '')
    if 'PocketTorah source truncated' in reason:
        return 'POCKETTORAH_SOURCE_TRUNCATED'
    if 'boundary duration too short' in reason:
        return 'POCKETTORAH_BOUNDARY_TOO_SHORT'
    if 'unreasonable atempo=' in reason:
        return 'POCKETTORAH_ATEMPO_OUT_OF_RANGE'
    return 'UNCLASSIFIED_AUDIO_FAILURE'


def full_ref(book, chapter, verse):
    return f'{book}.{int(chapter)}.{int(verse)}'


def input_by_ref(audio_input):
    book = audio_input['passage']['book']
    default_chapter = int(audio_input['passage']['chapter'])
    return {
        full_ref(book, verse.get('chapter', default_chapter), verse['verse']): verse
        for verse in audio_input['verses']
    }


def validate_policy(policy):
    if policy.get('schema_version') != '1.0-audio-fallback-policy':
        fail('Unsupported audio fallback policy schema')
    if policy.get('status') != 'APPROVED_PRODUCTION_POLICY':
        fail('Audio fallback production policy is not approved')
    if policy.get('priority') != ['POCKETTORAH', 'OPEN_BIBLE', 'OPENAI_TTS']:
        fail('Audio fallback priority must be PocketTorah → Open.Bible → OpenAI TTS')
    if abs(float(policy.get('target_wps', 0)) - TARGET_WPS) > 1e-9:
        fail('Audio fallback policy target_wps mismatch')
    return policy


def validate_open_bible_entry(ref, entry, policy, text_sha256, word_count):
    """Fail closed unless a source was manually verified as this exact verse."""
    required = ('status', 'ref', 'url', 'audio_sha256', 'spoken_text_sha256',
                'word_count', 'license', 'attribution_label',
                'attribution_url', 'verified_on')
    missing = [key for key in required if key not in entry]
    if missing:
        fail(f'Open.Bible registry entry {ref} lacks {missing}')
    if entry['status'] != 'VERIFIED_EXACT_VERSE' or entry['ref'] != ref:
        fail(f'Open.Bible registry entry {ref} is not exact-ref verified')
    if not entry['url'].startswith('https://'):
        fail(f'Open.Bible registry entry {ref} has a non-HTTPS audio URL')
    if not re.fullmatch(r'[0-9a-f]{64}', entry['audio_sha256']):
        fail(f'Open.Bible registry entry {ref} has an invalid audio_sha256')
    if entry['spoken_text_sha256'] != text_sha256:
        fail(f'Open.Bible registry entry {ref} does not match current RUN spoken text')
    if int(entry['word_count']) != word_count:
        fail(f'Open.Bible registry entry {ref} word count mismatch')
    if entry['license'] not in policy['open_bible']['allowed_licenses']:
        fail(f'Open.Bible registry entry {ref} license is not approved')
    if (not entry['attribution_label'].strip()
            or not entry['attribution_url'].startswith('https://')):
        fail(f'Open.Bible registry entry {ref} lacks valid attribution')
    return entry


def choose_fallback(ref, failure, verse_data, policy):
    """Pure planning function shared by production and contract tests."""
    code = classify_failure(failure)
    if code not in policy['eligible_pockettorah_failure_codes']:
        return {
            'ref': ref, 'status': 'BLOCKED', 'selected_source': None,
            'primary_failure_code': code,
            'reason': 'PocketTorah failure is not an approved physical-source defect',
        }
    text = spoken_text(verse_data['words'])
    text_sha256 = hashlib.sha256(text.encode('utf-8')).hexdigest()
    entry = policy['open_bible']['approved_verse_sources'].get(ref)
    if entry is not None:
        try:
            validate_open_bible_entry(ref, entry, policy, text_sha256,
                                      len(verse_data['words']))
        except Exception as error:
            return {
                'ref': ref, 'status': 'BLOCKED', 'selected_source': None,
                'primary_failure_code': code,
                'open_bible_status': 'REGISTRY_INTEGRITY_FAILED',
                'reason': str(error),
            }
        return {
            'ref': ref, 'status': 'PLANNED', 'selected_source': 'OPEN_BIBLE',
            'primary_failure_code': code,
            'open_bible_status': 'VERIFIED_EXACT_SOURCE',
            'open_bible_entry': entry,
        }
    if policy['openai_tts'].get('enabled') is True:
        return {
            'ref': ref, 'status': 'PLANNED', 'selected_source': 'OPENAI_TTS',
            'primary_failure_code': code,
            'open_bible_status': 'NO_APPROVED_EXACT_SOURCE_IN_REGISTRY',
        }
    return {
        'ref': ref, 'status': 'BLOCKED', 'selected_source': None,
        'primary_failure_code': code,
        'open_bible_status': 'NO_APPROVED_EXACT_SOURCE_IN_REGISTRY',
        'reason': 'OpenAI TTS is disabled by production policy',
    }


def make_audio_record(ref, verse_data, r1, r2, origin, disclosure='',
                      source_meta=None):
    d1 = duration(r1)
    word_count = len(verse_data['words'])
    source_wps = word_count / d1
    factor = TARGET_WPS / source_wps
    if not 0.25 <= factor <= 4.0:
        fail(f'{origin} produced unreasonable atempo={factor:.6f}')
    run('ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', str(r1),
        '-af', atempo_chain(factor), '-c:a', 'libmp3lame', '-q:a', '2', str(r2))
    d2 = duration(r2)
    theoretical = d1 / factor
    mean_db = mean_volume_db(r1)
    if mean_db < -55.0:
        fail(f'{origin} mean volume too low: {mean_db:.1f} dB')
    _, chapter, verse = ref.split('.')
    record = {
        'chapter': int(chapter), 'verse': int(verse),
        'ref': f'{int(chapter)}:{int(verse)}', 'word_count': word_count,
        'boundary_start': 0.0, 'boundary_end': d1,
        'boundary_start_meta': {'candidate': 0.0, 'refined': 0.0,
                                'method': f'standalone_{origin.lower()}_source_start'},
        'boundary_end_meta': {'candidate': d1, 'refined': d1,
                              'method': f'standalone_{origin.lower()}_source_end'},
        'boundary_scope': f'STANDALONE_{origin}',
        'r1': r1.name, 'r1_duration': d1, 'source_wps': source_wps,
        'target_wps': TARGET_WPS, 'atempo': factor,
        'r2': r2.name, 'r2_duration': d2,
        'r2_theoretical_duration': theoretical,
        'r2_duration_error': abs(d2 - theoretical),
        'r2_wps': word_count / d2, 'mean_volume_db': mean_db,
        'MAPPING_STATUS': 'PASS', 'SIGNAL_STATUS': 'PASS',
        'MODEL_AUDIO_STATUS': 'NOT_RUN',
        'HIGHEST_VERIFIED_STAGE': 'SIGNAL_CHECKED',
        'DELIVERY_STATUS': 'READY', 'LIMITATION_REASON': '',
        'audio_origin': origin,
    }
    if disclosure:
        record['ai_disclosure'] = disclosure
    if source_meta:
        record.update(source_meta)
    return record


def fetch_open_bible(ref, entry, audio_dir, stem):
    response = requests.get(entry['url'], timeout=120)
    if response.status_code >= 300:
        fail(f'Open.Bible GET {ref}: {response.status_code} {response.text[:300]}')
    actual_sha = hashlib.sha256(response.content).hexdigest()
    if actual_sha != entry['audio_sha256']:
        fail(f'Open.Bible audio_sha256 mismatch for {ref}')
    r1 = audio_dir / f'{stem}_openbible_r1.mp3'
    r2 = audio_dir / f'{stem}_openbible_r2.mp3'
    r1.write_bytes(response.content)
    source_meta = {
        'source_url': entry['url'], 'source_audio_sha256': actual_sha,
        'source_license': entry['license'],
        'source_attribution_label': entry['attribution_label'],
        'source_attribution_url': entry['attribution_url'],
        'source_verified_on': entry['verified_on'],
    }
    return r1, r2, source_meta


def fetch_openai(ref, verse_data, policy, audio_dir, stem, legacy_request=None):
    api_key = os.getenv('OPENAI_API_KEY', '').strip()
    if not api_key:
        fail('OPENAI_API_KEY is not configured in GitHub Actions secrets')
    settings = dict(policy['openai_tts'])
    if legacy_request:
        settings['model'] = legacy_request.get('model', settings['model'])
        settings['voice'] = legacy_request.get('voice', settings['voice'])
        settings['required_disclosure'] = legacy_request.get(
            'required_disclosure', settings['required_disclosure'])
    text = spoken_text(verse_data['words'])
    response = requests.post(
        'https://api.openai.com/v1/audio/speech',
        headers={'Authorization': f'Bearer {api_key}',
                 'Content-Type': 'application/json'},
        json={'model': settings['model'], 'voice': settings['voice'],
              'input': text, 'instructions': settings['instructions'],
              'response_format': 'mp3'}, timeout=180)
    if response.status_code >= 300:
        fail(f'OpenAI POST /v1/audio/speech: {response.status_code} {response.text[:600]}')
    r1 = audio_dir / f'{stem}_ai_r1.mp3'
    r2 = audio_dir / f'{stem}_ai_r2.mp3'
    r1.write_bytes(response.content)
    source_meta = {
        'ai_model': settings['model'], 'ai_voice': settings['voice'],
        'openai_request_id': response.headers.get('x-request-id'),
    }
    return r1, r2, settings['required_disclosure'], source_meta


def update_manifest(manifest, record, failure, decision):
    manifest['verses'].append(record)
    order = {ref: index for index, ref in enumerate(manifest['expected_refs'])}
    manifest['verses'].sort(key=lambda verse: order[verse['ref']])
    manifest['failed_verses'] = [item for item in manifest.get('failed_verses', [])
                                  if item['ref'] != failure['ref']]
    manifest['status'] = 'PASS' if not manifest['failed_verses'] else 'PARTIAL'
    book = decision['ref'].split('.')[0]
    as_osis = lambda verse: f'{book}.{verse["chapter"]}.{verse["verse"]}'
    ai_refs = [as_osis(verse) for verse in manifest['verses']
               if verse.get('audio_origin') == 'OPENAI_TTS']
    open_refs = [as_osis(verse) for verse in manifest['verses']
                 if verse.get('audio_origin') == 'OPEN_BIBLE']
    manifest.setdefault('qa', {}).update({
        'MAPPING_CONFIRMED': not manifest['failed_verses'],
        'SIGNAL_CHECKED': not manifest['failed_verses'],
        'AUDIO_DELIVERY_COMPLETE': not manifest['failed_verses'],
        'AI_FALLBACK_REFS': ai_refs,
        'OPEN_BIBLE_FALLBACK_REFS': open_refs,
        'AI_DISCLOSURE_REQUIRED': bool(ai_refs),
    })
    sources = [item for item in manifest.get('fallback_sources', [])
               if item.get('ref') != decision['ref']]
    source = {
        'ref': decision['ref'], 'type': record['audio_origin'],
        'reason': failure.get('LIMITATION_REASON', ''),
        'primary_failure_code': decision['primary_failure_code'],
        'open_bible_status': decision.get('open_bible_status'),
    }
    if record['audio_origin'] == 'OPENAI_TTS':
        source.update(model=record['ai_model'], voice=record['ai_voice'],
                      disclosure=record['ai_disclosure'])
    else:
        source.update(license=record['source_license'],
                      attribution_label=record['source_attribution_label'],
                      attribution_url=record['source_attribution_url'])
    manifest['fallback_sources'] = sources + [source]


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: build_ai_audio.py <run-dir>')
    run_dir = Path(sys.argv[1])
    policy = validate_policy(json.loads(DEFAULT_POLICY.read_text(encoding='utf-8')))
    policy_sha = digest(policy)
    request_path = run_dir / 'ai-audio-request.json'
    legacy_request = None
    target_refs = None
    if request_path.exists():
        legacy_request = json.loads(request_path.read_text(encoding='utf-8'))
        if legacy_request.get('status') != 'APPROVED_LAST_RESORT':
            fail('AI audio request is not explicitly approved as last resort')
        if legacy_request.get('run_id') != run_dir.name:
            fail('AI audio request run_id mismatch')
        if abs(float(legacy_request.get('target_wps', 0)) - TARGET_WPS) > 1e-9:
            fail('AI audio request target_wps mismatch')
        target_refs = legacy_request.get('refs') or [legacy_request.get('ref')]
        if not all(isinstance(ref, str) and ref.count('.') == 2 for ref in target_refs):
            fail('AI audio request refs must be OSIS book.chapter.verse')

    audio_input = json.loads((run_dir / 'audio-input.json').read_text(encoding='utf-8'))
    verses_by_ref = input_by_ref(audio_input)
    manifest_path = run_dir / 'audio' / 'audio_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    audio_dir = run_dir / 'audio'
    audit_path = run_dir / 'ai-audio-audit.json'

    # Preserve the 041 audit and prove its existing result remains reusable.
    if not manifest.get('failed_verses'):
        if target_refs:
            for ref in target_refs:
                _, chapter, verse = ref.split('.')
                existing = [item for item in manifest.get('verses', [])
                            if int(item['chapter']) == int(chapter)
                            and int(item['verse']) == int(verse)]
                if len(existing) != 1 or existing[0].get('audio_origin') != 'OPENAI_TTS':
                    fail(f'Existing fallback audio does not match {ref}')
                for key in ('r1', 'r2'):
                    if not (audio_dir / existing[0][key]).exists():
                        fail(f'Existing fallback audio lacks {existing[0][key]}')
            print(f'SKIP_FALLBACK_AUDIO_EXISTS: verified {target_refs}')
        else:
            print('SKIP_FALLBACK_AUDIO: primary manifest already PASS')
        return

    failures_by_ref = {
        full_ref(audio_input['passage']['book'], item['chapter'], item['verse']): item
        for item in manifest.get('failed_verses', [])
    }
    if target_refs is not None:
        missing = [ref for ref in target_refs if ref not in failures_by_ref]
        if missing:
            fail(f'Approved AI request has no matching failed verse: {missing}')
        selected_failures = [(ref, failures_by_ref[ref]) for ref in target_refs]
    else:
        selected_failures = list(failures_by_ref.items())

    audit = {
        'schema_version': '1.1-audio-fallback-audit',
        'status': 'RUNNING', 'run_id': run_dir.name,
        'policy_sha256': policy_sha, 'priority': policy['priority'],
        'input_source': 'current-run audio-input.json read-aloud tokens',
        'decisions': [],
    }

    def checkpoint():
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
                                 encoding='utf-8')
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n',
                              encoding='utf-8')

    for ref, failure in selected_failures:
        verse_data = verses_by_ref.get(ref)
        if verse_data is None:
            decision = {'ref': ref, 'status': 'BLOCKED', 'selected_source': None,
                        'primary_failure_code': classify_failure(failure),
                        'reason': 'Current RUN audio-input has no matching verse'}
            audit['decisions'].append(decision)
            failure['FALLBACK_STATUS'] = 'BLOCKED'
            failure['FALLBACK_ATTEMPTS'] = [decision]
            checkpoint()
            continue
        text = spoken_text(verse_data['words'])
        text_sha = hashlib.sha256(text.encode('utf-8')).hexdigest()
        token_ids = [word['id'] for word in verse_data['words']]
        decision = choose_fallback(ref, failure, verse_data, policy)
        if legacy_request and decision['status'] == 'PLANNED':
            # A legacy per-RUN request records an already completed second-source check.
            decision.update(status='PLANNED', selected_source='OPENAI_TTS',
                            open_bible_status='EXPLICIT_REQUEST_RECORDED_NO_VERIFIED_SOURCE')
        decision.update(token_ids=token_ids, input_text=text,
                        input_sha256=text_sha, word_count=len(token_ids))
        audit['decisions'].append(decision)
        failure['FAILURE_CODE'] = decision['primary_failure_code']
        failure['FALLBACK_STATUS'] = decision['status']
        failure['FALLBACK_ATTEMPTS'] = [{
            'source': 'OPEN_BIBLE',
            'status': decision.get('open_bible_status', 'NOT_REACHED'),
        }]
        if decision['status'] == 'BLOCKED':
            failure['FALLBACK_ATTEMPTS'].append({
                'source': 'OPENAI_TTS', 'status': 'NOT_RUN',
                'reason': decision['reason'],
            })
            checkpoint()
            continue

        _, chapter, verse = ref.split('.')
        cross_chapter = int(audio_input['passage'].get(
            'end_chapter', audio_input['passage']['chapter'])) != int(
                audio_input['passage']['chapter'])
        stem = (f'{audio_input["sequence"]}_{int(chapter)}_{int(verse)}'
                if cross_chapter else f'{audio_input["sequence"]}_{int(verse)}')
        try:
            if decision['selected_source'] == 'OPEN_BIBLE':
                entry = decision['open_bible_entry']
                r1, r2, source_meta = fetch_open_bible(ref, entry, audio_dir, stem)
                record = make_audio_record(ref, verse_data, r1, r2,
                                           'OPEN_BIBLE', source_meta=source_meta)
                decision.update(status='PASS', r1=r1.name, r2=r2.name,
                                measured_r2_wps=record['r2_wps'],
                                audio_sha256=source_meta['source_audio_sha256'])
                failure['FALLBACK_ATTEMPTS'][0]['status'] = 'PASS'
            else:
                r1, r2, disclosure, source_meta = fetch_openai(
                    ref, verse_data, policy, audio_dir, stem, legacy_request)
                record = make_audio_record(ref, verse_data, r1, r2,
                                           'OPENAI_TTS', disclosure, source_meta)
                decision.update(status='PASS', r1=r1.name, r2=r2.name,
                                model=record['ai_model'], voice=record['ai_voice'],
                                openai_request_id=record['openai_request_id'],
                                measured_r2_wps=record['r2_wps'],
                                disclosure=record['ai_disclosure'])
                failure['FALLBACK_ATTEMPTS'].append({
                    'source': 'OPENAI_TTS', 'status': 'PASS',
                    'model': record['ai_model'], 'voice': record['ai_voice'],
                })
            update_manifest(manifest, record, failure, decision)
            checkpoint()
            print(f'PASS: {record["audio_origin"]} repaired {ref}; '
                  f'words={len(token_ids)} r2_wps={record["r2_wps"]:.6f}')
        except Exception as error:
            decision.update(status='FAILED', error_type=type(error).__name__,
                            error_message=str(error))
            failure['FALLBACK_STATUS'] = 'FAILED'
            failure['FALLBACK_ATTEMPTS'].append({
                'source': decision['selected_source'], 'status': 'FAILED',
                'error_type': type(error).__name__, 'message': str(error),
            })
            # Runtime unavailability can fall through; a hash/metadata mismatch
            # is an integrity failure and deliberately remains PARTIAL.
            runtime_open_error = (decision['selected_source'] == 'OPEN_BIBLE'
                                  and 'Open.Bible GET' in str(error))
            if runtime_open_error and policy['openai_tts'].get('enabled'):
                try:
                    r1, r2, disclosure, source_meta = fetch_openai(
                        ref, verse_data, policy, audio_dir, stem, legacy_request)
                    record = make_audio_record(ref, verse_data, r1, r2,
                                               'OPENAI_TTS', disclosure, source_meta)
                    decision.update(status='PASS', selected_source='OPENAI_TTS',
                                    open_bible_runtime_error=str(error),
                                    model=record['ai_model'], voice=record['ai_voice'],
                                    openai_request_id=record['openai_request_id'],
                                    measured_r2_wps=record['r2_wps'],
                                    disclosure=record['ai_disclosure'])
                    failure['FALLBACK_ATTEMPTS'].append({
                        'source': 'OPENAI_TTS', 'status': 'PASS',
                        'model': record['ai_model'], 'voice': record['ai_voice'],
                    })
                    update_manifest(manifest, record, failure, decision)
                    checkpoint()
                    print(f'PASS: OPENAI_TTS repaired {ref} after Open.Bible runtime failure')
                    continue
                except Exception as second_error:
                    decision.update(status='FAILED',
                                    fallback_error_type=type(second_error).__name__,
                                    fallback_error_message=str(second_error))
                    failure['FALLBACK_ATTEMPTS'].append({
                        'source': 'OPENAI_TTS', 'status': 'FAILED',
                        'error_type': type(second_error).__name__,
                        'message': str(second_error),
                    })
            checkpoint()
            print(f'PARTIAL: audio fallback failed for {ref}: {error}', file=sys.stderr)

    audit['status'] = ('PASS' if all(item['status'] == 'PASS'
                                     for item in audit['decisions'])
                       else 'PARTIAL')
    checkpoint()
    passed = sum(item['status'] == 'PASS' for item in audit['decisions'])
    unresolved = len(audit['decisions']) - passed
    print(f'{manifest["status"]}: audio fallback pass={passed} unresolved={unresolved}')


if __name__ == '__main__':
    main()
