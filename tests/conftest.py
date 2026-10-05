"""Shared pytest fixtures. Everything is self-generated in tmp folders: no course material (D17)."""

import shutil
from pathlib import Path

import pytest

from agent_apunts.config import Settings, load_settings

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    """Tests must not depend on the developer's real environment variables."""
    for name in ("APUNTS_DIR", "TESTING_DIR", "QDRANT_URL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Throwaway project root with a copy of the real config/ (so the real files are tested)."""
    shutil.copytree(REPO_ROOT / "config", tmp_path / "config")
    return tmp_path


@pytest.fixture
def settings(project: Path) -> Settings:
    return load_settings(project)
