"""Work judges bounded observations; Actions stages/rechecks/adopts exact bytes.

This is the normal-production finishing check. The older strict full-content
repair desk remains available for explicitly requested historical repairs.
An unresolved boundary is disclosed and delivered, not a production deadlock.
"""
import hashlib
import math
import shutil
import tempfile
from pathlib import Path

from audio.boundary import expected_edges, identity, observe, policy, report
from audio.manifest import digest, write_json_atomic
from audio.processing import duration, make_audio_record, split_mp3
from audio.quality import file_sha, read
from audio.text import input_by_ref


def source_audio(manifest, directory):
    """Retrieve only the byte-pinned original through the existing adapter."""
    from audio.sources.pockettorah import BASE_RAW, get_bytes
    source = manifest['source']
    url = source['audio_url']
    if not url.startswith(BASE_RAW + '/data/audio/'):
        raise ValueError('Context source is not the pinned primary audio')
    data = get_bytes(url)
    if hashlib.sha256(data).hexdigest() != source['audio_sha256']:
        raise ValueError('Original source bytes changed')
    path = Path(directory) / 'source.mp3'
    path.write_bytes(data)
    return path


def context(run, ids):
    run = Path(run)
    settings = policy()
    current = read(run / 'audio-boundary/report.json')
    if not ids or len(ids) != len(set(ids)) or set(ids) - set(current['problem_edges']):
        raise ValueError('Context must target current unresolved edges')
    data = read(run / 'audio-input.json')
    manifest = read(run / 'audio/audio_manifest.json')
    rows = manifest['verses']
    jobs = []
    with tempfile.TemporaryDirectory(prefix='torah-boundary-context-') as tmp:
        path = source_audio(manifest, tmp)
        length = duration(path)
        expanded = [ref + '/' + side for edge in ids
                    for ref, original_side in [edge.split('/')]
                    for side in (('head', 'tail') if original_side == 'whole' else (original_side,))]
        for edge_id in expanded:
            ref, side = edge_id.split('/')
            index = next(i for i, v in enumerate(rows) if v['ref'] == ref)
            v = rows[index]
            if v.get('audio_origin', 'POCKETTORAH') != 'POCKETTORAH':
                raise ValueError('Continuous-source context cannot be used for fallback audio')
            cut = v['boundary_start' if side == 'head' else 'boundary_end']
            adjacent = index - 1 if side == 'head' else index + 1
            own = expected_edges(data, v, settings['edge_words'])
            other = expected_edges(data, rows[adjacent], settings['edge_words']) if 0 <= adjacent < len(rows) else {}
            start, end = max(0, cut - settings['context_seconds']), min(length, cut + settings['context_seconds'])
            jobs.append({
                'id': edge_id + '/context', 'ref': ref, 'side': 'context',
                'path': str(path), 'audio_sha256': file_sha(path),
                'start': round(start, 6), 'end': round(end, 6),
                'cut_seconds': cut - start, 'source_cut_seconds': cut,
                'expected': own[side],
                'other_edge': other.get('tail' if side == 'head' else 'head', ''),
                'expected_order': 'other_edge then expected' if side == 'head' else 'expected then other_edge',
            })
        observations = observe(run, jobs, settings)
    write_json_atomic(run / 'audio-boundary/context.json', {
        **identity(run, run / 'audio'), 'observations': observations,
        'note': 'suggested_cut_seconds is local to the excerpt; add start for original-source seconds. Work must judge it.',
    })


