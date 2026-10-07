"""Environment and pipeline health checks for `agent-apunts doctor`.

Every check returns a result with a fix, so a new machine (or a broken one) can be set up by
reading one screen instead of decoding stack traces.
"""

from dataclasses import dataclass

import httpx
from qdrant_client import QdrantClient

from agent_apunts.config import Settings
from agent_apunts.ingestion.discovery import find_files
from agent_apunts.ingestion.loaders import supported_extensions
from agent_apunts.ingestion.manifest import Manifest

STAGES = ("extract", "chunk", "index")


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""


def _model_names(tags: dict) -> set[str]:
    names = set()
    for model in tags.get("models", []):
        name = model.get("name", "")
        names.add(name)
        if name.endswith(":latest"):
            names.add(name.removesuffix(":latest"))  # "bge-m3" == "bge-m3:latest"
    return names


def check_sources(settings: Settings) -> list[Check]:
    checks = []
    for source in settings.sources:
        if source.root.is_dir():
            n = len(find_files(source.root, supported_extensions()))
            checks.append(Check(f"folder {source.name}", True, f"{source.root} ({n} documents)"))
        else:
            fix = "set TESTING_DIR in .env" if source.labelled else "create it or set APUNTS_DIR"
            checks.append(Check(f"folder {source.name}", False, f"{source.root} not found", fix))
    return checks


def check_ollama(settings: Settings, transport: httpx.BaseTransport | None = None) -> list[Check]:
    url = settings.ollama.url
    try:
        with httpx.Client(base_url=url, timeout=5, transport=transport) as client:
            tags = client.get("/api/tags").json()
    except httpx.HTTPError:
        fix = "start the Ollama app (Windows) or `sudo systemctl start ollama` (Omarchy)"
        return [Check("ollama", False, f"not reachable at {url}", fix)]
    names = _model_names(tags)
    checks = [Check("ollama", True, f"{url} ({len(tags.get('models', []))} models)")]
    for role, model in (("embedding model", settings.embedding.model), ("LLM", settings.llm.model)):
        present = model in names
        fix = "" if present else f"ollama pull {model}"
        checks.append(Check(role, present, model + ("" if present else " not pulled"), fix))
    return checks


def check_qdrant(settings: Settings, client: QdrantClient | None = None) -> list[Check]:
    # No version handshake: it only adds a warning when the server is down, which we report.
    client = client or QdrantClient(url=settings.qdrant.url, timeout=5, check_compatibility=False)
    name = settings.qdrant.collection
    try:
        exists = client.collection_exists(name)
    except Exception:  # noqa: BLE001 (connection errors come in several types)
        return [
            Check(
                "qdrant", False, f"not reachable at {settings.qdrant.url}", "docker compose up -d"
            )
        ]
    if not exists:
        return [Check("qdrant", True, f"collection '{name}' not created yet (run `index`)")]
    info = client.get_collection(name)
    stored = info.config.metadata or {}
    expected = (settings.embedding.model, settings.embedding.dimension)
    same = (stored.get("embedding_model"), stored.get("dimension")) == expected
    detail = (
        f"collection '{name}': {info.points_count} points, model {stored.get('embedding_model')}"
    )
    fix = "" if same else "settings changed the embedding model: new qdrant.collection + `index`"
    return [Check("qdrant", same, detail, fix)]


def pipeline_counts(settings: Settings, user_id: str) -> dict[str, int]:
    """How many of the user's documents have completed each stage (from the manifest)."""
    if not settings.paths.manifest.is_file():
        return {"registered": 0, **{s: 0 for s in STAGES}}
    with Manifest(settings.paths.manifest) as manifest:
        records = manifest.documents(user_id)
        counts = {"registered": len(records)}
        for stage in STAGES:
            counts[stage] = sum(
                manifest.stage(user_id, r.doc_id, stage) is not None for r in records
            )
    return counts
