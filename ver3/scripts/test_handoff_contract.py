#!/usr/bin/env python3
"""Fast contract test for small, stage-scoped Work handoffs."""
import json
import tempfile
from pathlib import Path

from handoff import (pipeline_failure, ready_for_email, waiting_for_cover,
                     waiting_for_json2)


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

        blocked = pipeline_failure(run, RuntimeError('fixture failure'), 'JSON2')
        assert blocked['status'] == 'BLOCKED'
        assert blocked['details']['error_type'] == 'RuntimeError'
        assert blocked['details']['last_successful_stage'] == 'JSON2'
        saved = json.loads((run / 'handoff.json').read_text(encoding='utf-8'))
        assert saved == blocked

    print('PASS: stage-scoped Work handoff contract')


if __name__ == '__main__':
    main()

