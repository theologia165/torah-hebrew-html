"""Load and enforce the production audio fallback policy."""
import hashlib
import json
import re
from pathlib import Path

from audio.text import spoken_text


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = ROOT / 'config' / 'audio-fallback.json'


def load_policy(path=DEFAULT_POLICY):
    path = Path(path)
    policy = json.loads(path.read_text(encoding='utf-8'))
    registry_path = policy.get('open_bible', {}).get('registry_path')
    if registry_path:
        registry = Path(registry_path)
        if not registry.is_absolute():
            registry = ROOT / registry
        sources = json.loads(registry.read_text(encoding='utf-8'))
        if sources.get('schema_version') != '1.0-open-bible-source-registry':
            raise RuntimeError('Unsupported Open.Bible source registry schema')
        policy['open_bible']['approved_verse_sources'] = sources.get(
            'approved_verse_sources', {})
        policy['open_bible']['registry_sha256'] = hashlib.sha256(
            registry.read_bytes()).hexdigest()
    return validate_policy(policy)


def validate_policy(policy):
    if policy.get('schema_version') != '1.0-audio-fallback-policy':
        raise RuntimeError('Unsupported audio fallback policy schema')
    if policy.get('status') != 'APPROVED_PRODUCTION_POLICY':
        raise RuntimeError('Audio fallback production policy is not approved')
    if policy.get('priority') != ['POCKETTORAH', 'OPEN_BIBLE', 'OPENAI_TTS']:
        raise RuntimeError(
            'Audio fallback priority must be PocketTorah → Open.Bible → OpenAI TTS')
    if abs(float(policy.get('target_wps', 0)) - 0.79306) > 1e-9:
        raise RuntimeError('Audio fallback policy target_wps mismatch')
    open_bible = policy.setdefault('open_bible', {})
    open_bible.setdefault('approved_verse_sources', {})
    if not isinstance(open_bible['approved_verse_sources'], dict):
        raise RuntimeError('Open.Bible approved source registry must be an object')
    return policy


def classify_failure(item):
    """Return a stable code; string parsing exists only for legacy manifests."""
    if item.get('FAILURE_CODE'):
        return item['FAILURE_CODE']
    reason = item.get('LIMITATION_REASON', '')
    if 'PocketTorah source truncated' in reason:
        return 'POCKETTORAH_SOURCE_TRUNCATED'
    if 'boundary duration too short' in reason:
        return 'POCKETTORAH_BOUNDARY_TOO_SHORT'
    if 'unreasonable atempo=' in reason:
        return 'POCKETTORAH_ATEMPO_OUT_OF_RANGE'
    return 'UNCLASSIFIED_AUDIO_FAILURE'


def validate_open_bible_entry(ref, entry, policy, text_sha256, word_count):
    """Fail closed unless a registry entry is the verified exact verse."""
    required = (
        'status', 'ref', 'url', 'audio_sha256', 'spoken_text_sha256',
        'word_count', 'license', 'attribution_label', 'attribution_url',
        'verified_on',
    )
    missing = [key for key in required if key not in entry]
    if missing:
        raise RuntimeError(f'Open.Bible registry entry {ref} lacks {missing}')
    if entry['status'] != 'VERIFIED_EXACT_VERSE' or entry['ref'] != ref:
        raise RuntimeError(f'Open.Bible registry entry {ref} is not exact-ref verified')
    if not entry['url'].startswith('https://'):
        raise RuntimeError(
            f'Open.Bible registry entry {ref} has a non-HTTPS audio URL')
    if not re.fullmatch(r'[0-9a-f]{64}', entry['audio_sha256']):
        raise RuntimeError(
            f'Open.Bible registry entry {ref} has an invalid audio_sha256')
    if entry['spoken_text_sha256'] != text_sha256:
        raise RuntimeError(
            f'Open.Bible registry entry {ref} does not match current RUN spoken text')
    if int(entry['word_count']) != word_count:
        raise RuntimeError(f'Open.Bible registry entry {ref} word count mismatch')
    if entry['license'] not in policy['open_bible']['allowed_licenses']:
        raise RuntimeError(
            f'Open.Bible registry entry {ref} license is not approved')
    if (not entry['attribution_label'].strip()
            or not entry['attribution_url'].startswith('https://')):
        raise RuntimeError(
            f'Open.Bible registry entry {ref} lacks valid attribution')
    return entry


def choose_fallback(ref, failure, verse_data, policy):
    """Choose a source without performing network or audio operations."""
    code = classify_failure(failure)
    if code not in policy['eligible_pockettorah_failure_codes']:
        return {
            'ref': ref,
            'status': 'BLOCKED',
            'selected_source': None,
            'primary_failure_code': code,
            'reason': (
                'PocketTorah failure is not an approved physical-source defect'),
        }
    text = spoken_text(verse_data['words'])
    text_sha256 = hashlib.sha256(text.encode('utf-8')).hexdigest()
    entry = policy['open_bible']['approved_verse_sources'].get(ref)
    if entry is not None:
        try:
            validate_open_bible_entry(
                ref, entry, policy, text_sha256, len(verse_data['words']))
        except Exception as error:
            return {
                'ref': ref,
                'status': 'BLOCKED',
                'selected_source': None,
                'primary_failure_code': code,
                'open_bible_status': 'REGISTRY_INTEGRITY_FAILED',
                'reason': str(error),
            }
        return {
            'ref': ref,
            'status': 'PLANNED',
            'selected_source': 'OPEN_BIBLE',
            'primary_failure_code': code,
            'open_bible_status': 'VERIFIED_EXACT_SOURCE',
            'open_bible_entry': entry,
        }
    if policy['openai_tts'].get('enabled') is True:
        return {
            'ref': ref,
            'status': 'PLANNED',
            'selected_source': 'OPENAI_TTS',
            'primary_failure_code': code,
            'open_bible_status': 'NO_APPROVED_EXACT_SOURCE_IN_REGISTRY',
        }
    return {
        'ref': ref,
        'status': 'BLOCKED',
        'selected_source': None,
        'primary_failure_code': code,
        'open_bible_status': 'NO_APPROVED_EXACT_SOURCE_IN_REGISTRY',
        'reason': 'OpenAI TTS is disabled by production policy',
    }
