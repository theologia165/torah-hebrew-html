"""Verified exact-verse Open.Bible source adapter."""
import hashlib
from pathlib import Path

import requests


class OpenBibleFetchError(RuntimeError):
    """Transient retrieval failure that may proceed to OpenAI TTS."""


class OpenBibleIntegrityError(RuntimeError):
    """Hash mismatch; must remain PARTIAL rather than falling through."""


def fetch_open_bible(ref, entry, audio_dir, stem):
    try:
        response = requests.get(entry['url'], timeout=120)
    except requests.RequestException as error:
        raise OpenBibleFetchError(f'Open.Bible GET {ref}: {error}') from error
    if response.status_code >= 300:
        raise OpenBibleFetchError(
            f'Open.Bible GET {ref}: {response.status_code} {response.text[:300]}')
    actual_sha = hashlib.sha256(response.content).hexdigest()
    if actual_sha != entry['audio_sha256']:
        raise OpenBibleIntegrityError(
            f'Open.Bible audio_sha256 mismatch for {ref}')
    audio_dir = Path(audio_dir)
    r1 = audio_dir / f'{stem}_openbible_r1.mp3'
    r2 = audio_dir / f'{stem}_openbible_r2.mp3'
    r1.write_bytes(response.content)
    source_meta = {
        'source_url': entry['url'],
        'source_audio_sha256': actual_sha,
        'source_license': entry['license'],
        'source_attribution_label': entry['attribution_label'],
        'source_attribution_url': entry['attribution_url'],
        'source_verified_on': entry['verified_on'],
    }
    return r1, r2, source_meta

