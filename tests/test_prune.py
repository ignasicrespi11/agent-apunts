"""prune.py: forget deleted and replaced documents everywhere, never moved ones (D35)."""

import pytest
from qdrant_client import QdrantClient

from agent_apunts.ingestion.chunk import chunk_all, chunks_path
from agent_apunts.ingestion.extract import extract_all, processed_path
from agent_apunts.ingestion.index import index_all
from agent_apunts.ingestion.manifest import Manifest
from agent_apunts.ingestion.prune import prune
from agent_apunts.ingestion.register import register_source
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


def _ingest(m, settings, embedder, store):
    register_source(m, USER, settings.source("testing"), settings)
    report = prune(m, USER, settings, store)
    extract_all(m, USER, settings)
    chunk_all(m, USER, settings)
    index_all(m, USER, settings, embedder, store)
    return report


def test_replaced_pdf_leaves_no_old_version(env, settings):
    m, root, embedder, store = env
    _ingest(m, settings, embedder, store)
    old = next(r for r in m.documents(USER) if r.rel_path.endswith("patrons.pdf"))

    make_pdf(root / "disseny_software" / "theory" / "patrons.pdf", ["a4"])  # new version
    report = _ingest(m, settings, embedder, store)

    assert report.removed == ["disseny_software/theory/patrons.pdf"]
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
    report = _ingest(m, settings, embedder, store)
    assert report.removed == ["informacio_i_seguretat/exams/e.pdf"]
    assert store.count(USER) < before and len(m.documents(USER)) == 1


def test_moved_pdf_is_not_pruned(env, settings):
    m, root, embedder, store = env
    _ingest(m, settings, embedder, store)
    target = root / "disseny_software" / "labs" / "patrons.pdf"
    target.parent.mkdir(parents=True)
    (root / "disseny_software" / "theory" / "patrons.pdf").rename(target)
    report = _ingest(m, settings, embedder, store)
    assert report.removed == []
    assert len(m.documents(USER)) == 2


def test_dry_run_changes_nothing(env, settings):
    m, root, embedder, store = env
    _ingest(m, settings, embedder, store)
    points = store.count(USER)
    (root / "informacio_i_seguretat" / "exams" / "e.pdf").unlink()
    register_source(m, USER, settings.source("testing"), settings)
    report = prune(m, USER, settings, store, dry_run=True)
    assert report.removed == ["informacio_i_seguretat/exams/e.pdf"]
    assert store.count(USER) == points and len(m.documents(USER)) == 2
