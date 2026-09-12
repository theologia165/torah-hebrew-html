#!/usr/bin/env python3
"""Offline integration test for the separated PocketTorah adapter."""
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from audio.sources import pockettorah


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        tone = root / 'source.mp3'
        subprocess.run([
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
            '-f', 'lavfi', '-i', 'sine=frequency=440:duration=4',
            '-c:a', 'libmp3lame', str(tone),
        ], check=True)
        data = {
            'sequence': '999',
            'passage': {
                'book': 'Genesis', 'chapter': 1, 'start_verse': 1,
                'end_verse': 2,
            },
            'verses': [
                {'chapter': 1, 'verse': 1, 'words': [
                    {'id': 1, 'surface': 'בְּרֵאשִׁית'},
                    {'id': 2, 'surface': 'בָּרָא'},
                ]},
                {'chapter': 1, 'verse': 2, 'words': [
                    {'id': 3, 'surface': 'וְהָאָרֶץ'},
                    {'id': 4, 'surface': 'הָיְתָה'},
                ]},
            ],
        }
        source_meta = {
            'parsha': 'fixture', 'aliyah': '1', 'base': 'fixture-1',
            'audio_base': 'fixture-1', 'labels_base': 'fixture-1',
            'audio_url': 'https://example.test/source.mp3',
            'labels_url': 'https://example.test/labels.txt',
        }

        def fixture_bytes(url):
            if url.endswith('.mp3'):
                return tone.read_bytes()
            return b'0.0,1.0,2.0,3.0,4.0'

        output = root / 'audio'
        with patch.object(pockettorah, 'resolve_source', return_value=source_meta), \
                patch.object(pockettorah, 'get_bytes', side_effect=fixture_bytes), \
                patch.object(pockettorah, 'detect_silences', return_value=[]):
            manifest = pockettorah.build(data, output)
        assert manifest['status'] == 'PASS'
        assert [item['ref'] for item in manifest['verses']] == ['1:1', '1:2']
        assert all(
            item['audio_origin'] == 'POCKETTORAH'
            for item in manifest['verses'])
        verify = subprocess.run([
            sys.executable,
            str(Path(__file__).with_name('verify_audio.py')),
            str(output),
        ], text=True, capture_output=True)
        assert verify.returncode == 0, verify.stderr
    print('PASS: separated PocketTorah adapter and shared processing')


if __name__ == '__main__':
    main()

