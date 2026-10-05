"""config.py: YAML + .env are merged into one validated Settings object (D20)."""

from pathlib import Path

import pytest

from agent_apunts.config import ConfigError, find_project_root, load_settings


def test_committed_config_is_valid(settings):
    assert settings.user.id == "ignasi"
    assert set(settings.subjects) == {
        "arquitectura_computadors",
        "disseny_software",
        "informacio_i_seguretat",
    }
    assert settings.languages == ["ca", "es", "en"]


def test_defaults_without_env(settings, project):
    assert settings.paths.testing_dir == project / "testing" / "apunts_testing"
    assert settings.paths.apunts_dir == project / "apunts"
    assert settings.paths.manifest == project / "data" / "manifest.sqlite"
    assert settings.qdrant.url == "http://localhost:6333"


def test_dotenv_overrides_default(project, tmp_path):
    corpus = tmp_path / "onedrive" / "apunts_testing"
    (project / ".env").write_text(f"TESTING_DIR={corpus}\nAPUNTS_DIR=\n")
    settings = load_settings(project)
    assert settings.paths.testing_dir == corpus
    assert settings.paths.apunts_dir == project / "apunts"  # empty value -> default


def test_real_env_overrides_dotenv(project, monkeypatch):
    (project / ".env").write_text("QDRANT_URL=http://from-dotenv:6333\n")
    monkeypatch.setenv("QDRANT_URL", "http://from-env:6333")
    assert load_settings(project).qdrant.url == "http://from-env:6333"


def test_relative_env_path_is_relative_to_project_root(project, monkeypatch):
    monkeypatch.setenv("TESTING_DIR", "elsewhere/pdfs")
    monkeypatch.chdir(project.parent)  # run from another folder: result must not change
    assert load_settings(project).paths.testing_dir == project / "elsewhere" / "pdfs"


def test_misspelled_key_is_an_error(project):
    path = project / "config" / "settings.yaml"
    path.write_text(path.read_text().replace("data_dir:", "data_dir: data\ndata_dri:"))
    with pytest.raises(ConfigError, match="data_dri"):
        load_settings(project)


def test_invalid_academic_year_is_an_error(project):
    path = project / "config" / "sources.yaml"
    path.write_text(path.read_text().replace('"2025-26"', '"2025-27"', 1))
    with pytest.raises(ConfigError, match="taken_in"):
        load_settings(project)


def test_missing_file_is_an_error(project):
    (project / "config" / "sources.yaml").unlink()
    with pytest.raises(ConfigError, match="sources.yaml"):
        load_settings(project)


def test_project_root_found_from_subfolder(project):
    sub = project / "src" / "deep"
    sub.mkdir(parents=True)
    assert find_project_root(sub) == project.resolve()


def test_project_root_not_found(tmp_path: Path):
    with pytest.raises(ConfigError):
        find_project_root(tmp_path)
