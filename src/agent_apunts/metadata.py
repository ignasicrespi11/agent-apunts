"""Document metadata: the one Pydantic model every document carries (CLAUDE.md, D5).

The same model is filled from three places over the project's life: the folder structure (now),
the auto-detector (D18, week 4) and the upload form (phase 2). Validation always happens here.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

if TYPE_CHECKING:
    from agent_apunts.config import Settings


class DocType(StrEnum):
    """Kind of document. The value is also the folder name in <root>/<subject>/<doc_type>/."""

    THEORY = "theory"
    LABS = "labs"
    EXERCISES = "exercises"
    EXAMS = "exams"


def _check_academic_year(value: str) -> str:
    start, end = value.split("-")
    if (int(start) + 1) % 100 != int(end):
        raise ValueError(f"academic year {value!r}: years must be consecutive (e.g. 2024-25)")
    return value


# "2024-25": the format UAB uses. Pattern checks the shape, the validator checks 24 -> 25.
AcademicYear = Annotated[
    str,
    StringConstraints(pattern=r"^\d{4}-\d{2}$"),
    AfterValidator(_check_academic_year),
]

# Folder-safe identifier: lowercase letters, digits, underscores ("disseny_software").
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]+$")]


class DocumentMetadata(BaseModel):
    """What a document *is about*. Who owns it (user_id) is stored next to it, not inside it,
    because the same PDF can belong to several users while its subject stays the same."""

    # frozen: metadata can't be changed by accident after validation.
    # extra="forbid": a misspelled field ("profesor") is an error instead of being silently dropped.
    model_config = ConfigDict(frozen=True, extra="forbid")

    university: str
    degree: str
    subject: Slug
    doc_type: DocType
    taken_in: AcademicYear  # year the user took the subject (from sources.yaml)
    academic_year: AcademicYear | None = None  # year of the document itself, if known
    professor: str | None = None


class UnknownSubjectError(ValueError):
    """A folder name is not a subject in config/sources.yaml."""


# Explicit forms: 2024-25, 2024_25, 2024/25, 2024-2025.
_YEAR_EXPLICIT = re.compile(r"(?<!\d)(20\d{2})[-_/](\d{2}|20\d{2})(?!\d)")
# Compact form used in exam filenames: IS2425-Parcial1 -> 2024-25. Only accepted when the two
# pairs are consecutive (24 -> 25), which rules out most other 4-digit numbers.
_YEAR_COMPACT = re.compile(r"(?<!\d)(\d{2})(\d{2})(?!\d)")


def year_from_filename(filename: str) -> str | None:
    """Best-effort document year from a filename; None if there is no unambiguous year."""
    if m := _YEAR_EXPLICIT.search(filename):
        start, end = int(m.group(1)), int(m.group(2)) % 100
        if (start + 1) % 100 == end:
            return f"{start}-{end:02d}"
    for m in _YEAR_COMPACT.finditer(filename):
        first, second = int(m.group(1)), int(m.group(2))
        if 10 <= first <= 50 and (first + 1) % 100 == second:
            return f"20{first:02d}-{second:02d}"
    return None


def metadata_from_path(path: Path, root: Path, settings: Settings) -> DocumentMetadata | None:
    """Metadata from the folder hint <root>/<subject>/<doc_type>/.../<file> (D5, D18: folder wins).

    Returns None when the file is not inside such folders (it waits for auto-detection, D18).
    Raises if the folders exist but are wrong: a typo in a folder name should be fixed, not guessed.
    """
    parts = path.relative_to(root).parts
    if len(parts) < 3:
        return None
    subject_slug, doc_type_name = parts[0], parts[1]

    subject = settings.subjects.get(subject_slug)
    if subject is None:
        known = ", ".join(sorted(settings.subjects)) or "(none)"
        raise UnknownSubjectError(
            f"folder {subject_slug!r} is not in config/sources.yaml (known: {known})"
        )
    try:
        doc_type = DocType(doc_type_name)
    except ValueError:
        allowed = ", ".join(t.value for t in DocType)
        raise ValueError(f"folder {doc_type_name!r} is not a doc_type ({allowed})") from None

    return DocumentMetadata(
        university=settings.user.university,
        degree=settings.user.degree,
        subject=subject_slug,
        doc_type=doc_type,
        taken_in=subject.taken_in,
        academic_year=year_from_filename(path.name),
        professor=subject.professor,
    )
