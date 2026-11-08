#!/usr/bin/env python3
"""Explicit, bounded reinspection of completed pages; never replay production."""
import argparse
import json
import os
import re
import subprocess
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path

from audio.boundary import identity
from audio.boundary_flow import process
from audio.manifest import digest, write_json_atomic
from audio.quality import file_sha, read

RUN_ID = r'[0-9]{3}-[0-9]{8}-r[0-9]+'


def changed_runs(before, after):
    """Only an explicit history request/decision in this push selects old RUNs."""
    if not re.fullmatch(r'[0-9a-f]{40}', before) or not re.fullmatch(r'[0-9a-f]{40}', after):
        raise ValueError('Invalid push identity')
    paths = subprocess.check_output(['git', 'diff', '--name-only', before, after], text=True).splitlines()
    selected = set()
    for path in paths:
        match = re.fullmatch(r'ver3/runs/(' + RUN_ID + r')/audio-boundary/(history-request|decision)\.json', path)
        if match and Path('ver3/runs', match[1], 'audio-boundary/history-request.json').is_file():
            selected.add(match[1])
    return sorted(selected)


def stable_page(value):
    """Notion refreshes file signatures without changing the cover asset."""
    if isinstance(value, list):
        return [stable_page(v) for v in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key == 'expiry_time':
            continue
        if key == 'file' and isinstance(item, dict) and isinstance(item.get('url'), str):
            parts = urlsplit(item['url'])
            item = {**item, 'url': urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))}
        result[key] = stable_page(item)
    return result


def publish(run, request):
    """Read back all audio; patch only adopted, uniquely named changed audio."""
    import requests
    from deliver import children, non_audio_digest, plain
    from prepare_notion_html import request_json
    desk = run / 'audio-boundary'
    token = os.environ['NOTION_TOKEN']
    page_id = request['page_id']
    page = request_json('GET', '/pages/' + page_id, token)
    blocks = children(page_id, token)
    before = non_audio_digest(blocks)
    protected_page = stable_page({k: page.get(k) for k in ('properties', 'cover', 'icon', 'parent')})
    manifest = read(run / 'audio/audio_manifest.json')
    by_ref = {v['ref']: v for v in manifest['verses']}
    mapped, ref = {}, None
    for block in blocks:
        if block['type'] == 'heading_2':
            match = re.search(r'(\d+:\d+)$', plain(block))
            ref = match[1] if match else None
        elif block['type'] == 'audio':
            if ref not in by_ref or ref in mapped:
                raise ValueError('Existing Notion audio mapping differs')
            mapped[ref] = block
    if set(mapped) != set(by_ref):
        raise ValueError('Existing Notion audio coverage differs')
    receipt = read(desk / 'finalization.json')
    changed = read(desk / 'candidate.json', {}).get('changed_refs', []) if receipt['candidate_adopted'] else []
    snapshot = desk / 'notion-before.json'
    if not snapshot.exists():
        write_json_atomic(snapshot, {'page_id': page_id, 'non_audio_sha256': before,
                                    'page': protected_page, 'audio_blocks': list(mapped.values())})
    saved = read(snapshot)
    if saved['non_audio_sha256'] != before or stable_page(saved['page']) != protected_page:
        raise ValueError('Existing page changed during bounded repair')
    from runner import commit_run
    commit_run(run, 'Checkpoint existing Notion audio before bounded repair')
    verified = []
    for ref, verse in by_ref.items():
        url = ('https://raw.githubusercontent.com/theologia165/torah-hebrew-html/'
               'asaichi-torah-ver3/' + run.as_posix() + '/audio/' + verse['r2'])
        response = requests.get(url, timeout=45)
        response.raise_for_status()
        if response.content != (run / 'audio' / verse['r2']).read_bytes():
            raise ValueError('Public MP3 differs from selected bytes: ' + ref)
        actual = mapped[ref]['audio']
        current_url = actual.get(actual.get('type', ''), {}).get('url')
        if ref in changed and current_url != url:
            request_json('PATCH', '/blocks/' + mapped[ref]['id'], token,
                         json={'audio': {'type': 'external', 'external': {'url': url},
                                         'caption': actual.get('caption', [])}})
        elif current_url != url:
            raise ValueError('Unchanged Notion audio URL differs: ' + ref)
        verified.append({'ref': ref, 'block_id': mapped[ref]['id'], 'url': url,
                         'r2_sha256': file_sha(run / 'audio' / verse['r2'])})
    after = children(page_id, token)
    if non_audio_digest(after) != before:
        raise ValueError('Non-audio blocks changed')
    page_after = request_json('GET', '/pages/' + page_id, token)
    if stable_page({k: page_after.get(k) for k in protected_page}) != protected_page:
        raise ValueError('Page cover/title changed')
    after_by_id = {b['id']: b for b in after}
    for row in verified:
        actual = after_by_id[row['block_id']]['audio']
        if actual.get(actual.get('type', ''), {}).get('url') != row['url']:
            raise ValueError('Notion audio readback differs')
    write_json_atomic(desk / 'history-closed.json', {
        'schema_version': '1.0-historical-boundary-receipt', 'run_id': run.name,
        'request_sha256': digest(request), 'finalization_sha256': file_sha(desk / 'finalization.json'),
        'boundary_status': receipt['status'], 'full_content_verified': False,
        'page_id': page_id, 'changed_refs': changed, 'published_audio_changed': bool(changed),
        'non_audio_sha256': before, 'non_audio_unchanged': True,
        'notion_audio_readback': verified,
    })


