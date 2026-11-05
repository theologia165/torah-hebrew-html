#!/usr/bin/env python3
"""Offline integration tests for bounded boundary QA and fail-open delivery.

Synthetic tones test orchestration/byte binding, never Hebrew listening quality.
The API is mocked; these tests cannot spend credits or write Notion/Gmail.
"""
import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audio.boundary import edge_jobs, identity, observe, policy, report
from audio.boundary_flow import delivery_summary, process
from audio.manifest import digest, write_json_atomic
from audio.processing import make_audio_record, split_mp3
from audio.quality import file_sha, read
from completion_gate import inspect_completion


class Response:
    status_code = 200
    ok = True
    headers = {'x-request-id': 'test-request'}

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class BoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cls.source = Path(cls.fixture.name) / 'source.mp3'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=30', '-c:a', 'libmp3lame',
                        str(cls.source)], check=True)
        cls.seed = Path(cls.fixture.name) / 'seed'
        audio = cls.seed / 'audio'
        audio.mkdir(parents=True)
        data = {'sequence': '999', 'passage': {'book': 'Genesis', 'chapter': 1,
                'start_verse': 1, 'end_verse': 3}, 'verses': []}
        records = []
        for n, surface in enumerate(('אב', 'גד', 'הו'), 1):
            verse = {'chapter': 1, 'verse': n, 'words': [{'id': n, 'surface': surface}]}
            data['verses'].append(verse)
            r1, r2 = audio / f'999_{n}_r1.mp3', audio / f'999_{n}_r2.mp3'
            split_mp3(cls.source, (n - 1) * 10, n * 10, r1)
            record = make_audio_record(f'Gen.1.{n}', verse, r1, r2, 'POCKETTORAH')
            record.update(boundary_start=(n - 1) * 10, boundary_end=n * 10,
                          boundary_scope='POCKETTORAH_CONTINUOUS')
            records.append(record)
        manifest = {'status': 'PASS', 'passage': data['passage'],
                    'expected_refs': ['1:1', '1:2', '1:3'], 'source': {},
                    'qa': {'MAPPING_CONFIRMED': True, 'SIGNAL_CHECKED': True,
                           'MODEL_AUDIO_CHECKED': False, 'AUDIO_DELIVERY_COMPLETE': True},
                    'verses': records, 'failed_verses': []}
        write_json_atomic(cls.seed / 'audio-input.json', data)
        write_json_atomic(audio / 'audio_manifest.json', manifest)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name) / '999-20261105-r1'
        shutil.copytree(self.seed, self.run)
        self.audio = self.run / 'audio'
        self.settings = policy()
        self.environment = patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-test-key'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.fail_ids = set()
        self.post = patch('audio.boundary.requests.post', side_effect=self.reply).start()
        self.addCleanup(patch.stopall)

    def reply(self, *args, **kwargs):
        request = kwargs['json']
        descriptions = json.loads(request['messages'][0]['content'][0]['text'].rsplit('\n', 1)[-1])
        return Response({'usage': {'prompt_tokens': 800, 'prompt_tokens_details': {'audio_tokens': 600}, 'completion_tokens': 100},
                         'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({'clips': [
                             {'id': row['id'], 'status': 'FAIL' if row['id'] in self.fail_ids else 'PASS',
                              'heard': row['expected'], 'evidence': 'Synthetic observation for workflow testing'}
                             for row in descriptions]})}}]})

    def decide(self, action='DELIVER_CURRENT', **extra):
        desk = self.run / 'audio-boundary'
        value = read(desk / 'decision-template.json')
        value.update(action=action, reviewer='Offline Work fixture',
                     reviewed_at='2026-11-05T00:00:00Z', evidence='Test decision, not a listening claim')
        value.update(extra)
        write_json_atomic(desk / 'decision.json', value)

    def advance(self):
        return process(self.run, lambda *_: None)

    def test_all_edges_cache_and_byte_change_rechecks_only_changed_verse(self):
        first = report(self.run)
        self.assertEqual(len(first['observations']), 6)
        self.assertFalse(first['full_content_verified'])
        self.assertEqual(self.post.call_count, 1)
        report(self.run)
        self.assertEqual(self.post.call_count, 1)
        path = self.audio / read(self.audio / 'audio_manifest.json')['verses'][0]['r2']
        with path.open('ab') as stream:
            stream.write(b'byte-change')
        report(self.run)
        self.assertEqual(self.post.call_count, 2)
        descriptions = json.loads(self.post.call_args.kwargs['json']['messages'][0]['content'][0]['text'].rsplit('\n', 1)[-1])
        self.assertEqual({row['id'] for row in descriptions}, {'1:1/head', '1:1/tail'})

    def test_short_verse_is_sent_once_and_full_content_is_never_claimed(self):
        settings = dict(self.settings, clip_seconds=6)
        jobs = edge_jobs(self.run, self.audio, settings)
        self.assertEqual(len(jobs), 3)
        self.assertTrue(all(j['side'] == 'whole' for j in jobs))
        observe(self.run, jobs, settings)
        self.assertEqual(self.post.call_count, 1)

    def test_duplicate_clips_are_not_paid_twice(self):
        jobs = edge_jobs(self.run, self.audio, self.settings)
        duplicate = dict(jobs[0], id='duplicate-id')
        rows = observe(self.run, [jobs[0], duplicate], self.settings)
        self.assertEqual(rows[0]['cache_key'], rows[1]['cache_key'])
        self.assertEqual(len(read(self.run / 'audio-boundary/usage.json')['requests']), 1)
        sent = self.post.call_args.kwargs['json']['messages'][0]['content']
        self.assertEqual(sum(c['type'] == 'input_audio' for c in sent), 1)

    def test_budget_limits_are_durable_across_reruns(self):
        for key, limit in [('max_requests', 0), ('max_audio_seconds', .1), ('max_estimated_usd', .00001)]:
            with self.subTest(key=key):
                shutil.rmtree(self.run / 'audio-boundary', ignore_errors=True)
                settings = dict(self.settings, **{key: limit})
                jobs = edge_jobs(self.run, self.audio, settings)
                rows = observe(self.run, jobs, settings)
                self.assertTrue(all(r['observation']['status'] == 'UNCERTAIN' for r in rows))
                observe(self.run, jobs, self.settings)
                self.assertEqual(self.post.call_count, 0)

    def test_request_is_claimed_before_api_and_transport_errors_do_not_retry_or_leak(self):
        def fail(*args, **kwargs):
            ledger = read(self.run / 'audio-boundary/usage.json')
            self.assertEqual(ledger['requests'][0]['status'], 'RESERVED')
            raise RuntimeError('secret offline-test-key raw audio body')
        self.post.side_effect = fail
        self.assertFalse(self.advance())
        self.assertFalse(self.advance())
        self.assertEqual(self.post.call_count, 1)
        audit = (self.run / 'audio-boundary/usage.json').read_text()
        self.assertNotIn('offline-test-key', audit)
        self.assertNotIn('raw audio body', audit)
        self.decide()
        self.assertTrue(self.advance())
        summary = delivery_summary(self.run)
        self.assertTrue(summary['email_disclosure_required'])
        self.assertFalse(summary['full_content_verified'])

    def test_missing_key_never_blocks_delivery_after_work_disclosure_decision(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            self.assertFalse(self.advance())
        self.decide()
        self.assertTrue(self.advance())
        self.assertEqual(self.post.call_count, 0)
        self.assertEqual(delivery_summary(self.run)['status'], 'DELIVER_WITH_UNRESOLVED_BOUNDARIES')
        reasons = inspect_completion(self.run)['reasons']
        self.assertIn('BOUNDARY_UNRESOLVED_NOT_DISCLOSED', reasons)
        receipt_sha = file_sha(self.run / 'audio-boundary/finalization.json')
        write_json_atomic(self.run / 'completion.json', {'audio_boundary': {
            'finalization_sha256': receipt_sha, 'disclosed_in_email': True}})
        self.assertNotIn('BOUNDARY_UNRESOLVED_NOT_DISCLOSED', inspect_completion(self.run)['reasons'])

    def test_stale_work_decision_cannot_authorize_audio_and_completed_receipt_is_bound(self):
        self.advance()
        self.decide()
        path = self.audio / read(self.audio / 'audio_manifest.json')['verses'][0]['r2']
        with path.open('ab') as stream:
            stream.write(b'new-bytes')
        self.assertFalse(self.advance())
        self.decide()
        self.assertTrue(self.advance())
        calls = self.post.call_count
        self.assertTrue(self.advance())
        self.assertEqual(self.post.call_count, calls)
        with path.open('ab') as stream:
            stream.write(b'after-approval')
        with self.assertRaises(ValueError):
            delivery_summary(self.run)

    def test_candidate_changes_two_neighbors_keeps_others_and_requires_work_adoption(self):
        self.fail_ids = {'1:1/tail', '1:2/head'}
        before = identity(self.run, self.audio)
        self.assertFalse(self.advance())
        self.decide('REQUEST_REPAIR', cuts=[{'ref': '1:1', 'side': 'tail', 'seconds': 10.2}])
        self.fail_ids.clear()
        with patch('audio.boundary_flow.source_audio', return_value=self.source):
            self.assertFalse(self.advance())
        self.assertEqual(identity(self.run, self.audio), before)
        desk = self.run / 'audio-boundary'
        candidate = read(desk / 'candidate.json')
        self.assertEqual(set(candidate['changed_refs']), {'1:1', '1:2'})
        self.assertEqual(candidate['candidate']['audio_sha256']['1:3'], before['audio_sha256']['1:3'])
        self.assertTrue(read(desk / 'candidate-report.json')['adoptable'])
        self.assertEqual(self.post.call_count, 2)
        self.decide('ADOPT_CANDIDATE')
        self.assertTrue(self.advance())
        self.assertTrue(delivery_summary(self.run)['candidate_adopted'])
        self.assertEqual(self.post.call_count, 2)
        self.assertTrue((desk / 'before/audio_manifest.json').exists())

    def test_bad_candidate_retains_original_and_delivers_with_warning(self):
        self.fail_ids = {'1:1/tail'}
        before = identity(self.run, self.audio)
        self.advance()
        self.decide('REQUEST_REPAIR', cuts=[{'ref': '1:1', 'side': 'tail', 'seconds': 10.2}])
        with patch('audio.boundary_flow.source_audio', return_value=self.source):
            self.assertFalse(self.advance())
        self.decide('ADOPT_CANDIDATE')
        self.assertFalse(self.advance())
        self.decide()
        self.assertTrue(self.advance())
        self.assertEqual(identity(self.run, self.audio), before)
        self.assertFalse(delivery_summary(self.run)['candidate_adopted'])

    def test_changed_candidate_cannot_use_old_work_approval(self):
        self.fail_ids = {'1:1/tail'}
        before = identity(self.run, self.audio)
        self.advance()
        self.decide('REQUEST_REPAIR', cuts=[{'ref': '1:1', 'side': 'tail', 'seconds': 10.2}])
        self.fail_ids.clear()
        with patch('audio.boundary_flow.source_audio', return_value=self.source):
            self.advance()
        self.decide('ADOPT_CANDIDATE')
        candidate = self.run / 'audio-boundary/candidate/audio'
        path = candidate / read(candidate / 'audio_manifest.json')['verses'][0]['r2']
        with path.open('ab') as stream:
            stream.write(b'changed-after-work-review')
        calls = self.post.call_count
        self.assertFalse(self.advance())
        self.assertEqual(identity(self.run, self.audio), before)
        self.assertEqual(self.post.call_count, calls)
        self.decide()
        self.assertTrue(self.advance())

    def test_known_defect_is_disclosed_even_if_model_edges_pass(self):
        write_json_atomic(self.run / 'audio-quality.json', {'verses': [
            {'ref': '1:1', 'findings': ['KNOWN_BOUNDARY_DEFECT']} ]})
        self.advance()
        self.decide()
        self.assertTrue(self.advance())
        summary = delivery_summary(self.run)
        self.assertTrue(summary['email_disclosure_required'])
        self.assertEqual(summary['unresolved'][0]['reason'], 'KNOWN_BOUNDARY_DEFECT')

    def test_context_and_repair_limits_survive_repeated_requests(self):
        self.fail_ids = {'1:1/tail'}
        self.advance()
        self.decide('INSPECT_CONTEXT', edges=['1:1/tail'])
        with patch('audio.boundary_flow.source_audio', return_value=self.source):
            self.assertFalse(self.advance())
        calls = self.post.call_count
        self.decide('INSPECT_CONTEXT', edges=['1:1/tail'], evidence='Second context request')
        self.assertFalse(self.advance())
        self.assertEqual(calls, self.post.call_count)
        self.decide('REQUEST_REPAIR', cuts=[{'ref': '1:1', 'side': 'tail', 'seconds': 100}])
        self.assertFalse(self.advance())
        self.decide('REQUEST_REPAIR', cuts=[{'ref': '1:1', 'side': 'tail', 'seconds': 10.2}])
        with patch('audio.boundary_flow.source_audio') as source:
            self.assertFalse(self.advance())
            source.assert_not_called()
        self.decide()
        self.assertTrue(self.advance())

    def test_truncated_or_unstructured_model_output_never_passes(self):
        self.post.return_value = Response({'choices': [{'finish_reason': 'length', 'message': {'content': 'not-json'}}]})
        self.post.side_effect = None
        result = report(self.run)
        self.assertEqual(len(result['problem_edges']), 6)
        self.assertTrue(all(r['observation']['status'] == 'UNCERTAIN' for r in result['observations']))


if __name__ == '__main__':
    unittest.main()
