"""The loader interface: one loader per file format (CLAUDE.md, "ingestion is modular").

A loader only knows its format: it turns a file into raw pages. Everything format-independent
(language detection, the "mostly image" flag, cleaning, chunking) happens in later stages, so a new
format (DOCX, PPTX) only needs a new loader, and every format gets the same treatment afterwards.
"""

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class RawPage(BaseModel):
    """One page (slide, A4 page...) as read from the file, before any processing."""

    model_config = ConfigDict(frozen=True)

    number: int  # 1-based, as the user sees it in a PDF viewer (citations use it)
    width: float  # points (1/72 inch); width > height means landscape (D13)
    height: float
    text: str
    title: str | None  # best guess at the page's heading, if any
    image_count: int  # embedded images on the page
    image_coverage: float = 0.0  # fraction of the page covered by images, 0-1 (D30)
    thumbnail: Path | None  # PNG written by the loader, if it can render pages


class Loader(Protocol):
    """What every loader provides. A Protocol (structural typing): a loader doesn't inherit from
    anything, it just needs these attributes and this method."""

    name: str  # e.g. "pymupdf"
    version: int  # bump when output changes: documents extracted with an older version are redone
    extensions: tuple[str, ...]  # lowercase, with dot: (".pdf",)

    def load(self, path: Path, thumbnails_dir: Path, thumbnail_width: int) -> list[RawPage]:
        """Read `path` and return its pages. Thumbnails (if any) go in `thumbnails_dir`."""
        ...
