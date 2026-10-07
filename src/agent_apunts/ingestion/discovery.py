"""Find the documents to ingest under a source folder. Read-only: originals are never modified."""

from collections.abc import Iterable
from pathlib import Path


def _is_ignored(path: Path, root: Path) -> bool:
    # Hidden files/folders (.git, .DS_Store) and Office/OneDrive lock files (~$name.docx).
    return any(part.startswith((".", "~$")) for part in path.relative_to(root).parts)


def find_files(root: Path, extensions: Iterable[str]) -> list[Path]:
    """All files under `root` whose extension is in `extensions` (e.g. {".pdf"}), case-insensitive.

    Sorted, so every run processes files in the same order (reproducible logs and reports).
    A missing root returns an empty list: an empty inbox is normal, not an error.
    """
    wanted = {ext.lower() for ext in extensions}
    if not root.is_dir():
        return []
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in wanted and not _is_ignored(p, root)
    )
