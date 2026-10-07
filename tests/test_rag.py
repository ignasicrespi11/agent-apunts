"""rag.py: abstention gates, prompt, citations and the query log (D32, D33)."""

import json

import pytest
from qdrant_client import QdrantClient

from agent_apunts.ingestion.chunk import chunk_all
from agent_apunts.ingestion.extract import extract_all
from agent_apunts.ingestion.index import index_all
from agent_apunts.ingestion.manifest import Manifest
from agent_apunts.ingestion.register import register_source
from agent_apunts.rag import NOT_FOUND, SYSTEM_PROMPT, ask, log_answer, parse_citations
from agent_apunts.store import VectorStore
from tests.fakes import HashEmbedder, ScriptedLLM
from tests.pdf_factory import make_pdf

USER = "ignasi"


def _with_min_score(settings, value):
    return settings.model_copy(
        update={"retrieval": settings.retrieval.model_copy(update={"min_score": value})}
    )


@pytest.fixture
def indexed(settings):
    root = settings.source("testing").root
    make_pdf(root / "disseny_software" / "theory" / "patrons.pdf", ["slide", "image"])
    make_pdf(root / "informacio_i_seguretat" / "exams" / "IS2425-P1.pdf", ["a4"])
    embedder = HashEmbedder()
    store = VectorStore(QdrantClient(":memory:"), "apunts", embedder.model, embedder.dimension)
    with Manifest(settings.paths.manifest) as m:
        register_source(m, USER, settings.source("testing"), settings)
        extract_all(m, USER, settings)
        chunk_all(m, USER, settings)
        index_all(m, USER, settings, embedder, store)
    return embedder, store


def _ask(question, settings, indexed, llm, **kw):
    embedder, store = indexed
    return ask(question, USER, settings, embedder, store, llm, **kw)


def test_answer_with_citations(settings, indexed):
    llm = ScriptedLLM("El patró observador notifica els canvis d'estat [1].")
    answer = _ask("Què fa el patró observador?", _with_min_score(settings, 0.0), indexed, llm)
    assert not answer.abstained and answer.cited == [1] and not answer.uncited
    assert answer.sources[0].rel_path == "disseny_software/theory/patrons.pdf"
    assert answer.sources[0].page == 1
    system, user = llm.prompts[0]
    assert system == SYSTEM_PROMPT
    assert user.startswith("Sources:\n\n[1] Disseny de Software · patrons")
    assert user.endswith("Question: Què fa el patró observador?")


def test_low_score_abstains_without_calling_the_llm(settings, indexed):
    llm = ScriptedLLM()  # would fail if called: no answers scripted
    answer = _ask("Què és un patró observador?", _with_min_score(settings, 0.99), indexed, llm)
    assert answer.abstained and answer.reason == "low_score"
    assert answer.answer == "No ho he trobat als teus apunts."  # question's language
    assert llm.prompts == []


def test_model_not_found_abstains(settings, indexed):
    llm = ScriptedLLM(NOT_FOUND)
    answer = _ask("What is a TLB?", _with_min_score(settings, 0.0), indexed, llm)
    assert answer.abstained and answer.reason == "not_found" and answer.cited == []
    assert answer.answer == "I couldn't find this in your notes."


def test_answer_without_valid_citation_is_flagged(settings, indexed):
    llm = ScriptedLLM("Observer notifies dependents [7].")  # [7] doesn't exist
    answer = _ask("observer pattern", _with_min_score(settings, 0.0), indexed, llm)
    assert not answer.abstained and answer.uncited and answer.cited == []


def test_filters_reach_qdrant(settings, indexed):
    llm = ScriptedLLM("Resposta [1].")
    answer = _ask(
        "memoria caché", _with_min_score(settings, 0.0), indexed, llm, subject="disseny_software"
    )
    assert answer.filters == {"subject": "disseny_software"}
    assert all(s.subject == "disseny_software" for s in answer.sources)


def test_other_users_notes_are_never_used(settings, indexed):
    embedder, store = indexed
    llm = ScriptedLLM()
    answer = ask("patró observador", "anna", _with_min_score(settings, 0.0), embedder, store, llm)
    assert answer.abstained and answer.reason == "no_results" and llm.prompts == []


@pytest.mark.parametrize(
    "text,n,expected",
    [
        ("A [1]. B [3][1].", 3, [1, 3]),
        ("A [1, 2].", 3, [1, 2]),
        ("A [4] and [0].", 3, []),
        ("No citations.", 3, []),
        ("Array a[i] in code [2].", 3, [2]),
    ],
)
def test_parse_citations(text, n, expected):
    assert parse_citations(text, n) == expected


def test_log_has_user_id_and_appends(settings, indexed, tmp_path):
    llm = ScriptedLLM("Resposta [1].", "Altra [1].")
    for question in ("patró observador", "observador"):
        answer = _ask(question, _with_min_score(settings, 0.0), indexed, llm)
        path = log_answer(answer, tmp_path / "logs")
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert all(line["user_id"] == USER and line["timestamp"] for line in lines)
    assert lines[0]["sources"][0]["chunk_id"]
