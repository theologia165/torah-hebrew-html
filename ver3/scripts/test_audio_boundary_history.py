#!/usr/bin/env python3
"""Offline checks: historical routing and completed-page state preservation."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from audio.manifest import write_json_atomic
from audio_boundary_history import changed_runs, execute, stable_page


class HistoryTest(unittest.TestCase):
    def test_expiring_cover_signature_is_not_an_asset_change(self):
        one = {'cover': {'type': 'file', 'file': {'url': 'https://files.example/asset-id/cover.jpg?signature=old', 'expiry_time': 'old'}}}
        two = {'cover': {'type': 'file', 'file': {'url': 'https://files.example/asset-id/cover.jpg?signature=new', 'expiry_time': 'new'}}}
        self.assertEqual(stable_page(one), stable_page(two))
        two['cover']['file']['url'] = 'https://files.example/other-asset/cover.jpg?signature=new'
        self.assertNotEqual(stable_page(one), stable_page(two))

    def test_only_explicit_history_inputs_select_old_runs(self):
        paths = '\n'.join([
            'ver3/runs/094-20261103-r1/audio-boundary/decision.json',
            'ver3/runs/094-20261103-r1/audio-boundary/history-request.json',
            'ver3/runs/098-20261107-r1/audio-boundary/decision.json',
            'ver3/request.json', 'ver3/runs/095-20261104-r1/audio-boundary/usage.json'])
        with patch('audio_boundary_history.subprocess.check_output', return_value=paths), \
             patch.object(Path, 'is_file', lambda p: '094-' in str(p)):
            self.assertEqual(changed_runs('a'*40, 'b'*40), ['094-20261103-r1'])
        with self.assertRaises(ValueError):
            changed_runs('HEAD~1', 'HEAD')

    def test_media_subprocess_cannot_consume_the_next_run(self):
        workflow = Path(__file__).resolve().parents[2] / '.github/workflows/asaichi-torah-ver3.yml'
        text = workflow.read_text()
        start = text.index('            mapfile -t historical_runs')
        end = text.index('\n          elif', start)
        loop = text[start:end]
        with tempfile.TemporaryDirectory() as tmp:
            targets = Path(tmp) / 'targets'
            targets.write_text('094-20261103-r1\n095-20261104-r1\n')
            loop = loop.replace('/tmp/torah-history-targets', str(targets))
            # A decoder that reads all stdin reproduces ffmpeg's loop hazard.
            script = 'python() { cat >/dev/null; printf "%s\\n" "$2"; };\n' + loop
            result = subprocess.check_output(['bash', '-c', script], text=True)
            self.assertEqual(result.splitlines(), ['ver3/runs/094-20261103-r1', 'ver3/runs/095-20261104-r1'])

    def test_review_handoff_never_replaces_completed_production_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path.cwd()
            try:
                os.chdir(tmp)
                run = Path('ver3/runs/094-20261103-r1')
                desk = run / 'audio-boundary'
                desk.mkdir(parents=True)
                request = {'operation': 'BOUNDED_HISTORICAL_BOUNDARY_REVIEW',
                           'run_id': run.name, 'page_id': 'existing-page', 'reason': 'User requested',
                           'repair_if_confirmed': True, 'before': {'run_id': run.name}}
                write_json_atomic(desk / 'history-request.json', request)
                write_json_atomic(run / 'completion.json', {'delivery_status': 'PASS',
                                  'page_id': 'existing-page', 'gmail': {'sent_verified': True}})
                for p in [run / 'handoff.json', run / 'delivery.json', Path('ver3/request.json'),
                          Path('ver3/state/production.json')]:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text('{"protected":true}\n')
                def fake_process(run, checkpoint):
                    (run / 'handoff.json').write_text('{"next_action":"REVIEW_AUDIO_BOUNDARIES"}\n')
                    checkpoint(run, 'test')
                    return False
                with patch('audio_boundary_history.identity', return_value=request['before']), \
                     patch('audio_boundary_history.process', side_effect=fake_process), \
                     patch('runner.commit_run'):
                    execute(run)
                self.assertEqual((run / 'handoff.json').read_text(), '{"protected":true}\n')
                self.assertIn('REVIEW_AUDIO_BOUNDARIES', (desk / 'history-handoff.json').read_text())
                self.assertFalse((desk / 'history-closed.json').exists())
                request['page_id'] = 'wrong-page'
                write_json_atomic(desk / 'history-request.json', request)
                with self.assertRaises(ValueError):
                    execute(run)
            finally:
                os.chdir(old)


if __name__ == '__main__':
    unittest.main()
