#!/usr/bin/env python3
"""Fast contract tests for the production audio fallback decision gate."""
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import build_ai_audio as fallback
from build_ai_audio import (choose_fallback, classify_failure, spoken_text,
                            validate_policy)


def main():
    root = Path(__file__).resolve().parents[1]
    policy = validate_policy(json.loads(
        (root / 'config' / 'audio-fallback.json').read_text(encoding='utf-8')))
    verse = {'words': [
        {'id': 101, 'surface': 'וַיֹּאמֶר'},
        {'id': 102, 'surface': 'אֵלָיו'},
    ]}
    truncated = {
        'ref': '28:4',
        'LIMITATION_REASON': 'PocketTorah source truncated: test fixture',
    }
    assert classify_failure(truncated) == 'POCKETTORAH_SOURCE_TRUNCATED'
    automatic = choose_fallback('Gen.28.4', truncated, verse, policy)
    assert automatic['selected_source'] == 'OPENAI_TTS'
    assert automatic['open_bible_status'] == 'NO_APPROVED_EXACT_SOURCE_IN_REGISTRY'

    unsafe = {'ref': '28:4', 'FAILURE_CODE': 'POCKETTORAH_BOUNDARY_TOO_SHORT',
              'LIMITATION_REASON': 'boundary duration too short: test fixture'}
    blocked = choose_fallback('Gen.28.4', unsafe, verse, policy)
    assert blocked['status'] == 'BLOCKED' and blocked['selected_source'] is None

    registered = copy.deepcopy(policy)
    text_sha = hashlib.sha256(spoken_text(verse['words']).encode('utf-8')).hexdigest()
    registered['open_bible']['approved_verse_sources']['Gen.28.4'] = {
        'status': 'VERIFIED_EXACT_VERSE', 'ref': 'Gen.28.4',
        'url': 'https://open.bible/example/gen-28-4.mp3',
        'audio_sha256': 'a' * 64, 'spoken_text_sha256': text_sha,
        'word_count': 2, 'license': 'CC BY',
        'attribution_label': 'Verified Open.Bible fixture',
        'attribution_url': 'https://open.bible/bibles',
        'verified_on': '2026-09-12',
    }
    second_source = choose_fallback('Gen.28.4', truncated, verse, registered)
    assert second_source['selected_source'] == 'OPEN_BIBLE'

    registered['open_bible']['approved_verse_sources']['Gen.28.4'][
        'spoken_text_sha256'] = 'b' * 64
    integrity_block = choose_fallback('Gen.28.4', truncated, verse, registered)
    assert integrity_block['status'] == 'BLOCKED'
    assert integrity_block['open_bible_status'] == 'REGISTRY_INTEGRITY_FAILED'

    # Missing API credentials must not abort delivery of other media. Exercise
    # two failed verses to keep the standard path multi-ref, unlike the 041
    # one-off request which handled only one verse.
    with tempfile.TemporaryDirectory() as directory:
        run = Path(directory) / '999-test-r1'
        audio = run / 'audio'
        audio.mkdir(parents=True)
        audio_input = {
            'sequence': '999',
            'passage': {'book': 'Gen', 'chapter': 28, 'start_verse': 4,
                        'end_verse': 5},
            'verses': [
                {'chapter': 28, 'verse': 4, 'words': verse['words']},
                {'chapter': 28, 'verse': 5, 'words': [
                    {'id': 103, 'surface': 'וְאֵל'},
                    {'id': 104, 'surface': 'שַׁדַּי'},
                ]},
            ],
        }
        failures = [
            {'chapter': 28, 'verse': number, 'ref': f'28:{number}',
             'word_count': 2, 'MAPPING_STATUS': 'FAILED',
             'SIGNAL_STATUS': 'NOT_RUN', 'MODEL_AUDIO_STATUS': 'NOT_RUN',
             'HIGHEST_VERIFIED_STAGE': 'NONE',
             'DELIVERY_STATUS': 'NOT_IMPLEMENTED_FAILED',
             'FAILURE_CODE': 'POCKETTORAH_SOURCE_TRUNCATED',
             'LIMITATION_REASON': 'PocketTorah source truncated: test fixture'}
            for number in (4, 5)
        ]
        manifest = {
            'schema_version': 'audio-1.3', 'status': 'PARTIAL',
            'sequence': '999', 'passage': audio_input['passage'],
            'expected_refs': ['28:4', '28:5'],
            'source': {'pockettorah_commit': 'fixture'},
            'qa': {'MAPPING_CONFIRMED': False, 'SIGNAL_CHECKED': False,
                   'MODEL_AUDIO_CHECKED': False,
                   'AUDIO_DELIVERY_COMPLETE': False, 'target_wps': 0.79306},
            'verses': [], 'failed_verses': failures,
        }
        (run / 'audio-input.json').write_text(json.dumps(audio_input), encoding='utf-8')
        (audio / 'audio_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        env = dict(os.environ)
        env.pop('OPENAI_API_KEY', None)
        result = subprocess.run(
            [sys.executable, str(root / 'scripts' / 'build_ai_audio.py'), str(run)],
            text=True, capture_output=True, env=env)
        assert result.returncode == 0, result.stderr
        audited = json.loads((run / 'ai-audio-audit.json').read_text(encoding='utf-8'))
        partial = json.loads((audio / 'audio_manifest.json').read_text(encoding='utf-8'))
        assert audited['status'] == 'PARTIAL' and len(audited['decisions']) == 2
        assert all(item['FALLBACK_STATUS'] == 'FAILED'
                   for item in partial['failed_verses'])
        verified = subprocess.run(
            [sys.executable, str(root / 'scripts' / 'verify_audio.py'), str(audio)],
            text=True, capture_output=True)
        assert verified.returncode == 0, verified.stderr

    # Exercise the full standard (no per-RUN request) OpenAI path without a
    # network call. The fixture audio proves r1/r2, manifest and audit wiring.
    with tempfile.TemporaryDirectory() as directory:
        run = Path(directory) / '998-test-r1'
        audio = run / 'audio'
        audio.mkdir(parents=True)
        audio_input = {
            'sequence': '998',
            'passage': {'book': 'Gen', 'chapter': 28, 'start_verse': 4,
                        'end_verse': 4},
            'verses': [{'chapter': 28, 'verse': 4, 'words': verse['words']}],
        }
        failure = {
            'chapter': 28, 'verse': 4, 'ref': '28:4', 'word_count': 2,
            'MAPPING_STATUS': 'FAILED', 'SIGNAL_STATUS': 'NOT_RUN',
            'MODEL_AUDIO_STATUS': 'NOT_RUN', 'HIGHEST_VERIFIED_STAGE': 'NONE',
            'DELIVERY_STATUS': 'NOT_IMPLEMENTED_FAILED',
            'FAILURE_CODE': 'POCKETTORAH_SOURCE_TRUNCATED',
            'LIMITATION_REASON': 'PocketTorah source truncated: test fixture',
        }
        manifest = {
            'schema_version': 'audio-1.3', 'status': 'PARTIAL',
            'sequence': '998', 'passage': audio_input['passage'],
            'expected_refs': ['28:4'], 'source': {'pockettorah_commit': 'fixture'},
            'qa': {'MAPPING_CONFIRMED': False, 'SIGNAL_CHECKED': False,
                   'MODEL_AUDIO_CHECKED': False,
                   'AUDIO_DELIVERY_COMPLETE': False, 'target_wps': 0.79306},
            'verses': [], 'failed_verses': [failure],
        }
        (run / 'audio-input.json').write_text(json.dumps(audio_input), encoding='utf-8')
        (audio / 'audio_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        tone = run / 'tts-fixture.mp3'
        subprocess.run([
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
            '-i', 'sine=frequency=440:duration=2', '-c:a', 'libmp3lame', str(tone),
        ], check=True)

        class FakeResponse:
            status_code = 200
            content = tone.read_bytes()
            headers = {'x-request-id': 'test-request-id'}
            text = ''

        prior_key = os.environ.get('OPENAI_API_KEY')
        os.environ['OPENAI_API_KEY'] = 'test-key-never-sent'
        prior_argv = sys.argv
        sys.argv = ['build_ai_audio.py', str(run)]
        try:
            with patch.object(fallback.requests, 'post', return_value=FakeResponse()):
                fallback.main()
        finally:
            sys.argv = prior_argv
            if prior_key is None:
                os.environ.pop('OPENAI_API_KEY', None)
            else:
                os.environ['OPENAI_API_KEY'] = prior_key
        repaired = json.loads((audio / 'audio_manifest.json').read_text(encoding='utf-8'))
        audit = json.loads((run / 'ai-audio-audit.json').read_text(encoding='utf-8'))
        assert repaired['status'] == 'PASS' and not repaired['failed_verses']
        assert repaired['verses'][0]['audio_origin'] == 'OPENAI_TTS'
        assert repaired['verses'][0]['ai_disclosure']
        assert audit['decisions'][0]['token_ids'] == [101, 102]
        assert audit['decisions'][0]['openai_request_id'] == 'test-request-id'
        verified = subprocess.run(
            [sys.executable, str(root / 'scripts' / 'verify_audio.py'), str(audio)],
            text=True, capture_output=True)
        assert verified.returncode == 0, verified.stderr

        # The second-source path requires exact bytes and carries attribution,
        # while keeping the Notion audio caption empty (tested in contracts).
        open_entry = {
            'status': 'VERIFIED_EXACT_VERSE', 'ref': 'Gen.28.4',
            'url': 'https://open.bible/example/gen-28-4.mp3',
            'audio_sha256': hashlib.sha256(tone.read_bytes()).hexdigest(),
            'spoken_text_sha256': hashlib.sha256(
                spoken_text(verse['words']).encode('utf-8')).hexdigest(),
            'word_count': 2, 'license': 'CC BY',
            'attribution_label': 'Verified Open.Bible fixture',
            'attribution_url': 'https://open.bible/bibles',
            'verified_on': '2026-09-12',
        }
        fallback.validate_open_bible_entry(
            'Gen.28.4', open_entry, policy,
            open_entry['spoken_text_sha256'], 2)
        with patch.object(fallback.requests, 'get', return_value=FakeResponse()):
            open_r1, open_r2, source_meta = fallback.fetch_open_bible(
                'Gen.28.4', open_entry, audio, '998_4_fixture')
        open_record = fallback.make_audio_record(
            'Gen.28.4', verse, open_r1, open_r2, 'OPEN_BIBLE',
            source_meta=source_meta)
        assert open_record['audio_origin'] == 'OPEN_BIBLE'
        assert open_record['source_license'] == 'CC BY'
        assert 'ai_disclosure' not in open_record
    print('PASS: audio fallback hierarchy, exact-source gates, multi-ref PARTIAL continuation')


if __name__ == '__main__':
    main()
