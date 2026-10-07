"""PRUNE: forget documents whose content no longer exists in any source folder (D35).

A deleted PDF, or an edited one (new content = new doc_id, D12), leaves its old version behind:
manifest row, processed JSON, chunks, thumbnails and Qdrant points. Without pruning, search keeps
citing a file (or an old version) that isn't there any more. Only derived data is deleted; the
PDFs themselves are never touched, and everything removed can be rebuilt by `ingest`.

Deleting is only safe on evidence, so orphans are decided from a `register` run over ALL sources:
a document is an orphan only if its source folder was there and scanned, its content (doc_id) was
seen nowhere, and its file did not fail to read. An unmounted OneDrive folder or a file locked
mid-sync therefore never wipes anything.
"""

import shutil
from dataclasses import dataclass, field

from agent_apunts.config import Settings
from agent_apunts.ingestion.chunk import chunks_path
from agent_apunts.ingestion.extract import processed_path
from agent_apunts.ingestion.manifest import DocumentRecord, Manifest
from agent_apunts.ingestion.register import RegisterReport
from agent_apunts.store import VectorStore


@dataclass
class Orphans:
    documents: list[DocumentRecord] = field(default_factory=list)
    skipped_sources: list[str] = field(default_factory=list)  # folder missing: nothing decided
    blocked_sources: list[str] = field(default_factory=list)  # unreadable files: nothing decided


def find_orphans(
    manifest: Manifest, user_id: str, settings: Settings, scans: dict[str, RegisterReport]
) -> Orphans:
    """`scans`: this run's register report per source name (every existing source folder)."""
    for source in settings.sources:
        if source.root.is_dir() and source.name not in scans:
            # A file could have moved into an unscanned folder: we can't tell it from a deletion.
            raise ValueError(f"register every source before pruning (missing: {source.name})")
    seen = set().union(*(scan.seen for scan in scans.values()))

    result = Orphans()
    for name, scan in scans.items():
        if not scan.scanned:
            result.skipped_sources.append(name)
        elif scan.unreadable:
            # A file we couldn't read might be the moved copy of any document: its content is
            # unknown, so this source can't prove anything is gone until the error is fixed.
            result.blocked_sources.append(name)
    for record in manifest.documents(user_id):
        scan = scans.get(record.source)
        if scan is None or not scan.scanned or scan.unreadable:
            continue  # folder missing (unmounted drive) or unreadable files: keep everything
        if record.doc_id in seen:
            continue
        result.documents.append(record)
    return result


def remove(
    manifest: Manifest,
    user_id: str,
    settings: Settings,
    store: VectorStore,
    orphans: list[DocumentRecord],
) -> None:
    for record in orphans:
        # Qdrant first: if it fails, nothing local is deleted and the next run retries cleanly.
        store.delete_document(user_id, record.doc_id)
        processed_path(settings, user_id, record.doc_id).unlink(missing_ok=True)
        chunks_path(settings, user_id, record.doc_id).unlink(missing_ok=True)
        thumbnails = settings.paths.thumbnails_dir / user_id / record.doc_id
        if thumbnails.is_dir():
            shutil.rmtree(thumbnails)
        manifest.delete(user_id, record.doc_id)
