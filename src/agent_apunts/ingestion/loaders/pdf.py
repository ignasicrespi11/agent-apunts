"""PDF loader with PyMuPDF (D15): per page text, title guess, image count and a PNG thumbnail."""

import re
import statistics
import unicodedata
from pathlib import Path

import numpy as np
import pymupdf

from agent_apunts.ingestion.loaders.base import RawPage

_MAX_TITLE_CHARS = 200
# A title must start in the top 30% of the page. Big text lower down is a callout, not a title
# (real case: slides_grasp.pdf p26, a big comment under a code screenshot).
_TITLE_TOP_FRACTION = 0.3


# Spacing accent marks (as LaTeX writes them into PDFs) -> the combining mark NFC can merge.
# Only letters that take each accent: vowels (LaTeX writes "í" with a dotless "ı"), and n/a/o for
# the tilde. Anything else ("´h") is not an accent, so it is left alone.
_COMBINING = {"\u00b4": "\u0301", "\u00a8": "\u0308", "\u02c6": "\u0302", "\u02dc": "\u0303"}
_SPACING_ACCENT = re.compile(r"([\u00b4\u00a8\u02c6])([aeiouAEIOU\u0131])|(\u02dc)([nNaAoO])")
# Catalan elision typed with the accent key instead of the apostrophe ("l´any", "d´aquest",
# "s´ha"): a one-letter word, then ´, then a vowel or h. But LaTeX writes "més" as "m´es" and
# "té" as "t´e", the same shape. A LaTeX page also has accents INSIDE words ("Soluci´o",
# "f´ısica"), a typed page never does: only pages without them read ´ as an apostrophe.
_ELISION = re.compile(r"(?<![^\W\d_])([ldsmntLDSMNT])\u00b4(?=[aeiouhAEIOUH\u00c0-\u00ff])")
_LATEX_ACCENT_IN_WORD = re.compile(r"[^\W\d_]{2}[\u00b4\u00a8\u02c6`][aeiouAEIOU\u0131]")


def _accent(m: re.Match) -> str:
    mark, letter = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    return letter.replace("\u0131", "i") + _COMBINING[mark]


