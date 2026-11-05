"""Bounded observations of actual delivered MP3 edges, never a full-content PASS.

Every request is checkpointed BEFORE transmission. Interrupted/failed requests
consume their reservation and are not repeated on Actions reruns. No audio or
raw provider error body is written to JSON or logs.
"""
import base64
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

import requests

from audio.manifest import digest, write_json_atomic
from audio.processing import duration, split_mp3
from audio.quality import file_sha, read, safe_audio_path
from audio.text import input_by_ref, spoken_text

ROOT = Path(__file__).resolve().parents[2]
VERSION = '1.0-boundary-observer'
PROMPT = (
    'Inspect Biblical Hebrew recording edges. Listen; never fill missing sounds '
    'from the supplied text or memory. Cantillation and pronunciation variants '
    'are allowed. Each input has its own id and expected edge words. For a head '
    'judge ONLY the original beginning; for a tail ONLY the original ending. '
    'The other end was deliberately cut for this excerpt and is NOT a defect. '
    'For whole clips judge BOTH original ends; no artificial edge exists. '
    'For context clips expected_order describes the two verses around the cut. '
    'The expected words may exceed a short excerpt: use UNCERTAIN, not FAIL, '
    'when context is insufficient. Judge missing edge words, clipping at the '
    'original edge and speech belonging to another verse. For context clips '
    'judge the marked original cut; suggest an offset in seconds only when '
    'audible. Return JSON {"clips":[{"id":"...","status":"PASS|FAIL|UNCERTAIN",'
    '"heard":"audible edge words","evidence":"brief acoustic reason",'
    '"suggested_cut_seconds":null}]}. No prose. Do not claim full-verse QA.'
)


def persist_reservation(run):
    # Actions runners are ephemeral. A local write alone cannot survive a job
    # cancellation; publish the reservation before making any paid request.
    # Offline fixtures live outside ver3/runs and never execute git commands.
    if os.getenv('GITHUB_ACTIONS') and Path(run).resolve().is_relative_to(ROOT / 'runs'):
        from runner import commit_run
        commit_run(run, 'Reserve bounded audio inspection budget before API request')


def policy():
    value = read(ROOT / 'config/audio-boundary.json')
    if value['model'] not in ('gpt-audio-1.5', 'gpt-audio'):
        raise ValueError('Unsupported boundary listening model')
    for key in ('clip_seconds', 'context_seconds', 'edge_words', 'clips_per_request',
                'max_output_tokens', 'max_requests', 'max_audio_seconds',
                'max_estimated_usd', 'reserve_audio_tokens_per_second',
                'audio_input_usd_per_million', 'text_input_usd_per_million',
                'text_output_usd_per_million', 'timeout_seconds'):
        if not isinstance(value[key], (int, float)) or not math.isfinite(value[key]) or value[key] <= 0:
            raise ValueError('Invalid boundary policy: ' + key)
    return value


def identity(run, audio_dir):
    data = read(Path(run) / 'audio-input.json')
    manifest = read(Path(audio_dir) / 'audio_manifest.json')
    return {
        'run_id': Path(run).name, 'input_sha256': digest(data),
        'manifest_sha256': digest(manifest),
        'audio_sha256': {v['ref']: file_sha(safe_audio_path(audio_dir, v['r2']))
                         for v in manifest['verses']},
    }


def expected_edges(data, verse, count):
    ref = f"{data['passage']['book']}.{verse['chapter']}.{verse['verse']}"
    words = input_by_ref(data)[ref]['words']
    return {'head': spoken_text(words[:count]), 'tail': spoken_text(words[-count:])}


def edge_jobs(run, audio_dir, settings):
    data = read(Path(run) / 'audio-input.json')
    manifest = read(Path(audio_dir) / 'audio_manifest.json')
    jobs = []
    verses = manifest['verses']
    for index, v in enumerate(verses):
        path = safe_audio_path(audio_dir, v['r2'])
        length = duration(path)
        edges = expected_edges(data, v, settings['edge_words'])
        sides = ('whole',) if length <= settings['clip_seconds'] * 2 else ('head', 'tail')
        for side in sides:
            if side == 'whole':
                full = f"{data['passage']['book']}.{v['chapter']}.{v['verse']}"
                expected = spoken_text(input_by_ref(data)[full]['words'])
            else:
                expected = edges[side]
            start = 0 if side == 'head' else max(0, length - settings['clip_seconds'])
            end = min(length, settings['clip_seconds']) if side == 'head' else length
            if side == 'whole':
                start, end = 0, length
            adjacent = index - 1 if side == 'head' else index + 1
            other = expected_edges(data, verses[adjacent], settings['edge_words']) if 0 <= adjacent < len(verses) else {}
            jobs.append({
                'id': v['ref'] + '/' + side, 'ref': v['ref'], 'side': side,
                'path': str(path), 'audio_sha256': file_sha(path),
                'start': round(start, 6), 'end': round(end, 6),
                'expected': expected, 'other_edge': other.get('tail' if side == 'head' else 'head', ''),
                'boundary_start': v['boundary_start'], 'boundary_end': v['boundary_end'],
                'boundary_start_meta': v.get('boundary_start_meta'),
                'boundary_end_meta': v.get('boundary_end_meta'),
            })
    return jobs


