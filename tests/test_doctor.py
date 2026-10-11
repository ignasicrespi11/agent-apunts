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


def test_qdrant_old_schema_is_reported(settings):
    from qdrant_client import models

    client = QdrantClient(":memory:")
    client.create_collection(
        settings.qdrant.collection,
        vectors_config=models.VectorParams(size=1024, distance=models.Distance.COSINE),
        metadata={"embedding_model": settings.embedding.model, "dimension": 1024},
    )
    (check,) = doctor.check_qdrant(settings, client)
    assert not check.ok and "older layout" in check.detail


def test_something_else_on_the_ollama_port(settings):
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text="<html>hi</html>"))
    (check,) = doctor.check_ollama(settings, transport)
    assert not check.ok and "is not Ollama" in check.detail
    transport = httpx.MockTransport(lambda r: httpx.Response(404, text="nope"))
    (check,) = doctor.check_ollama(settings, transport)
    assert not check.ok and "not reachable" in check.detail


def test_loaded_models_say_gpu_or_cpu(settings):
    # /api/ps reports size (total) and size_vram (part in GPU memory), like `ollama ps`.
    running = [
        {"name": "bge-m3:latest", "size": 1000, "size_vram": 1000},
        {"name": "qwen2.5:7b", "size": 1000, "size_vram": 250},
    ]

    def handler(request):
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": running})
        return httpx.Response(200, json={"models": [{"name": "bge-m3:latest"}]})

    checks = doctor.check_ollama(settings, httpx.MockTransport(handler))
    memory = next(c for c in checks if c.name == "ollama memory")
    assert memory.ok
    assert "bge-m3:latest 100% GPU" in memory.detail
    assert "qwen2.5:7b 75% CPU / 25% GPU" in memory.detail


def test_no_loaded_model_and_old_ollama_without_ps(settings):
    def handler(request):
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": []})
        return httpx.Response(200, json={"models": []})

    checks = doctor.check_ollama(settings, httpx.MockTransport(handler))
    assert "no model loaded" in next(c for c in checks if c.name == "ollama memory").detail

    def old(request):
        if request.url.path == "/api/ps":
            return httpx.Response(404, text="404 page not found")
        return httpx.Response(200, json={"models": []})

    checks = doctor.check_ollama(settings, httpx.MockTransport(old))
    assert checks[0].ok and all(c.name != "ollama memory" for c in checks)


def test_processor_column():
    assert doctor._processor({"size": 10, "size_vram": 0}) == "100% CPU"
    assert doctor._processor({"size": 10}) == "100% CPU"
    assert doctor._processor({"size": 10, "size_vram": 10}) == "100% GPU"
    assert doctor._processor({"size": 10, "size_vram": 5}) == "50% CPU / 50% GPU"
