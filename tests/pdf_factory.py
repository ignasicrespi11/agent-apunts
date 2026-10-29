"""Self-generated PDFs for tests (D17: no course material in the repo, not even as fixtures).

They imitate the two page kinds found in the real corpus (D13): landscape slides with a big title
and little text, and dense portrait A4 pages in a single font size; plus an image-only page.
"""

from pathlib import Path

import pymupdf

A4 = (595, 842)  # points
SLIDE = (842, 595)

CATALAN = (
    "Un patró de disseny és una solució reutilitzable a un problema comú. "
    "El patró observador permet notificar els canvis d'estat a diversos objectes."
)
SPANISH = (
    "La memoria caché almacena los datos usados recientemente para reducir el tiempo medio "
    "de acceso. Calcule la tasa de aciertos y el tiempo de acceso efectivo del sistema. "
)
ENGLISH = "Access control decides which users may read or modify each resource in the system."


def _image(page: pymupdf.Page, rect: pymupdf.Rect) -> None:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 30), False)
    pix.clear_with(180)
    page.insert_image(rect, pixmap=pix)


def make_pdf(path: Path, pages: list[str]) -> Path:
    """pages: list of 'slide', 'a4', 'dense', 'code' or 'image' (one page each)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for kind in pages:
        if kind == "slide":
            page = doc.new_page(width=SLIDE[0], height=SLIDE[1])
            page.insert_text((50, 80), "Patrons de disseny", fontsize=32)
            page.insert_textbox(pymupdf.Rect(50, 120, 790, 400), CATALAN, fontsize=16)
            _image(page, pymupdf.Rect(600, 420, 780, 560))
        elif kind == "a4":
            page = doc.new_page(width=A4[0], height=A4[1])
            page.insert_textbox(pymupdf.Rect(50, 50, 545, 790), SPANISH * 12, fontsize=11)
        elif kind == "dense":  # ~800 words in 4 paragraphs: must be split into chunks (D26)
            page = doc.new_page(width=A4[0], height=A4[1])
            paragraphs = "\n\n".join(f"Paragraph {i}. " + SPANISH * 4 for i in range(1, 5))
            page.insert_textbox(pymupdf.Rect(40, 40, 555, 800), paragraphs, fontsize=7)
        elif kind == "code":  # text + a big image, like a slide with a code screenshot (D30)
            page = doc.new_page(width=SLIDE[0], height=SLIDE[1])
            page.insert_text((50, 80), "Observer: implementation", fontsize=30)
            page.insert_text(
                (50, 130),
                "The subject keeps a list and notifies every registered observer.",
                fontsize=16,
            )
            _image(page, pymupdf.Rect(50, 160, 790, 560))
        elif kind == "image":
            page = doc.new_page(width=SLIDE[0], height=SLIDE[1])
            _image(page, pymupdf.Rect(50, 50, 790, 545))
        else:
            raise ValueError(kind)
    doc.save(path)
    doc.close()
    return path
