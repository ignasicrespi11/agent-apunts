"""Stage 5, INDEX: chunks -> vectors (Embedder) -> Qdrant points (D28, D29).

Incremental like the other stages: a document is re-indexed when its chunks or the embedding model
changed, or when Qdrant lost its points (e.g. the Docker volume was deleted).
"""

import hashlib
from dataclasses import dataclass, field

from agent_apunts.config import Settings
from agent_apunts.embeddings import Embedder, EmbeddingError
from agent_apunts.ingestion.chunk import STAGE as CHUNK_STAGE
from agent_apunts.ingestion.chunk import ChunkedDocument, chunks_path, read_chunks
from agent_apunts.ingestion.manifest import Manifest
from agent_apunts.store import VectorStore

STAGE = "index"


def _digest(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:12]


def index_version(doc: ChunkedDocument, embedder: Embedder) -> str:
    """'<vectors>|<payload>': what the stored points depend on, in two independent parts.

    - vectors: the model + the embedded text of every chunk (chunk IDs hash the text, D29; the
      header is embedded too). Identical chunks after a re-extract or re-chunk keep this part,
      so nothing is re-embedded (minutes saved on a CPU).
    - payload: path + metadata (moving a PDF from labs/ to theory/ changes doc_type). If only
      this part changes, the payload is rewritten in one Qdrant call, vectors untouched.
    """
    vectors = _digest([embedder.model] + [f"{c.chunk_id}|{c.header}" for c in doc.chunks])
    meta = doc.metadata.model_dump_json() if doc.metadata else ""
    payload = _digest([doc.source, doc.rel_path, meta])
    return f"{embedder.model}:{vectors}|{payload}"


@dataclass
class IndexReport:
    indexed: list[str] = field(default_factory=list)
    up_to_date: list[str] = field(default_factory=list)
    not_chunked: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    points: int = 0
    payload_only: list[str] = field(default_factory=list)  # moved/relabelled: no re-embedding
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
        version = index_version(doc, embedder)
        done = manifest.stage(user_id, record.doc_id, STAGE)
        if (
            not force
            and done is not None
            and done.version == version
            and store.count(user_id, record.doc_id) == len(doc.chunks)
        ):
            report.up_to_date.append(record.rel_path)
            continue
        if (
            not force
            and done is not None
            and done.version.split("|")[0] == version.split("|")[0]
            and store.count(user_id, record.doc_id) == len(doc.chunks)
        ):
            # Same vectors, new path/metadata: rewrite the payload only.
            try:
                store.update_document_payload(doc)
            except Exception as e:  # noqa: BLE001 (one bad document must not stop the run)
                report.errors.append((record.rel_path, f"{type(e).__name__}: {e}"))
                continue
            manifest.mark_done(user_id, record.doc_id, STAGE, version, done.output)
            report.payload_only.append(record.rel_path)
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