def cache_key(job, settings):
    # Local file location/whole manifest are irrelevant when the actual clip,
    # expected text, model and instructions are unchanged.
    keys = ('audio_sha256', 'start', 'end', 'expected', 'other_edge', 'side', 'cut_seconds', 'expected_order')
    return digest({'clip': {k: job.get(k) for k in keys}, 'model': settings['model'],
                   'version': VERSION, 'prompt': PROMPT})


def public_job(job):
    return {k: v for k, v in job.items() if k != 'path'}


def estimated_cost(seconds, text, settings):
    # UTF-8 byte count is intentionally conservative for the short text prompt.
    return (seconds * settings['reserve_audio_tokens_per_second'] * settings['audio_input_usd_per_million']
            + (len(text.encode('utf-8')) + 256) * settings['text_input_usd_per_million']
            + settings['max_output_tokens'] * settings['text_output_usd_per_million']) / 1_000_000


def usage_cost(usage, settings):
    if not usage or 'audio_tokens' not in usage.get('prompt_tokens_details', {}):
        return None
    audio = usage['prompt_tokens_details']['audio_tokens']
    text = max(0, usage.get('prompt_tokens', 0) - audio)
    return (audio * settings['audio_input_usd_per_million']
            + text * settings['text_input_usd_per_million']
            + usage.get('completion_tokens', 0) * settings['text_output_usd_per_million']) / 1_000_000


