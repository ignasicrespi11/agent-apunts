"""Stage 1, REGISTER: give every file a content-hash ID and record it in the manifest (D12).

Cheap and safe to re-run: unchanged files are skipped, moved/renamed files keep their ID (and every
completed stage), exact duplicates are reported instead of being processed twice.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from agent_apunts.config import Settings, Source
from agent_apunts.ingestion.discovery import find_files
from agent_apunts.ingestion.loaders import supported_extensions
from agent_apunts.ingestion.manifest import DocumentRecord, Manifest
from agent_apunts.metadata import DocumentMetadata, metadata_from_path


def file_hash(path: Path) -> str:
    """SHA-256 of the file bytes, read in 1 MiB blocks so big PDFs don't load into memory at once.

    Same bytes -> same ID, whatever the filename or folder: this is what makes re-ingestion
    idempotent and renames free. SHA-256 because accidental collisions are practically impossible.
    """
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class RegisterReport:
    new: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    moved: list[tuple[str, str]] = field(default_factory=list)  # (old rel_path, new rel_path)
    duplicates: list[tuple[str, str]] = field(default_factory=list)  # (skipped, kept)
    missing: list[str] = field(default_factory=list)  # in the manifest, content no longer found
    errors: list[tuple[str, str]] = field(default_factory=list)  # (rel_path, reason)


def _metadata(path: Path, source: Source, settings: Settings) -> DocumentMetadata | None:
    meta = metadata_from_path(path, source.root, settings)  # raises on wrong folder names
    if meta is None and source.labelled:
        raise ValueError("labelled source: file must be in <subject>/<doc_type>/ folders")
    return meta


def register_source(
    manifest: Manifest, user_id: str, source: Source, settings: Settings
) -> RegisterReport:
    report = RegisterReport()
    seen: dict[str, str] = {}  # doc_id -> rel_path, within this run

    for path in find_files(source.root, supported_extensions()):
        rel_path = path.relative_to(source.root).as_posix()
        try:
            meta = _metadata(path, source, settings)
            doc_id = file_hash(path)
        except (ValueError, OSError) as e:
            report.errors.append((rel_path, str(e)))
            continue

        if doc_id in seen:
            report.duplicates.append((rel_path, seen[doc_id]))
            continue
        seen[doc_id] = rel_path

        existing = manifest.get(user_id, doc_id)
        if existing is None:
            manifest.add(user_id, doc_id, source.name, rel_path, path.stat().st_size, meta)
            report.new.append(rel_path)
        elif existing.source != source.name and _still_exists(existing, settings):
            # Same content already registered from the other source (e.g. a PDF that is both
            # in the inbox and in the labelled set): keep the first one.
            report.duplicates.append((rel_path, f"{existing.source}/{existing.rel_path}"))
        elif (existing.source, existing.rel_path, existing.metadata) != (
            source.name,
            rel_path,
            meta,
        ):
            manifest.update_location(user_id, doc_id, source.name, rel_path, meta)
            report.moved.append((existing.rel_path, rel_path))
        else:
            report.unchanged.append(rel_path)

    # No file in this source has this content any more: deleted, or edited (new content = new ID).
    # Only reported: removing a document from the index is a deliberate action (later: --prune).
    for record in manifest.documents(user_id, source.name):
        if record.doc_id not in seen:
            report.missing.append(record.rel_path)
    return report


def _still_exists(record: DocumentRecord, settings: Settings) -> bool:
    return (settings.source(record.source).root / record.rel_path).is_file()
