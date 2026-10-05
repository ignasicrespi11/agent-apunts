"""PDF loader (PyMuPDF) on self-generated PDFs."""

from pathlib import Path

import pymupdf
import pytest

from agent_apunts.ingestion.loaders import loader_for, supported_extensions
from agent_apunts.ingestion.loaders.pdf import PdfLoader, normalize_text
from tests.pdf_factory import make_pdf


@pytest.fixture
def pages(tmp_path):
    pdf = make_pdf(tmp_path / "doc.pdf", ["slide", "a4", "image"])
    return PdfLoader().load(pdf, tmp_path / "thumbs", thumbnail_width=320)


def test_registry():
    assert ".pdf" in supported_extensions()
    assert isinstance(loader_for(Path("SLIDES.PDF")), PdfLoader)  # extension case-insensitive


def test_page_numbers_and_shape(pages):
    assert [p.number for p in pages] == [1, 2, 3]
    slide, a4, _ = pages
    assert slide.width > slide.height  # landscape
    assert a4.width < a4.height  # portrait


def test_text_and_title(pages):
    slide, a4, image = pages
    assert slide.title == "Patrons de disseny"
    assert "patró observador" in slide.text
    assert a4.title is None  # one font size: no title instead of a random line
    assert "memoria caché" in a4.text
    assert image.text == "" and image.title is None


def test_images_and_thumbnails(pages):
    assert [p.image_count for p in pages] == [1, 0, 1]
    for p in pages:
        assert p.thumbnail.is_file()
        assert pymupdf.Pixmap(str(p.thumbnail)).width == 320


def test_password_protected_pdf_is_an_error(tmp_path):
    doc = pymupdf.open()
    doc.new_page()
    path = tmp_path / "locked.pdf"
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="x", owner_pw="y")
    with pytest.raises(ValueError, match="password"):
        PdfLoader().load(path, tmp_path / "t", 100)


def test_normalize_text():
    decomposed = "memòria"  # "o" + combining grave accent
    assert normalize_text(decomposed) == "memòria"
    assert normalize_text("a  \n\n\n\nb \n") == "a\n\nb"
