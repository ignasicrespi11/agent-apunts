"""The vector store: chunks + their vectors in Qdrant (D2).

One collection for everyone; every point carries `user_id` in its payload, indexed as the tenant
key, and every search filters on it INSIDE the Qdrant query (CLAUDE.md: never after retrieval, or a
user could see another user's notes and top-k would be wrong). The collection remembers which
embedding model built it (D28) and refuses vectors or queries from a different one.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from qdrant_client import QdrantClient, models

from agent_apunts.config import Settings
from agent_apunts.ingestion.chunk import Chunk, ChunkedDocument

# Payload fields with an index: filtering on them stays fast as the collection grows.
_KEYWORD_INDEXES = ("subject", "doc_type", "doc_id", "language")


class StoreError(RuntimeError):
    """Qdrant is unreachable or the collection doesn't match the settings."""


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    score: float  # cosine similarity: higher = closer in meaning
    payload: dict


def _payload(doc: ChunkedDocument, chunk: Chunk) -> dict:
    meta = doc.metadata.model_dump(mode="json") if doc.metadata else {}
    return {
        "user_id": doc.user_id,
        "doc_id": doc.doc_id,
        "source": doc.source,
        "rel_path": doc.rel_path,
        "chunk_index": chunk.index,
        "page": chunk.page,
        "part": chunk.part,
        "title": chunk.title,
        "header": chunk.header,
        "text": chunk.text,
        "language": chunk.language,
        **meta,  # university, degree, subject, doc_type, taken_in, academic_year, professor
    }


def _user_filter(user_id: str, **equals: str | None) -> models.Filter:
    conditions = [models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id))]
    for key, value in equals.items():
        if value is not None:
            conditions.append(models.FieldCondition(key=key, match=models.MatchValue(value=value)))
    return models.Filter(must=conditions)


class VectorStore:
    def __init__(self, client: QdrantClient, collection: str, model: str, dimension: int) -> None:
        self._client = client
        self.collection = collection
        self.model = model
        self.dimension = dimension

    @classmethod
    def from_settings(cls, settings: Settings) -> "VectorStore":
        client = QdrantClient(url=settings.qdrant.url, timeout=60)
        e = settings.embedding
        return cls(client, settings.qdrant.collection, e.model, e.dimension)

    def ensure_collection(self) -> None:
        """Create the collection (with its indexes) if missing; check its model if it exists."""
        try:
            exists = self._client.collection_exists(self.collection)
        except Exception as e:  # noqa: BLE001 (connection errors come in several types)
            raise StoreError(
                f"cannot reach Qdrant: {e}. Is it running? (`docker compose up -d`)"
            ) from e
        if exists:
            self._check_model()
            return
        self._client.create_collection(
            self.collection,
            vectors_config=models.VectorParams(
                size=self.dimension, distance=models.Distance.COSINE
            ),
            metadata={"embedding_model": self.model, "dimension": self.dimension},
        )
        # is_tenant: Qdrant stores each user's points together, so per-user searches stay fast.
        self._client.create_payload_index(
            self.collection,
            "user_id",
            models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD, is_tenant=True),
        )
        for field in _KEYWORD_INDEXES:
            self._client.create_payload_index(
                self.collection, field, models.PayloadSchemaType.KEYWORD
            )

    def _check_model(self) -> None:
        info = self._client.get_collection(self.collection)
        stored = info.config.metadata or {}
        if (stored.get("embedding_model"), stored.get("dimension")) != (self.model, self.dimension):
            raise StoreError(
                f"collection '{self.collection}' was built with {stored.get('embedding_model')} "
                f"({stored.get('dimension')} dims) but settings use {self.model} "
                f"({self.dimension} dims). Mixing models makes search meaningless: use a new "
                "collection name in settings.yaml (qdrant.collection) and re-index."
            )

    def replace_document(self, doc: ChunkedDocument, vectors: Sequence[Sequence[float]]) -> int:
        """Make the collection hold exactly this document's current chunks. Idempotent (D29):
        unchanged chunks keep their IDs (upsert overwrites), chunks that no longer exist are
        deleted. Upsert first, then delete: there is never a moment with the document missing."""
        if len(vectors) != len(doc.chunks):
            raise ValueError("one vector per chunk expected")
        points = [
            models.PointStruct(id=c.chunk_id, vector=list(v), payload=_payload(doc, c))
            for c, v in zip(doc.chunks, vectors, strict=True)
        ]
        if points:
            self._client.upsert(self.collection, points=points, wait=True)
        stale = _user_filter(doc.user_id, doc_id=doc.doc_id)
        if points:
            stale.must_not = [models.HasIdCondition(has_id=[p.id for p in points])]
        self._client.delete(self.collection, points_selector=models.FilterSelector(filter=stale))
        return len(points)

    def delete_document(self, user_id: str, doc_id: str) -> None:
        """Remove every point of one document of one user (used by prune)."""
        if not self._client.collection_exists(self.collection):
            return
        selector = models.FilterSelector(filter=_user_filter(user_id, doc_id=doc_id))
        self._client.delete(self.collection, points_selector=selector, wait=True)

    def count(self, user_id: str, doc_id: str | None = None) -> int:
        result = self._client.count(
            self.collection, count_filter=_user_filter(user_id, doc_id=doc_id), exact=True
        )
        return result.count

    def search(
        self,
        user_id: str,
        vector: Sequence[float],
        limit: int,
        subject: str | None = None,
        doc_type: str | None = None,
    ) -> list[Hit]:
        """Nearest chunks to `vector` among this user's chunks (filter applied inside Qdrant)."""
        response = self._client.query_points(
            self.collection,
            query=list(vector),
            query_filter=_user_filter(user_id, subject=subject, doc_type=doc_type),
            limit=limit,
            with_payload=True,
        )
        return [Hit(str(p.id), p.score, p.payload or {}) for p in response.points]
