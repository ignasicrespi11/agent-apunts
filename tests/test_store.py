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


def test_identical_chunks_are_not_re_embedded(manifest, settings, embedder, store, monkeypatch):
    _index(manifest, settings, embedder, store)
    calls = embedder.calls
    # A new extractor version re-extracts and re-chunks everything, but the text is identical...
    from pathlib import Path

    from agent_apunts.ingestion.loaders import loader_for

    loader = loader_for(Path("x.pdf"))
    monkeypatch.setattr(loader, "version", loader.version + 1)
    assert len(extract_all(manifest, USER, settings).extracted) == 2
    assert len(chunk_all(manifest, USER, settings).chunked) == 2
    # ... so the vectors are still valid: no embedding call at all.
    report = _index(manifest, settings, embedder, store)
    assert report.indexed == [] and len(report.up_to_date) == 2
    assert embedder.calls == calls


def test_moved_document_gets_its_payload_updated(manifest, settings, embedder, store):
    _index(manifest, settings, embedder, store)
    root = settings.source("testing").root
    old = root / "disseny_software" / "theory" / "patrons.pdf"
    new = root / "disseny_software" / "labs" / "patrons.pdf"
    new.parent.mkdir(parents=True)
    old.rename(new)
    register_source(manifest, USER, settings.source("testing"), settings)  # moved: same doc_id
    chunk_all(manifest, USER, settings)
    calls = embedder.calls
    report = _index(manifest, settings, embedder, store)
    # Same file name and subject -> same embedded text: payload rewritten, nothing re-embedded.
    assert report.payload_only == ["disseny_software/labs/patrons.pdf"] and report.indexed == []
    assert embedder.calls == calls
    hits = search("patró observador", USER, embedder, store, doc_type="labs")
    assert hits and hits[0].payload["rel_path"] == "disseny_software/labs/patrons.pdf"


class ConstantEmbedder(HashEmbedder):
    """Every text gets the same vector: dense search can't tell chunks apart, keywords can."""

    def embed(self, texts):
        self.calls += 1
        return [[1.0] + [0.0] * (self.dimension - 1) for _ in texts]


def _doc(user_id, doc_id, texts):
    from agent_apunts.ingestion.chunk import Chunk, ChunkedDocument
    from agent_apunts.ingestion.chunk import chunk_id as make_id

    return ChunkedDocument(
        user_id=user_id,
        doc_id=doc_id,
        source="testing",
        rel_path=f"{doc_id}.pdf",
        metadata=None,
        chunker="t",
        removed=[],
        chunks=[
            Chunk(
                chunk_id=make_id(user_id, doc_id, i, t),
                index=i,
                page=i + 1,
                part=0,
                title=None,
                header="h",
                text=t,
                word_count=len(t.split()),
                language="en",
            )
            for i, t in enumerate(texts)
        ],
    )


def test_hybrid_finds_exact_keyword_and_keeps_cosine_scores(client):
    embedder = ConstantEmbedder()
    store = VectorStore(client, "h", embedder.model, embedder.dimension, avg_chunk_words=5)
    store.ensure_collection()
    texts = ["cache memory levels", "pipeline hazards stall", "the TLB caches page translations"]
    doc = _doc(USER, "d", texts)
    store.replace_document(doc, embedder.embed(texts))
    other = _doc("anna", "o", ["TLB TLB TLB"])
    store.replace_document(other, embedder.embed(other.chunks))

    (vector,) = embedder.embed(["what is a TLB"])
    hits = store.search(USER, vector, limit=3, query_text="what is a TLB")
    assert hits[0].payload["text"] == texts[2]  # keyword match ranked first
    assert all(h.payload["user_id"] == USER for h in hits)  # filter applies to both methods
    assert all(abs(h.score - 1.0) < 1e-6 for h in hits)  # scores are cosine, not RRF


def test_collection_with_old_schema_is_refused(client):
    from qdrant_client import models

    client.create_collection(
        "old",
        vectors_config=models.VectorParams(size=64, distance=models.Distance.COSINE),
        metadata={"embedding_model": "fake-hash", "dimension": 64},
    )
    with pytest.raises(StoreError, match="older layout"):
        VectorStore(client, "old", "fake-hash", 64).ensure_collection()


def test_payload_update_failure_is_reported_not_fatal(manifest, settings, embedder, store):
    _index(manifest, settings, embedder, store)
    root = settings.source("testing").root
    target = root / "disseny_software" / "labs" / "patrons.pdf"
    target.parent.mkdir(parents=True)
    (root / "disseny_software" / "theory" / "patrons.pdf").rename(target)
    register_source(manifest, USER, settings.source("testing"), settings)
    chunk_all(manifest, USER, settings)

    def broken(doc):
        raise RuntimeError("qdrant timeout")

    store.update_document_payload = broken
    report = _index(manifest, settings, embedder, store)
    assert report.errors == [("disseny_software/labs/patrons.pdf", "RuntimeError: qdrant timeout")]
    assert len(report.up_to_date) == 1  # the other document is still processed


def test_index_reports_progress_once_per_document_and_at_the_end(
    manifest, settings, embedder, store
):
    calls = []
    _index(manifest, settings, embedder, store, on_progress=lambda *a: calls.append(a))
    assert [(done, total) for done, total, _ in calls] == [(0, 2), (1, 2), (2, 2)]
    assert all(path.endswith(".pdf") for _, _, path in calls[:-1]) and calls[-1][2] == ""

    # Up-to-date documents are reported too: a re-run shows the bar move, not a frozen screen.
    calls.clear()
    _index(manifest, settings, embedder, store, on_progress=lambda *a: calls.append(a))
    assert len(calls) == 3
