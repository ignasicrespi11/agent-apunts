"""prune.py: forget deleted and replaced documents, never on missing evidence (D35)."""

import pytest
from qdrant_client import QdrantClient

from agent_apunts.ingestion.chunk import chunk_all, chunks_path
from agent_apunts.ingestion.extract import extract_all, processed_path
from agent_apunts.ingestion.index import index_all
from agent_apunts.ingestion.manifest import Manifest
from agent_apunts.ingestion.prune import find_orphans, remove
from agent_apunts.ingestion.register import RegisterReport, register_source
from agent_apunts.store import VectorStore
from tests.fakes import HashEmbedder
from tests.pdf_factory import make_pdf

USER = "ignasi"


@pytest.fixture
def env(settings):
    root = settings.source("testing").root
    make_pdf(root / "disseny_software" / "theory" / "patrons.pdf", ["slide"])
    make_pdf(root / "informacio_i_seguretat" / "exams" / "e.pdf", ["a4"])
    embedder = HashEmbedder()
    store = VectorStore(QdrantClient(":memory:"), "apunts", embedder.model, embedder.dimension)
    with Manifest(settings.paths.manifest) as m:
        yield m, root, embedder, store


def _scan(m, settings):
    return {src.name: register_source(m, USER, src, settings) for src in settings.sources}


def _ingest(m, settings, embedder, store):
    orphans = find_orphans(m, USER, settings, _scan(m, settings))
    remove(m, USER, settings, store, orphans.documents)
    extract_all(m, USER, settings)
    chunk_all(m, USER, settings)
    index_all(m, USER, settings, embedder, store)
    return [r.rel_path for r in orphans.documents]


def test_replaced_pdf_leaves_no_old_version(env, settings):
    m, root, embedder, store = env
    _ingest(m, settings, embedder, store)
    old = next(r for r in m.documents(USER) if r.rel_path.endswith("patrons.pdf"))

    make_pdf(root / "disseny_software" / "theory" / "patrons.pdf", ["a4"])  # new version
    removed = _ingest(m, settings, embedder, store)

    assert removed == ["disseny_software/theory/patrons.pdf"]
    assert m.get(USER, old.doc_id) is None and m.stage(USER, old.doc_id, "extract") is None
    assert not processed_path(settings, USER, old.doc_id).exists()
    assert not chunks_path(settings, USER, old.doc_id).exists()
    assert not (settings.paths.thumbnails_dir / USER / old.doc_id).exists()
    assert store.count(USER, old.doc_id) == 0
    assert len(m.documents(USER)) == 2  # the new version and the other document


def test_deleted_pdf_is_forgotten(env, settings):
    m, root, embedder, store = env
    _ingest(m, settings, embedder, store)
    before = store.count(USER)
    (root / "informacio_i_seguretat" / "exams" / "e.pdf").unlink()
    assert _ingest(m, settings, embedder, store) == ["informacio_i_seguretat/exams/e.pdf"]
    assert store.count(USER) < before and len(m.documents(USER)) == 1


def test_moved_pdf_is_not_pruned(env, settings):
    m, root, embedder, store = env
    _ingest(m, settings, embedder, store)
    target = root / "disseny_software" / "labs" / "patrons.pdf"
    target.parent.mkdir(parents=True)
    (root / "disseny_software" / "theory" / "patrons.pdf").rename(target)
    assert _ingest(m, settings, embedder, store) == []
    assert len(m.documents(USER)) == 2


def test_missing_source_folder_keeps_everything(env, settings):
    # e.g. OneDrive not mounted on this machine: absence of evidence is not deletion.
    m, root, embedder, store = env
    _ingest(m, settings, embedder, store)
    root.rename(root.with_name("unmounted"))
    orphans = find_orphans(m, USER, settings, _scan(m, settings))
    assert orphans.documents == [] and orphans.skipped_sources == ["testing", "apunts"]


def test_unreadable_file_is_kept(env, settings):
    m, root, embedder, store = env
    _ingest(m, settings, embedder, store)
    scans = _scan(m, settings)
    # Simulate a file locked mid-sync: register could not hash it this time.
    exam = next(r for r in m.documents(USER) if r.rel_path.endswith("e.pdf"))
    scans["testing"].seen.discard(exam.doc_id)
    scans["testing"].errors.append((exam.rel_path, "PermissionError"))
    assert find_orphans(m, USER, settings, scans).documents == []


def test_every_existing_source_must_be_scanned(env, settings):
    m, root, embedder, store = env
    scans = {"testing": register_source(m, USER, settings.source("testing"), settings)}
    settings.source("apunts").root.mkdir(parents=True)
    with pytest.raises(ValueError, match="register every source"):
        find_orphans(m, USER, settings, scans)
    scans["apunts"] = RegisterReport(scanned=True)
    find_orphans(m, USER, settings, scans)  # now fine
