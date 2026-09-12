"""Shared ffmpeg/ffprobe processing for every approved audio source."""
import re
import subprocess


TARGET_WPS = 0.79306


class AudioProcessingError(RuntimeError):
    pass


def run_checked(args):
    result = subprocess.run(args, text=True, capture_output=True)
    if result.returncode:
        raise AudioProcessingError(
            f"command failed: {' '.join(map(str, args))}\n{result.stderr}")
    return result


def duration(path):
    result = run_checked([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=nokey=1:noprint_wrappers=1', str(path),
    ])
    return float(result.stdout.strip())


def mean_volume_db(path):
    result = subprocess.run([
        'ffmpeg', '-hide_banner', '-nostats', '-i', str(path),
        '-af', 'volumedetect', '-f', 'null', '-',
    ], text=True, capture_output=True)
    match = re.search(r'mean_volume:\s*(-?[0-9.]+) dB', result.stderr)
    if not match:
        raise AudioProcessingError(f'Could not measure mean volume for {path}')
    return float(match.group(1))


def atempo_chain(factor):
    if factor <= 0:
        raise AudioProcessingError(f'invalid atempo {factor}')
    values = []
    while factor < 0.5:
        values.append(0.5)
        factor /= 0.5
    while factor > 2.0:
        values.append(2.0)
        factor /= 2.0
    values.append(factor)
    return ','.join(f'atempo={value:.9f}' for value in values)


def split_mp3(source, start, end, output):
    run_checked([
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', str(source),
        '-af', f'atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS',
        '-c:a', 'libmp3lame', '-q:a', '2', str(output),
    ])


def speed_mp3(source, factor, output):
    run_checked([
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', str(source),
        '-af', atempo_chain(factor), '-c:a', 'libmp3lame', '-q:a', '2',
        str(output),
    ])


def make_audio_record(ref, verse_data, r1, r2, origin, disclosure='',
                      source_meta=None):
    """Normalize a standalone fallback source and return one manifest record."""
    d1 = duration(r1)
    word_count = len(verse_data['words'])
    source_wps = word_count / d1
    factor = TARGET_WPS / source_wps
    if not 0.25 <= factor <= 4.0:
        raise AudioProcessingError(
            f'{origin} produced unreasonable atempo={factor:.6f}')
    speed_mp3(r1, factor, r2)
    d2 = duration(r2)
    theoretical = d1 / factor
    mean_db = mean_volume_db(r1)
    if mean_db < -55.0:
        raise AudioProcessingError(
            f'{origin} mean volume too low: {mean_db:.1f} dB')
    _, chapter, verse = ref.split('.')
    record = {
        'chapter': int(chapter),
        'verse': int(verse),
        'ref': f'{int(chapter)}:{int(verse)}',
        'word_count': word_count,
        'boundary_start': 0.0,
        'boundary_end': d1,
        'boundary_start_meta': {
            'candidate': 0.0,
            'refined': 0.0,
            'method': f'standalone_{origin.lower()}_source_start',
        },
        'boundary_end_meta': {
            'candidate': d1,
            'refined': d1,
            'method': f'standalone_{origin.lower()}_source_end',
        },
        'boundary_scope': f'STANDALONE_{origin}',
        'r1': r1.name,
        'r1_duration': d1,
        'source_wps': source_wps,
        'target_wps': TARGET_WPS,
        'atempo': factor,
        'r2': r2.name,
        'r2_duration': d2,
        'r2_theoretical_duration': theoretical,
        'r2_duration_error': abs(d2 - theoretical),
        'r2_wps': word_count / d2,
        'mean_volume_db': mean_db,
        'MAPPING_STATUS': 'PASS',
        'SIGNAL_STATUS': 'PASS',
        'MODEL_AUDIO_STATUS': 'NOT_RUN',
        'HIGHEST_VERIFIED_STAGE': 'SIGNAL_CHECKED',
        'DELIVERY_STATUS': 'READY',
        'LIMITATION_REASON': '',
        'audio_origin': origin,
    }
    if disclosure:
        record['ai_disclosure'] = disclosure
    if source_meta:
        record.update(source_meta)
    return record

