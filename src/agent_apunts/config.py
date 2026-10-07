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
from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    logs_dir: Path  # query log (D33)

    @property
    def manifest(self) -> Path:
        return self.data_dir / "manifest.sqlite"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def thumbnails_dir(self) -> Path:
        return self.data_dir / "thumbnails"

    @property
    def chunks_dir(self) -> Path:
        return self.data_dir / "chunks"

    @property
    def eval_dir(self) -> Path:
        return self.data_dir / "eval"


class ExtractionSettings(_Strict):
    image_page_max_chars: int = Field(ge=0)
    thumbnail_width: int = Field(gt=0)
    language_min_chars: int = Field(ge=0)
    language_min_confidence: float = Field(ge=0, le=1)
    large_image_min_coverage: float = Field(ge=0, le=1)


class CleaningSettings(_Strict):
    repeated_line_min_share: float = Field(gt=0, le=1)
    repeated_line_min_pages: int = Field(ge=2)
    repeated_line_max_chars: int = Field(gt=0)


class ChunkingSettings(_Strict):
    max_words: int = Field(gt=0)
    target_words: int = Field(gt=0)
    min_words: int = Field(ge=0)

    @model_validator(mode="after")
    def _sizes_are_ordered(self) -> ChunkingSettings:
        if not self.min_words <= self.target_words <= self.max_words:
            raise ValueError("chunking needs min_words <= target_words <= max_words")
        return self


class EmbeddingSettings(_Strict):
    provider: Literal["ollama"]
    model: str
    dimension: int = Field(gt=0)
    batch_size: int = Field(gt=0)


class OllamaSettings(_Strict):
    url: str


class QdrantSettings(_Strict):
    url: str
    collection: str


class LLMSettings(_Strict):
    provider: Literal["ollama"]  # only free, local providers are implemented (D31)
    model: str
    temperature: float = Field(ge=0, le=2)
    num_ctx: int = Field(gt=0)


class RetrievalSettings(_Strict):
    top_k: int = Field(gt=0)
    min_score: float = Field(ge=-1, le=1)  # cosine similarity


class Source(_Strict):
    """A folder documents are read from.

    labelled=True: every file must sit in <subject>/<doc_type>/ folders (the manually organised
    ground truth). labelled=False: folders are an optional hint (the inbox, D18).
    """

    name: str
    root: Path
    labelled: bool


class Settings(_Strict):
    user: UserProfile
    languages: list[str] = Field(min_length=1)
    paths: Paths
    extraction: ExtractionSettings
    cleaning: CleaningSettings
    chunking: ChunkingSettings
    embedding: EmbeddingSettings
    qdrant: QdrantSettings
    ollama: OllamaSettings
    retrieval: RetrievalSettings
    llm: LLMSettings
    subjects: dict[Slug, Subject]

    @property
    def sources(self) -> tuple[Source, ...]:
        """Where documents are read from. The name is stored in the manifest with each document."""
        return (
            Source(name="testing", root=self.paths.testing_dir, labelled=True),
            Source(name="apunts", root=self.paths.apunts_dir, labelled=False),
        )

    def source(self, name: str) -> Source:
        for source in self.sources:
            if source.name == name:
                return source
        raise KeyError(f"unknown source {name!r} (known: {[s.name for s in self.sources]})")


# Per-machine values read from the environment, with their defaults.
_ENV_VARS = {
    "APUNTS_DIR": "apunts",
    "TESTING_DIR": "testing/apunts_testing",
    "QDRANT_URL": "http://localhost:6333",
    "OLLAMA_URL": "http://localhost:11434",
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
    logs_dir = raw.pop("logs_dir", "logs")
    raw["paths"] = {
        "project_root": root,
        "apunts_dir": _resolve(env["APUNTS_DIR"], root),
        "testing_dir": _resolve(env["TESTING_DIR"], root),
        "data_dir": _resolve(data_dir, root),
        "logs_dir": _resolve(logs_dir, root),
    }
    raw.setdefault("qdrant", {})["url"] = env["QDRANT_URL"]
    raw["ollama"] = {"url": env["OLLAMA_URL"]}
    raw["subjects"] = sources.get("subjects") or {}

    try:
        return Settings.model_validate(raw)
    except ValueError as e:  # pydantic.ValidationError is a ValueError
        raise ConfigError(f"invalid configuration in {root / 'config'}:\n{e}") from e
