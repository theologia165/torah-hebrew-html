"""Resolve audited primary-source failures through approved adapters."""
import hashlib
import json
import sys
from pathlib import Path

from audio.manifest import checkpoint, digest, update_manifest
from audio.policy import choose_fallback, classify_failure, load_policy
from audio.processing import TARGET_WPS, make_audio_record
from audio.sources.open_bible import OpenBibleFetchError, fetch_open_bible
from audio.sources.openai_tts import fetch_openai
from audio.text import full_ref, input_by_ref, spoken_text


def resolve(run_dir):
    run_dir = Path(run_dir)
    policy = load_policy()
    policy_sha = digest(policy)
    request_path = run_dir / 'ai-audio-request.json'
    legacy_request = None
    target_refs = None
    if request_path.exists():
        legacy_request = json.loads(request_path.read_text(encoding='utf-8'))
        if legacy_request.get('status') != 'APPROVED_LAST_RESORT':
            raise RuntimeError('AI audio request is not explicitly approved as last resort')
        if legacy_request.get('run_id') != run_dir.name:
            raise RuntimeError('AI audio request run_id mismatch')
        if abs(float(legacy_request.get('target_wps', 0)) - TARGET_WPS) > 1e-9:
            raise RuntimeError('AI audio request target_wps mismatch')
        target_refs = legacy_request.get('refs') or [legacy_request.get('ref')]
        if not all(
                isinstance(ref, str) and ref.count('.') == 2
                for ref in target_refs):
            raise RuntimeError('AI audio request refs must be OSIS book.chapter.verse')

    audio_input = json.loads(
        (run_dir / 'audio-input.json').read_text(encoding='utf-8'))
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
                existing = [
                    item for item in manifest.get('verses', [])
                    if int(item['chapter']) == int(chapter)
                    and int(item['verse']) == int(verse)
                ]
                if (len(existing) != 1
                        or existing[0].get('audio_origin') != 'OPENAI_TTS'):
                    raise RuntimeError(f'Existing fallback audio does not match {ref}')
                for key in ('r1', 'r2'):
                    if not (audio_dir / existing[0][key]).exists():
                        raise RuntimeError(
                            f'Existing fallback audio lacks {existing[0][key]}')
            print(f'SKIP_FALLBACK_AUDIO_EXISTS: verified {target_refs}')
        else:
            print('SKIP_FALLBACK_AUDIO: primary manifest already PASS')
        return manifest

    failures_by_ref = {
        full_ref(
            audio_input['passage']['book'], item['chapter'], item['verse']): item
        for item in manifest.get('failed_verses', [])
    }
    if target_refs is not None:
        missing = [ref for ref in target_refs if ref not in failures_by_ref]
        if missing:
            raise RuntimeError(
                f'Approved AI request has no matching failed verse: {missing}')
        selected_failures = [(ref, failures_by_ref[ref]) for ref in target_refs]
    else:
        selected_failures = list(failures_by_ref.items())

    audit = {
        'schema_version': '1.1-audio-fallback-audit',
        'status': 'RUNNING',
        'run_id': run_dir.name,
        'policy_sha256': policy_sha,
        'priority': policy['priority'],
        'input_source': 'current-run audio-input.json read-aloud tokens',
        'decisions': [],
    }

    def save_checkpoint():
        checkpoint(manifest_path, manifest, audit_path, audit)

    for ref, failure in selected_failures:
        verse_data = verses_by_ref.get(ref)
        if verse_data is None:
            decision = {
                'ref': ref,
                'status': 'BLOCKED',
                'selected_source': None,
                'primary_failure_code': classify_failure(failure),
                'reason': 'Current RUN audio-input has no matching verse',
            }
            audit['decisions'].append(decision)
            failure['FALLBACK_STATUS'] = 'BLOCKED'
            failure['FALLBACK_ATTEMPTS'] = [decision]
            save_checkpoint()
            continue

        text = spoken_text(verse_data['words'])
        text_sha = hashlib.sha256(text.encode('utf-8')).hexdigest()
        token_ids = [word['id'] for word in verse_data['words']]
        decision = choose_fallback(ref, failure, verse_data, policy)
        if legacy_request and decision['status'] == 'PLANNED':
            # The legacy request records an already completed second-source check.
            decision.update(
                selected_source='OPENAI_TTS',
                open_bible_status='EXPLICIT_REQUEST_RECORDED_NO_VERIFIED_SOURCE')
        decision.update(
            token_ids=token_ids,
            input_text=text,
            input_sha256=text_sha,
            word_count=len(token_ids),
        )
        audit['decisions'].append(decision)
        failure['FAILURE_CODE'] = decision['primary_failure_code']
        failure['FALLBACK_STATUS'] = decision['status']
        failure['FALLBACK_ATTEMPTS'] = [{
            'source': 'OPEN_BIBLE',
            'status': decision.get('open_bible_status', 'NOT_REACHED'),
        }]
        if decision['status'] == 'BLOCKED':
            failure['FALLBACK_ATTEMPTS'].append({
                'source': 'OPENAI_TTS',
                'status': 'NOT_RUN',
                'reason': decision['reason'],
            })
            save_checkpoint()
            continue

        _, chapter, verse = ref.split('.')
        cross_chapter = int(audio_input['passage'].get(
            'end_chapter', audio_input['passage']['chapter'])) != int(
                audio_input['passage']['chapter'])
        stem = (
            f'{audio_input["sequence"]}_{int(chapter)}_{int(verse)}'
            if cross_chapter else f'{audio_input["sequence"]}_{int(verse)}')
        try:
            if decision['selected_source'] == 'OPEN_BIBLE':
                entry = decision['open_bible_entry']
                r1, r2, source_meta = fetch_open_bible(
                    ref, entry, audio_dir, stem)
                record = make_audio_record(
                    ref, verse_data, r1, r2, 'OPEN_BIBLE',
                    source_meta=source_meta)
                decision.update(
                    status='PASS',
                    r1=r1.name,
                    r2=r2.name,
                    measured_r2_wps=record['r2_wps'],
                    audio_sha256=source_meta['source_audio_sha256'],
                )
                failure['FALLBACK_ATTEMPTS'][0]['status'] = 'PASS'
            else:
                r1, r2, disclosure, source_meta = fetch_openai(
                    ref, verse_data, policy, audio_dir, stem, legacy_request)
                record = make_audio_record(
                    ref, verse_data, r1, r2, 'OPENAI_TTS', disclosure,
                    source_meta)
                decision.update(
                    status='PASS',
                    r1=r1.name,
                    r2=r2.name,
                    model=record['ai_model'],
                    voice=record['ai_voice'],
                    openai_request_id=record['openai_request_id'],
                    measured_r2_wps=record['r2_wps'],
                    disclosure=record['ai_disclosure'],
                )
                failure['FALLBACK_ATTEMPTS'].append({
                    'source': 'OPENAI_TTS',
                    'status': 'PASS',
                    'model': record['ai_model'],
                    'voice': record['ai_voice'],
                })
            update_manifest(manifest, record, failure, decision)
            save_checkpoint()
            print(
                f'PASS: {record["audio_origin"]} repaired {ref}; '
                f'words={len(token_ids)} r2_wps={record["r2_wps"]:.6f}')
        except Exception as error:
            decision.update(
                status='FAILED',
                error_type=type(error).__name__,
                error_message=str(error),
            )
            failure['FALLBACK_STATUS'] = 'FAILED'
            failure['FALLBACK_ATTEMPTS'].append({
                'source': decision['selected_source'],
                'status': 'FAILED',
                'error_type': type(error).__name__,
                'message': str(error),
            })
            # Only a transient/HTTP Open.Bible retrieval error may continue to
            # TTS.  Hash, license and metadata failures remain PARTIAL.
            if (isinstance(error, OpenBibleFetchError)
                    and policy['openai_tts'].get('enabled')):
                try:
                    r1, r2, disclosure, source_meta = fetch_openai(
                        ref, verse_data, policy, audio_dir, stem, legacy_request)
                    record = make_audio_record(
                        ref, verse_data, r1, r2, 'OPENAI_TTS', disclosure,
                        source_meta)
                    decision.update(
                        status='PASS',
                        selected_source='OPENAI_TTS',
                        open_bible_runtime_error=str(error),
                        model=record['ai_model'],
                        voice=record['ai_voice'],
                        openai_request_id=record['openai_request_id'],
                        measured_r2_wps=record['r2_wps'],
                        disclosure=record['ai_disclosure'],
                    )
                    failure['FALLBACK_ATTEMPTS'].append({
                        'source': 'OPENAI_TTS',
                        'status': 'PASS',
                        'model': record['ai_model'],
                        'voice': record['ai_voice'],
                    })
                    update_manifest(manifest, record, failure, decision)
                    save_checkpoint()
                    print(
                        f'PASS: OPENAI_TTS repaired {ref} after '
                        'Open.Bible runtime failure')
                    continue
                except Exception as second_error:
                    decision.update(
                        status='FAILED',
                        fallback_error_type=type(second_error).__name__,
                        fallback_error_message=str(second_error),
                    )
                    failure['FALLBACK_ATTEMPTS'].append({
                        'source': 'OPENAI_TTS',
                        'status': 'FAILED',
                        'error_type': type(second_error).__name__,
                        'message': str(second_error),
                    })
            save_checkpoint()
            print(
                f'PARTIAL: audio fallback failed for {ref}: {error}',
                file=sys.stderr)

    audit['status'] = (
        'PASS' if all(
            item['status'] == 'PASS' for item in audit['decisions'])
        else 'PARTIAL')
    save_checkpoint()
    passed = sum(item['status'] == 'PASS' for item in audit['decisions'])
    unresolved = len(audit['decisions']) - passed
    print(
        f'{manifest["status"]}: audio fallback pass={passed} '
        f'unresolved={unresolved}')
    return manifest


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: resolve_audio.py <run-dir>')
    resolve(Path(sys.argv[1]))


if __name__ == '__main__':
    main()

