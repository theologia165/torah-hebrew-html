"""Small, deterministic Work handoffs emitted by GitHub Actions."""
import hashlib
import json
from pathlib import Path


VER3_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = VER3_ROOT.parent
SCHEMA_VERSION = '1.0-work-handoff'


def _repo_path(path):
    path = Path(path)
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _spec(path):
    full_path = REPO_ROOT / path
    return {
        'path': path,
        'sha256': hashlib.sha256(full_path.read_bytes()).hexdigest(),
    }


def _identity(run):
    request = {}
    json1 = Path(run) / 'json1.json'
    if json1.exists():
        request = json.loads(json1.read_text(encoding='utf-8')).get('request', {})
    return {
        'run_id': request.get('run_id', Path(run).name),
        'sequence': request.get('sequence'),
    }


def write_handoff(run, *, phase, status, next_action, stage_spec,
                  required_inputs=(), expected_outputs=(), details=None):
    """Write one compact state transition without timestamps or secrets."""
    run = Path(run)
    payload = {
        'schema_version': SCHEMA_VERSION,
        **_identity(run),
        'phase': phase,
        'status': status,
        'next_action': next_action,
        'stage_spec': _spec(stage_spec),
        'required_inputs': [_repo_path(path) for path in required_inputs],
        'expected_outputs': [_repo_path(path) for path in expected_outputs],
        'research_input_policy': (
            'Use only this RUN json1.1 for research; never read an older RUN '
            'json2/json3, Notion page, image, or email as research input.'),
    }
    if details:
        payload['details'] = details
    path = run / 'handoff.json'
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    temporary.replace(path)
    return payload


def waiting_for_json2(run):
    run = Path(run)
    return write_handoff(
        run,
        phase='JSON2',
        status='WAITING_FOR_WORK',
        next_action='CREATE_JSON2',
        stage_spec='ver3/spec/json2-quality.md',
        required_inputs=(run / 'json1.1.json',),
        expected_outputs=(run / 'json2.json',),
        details={'quality_gate': 'WORK_JSON2_QUALITY=PASS_BEFORE_COMMIT'},
    )


def waiting_for_cover(run, ticket_status):
    run = Path(run)
    return write_handoff(
        run,
        phase='IMAGE',
        status='WAITING_FOR_WORK',
        next_action='GENERATE_QA_AND_UPLOAD_COVER',
        stage_spec='ver3/spec/image-handoff.md',
        required_inputs=(
            run / 'json2.json',
            'ver3/config/image-master.json',
            'ver3/config/parasha-image/index.json',
            run / 'cover-upload.json',
        ),
        expected_outputs=(run / 'cover-ready.json',),
        details={'cover_ticket_status': ticket_status},
    )


def ready_for_email(run, delivery, completion_gate=None):
    run = Path(run)
    status = delivery.get('status', 'UNKNOWN')
    return write_handoff(
        run,
        phase='EMAIL_AND_STATE',
        status='WAITING_FOR_WORK',
        next_action=(
            'SEND_SUCCESS_EMAIL_AND_ADVANCE_STATE'
            if status == 'PASS' else 'SEND_PARTIAL_EMAIL_KEEP_STATE'),
        stage_spec='ver3/spec/email-delivery.md',
        required_inputs=(
            run / 'delivery.json',
            run / 'json2.json',
            run / 'cover-ready.json',
        ),
        expected_outputs=(
            (run / 'completion.json', 'ver3/state/production.json')
            if status == 'PASS' else (run / 'completion.md',)
        ),
        details={
            'delivery_status': status,
            'page_url': delivery.get('page_url'),
            'missing_audio_refs': delivery.get('missing_audio_refs', []),
            'missing_html_refs': delivery.get('missing_html_refs', []),
            'cover_status': delivery.get('cover', {}).get('status'),
            'completion_gate_reasons': (
                (completion_gate or {}).get('reasons', [])),
        },
    )


def no_action(run, status='PASS'):
    run = Path(run)
    return write_handoff(
        run,
        phase='COMPLETE',
        status=status,
        next_action='NONE',
        stage_spec='ver3/spec/work-entry.md',
        required_inputs=(
            run / 'delivery.json',
            run / 'completion.json',
            'ver3/state/production.json',
        ),
        details={
            'reason': (
                'Delivery, Gmail Sent receipt, and production advancement '
                'are all verified.'),
        },
    )


def pipeline_failure(run, error, last_successful_stage):
    run = Path(run)
    return write_handoff(
        run,
        phase='FAILURE_REPORT',
        status='BLOCKED',
        next_action='SEND_PARTIAL_EMAIL_KEEP_STATE',
        stage_spec='ver3/spec/failure-report.md',
        required_inputs=(run / 'delivery.json',),
        expected_outputs=(run / 'completion.md',),
        details={
            'failed_operation': 'GITHUB_ACTIONS_PIPELINE',
            'error_type': type(error).__name__,
            'error_message': str(error)[-2000:],
            'last_successful_stage': last_successful_stage,
        },
    )