def build_candidate(run, cuts):
    """Change shared cuts, preserving every unaffected MP3 and cache identity."""
    run = Path(run)
    desk = run / 'audio-boundary'
    candidate = desk / 'candidate' / 'audio'
    if candidate.exists():
        raise ValueError('Only one candidate generation is permitted per RUN')
    if not isinstance(cuts, list) or not cuts:
        raise ValueError('Reviewed cuts are required')
    original = read(run / 'audio/audio_manifest.json')
    manifest = read(run / 'audio/audio_manifest.json')
    rows = manifest['verses']
    changes = {}
    boundaries = set()
    for cut in cuts:
        ref, side, seconds = cut['ref'], cut['side'], cut['seconds']
        problems = set(read(desk / 'report.json')['problem_edges'])
        if ref + '/' + side not in problems and ref + '/whole' not in problems:
            raise ValueError('Correction must target a currently unresolved edge')
        if side not in ('head', 'tail') or isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds):
            raise ValueError('Invalid reviewed cut')
        index = next(i for i, v in enumerate(rows) if v['ref'] == ref)
        if rows[index].get('audio_origin', 'POCKETTORAH') != 'POCKETTORAH':
            raise ValueError('Boundary correction requires original primary audio')
        boundary = index if side == 'head' else index + 1
        if boundary in boundaries:
            raise ValueError('Duplicate/shared cut specified twice')
        boundaries.add(boundary)
        old = rows[index]['boundary_start' if side == 'head' else 'boundary_end']
        if 0 < boundary < len(rows) and abs(rows[boundary - 1]['boundary_end'] - rows[boundary]['boundary_start']) > .001:
            raise ValueError('Cannot correct a shared cut across missing/discontinuous audio')
        if abs(seconds - old) > policy()['context_seconds']:
            raise ValueError('Correction exceeds the inspected context window')
        for affected, key in ((boundary - 1, 'boundary_end'), (boundary, 'boundary_start')):
            if 0 <= affected < len(rows):
                row = rows[affected]
                if row.get('audio_origin', 'POCKETTORAH') != 'POCKETTORAH':
                    raise ValueError('Cannot move shared boundary into standalone fallback')
                row[key] = seconds
                row[key + '_meta'] = {'candidate': old, 'refined': seconds, 'method': 'work_reviewed_boundary_candidate'}
                changes[row['ref']] = row
    data = read(run / 'audio-input.json')
    words = input_by_ref(data)
    with tempfile.TemporaryDirectory(prefix='torah-boundary-repair-') as tmp:
        source = source_audio(manifest, tmp)
        length = duration(source)
        if any(v['boundary_start'] < 0 or v['boundary_end'] > length + .001
               or v['boundary_end'] - v['boundary_start'] < .4 for v in rows):
            raise ValueError('Reviewed cuts create invalid verse lengths')
        shutil.copytree(run / 'audio', candidate)
        for ref, row in changes.items():
            tag = digest({'cuts': cuts, 'ref': ref})[:12]
            stem = f"{data['sequence']}_{row['chapter']}_{row['verse']}_bqa_{tag}"
            r1, r2 = candidate / (stem + '_r1.mp3'), candidate / (stem + '_r2.mp3')
            split_mp3(source, row['boundary_start'], row['boundary_end'], r1)
            osis = f"{data['passage']['book']}.{row['chapter']}.{row['verse']}"
            record = make_audio_record(osis, words[osis], r1, r2, 'POCKETTORAH')
            record.update({k: row[k] for k in ('boundary_start', 'boundary_end', 'boundary_start_meta', 'boundary_end_meta') if k in row})
            record['boundary_scope'] = 'POCKETTORAH_CONTINUOUS'
            row.update(record)
    write_json_atomic(candidate / 'audio_manifest.json', manifest)
    write_json_atomic(desk / 'candidate.json', {
        'before': identity(run, run / 'audio'), 'cuts': cuts,
        'changed_refs': list(changes), 'original_manifest_sha256': digest(original),
        'candidate': identity(run, candidate),
    })
    return candidate


def candidate_check(run):
    from audio_quality import inspect_audio
    run = Path(run)
    desk = run / 'audio-boundary'
    candidate = desk / 'candidate/audio'
    machine = inspect_audio(run, candidate, output=desk / 'candidate-machine.json')
    if machine['machine_status'] != 'PASS' or machine['blocking_refs']:
        raise ValueError('Candidate failed independent machine or known-defect inspection')
    result = report(run, candidate, filename='candidate-report.json')
    changed = read(desk / 'candidate.json')['changed_refs']
    result['changed_refs'] = changed
    result['adoptable'] = all(r['observation']['status'] == 'PASS'
                              for r in result['observations'] if r['ref'] in changed)
    write_json_atomic(desk / 'candidate-report.json', result)
    return result


