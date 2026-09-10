#!/usr/bin/env python3
"""Repair one explicitly approved missing verse with OpenAI TTS.

The input text is derived only from the current RUN's audio-input.json.  The
script never accepts free-form Hebrew in the repair request, so a retry cannot
silently drift from the Neon/MorphHB token sequence.
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


def fail(message):
    raise RuntimeError(message)


def run(*args):
    subprocess.run(args, check=True)


def duration(path):
    p = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=nokey=1:noprint_wrappers=1', str(path)],
        text=True, capture_output=True, check=True)
    return float(p.stdout.strip())


def mean_volume_db(path):
    p = subprocess.run(
        ['ffmpeg', '-hide_banner', '-i', str(path), '-af', 'volumedetect',
         '-f', 'null', '-'], text=True, capture_output=True)
    m = re.search(r'mean_volume:\s*(-?[0-9.]+) dB', p.stderr)
    if not m:
        fail(f'Could not measure mean volume for {path}')
    return float(m.group(1))


def atempo_chain(factor):
    values = []
    while factor < 0.5:
        values.append(0.5)
        factor /= 0.5
    while factor > 2.0:
        values.append(2.0)
        factor /= 2.0
    values.append(factor)
    return ','.join(f'atempo={v:.9f}' for v in values)


def spoken_text(words):
    # Remove cantillation marks but retain niqqud/dagesh.  This prevents the
    # speech model from treating trope marks as stray control-like characters.
    return ' '.join(re.sub(r'[\u0591-\u05af]', '', w['surface']) for w in words)


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: build_ai_audio.py <run-dir>')
    run_dir = Path(sys.argv[1])
    request_path = run_dir / 'ai-audio-request.json'
    if not request_path.exists():
        return
    request = json.loads(request_path.read_text(encoding='utf-8'))
    if request.get('status') != 'APPROVED_LAST_RESORT':
        fail('AI audio request is not explicitly approved as last resort')
    if request.get('run_id') != run_dir.name:
        fail('AI audio request run_id mismatch')
    if float(request.get('target_wps', 0)) != TARGET_WPS:
        fail('AI audio request target_wps mismatch')

    audio_input = json.loads((run_dir / 'audio-input.json').read_text(encoding='utf-8'))
    manifest_path = run_dir / 'audio' / 'audio_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    target = request['ref'].split('.')
    if len(target) != 3:
        fail('AI audio request ref must be OSIS book.chapter.verse')
    chapter, verse = int(target[1]), int(target[2])
    matches = [v for v in audio_input['verses']
               if int(v.get('chapter', audio_input['passage']['chapter'])) == chapter
               and int(v['verse']) == verse]
    if len(matches) != 1:
        fail(f'Expected one audio-input verse for {request["ref"]}, got {len(matches)}')
    verse_data = matches[0]
    failed = [v for v in manifest.get('failed_verses', [])
              if int(v['chapter']) == chapter and int(v['verse']) == verse]
    if len(failed) != 1 or 'PocketTorah source truncated' not in failed[0].get('LIMITATION_REASON', ''):
        fail('AI fallback is allowed only for the audited PocketTorah truncation')

    audio_dir = run_dir / 'audio'
    stem = f'{audio_input["sequence"]}_{chapter}_{verse}_ai'
    r1 = audio_dir / f'{stem}_r1.mp3'
    r2 = audio_dir / f'{stem}_r2.mp3'
    audit_path = run_dir / 'ai-audio-audit.json'
    existing = [v for v in manifest.get('verses', [])
                if int(v['chapter']) == chapter and int(v['verse']) == verse]
    if existing:
        if (existing[0].get('audio_origin') == 'OPENAI_TTS' and r1.exists()
                and r2.exists() and audit_path.exists()):
            print(f'SKIP_AI_AUDIO_EXISTS: {request["ref"]}')
            return
        fail('A non-identical audio record already exists for the requested verse')

    api_key = os.getenv('OPENAI_API_KEY', '').strip()
    if not api_key:
        fail('OPENAI_API_KEY is not configured in GitHub Actions secrets')
    text = spoken_text(verse_data['words'])
    model = request.get('model', 'gpt-4o-mini-tts')
    voice = request.get('voice', 'cedar')
    instructions = (
        'Read only the supplied Hebrew text once. Use a clear, reverent male voice '
        'and careful standard Israeli pronunciation suitable for studying Biblical '
        'Hebrew. Preserve every word and its order. Do not add a verse number, '
        'translation, introduction, explanation, or closing words.')
    response = requests.post(
        'https://api.openai.com/v1/audio/speech',
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        json={'model': model, 'voice': voice, 'input': text,
              'instructions': instructions, 'response_format': 'mp3'}, timeout=180)
    if response.status_code >= 300:
        fail(f'OpenAI POST /v1/audio/speech: {response.status_code} {response.text[:600]}')
    r1.write_bytes(response.content)
    d1 = duration(r1)
    word_count = len(verse_data['words'])
    source_wps = word_count / d1
    factor = TARGET_WPS / source_wps
    if not 0.25 <= factor <= 4.0:
        fail(f'OpenAI TTS produced unreasonable atempo={factor:.6f}')
    run('ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', str(r1),
        '-af', atempo_chain(factor), '-c:a', 'libmp3lame', '-q:a', '2', str(r2))
    d2 = duration(r2)
    theoretical = d1 / factor
    mean_db = mean_volume_db(r1)
    if mean_db < -55.0:
        fail(f'OpenAI TTS mean volume too low: {mean_db:.1f} dB')

    record = {
        'chapter': chapter, 'verse': verse, 'ref': f'{chapter}:{verse}',
        'word_count': word_count, 'boundary_start': 0.0, 'boundary_end': d1,
        'boundary_start_meta': {'candidate': 0.0, 'refined': 0.0,
                                'method': 'standalone_ai_source_start'},
        'boundary_end_meta': {'candidate': d1, 'refined': d1,
                              'method': 'standalone_ai_source_end'},
        'boundary_scope': 'STANDALONE_SYNTHETIC',
        'r1': r1.name, 'r1_duration': d1, 'source_wps': source_wps,
        'target_wps': TARGET_WPS, 'atempo': factor,
        'r2': r2.name, 'r2_duration': d2,
        'r2_theoretical_duration': theoretical,
        'r2_duration_error': abs(d2 - theoretical), 'r2_wps': word_count / d2,
        'mean_volume_db': mean_db, 'MAPPING_STATUS': 'PASS',
        'SIGNAL_STATUS': 'PASS', 'MODEL_AUDIO_STATUS': 'NOT_RUN',
        'HIGHEST_VERIFIED_STAGE': 'SIGNAL_CHECKED', 'DELIVERY_STATUS': 'READY',
        'LIMITATION_REASON': '', 'audio_origin': 'OPENAI_TTS',
        'ai_disclosure': 'OpenAIによるAI生成音声（PocketTorah原音欠損のため）'
    }
    manifest['verses'].append(record)
    order = {ref: i for i, ref in enumerate(manifest['expected_refs'])}
    manifest['verses'].sort(key=lambda v: order[v['ref']])
    manifest['failed_verses'] = [v for v in manifest.get('failed_verses', [])
                                  if v['ref'] != f'{chapter}:{verse}']
    manifest['status'] = 'PASS' if not manifest['failed_verses'] else 'PARTIAL'
    manifest['qa'].update({
        'MAPPING_CONFIRMED': not manifest['failed_verses'],
        'SIGNAL_CHECKED': not manifest['failed_verses'],
        'AUDIO_DELIVERY_COMPLETE': not manifest['failed_verses'],
        'AI_FALLBACK_REFS': [request['ref']],
        'AI_DISCLOSURE_REQUIRED': True,
    })
    manifest['fallback_sources'] = [{
        'ref': request['ref'], 'type': 'OPENAI_TTS', 'model': model, 'voice': voice,
        'reason': failed[0]['LIMITATION_REASON'],
        'disclosure': record['ai_disclosure'],
    }]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    audit = {
        'schema_version': '1.0-ai-audio-audit', 'status': 'PASS',
        'run_id': run_dir.name, 'ref': request['ref'],
        'input_source': 'current-run audio-input.json tokens',
        'token_ids': [w['id'] for w in verse_data['words']],
        'input_text': text,
        'input_sha256': hashlib.sha256(text.encode()).hexdigest(),
        'model': model, 'voice': voice,
        'openai_request_id': response.headers.get('x-request-id'),
        'r1': r1.name, 'r2': r2.name, 'target_wps': TARGET_WPS,
        'measured_r2_wps': word_count / d2,
        'disclosure': record['ai_disclosure'],
    }
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'PASS: OpenAI TTS repaired {request["ref"]}; words={word_count} r2_wps={word_count/d2:.6f}')


if __name__ == '__main__':
    main()
