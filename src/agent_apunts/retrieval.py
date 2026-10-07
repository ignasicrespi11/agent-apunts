"""Retrieval: question -> the most similar chunks of THIS user's notes.

The question is embedded with the same model as the chunks (checked by the store), then Qdrant
returns the nearest chunks with the user/subject filter applied inside the query. Deciding whether
the hits are relevant enough to answer (abstention threshold) is the RAG step's job (week 4).
"""

from agent_apunts.embeddings import Embedder
from agent_apunts.store import Hit, VectorStore


def search(
    question: str,
    user_id: str,
    embedder: Embedder,
    store: VectorStore,
    limit: int = 5,
    subject: str | None = None,
    doc_type: str | None = None,
    hybrid: bool = False,
) -> list[Hit]:
    (vector,) = embedder.embed([question])
    return store.search(
        user_id,
        vector,
        limit=limit,
        subject=subject,
        doc_type=doc_type,
        query_text=question if hybrid else None,  # keywords too (D37)
    )
