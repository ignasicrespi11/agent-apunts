"""Stage 5, INDEX: chunks -> vectors (Embedder) -> Qdrant points (D28, D29).

Incremental like the other stages: a document is re-indexed when its chunks or the embedding model
changed, or when Qdrant lost its points (e.g. the Docker volume was deleted).
"""

from dataclasses import dataclass, field

from agent_apunts.config import Settings
from agent_apunts.embeddings import Embedder, EmbeddingError
from agent_apunts.ingestion.chunk import STAGE as CHUNK_STAGE
from agent_apunts.ingestion.chunk import chunks_path, read_chunks
from agent_apunts.ingestion.manifest import Manifest
from agent_apunts.store import VectorStore

STAGE = "index"


def index_version(chunker: str, embedder: Embedder) -> str:
    return f"{chunker}|{embedder.model}"


@dataclass
class IndexReport:
    indexed: list[str] = field(default_factory=list)
    up_to_date: list[str] = field(default_factory=list)
    not_chunked: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    points: int = 0
    stopped: str | None = None  # set when the embedder fails: every document would fail too


def index_all(
    manifest: Manifest,
    user_id: str,
    settings: Settings,
    embedder: Embedder,
    store: VectorStore,
    force: bool = False,
) -> IndexReport:
    report = IndexReport()
    store.ensure_collection()
    for record in manifest.documents(user_id):
        chunked = manifest.stage(user_id, record.doc_id, CHUNK_STAGE)
        path = chunks_path(settings, user_id, record.doc_id)
        if chunked is None or not path.is_file():
            report.not_chunked.append(record.rel_path)
            continue
        doc = read_chunks(path)
        version = index_version(doc.chunker, embedder)
        done = manifest.stage(user_id, record.doc_id, STAGE)
        if (
            not force
            and done is not None
            and done.version == version
            and store.count(user_id, record.doc_id) == len(doc.chunks)
        ):
            report.up_to_date.append(record.rel_path)
            continue
        try:
            vectors = embedder.embed([c.embedding_text for c in doc.chunks])
            report.points += store.replace_document(doc, vectors)
        except EmbeddingError as e:
            report.stopped = str(e)  # Ollama down or model missing: no point trying the rest
            break
        except Exception as e:  # noqa: BLE001 (one bad document must not stop the run)
            report.errors.append((record.rel_path, f"{type(e).__name__}: {e}"))
            continue
        manifest.mark_done(user_id, record.doc_id, STAGE, version, f"{len(doc.chunks)} points")
        report.indexed.append(record.rel_path)
    return report