def normalize_text(text: str) -> str:
    """Make extracted text consistent without changing its content.

    - NFC: some PDFs store "à" as "a" + combining accent; NFC turns it into the single character
      users type, so search and embeddings see the same string.
    - LaTeX-made PDFs often store the accent as a separate *spacing* character before the letter
      ("Soluci´o", "Pr`actica"): it is turned into the real letter ("Solució", "Pràctica"),
      otherwise "solució" never matches. Found on the real corpus (IS exams). On pages without
      LaTeX accents, the same key typed as a Catalan apostrophe ("l´any") becomes "l'any".
    - Strip trailing spaces per line and collapse 3+ newlines into one blank line.
    Removing boilerplate (logos, repeated footers) is NOT done here: that's the CLEAN stage (D11).
    """
    if not _LATEX_ACCENT_IN_WORD.search(text):
        text = _ELISION.sub(r"\1'", text)
    text = _SPACING_ACCENT.sub(_accent, text)
    # Grave accent: only between letters ("Pr`actica"), so code backticks are left alone.
    text = re.sub(r"(?<=[A-Za-z])`([aeiouAEIOU])", lambda m: m.group(1) + "\u0300", text)
    text = unicodedata.normalize("NFC", text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _in_title_area(span: dict, page: pymupdf.Page) -> bool:
    # Text coordinates are for the unrotated page; rotation_matrix maps them to what the user sees.
    top = (pymupdf.Rect(span["bbox"]) * page.rotation_matrix).y0
    return top < page.rect.height * _TITLE_TOP_FRACTION


def guess_title(page: pymupdf.Page) -> str | None:
    """Heuristic: the title is the largest text in the top 30% of the page, if its font is clearly
    larger than the body text (>= 15%). Pages in one font size get None instead of a random line:
    a wrong title is worse than none, because it goes into every chunk's header (D13).

    Known weak spots (check with `inspect`): decorative big text at the top (a huge "01"), titles
    that are images, headings in bold but the same size as the body (they get None).
    """
    spans = [
        span
        for block in page.get_text("dict", sort=True)["blocks"]
        for line in block.get("lines", [])  # image blocks have no "lines"
        for span in line["spans"]
        if span["text"].strip()
    ]
    if not spans:
        return None
    # Body size = the font size covering most characters (median weighted by text length).
    sizes = [span["size"] for span in spans for _ in span["text"]]
    body_size = statistics.median(sizes)
    # Only text with letters or digits can be a title: big bullets or symbols ("• • •") can't.
    candidates = [
        span
        for span in spans
        if any(c.isalnum() for c in span["text"]) and _in_title_area(span, page)
    ]
    if not candidates:
        return None
    max_size = max(span["size"] for span in candidates)
    if max_size < body_size * 1.15:
        return None
    parts = [span["text"].strip() for span in candidates if span["size"] >= max_size - 0.5]
    title = normalize_text(" ".join(parts))
    title = re.sub(r"\s+", " ", title)
    return title[:_MAX_TITLE_CHARS] or None


_GRID = 40  # 40 x 40 sample points per page: precise enough for a coverage percentage


def image_coverage(page: pymupdf.Page) -> float:
    """Fraction of the page (0-1) covered by embedded images (D30).

    Sampled on a grid so overlapping images are not counted twice. Answers the question text
    extraction can't: is there content we are not reading (a code screenshot, a diagram)?
    Vector drawings (shapes drawn by PowerPoint) are not images and are not counted.
    """
    boxes = [info["bbox"] for info in page.get_image_info()]
    if not boxes:
        return 0.0
    # Image boxes are in the unrotated visible area's coordinates, starting at (0, 0) even when
    # the PDF's CropBox is offset: sample that area, not the CropBox's absolute position.
    width, height = page.cropbox.width, page.cropbox.height
    # Grid of sample points (cell centres), tested against every box at once with numpy:
    # a third of extraction time was spent on a pure-Python version of this loop.
    xs, ys = np.meshgrid(
        (np.arange(_GRID) + 0.5) * width / _GRID, (np.arange(_GRID) + 0.5) * height / _GRID
    )
    covered = np.zeros_like(xs, dtype=bool)
    for x0, y0, x1, y1 in boxes:
        covered |= (xs >= x0) & (xs < x1) & (ys >= y0) & (ys < y1)
    return round(float(covered.mean()), 3)


class PdfLoader:
    name = "pymupdf"
    # 2: symbol-only text is never a title. 3: titles only in the top 30% of the page.
    # 4: image_coverage per page (D30). 5: coverage correct on PDFs with an offset CropBox.
    # 6: LaTeX spacing accents fixed ("Soluci´o" -> "Solució").
    version = 7  # 7: "l´any" is an apostrophe, not "lány"; LaTeX "´ı" -> "í"
    extensions = (".pdf",)

    def load(self, path: Path, thumbnails_dir: Path, thumbnail_width: int) -> list[RawPage]:
        pages: list[RawPage] = []
        with pymupdf.open(path) as doc:
            if doc.needs_pass:
                raise ValueError("PDF is password-protected")
            thumbnails_dir.mkdir(parents=True, exist_ok=True)
            for page in doc:
                number = page.number + 1
                rect = page.rect  # visible page size, rotation already applied
                zoom = thumbnail_width / rect.width
                thumbnail = thumbnails_dir / f"p{number:04d}.png"
                page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).save(thumbnail)
                pages.append(
                    RawPage(
                        number=number,
                        width=round(rect.width, 1),
                        height=round(rect.height, 1),
                        # sort=True: blocks in reading order (top-left to bottom-right) instead of
                        # the order they were written into the file, which is often jumbled.
                        text=normalize_text(page.get_text("text", sort=True)),
                        title=guess_title(page),
                        image_count=len(page.get_images()),
                        image_coverage=image_coverage(page),
                        thumbnail=thumbnail,
                    )
                )
        return pages
