#!/usr/bin/env python3
"""Offline checks: historical routing and completed-page state preservation."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from audio.manifest import write_json_atomic
from audio_boundary_history import changed_runs, execute


class HistoryTest(unittest.TestCase):
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
