"""Collect actual audio-model observations; Work still owns the final review."""
import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from audio.manifest import digest, write_json_atomic
from audio.quality import file_sha, read, safe_audio_path
from audio.text import input_by_ref, spoken_text


def collect(run, desk, audio_dir):
    run, desk, audio_dir = Path(run), Path(desk), Path(audio_dir)
    request = read(desk / 'audio-model-review-request.json')
    if not request:
        return None
    manifest = read(audio_dir / 'audio_manifest.json')
    audio_input = read(run / 'audio-input.json')
    if (request.get('run_id') != run.name
            or request.get('manifest_sha256') != digest(manifest)
            or request.get('input_sha256') != digest(audio_input)):
        raise ValueError('Audio model review request is not bound to this candidate')
    model = request.get('model')
    if model not in ('gpt-audio-1.5', 'gpt-audio'):
        raise ValueError('Unsupported listening model')
    expected = input_by_ref(audio_input)
    path = desk / 'model-audio-observations.json'
    audit = read(path) or {
        'schema_version': '1.0-model-audio-observations', 'run_id': run.name,
        'input_sha256': digest(audio_input), 'manifest_sha256': digest(manifest),
        'model': model, 'review_request_sha256': digest(request), 'verses': [],
        'purpose': 'Observations only. Work must evaluate them before writing a content PASS.',
    }
    if audit.get('review_request_sha256') != digest(request):
        raise ValueError('Existing listening observations belong to another request')
    for verse in manifest['verses']:
        hashes = {key + '_sha256': file_sha(safe_audio_path(audio_dir, verse[key]))
                  for key in ('r1', 'r2')}
        prior = next((row for row in audit['verses'] if row['ref'] == verse['ref']), None)
        if prior and all(prior.get(key) == value for key, value in hashes.items()):
            continue
        full_ref = f"{audio_input['passage']['book']}.{verse['chapter']}.{verse['verse']}"
        text = spoken_text(expected[full_ref]['words'])
        prompt = (
            'You are checking two recordings of the same Biblical Hebrew verse. '
            'Listen to BOTH audio inputs, not just the reference text. The first is '
            'natural speed r1, the second is study speed r2. Normal cantillation, '
            'Ashkenazi/Israeli pronunciation and vowel-letter spelling variation are '
            'not errors. First transcribe what is audible. Then compare it with the '
            'reference. Do not silently fill in missing words from memory or the '
            'reference. Mark UNCERTAIN when you cannot establish a word or a clipped '
            'ending. Check all words, including repetitions. Return only JSON with '
            'heard_text_r1, heard_text_r2, and r1/r2 objects each containing '
            'first_word, last_word, word_order, no_other_verse, no_truncation, '
            'study_speed (each PASS/FAIL/UNCERTAIN), missing_words, extra_words, '
            'clipped_words arrays, and evidence explaining what you heard. '
            'study_speed means intelligible with no unnatural acceleration; '
            'r1 may be faster than r2. Also return doubts as an array. '
            f'Reference {full_ref}: {text}')
        content = [{'type': 'text', 'text': prompt}]
        for key in ('r1', 'r2'):
            content.append({'type': 'text', 'text': f'Recording {key}'})
            content.append({'type': 'input_audio', 'input_audio': {
                'format': 'mp3',
                'data': base64.b64encode(safe_audio_path(audio_dir, verse[key]).read_bytes()).decode('ascii'),
            }})
        response = requests.post(
            'https://api.openai.com/v1/chat/completions',
            headers={'Authorization': 'Bearer ' + os.environ['OPENAI_API_KEY'],
                     'Content-Type': 'application/json'},
            json={'model': model, 'modalities': ['text'], 'temperature': 0,
                  'max_tokens': 2200, 'store': False,
                  'messages': [{'role': 'user', 'content': content}]},
            timeout=180)
        if not response.ok:
            # Never log request bodies or the API key/audio payload.
            raise RuntimeError(f'Audio listening API {response.status_code}: {response.text[:800]}')
        payload = response.json()
        raw = payload['choices'][0]['message'].get('content') or ''
        cleaned = raw.strip()
        if cleaned.startswith('```'):
            cleaned = cleaned.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
        try:
            observation = json.loads(cleaned)
        except json.JSONDecodeError:
            observation = {'parse_status': 'UNSTRUCTURED', 'raw_text': raw}
        record = {
            'ref': verse['ref'], **hashes, 'expected_text': text,
            'model': payload.get('model', model),
            'api_request_id': response.headers.get('x-request-id'),
            'response_id': payload.get('id'), 'usage': payload.get('usage'),
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'observation': observation,
        }
        audit['verses'] = [row for row in audit['verses'] if row['ref'] != verse['ref']] + [record]
        audit['status'] = 'OBSERVATIONS_INCOMPLETE'
        write_json_atomic(path, audit)
        print(f'MODEL_AUDIO_OBSERVATION: {verse["ref"]} recorded; Work review still required')
    audit['status'] = 'OBSERVATIONS_COMPLETE_NOT_A_CONTENT_PASS'
    write_json_atomic(path, audit)
    return path
