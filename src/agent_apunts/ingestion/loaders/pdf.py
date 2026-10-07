"""PDF loader with PyMuPDF (D15): per page text, title guess, image count and a PNG thumbnail."""

import re
import statistics
import unicodedata
from pathlib import Path

import pymupdf

from agent_apunts.ingestion.loaders.base import RawPage

_MAX_TITLE_CHARS = 200
# A title must start in the top 30% of the page. Big text lower down is a callout, not a title
# (real case: slides_grasp.pdf p26, a big comment under a code screenshot).
_TITLE_TOP_FRACTION = 0.3


def normalize_text(text: str) -> str:
    """Make extracted text consistent without changing its content.

    - NFC: some PDFs store "à" as "a" + combining accent; NFC turns it into the single character
      users type, so search and embeddings see the same string.
    - Strip trailing spaces per line and collapse 3+ newlines into one blank line.
    Removing boilerplate (logos, repeated footers) is NOT done here: that's the CLEAN stage (D11).
    """
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
    boxes = [pymupdf.Rect(info["bbox"]) for info in page.get_image_info()]
    if not boxes:
        return 0.0
    box = page.cropbox  # image boxes use the unrotated page's coordinates
    width, height = box.width, box.height
    covered = 0
    for i in range(_GRID):
        for j in range(_GRID):
            point = pymupdf.Point(
                box.x0 + (i + 0.5) * width / _GRID, box.y0 + (j + 0.5) * height / _GRID
            )
            covered += any(point in r for r in boxes)
    return round(covered / _GRID**2, 3)


class PdfLoader:
    name = "pymupdf"
    # 2: symbol-only text is never a title. 3: titles only in the top 30% of the page.
    # 4: image_coverage per page (D30).
    version = 4
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