def finish(run, state, decision, adopted=False):
    run = Path(run)
    desk = run / 'audio-boundary'
    current = report(run)
    unresolved = [{
        'edge': r['id'], 'status': 'FAIL' if r['known_findings'] else r['observation']['status'],
        'reason': ','.join(r['known_findings']) if r['known_findings'] else r['observation']['evidence'],
    } for r in current['observations'] if r['observation']['status'] != 'PASS' or r['known_findings']]
    receipt = {
        'schema_version': '1.0-boundary-finalization', **identity(run, run / 'audio'),
        'status': 'BOUNDARY_PASS' if current['observations'] and not unresolved else 'DELIVER_WITH_UNRESOLVED_BOUNDARIES',
        'scope': current['scope'], 'full_content_verified': False,
        'delivery_allowed': True, 'candidate_adopted': adopted,
        'repair_attempted': state['repair_rounds'] > 0,
        'unresolved': unresolved, 'missing_audio_refs': current['missing_audio_refs'],
        'workflow_notes': state.get('notes', []),
        'reviewer': decision['reviewer'], 'reviewed_at': decision['reviewed_at'],
        'evidence': decision['evidence'], 'decision_sha256': digest(decision),
        'usage_sha256': file_sha(desk / 'usage.json'),
        'report_sha256': file_sha(desk / 'report.json'),
        'email_disclosure_required': bool(unresolved or state.get('notes')),
    }
    write_json_atomic(desk / 'finalization.json', receipt)
    return True


def waiting(run, state):
    from handoff import write_handoff
    desk = Path(run) / 'audio-boundary'
    report_path = desk / ('candidate-report.json' if state['phase'] == 'CANDIDATE' else 'report.json')
    inputs = [report_path, desk / 'usage.json', desk / 'state.json']
    inputs += [p for p in (desk / 'context.json', desk / 'candidate.json') if p.exists()]
    result = read(report_path)
    template = {
        'schema_version': '1.0-work-boundary-decision', 'run_id': Path(run).name,
        'report_sha256': file_sha(report_path),
        'action': 'DELIVER_CURRENT', 'reviewer': '', 'reviewed_at': '', 'evidence': '',
        'note': 'Work must judge observations. A template is not an approval. Other actions: INSPECT_CONTEXT, REQUEST_REPAIR, ADOPT_CANDIDATE.',
    }
    write_json_atomic(desk / 'decision-template.json', template)
    write_handoff(run, phase='AUDIO_BOUNDARY', status='WAITING_FOR_WORK',
                  next_action='REVIEW_AUDIO_BOUNDARIES', stage_spec='ver3/spec/audio-boundary.md',
                  required_inputs=inputs + [desk / 'decision-template.json'],
                  expected_outputs=[desk / 'decision.json'],
                  details={'phase': state['phase'], 'problem_edges': result['problem_edges'],
                           'delivery_policy': 'Unresolved audio is delivered with email disclosure; no PASS fabrication.'})


