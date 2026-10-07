"""store.py + index stage + retrieval against Qdrant in local (in-memory) mode: no Docker needed."""

import pytest
from qdrant_client import QdrantClient

from agent_apunts.ingestion.chunk import chunk_all
from agent_apunts.ingestion.extract import extract_all
from agent_apunts.ingestion.index import index_all
from agent_apunts.ingestion.manifest import Manifest
from agent_apunts.ingestion.register import register_source
from agent_apunts.retrieval import search
from agent_apunts.store import StoreError, VectorStore
from tests.fakes import HashEmbedder
from tests.pdf_factory import make_pdf

USER = "ignasi"


@pytest.fixture
def embedder():
    return HashEmbedder()


@pytest.fixture
def client():
    return QdrantClient(":memory:")


@pytest.fixture
def store(client, embedder):
    return VectorStore(client, "apunts", embedder.model, embedder.dimension)


@pytest.fixture
def manifest(settings):
    root = settings.source("testing").root
    make_pdf(root / "disseny_software" / "theory" / "patrons.pdf", ["slide", "image", "slide"])
    make_pdf(root / "informacio_i_seguretat" / "exams" / "IS2425-P1.pdf", ["dense", "a4"])
    with Manifest(settings.paths.manifest) as m:
        register_source(m, USER, settings.source("testing"), settings)
        extract_all(m, USER, settings)
        chunk_all(m, USER, settings)
        yield m


def _index(manifest, settings, embedder, store, **kw):
    return index_all(manifest, USER, settings, embedder, store, **kw)


def test_index_then_search_finds_the_right_chunk(manifest, settings, embedder, store):
    report = _index(manifest, settings, embedder, store)
    assert len(report.indexed) == 2 and not report.errors and report.stopped is None
    assert store.count(USER) == report.points

    hits = search("patró observador canvis estat", USER, embedder, store, limit=3)
    assert hits[0].payload["subject"] == "disseny_software"
    assert hits[0].payload["page"] in (1, 3)
    assert hits[0].payload["text"] and hits[0].payload["header"].startswith("Disseny de Software")


def test_index_twice_keeps_the_same_points(manifest, settings, embedder, store):
    _index(manifest, settings, embedder, store)
    before = store.count(USER)
    second = _index(manifest, settings, embedder, store)
    assert second.indexed == [] and len(second.up_to_date) == 2
    forced = _index(manifest, settings, embedder, store, force=True)
    assert len(forced.indexed) == 2
    assert store.count(USER) == before  # upsert by deterministic ID: no duplicates (D29)


def test_lost_points_are_reindexed(manifest, settings, embedder, client):
    store = VectorStore(client, "apunts", embedder.model, embedder.dimension)
    _index(manifest, settings, embedder, store)
    client.delete_collection("apunts")  # e.g. the Docker volume was deleted
    report = _index(manifest, settings, embedder, store)
    assert len(report.indexed) == 2 and store.count(USER) > 0


def test_search_filters_by_user_and_subject_inside_qdrant(manifest, settings, embedder, store):
    _index(manifest, settings, embedder, store)
    assert search("memoria caché", "someone_else", embedder, store) == []
    only_ds = search("memoria caché", USER, embedder, store, subject="disseny_software")
    assert only_ds and all(h.payload["subject"] == "disseny_software" for h in only_ds)


def test_rechunked_document_drops_stale_points(manifest, settings, embedder, store, project):
    from agent_apunts.config import load_settings

    _index(manifest, settings, embedder, store)
    before = store.count(USER)
    path = project / "config" / "settings.yaml"
    text = path.read_text().replace("max_words: 450", "max_words: 120")
    path.write_text(text.replace("target_words: 350", "target_words: 100"))
    smaller = load_settings(project)
    chunk_all(manifest, USER, smaller)
    _index(manifest, smaller, embedder, store)
    expected = sum(
        int(manifest.stage(USER, r.doc_id, "index").output.split()[0])
        for r in manifest.documents(USER)
    )
    assert store.count(USER) == expected > before  # more, smaller chunks; old ones gone


def test_collection_built_with_another_model_is_refused(client, embedder):
    VectorStore(client, "apunts", "model-a", 64).ensure_collection()
    with pytest.raises(StoreError, match="was built with model-a"):
        VectorStore(client, "apunts", "model-b", 64).ensure_collection()


def test_embedder_failure_stops_the_run(manifest, settings, store):
    from agent_apunts.embeddings import EmbeddingError

    class Down(HashEmbedder):
        def embed(self, texts):
            raise EmbeddingError("cannot reach Ollama")

    report = _index(manifest, settings, Down(), store)
    assert report.stopped == "cannot reach Ollama" and report.indexed == []
