"""evaluation.py: golden set validation and retrieval metrics (D34)."""

from pathlib import Path

import pytest
from qdrant_client import QdrantClient

from agent_apunts import evaluation as ev
from agent_apunts.store import Hit, VectorStore
from tests.fakes import HashEmbedder

REPO = Path(__file__).resolve().parents[1]


def _hit(path, page, score=0.5):
    return Hit(chunk_id=f"{path}{page}", score=score, payload={"rel_path": path, "page": page})


def _result(rank, answerable=True, score=0.6, language="ca", subject="ds", tags=()):
    return ev.QuestionResult(
        id=f"q{rank}{score}",
        language=language,
        subject=subject,
        tags=list(tags),
        answerable=answerable,
        rank=rank,
        best_score=score,
        top=[],
    )


def test_example_golden_set_is_valid():
    golden = ev.load_golden(REPO / "eval" / "golden.example.yaml")
    assert any(not q.answerable for q in golden.questions)
    assert {q.language for q in golden.questions} == {"ca", "es", "en"}


def test_invalid_golden_sets_are_rejected(tmp_path):
    path = tmp_path / "g.yaml"
    path.write_text("questions:\n  - {id: a, question: x, language: ca}\n")
    with pytest.raises(ValueError, match="need at least one expected"):
        ev.load_golden(path)
    path.write_text(
        "questions:\n"
        "  - {id: a, question: x, language: ca, answerable: false}\n"
        "  - {id: a, question: y, language: ca, answerable: false}\n"
    )
    with pytest.raises(ValueError, match="duplicate"):
        ev.load_golden(path)
    path.write_text("questions:\n  - {id: a, question: x, language: ca, answerabel: false}\n")
    with pytest.raises(ValueError):  # typo in a field name
        ev.load_golden(path)


def test_first_correct_rank_by_document_and_page():
    hits = [_hit("a.pdf", 1), _hit("b.pdf", 7), _hit("b.pdf", 3)]
    assert ev.first_correct_rank(hits, [ev.Expected(document="b.pdf", pages=[3])]) == 3
    assert ev.first_correct_rank(hits, [ev.Expected(document="b.pdf")]) == 2  # any page
    assert ev.first_correct_rank(hits, [ev.Expected(document="c.pdf")]) is None


def test_metrics_hit_at_k_and_mrr():
    results = [_result(1), _result(2), _result(None), _result(5), _result(None, answerable=False)]
    m = ev.metrics(results, (1, 3, 5))
    assert m.questions == 4  # unanswerable questions don't count for retrieval
    assert m.hit_at == {1: 0.25, 3: 0.5, 5: 0.75}
    assert m.mrr == round((1 + 1 / 2 + 0 + 1 / 5) / 4, 3)


def test_breakdown_by_language_subject_and_tag():
    results = [
        _result(1, language="ca", tags=["code-image"]),
        _result(None, language="en", tags=["code-image", "definition"]),
    ]
    groups = ev.breakdown(results, (1,))
    assert groups["language"]["ca"].hit_at[1] == 1.0
    assert groups["language"]["en"].hit_at[1] == 0.0
    assert groups["tag"]["code-image"].questions == 2


def test_abstention_rates_and_sweep():
    results = [
        _result(1, score=0.70),
        _result(1, score=0.40),  # answerable but weak: would be wrongly refused at 0.45
        _result(None, answerable=False, score=0.30),
        _result(None, answerable=False, score=0.50),
    ]
    gate = ev.abstention(results, 0.45)
    assert (gate.correct_abstention, gate.false_abstention, gate.balanced) == (0.5, 0.5, 0.5)
    rows = ev.sweep(results)
    assert rows[0].threshold == 0.2 and rows[-1].threshold == 0.8
    assert max(rows, key=lambda r: r.balanced).balanced == 0.75


def test_run_questions_end_to_end(tmp_path):
    embedder = HashEmbedder()
    store = VectorStore(QdrantClient(":memory:"), "t", embedder.model, embedder.dimension)
    store.ensure_collection()
    from agent_apunts.ingestion.chunk import Chunk, ChunkedDocument

    texts = ["observer notifies registered observers", "cache memory hierarchy levels"]
    doc = ChunkedDocument(
        user_id="ignasi",
        doc_id="d",
        source="testing",
        rel_path="ds/theory/patterns.pdf",
        metadata=None,
        chunker="t",
        removed=[],
        chunks=[
            Chunk(
                chunk_id=f"00000000-0000-5000-8000-00000000000{i}",
                index=i,
                page=i + 1,
                part=0,
                title=None,
                header="h",
                text=t,
                word_count=4,
                language="en",
            )
            for i, t in enumerate(texts)
        ],
    )
    store.replace_document(doc, embedder.embed([c.text for c in doc.chunks]))
    golden = ev.GoldenSet(
        questions=[
            ev.GoldenQuestion(
                id="q1",
                question="who notifies observers",
                language="en",
                expected=[ev.Expected(document="ds/theory/patterns.pdf", pages=[1])],
            )
        ]
    )
    (result,) = ev.run_questions(golden, "ignasi", embedder, store, k=2)
    assert result.rank == 1 and result.best_score is not None
    assert result.top[0].startswith("ds/theory/patterns.pdf p.1")


def _answer(answerable, abstained, cited=(), cited_expected=0, uncited=False):
    return ev.AnswerResult(
        id="q",
        answerable=answerable,
        abstained=abstained,
        reason=None,
        cited=list(cited),
        cited_expected=cited_expected,
        uncited=uncited,
        latency_ms=2000,
        answer="",
    )


def test_answer_metrics():
    results = [
        _answer(True, False, cited=["a p.1", "b p.2"], cited_expected=1),  # good, 1 of 2 right
        _answer(True, False, cited=["c p.9"], cited_expected=0),  # cites the wrong page
        _answer(True, True),  # false abstention
        _answer(False, True),  # correct abstention
        _answer(False, False, uncited=True),  # missed abstention, and uncited
    ]
    m = ev.answer_metrics(results)
    assert m.abstention_accuracy == round(3 / 5, 3)
    assert (m.false_abstentions, m.missed_abstentions) == (1, 1)
    assert m.citation_hit == 0.5  # 1 of the 2 answered answerable questions
    assert m.citation_precision == round(1 / 3, 3)
    assert m.uncited == 1 and m.mean_latency_s == 2.0
