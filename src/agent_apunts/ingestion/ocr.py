"""Read the text inside a page's images with Tesseract (D30 step 3, D39 proposed; off by default).

Slides keep code examples and diagrams as screenshots: 31% of Disseny de Software's content was not
readable as text (`images`, 2026-10-08). PyMuPDF already bundles MuPDF's Tesseract engine, so no
extra Python package is needed: each large image region is rendered at `dpi` and OCR'd with the
installed language files (tessdata). Small images (logos, icons) are skipped.

The OCR text is kept apart from the page's real text (ExtractedPage.ocr_text) and labelled in the
chunk, so it can be measured (eval with `code-image` questions, before/after) and switched off.
"""

from dataclasses import dataclass
from pathlib import Path

import pymupdf

# ISO 639-1 (settings.languages) -> Tesseract language file names.
_TESSERACT = {"ca": "cat", "es": "spa", "en": "eng", "fr": "fra", "de": "deu", "it": "ita"}


@dataclass(frozen=True)
class OcrOptions:
    language: str  # Tesseract form, e.g. "cat+spa+eng"
    dpi: int
    min_image_share: float  # skip images smaller than this share of the page (logos, icons)
    tessdata: str | None = None  # folder with <lang>.traineddata; None: let PyMuPDF find it


def tesseract_language(languages: list[str]) -> str:
    return "+".join(_TESSERACT.get(code, code) for code in languages)


def find_tessdata() -> Path | None:
    """Tesseract's language folder, as PyMuPDF finds it (TESSDATA_PREFIX or the installation)."""
    try:
        found = pymupdf.get_tessdata()
    except (RuntimeError, OSError):
        return None
    return Path(found) if found and Path(found).is_dir() else None


def missing_languages(language: str, tessdata: Path | None) -> list[str]:
    """Language files OCR needs that aren't installed (empty = ready)."""
    needed = language.split("+")
    if tessdata is None:
        return needed
    return [lang for lang in needed if not (tessdata / f"{lang}.traineddata").is_file()]


def self_test(language: str, tessdata: Path | None) -> str | None:
    """OCR a tiny blank image once: None if Tesseract loads every language, else the reason.
    Language files that exist but are broken (an interrupted download, an HTML error page saved
    as .traineddata) would otherwise fail every page of every document."""
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 32, 32), False)
    pixmap.clear_with(255)
    try:
        pixmap.pdfocr_tobytes(language=language, tessdata=str(tessdata) if tessdata else None)
    except Exception as e:  # noqa: BLE001 (MuPDF raises its own error types)
        return f"Tesseract could not load {language!r} ({e}); re-download the language files"
    return None


def _lines(words: list[tuple]) -> str:
    """OCR words -> text lines. Tesseract's PDF layer splits a line into many spans; words whose
    vertical centres are within half a word height of the line's belong to the same line."""
    rows: list[list[tuple]] = []
    for word in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        centre, height = (word[1] + word[3]) / 2, word[3] - word[1]
        if rows:
            last = rows[-1]
            last_centre = sum((w[1] + w[3]) / 2 for w in last) / len(last)
            if abs(centre - last_centre) <= height / 2:
                last.append(word)
                continue
        rows.append([word])
    return "\n".join(" ".join(w[4] for w in sorted(row, key=lambda w: w[0])) for row in rows)


def image_text(page: pymupdf.Page, options: OcrOptions) -> str:
    """Text read from the page's large images, top to bottom, one block per image."""
    page_area = abs(page.rect)
    if page.rotation:  # image boxes are in unrotated coordinates: OCR the whole page instead
        boxes = [page.rect] if page.get_images() else []
    else:
        boxes = [
            pymupdf.Rect(info["bbox"]) & page.rect
            for info in page.get_image_info()
            if abs(pymupdf.Rect(info["bbox"]) & page.rect) >= options.min_image_share * page_area
        ]
    blocks = []
    for box in sorted(boxes, key=lambda r: (r.y0, r.x0)):
        if box.is_empty:
            continue
        pixmap = page.get_pixmap(clip=box, dpi=options.dpi, alpha=False)
        ocr_pdf = pymupdf.open(
            "pdf", pixmap.pdfocr_tobytes(language=options.language, tessdata=options.tessdata)
        )
        with ocr_pdf:
            text = _lines(ocr_pdf[0].get_text("words"))
        # Keep lines with at least two letters: OCR of a diagram yields stray symbols.
        kept = [line for line in text.splitlines() if sum(c.isalpha() for c in line) >= 2]
        if kept:
            blocks.append("\n".join(kept))
    return "\n\n".join(blocks)