def observe(run, jobs, settings=None):
    """Collect short observations under a single durable per-RUN budget."""
    settings = settings or policy()
    desk = Path(run) / 'audio-boundary'
    desk.mkdir(parents=True, exist_ok=True)
    ledger_path = desk / 'usage.json'
    ledger = read(ledger_path, {'run_id': Path(run).name, 'requests': [], 'cache': {}})
    if ledger['run_id'] != Path(run).name:
        raise ValueError('Boundary budget belongs to another RUN')
    cache = ledger['cache']
    pending, seen = [], set()
    for job in jobs:
        key = cache_key(job, settings)
        if key not in cache and key not in seen:
            pending.append((key, job))
            seen.add(key)
    while pending:
        batch = pending[:int(settings['clips_per_request'])]
        pending = pending[len(batch):]
        descriptions = [{k: job.get(k) for k in ('id', 'side', 'expected', 'other_edge', 'cut_seconds', 'expected_order')}
                        for _, job in batch]
        text = PROMPT + '\n' + json.dumps(descriptions, ensure_ascii=False)
        seconds = sum(job['end'] - job['start'] for _, job in batch)
        reserve = estimated_cost(seconds, text, settings)
        used = ledger['requests']
        spent = sum(max(r['reserved_usd'], r.get('actual_usd') or 0) for r in used)
        reason = None
        if not settings.get('enabled', True):
            reason = 'POLICY_DISABLED'
        elif not os.getenv('OPENAI_API_KEY', '').strip():
            reason = 'LISTENING_KEY_UNAVAILABLE'
        elif ledger.get('api_disabled'):
            reason = ledger['api_disabled']
        elif (len(used) >= settings['max_requests']
              or sum(r['audio_seconds'] for r in used) + seconds > settings['max_audio_seconds']
              or spent + reserve > settings['max_estimated_usd']):
            reason = 'BOUNDARY_BUDGET_LIMIT'
        if reason:
            for key, job in batch:
                cache[key] = {'status': 'UNCERTAIN', 'heard': '', 'evidence': reason}
            write_json_atomic(ledger_path, ledger)
            continue
        # Claim the request and its clips before any paid work. A killed process
        # leaves UNCERTAIN entries, never a reason to send the same audio again.
        record = {'id': len(used) + 1, 'status': 'RESERVED', 'audio_seconds': seconds,
                  'reserved_usd': reserve, 'model': settings['model'],
                  'clip_keys': [key for key, _ in batch]}
        used.append(record)
        for key, job in batch:
            cache[key] = {'status': 'UNCERTAIN', 'heard': '', 'evidence': 'REQUEST_INTERRUPTED_OR_INCOMPLETE'}
        write_json_atomic(ledger_path, ledger)
        try:
            persist_reservation(run)
            content = [{'type': 'text', 'text': text}]
            with tempfile.TemporaryDirectory(prefix='torah-boundary-') as tmp:
                for index, (_, job) in enumerate(batch):
                    clip = Path(tmp) / f'{index}.mp3'
                    split_mp3(Path(job['path']), job['start'], job['end'], clip)
                    content.extend([
                        {'type': 'text', 'text': 'Clip ' + job['id']},
                        {'type': 'input_audio', 'input_audio': {'format': 'mp3',
                         'data': base64.b64encode(clip.read_bytes()).decode('ascii')}},
                    ])
            response = requests.post(
                'https://api.openai.com/v1/chat/completions',
                headers={'Authorization': 'Bearer ' + os.environ['OPENAI_API_KEY'],
                         'Content-Type': 'application/json'},
                json={'model': settings['model'], 'modalities': ['text'], 'temperature': 0,
                      'store': False, 'max_tokens': settings['max_output_tokens'],
                      'messages': [{'role': 'user', 'content': content}]},
                timeout=settings['timeout_seconds'])
            record['http_status'] = response.status_code
            record['api_request_id'] = response.headers.get('x-request-id')
            if not response.ok:
                ledger['api_disabled'] = f'LISTENING_HTTP_{response.status_code}'
                raise ValueError(ledger['api_disabled'])
            payload = response.json()
            record['usage'] = payload.get('usage')
            record['actual_usd'] = usage_cost(payload.get('usage'), settings)
            raw = payload['choices'][0]['message'].get('content', '').strip()
            if raw.startswith('```'):
                raw = raw.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
            rows = json.loads(raw)['clips']
            by_id = {r['id']: r for r in rows}
            if len(by_id) != len(rows) or set(by_id) != {j['id'] for _, j in batch}:
                raise ValueError('Invalid observation coverage')
            for key, job in batch:
                row = by_id[job['id']]
                status = row.get('status')
                if (status not in ('PASS', 'FAIL', 'UNCERTAIN')
                        or not isinstance(row.get('heard'), str)
                        or not isinstance(row.get('evidence'), str) or not row['evidence'].strip()
                        or (status == 'PASS' and not row['heard'].strip())):
                    raise ValueError('Invalid observation evidence')
            if payload['choices'][0].get('finish_reason') != 'stop':
                raise ValueError('Incomplete observation response')
            for key, job in batch:
                row = by_id[job['id']]
                cache[key] = {'status': row['status'], 'heard': row['heard'][:300],
                              'evidence': row['evidence'][:400], 'request_id': record['id'],
                              'suggested_cut_seconds': row.get('suggested_cut_seconds')}
            record['status'] = 'OBSERVED'
        except Exception as error:
            # Even transport exceptions may contain credential URLs or payloads.
            # Persist only the type and a safe, locally generated reason.
            record.update(status='UNRESOLVED', error_type=type(error).__name__)
            ledger['api_disabled'] = ledger.get('api_disabled', 'LISTENING_REQUEST_FAILED')
            for key, job in batch:
                cache[key] = {'status': 'UNCERTAIN', 'heard': '', 'evidence': ledger['api_disabled']}
        write_json_atomic(ledger_path, ledger)
    return [{**public_job(j), 'cache_key': cache_key(j, settings),
             'observation': cache[cache_key(j, settings)]} for j in jobs]


def report(run, audio_dir=None, *, filename='report.json'):
    settings = policy()
    run = Path(run)
    audio_dir = Path(audio_dir) if audio_dir else run / 'audio'
    rows = observe(run, edge_jobs(run, audio_dir, settings), settings)
    current = identity(run, audio_dir)
    machine_path = (run / 'audio-quality.json' if audio_dir == run / 'audio'
                    else run / 'audio-boundary/candidate-machine.json')
    machine = read(machine_path, {})
    # After candidate adoption the root machine report can still describe the
    # old MP3 set. Never carry old defect findings onto newly selected bytes.
    if (machine.get('manifest_sha256') != current['manifest_sha256']
            or machine.get('input_sha256') != current['input_sha256']):
        machine = {}
    known = {v['ref']: v.get('findings', []) for v in machine.get('verses', [])
             if v.get('findings') and v.get('r2_sha256') == current['audio_sha256'].get(v['ref'])}
    for row in rows:
        row['known_findings'] = known.get(row['ref'], [])
    result = {
        'schema_version': '1.0-boundary-report', **current,
        'scope': 'ALL_IMPLEMENTED_VERSE_HEADS_AND_TAILS_ONLY',
        'full_content_verified': False, 'policy_sha256': digest(settings),
        'observations': rows,
        'problem_edges': [r['id'] for r in rows if r['observation']['status'] != 'PASS' or r['known_findings']],
        'missing_audio_refs': [v['ref'] for v in read(audio_dir / 'audio_manifest.json').get('failed_verses', [])],
    }
    result['status'] = 'BOUNDARY_OBSERVATIONS_PASS' if rows and not result['problem_edges'] else 'BOUNDARY_OBSERVATIONS_UNRESOLVED'
    write_json_atomic(run / 'audio-boundary' / filename, result)
    return result
