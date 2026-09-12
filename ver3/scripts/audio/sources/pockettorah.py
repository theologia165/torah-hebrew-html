"""Primary PocketTorah source adapter and per-verse extractor."""
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from audio.processing import (
    TARGET_WPS,
    duration,
    mean_volume_db,
    speed_mp3,
    split_mp3,
)


POCKETTORAH_SHA = '8a23287221dd535966ee9914de9a03e71769a469'
BASE_RAW = f'https://raw.githubusercontent.com/rneiss/PocketTorah/{POCKETTORAH_SHA}'
ALIYAH_URL = f'{BASE_RAW}/data/aliyah.json'
SILENCE_NOISE_DB = -38
SILENCE_MIN_D = 0.08
SIGNAL_WINDOW = 1.25


def fail(message):
    print(f'FAIL: {message}', file=sys.stderr)
    raise SystemExit(1)


def get_bytes(url):
    request = urllib.request.Request(
        url, headers={'User-Agent': 'asaichi-torah-ver3'})
    return urllib.request.urlopen(request, timeout=60).read()


def detect_silences(path):
    import subprocess
    result = subprocess.run([
        'ffmpeg', '-hide_banner', '-nostats', '-i', str(path),
        '-af', f'silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_D}',
        '-f', 'null', '-',
    ], text=True, capture_output=True)
    starts = [
        float(value)
        for value in re.findall(r'silence_start:\s*([0-9.]+)', result.stderr)
    ]
    ends = [
        float(value)
        for value in re.findall(r'silence_end:\s*([0-9.]+)', result.stderr)
    ]
    return [
        (start, ends[index]) for index, start in enumerate(starts)
        if index < len(ends) and ends[index] >= start
    ]


def boundary_meta(candidate, silences):
    nearby = []
    for start, end in silences:
        if end < candidate - SIGNAL_WINDOW or start > candidate + SIGNAL_WINDOW:
            continue
        nearby.append((min(abs(candidate - start), abs(candidate - end)), start, end))
    record = {
        'candidate': candidate,
        'refined': candidate,
        'method': 'label_onset_model_pending',
    }
    if nearby:
        _, start, end = min(nearby, key=lambda item: item[0])
        record['signal'] = {
            'nearest_silence_start': start,
            'nearest_silence_end': end,
            'distance_to_silence_end': candidate - end,
        }
    return record


def resolve_source(data):
    aliyah = json.loads(get_bytes(ALIYAH_URL).decode('utf-8-sig'))
    passage = data['passage']
    start_chapter = int(passage['chapter'])
    end_chapter = int(passage.get('end_chapter', start_chapter))
    begin = f"{start_chapter}:{passage['start_verse']}"
    end = f"{end_chapter}:{passage['end_verse']}"
    matches = []
    for parasha in aliyah['parshiot']['parsha']:
        if not parasha.get('_verse', '').startswith(passage['book'] + ' '):
            continue
        for item in parasha.get('fullkriyah', {}).get('aliyah', []):
            if (item.get('_begin') == begin and item.get('_end') == end
                    and item.get('_num') != 'M'):
                matches.append((parasha['_id'], item['_num']))
    if len(matches) != 1:
        fail(
            f'PocketTorah aliyah mapping expected 1 match for '
            f'{begin}-{end}, got {matches}')
    parasha, aliyah_number = matches[0]
    base = f'{parasha}-{aliyah_number}'
    audio_base = re.sub(r"[\s'’]+", '', base)
    tree = json.loads(get_bytes(
        'https://api.github.com/repos/rneiss/PocketTorah/git/trees/'
        f'{POCKETTORAH_SHA}?recursive=1'))
    wanted = f'data/torah/labels/{base}.txt'
    exact = [
        item['path'] for item in tree['tree']
        if item['path'].casefold() == wanted.casefold()
    ]
    if len(exact) != 1:
        fail(f'Labels filename resolution expected 1 match for {wanted}, got {exact}')
    labels_base = Path(exact[0]).stem
    return {
        'parsha': parasha,
        'aliyah': aliyah_number,
        'base': base,
        'audio_base': audio_base,
        'labels_base': labels_base,
        'audio_url': (
            f'{BASE_RAW}/data/audio/'
            f'{urllib.parse.quote(audio_base, safe="")}.mp3'),
        'labels_url': (
            f'{BASE_RAW}/data/torah/labels/'
            f'{urllib.parse.quote(labels_base, safe="")}.txt'),
    }


