"""Stages 3+4, CLEAN + CHUNK: processed JSON -> data/chunks/<user_id>/<doc_id>.json (D26, D27, D29).

Cleaning runs inside this stage (it has no other consumer); what it removed is written next to the
chunks so it can be audited. Reads only the extract stage's JSON, never the PDF (D11).
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from agent_apunts.config import Settings
from agent_apunts.ingestion.chunking import count_words, split_text
from agent_apunts.ingestion.cleaning import clean_pages
from agent_apunts.ingestion.extract import STAGE as EXTRACT_STAGE
from agent_apunts.ingestion.extract import ExtractedDocument, processed_path, read_json
from agent_apunts.ingestion.manifest import DocumentRecord, Manifest
from agent_apunts.metadata import DocumentMetadata

STAGE = "chunk"
CHUNKER_VERSION = 1  # bump when chunking/cleaning code changes its output
# Fixed namespace for chunk UUIDs: same inputs -> same UUID on every machine, forever.
_CHUNK_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/ignasicrespi11/agent-apunts")


class Chunk(BaseModel):
    chunk_id: str  # UUIDv5, also the Qdrant point ID (D29)
    index: int  # position in the document, 0-based
    page: int  # 1-based page it comes from (citations)
    part: int  # position within the page, 0-based (dense pages give several parts)
    title: str | None
    header: str  # "subject · document · title or p. N", prepended for embedding only (D26)
    text: str  # cleaned text, shown to the LLM and the user
    word_count: int
    language: str | None

    @property
    def embedding_text(self) -> str:
        return f"{self.header}\n\n{self.text}"


class RemovedLine(BaseModel):
    text: str
    count: int


class ChunkedDocument(BaseModel):
    user_id: str
    doc_id: str
    source: str
    rel_path: str
    metadata: DocumentMetadata | None
    chunker: str  # version string of everything that shaped this output
    removed: list[RemovedLine]  # boilerplate removed by cleaning, most frequent first (D27)
    chunks: list[Chunk]


def chunk_id(user_id: str, doc_id: str, index: int, text: str) -> str:
    return str(uuid.uuid5(_CHUNK_NAMESPACE, f"{user_id}|{doc_id}|{index}|{text}"))


def chunker_version(settings: Settings, extractor: str, record: DocumentRecord) -> str:
    """Identifies everything that determines the chunks: code version, cleaning/chunking settings,
    the extraction they read, and where the document is and what it is (the header shows the
    subject and file name). Change any of them and the document is re-chunked."""
    params = json.dumps(
        [
            settings.cleaning.model_dump(),
            settings.chunking.model_dump(),
            record.source,
            record.rel_path,
            record.metadata.model_dump(mode="json") if record.metadata else None,
            _subject_name(record, settings),  # shown in the header: renaming it re-chunks
        ],
        sort_keys=True,
    )
    digest = hashlib.sha256(params.encode()).hexdigest()[:8]
    return f"chunker-{CHUNKER_VERSION}:{digest}:{extractor}"


def chunks_path(settings: Settings, user_id: str, doc_id: str) -> Path:
    return settings.paths.chunks_dir / user_id / f"{doc_id}.json"


def _document_label(rel_path: str) -> str:
    # "disseny_software/theory/slides_grasp.pdf" -> "slides grasp": words help the embedding.
    return Path(rel_path).stem.replace("_", " ").replace("-", " ")


def _subject_name(record: DocumentRecord, settings: Settings) -> str | None:
    if record.metadata and record.metadata.subject in settings.subjects:
        return settings.subjects[record.metadata.subject].name
    return None


def _header(record: DocumentRecord, settings: Settings, title: str | None, page: int) -> str:
    parts = []
    if subject := _subject_name(record, settings):
        parts.append(subject)
    parts.append(_document_label(record.rel_path))
    parts.append(title or f"p. {page}")
    return " · ".join(parts)


def chunk_document(
    doc: ExtractedDocument, record: DocumentRecord, settings: Settings
) -> ChunkedDocument:
    """Text comes from the extraction; location and metadata from the manifest record, which is
    the source of truth: a moved or relabelled file keeps its extraction (same content, same
    doc_id) but must get its new path and metadata here and in Qdrant."""
    cl, ch = settings.cleaning, settings.chunking
    cleaned = clean_pages(
        [p.text for p in doc.pages],
        cl.repeated_line_min_share,
        cl.repeated_line_min_pages,
        cl.repeated_line_max_chars,
    )
    chunks: list[Chunk] = []
    for page, text in zip(doc.pages, cleaned.pages, strict=True):
        if count_words(text) < ch.min_words:
            continue  # image-only or blank page: nothing to search (D29)
        for part, piece in enumerate(split_text(text, ch.max_words, ch.target_words)):
            index = len(chunks)
            chunks.append(
                Chunk(
                    chunk_id=chunk_id(doc.user_id, doc.doc_id, index, piece),
                    index=index,
                    page=page.number,
                    part=part,
                    title=page.title,
                    header=_header(record, settings, page.title, page.number),
                    text=piece,
                    word_count=count_words(piece),
                    language=page.language,
                )
            )
    return ChunkedDocument(
        user_id=doc.user_id,
        doc_id=doc.doc_id,
        source=record.source,
        rel_path=record.rel_path,
        metadata=record.metadata,
        chunker=chunker_version(settings, doc.extractor, record),
        removed=[RemovedLine(text=t, count=n) for t, n in cleaned.removed.most_common()],
        chunks=chunks,
    )


def write_chunks(doc: ChunkedDocument, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")  # atomic write, as in extract (D24)
    tmp.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)


def read_chunks(path: Path) -> ChunkedDocument:
    return ChunkedDocument.model_validate(json.loads(path.read_text(encoding="utf-8")))


@dataclass
class ChunkReport:
    chunked: list[str] = field(default_factory=list)
    up_to_date: list[str] = field(default_factory=list)
    not_extracted: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    chunks: int = 0
    removed: dict[str, int] = field(default_factory=dict)  # boilerplate line -> documents


def chunk_all(
    manifest: Manifest, user_id: str, settings: Settings, force: bool = False
) -> ChunkReport:
    report = ChunkReport()
    for record in manifest.documents(user_id):
        extracted = manifest.stage(user_id, record.doc_id, EXTRACT_STAGE)
        source = processed_path(settings, user_id, record.doc_id)
        if extracted is None or not source.is_file():
            report.not_extracted.append(record.rel_path)
            continue
        version = chunker_version(settings, extracted.version, record)
        if not force and _is_up_to_date(manifest, record, settings, version):
            report.up_to_date.append(record.rel_path)
            continue
        try:
            doc = chunk_document(read_json(source), record, settings)
        except Exception as e:  # noqa: BLE001 (one bad document must not stop the run)
            report.errors.append((record.rel_path, f"{type(e).__name__}: {e}"))
            continue
        out = chunks_path(settings, user_id, record.doc_id)
        write_chunks(doc, out)
        manifest.mark_done(
            user_id,
            record.doc_id,
            STAGE,
            doc.chunker,
            out.relative_to(settings.paths.data_dir).as_posix(),
        )
        report.chunked.append(record.rel_path)
        report.chunks += len(doc.chunks)
        for line in doc.removed:
            report.removed[line.text] = report.removed.get(line.text, 0) + 1
    return report


def _is_up_to_date(
    manifest: Manifest, record: DocumentRecord, settings: Settings, version: str
) -> bool:
    done = manifest.stage(record.user_id, record.doc_id, STAGE)
    return (
        done is not None
        and done.version == version
        and chunks_path(settings, record.user_id, record.doc_id).is_file()
    )
