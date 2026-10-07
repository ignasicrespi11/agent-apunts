"""detection.py: subject by nearest centroid, doc_type by keywords, measured leave-one-out (D36)."""

import numpy as np
import pymupdf
import pytest

from agent_apunts import detection as det
from agent_apunts.metadata import DocType

VOCAB = {
    "disseny_software": "patró observer creator factory singleton classe herència interfície UML",
    "arquitectura_computadors": "memòria cache pipeline registre processador instrucció bus TLB",
    "informacio_i_seguretat": "xifratge clau pública hash signatura certificat atac contrasenya",
}


def text_pdf(path, text, pages=3):
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_textbox(pymupdf.Rect(50, 50, 545, 800), f"{text} pàgina {i}. " * 8, fontsize=11)
    doc.save(path)
    doc.close()
    return path


@pytest.mark.parametrize(
    "filename,first_page,expected,source",
    [
        ("IS2526-ExamenFinal.pdf", "", DocType.EXAMS, "filename"),
        ("IS2425-Parcial1.pdf", "", DocType.EXAMS, "filename"),
        ("Pràctica_2_enunciat.pdf", "", DocType.LABS, "filename"),
        ("Llibre_de_Problemes_IS.pdf", "", DocType.EXERCISES, "filename"),
        ("slides_grasp.pdf", "", DocType.THEORY, "filename"),
        ("doc_0042.pdf", "Examen final de Disseny de Software", DocType.EXAMS, "first_page"),
        ("doc_0043.pdf", "Benvinguts a l'assignatura", DocType.THEORY, "default"),
    ],
)
def test_guess_doc_type(filename, first_page, expected, source):
    assert det.guess_doc_type(filename, first_page) == (expected, source)


def test_sample_texts_spreads_over_the_document():
    texts = [f"t{i}" for i in range(10)]
    assert det.sample_texts(texts, 3) == ["t0", "t4", "t9"]  # start, middle (4.5 -> 4), end
    assert det.sample_texts(texts[:2], 6) == ["t0", "t1"]


def test_margin_decides_confidence():
    centroids = {"a": np.array([1.0, 0.0]), "b": np.array([0.0, 1.0])}
    from agent_apunts.ingestion.manifest import DocumentRecord

    record = DocumentRecord(
        user_id="u",
        doc_id="d",
        source="apunts",
        rel_path="x.pdf",
        size_bytes=1,
        metadata=None,
        registered_at="",
        updated_at="",
    )
    clear = det.detect(record, det._unit(np.array([0.9, 0.1])), "", centroids, 0.05)
    torn = det.detect(record, det._unit(np.array([0.5, 0.49])), "", centroids, 0.05)
    assert clear.subject == "a" and clear.confident
    assert torn.subject == "a" and not torn.confident


def test_leave_one_out_and_inbox_detection(settings):
    from agent_apunts.ingestion.chunk import chunk_all, chunks_path, read_chunks
    from agent_apunts.ingestion.extract import extract_all
    from agent_apunts.ingestion.manifest import Manifest
    from agent_apunts.ingestion.register import register_source
    from tests.fakes import HashEmbedder

    testing = settings.source("testing").root
    for subject, words in VOCAB.items():
        for n in range(3):
            text_pdf(testing / subject / "theory" / f"tema{n}.pdf", f"{words} {subject} {n}")
    inbox = settings.source("apunts").root
    text_pdf(inbox / "Examen_final.pdf", VOCAB["arquitectura_computadors"] + " exercici")

    with Manifest(settings.paths.manifest) as m:
        for src in settings.sources:
            register_source(m, "ignasi", src, settings)
        extract_all(m, "ignasi", settings)
        chunk_all(m, "ignasi", settings)
        records = m.documents("ignasi")
    texts = {
        r.doc_id: det.sample_texts(
            [c.text for c in read_chunks(chunks_path(settings, "ignasi", r.doc_id)).chunks], 6
        )
        for r in records
    }
    vectors = det.document_vectors(texts, HashEmbedder(dimension=256))
    labelled = [r for r in records if r.metadata]

    result = det.evaluate_leave_one_out(labelled, vectors, {}, min_margin=0.05)
    assert result.documents == 9 and result.subject_correct == 9
    assert result.doc_type_correct == 9  # "tema" -> theory

    (inbox_doc,) = [r for r in records if r.metadata is None]
    centroids = det.subject_centroids(vectors, {r.doc_id: r.metadata.subject for r in labelled})
    guess = det.detect(inbox_doc, vectors[inbox_doc.doc_id], "", centroids, 0.05)
    assert guess.subject == "arquitectura_computadors" and guess.confident
    assert guess.doc_type is DocType.EXAMS and guess.doc_type_source == "filename"
