"""agent.py: tool-using agent with a scripted model (D38). No Ollama, Qdrant in memory."""

import pytest
from qdrant_client import QdrantClient

from agent_apunts.agent import AGENT_SYSTEM_PROMPT, NoteTools, run_agent, tool_schemas
from agent_apunts.ingestion.chunk import chunk_all
from agent_apunts.ingestion.extract import extract_all
from agent_apunts.ingestion.index import index_all
from agent_apunts.ingestion.manifest import Manifest
from agent_apunts.ingestion.register import register_source
from agent_apunts.llm import ToolCall
from agent_apunts.store import VectorStore
from tests.fakes import HashEmbedder, ScriptedChat
from tests.pdf_factory import make_pdf

USER = "ignasi"
SLIDES = "disseny_software/theory/patrons.pdf"


def _low_min_score(settings):
    return settings.model_copy(
        update={"retrieval": settings.retrieval.model_copy(update={"min_score": 0.0})}
    )


@pytest.fixture
def indexed(settings):
    root = settings.source("testing").root
    make_pdf(root / "disseny_software" / "theory" / "patrons.pdf", ["slide", "a4"])
    make_pdf(root / "informacio_i_seguretat" / "exams" / "IS2425-P1.pdf", ["a4"])
    embedder = HashEmbedder()
    store = VectorStore(QdrantClient(":memory:"), "apunts", embedder.model, embedder.dimension)
    with Manifest(settings.paths.manifest) as m:
        for user in (USER, "anna"):  # same files for another user: must never leak
            register_source(m, user, settings.source("testing"), settings)
            extract_all(m, user, settings)
            chunk_all(m, user, settings)
            index_all(m, user, settings, embedder, store)
    return embedder, store


def _run(question, settings, indexed, chat):
    embedder, store = indexed
    return run_agent(question, USER, settings, embedder, store, chat)


def test_search_then_cited_answer(settings, indexed):
    chat = ScriptedChat(
        [("search_notes", {"query": "patró observador", "subject": "disseny_software"})],
        "L'observador notifica els canvis [1].",
    )
    answer = _run("Què fa el patró observador?", _low_min_score(settings), indexed, chat)
    assert answer.mode == "agent" and not answer.abstained
    assert answer.cited == [1] and not answer.uncited
    assert answer.sources[0].rel_path == SLIDES
    assert [s.tool for s in answer.steps] == ["search_notes"]
    assert answer.steps[0].result.startswith("2 sources [1] [2]")
    messages, tools = chat.requests[0]
    assert messages[0]["content"] == AGENT_SYSTEM_PROMPT and tools is not None
    tool_message = chat.requests[1][0][-1]
    assert tool_message["role"] == "tool" and tool_message["content"].startswith("[1] Disseny")


def test_user_id_can_not_be_chosen_by_the_model(settings, indexed):
    embedder, store = indexed
    tools = NoteTools(USER, _low_min_score(settings), embedder, store)
    text, _ = tools.run(ToolCall("search_notes", {"query": "patró", "user_id": "anna"}))
    assert text.startswith("[1]")
    assert {s.chunk_id for s in tools.sources} <= {
        h.chunk_id for h in store.search(USER, embedder.embed(["patró"])[0], limit=50)
    }
    assert "user_id" not in str(tool_schemas(settings))


def test_bad_arguments_come_back_as_text_and_the_loop_goes_on(settings, indexed):
    chat = ScriptedChat(
        [("search_notes", {"query": "x", "subject": "astrologia"})],
        [("no_such_tool", {})],
        [("get_page", {"document": SLIDES, "page": 99})],
        "NOT_FOUND",
    )
    answer = _run("Horòscop?", settings, indexed, chat)
    assert answer.abstained and answer.reason == "no_results"
    assert [s.result.split(":")[0] for s in answer.steps] == ["error", "error", "error"]
    assert "unknown subject 'astrologia'" in answer.steps[0].result


def test_tool_call_limit_forces_a_final_answer_without_tools(settings, indexed):
    s = _low_min_score(settings)
    search = [("search_notes", {"query": "patró"})]
    chat = ScriptedChat(*([search] * 10), default="Resposta [1].")
    answer = _run("Patrons?", s, indexed, chat)
    assert len(answer.steps) == s.agent.max_tool_calls
    last_messages, last_tools = chat.requests[-1]
    assert last_tools is None and "limit reached" in last_messages[-1]["content"]
    assert answer.answer == "Resposta [1]." and answer.cited == [1]


def test_get_page_and_global_numbering(settings, indexed):
    s = _low_min_score(settings)
    chat = ScriptedChat(
        [("search_notes", {"query": "patró observador"})],
        [("get_page", {"document": SLIDES, "page": 1})],  # same chunk again: keeps its number
        "Resposta [1] i [2].",
    )
    answer = _run("Patró?", s, indexed, chat)
    numbers = [src.number for src in answer.sources]
    assert numbers == list(range(1, len(numbers) + 1))  # no duplicates, no gaps
    assert len({src.chunk_id for src in answer.sources}) == len(answer.sources)
    assert answer.steps[1].tool == "get_page" and "sources" in answer.steps[1].result


def test_listing_answers_need_no_citation(settings, indexed):
    chat = ScriptedChat([("list_subjects", {})], "Tens apunts de Disseny i IS.")
    answer = _run("Quines assignatures tinc?", settings, indexed, chat)
    assert not answer.abstained and not answer.uncited
    listing = chat.requests[1][0][-1]["content"]
    assert "disseny_software (Disseny de Software): 1 theory" in listing
    assert "informacio_i_seguretat" in listing and "1 exams" in listing


def test_list_documents_filters(settings, indexed):
    embedder, store = indexed
    tools = NoteTools(USER, settings, embedder, store)
    text, summary = tools.run(ToolCall("list_documents", {"doc_type": "exams"}))
    assert (
        text == "- informacio_i_seguretat/exams/IS2425-P1.pdf (2024-25)"
        and summary == "1 documents"
    )


def test_low_scores_are_never_shown_to_the_model(settings, indexed):
    s = settings.model_copy(
        update={"retrieval": settings.retrieval.model_copy(update={"min_score": 0.99})}
    )
    chat = ScriptedChat([("search_notes", {"query": "mundial de futbol"})], "NOT_FOUND")
    answer = _run("Mundial?", s, indexed, chat)
    assert chat.requests[1][0][-1]["content"].startswith("No relevant notes found")
    assert answer.abstained and answer.sources == []


def test_answer_without_any_tool_is_flagged(settings, indexed):
    answer = _run("Hola?", settings, indexed, ScriptedChat("Hola! Sóc un model."))
    assert not answer.abstained and answer.uncited and answer.steps == []
