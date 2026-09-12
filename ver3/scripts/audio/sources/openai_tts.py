"""Last-resort OpenAI TTS adapter; it performs no source-selection logic."""
import os
from pathlib import Path

import requests

from audio.text import spoken_text


class OpenAITTSError(RuntimeError):
    pass


def fetch_openai(ref, verse_data, policy, audio_dir, stem, legacy_request=None):
    api_key = os.getenv('OPENAI_API_KEY', '').strip()
    if not api_key:
        raise OpenAITTSError(
            'OPENAI_API_KEY is not configured in GitHub Actions secrets')
    settings = dict(policy['openai_tts'])
    if legacy_request:
        settings['model'] = legacy_request.get('model', settings['model'])
        settings['voice'] = legacy_request.get('voice', settings['voice'])
        settings['required_disclosure'] = legacy_request.get(
            'required_disclosure', settings['required_disclosure'])
    text = spoken_text(verse_data['words'])
    try:
        response = requests.post(
            'https://api.openai.com/v1/audio/speech',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'model': settings['model'],
                'voice': settings['voice'],
                'input': text,
                'instructions': settings['instructions'],
                'response_format': 'mp3',
            },
            timeout=180,
        )
    except requests.RequestException as error:
        raise OpenAITTSError(
            f'OpenAI POST /v1/audio/speech: {error}') from error
    if response.status_code >= 300:
        raise OpenAITTSError(
            'OpenAI POST /v1/audio/speech: '
            f'{response.status_code} {response.text[:600]}')
    audio_dir = Path(audio_dir)
    r1 = audio_dir / f'{stem}_ai_r1.mp3'
    r2 = audio_dir / f'{stem}_ai_r2.mp3'
    r1.write_bytes(response.content)
    source_meta = {
        'ai_model': settings['model'],
        'ai_voice': settings['voice'],
        'openai_request_id': response.headers.get('x-request-id'),
    }
    return r1, r2, settings['required_disclosure'], source_meta

