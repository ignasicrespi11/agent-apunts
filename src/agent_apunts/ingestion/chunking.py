"""Split a page's text into chunks: size decides (D26).

A page that fits in `max_words` stays whole (almost every slide). A longer page (dense A4 exam) is
cut at the most natural boundary available: paragraphs (blank lines), then lines, then words as a
last resort, and the pieces are packed into chunks of about `target_words`, never above `max_words`.
"""

import re


def count_words(text: str) -> int:
    return len(text.split())


def _units(text: str, max_words: int) -> list[str]:
    """Break text into pieces of at most max_words, using the largest natural boundary possible."""
    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if count_words(paragraph) <= max_words:
            units.append(paragraph)
            continue
        for line in paragraph.splitlines():
            line = line.strip()
            if not line:
                continue
            if count_words(line) <= max_words:
                units.append(line)
                continue
            words = line.split()  # a single huge line: plain word windows
            units += [" ".join(words[i : i + max_words]) for i in range(0, len(words), max_words)]
    return units


def split_text(text: str, max_words: int, target_words: int) -> list[str]:
    """Chunks for one page, in reading order. Joining them gives back all the page's words."""
    text = text.strip()
    if not text:
        return []
    if count_words(text) <= max_words:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for unit in _units(text, max_words):
        n = count_words(unit)
        if current and size + n > max_words:  # adding it would overflow: close the chunk first
            chunks.append("\n\n".join(current))
            current, size = [], 0
        current.append(unit)
        size += n
        if size >= target_words:  # big enough: close it here, at a natural boundary
            chunks.append("\n\n".join(current))
            current, size = [], 0
    if current:
        chunks.append("\n\n".join(current))
    # A tiny leftover (a closing line) is worth little on its own: glue it to the previous chunk
    # when they fit together.
    if len(chunks) >= 2:
        last, previous = count_words(chunks[-1]), count_words(chunks[-2])
        if last < target_words // 4 and previous + last <= max_words:
            chunks[-2:] = [chunks[-2] + "\n\n" + chunks[-1]]
    return chunks
