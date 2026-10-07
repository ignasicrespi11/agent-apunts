"""extract.py: registered documents -> processed JSON, incremental and versioned."""

import pytest

from agent_apunts.ingestion import extract as extract_mod
from agent_apunts.ingestion.extract import extract_all, processed_path, read_json
from agent_apunts.ingestion.manifest import Manifest
from agent_apunts.ingestion.register import register_source
from tests.pdf_factory import make_pdf

USER = "ignasi"


@pytest.fixture
def manifest(settings):
    root = settings.source("testing").root
    make_pdf(root / "disseny_software" / "theory" / "slides.pdf", ["slide", "image"])
    make_pdf(root / "informacio_i_seguretat" / "exams" / "IS2425-P1.pdf", ["a4", "a4"])
    with Manifest(settings.paths.manifest) as m:
        register_source(m, USER, settings.source("testing"), settings)
        yield m


def _doc(manifest, settings, name):
    record = next(r for r in manifest.documents(USER) if name in r.rel_path)
    return read_json(processed_path(settings, USER, record.doc_id))


def test_extracts_every_document(manifest, settings):
    report = extract_all(manifest, USER, settings)
    assert len(report.extracted) == 2 and report.pages == 4 and not report.errors
    assert report.empty_pages == [("disseny_software/theory/slides.pdf", 2)]

    slides = _doc(manifest, settings, "slides")
    assert slides.user_id == USER and slides.extractor == "pymupdf-5"
    assert slides.metadata.subject == "disseny_software"
    slide, image = slides.pages
    assert slide.title == "Patrons de disseny" and slide.language == "ca"
    assert not slide.mostly_image and image.mostly_image
    assert (settings.paths.data_dir / slide.thumbnail).is_file()

    exam = _doc(manifest, settings, "IS2425")
    assert exam.languages == ["es"]
    assert all(p.char_count > 1000 for p in exam.pages)


def test_marks_stage_in_manifest(manifest, settings):
    extract_all(manifest, USER, settings)
    for record in manifest.documents(USER):
        stage = manifest.stage(USER, record.doc_id, "extract")
        assert stage.version == "pymupdf-5"
        assert stage.output == f"processed/{USER}/{record.doc_id}.json"


def test_second_run_skips_up_to_date(manifest, settings):
    extract_all(manifest, USER, settings)
    again = extract_all(manifest, USER, settings)
    assert again.extracted == [] and len(again.up_to_date) == 2
    forced = extract_all(manifest, USER, settings, force=True)
    assert len(forced.extracted) == 2


def test_deleted_output_is_redone(manifest, settings):
    extract_all(manifest, USER, settings)
    record = manifest.documents(USER)[0]
    processed_path(settings, USER, record.doc_id).unlink()
    assert extract_all(manifest, USER, settings).extracted == [record.rel_path]


def test_new_loader_version_redoes_everything(manifest, settings, monkeypatch):
    extract_all(manifest, USER, settings)
    loader = extract_mod.loader_for(extract_mod.Path("x.pdf"))
    monkeypatch.setattr(loader, "version", loader.version + 1)
    assert len(extract_all(manifest, USER, settings).extracted) == 2


def test_broken_file_does_not_stop_the_run(manifest, settings):
    root = settings.source("testing").root
    broken = root / "disseny_software" / "labs" / "broken.pdf"
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"not really a pdf")
    register_source(manifest, USER, settings.source("testing"), settings)

    report = extract_all(manifest, USER, settings)
    assert len(report.extracted) == 2
    assert [path for path, _ in report.errors] == ["disseny_software/labs/broken.pdf"]
    assert not any(settings.paths.processed_dir.rglob("*.tmp"))
