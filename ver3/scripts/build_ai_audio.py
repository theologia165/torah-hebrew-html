#!/usr/bin/env python3
"""Legacy-compatible exports for the modular audio resolver.

New production code invokes ``resolve_audio.py``.  These exports keep the
already completed 041 repair and external maintenance scripts reproducible.
"""
from audio.manifest import digest, update_manifest
from audio.policy import (
    choose_fallback,
    classify_failure,
    load_policy,
    validate_open_bible_entry,
    validate_policy,
)
from audio.processing import (
    TARGET_WPS,
    atempo_chain,
    duration,
    make_audio_record,
    mean_volume_db,
)
from audio.resolver import main, resolve
from audio.sources.open_bible import fetch_open_bible
from audio.sources.openai_tts import fetch_openai
from audio.text import full_ref, input_by_ref, spoken_text


__all__ = [
    'TARGET_WPS', 'atempo_chain', 'choose_fallback', 'classify_failure',
    'digest', 'duration', 'fetch_open_bible', 'fetch_openai', 'full_ref',
    'input_by_ref', 'load_policy', 'main', 'make_audio_record',
    'mean_volume_db', 'resolve', 'spoken_text', 'update_manifest',
    'validate_open_bible_entry', 'validate_policy',
]


if __name__ == '__main__':
    main()
