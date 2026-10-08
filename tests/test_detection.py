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


def test_similar_pairs_and_groups():
    v = {
        "a": det._unit(np.array([1.0, 0.0, 0.0])),
        "a2": det._unit(np.array([0.99, 0.05, 0.0])),  # near-duplicate of a
        "a3": det._unit(np.array([0.97, 0.1, 0.05])),  # near-duplicate of a2
        "b": det._unit(np.array([0.0, 1.0, 0.0])),
    }
    pairs = det.similar_pairs(v, 0.95)
    assert [(x, y) for x, y, _ in pairs][0] == ("a", "a2")
    assert all("b" not in (x, y) for x, y, _ in pairs)
    assert det.group_pairs(pairs) == [{"a", "a2", "a3"}]
    assert det.similar_pairs({"a": v["a"]}, 0.5) == []


def test_single_subject_is_never_confident():
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
    centroids = {"only": np.array([1.0, 0.0])}
    guess = det.detect(record, det._unit(np.array([1.0, 0.1])), "", centroids, 0.05)
    assert guess.subject == "only" and guess.margin == 0.0 and not guess.confident


def test_document_vectors_are_cached(tmp_path):
    from tests.fakes import HashEmbedder

    embedder = HashEmbedder()
    cache = tmp_path / "cache.json"
    first = det.document_vectors({"a": ["x y"], "b": ["z w"]}, embedder, cache)
    assert embedder.calls == 1
    again = det.document_vectors({"a": ["x y"], "b": ["z w"]}, embedder, cache)
    assert embedder.calls == 1  # nothing re-embedded
    assert np.allclose(first["a"], again["a"], atol=1e-5)
    det.document_vectors({"a": ["x y"], "b": ["changed"]}, embedder, cache)
    assert embedder.calls == 2  # only the changed document
