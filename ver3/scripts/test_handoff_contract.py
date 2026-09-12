#!/usr/bin/env python3
"""Fast contract test for small, stage-scoped Work handoffs."""
import json
import tempfile
from pathlib import Path

from completion_gate import inspect_completion
from handoff import (no_action, pipeline_failure, ready_for_email,
                     waiting_for_cover, waiting_for_json2)


def main():
    with tempfile.TemporaryDirectory() as directory:
        run = Path(directory) / '999-test-r1'
        run.mkdir()
        (run / 'json1.json').write_text(json.dumps({
            'request': {'run_id': run.name, 'sequence': '999'},
        }), encoding='utf-8')

        json2 = waiting_for_json2(run)
        assert json2['next_action'] == 'CREATE_JSON2'
        assert json2['stage_spec']['path'] == 'ver3/spec/json2-quality.md'
        assert len(json2['stage_spec']['sha256']) == 64
        assert json2['research_input_policy'].startswith('Use only this RUN')
        assert not any('runs/*' in path for path in json2['required_inputs'])

        image = waiting_for_cover(run, 'ISSUED_CURRENT')
        assert image['next_action'] == 'GENERATE_QA_AND_UPLOAD_COVER'
        assert image['details']['cover_ticket_status'] == 'ISSUED_CURRENT'
        assert image['stage_spec']['path'] == 'ver3/spec/image-handoff.md'

        email = ready_for_email(run, {
            'status': 'PARTIAL',
            'page_url': 'https://www.notion.so/test',
            'missing_audio_refs': ['Gen.28.4'],
        })
        assert email['next_action'] == 'SEND_PARTIAL_EMAIL_KEEP_STATE'
        assert email['details']['missing_audio_refs'] == ['Gen.28.4']
        assert email['stage_spec']['path'] == 'ver3/spec/email-delivery.md'

        delivery = {
            'status': 'PASS', 'run_id': run.name,
            'page_id': 'page-999',
            'page_url': 'https://www.notion.so/page-999',
            'cover': {'status': 'PASS'},
            'missing_audio_refs': [],
            'missing_html_refs': [],
        }
        (run / 'delivery.json').write_text(
            json.dumps(delivery), encoding='utf-8')
        production = Path(directory) / 'production.json'
        production.write_text(json.dumps({
            'next_sequence': '999',
            'last_completed': {'sequence': '998', 'status': 'PASS'},
        }), encoding='utf-8')
        stale = inspect_completion(run, production)
        assert stale['complete'] is False
        assert 'COMPLETION_RECEIPT_MISSING' in stale['reasons']
        assert 'PRODUCTION_NEXT_SEQUENCE_NOT_ADVANCED' in stale['reasons']
        pending = ready_for_email(run, delivery, stale)
        assert pending['next_action'] == 'SEND_SUCCESS_EMAIL_AND_ADVANCE_STATE'
        assert pending['expected_outputs'] == [
            f'{run.as_posix()}/completion.json',
            'ver3/state/production.json',
        ]

        completion = {
            'schema_version': '1.0-work-completion',
            'run_id': run.name,
            'sequence': '999',
            'delivery_status': 'PASS',
            'page_id': delivery['page_id'],
            'page_url': delivery['page_url'],
            'gmail': {
                'message_id': 'gmail-999',
                'subject': '999｜test',
                'sent_verified': True,
            },
            'completed_at': '2026-09-12T00:00:00Z',
        }
        (run / 'completion.json').write_text(
            json.dumps(completion), encoding='utf-8')
        production.write_text(json.dumps({
            'next_sequence': '1000',
            'last_completed': {
                'sequence': '999',
                'run_id': run.name,
                'status': 'PASS',
                'page_id': delivery['page_id'],
                'page_url': delivery['page_url'],
                'gmail_message_id': 'gmail-999',
                'gmail_sent_verified': True,
            },
        }), encoding='utf-8')
        complete = inspect_completion(run, production)
        assert complete['complete'] is True, complete
        done = no_action(run)
        assert done['next_action'] == 'NONE'
        assert done['required_inputs'][-2:] == [
            f'{run.as_posix()}/completion.json',
            'ver3/state/production.json',
        ]

        blocked = pipeline_failure(run, RuntimeError('fixture failure'), 'JSON2')
        assert blocked['status'] == 'BLOCKED'
        assert blocked['details']['error_type'] == 'RuntimeError'
        assert blocked['details']['last_successful_stage'] == 'JSON2'
        saved = json.loads((run / 'handoff.json').read_text(encoding='utf-8'))
        assert saved == blocked

    print('PASS: stage-scoped Work handoff contract')


if __name__ == '__main__':
    main()
