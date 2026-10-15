"""ocr.py and the OCR path through extract and chunk (D39). Needs Tesseract's language files:
the tests that really OCR are skipped on machines without them."""

import pymupdf
import pytest

from agent_apunts.ingestion import ocr
from agent_apunts.ingestion.chunk import OCR_LABEL, chunk_all, chunks_path, read_chunks
from agent_apunts.ingestion.extract import (
    OcrUnavailableError,
    extract_all,
    processed_path,
    read_json,
)
from agent_apunts.ingestion.manifest import Manifest
from agent_apunts.ingestion.register import register_source
from tests.pdf_factory import make_pdf

USER = "ignasi"
TESSDATA = ocr.find_tessdata()
READY = TESSDATA is not None and not ocr.missing_languages("cat+spa+eng", TESSDATA)
needs_tesseract = pytest.mark.skipif(not READY, reason="Tesseract cat/spa/eng not installed")


def _with_ocr(settings, enabled=True):
    ex = settings.extraction
    return settings.model_copy(
        update={
            "extraction": ex.model_copy(
                update={"ocr": ex.ocr.model_copy(update={"enabled": enabled})}
            )
        }
    )


def test_tesseract_language_names():
    assert ocr.tesseract_language(["ca", "es", "en"]) == "cat+spa+eng"


def test_missing_languages(tmp_path):
    (tmp_path / "eng.traineddata").write_bytes(b"x")
    assert ocr.missing_languages("cat+eng", tmp_path) == ["cat"]
    assert ocr.missing_languages("eng", None) == ["eng"]


def test_words_are_regrouped_into_lines():
    # (x0, y0, x1, y1, word): two lines, words given out of order, as the OCR layer does.
    words = [
        (60, 10, 90, 20, "class"),
        (10, 40, 40, 50, "Sale"),
        (10, 10, 50, 20, "public"),
        (50, 41, 80, 51, "sale"),
    ]
    assert ocr._lines(words) == "public class\nSale sale"


@needs_tesseract
def test_code_screenshot_is_read_and_logo_skipped(tmp_path):
    path = make_pdf(tmp_path / "s.pdf", ["screenshot"])
    options = ocr.OcrOptions("cat+spa+eng", 200, 0.05, str(TESSDATA))
    with pymupdf.open(path) as doc:
        text = ocr.image_text(doc[0], options)
    assert "public class Creator" in text
    # OCR is not exact: small monospace text can lose accents ("instancia"). Known limitation:
    # bge-m3 and the hybrid keywords (accent-free) still match it.
    assert "creador crea la instanc" in text
    assert text.count("\n\n") == 0  # one block: the logo (small image) was not OCR'd


def test_ocr_off_by_default_changes_nothing(settings):
    root = settings.source("testing").root
    make_pdf(root / "disseny_software" / "theory" / "s.pdf", ["screenshot"])
    with Manifest(settings.paths.manifest) as m:
        register_source(m, USER, settings.source("testing"), settings)
        extract_all(m, USER, settings)
        (record,) = m.documents(USER)
    doc = read_json(processed_path(settings, USER, record.doc_id))
    assert doc.pages[0].ocr_text == "" and "+ocr" not in doc.extractor


def test_ocr_on_without_language_files_says_how_to_fix(settings, monkeypatch):
    monkeypatch.setattr("agent_apunts.ingestion.extract.find_tessdata", lambda: None)
    root = settings.source("testing").root
    make_pdf(root / "disseny_software" / "theory" / "s.pdf", ["screenshot"])
    with Manifest(settings.paths.manifest) as m:
        register_source(m, USER, settings.source("testing"), settings)
        with pytest.raises(OcrUnavailableError, match="cat.traineddata"):
            extract_all(m, USER, _with_ocr(settings))


@needs_tesseract
def test_ocr_text_reaches_the_chunks_and_switching_it_reextracts(settings):
    root = settings.source("testing").root
    make_pdf(root / "disseny_software" / "theory" / "s.pdf", ["screenshot", "image"])
    on = _with_ocr(settings)
    with Manifest(settings.paths.manifest) as m:
        register_source(m, USER, settings.source("testing"), settings)
        extract_all(m, USER, settings)  # off first
        report = extract_all(m, USER, on)  # turning OCR on re-extracts
        assert report.extracted == ["disseny_software/theory/s.pdf"]
        chunk_all(m, USER, on)
        (record,) = m.documents(USER)
    doc = read_json(processed_path(on, USER, record.doc_id))
    assert "+ocr1" in doc.extractor and "public class Creator" in doc.pages[0].ocr_text
    assert doc.pages[1].ocr_text == ""  # a plain grey image has no text
    chunks = read_chunks(chunks_path(on, USER, record.doc_id)).chunks
    assert len(chunks) == 1 and chunks[0].page == 1
    assert chunks[0].text.startswith("Patró Creator")
    assert f"{OCR_LABEL}\npublic class Creator" in chunks[0].text


def test_broken_language_files_are_caught_before_any_document(tmp_path):
    for lang in ("cat", "spa", "eng"):  # what a blocked download saves: a short error page
        (tmp_path / f"{lang}.traineddata").write_text('{"message": "Forbidden"}')
    assert ocr.missing_languages("cat+spa+eng", tmp_path) == []  # present...
    assert "could not load" in ocr.self_test("cat+spa+eng", tmp_path)  # ...but unusable


@needs_tesseract
def test_self_test_passes_with_real_files():
    assert ocr.self_test("cat+spa+eng", TESSDATA) is None
