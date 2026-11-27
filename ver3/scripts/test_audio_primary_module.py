#!/usr/bin/env python3
"""Offline integration test for the separated PocketTorah adapter."""
import subprocess
import sys
import tempfile
import json
import os
from pathlib import Path
from unittest.mock import patch

from audio.sources import pockettorah
from audio.processing import normalized_atempo


def main():
    # Standard Jewish Yitro-6 is WLC19:20-20:17, never a shortened reading.
    counts = [16, 15, 10, 20, 19, 6, 7, 9, 7, 16, 21, 6,
              17, 5, 6, 18, 26, 15, 2, 2, 2, 5, 15]
    refs = [(19, v) for v in range(20, 26)] + [(20, v) for v in range(1, 18)]
    yitro = {'passage': {'book': 'Exodus', 'chapter': 19,
                         'start_verse': 20, 'end_chapter': 20, 'end_verse': 17},
             'verses': [{'chapter': c, 'verse': v, 'words': [{}] * n}
                        for (c, v), n in zip(refs, counts)]}
    begin, end, mapping = pockettorah.source_range(yitro)
    assert (begin, end) == ('19:20', '20:14')
    assert mapping['word_count'] == 265 and mapping['wlc_verse_count'] == 23
    source_fixture = {'parshiot': {'parsha': [{
        '_id': 'Yitro', '_verse': 'Exodus 18:1 - 20:23',
        'fullkriyah': {'aliyah': [{'_begin': '19:20', '_end': '20:14',
                                 '_num': '6'}]}}]}}
    tree_fixture = {'tree': [{'path': 'data/torah/labels/Yitro-6.txt'}]}
    with patch.object(pockettorah, 'get_bytes', side_effect=[
            json.dumps(source_fixture).encode(), json.dumps(tree_fixture).encode()]):
        resolved = pockettorah.resolve_source(yitro)
    assert resolved['audio_base'] == 'Yitro-6'
    assert resolved['verse_numbering_mapping'] == mapping
    for bad in (dict(yitro, verses=yitro['verses'][:-1]),
                dict(yitro, verses=list(reversed(yitro['verses'])))):
        try:
            pockettorah.source_range(bad)
        except SystemExit:
            pass
        else:
            raise AssertionError('Incomplete/reordered WLC range accepted')
    yitro['verses'][-1]['words'] = [{}] * 14
    try:
        pockettorah.source_range(yitro)
    except SystemExit:
        pass
    else:
        raise AssertionError('Changed Yitro word count accepted')
    assert pockettorah.source_range({'passage': {'book': 'Genesis', 'chapter': 1,
           'start_verse': 1, 'end_verse': 2}}) == ('1:1', '1:2', None)
    # The following standard aliyah uses the same three-verse numbering shift.
    seventh = {'passage': {'book': 'Exodus', 'chapter': 20,
                           'start_verse': 18, 'end_verse': 26},
               'verses': [{'chapter': 20, 'verse': v, 'words': [{}]}
                          for v in range(18, 27)]}
    assert pockettorah.source_range(seventh)[:2] == ('20:15', '20:23')
    source_fixture['parshiot']['parsha'][0]['fullkriyah']['aliyah'] = [
        {'_begin': '20:15', '_end': '20:23', '_num': '7'}]
    tree_fixture['tree'][0]['path'] = 'data/torah/labels/Yitro-7.txt'
    with patch.object(pockettorah, 'get_bytes', side_effect=[
            json.dumps(source_fixture).encode(), json.dumps(tree_fixture).encode()]):
        assert pockettorah.resolve_source(seventh)['audio_base'] == 'Yitro-7'
    try:
        pockettorah.source_range(dict(seventh, verses=seventh['verses'][:-1]))
    except SystemExit:
        pass
    else:
        raise AssertionError('Incomplete Yitro-7 WLC range accepted')
    # Reproduce the 093 last-word spill without applying 085's label shift.
    fixture_profile = {
        'id': 'boundary-test', 'audio_base': 'test-source',
        'pockettorah_commit': pockettorah.POCKETTORAH_SHA,
        'audio_sha256': 'audio-hash', 'labels_sha256': 'labels-hash',
        'word_count': 2, 'verse_word_counts': [1, 1],
        'expected_refs': ['6:16', '6:17'], 'boundaries': [0, 2.7, 5],
    }
    fixture_data = {'passage': {'chapter': 6}, 'verses': [
        {'verse': 16, 'words': [{}]}, {'verse': 17, 'words': [{}]}]}
    prior_cuts = [{'candidate': t, 'refined': t} for t in [0.2, 1.1, 5]]
    fixture_meta = {key: fixture_profile[key] for key in
                    ('audio_base', 'audio_sha256', 'labels_sha256')}
    with patch.object(Path, 'exists', return_value=True), \
            patch.object(Path, 'read_text', return_value=json.dumps({'profiles': [fixture_profile]})):
        corrected = pockettorah.verified_verse_boundaries(
            fixture_data, fixture_meta.copy(), 5, prior_cuts)
        assert [v['refined'] for v in corrected] == [0, 2.7, 5]
        assert corrected[1]['candidate'] == 1.1
        assert pockettorah.verified_verse_boundaries(
            fixture_data, {'audio_base': 'unrelated'}, 5, prior_cuts) == prior_cuts
        try:
            pockettorah.verified_verse_boundaries(
                fixture_data, dict(fixture_meta, audio_sha256='changed'), 5, prior_cuts)
        except SystemExit:
            pass
        else:
            raise AssertionError('Changed source accepted reviewed boundaries')
    with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token'}), \
            patch.object(pockettorah.urllib.request, 'urlopen') as open_url:
        open_url.return_value.read.return_value = b'{}'
        pockettorah.get_bytes('https://api.github.com/repos/rneiss/PocketTorah/git/trees/pinned')
        assert open_url.call_args.args[0].get_header('Authorization') == 'Bearer test-token'
        for url in ('https://raw.githubusercontent.com/rneiss/PocketTorah/pinned/file',
                    'https://api.github.com.example.test/file',
                    'http://api.github.com/file'):
            pockettorah.get_bytes(url)
            assert open_url.call_args.args[0].get_header('Authorization') is None
    registry = json.loads((Path(__file__).resolve().parents[1] /
                           'quality/audio/source-alignments.json').read_text())
    profile = registry['profiles'][0]
    # The 085 source has a leading marker plus N word onsets, not an end label.
    fixture_labels = [0] + [1.5 + i for i in range(181)]
    meta = {'audio_base': profile['audio_base']}
    onsets, ending = pockettorah.normalize_labels(
        fixture_labels, 181, 187.48075, meta,
        profile['audio_sha256'], profile['labels_sha256'])
    assert onsets == fixture_labels[1:] and ending == 187.48075
    assert onsets[11] == fixture_labels[12]
    assert meta['label_alignment'] == 'LEADING_ZERO_THEN_WORD_ONSETS'
    try:
        pockettorah.normalize_labels(fixture_labels, 181, 187.48075,
                                    {'audio_base': profile['audio_base']},
                                    '0' * 64, profile['labels_sha256'])
    except SystemExit:
        pass
    else:
        raise AssertionError('Changed source bytes accepted a pinned correction')
    # Other sources keep their prior convention; a zero alone is not evidence.
    assert pockettorah.normalize_labels([0, 1, 2], 2, 3,
                                      {'audio_base': 'other'}, '', '') == ([0, 1], 2)
    factor, capped = normalized_atempo(0.35)
    assert factor == 1.0 and capped is True
    factor, capped = normalized_atempo(1.0)
    assert factor < 1.0 and capped is False
    refined = pockettorah.boundary_meta(1.0, [(0.8, 1.2)])
    assert refined['refined'] == 1.2
    assert refined['method'] == 'next_word_onset_refined_to_silence_end'
    refined_before = pockettorah.boundary_meta(0.6, [(0.8, 1.2)])
    assert refined_before['refined'] == 1.2
    assert refined_before['method'] == 'next_word_onset_refined_to_silence_end'
    unchanged_after = pockettorah.boundary_meta(1.3, [(0.8, 1.2)])
    assert unchanged_after['refined'] == 1.3
    assert unchanged_after['method'] == 'next_word_onset'
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

