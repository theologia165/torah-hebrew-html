"""Deterministic finalization gate for a delivered Ver.3 RUN."""
import json
from pathlib import Path


SCHEMA_VERSION = '1.0-work-completion'


def _read_json(path):
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding='utf-8'))


def expected_next_sequence(sequence):
    return f'{int(sequence) + 1:03d}'


def inspect_completion(run, production_path='ver3/state/production.json'):
    """Return machine-readable reasons why a RUN is not formally complete."""
    run = Path(run)
    delivery = _read_json(run / 'delivery.json') or {}
    completion = _read_json(run / 'completion.json')
    production = _read_json(production_path) or {}
    run_id = delivery.get('run_id') or run.name
    sequence = str(run_id.split('-', 1)[0])
    reasons = []

    if delivery.get('status') != 'PASS':
        reasons.append('DELIVERY_NOT_PASS')
    if delivery.get('cover', {}).get('status') != 'PASS':
        reasons.append('DELIVERY_COVER_NOT_PASS')
    if delivery.get('missing_audio_refs'):
        reasons.append('DELIVERY_AUDIO_MISSING')
    if delivery.get('missing_html_refs'):
        reasons.append('DELIVERY_HTML_MISSING')

    if completion is None:
        reasons.append('COMPLETION_RECEIPT_MISSING')
    else:
        if completion.get('schema_version') != SCHEMA_VERSION:
            reasons.append('COMPLETION_RECEIPT_SCHEMA_INVALID')
        if completion.get('run_id') != run_id:
            reasons.append('COMPLETION_RECEIPT_RUN_MISMATCH')
        if str(completion.get('sequence')) != sequence:
            reasons.append('COMPLETION_RECEIPT_SEQUENCE_MISMATCH')
        if completion.get('delivery_status') != 'PASS':
            reasons.append('COMPLETION_DELIVERY_NOT_PASS')
        if completion.get('page_id') != delivery.get('page_id'):
            reasons.append('COMPLETION_PAGE_ID_MISMATCH')
        if completion.get('page_url') != delivery.get('page_url'):
            reasons.append('COMPLETION_PAGE_URL_MISMATCH')
        gmail = completion.get('gmail') or {}
        if gmail.get('sent_verified') is not True:
            reasons.append('GMAIL_SENT_NOT_VERIFIED')
        if not gmail.get('message_id'):
            reasons.append('GMAIL_MESSAGE_ID_MISSING')
        if not gmail.get('subject'):
            reasons.append('GMAIL_SUBJECT_MISSING')
        if not completion.get('completed_at'):
            reasons.append('COMPLETION_TIMESTAMP_MISSING')

    last = production.get('last_completed') or {}
    if last.get('run_id') != run_id or str(last.get('sequence')) != sequence:
        reasons.append('PRODUCTION_LAST_COMPLETED_MISMATCH')
    if last.get('status') != 'PASS':
        reasons.append('PRODUCTION_LAST_COMPLETED_NOT_PASS')
    if last.get('page_id') != delivery.get('page_id'):
        reasons.append('PRODUCTION_PAGE_ID_MISMATCH')
    if last.get('page_url') != delivery.get('page_url'):
        reasons.append('PRODUCTION_PAGE_URL_MISMATCH')
    if completion:
        gmail = completion.get('gmail') or {}
        if last.get('gmail_message_id') != gmail.get('message_id'):
            reasons.append('PRODUCTION_GMAIL_MESSAGE_MISMATCH')
        if last.get('gmail_sent_verified') is not True:
            reasons.append('PRODUCTION_GMAIL_NOT_VERIFIED')
    if production.get('next_sequence') != expected_next_sequence(sequence):
        reasons.append('PRODUCTION_NEXT_SEQUENCE_NOT_ADVANCED')

    return {
        'complete': not reasons,
        'run_id': run_id,
        'sequence': sequence,
        'expected_next_sequence': expected_next_sequence(sequence),
        'reasons': reasons,
    }
