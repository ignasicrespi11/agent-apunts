"""CLI commands, run in-process with Typer's test runner."""

import pytest
from typer.testing import CliRunner

from agent_apunts.cli import app

# Wide terminal: rich tables would otherwise wrap paths and texts mid-word in assertions.
runner = CliRunner(env={"COLUMNS": "200"})


@pytest.fixture
def in_project(project, monkeypatch):
    monkeypatch.chdir(project)  # the CLI finds config/ from the current folder
    return project


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-")  # content is irrelevant for `config`: it only counts files


def test_config_counts_pdfs_and_reports_problems(in_project):
    corpus = in_project / "testing" / "apunts_testing"
    _touch(corpus / "disseny_software" / "theory" / "t1.pdf")
    _touch(corpus / "disseny_software" / "theory" / "t2.pdf")
    _touch(corpus / "typo_subject" / "exams" / "e.pdf")

    result = runner.invoke(app, ["config"])

    assert result.exit_code == 0, result.output
    assert "3 documents" in result.output
    assert "disseny_software" in result.output
    assert "typo_subject" in result.output and "problem" in result.output


def test_config_error_exits_nonzero(in_project):
    (in_project / "config" / "settings.yaml").write_text("user: {}\n")
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 1
    assert "Configuration error" in result.output


def test_register_extract_inspect(in_project):
    from tests.pdf_factory import make_pdf

    corpus = in_project / "testing" / "apunts_testing"
    # The "image" page has no text: it exercises the empty-pages list in `extract`'s output.
    make_pdf(corpus / "disseny_software" / "theory" / "patrons.pdf", ["slide", "a4", "image"])

    result = runner.invoke(app, ["register"])
    assert result.exit_code == 0, result.output
    assert "1 new" in result.output

    result = runner.invoke(app, ["extract"])
    assert result.exit_code == 0, result.output
    assert "1 extracted (3 pages)" in result.output
    assert "patrons.pdf  page 3" in result.output

    result = runner.invoke(app, ["inspect", "patrons"])
    assert result.exit_code == 0, result.output
    assert "Patrons de disseny" in result.output and "landscape" in result.output

    result = runner.invoke(app, ["inspect", "patrons", "--page", "2"])
    assert result.exit_code == 0, result.output
    assert "memoria caché" in result.output

    result = runner.invoke(app, ["images"])
    assert result.exit_code == 0, result.output
    assert "disseny_software" in result.output

    result = runner.invoke(app, ["chunk"])
    assert result.exit_code == 0, result.output
    assert "1 chunked (2 chunks)" in result.output  # slide + A4 page; the image page gives none

    result = runner.invoke(app, ["inspect", "patrons", "--chunks"])
    assert result.exit_code == 0, result.output
    assert "Disseny de Software" in result.output

    result = runner.invoke(app, ["inspect", "patrons", "--chunks", "--page", "1"])
    assert result.exit_code == 0, result.output
    assert "notificar els canvis" in result.output


def test_inspect_unknown_document(in_project):
    result = runner.invoke(app, ["inspect", "nothing"])
    assert result.exit_code == 1
    assert "No document matches" in result.output


def test_register_unknown_source(in_project):
    result = runner.invoke(app, ["register", "--source", "nope"])
    assert result.exit_code == 1
    assert "unknown source" in result.output


@pytest.fixture
def fake_services(monkeypatch, in_project):
    """Ollama -> HashEmbedder, Qdrant -> one in-memory store shared by every command call."""
    from qdrant_client import QdrantClient

    from agent_apunts import cli
    from agent_apunts.store import VectorStore
    from tests.fakes import HashEmbedder, ScriptedLLM

    embedder = HashEmbedder()
    store = VectorStore(QdrantClient(":memory:"), "apunts", embedder.model, embedder.dimension)
    monkeypatch.setattr(cli, "make_embedder", lambda settings: embedder)
    monkeypatch.setattr(cli, "make_llm", lambda settings: ScriptedLLM("Notifica els canvis [1]."))
    monkeypatch.setattr(cli.VectorStore, "from_settings", classmethod(lambda cls, s: store))
    return in_project


