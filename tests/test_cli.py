"""CLI commands, run in-process with Typer's test runner."""

import pytest
from typer.testing import CliRunner

from agent_apunts.cli import app

runner = CliRunner()


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


def test_inspect_unknown_document(in_project):
    result = runner.invoke(app, ["inspect", "nothing"])
    assert result.exit_code == 1
    assert "No document matches" in result.output


def test_register_unknown_source(in_project):
    result = runner.invoke(app, ["register", "--source", "nope"])
    assert result.exit_code == 1
    assert "unknown source" in result.output
