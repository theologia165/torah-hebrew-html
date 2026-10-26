#!/usr/bin/env python3
"""Offline regressions for false PASS, known defects and staged repairs."""
import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audio.manifest import digest, write_json_atomic
from audio.processing import make_audio_record
from audio.quality import (CHECKS, cancel_repair, inspect, quarantine, read,
                           request_repair)
from audio.repair import execute, pending
from audio_quality import inspect_audio


class AudioQualityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cls.tone = Path(cls.fixture.name) / 'tone.mp3'
        subprocess.run([
            'ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
            'sine=frequency=440:duration=3', '-c:a', 'libmp3lame', str(cls.tone),
        ], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name) / '999-20261026-r1'
        self.audio = self.run / 'audio'
        self.audio.mkdir(parents=True)
        self.data = {
            'sequence': '999',
            'passage': {'book': 'Genesis', 'chapter': 1,
                        'start_verse': 1, 'end_verse': 2},
            'verses': [
                {'chapter': 1, 'verse': 1, 'words': [
                    {'id': 1, 'surface': 'א'}, {'id': 2, 'surface': 'ב'}]},
                {'chapter': 1, 'verse': 2, 'words': [
                    {'id': 3, 'surface': 'ג'}, {'id': 4, 'surface': 'ד'}]},
            ],
        }
        write_json_atomic(self.run / 'audio-input.json', self.data)
        records = []
        for verse in self.data['verses']:
            ref = f"Gen.1.{verse['verse']}"
            r1 = self.audio / f"999_{verse['verse']}_r1.mp3"
            r2 = self.audio / f"999_{verse['verse']}_r2.mp3"
            shutil.copyfile(self.tone, r1)
            record = make_audio_record(ref, verse, r1, r2, 'POCKETTORAH')
            record['boundary_scope'] = 'STANDALONE_TEST'
            records.append(record)
        self.manifest = {
            'status': 'PASS', 'sequence': '999', 'passage': self.data['passage'],
            'source': {}, 'expected_refs': ['1:1', '1:2'],
            'qa': {'MAPPING_CONFIRMED': True, 'SIGNAL_CHECKED': True,
                   'MODEL_AUDIO_CHECKED': False, 'AUDIO_DELIVERY_COMPLETE': True,
                   'AUDIO_VERIFICATION_COMPLETE': False},
            'verses': records, 'failed_verses': [],
        }
        write_json_atomic(self.audio / 'audio_manifest.json', self.manifest)
        write_json_atomic(self.run / 'delivery.json', {
            'status': 'PASS', 'run_id': self.run.name, 'page_id': 'same-page',
            'page_url': 'https://www.notion.so/same-page',
        })

    def approve(self, report_path, review_path):
        template = report_path.with_name(report_path.stem + '-review-template.json')
        review = read(template)
        review.update(reviewer='Offline test fixture, not a real listening claim',
                      method='HUMAN_LISTENING', reviewed_at='2026-10-26T00:00:00Z')
        for verse in review['verses']:
            verse['checks'] = {key: 'PASS' for key in CHECKS}
            verse['evidence'] = 'Synthetic fixture approval for testing the gate only'
        write_json_atomic(review_path, review)
        return review

    def test_machine_pass_is_not_listening_pass(self):
        report = inspect_audio(self.run)
        self.assertEqual(report['machine_status'], 'PASS')
        self.assertEqual(report['status'], 'CONTENT_REVIEW_PENDING')
        self.assertFalse(report['AUDIO_VERIFICATION_COMPLETE'])
        self.assertEqual(report['pending_refs'], ['1:1', '1:2'])
        template = read(self.run / 'audio-quality-review-template.json')
        self.assertEqual(template['verses'][0]['checks']['last_word'], 'PENDING')

    def test_review_bound_to_run_input_manifest_and_both_audio_files(self):
        inspect_audio(self.run)
        review_path = self.run / 'audio-content-review.json'
        review = self.approve(self.run / 'audio-quality.json', review_path)
        self.assertEqual(inspect_audio(self.run)['status'], 'PASS')
        cases = []
        wrong = copy.deepcopy(review); wrong['run_id'] = 'other-run'; cases.append(wrong)
        wrong = copy.deepcopy(review); wrong['input_sha256'] = '0' * 64; cases.append(wrong)
        wrong = copy.deepcopy(review); wrong['manifest_sha256'] = '0' * 64; cases.append(wrong)
        wrong = copy.deepcopy(review); wrong['verses'][0]['r2_sha256'] = '0' * 64; cases.append(wrong)
        wrong = copy.deepcopy(review); wrong['verses'][0]['r1_sha256'] = '0' * 64; cases.append(wrong)
        wrong = copy.deepcopy(review); wrong['verses'].append(wrong['verses'][0]); cases.append(wrong)
        wrong = copy.deepcopy(review); wrong['verses'][0]['evidence'] = ''; cases.append(wrong)
        wrong = copy.deepcopy(review); wrong['verses'].pop(); cases.append(wrong)
        for invalid in cases:
            with self.subTest(invalid=invalid):
                write_json_atomic(review_path, invalid)
                self.assertNotEqual(inspect(self.run, machine_status='PASS')['status'], 'PASS')
        write_json_atomic(review_path, review)
        with (self.audio / '999_1_r2.mp3').open('ab') as stream:
            stream.write(b'changed-after-review')
        self.assertNotEqual(inspect(self.run, machine_status='PASS')['status'], 'PASS')

    def test_known_085_offset_quarantines_all_affected_audio(self):
        self.manifest['source'] = {
            'audio_base': 'Shemot-1',
            'pockettorah_commit': '8a23287221dd535966ee9914de9a03e71769a469',
        }
        write_json_atomic(self.audio / 'audio_manifest.json', self.manifest)
        report = inspect(self.run, machine_status='PASS')
        self.assertEqual(report['status'], 'BLOCKED')
        self.assertEqual(report['blocking_refs'], ['1:1', '1:2'])
        self.assertIn('AUDIO-085-LABEL-OFFSET', report['matched_incidents'])
        quarantine(self.run, report)
        quarantined = read(self.audio / 'audio_manifest.json')
        self.assertEqual(quarantined['status'], 'PARTIAL')
        self.assertEqual(quarantined['verses'], [])
        self.assertEqual(len(quarantined['failed_verses']), 2)
        self.assertEqual(quarantined['failed_verses'][0]['FAILURE_CODE'], 'AUDIO_QUALITY_QUARANTINED')
        self.assertTrue((self.audio / '999_1_r2.mp3').exists())
        self.assertTrue((self.run / 'audio-manifest-before-quality-quarantine.json').exists())
        after = inspect_audio(self.run)
        self.assertEqual(after['machine_status'], 'PASS')
        self.assertEqual(after['status'], 'BLOCKED')
        self.assertEqual(after['failed_refs'], ['1:1', '1:2'])

    def test_content_failure_does_not_suppress_healthy_verse(self):
        inspect_audio(self.run)
        path = self.run / 'audio-content-review.json'
        review = self.approve(self.run / 'audio-quality.json', path)
        review['verses'][0]['checks']['last_word'] = 'FAIL'
        write_json_atomic(path, review)
        report = inspect(self.run, machine_status='PASS')
        quarantine(self.run, report)
        self.assertEqual([v['ref'] for v in read(self.audio / 'audio_manifest.json')['verses']], ['1:2'])
        after = inspect_audio(self.run)
        self.assertEqual(after['machine_status'], 'PASS')
        self.assertEqual(after['failed_refs'], ['1:1'])

    def test_candidate_waits_before_publish_then_closes_on_same_page(self):
        request_repair(self.run, 'repair-1', 'fixture boundary defect', ['AUDIO-048-PRE-SILENCE'])
        desk = self.run / 'audio-repairs/repair-1'
        candidate_run = desk / self.run.name
        candidate_run.mkdir(parents=True)
        shutil.copytree(self.audio, candidate_run / 'audio')
        # Change bytes in the candidate without changing the old publication.
        candidate_file = candidate_run / 'audio/999_1_r2.mp3'
        with candidate_file.open('ab') as stream:
            stream.write(b'candidate')
        old_bytes = (self.audio / '999_1_r2.mp3').read_bytes()
        commits = []
        self.assertTrue(pending(self.run))
        self.assertFalse(execute(self.run, lambda run, message: commits.append(message)))
        self.assertEqual((self.audio / '999_1_r2.mp3').read_bytes(), old_bytes)
        self.assertEqual(read(self.run / 'handoff.json')['next_action'], 'REVIEW_AND_REPAIR_AUDIO')
        self.assertFalse((self.run / 'audio-repair.done.json').exists())
        self.approve(desk / 'audio-quality.json', desk / 'audio-content-review.json')

        def fake_deliver(args, **kwargs):
            self.assertIn('deliver.py', args[1])
            write_json_atomic(self.run / 'delivery.json', {
                'status': 'PASS', 'run_id': self.run.name, 'page_id': 'same-page',
                'operation': 'AUDIO_ONLY_REPLACE', 'AUDIO_IMPLEMENTED_COUNT': 2,
            })
            return subprocess.CompletedProcess(args, 0)

        # Mock only external delivery; inspection still uses real ffprobe.
        original_run = subprocess.run
        def route(args, **kwargs):
            return fake_deliver(args, **kwargs) if 'deliver.py' in str(args[1]) else original_run(args, **kwargs)
        with patch('audio.repair.subprocess.run', side_effect=route):
            self.assertTrue(execute(self.run, lambda run, message: commits.append(message)))
        self.assertFalse(pending(self.run))
        self.assertEqual((desk / 'before/999_1_r2.mp3').read_bytes(), old_bytes)
        self.assertEqual((self.audio / '999_1_r2.mp3').read_bytes(), candidate_file.read_bytes())
        receipt = read(desk / 'closed.json')
        self.assertEqual(receipt['page_id'], 'same-page')
        self.assertEqual(receipt['request_sha256'], digest(read(self.run / 'audio-repair.json')))
        self.assertEqual(receipt['status'], 'PASS')

    def test_cancel_is_not_close_and_new_id_preserves_history(self):
        request_repair(self.run, 'repair-1', 'fixture', ['AUDIO-085-LABEL-OFFSET'])
        with self.assertRaises(ValueError):
            request_repair(self.run, 'repair-2', 'fixture', ['AUDIO-085-LABEL-OFFSET'])
        cancel_repair(self.run, 'New source alignment implementation needed')
        self.assertFalse(pending(self.run))
        self.assertFalse(read(self.run / 'audio-repair.done.json')['audio_repair_completed'])
        request_repair(self.run, 'repair-2', 'fixture', ['AUDIO-085-LABEL-OFFSET'])
        self.assertTrue(pending(self.run))
        self.assertTrue((self.run / 'audio-repairs/repair-1/cancelled.json').exists())
        with self.assertRaises(ValueError):
            request_repair(self.run, '../bad', 'fixture', ['AUDIO-085-LABEL-OFFSET'])


if __name__ == '__main__':
    unittest.main()
