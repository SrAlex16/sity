"""Split text into TTS-ready fragments at sentence boundaries."""
from __future__ import annotations

import re

_SENTENCE_END = re.compile(r'(?<=[.!?;])\s+')


def split_by_sentences(text: str, max_chars: int) -> list[str]:
    """Split *text* into fragments of at most *max_chars* chars.

    Splits at sentence boundaries (.!?;) to avoid cutting mid-sentence.
    If a single sentence exceeds max_chars it is kept as-is.
    Empty fragments are dropped.
    """
    if len(text) <= max_chars:
        return [text] if text.strip() else []

    sentences = _SENTENCE_END.split(text.strip())
    fragments: list[str] = []
    current = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_chars:
            current += " " + sentence
        else:
            fragments.append(current)
            current = sentence

    if current:
        fragments.append(current)

    return fragments
