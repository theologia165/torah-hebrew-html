#!/usr/bin/env python3
"""One operator entry point for the audio quality desk."""
import argparse
import subprocess
import sys
from pathlib import Path

from audio.quality import cancel_repair, inspect, request_repair


def inspect_audio(run, audio_dir=None, review_path=None, output=None):
    audio_dir = Path(audio_dir) if audio_dir else Path(run) / 'audio'
    result = subprocess.run([
        sys.executable, str(Path(__file__).with_name('verify_audio.py')),
        str(audio_dir),
    ], text=True, capture_output=True)
    report = inspect(
        run, audio_dir, review_path,
        machine_status='PASS' if result.returncode == 0 else 'FAIL',
        machine_output=result.stdout + result.stderr, output=output)
    print(f"AUDIO_QUALITY={report['status']} MACHINE={report['machine_status']} "
          f"CONTENT={report['content_status']} next={report['next_action']}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('inspect', 'check'):
        command = commands.add_parser(name)
        command.add_argument('run', type=Path)
        command.add_argument('--audio-dir', type=Path)
        command.add_argument('--review', type=Path)
        command.add_argument('--output', type=Path)
    command = commands.add_parser('request-repair')
    command.add_argument('run', type=Path)
    command.add_argument('--repair-id', required=True)
    command.add_argument('--reason', required=True)
    command.add_argument('--incident', action='append', required=True)
    command = commands.add_parser('repair')
    command.add_argument('run', type=Path)
    command = commands.add_parser('cancel-repair')
    command.add_argument('run', type=Path)
    command.add_argument('--reason', required=True)
    args = parser.parse_args()
    if args.command == 'cancel-repair':
        cancel_repair(args.run, args.reason)
        print('REPAIR_CANCELLED_WITH_EVIDENCE: not a successful repair')
        return
    if args.command == 'request-repair':
        request_repair(args.run, args.repair_id, args.reason, args.incident)
        print('REPAIR_REQUEST_RECORDED: commit request and run Ver.3 Actions')
        return
    if args.command == 'repair':
        from audio.repair import execute, pending
        from runner import commit_run
        if pending(args.run):
            execute(args.run, commit_run)
        else:
            print('NO_PENDING_AUDIO_REPAIR')
        return
    report = inspect_audio(args.run, args.audio_dir, args.review, args.output)
    # inspect is diagnostic; check is the strict publishing gate for repairs.
    if args.command == 'check' and report['status'] != 'PASS':
        raise SystemExit(1)
    if report['machine_status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
