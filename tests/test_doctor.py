"""doctor.py: every check says what is wrong and how to fix it."""

import httpx
from qdrant_client import QdrantClient

from agent_apunts import doctor
from agent_apunts.store import VectorStore


def _ollama(models=None, up=True):
    def handler(request):
        if not up:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"models": [{"name": m} for m in models or []]})

    return httpx.MockTransport(handler)


def test_ollama_models_present_with_latest_tag(settings):
    transport = _ollama(["bge-m3:latest", "qwen2.5:7b"])
    checks = doctor.check_ollama(settings, transport)
    assert all(c.ok for c in checks)


def test_ollama_missing_model_says_pull(settings):
    checks = doctor.check_ollama(settings, _ollama(["bge-m3:latest"]))
    llm = next(c for c in checks if c.name == "LLM")
    assert not llm.ok and llm.fix == f"ollama pull {settings.llm.model}"


def test_ollama_down(settings):
    (check,) = doctor.check_ollama(settings, _ollama(up=False))
    assert not check.ok and "systemctl start ollama" in check.fix


def test_qdrant_states(settings):
    client = QdrantClient(":memory:")
    (check,) = doctor.check_qdrant(settings, client)
    assert check.ok and "not created yet" in check.detail
    VectorStore(client, settings.qdrant.collection, "other-model", 1024).ensure_collection()
    (check,) = doctor.check_qdrant(settings, client)
    assert not check.ok and "new qdrant.collection" in check.fix


def test_sources_and_counts(settings):
    checks = {c.name: c for c in doctor.check_sources(settings)}
    assert not checks["folder testing"].ok and "TESTING_DIR" in checks["folder testing"].fix
    assert doctor.pipeline_counts(settings, "ignasi") == {
        "registered": 0,
        "extract": 0,
        "chunk": 0,
        "index": 0,
    }
    assert not settings.paths.manifest.exists()  # counting doesn't create an empty manifest
