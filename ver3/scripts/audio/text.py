"""Build deterministic read-aloud text from the current RUN only."""
import re


def spoken_text(words):
    """Return qere-filtered token surfaces without cantillation.

    ``audio-input.json`` is already derived from the current RUN's JSON1/1.1
    and contains only tokens marked ``read_aloud``.  This function never
    accepts a free-form replacement text.
    """
    return ' '.join(
        re.sub(r'[\u0591-\u05af]', '', word['surface']) for word in words
    )


def full_ref(book, chapter, verse):
    return f'{book}.{int(chapter)}.{int(verse)}'


def input_by_ref(audio_input):
    book = audio_input['passage']['book']
    default_chapter = int(audio_input['passage']['chapter'])
    return {
        full_ref(book, verse.get('chapter', default_chapter), verse['verse']): verse
        for verse in audio_input['verses']
    }

