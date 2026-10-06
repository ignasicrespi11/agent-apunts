"""Stage 2, EXTRACT: registered document -> data/processed/<user_id>/<doc_id>.json (D11).

The loader reads the format; this stage adds what is the same for every format (language per page,
"mostly image" flag) and writes one JSON per document that you can open and read (D11: inspectable).
Later stages (clean, chunk, index) read this JSON and never the PDF again.
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from agent_apunts.config import Settings
from agent_apunts.ingestion.language import detect_language
from agent_apunts.ingestion.loaders import Loader, loader_for
from agent_apunts.ingestion.manifest import DocumentRecord, Manifest
from agent_apunts.metadata import DocumentMetadata

STAGE = "extract"


class ExtractedPage(BaseModel):
    number: int  # 1-based
    width: float  # points
    height: float
    title: str | None
    text: str
    char_count: int
    language: str | None  # None: too little text or unsure (D16)
    image_count: int
    mostly_image: bool  # little text: the content is in images/diagrams (D14)
    thumbnail: str | None  # relative to data_dir, '/'-separated


class ExtractedDocument(BaseModel):
    user_id: str
    doc_id: str
    source: str
    rel_path: str
    metadata: DocumentMetadata | None
    extractor: str  # e.g. 'pymupdf-2'
    languages: list[str]  # page languages, most frequent first
    pages: list[ExtractedPage]


def loader_version(loader: Loader) -> str:
    return f"{loader.name}-{loader.version}"


def processed_path(settings: Settings, user_id: str, doc_id: str) -> Path:
    # Per-user folders: deleting a user's data is deleting their folders.
    return settings.paths.processed_dir / user_id / f"{doc_id}.json"


def extract_document(record: DocumentRecord, settings: Settings) -> ExtractedDocument:
    loader = loader_for(Path(record.rel_path))
    if loader is None:
        raise ValueError(f"no loader for {record.rel_path}")
    path = settings.source(record.source).root / record.rel_path
    thumbs = settings.paths.thumbnails_dir / record.user_id / record.doc_id
    ex = settings.extraction

    pages = []
    for raw in loader.load(path, thumbs, ex.thumbnail_width):
        chars = len(raw.text)
        pages.append(
            ExtractedPage(
                number=raw.number,
                width=raw.width,
                height=raw.height,
                title=raw.title,
                text=raw.text,
                char_count=chars,
                language=detect_language(
                    raw.text,
                    tuple(settings.languages),
                    ex.language_min_chars,
                    ex.language_min_confidence,
                ),
                image_count=raw.image_count,
                mostly_image=chars < ex.image_page_max_chars,
                thumbnail=(
                    raw.thumbnail.relative_to(settings.paths.data_dir).as_posix()
                    if raw.thumbnail
                    else None
                ),
            )
        )
    counts = Counter(p.language for p in pages if p.language)
    return ExtractedDocument(
        user_id=record.user_id,
        doc_id=record.doc_id,
        source=record.source,
        rel_path=record.rel_path,
        metadata=record.metadata,
        extractor=loader_version(loader),
        languages=[lang for lang, _ in counts.most_common()],
        pages=pages,
    )


def write_json(doc: ExtractedDocument, path: Path) -> None:
    """Write to a temporary file, then rename: a crash mid-write never leaves a half JSON
    (rename is atomic), so 'stage done' in the manifest always means a complete file exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> ExtractedDocument:
    return ExtractedDocument.model_validate(json.loads(path.read_text(encoding="utf-8")))


def is_up_to_date(manifest: Manifest, record: DocumentRecord, settings: Settings) -> bool:
    """Done before with the same loader version, and the output file is still there."""
    loader = loader_for(Path(record.rel_path))
    done = manifest.stage(record.user_id, record.doc_id, STAGE)
    return (
        loader is not None
        and done is not None
        and done.version == loader_version(loader)
        and processed_path(settings, record.user_id, record.doc_id).is_file()
    )


@dataclass
class ExtractReport:
    extracted: list[str] = field(default_factory=list)
    up_to_date: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)  # (rel_path, reason)
    # Pages to look at: no text at all (image-only or scanned -> D14 / OCR later).
    empty_pages: list[tuple[str, int]] = field(default_factory=list)  # (rel_path, page)
    pages: int = 0


def extract_all(
    manifest: Manifest, user_id: str, settings: Settings, force: bool = False
) -> ExtractReport:
    """Extract every registered document of `user_id` that isn't up to date (or all with force)."""
    report = ExtractReport()
    for record in manifest.documents(user_id):
        if not force and is_up_to_date(manifest, record, settings):
            report.up_to_date.append(record.rel_path)
            continue
        try:
            doc = extract_document(record, settings)
        except Exception as e:  # noqa: BLE001 (one bad file must not stop the whole run)
            report.errors.append((record.rel_path, f"{type(e).__name__}: {e}"))
            continue
        out = processed_path(settings, user_id, record.doc_id)
        write_json(doc, out)
        manifest.mark_done(
            user_id,
            record.doc_id,
            STAGE,
            doc.extractor,
            out.relative_to(settings.paths.data_dir).as_posix(),
        )
        report.extracted.append(record.rel_path)
        report.pages += len(doc.pages)
        report.empty_pages += [(record.rel_path, p.number) for p in doc.pages if not p.char_count]
    return report
