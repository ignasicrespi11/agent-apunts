"""Load and validate the configuration (D20).

Two sources, merged into one validated `Settings` object:
- config/settings.yaml + config/sources.yaml: shared, committed, identical on every machine.
- .env (and real environment variables): per machine, never committed. Only the values listed in
  `_ENV_VARS` are read from it, explicitly, so it is always clear where a value comes from.

The rest of the code only sees `Settings`. Moving to pydantic-settings (deployment) or to a database
of user profiles (multi-user) changes this file only.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field

from agent_apunts.metadata import AcademicYear, Slug


class _Strict(BaseModel):
    # A misspelled key in a YAML file is an error, not a silently ignored setting.
    model_config = ConfigDict(extra="forbid", frozen=True)


class UserProfile(_Strict):
    id: Slug
    university: str
    degree: str


class Subject(_Strict):
    name: str
    taken_in: AcademicYear
    professor: str | None = None


class Paths(_Strict):
    """Absolute paths, resolved for this machine."""

    project_root: Path
    apunts_dir: Path  # inbox of real material
    testing_dir: Path  # manually labelled set (dev corpus + ground truth)
    data_dir: Path  # stage outputs

    @property
    def manifest(self) -> Path:
        return self.data_dir / "manifest.sqlite"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def thumbnails_dir(self) -> Path:
        return self.data_dir / "thumbnails"


class ExtractionSettings(_Strict):
    image_page_max_chars: int = Field(ge=0)
    thumbnail_width: int = Field(gt=0)


class EmbeddingSettings(_Strict):
    model: str
    dimension: int = Field(gt=0)


class QdrantSettings(_Strict):
    url: str
    collection: str


class LLMSettings(_Strict):
    provider: Literal["ollama", "anthropic"]
    model: str


class Settings(_Strict):
    user: UserProfile
    languages: list[str] = Field(min_length=1)
    paths: Paths
    extraction: ExtractionSettings
    embedding: EmbeddingSettings
    qdrant: QdrantSettings
    llm: LLMSettings
    subjects: dict[Slug, Subject]

    @property
    def source_dirs(self) -> dict[str, Path]:
        """Where documents are read from, by source name (stored in the manifest)."""
        return {"testing": self.paths.testing_dir, "apunts": self.paths.apunts_dir}


# Per-machine values read from the environment, with their defaults.
_ENV_VARS = {
    "APUNTS_DIR": "apunts",
    "TESTING_DIR": "testing/apunts_testing",
    "QDRANT_URL": "http://localhost:6333",
}


class ConfigError(Exception):
    """The configuration files are missing or invalid."""


def find_project_root(start: Path | None = None) -> Path:
    """Walk up from `start` (default: current dir) to the folder containing config/settings.yaml,
    so commands work from any subfolder of the repo, like git does."""
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "config" / "settings.yaml").is_file():
            return candidate
    raise ConfigError(f"config/settings.yaml not found in {here} or any parent folder")


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        raise ConfigError(f"missing {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return data


def _read_env(project_root: Path) -> dict[str, str]:
    """Values of `_ENV_VARS`: real environment > .env > default.

    dotenv_values() only *reads* .env; unlike load_dotenv() it doesn't modify os.environ,
    so loading settings has no side effects (and tests don't leak into each other).
    """
    dotenv = dotenv_values(project_root / ".env")
    values = {}
    for name, default in _ENV_VARS.items():
        # `or`: an empty value (TESTING_DIR= in .env.example) means "use the default".
        values[name] = os.environ.get(name) or dotenv.get(name) or default
    return values


def _resolve(path_str: str, project_root: Path) -> Path:
    # Relative paths are relative to the project root, not to wherever the command was run.
    path = Path(path_str).expanduser()
    return (path if path.is_absolute() else project_root / path).resolve()


def load_settings(project_root: Path | None = None) -> Settings:
    """Read config/*.yaml + environment and return validated settings. Raises ConfigError."""
    root = (project_root or find_project_root()).resolve()
    raw = _read_yaml(root / "config" / "settings.yaml")
    sources = _read_yaml(root / "config" / "sources.yaml")
    env = _read_env(root)

    data_dir = raw.pop("data_dir", "data")
    raw["paths"] = {
        "project_root": root,
        "apunts_dir": _resolve(env["APUNTS_DIR"], root),
        "testing_dir": _resolve(env["TESTING_DIR"], root),
        "data_dir": _resolve(data_dir, root),
    }
    raw.setdefault("qdrant", {})["url"] = env["QDRANT_URL"]
    raw["subjects"] = sources.get("subjects") or {}

    try:
        return Settings.model_validate(raw)
    except ValueError as e:  # pydantic.ValidationError is a ValueError
        raise ConfigError(f"invalid configuration in {root / 'config'}:\n{e}") from e