def test_ingest_then_search(fake_services):
    from tests.pdf_factory import make_pdf

    corpus = fake_services / "testing" / "apunts_testing"
    make_pdf(corpus / "disseny_software" / "theory" / "patrons.pdf", ["slide", "a4"])

    result = runner.invoke(app, ["ingest"])
    assert result.exit_code == 0, result.output
    assert "1 indexed (2 points)" in result.output

    again = runner.invoke(app, ["ingest"])
    assert again.exit_code == 0, again.output
    assert "0 indexed (0 points), 1 up to date" in again.output
    assert "holds 2 points" in again.output  # idempotent: still 2 (D29)

    result = runner.invoke(app, ["search", "patró observador", "--subject", "disseny_software"])
    assert result.exit_code == 0, result.output
    assert "disseny_software" in result.output and "score" in result.output


def test_search_unknown_subject(fake_services):
    result = runner.invoke(app, ["search", "x", "--subject", "nope"])
    assert result.exit_code == 1 and "Unknown subject" in result.output


def test_ask_answers_cites_and_logs(fake_services):
    from tests.pdf_factory import make_pdf

    corpus = fake_services / "testing" / "apunts_testing"
    make_pdf(corpus / "disseny_software" / "theory" / "patrons.pdf", ["slide"])
    settings_file = fake_services / "config" / "settings.yaml"
    settings_file.write_text(settings_file.read_text().replace("min_score: 0.45", "min_score: 0.0"))
    assert runner.invoke(app, ["ingest"]).exit_code == 0

    result = runner.invoke(app, ["ask", "Què fa el patró observador?"])
    assert result.exit_code == 0, result.output
    assert "Notifica els canvis [1]." in result.output
    assert "yes" in result.output  # source [1] marked as cited
    log = (fake_services / "logs" / "queries.jsonl").read_text(encoding="utf-8")
    assert '"user_id": "ignasi"' in log


