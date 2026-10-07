"""chunk.py: processed JSON -> cleaned chunks, incremental and deterministic (D26, D27, D29)."""

import pytest

from agent_apunts.config import load_settings
from agent_apunts.ingestion.chunk import chunk_all, chunks_path, read_chunks
from agent_apunts.ingestion.extract import extract_all
from agent_apunts.ingestion.manifest import Manifest
from agent_apunts.ingestion.register import register_source
from tests.pdf_factory import make_pdf

USER = "ignasi"


@pytest.fixture
def manifest(settings):
    root = settings.source("testing").root
    make_pdf(root / "disseny_software" / "theory" / "patrons.pdf", ["slide", "image", "slide"])
    make_pdf(root / "informacio_i_seguretat" / "exams" / "IS2425-P1.pdf", ["dense", "a4"])
    with Manifest(settings.paths.manifest) as m:
        register_source(m, USER, settings.source("testing"), settings)
        extract_all(m, USER, settings)
        yield m


def _doc(manifest, settings, name):
    record = next(r for r in manifest.documents(USER) if name in r.rel_path)
    return read_chunks(chunks_path(settings, USER, record.doc_id))


def test_chunks_every_extracted_document(manifest, settings):
    report = chunk_all(manifest, USER, settings)
    assert len(report.chunked) == 2 and not report.errors

    slides = _doc(manifest, settings, "patrons")
    assert [c.page for c in slides.chunks] == [1, 3]  # the image-only page gives no chunk
    first = slides.chunks[0]
    assert first.header == "Disseny de Software · patrons · Patrons de disseny"
    assert first.embedding_text.startswith(first.header + "\n\n")
    assert first.language == "ca"


def test_dense_page_is_split_and_small_page_is_not(manifest, settings):
    chunk_all(manifest, USER, settings)
    exam = _doc(manifest, settings, "IS2425")
    page1 = [c for c in exam.chunks if c.page == 1]
    page2 = [c for c in exam.chunks if c.page == 2]
    assert len(page1) >= 2 and [c.part for c in page1] == list(range(len(page1)))
    assert len(page2) == 1
    assert all(c.word_count <= settings.chunking.max_words for c in exam.chunks)
    assert exam.chunks[0].header.endswith("· p. 1")  # A4 page without a title
    assert [c.index for c in exam.chunks] == list(range(len(exam.chunks)))


def test_repeated_lines_are_removed_and_reported(manifest, settings):
    chunk_all(manifest, USER, settings)
    slides = _doc(manifest, settings, "patrons")
    # Both slides start with the same title line: 2 of 3 pages, but below min_pages=3 -> kept.
    assert "Patrons de disseny" in slides.chunks[0].text
    assert slides.removed == []


def test_chunk_ids_are_deterministic(manifest, settings):
    chunk_all(manifest, USER, settings)
    before = [c.chunk_id for c in _doc(manifest, settings, "IS2425").chunks]
    chunk_all(manifest, USER, settings, force=True)
    after = [c.chunk_id for c in _doc(manifest, settings, "IS2425").chunks]
    assert before == after and len(set(before)) == len(before)


def test_incremental_and_settings_aware(manifest, settings, project):
    chunk_all(manifest, USER, settings)
    assert len(chunk_all(manifest, USER, settings).up_to_date) == 2

    path = project / "config" / "settings.yaml"
    path.write_text(path.read_text().replace("max_words: 450", "max_words: 400"))
    changed = load_settings(project)
    assert len(chunk_all(manifest, USER, changed).chunked) == 2  # new settings -> re-chunk


def test_documents_not_extracted_are_listed(settings):
    root = settings.source("testing").root
    make_pdf(root / "disseny_software" / "labs" / "lab.pdf", ["slide"])
    with Manifest(settings.paths.manifest) as m:
        register_source(m, USER, settings.source("testing"), settings)
        report = chunk_all(m, USER, settings)
    assert report.not_extracted == ["disseny_software/labs/lab.pdf"]
