"""metadata.py: DocumentMetadata validation and metadata from the folder hint (D5)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_apunts.metadata import (
    DocType,
    DocumentMetadata,
    UnknownSubjectError,
    metadata_from_path,
    year_from_filename,
)

ROOT = Path("/corpus")

VALID = dict(
    university="UAB",
    degree="Computer Engineering",
    subject="disseny_software",
    doc_type="theory",
    taken_in="2025-26",
)


def test_valid_metadata():
    meta = DocumentMetadata(**VALID)
    assert meta.doc_type is DocType.THEORY
    assert meta.professor is None and meta.academic_year is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("doc_type", "slides"),  # not a DocType
        ("subject", "Disseny Software"),  # not a slug
        ("taken_in", "2025-27"),  # years not consecutive
        ("taken_in", "25-26"),  # wrong shape
    ],
)
def test_invalid_metadata(field, value):
    with pytest.raises(ValidationError):
        DocumentMetadata(**{**VALID, field: value})


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        DocumentMetadata(**VALID, profesor="X")


def test_metadata_is_immutable():
    meta = DocumentMetadata(**VALID)
    with pytest.raises(ValidationError):
        meta.subject = "other"


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("IS2425-Parcial1.pdf", "2024-25"),
        ("examen_2022-23_final.pdf", "2022-23"),
        ("exam 2023-2024.pdf", "2023-24"),
        ("final_2021_22.pdf", "2021-22"),
        ("tema3.pdf", None),
        ("practica_2024.pdf", None),  # a single year is ambiguous
        ("scan_20241005.pdf", None),  # a date is not an academic year
        ("p1234.pdf", None),  # 12 -> 34 not consecutive
    ],
)
def test_year_from_filename(filename, expected):
    assert year_from_filename(filename) == expected


def test_metadata_from_path(settings):
    path = ROOT / "informacio_i_seguretat" / "exams" / "IS2425-Parcial1.pdf"
    meta = metadata_from_path(path, ROOT, settings)
    assert meta == DocumentMetadata(
        university="UAB",
        degree="Computer Engineering",
        subject="informacio_i_seguretat",
        doc_type=DocType.EXAMS,
        taken_in="2025-26",
        academic_year="2024-25",
    )


def test_deeper_folders_are_allowed(settings):
    path = ROOT / "disseny_software" / "labs" / "p1" / "enunciat.pdf"
    assert metadata_from_path(path, ROOT, settings).doc_type is DocType.LABS


def test_unorganised_file_has_no_metadata(settings):
    assert metadata_from_path(ROOT / "loose.pdf", ROOT, settings) is None
    assert metadata_from_path(ROOT / "disseny_software" / "x.pdf", ROOT, settings) is None


def test_unknown_subject_folder(settings):
    with pytest.raises(UnknownSubjectError, match="known: arquitectura_computadors"):
        metadata_from_path(ROOT / "dissenys" / "theory" / "x.pdf", ROOT, settings)


def test_unknown_doc_type_folder(settings):
    with pytest.raises(ValueError, match="slides"):
        metadata_from_path(ROOT / "disseny_software" / "slides" / "x.pdf", ROOT, settings)