def test_eval_reports_and_saves_a_run(fake_services):
    from tests.pdf_factory import make_pdf

    corpus = fake_services / "testing" / "apunts_testing"
    make_pdf(corpus / "disseny_software" / "theory" / "patrons.pdf", ["slide", "a4"])
    assert runner.invoke(app, ["ingest"]).exit_code == 0
    golden = fake_services / "eval" / "golden.yaml"
    golden.parent.mkdir()
    golden.write_text(
        "questions:\n"
        "  - id: observer\n"
        "    question: patró observador canvis estat\n"
        "    language: ca\n"
        "    subject: disseny_software\n"
        "    expected: [{document: disseny_software/theory/patrons.pdf, pages: [1]}]\n"
        "  - id: typo\n"
        "    question: x\n"
        "    language: en\n"
        "    expected: [{document: disseny_software/theory/missing.pdf}]\n"
        "  - {id: none, question: mundial de futbol, language: ca, answerable: false}\n"
        "  - id: page-typo\n"
        "    question: patró\n"
        "    language: ca\n"
        "    expected: [{document: disseny_software/theory/patrons.pdf, pages: [20]}]\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["eval", "--sweep"])
    assert result.exit_code == 0, result.output
    assert "hit@1" in result.output and "MRR" in result.output
    assert "missing.pdf" in result.output  # unknown expected document is reported
    assert "page-typo: disseny_software/theory/patrons.pdf has 2 pages, not [20]" in result.output
    assert "min_score" in result.output
    assert list((fake_services / "data" / "eval").glob("retrieval-*.json"))


def test_eval_without_golden_file(fake_services):
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 1 and "golden.example.yaml" in result.output


def test_prune_registers_first_so_moves_are_not_deleted(fake_services):
    from tests.pdf_factory import make_pdf

    corpus = fake_services / "testing" / "apunts_testing"
    make_pdf(corpus / "disseny_software" / "theory" / "patrons.pdf", ["slide"])
    assert runner.invoke(app, ["ingest"]).exit_code == 0
    (corpus / "disseny_software" / "labs").mkdir()
    (corpus / "disseny_software" / "theory" / "patrons.pdf").rename(
        corpus / "disseny_software" / "labs" / "patrons.pdf"
    )
    result = runner.invoke(app, ["prune"])  # no explicit register before it
    assert result.exit_code == 0, result.output
    assert "Nothing to prune." in result.output and "1 moved" in result.output


def test_detect_suggests_and_evaluates(fake_services):
    from tests.pdf_factory import make_pdf

    corpus = fake_services / "testing" / "apunts_testing"
    make_pdf(corpus / "disseny_software" / "theory" / "patrons.pdf", ["slide", "a4"])
    make_pdf(corpus / "informacio_i_seguretat" / "exams" / "e.pdf", ["a4", "dense"])
    make_pdf(fake_services / "apunts" / "Examen_misteri.pdf", ["slide"])
    assert runner.invoke(app, ["ingest"]).exit_code == 0

    result = runner.invoke(app, ["detect"])
    assert result.exit_code == 0, result.output
    assert "Examen_misteri.pdf" in result.output and "exams (filename)" in result.output

    result = runner.invoke(app, ["detect", "--evaluate"])
    assert result.exit_code == 0, result.output
    assert "2 labelled documents" in result.output and "subject correct" in result.output
    assert "also leaving out" in result.output  # the stricter number, without near-duplicates


def test_doctor_reports_problems_with_fixes(in_project, monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:9")  # nothing listens on port 9
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "docker compose up -d" in result.output and "TESTING_DIR" in result.output
    assert "Pipeline for ignasi: 0 registered" in result.output


def test_duplicates_finds_a_reupload(fake_services):
    from tests.pdf_factory import make_pdf

    corpus = fake_services / "testing" / "apunts_testing"
    make_pdf(corpus / "disseny_software" / "theory" / "patrons.pdf", ["slide", "a4"])
    make_pdf(corpus / "informacio_i_seguretat" / "exams" / "e.pdf", ["dense"])
    # Same content plus one extra page: not an exact duplicate (different hash), but near.
    make_pdf(corpus / "disseny_software" / "labs" / "patrons_v2.pdf", ["slide", "a4", "image"])
    assert runner.invoke(app, ["ingest"]).exit_code == 0
    result = runner.invoke(app, ["duplicates", "--min-similarity", "0.95"])
    assert result.exit_code == 0, result.output
    assert "patrons_v2.pdf" in result.output and "1 groups" in result.output


def test_eval_answers_end_to_end(fake_services, monkeypatch):
    from agent_apunts import cli
    from tests.fakes import ScriptedLLM
    from tests.pdf_factory import make_pdf

    corpus = fake_services / "testing" / "apunts_testing"
    make_pdf(corpus / "disseny_software" / "theory" / "patrons.pdf", ["slide"])
    settings_file = fake_services / "config" / "settings.yaml"
    settings_file.write_text(settings_file.read_text().replace("min_score: 0.45", "min_score: 0.0"))
    assert runner.invoke(app, ["ingest"]).exit_code == 0
    llm = ScriptedLLM("El patró notifica [1].", "NOT_FOUND")
    monkeypatch.setattr(cli, "make_llm", lambda s: llm)
    (fake_services / "eval").mkdir()
    (fake_services / "eval" / "golden.yaml").write_text(
        "questions:\n"
        "  - id: observer\n"
        "    question: patró observador\n"
        "    language: ca\n"
        "    expected: [{document: disseny_software/theory/patrons.pdf, pages: [1]}]\n"
        "  - {id: none, question: mundial de futbol, language: ca, answerable: false}\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["eval", "--answers"])
    assert result.exit_code == 0, result.output
    assert "Abstention accuracy 100%" in result.output
    assert "100% of answers cite an expected page" in result.output
    assert list((fake_services / "data" / "eval").glob("answers-*.json"))


def test_compare_needs_two_runs_then_compares_the_newest(fake_services):
    import json as _json

    result = runner.invoke(app, ["compare"])
    assert result.exit_code == 1 and "run `eval` twice" in result.output

    runs = fake_services / "data" / "eval"
    runs.mkdir(parents=True)
    for stamp, mrr in (("20261015T100000Z", 0.4), ("20261015T110000Z", 0.6)):
        run = {
            "settings": {"retrieval": {"hybrid": mrr > 0.5}},
            "summary": {"overall": {"mrr": mrr}, "k": 5},
            "results": [],
        }
        (runs / f"retrieval-{stamp}.json").write_text(_json.dumps(run), encoding="utf-8")
    result = runner.invoke(app, ["compare"])
    assert result.exit_code == 0, result.output
    assert "overall.mrr" in result.output and "+0.200" in result.output
    assert "retrieval.hybrid: False -> True" in result.output


def test_documents_lists_paths_pages_and_state(fake_services):
    from tests.pdf_factory import make_pdf

    corpus = fake_services / "testing" / "apunts_testing"
    make_pdf(corpus / "disseny_software" / "theory" / "patrons.pdf", ["slide", "a4"])
    make_pdf(corpus / "informacio_i_seguretat" / "exams" / "e.pdf", ["a4"])
    assert runner.invoke(app, ["ingest"]).exit_code == 0

    result = runner.invoke(app, ["documents", "--subject", "disseny_software"])
    assert result.exit_code == 0, result.output
    assert "disseny_software/theory/patrons.pdf" in result.output
    assert "extract chunk index" in result.output and "e.pdf" not in result.output


def test_ask_agent_shows_steps_and_logs_mode(fake_services, monkeypatch):
    from agent_apunts import cli
    from tests.fakes import ScriptedChat
    from tests.pdf_factory import make_pdf

    corpus = fake_services / "testing" / "apunts_testing"
    make_pdf(corpus / "disseny_software" / "theory" / "patrons.pdf", ["slide"])
    settings_file = fake_services / "config" / "settings.yaml"
    settings_file.write_text(settings_file.read_text().replace("min_score: 0.45", "min_score: 0.0"))
    assert runner.invoke(app, ["ingest"]).exit_code == 0
    chat = ScriptedChat([("search_notes", {"query": "observador"})], "Notifica [1].")
    monkeypatch.setattr(cli, "make_chat", lambda settings: chat)

    result = runner.invoke(app, ["ask", "Què fa l'observador?", "--agent"])
    assert result.exit_code == 0, result.output
    assert "search_notes(query='observador')" in result.output and "Notifica [1]." in result.output
    log = (fake_services / "logs" / "queries.jsonl").read_text(encoding="utf-8")
    assert '"mode": "agent"' in log and '"tool": "search_notes"' in log


def test_ask_agent_falls_back_when_the_model_has_no_tools(fake_services, monkeypatch):
    from agent_apunts import cli
    from agent_apunts.llm import ToolsNotSupportedError
    from tests.pdf_factory import make_pdf

    corpus = fake_services / "testing" / "apunts_testing"
    make_pdf(corpus / "disseny_software" / "theory" / "patrons.pdf", ["slide"])
    settings_file = fake_services / "config" / "settings.yaml"
    settings_file.write_text(settings_file.read_text().replace("min_score: 0.45", "min_score: 0.0"))
    assert runner.invoke(app, ["ingest"]).exit_code == 0

    class NoTools:
        model = "old-model"

        def chat(self, messages, tools=None):
            raise ToolsNotSupportedError("no tools")

    monkeypatch.setattr(cli, "make_chat", lambda settings: NoTools())
    result = runner.invoke(app, ["ask", "Què fa l'observador?", "--agent"])
    assert result.exit_code == 0, result.output
    assert "single-shot ask instead" in result.output
    assert "Notifica els canvis [1]." in result.output  # ScriptedLLM from fake_services


def test_eval_answers_with_the_agent_reports_per_tag(fake_services, monkeypatch):
    from agent_apunts import cli
    from tests.fakes import ScriptedChat
    from tests.pdf_factory import make_pdf

    corpus = fake_services / "testing" / "apunts_testing"
    make_pdf(corpus / "disseny_software" / "theory" / "patrons.pdf", ["slide"])
    settings_file = fake_services / "config" / "settings.yaml"
    settings_file.write_text(settings_file.read_text().replace("min_score: 0.45", "min_score: 0.0"))
    assert runner.invoke(app, ["ingest"]).exit_code == 0
    chat = ScriptedChat(
        [("search_notes", {"query": "observador", "subject": "disseny_software"})],
        "Notifica [1].",
        "NOT_FOUND",
    )
    monkeypatch.setattr(cli, "make_chat", lambda s: chat)
    (fake_services / "eval").mkdir()
    (fake_services / "eval" / "golden.yaml").write_text(
        "questions:\n"
        "  - id: observer\n"
        "    question: patró observador\n"
        "    language: ca\n"
        "    tags: [multi-step]\n"
        "    expected: [{document: disseny_software/theory/patrons.pdf, pages: [1]}]\n"
        "  - {id: none, question: mundial, language: ca, answerable: false}\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["eval", "--answers", "--agent"])
    assert result.exit_code == 0, result.output
    assert "answers, agent" in result.output and "1 tool calls" in result.output
    assert "multi-step" in result.output and "Abstention accuracy 100%" in result.output
    (saved,) = (fake_services / "data" / "eval").glob("answers-*.json")
    assert '"mode": "agent"' in saved.read_text(encoding="utf-8")
