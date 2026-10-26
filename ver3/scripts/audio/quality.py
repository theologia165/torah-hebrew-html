"""Audio quality desk: evidence, case matching, review and repair receipts.

This module never claims to have listened. A content PASS must come from a
separate reviewer and be bound to the exact current input and MP3 bytes.
"""
import json
from pathlib import Path

from audio.manifest import digest, write_json_atomic
from audio.text import input_by_ref, spoken_text


ROOT = Path(__file__).resolve().parents[2]
REGISTER = ROOT / 'quality/audio/incidents.json'
CHECKS = ('first_word', 'last_word', 'word_order', 'no_other_verse',
          'no_truncation', 'study_speed')
METHODS = ('HUMAN_LISTENING', 'MODEL_AUDIO_LISTENING',
           'ASR_WITH_BOUNDARY_REVIEW')


def read(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def file_sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_audio_path(directory, name):
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError('Audio file must be a basename')
    return Path(directory) / name


def inspect(run, audio_dir=None, review_path=None, *, machine_status,
            machine_output='', output=None):
    run = Path(run)
    audio_dir = Path(audio_dir) if audio_dir else run / 'audio'
    review_path = Path(review_path) if review_path else run / 'audio-content-review.json'
    output = Path(output) if output else run / 'audio-quality.json'
    manifest = read(audio_dir / 'audio_manifest.json', {})
    audio_input = read(run / 'audio-input.json', {})
    register = read(REGISTER)
    review = read(review_path, {})
    input_sha = digest(audio_input)
    manifest_sha = digest(manifest)
    source = manifest.get('source', {})
    matches = [case for case in register['incidents']
               if case.get('source_match') and all(
                   source.get(key) == value
                   for key, value in case['source_match'].items())]
    binding_ok = (
        review.get('schema_version') == '1.0-audio-content-review'
        and review.get('run_id') == run.name
        and review.get('input_sha256') == input_sha
        and review.get('manifest_sha256') == manifest_sha
        and review.get('method') in METHODS
        and bool(review.get('reviewer')) and bool(review.get('reviewed_at')))
    review_rows = review.get('verses', [])
    by_ref = {row.get('ref'): row for row in review_rows}
    # Duplicated or extra review rows cannot certify the current delivery.
    expected_rows = {v['ref'] for v in manifest.get('verses', [])}
    binding_ok = binding_ok and len(by_ref) == len(review_rows) and set(by_ref) == expected_rows
    text_by_ref = input_by_ref(audio_input) if audio_input else {}
    book = audio_input.get('passage', {}).get('book', '')
    rows, template = [], []
    for verse in manifest.get('verses', []):
        ref = verse['ref']
        full_ref = f"{book}.{verse['chapter']}.{verse['verse']}"
        current = text_by_ref.get(full_ref)
        hashes = {key + '_sha256': file_sha(path) if path.is_file() else None
                  for key in ('r1', 'r2')
                  for path in [safe_audio_path(audio_dir, verse[key])]}
        findings = []
        if not current or len(current['words']) != verse.get('word_count'):
            findings.append('CURRENT_INPUT_MAPPING_MISMATCH')
        if not all(hashes.values()):
            findings.append('AUDIO_BYTES_MISSING')
        for case in matches:
            alignment_unfixed = (case.get('required_alignment')
                                 and source.get('label_alignment') != case['required_alignment'])
            defective_boundary = any(
                abs(verse.get(key, -1) - value) < 0.0001
                for key, value in case.get('defective_boundary_values', {}).items())
            if alignment_unfixed or defective_boundary:
                findings.append(case['failure_code'])
        row = by_ref.get(ref, {})
        row_valid = binding_ok and all(row.get(key) == value for key, value in hashes.items())
        checks = row.get('checks', {}) if row_valid else {}
        if any(value == 'FAIL' for value in checks.values()):
            findings.append('CONTENT_REVIEW_FAILED')
        content_pass = (row_valid and bool(row.get('evidence'))
                        and all(checks.get(key) == 'PASS' for key in CHECKS))
        if findings:
            content_pass = False
        rows.append({
            'ref': ref, 'osis_ref': full_ref, **hashes,
            'r1': str(audio_dir / verse['r1']),
            'r2': str(audio_dir / verse['r2']),
            'content_status': 'PASS' if content_pass else ('FAIL' if findings else 'PENDING'),
            'findings': findings,
        })
        template.append({
            'ref': ref, **hashes,
            'expected_text': spoken_text(current['words']) if current else '',
            'checks': {key: 'PENDING' for key in CHECKS}, 'evidence': '',
        })
    blocking_refs = [row['ref'] for row in rows if row['findings']]
    pending_refs = [row['ref'] for row in rows if row['content_status'] == 'PENDING']
    failed_refs = [v['ref'] for v in manifest.get('failed_verses', [])]
    accounted_refs = {row['osis_ref'] for row in rows} | {
        f"{book}.{v['chapter']}.{v['verse']}"
        for v in manifest.get('failed_verses', [])}
    input_covered = accounted_refs == set(text_by_ref)
    if not input_covered:
        machine_status = 'FAIL'
        machine_output += '\nCURRENT_INPUT_COVERAGE_MISMATCH'
    content_pass = bool(rows) and input_covered and not (blocking_refs or pending_refs or failed_refs)
    quality_pass = machine_status == 'PASS' and content_pass
    report = {
        'schema_version': '1.0-audio-quality', 'run_id': run.name,
        'status': 'PASS' if quality_pass else (
            'BLOCKED' if machine_status != 'PASS' or blocking_refs or failed_refs
            else 'CONTENT_REVIEW_PENDING'),
        'machine_status': machine_status,
        'content_status': 'PASS' if content_pass else 'PENDING_OR_FAILED',
        'AUDIO_VERIFICATION_COMPLETE': quality_pass,
        'input_sha256': input_sha, 'manifest_sha256': manifest_sha,
        'current_input_covered': input_covered,
        'register_sha256': digest(register), 'review_path': str(review_path),
        'review_sha256': digest(review) if review else None,
        'matched_incidents': [case['id'] for case in matches],
        'regression_tests': register['regression_command'],
        'blocking_refs': blocking_refs, 'pending_refs': pending_refs,
        'failed_refs': failed_refs, 'verses': rows,
        'machine_output': machine_output[-4000:],
        'next_action': 'READY_FOR_DELIVERY' if quality_pass else (
            'DIAGNOSE_AND_REPAIR_AUDIO' if blocking_refs or failed_refs or machine_status != 'PASS'
            else 'REVIEW_AUDIO_CONTENT'),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(output, report)
    template_path = output.with_name(output.stem + '-review-template.json')
    write_json_atomic(template_path, {
        'schema_version': '1.0-audio-content-review', 'run_id': run.name,
        'input_sha256': input_sha, 'manifest_sha256': manifest_sha,
        'reviewer': '', 'method': '', 'reviewed_at': '', 'verses': template,
    })
    return report


def quarantine(run, report):
    """Exclude proven defects, preserving healthy media and original evidence."""
    run = Path(run)
    path = run / 'audio/audio_manifest.json'
    manifest = read(path)
    blocked = set(report['blocking_refs'])
    if not blocked:
        return
    archive = run / 'audio-manifest-before-quality-quarantine.json'
    if not archive.exists():
        write_json_atomic(archive, manifest)
    rows = {v['ref']: v for v in report['verses']}
    for verse in manifest['verses']:
        if verse['ref'] in blocked:
            manifest.setdefault('failed_verses', []).append({
                'chapter': verse['chapter'], 'verse': verse['verse'],
                'ref': verse['ref'], 'word_count': verse['word_count'],
                'FAILURE_CODE': 'AUDIO_QUALITY_QUARANTINED',
                'LIMITATION_REASON': ','.join(rows[verse['ref']]['findings']),
                'DELIVERY_STATUS': 'NOT_IMPLEMENTED_FAILED',
            })
    manifest['verses'] = [v for v in manifest['verses'] if v['ref'] not in blocked]
    manifest['status'] = 'PARTIAL'
    manifest['qa'].update(MAPPING_CONFIRMED=False, SIGNAL_CHECKED=False,
                          AUDIO_DELIVERY_COMPLETE=False, AUDIO_VERIFICATION_COMPLETE=False)
    write_json_atomic(path, manifest)


def request_repair(run, repair_id, reason, incident_ids):
    import re
    run = Path(run)
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', repair_id):
        raise ValueError('repair_id must be a short path-safe identifier')
    delivery = read(run / 'delivery.json', {})
    if not delivery.get('page_id') or delivery.get('status') != 'PASS':
        raise ValueError('Completed delivery with an existing page is required')
    register = read(REGISTER)
    if not reason.strip() or not incident_ids or set(incident_ids) - {c['id'] for c in register['incidents']}:
        raise ValueError('Reason and registered incident IDs are required')
    path = run / 'audio-repair.json'
    prior = read(path)
    done = read(run / 'audio-repair.done.json', {})
    legacy_complete = prior and not prior.get('repair_id') and done.get('status') == 'PASS'
    if prior and not legacy_complete and done.get('request_sha256') != digest(prior):
        raise ValueError('An unresolved repair already exists; inspect it before replacing')
    payload = {
        'operation': 'AUDIO_ONLY_REPLACE', 'audio_only_repair': True,
        'run_id': run.name, 'page_id': delivery['page_id'],
        'update_page_id': delivery['page_id'], 'repair_id': repair_id,
        'reason': reason, 'incident_ids': incident_ids,
        'quality_department': 'ver3/quality/audio',
    }
    if (run / 'audio-repairs' / repair_id).exists():
        raise ValueError('repair_id was already used; preserve its evidence')
    write_json_atomic(path, payload)
    return payload


def cancel_repair(run, reason):
    run = Path(run)
    request = read(run / 'audio-repair.json')
    if not request or not reason.strip():
        raise ValueError('Existing repair and cancellation reason are required')
    repair_id = request.get('repair_id') or 'legacy-' + digest(request)[:12]
    import re
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', repair_id):
        raise ValueError('Unsafe repair_id')
    desk = run / 'audio-repairs' / repair_id
    desk.mkdir(parents=True, exist_ok=True)
    receipt = {
        'status': 'CANCELLED', 'run_id': run.name, 'repair_id': repair_id,
        'request_sha256': digest(request), 'reason': reason,
        'audio_repair_completed': False,
    }
    if (desk / 'closed.json').exists():
        raise ValueError('Cannot cancel a closed repair')
    write_json_atomic(desk / 'cancelled.json', receipt)
    write_json_atomic(run / 'audio-repair.done.json', receipt)
    return receipt
