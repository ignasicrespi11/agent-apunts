"""manifest.py: documents and stage status in SQLite, always scoped by user_id."""

import sqlite3

import pytest

from agent_apunts.ingestion.manifest import SCHEMA_VERSION, Manifest
from agent_apunts.metadata import DocumentMetadata

META = DocumentMetadata(
    university="UAB",
    degree="Computer Engineering",
    subject="disseny_software",
    doc_type="theory",
    taken_in="2025-26",
)


@pytest.fixture
def manifest(tmp_path):
    with Manifest(tmp_path / "data" / "manifest.sqlite") as m:
        yield m


def test_add_and_get_roundtrip(manifest):
    manifest.add("ignasi", "abc123", "testing", "disseny_software/theory/t1.pdf", 10, META)
    record = manifest.get("ignasi", "abc123")
    assert record.metadata == META  # JSON in SQLite -> validated model again
    assert record.rel_path == "disseny_software/theory/t1.pdf"


def test_documents_are_scoped_by_user(manifest):
    manifest.add("ignasi", "abc123", "testing", "a.pdf", 10, None)
    assert manifest.get("someone_else", "abc123") is None
    assert manifest.documents("someone_else") == []
    assert manifest.find("someone_else", "abc") == []


def test_same_document_for_two_users(manifest):
    manifest.add("ignasi", "abc123", "testing", "a.pdf", 10, None)
    manifest.add("anna", "abc123", "apunts", "b.pdf", 10, None)  # same bytes, other owner
    assert len(manifest.documents("ignasi")) == len(manifest.documents("anna")) == 1


def test_update_location_keeps_stages(manifest):
    manifest.add("ignasi", "abc123", "apunts", "loose.pdf", 10, None)
    manifest.mark_done("ignasi", "abc123", "extract", "pymupdf-2", "processed/x.json")
    manifest.update_location("ignasi", "abc123", "testing", "disseny_software/theory/t.pdf", META)
    assert manifest.get("ignasi", "abc123").source == "testing"
    assert manifest.stage("ignasi", "abc123", "extract").version == "pymupdf-2"


def test_mark_done_overwrites(manifest):
    manifest.add("ignasi", "abc123", "testing", "a.pdf", 10, None)
    manifest.mark_done("ignasi", "abc123", "extract", "pymupdf-1", "x")
    manifest.mark_done("ignasi", "abc123", "extract", "pymupdf-2", "x")
    assert manifest.stage("ignasi", "abc123", "extract").version == "pymupdf-2"
    assert manifest.stage("ignasi", "abc123", "chunk") is None


def test_find_by_prefix_or_path(manifest):
    manifest.add("ignasi", "abc123", "testing", "disseny_software/theory/t1.pdf", 1, None)
    manifest.add("ignasi", "def456", "testing", "dissenyXsoftware/theory/t2.pdf", 1, None)
    assert [r.doc_id for r in manifest.find("ignasi", "abc")] == ["abc123"]
    # "_" is a literal underscore, not the LIKE wildcard that would also match "X"
    assert [r.doc_id for r in manifest.find("ignasi", "disseny_software")] == ["abc123"]


def test_schema_version_is_checked(tmp_path):
    path = tmp_path / "m.sqlite"
    Manifest(path).close()
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(RuntimeError, match="schema v99"):
        Manifest(path)
