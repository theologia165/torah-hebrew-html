"""Atomic audit and manifest updates for the audio resolver."""
import hashlib
import json
from pathlib import Path


def digest(value):
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(',', ':')
    ).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def write_json_atomic(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    temporary.replace(path)


def checkpoint(manifest_path, manifest, audit_path, audit):
    write_json_atomic(manifest_path, manifest)
    write_json_atomic(audit_path, audit)


def update_manifest(manifest, record, failure, decision):
    manifest['verses'].append(record)
    order = {ref: index for index, ref in enumerate(manifest['expected_refs'])}
    manifest['verses'].sort(key=lambda verse: order[verse['ref']])
    manifest['failed_verses'] = [
        item for item in manifest.get('failed_verses', [])
        if item['ref'] != failure['ref']
    ]
    manifest['status'] = 'PASS' if not manifest['failed_verses'] else 'PARTIAL'
    book = decision['ref'].split('.')[0]
    as_osis = lambda verse: f'{book}.{verse["chapter"]}.{verse["verse"]}'
    ai_refs = [
        as_osis(verse) for verse in manifest['verses']
        if verse.get('audio_origin') == 'OPENAI_TTS'
    ]
    open_refs = [
        as_osis(verse) for verse in manifest['verses']
        if verse.get('audio_origin') == 'OPEN_BIBLE'
    ]
    manifest.setdefault('qa', {}).update({
        'MAPPING_CONFIRMED': not manifest['failed_verses'],
        'SIGNAL_CHECKED': not manifest['failed_verses'],
        'AUDIO_DELIVERY_COMPLETE': not manifest['failed_verses'],
        'AI_FALLBACK_REFS': ai_refs,
        'OPEN_BIBLE_FALLBACK_REFS': open_refs,
        'AI_DISCLOSURE_REQUIRED': bool(ai_refs),
    })
    sources = [
        item for item in manifest.get('fallback_sources', [])
        if item.get('ref') != decision['ref']
    ]
    source = {
        'ref': decision['ref'],
        'type': record['audio_origin'],
        'reason': failure.get('LIMITATION_REASON', ''),
        'primary_failure_code': decision['primary_failure_code'],
        'open_bible_status': decision.get('open_bible_status'),
    }
    if record['audio_origin'] == 'OPENAI_TTS':
        source.update(
            model=record['ai_model'],
            voice=record['ai_voice'],
            disclosure=record['ai_disclosure'],
        )
    else:
        source.update(
            license=record['source_license'],
            attribution_label=record['source_attribution_label'],
            attribution_url=record['source_attribution_url'],
        )
    manifest['fallback_sources'] = sources + [source]