def process(run, commit_run):
    """Return true only when Work has resolved the handoff, including fail-open."""
    run = Path(run)
    desk = run / 'audio-boundary'
    desk.mkdir(parents=True, exist_ok=True)
    if resume_adoption(run):
        return True
    receipt = read(desk / 'finalization.json')
    if receipt and all(receipt.get(k) == v for k, v in identity(run, run / 'audio').items()):
        return True
    state_path = desk / 'state.json'
    state = read(state_path, {'run_id': run.name, 'phase': 'INITIAL',
                             'context_rounds': 0, 'repair_rounds': 0,
                             'handled_decisions': [], 'notes': []})
    if state['run_id'] != run.name:
        raise ValueError('Boundary flow RUN mismatch')
    if state['phase'] == 'INITIAL':
        report(run)
        state['phase'] = 'REVIEW'
    active_report = desk / ('candidate-report.json' if state['phase'] == 'CANDIDATE' else 'report.json')
    # Re-bind the normal report after an external audio/input change; old
    # decisions cannot authorize new bytes. The same per-RUN budget persists.
    if state['phase'] != 'CANDIDATE' and any(read(active_report).get(k) != v for k, v in identity(run, run / 'audio').items()):
        report(run)
    decision = read(desk / 'decision.json')
    if decision and digest(decision) not in state['handled_decisions']:
        if (decision.get('schema_version') != '1.0-work-boundary-decision'
                or decision.get('run_id') != run.name
                or decision.get('report_sha256') != file_sha(active_report)
                or not all(isinstance(decision.get(k), str) and decision[k].strip()
                           for k in ('reviewer', 'reviewed_at', 'evidence'))):
            state['notes'].append('STALE_OR_INCOMPLETE_WORK_DECISION: review the current template')
        else:
            action = decision.get('action')
            if action == 'DELIVER_CURRENT':
                write_json_atomic(state_path, state)
                return finish(run, state, decision)
            elif action == 'ADOPT_CANDIDATE':
                candidate = desk / 'candidate/audio'
                info = read(desk / 'candidate.json', {})
                try:
                    if (state['phase'] != 'CANDIDATE'
                            or info.get('before') != identity(run, run / 'audio')
                            or info.get('candidate') != identity(run, candidate)):
                        raise ValueError('Candidate adoption input changed')
                    result = candidate_check(run)
                    if file_sha(active_report) != decision['report_sha256']:
                        raise ValueError('Candidate observations changed after Work decision')
                except Exception as error:
                    result = {'adoptable': False}
                    state['notes'].append('CANDIDATE_ADOPTION_FAILED:' + type(error).__name__)
                if not result['adoptable']:
                    state['notes'].append('CANDIDATE_NOT_CONFIRMED: original audio retained')
                else:
                    # Copy unique candidate filenames first, manifest last. Reruns
                    # recover against the adoption intent if interrupted.
                    intent = {'decision': decision, 'before': info['before'],
                              'candidate': identity(run, candidate)}
                    write_json_atomic(desk / 'adoption.json', intent)
                    if not (desk / 'before').exists():
                        shutil.copytree(run / 'audio', desk / 'before')
                    for verse in read(candidate / 'audio_manifest.json')['verses']:
                        for key in ('r1', 'r2'):
                            shutil.copyfile(candidate / verse[key], run / 'audio' / verse[key])
                    write_json_atomic(run / 'audio/audio_manifest.json', read(candidate / 'audio_manifest.json'))
                    write_json_atomic(state_path, state)
                    return finish(run, state, decision, adopted=True)
            elif action in ('INSPECT_CONTEXT', 'REQUEST_REPAIR'):
                key = 'context_rounds' if action == 'INSPECT_CONTEXT' else 'repair_rounds'
                limit = policy()['max_' + key]
                if state[key] >= limit or (action == 'INSPECT_CONTEXT' and state['phase'] == 'CANDIDATE'):
                    state['notes'].append(action + '_LIMIT: retain original audio or adopt a confirmed candidate')
                else:
                    state[key] += 1
                    # Durable claim: crashes cannot regenerate paid work/candidates.
                    write_json_atomic(state_path, state)
                    try:
                        if action == 'INSPECT_CONTEXT':
                            context(run, decision.get('edges', []))
                        else:
                            build_candidate(run, decision.get('cuts'))
                            candidate_check(run)
                            state['phase'] = 'CANDIDATE'
                    except Exception as error:
                        state['notes'].append(action + '_FAILED:' + type(error).__name__ + '; original audio retained')
            else:
                state['notes'].append('UNKNOWN_WORK_ACTION: retain original audio or use the documented action')
            state['handled_decisions'].append(digest(decision))
            write_json_atomic(desk / f'decision-{len(state["handled_decisions"])}.json', decision)
    state['notes'] = list(dict.fromkeys(state['notes']))[-20:]
    write_json_atomic(state_path, state)
    waiting(run, state)
    commit_run(run, 'Record bounded audio boundary observations for Work review')
    return False


def resume_adoption(run):
    """Complete a byte-bound, Work-authorized interrupted adoption before waiting."""
    run = Path(run)
    desk = run / 'audio-boundary'
    intent = read(desk / 'adoption.json')
    if not intent or (desk / 'finalization.json').exists():
        return False
    if identity(run, run / 'audio') == intent['candidate']:
        return finish(run, read(desk / 'state.json'), intent['decision'], adopted=True)
    return False


def delivery_summary(run):
    desk = Path(run) / 'audio-boundary'
    receipt = read(desk / 'finalization.json')
    if not receipt or not receipt.get('delivery_allowed'):
        raise ValueError('Work boundary decision is required before normal delivery')
    if any(receipt.get(k) != v for k, v in identity(run, Path(run) / 'audio').items()):
        raise ValueError('Selected audio changed after Work boundary decision')
    return {
        'status': receipt['status'], 'scope': receipt['scope'],
        'full_content_verified': False, 'candidate_adopted': receipt['candidate_adopted'],
        'repair_attempted': receipt['repair_attempted'], 'unresolved': receipt['unresolved'],
        'workflow_notes': receipt['workflow_notes'],
        'email_disclosure_required': receipt['email_disclosure_required'],
        'finalization_sha256': file_sha(desk / 'finalization.json'),
    }
