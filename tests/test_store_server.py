"""Integration test against a REAL Qdrant server (the in-memory mode ignores payload indexes).

Opt-in: runs only when QDRANT_TEST_URL is set, e.g. after `docker compose up -d`:
    QDRANT_TEST_URL=http://localhost:6333 uv run pytest tests/test_store_server.py
Uses a throwaway collection and deletes it afterwards; your real 'apunts' collection is untouched.
"""

import os
import uuid

import pytest
from qdrant_client import QdrantClient

from agent_apunts.ingestion.chunk import Chunk, ChunkedDocument
from agent_apunts.store import StoreError, VectorStore
from tests.fakes import HashEmbedder

URL = os.environ.get("QDRANT_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set QDRANT_TEST_URL to run against a server")


@pytest.fixture
def store():
    client = QdrantClient(url=URL, timeout=30)
    name = f"test_{uuid.uuid4().hex[:8]}"
    embedder = HashEmbedder()
    yield VectorStore(client, name, embedder.model, embedder.dimension), embedder, client
    client.delete_collection(name)


def _doc(user_id, doc_id, texts, subject="disseny_software"):
    from agent_apunts.metadata import DocumentMetadata

    meta = DocumentMetadata(
        university="UAB",
        degree="CE",
        subject=subject,
        doc_type="theory",
        taken_in="2025-26",
    )
    chunks = [
        Chunk(
            chunk_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{user_id}{doc_id}{i}{t}")),
            index=i,
            page=i + 1,
            part=0,
            title=None,
            header=f"h · p. {i + 1}",
            text=t,
            word_count=len(t.split()),
            language="en",
        )
        for i, t in enumerate(texts)
    ]
    return ChunkedDocument(
        user_id=user_id,
        doc_id=doc_id,
        source="testing",
        rel_path=f"{doc_id}.pdf",
        metadata=meta,
        chunker="test",
        removed=[],
        chunks=chunks,
    )


def test_collection_has_metadata_and_tenant_index(store):
    vs, _, client = store
    vs.ensure_collection()
    info = client.get_collection(vs.collection)
    assert info.config.metadata == {"embedding_model": "fake-hash", "dimension": 64, "schema": 2}
    assert {"user_id", "subject", "doc_type", "doc_id", "language"} <= set(info.payload_schema)
    vs.ensure_collection()  # second call: exists, same model -> fine


def test_replace_search_and_isolation_on_server(store):
    vs, embedder, _ = store
    vs.ensure_collection()
    a = _doc("ignasi", "d1", ["cache memory hierarchy", "pipeline hazards"])
    b = _doc("anna", "d2", ["cache memory hierarchy"])
    for doc in (a, b):
        vs.replace_document(doc, embedder.embed([c.text for c in doc.chunks]))
    assert vs.count("ignasi") == 2 and vs.count("anna") == 1

    (vector,) = embedder.embed(["cache memory"])
    hits = vs.search("ignasi", vector, limit=5)
    assert {h.payload["user_id"] for h in hits} == {"ignasi"}
    assert hits[0].payload["text"] == "cache memory hierarchy"

    shorter = _doc("ignasi", "d1", ["cache memory hierarchy"])  # re-chunked: one chunk fewer
    vs.replace_document(shorter, embedder.embed(["cache memory hierarchy"]))
    assert vs.count("ignasi") == 1 and vs.count("anna") == 1


def test_other_model_refused_on_server(store):
    vs, _, client = store
    vs.ensure_collection()
    with pytest.raises(StoreError, match="was built with fake-hash"):
        VectorStore(client, vs.collection, "bge-m3", 64).ensure_collection()


def test_update_document_payload_on_server(store):
    from agent_apunts.metadata import DocumentMetadata

    vs, embedder, _ = store
    vs.ensure_collection()
    doc = _doc("ignasi", "d1", ["cache memory hierarchy", "pipeline hazards"])
    vs.replace_document(doc, embedder.embed([c.text for c in doc.chunks]))
    moved = doc.model_copy(
        update={
            "rel_path": "d1-moved.pdf",
            "metadata": DocumentMetadata(
                university="UAB",
                degree="CE",
                subject="disseny_software",
                doc_type="labs",
                taken_in="2025-26",
            ),
        }
    )
    vs.update_document_payload(moved)
    (vector,) = embedder.embed(["cache memory"])
    hits = vs.search("ignasi", vector, limit=5, doc_type="labs")
    assert len(hits) == 2 and {h.payload["rel_path"] for h in hits} == {"d1-moved.pdf"}
    assert hits[0].payload["text"]  # chunk-level fields untouched


def test_hybrid_search_on_server(store):
    vs, embedder, _ = store
    vs.ensure_collection()
    a = _doc("ignasi", "d1", ["cache memory hierarchy", "the TLB caches translations", "pipeline"])
    b = _doc("anna", "d2", ["TLB TLB TLB"])
    for doc in (a, b):
        vs.replace_document(doc, embedder.embed([c.text for c in doc.chunks]))
    (vector,) = embedder.embed(["what is a TLB"])
    hits = vs.search("ignasi", vector, limit=3, query_text="what is a TLB")
    assert hits[0].payload["text"] == "the TLB caches translations"
    assert {h.payload["user_id"] for h in hits} == {"ignasi"}
    assert all(-1.0 <= h.score <= 1.0 for h in hits)  # cosine, not fusion scores
