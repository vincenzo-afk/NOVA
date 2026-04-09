"""Text chunking helpers."""

from __future__ import annotations

import re


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n{2,}")


def _split_sentences(text: str) -> list[str]:
    chunks = []
    for item in _SENTENCE_SPLIT.split(text):
        sentence = item.strip()
        if sentence:
            chunks.append(sentence)
    return chunks


def _word_count(text: str) -> int:
    return len(text.split())


def chunk_text(text: str, size: int = 512, overlap: int = 64) -> list[str]:
    if overlap >= size:
        raise ValueError(f"overlap ({overlap}) must be less than size ({size})")
    if not text.strip():
        return []

    sentences = _split_sentences(text)
    if not sentences:
        return []

    out: list[str] = []
    current: list[str] = []
    current_word_buffer: list[str] = []
    current_words = 0

    for sentence in sentences:
        sent_words = _word_count(sentence)

        if sent_words > size:
            words = sentence.split()
            if current:
                out.append(" ".join(current).strip())
                current = []
                current_words = 0
            idx = 0
            while idx < len(words):
                piece = words[idx : idx + size]
                out.append(" ".join(piece).strip())
                if idx + size >= len(words):
                    break
                idx += max(1, size - overlap)
            continue

        if current_words + sent_words <= size:
            current.append(sentence)
            current_word_buffer.extend(sentence.split())
            current_words += sent_words
            continue

        out.append(" ".join(current).strip())

        tail_words = current_word_buffer[-overlap:] if overlap > 0 else []
        current = [" ".join(tail_words).strip()] if tail_words else []
        current = [c for c in current if c]
        current_word_buffer = list(tail_words)
        current_words = len(current_word_buffer)

        current.append(sentence)
        current_word_buffer.extend(sentence.split())
        current_words += sent_words

    if current:
        out.append(" ".join(current).strip())

    return [chunk for chunk in out if chunk]
