"""The manifest: which documents exist and which pipeline stages each one has completed (D12).

A single SQLite file (data/manifest.sqlite). SQLite because it is a file (nothing to install or
run), it is transactional (a crash mid-run does not corrupt it) and any SQLite viewer opens it.
Every query takes `user_id` explicitly, so one manifest can hold many users (D7).
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from agent_apunts.metadata import DocumentMetadata

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    user_id       TEXT NOT NULL,
    doc_id        TEXT NOT NULL,   -- SHA-256 of the file bytes (D12)
    source        TEXT NOT NULL,   -- 'testing' or 'apunts' (Settings.sources)
    rel_path      TEXT NOT NULL,   -- current location, relative to the source root, '/'-separated
    size_bytes    INTEGER NOT NULL,
    metadata      TEXT,            -- DocumentMetadata as JSON; NULL until detected (D18)
    registered_at TEXT NOT NULL,   -- ISO 8601, UTC
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (user_id, doc_id)
);
CREATE TABLE IF NOT EXISTS stages (
    user_id      TEXT NOT NULL,
    doc_id       TEXT NOT NULL,
    stage        TEXT NOT NULL,    -- 'extract', later 'chunk', 'index'
    version      TEXT NOT NULL,    -- what produced the output, e.g. 'pymupdf-2'
    output       TEXT,             -- path of the output, relative to data_dir
    completed_at TEXT NOT NULL,
    PRIMARY KEY (user_id, doc_id, stage),
    FOREIGN KEY (user_id, doc_id) REFERENCES documents (user_id, doc_id) ON DELETE CASCADE
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class DocumentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    doc_id: str
    source: str
    rel_path: str
    size_bytes: int
    metadata: DocumentMetadata | None
    registered_at: str
    updated_at: str


class StageRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: str
    version: str
    output: str | None
    completed_at: str


class Manifest:
    """Thin wrapper over the SQLite file. Use as a context manager: `with Manifest(path) as m:`."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            raise RuntimeError(f"{path} has schema v{version}, code expects v{SCHEMA_VERSION}")
        with self._conn:
            self._conn.executescript(_SCHEMA)
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def __enter__(self) -> "Manifest":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    # --- documents ---------------------------------------------------------------------------

    def get(self, user_id: str, doc_id: str) -> DocumentRecord | None:
        row = self._conn.execute(
            "SELECT * FROM documents WHERE user_id = ? AND doc_id = ?", (user_id, doc_id)
        ).fetchone()
        return _to_record(row) if row else None

    def documents(self, user_id: str, source: str | None = None) -> list[DocumentRecord]:
        sql, args = "SELECT * FROM documents WHERE user_id = ?", [user_id]
        if source is not None:
            sql += " AND source = ?"
            args.append(source)
        rows = self._conn.execute(sql + " ORDER BY source, rel_path", args).fetchall()
        return [_to_record(r) for r in rows]

    def find(self, user_id: str, query: str) -> list[DocumentRecord]:
        """Documents whose doc_id starts with `query` (like git short hashes) or whose path
        contains it. Used by `inspect` so the user doesn't have to type 64 hex characters."""
        q = _escape_like(query)
        rows = self._conn.execute(
            "SELECT * FROM documents WHERE user_id = ?"
            " AND (doc_id LIKE ? ESCAPE '\\' OR rel_path LIKE ? ESCAPE '\\')"
            " ORDER BY source, rel_path",
            (user_id, f"{q}%", f"%{q}%"),
        ).fetchall()
        return [_to_record(r) for r in rows]

    def add(
        self,
        user_id: str,
        doc_id: str,
        source: str,
        rel_path: str,
        size_bytes: int,
        metadata: DocumentMetadata | None,
    ) -> None:
        now = _now()
        with self._conn:  # `with conn` = one transaction: commit on success, rollback on error
            self._conn.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, doc_id, source, rel_path, size_bytes, _dump(metadata), now, now),
            )

    def update_location(
        self,
        user_id: str,
        doc_id: str,
        source: str,
        rel_path: str,
        metadata: DocumentMetadata | None,
    ) -> None:
        """The same content was found somewhere else (moved/renamed): update path and metadata,
        keep the ID and every completed stage."""
        with self._conn:
            self._conn.execute(
                "UPDATE documents SET source = ?, rel_path = ?, metadata = ?, updated_at = ?"
                " WHERE user_id = ? AND doc_id = ?",
                (source, rel_path, _dump(metadata), _now(), user_id, doc_id),
            )

    def delete(self, user_id: str, doc_id: str) -> None:
        """Forget a document; its stage rows go too (ON DELETE CASCADE)."""
        with self._conn:
            self._conn.execute(
                "DELETE FROM documents WHERE user_id = ? AND doc_id = ?", (user_id, doc_id)
            )

    # --- stages ------------------------------------------------------------------------------

    def stage(self, user_id: str, doc_id: str, stage: str) -> StageRecord | None:
        row = self._conn.execute(
            "SELECT stage, version, output, completed_at FROM stages"
            " WHERE user_id = ? AND doc_id = ? AND stage = ?",
            (user_id, doc_id, stage),
        ).fetchone()
        return StageRecord(**dict(row)) if row else None

    def mark_done(
        self, user_id: str, doc_id: str, stage: str, version: str, output: str | None
    ) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO stages VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (user_id, doc_id, stage) DO UPDATE SET"
                " version = excluded.version, output = excluded.output,"
                " completed_at = excluded.completed_at",
                (user_id, doc_id, stage, version, output, _now()),
            )


def _escape_like(text: str) -> str:
    # In LIKE, % and _ are wildcards; "disseny_software" must match the literal underscore.
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _dump(metadata: DocumentMetadata | None) -> str | None:
    return metadata.model_dump_json() if metadata else None


def _to_record(row: sqlite3.Row) -> DocumentRecord:
    data = dict(row)
    raw = data.pop("metadata")
    meta = DocumentMetadata.model_validate_json(raw) if raw else None
    return DocumentRecord(**data, metadata=meta)