def execute(run):
    from runner import commit_run
    run = Path(run)
    if not re.fullmatch(RUN_ID, run.name) or run.parent.as_posix() != 'ver3/runs':
        raise ValueError('Explicit existing RUN path required')
    desk = run / 'audio-boundary'
    request = read(desk / 'history-request.json', {})
    completion = read(run / 'completion.json', {})
    if (request.get('operation') != 'BOUNDED_HISTORICAL_BOUNDARY_REVIEW'
            or request.get('run_id') != run.name or not request.get('reason')
            or not request.get('repair_if_confirmed')
            or completion.get('delivery_status') != 'PASS'
            or completion.get('gmail', {}).get('sent_verified') is not True
            or request.get('page_id') != completion.get('page_id')):
        raise ValueError('Explicit completed-page review authorization required')
    closed = read(desk / 'history-closed.json', {})
    if closed.get('request_sha256') == digest(request):
        print('SKIP_CLOSED_HISTORICAL_BOUNDARY_REVIEW: ' + run.name)
        return
    adoption = read(desk / 'adoption.json', {})
    if request['before'] != identity(run, run / 'audio') and adoption.get('before') != request['before']:
        raise ValueError('Historical audio changed since explicit request')
    protected = {p: p.read_bytes() for p in [run / 'handoff.json', run / 'completion.json',
                 run / 'delivery.json', Path('ver3/request.json'), Path('ver3/state/production.json')]}
    handoff = run / 'handoff.json'
    def checkpoint(_run, message):
        if handoff.read_bytes() != protected[handoff]:
            (desk / 'history-handoff.json').write_bytes(handoff.read_bytes())
            handoff.write_bytes(protected[handoff])
        commit_run(run, message)
    try:
        complete = process(run, checkpoint)
        if complete:
            # Publish reviewed MP3 bytes before switching the existing Notion URLs.
            checkpoint(run, 'Record historical boundary decision and selected audio')
            publish(run, request)
    finally:
        if handoff.read_bytes() != protected[handoff]:
            (desk / 'history-handoff.json').write_bytes(handoff.read_bytes())
            handoff.write_bytes(protected[handoff])
        for path, content in protected.items():
            if path.read_bytes() != content:
                raise ValueError('Historical review changed protected production state: ' + str(path))
        commit_run(run, 'Record bounded historical audio review evidence')
    print(('HISTORICAL_BOUNDARY_CLOSED: ' if complete else 'WAITING_FOR_HISTORICAL_BOUNDARY_REVIEW: ') + run.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', nargs='?', type=Path)
    parser.add_argument('--changed-runs', nargs=2, metavar=('BEFORE', 'AFTER'))
    args = parser.parse_args()
    if args.changed_runs:
        for run_id in changed_runs(*args.changed_runs):
            print(run_id)
    elif args.run:
        execute(args.run)
    else:
        parser.error('Explicit RUN or push range required')


if __name__ == '__main__':
    main()
