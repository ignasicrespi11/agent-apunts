"""embeddings.py: the Ollama embedder against a fake Ollama (httpx.MockTransport, no server)."""

import json

import httpx
import pytest

from agent_apunts.embeddings import EmbeddingError, OllamaEmbedder, make_embedder


def _fake_ollama(dimension=4, status=200, calls=None):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if calls is not None:
            calls.append(body)
        if status != 200:
            return httpx.Response(status, text="model not found")
        vectors = [[float(len(text))] * dimension for text in body["input"]]
        return httpx.Response(200, json={"model": body["model"], "embeddings": vectors})

    return httpx.MockTransport(handler)


def _embedder(**kwargs):
    transport = _fake_ollama(**kwargs)
    return OllamaEmbedder("http://ollama", "bge-m3", 4, batch_size=2, transport=transport)


def test_embeds_in_batches_and_keeps_order():
    calls = []
    vectors = _embedder(calls=calls).embed(["a", "bb", "ccc", "dddd", "eeeee"])
    assert [v[0] for v in vectors] == [1, 2, 3, 4, 5]
    assert [len(c["input"]) for c in calls] == [2, 2, 1]
    assert all(c["model"] == "bge-m3" for c in calls)


def test_missing_model_says_how_to_fix_it():
    with pytest.raises(EmbeddingError, match="ollama pull bge-m3"):
        _embedder(status=404).embed(["x"])


def test_wrong_dimension_is_an_error():
    with pytest.raises(EmbeddingError, match="returns 8 dimensions"):
        _embedder(dimension=8).embed(["x"])


def test_ollama_not_running_says_how_to_fix_it():
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    embedder = OllamaEmbedder(
        "http://ollama", "bge-m3", 4, 2, transport=httpx.MockTransport(refuse)
    )
    with pytest.raises(EmbeddingError, match="Is it running"):
        embedder.embed(["x"])


def test_factory_uses_settings(settings):
    embedder = make_embedder(settings)
    assert embedder.model == "bge-m3" and embedder.dimension == 1024
