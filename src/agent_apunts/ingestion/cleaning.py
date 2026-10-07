"""Stage 3, CLEAN: remove per-document boilerplate before chunking (D27).

Boilerplate = text that repeats on most pages of a document (course name, logo text, footer, page
numbers). Left in, it makes every chunk of the document look alike to the embedding model.
Everything removed is reported, so a wrong removal (e.g. a formula) can be spotted and the
thresholds in settings.yaml tuned.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field

_NUMBER_ONLY = re.compile(r"\d{1,4}")
# A cover page is often unnumbered, so printed page numbers can lag the real page by 1 or 2.
_PAGE_NUMBER_OFFSETS = (0, 1, 2)
PAGE_NUMBER_LABEL = "(page number)"


def _key(line: str) -> str:
    """Comparison key: case and spacing ignored. Digits are NOT masked: masking them would make
    "Exercici 1", "Exercici 2"... look like one repeated line and delete real headings. The price:
    a footer like "Page 3 of 12" is not recognised as boilerplate (small noise, nothing lost)."""
    return " ".join(line.split()).lower()


def _can_be_boilerplate(line: str, max_chars: int) -> bool:
    # Must contain a letter: a number repeated on many pages ("0", "1" in exam tables) is data.
    # Numbers alone are only removed by the page-number rule below.
    stripped = line.strip()
    return 0 < len(stripped) <= max_chars and any(c.isalpha() for c in stripped)


def _is_page_number(line: str, page_number: int) -> bool:
    if not _NUMBER_ONLY.fullmatch(line):
        return False
    value = int(line)  # printed page numbers start at 1: a "0" is data
    return value >= 1 and any(value == page_number - offset for offset in _PAGE_NUMBER_OFFSETS)


@dataclass
class CleanedDocument:
    pages: list[str]  # cleaned text, same order and length as the input
    removed: Counter[str] = field(default_factory=Counter)  # removed line -> times removed


def clean_pages(
    texts: list[str], min_share: float, min_pages: int, max_chars: int
) -> CleanedDocument:
    """Clean the pages of ONE document (texts[0] is page 1). Pure: same input, same output."""
    page_keys = [
        {_key(line) for line in text.splitlines() if _can_be_boilerplate(line, max_chars)}
        for text in texts
    ]
    pages_with = Counter(key for keys in page_keys for key in keys)
    threshold = max(min_pages, math.ceil(min_share * len(texts)))
    boilerplate = {key for key, n in pages_with.items() if n >= threshold}

    result = CleanedDocument(pages=[])
    example: dict[str, str] = {}  # key -> first spelling seen (case/spacing variants count as one)
    for page_number, text in enumerate(texts, start=1):
        lines = text.splitlines()
        content = [i for i, line in enumerate(lines) if line.strip()]
        # Page numbers are only looked for in the first and last lines (header/footer), so a
        # number alone in a table cell in the middle of an exam page is never touched.
        edges = {content[0], content[-1]} if content else set()
        kept = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and (key := _key(stripped)) in boilerplate:
                result.removed[example.setdefault(key, " ".join(stripped.split()))] += 1
            elif i in edges and _is_page_number(stripped, page_number):
                result.removed[PAGE_NUMBER_LABEL] += 1
            else:
                kept.append(line)
        cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
        result.pages.append(cleaned)
    return result
