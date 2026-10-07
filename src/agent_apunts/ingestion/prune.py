"""PRUNE: forget documents whose content no longer exists in any source folder (D35).

A deleted PDF, or an edited one (new content = new doc_id, D12), leaves its old version behind:
manifest row, processed JSON, chunks, thumbnails and Qdrant points. Without pruning, search keeps
citing a file (or an old version) that isn't there any more. Only derived data is deleted; the
PDFs themselves are never touched, and everything removed can be rebuilt by `ingest`.
"""

import shutil
from dataclasses import dataclass, field

from agent_apunts.config import Settings
from agent_apunts.ingestion.chunk import chunks_path
from agent_apunts.ingestion.extract import processed_path
from agent_apunts.ingestion.manifest import DocumentRecord, Manifest
from agent_apunts.ingestion.register import file_hash
from agent_apunts.store import VectorStore


def find_orphans(manifest: Manifest, user_id: str, settings: Settings) -> list[DocumentRecord]:
    """Documents whose recorded file is gone or now has different content.

    Run after `register`: a file that only moved has already been given its new location, so
    whatever still points to a missing or changed file has no copy left anywhere.
    """
    orphans = []
    for record in manifest.documents(user_id):
        path = settings.source(record.source).root / record.rel_path
        if not path.is_file() or file_hash(path) != record.doc_id:
            orphans.append(record)
    return orphans


@dataclass
class PruneReport:
    removed: list[str] = field(default_factory=list)  # rel_paths of forgotten documents


def prune(
    manifest: Manifest,
    user_id: str,
    settings: Settings,
    store: VectorStore,
    dry_run: bool = False,
) -> PruneReport:
    report = PruneReport()
    for record in find_orphans(manifest, user_id, settings):
        report.removed.append(record.rel_path)
        if dry_run:
            continue
        # Qdrant first: if it fails, nothing local is deleted and the next run retries cleanly.
        store.delete_document(user_id, record.doc_id)
        processed_path(settings, user_id, record.doc_id).unlink(missing_ok=True)
        chunks_path(settings, user_id, record.doc_id).unlink(missing_ok=True)
        thumbnails = settings.paths.thumbnails_dir / user_id / record.doc_id
        if thumbnails.is_dir():
            shutil.rmtree(thumbnails)
        manifest.delete(user_id, record.doc_id)
    return report