def _failed_record(chapter, verse, word_count, mapping_status, signal_status,
                   highest_stage, failure_code, reason):
    return {
        'chapter': chapter,
        'verse': verse,
        'ref': f'{chapter}:{verse}',
        'word_count': word_count,
        'MAPPING_STATUS': mapping_status,
        'SIGNAL_STATUS': signal_status,
        'MODEL_AUDIO_STATUS': 'NOT_RUN',
        'HIGHEST_VERIFIED_STAGE': highest_stage,
        'DELIVERY_STATUS': 'NOT_IMPLEMENTED_FAILED',
        'FAILURE_CODE': failure_code,
        'LIMITATION_REASON': reason,
    }


def build(data, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    passage = data['passage']
    default_chapter = int(passage['chapter'])
    cross_chapter = int(
        passage.get('end_chapter', default_chapter)) != default_chapter
    source_meta = resolve_source(data)
    source = output / f"{source_meta['audio_base']}_source.mp3"
    source.write_bytes(get_bytes(source_meta['audio_url']))
    labels = [
        float(value) for value in get_bytes(source_meta['labels_url'])
        .decode('utf-8-sig').strip().split(',') if value.strip()
    ]
    word_counts = [len(verse['words']) for verse in data['verses']]
    total_words = sum(word_counts)
    if len(labels) not in (total_words, total_words + 1):
        fail(
            f'MAPPING: label count {len(labels)} incompatible with '
            f'word count {total_words}')
    source_duration = duration(source)

    # A label beyond the physical MP3 is a stable source defect.  It is not a
    # boundary or atempo problem and is the only kind of defect eligible for
    # automatic fallback without further evidence.
    outside = [
        (index + 1, onset) for index, onset in enumerate(labels[:total_words])
        if onset > source_duration
    ]
    if len(labels) == total_words + 1 and labels[-1] <= source_duration + 0.25:
        word_onsets, explicit_end = labels[:-1], labels[-1]
    else:
        word_onsets, explicit_end = labels[:total_words], source_duration
    if len(word_onsets) != total_words:
        fail('MAPPING: could not normalize PocketTorah label count')

    silences = detect_silences(source)
    cumulative = [0]
    for count in word_counts:
        cumulative.append(cumulative[-1] + count)
    boundaries = []
    for index in range(len(data['verses']) + 1):
        if index == 0:
            boundaries.append({
                'candidate': word_onsets[0],
                'refined': word_onsets[0],
                'method': 'first_word_onset',
            })
        elif index == len(data['verses']):
            boundaries.append({
                'candidate': explicit_end,
                'refined': explicit_end,
                'method': 'source_end',
            })
        else:
            boundaries.append(boundary_meta(
                word_onsets[cumulative[index]], silences))
    for index in range(1, len(boundaries)):
        if boundaries[index]['refined'] <= boundaries[index - 1]['refined']:
            fail(f'SIGNAL: non-monotonic boundary {index}')

    sequence = data['sequence']
    records = []
    failed = []
    for index, verse_data in enumerate(data['verses']):
        chapter = int(verse_data.get('chapter', default_chapter))
        verse = int(verse_data['verse'])
        start = boundaries[index]['refined']
        end = boundaries[index + 1]['refined']
        stem = (
            f'{sequence}_{chapter}_{verse}' if cross_chapter
            else f'{sequence}_{verse}')
        r1 = output / f'{stem}_r1.mp3'
        r2 = output / f'{stem}_r2.mp3'
        word_start, word_end = cumulative[index], cumulative[index + 1]
        verse_outside = [
            (token_index + 1, labels[token_index])
            for token_index in range(word_start, word_end)
            if token_index < len(labels)
            and labels[token_index] > source_duration
        ]
        if verse_outside:
            first_index, first_time = verse_outside[0]
            reason = (
                f'PocketTorah source truncated: label word '
                f'{first_index}/{total_words} onset={first_time:.6f}s exceeds '
                f'audio duration={source_duration:.6f}s; '
                f'verse_out_of_audio_labels={len(verse_outside)}')
            for path in (r1, r2):
                path.unlink(missing_ok=True)
            failed.append(_failed_record(
                chapter, verse, len(verse_data['words']), 'FAILED', 'NOT_RUN',
                'NONE', 'POCKETTORAH_SOURCE_TRUNCATED', reason))
            continue
        if end - start < 0.4:
            reason = f'boundary duration too short: {end - start:.6f}s'
            for path in (r1, r2):
                path.unlink(missing_ok=True)
            failed.append(_failed_record(
                chapter, verse, len(verse_data['words']), 'FAILED', 'NOT_RUN',
                'NONE', 'POCKETTORAH_BOUNDARY_TOO_SHORT', reason))
            continue

        split_mp3(source, start, end, r1)
        r1_duration = duration(r1)
        source_wps = len(verse_data['words']) / r1_duration
        factor = TARGET_WPS / source_wps
        if not 0.25 <= factor <= 4.0:
            for path in (r1, r2):
                path.unlink(missing_ok=True)
            failed.append(_failed_record(
                chapter, verse, len(verse_data['words']), 'PASS', 'FAILED',
                'MAPPING_CONFIRMED', 'POCKETTORAH_ATEMPO_OUT_OF_RANGE',
                f'unreasonable atempo={factor:.6f}'))
            continue
        speed_mp3(r1, factor, r2)
        r2_duration = duration(r2)
        theoretical = r1_duration / factor
        mean_db = mean_volume_db(r1)
        if mean_db < -55.0:
            fail(f'SIGNAL: verse {chapter}:{verse} mean volume too low')
        records.append({
            'chapter': chapter,
            'verse': verse,
            'ref': f'{chapter}:{verse}',
            'word_count': len(verse_data['words']),
            'boundary_start': start,
            'boundary_end': end,
            'boundary_start_meta': boundaries[index],
            'boundary_end_meta': boundaries[index + 1],
            'r1': r1.name,
            'r1_duration': r1_duration,
            'source_wps': source_wps,
            'target_wps': TARGET_WPS,
            'atempo': factor,
            'r2': r2.name,
            'r2_duration': r2_duration,
            'r2_theoretical_duration': theoretical,
            'r2_duration_error': abs(r2_duration - theoretical),
            'r2_wps': len(verse_data['words']) / r2_duration,
            'mean_volume_db': mean_db,
            'MAPPING_STATUS': 'PASS',
            'SIGNAL_STATUS': 'PASS',
            'MODEL_AUDIO_STATUS': 'NOT_RUN',
            'HIGHEST_VERIFIED_STAGE': 'SIGNAL_CHECKED',
            'DELIVERY_STATUS': 'READY',
            'LIMITATION_REASON': '',
            'audio_origin': 'POCKETTORAH',
        })

    expected_refs = [
        f"{int(verse.get('chapter', default_chapter))}:{int(verse['verse'])}"
        for verse in data['verses']
    ]
    status = 'PARTIAL' if failed else 'PASS'
    manifest = {
        'schema_version': 'audio-1.3',
        'status': status,
        'sequence': sequence,
        'passage': passage,
        'expected_refs': expected_refs,
        'source': {
            **source_meta,
            'pockettorah_commit': POCKETTORAH_SHA,
            'source_file': source.name,
            'source_duration': source_duration,
            'label_count': len(labels),
            'word_count': total_words,
            'out_of_audio_label_count': len(outside),
        },
        'qa': {
            'MAPPING_CONFIRMED': not failed,
            'SIGNAL_CHECKED': not failed,
            'MODEL_AUDIO_CHECKED': False,
            'AUDIO_DELIVERY_COMPLETE': not failed,
            'AUDIO_VERIFICATION_COMPLETE': False,
            'target_wps': TARGET_WPS,
            'boundary_rule': (
                'PocketTorah next-word onset is the deterministic shared '
                'boundary; signal pauses are annotations only until '
                'MODEL_AUDIO confirms prior-word completion and no next-verse '
                'contamination'),
        },
        'verses': records,
        'failed_verses': failed,
    }
    (output / 'audio_manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    print(
        f'{status}: AUDIO build implemented={len(records)} failed={len(failed)} '
        f'words={total_words} source={source_meta["base"]} '
        f'target_wps={TARGET_WPS} model_audio=PENDING')
    return manifest


def main():
    if len(sys.argv) != 3:
        fail('usage: build_audio.py <enriched.json> <audio-output-dir>')
    data = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    build(data, Path(sys.argv[2]))


if __name__ == '__main__':
    main()

