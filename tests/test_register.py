"""register.py: content-hash IDs; re-running is idempotent; moves, duplicates, missing files."""

import shutil

import pytest

from agent_apunts.ingestion.manifest import Manifest
from agent_apunts.ingestion.register import file_hash, register_source
from tests.pdf_factory import make_pdf

USER = "ignasi"


@pytest.fixture
def manifest(settings):
    with Manifest(settings.paths.manifest) as m:
        yield m


@pytest.fixture
def testing(settings):
    return settings.source("testing")


def _run(manifest, settings, name="testing"):
    return register_source(manifest, USER, settings.source(name), settings)


def test_file_hash_depends_on_content_only(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", ["slide"])
    b = tmp_path / "renamed.pdf"
    shutil.copy(a, b)
    assert file_hash(a) == file_hash(b)
    assert len(file_hash(a)) == 64
    assert file_hash(a) != file_hash(make_pdf(tmp_path / "c.pdf", ["a4"]))


def test_register_is_idempotent(manifest, settings, testing):
    make_pdf(testing.root / "disseny_software" / "theory" / "t1.pdf", ["slide"])
    make_pdf(testing.root / "informacio_i_seguretat" / "exams" / "IS2425-P1.pdf", ["a4"])

    first = _run(manifest, settings)
    assert len(first.new) == 2 and not first.errors

    second = _run(manifest, settings)
    assert second.new == [] and len(second.unchanged) == 2
    assert len(manifest.documents(USER)) == 2

    exam = next(r for r in manifest.documents(USER) if "IS2425" in r.rel_path)
    assert exam.metadata.doc_type == "exams" and exam.metadata.academic_year == "2024-25"


def test_moved_file_keeps_its_id(manifest, settings, testing):
    old = make_pdf(testing.root / "disseny_software" / "theory" / "t1.pdf", ["slide"])
    _run(manifest, settings)
    (doc,) = manifest.documents(USER)

    new = testing.root / "disseny_software" / "labs" / "renamed.pdf"
    new.parent.mkdir(parents=True)
    old.rename(new)
    report = _run(manifest, settings)

    assert report.moved == [("disseny_software/theory/t1.pdf", "disseny_software/labs/renamed.pdf")]
    (moved,) = manifest.documents(USER)
    assert moved.doc_id == doc.doc_id
    assert moved.metadata.doc_type == "labs"  # folder hint re-read after the move


def test_duplicates_are_skipped(manifest, settings, testing):
    a = make_pdf(testing.root / "disseny_software" / "theory" / "a.pdf", ["slide"])
    copy = testing.root / "disseny_software" / "labs" / "copy.pdf"
    copy.parent.mkdir(parents=True)
    shutil.copy(a, copy)
    report = _run(manifest, settings)
    assert len(report.new) == 1
    assert report.duplicates == [
        ("disseny_software/theory/a.pdf", "disseny_software/labs/copy.pdf")
    ]


def test_missing_and_edited_files_are_reported(manifest, settings, testing):
    path = make_pdf(testing.root / "disseny_software" / "theory" / "t.pdf", ["slide"])
    _run(manifest, settings)
    make_pdf(path, ["a4"])  # same name, new content -> new ID; the old ID is reported missing
    report = _run(manifest, settings)
    assert report.new == ["disseny_software/theory/t.pdf"]
    assert report.missing == ["disseny_software/theory/t.pdf"]


def test_labelled_source_requires_folders(manifest, settings, testing):
    make_pdf(testing.root / "loose.pdf", ["slide"])
    make_pdf(testing.root / "typo" / "theory" / "x.pdf", ["slide"])
    report = _run(manifest, settings)
    assert report.new == []
    assert {path for path, _ in report.errors} == {"loose.pdf", "typo/theory/x.pdf"}


def test_inbox_accepts_unorganised_files(manifest, settings):
    inbox = settings.source("apunts")
    make_pdf(inbox.root / "loose.pdf", ["slide"])
    report = _run(manifest, settings, "apunts")
    assert report.new == ["loose.pdf"]
    assert manifest.documents(USER)[0].metadata is None  # waits for auto-detection (D18)


def test_same_file_in_both_sources_is_kept_once(manifest, settings, testing):
    a = make_pdf(testing.root / "disseny_software" / "theory" / "a.pdf", ["slide"])
    inbox = settings.source("apunts").root
    inbox.mkdir(parents=True)
    shutil.copy(a, inbox / "a.pdf")
    _run(manifest, settings, "testing")
    report = _run(manifest, settings, "apunts")
    assert report.new == [] and report.duplicates[0][0] == "a.pdf"
    assert manifest.documents(USER)[0].source == "testing"
