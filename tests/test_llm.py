"""llm.py: the Ollama chat client against a fake Ollama (httpx.MockTransport)."""

import json

import httpx
import pytest

from agent_apunts.llm import LLMError, OllamaClient, make_llm


def _client(handler):
    return OllamaClient(
        "http://ollama", "qwen2.5:7b", 0, 8192, transport=httpx.MockTransport(handler)
    )


def test_sends_system_user_and_options():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(
            200, json={"message": {"role": "assistant", "content": " Hola [1]. "}}
        )

    response = _client(handler).complete("rules", "question")
    assert response.text == "Hola [1]." and response.model == "qwen2.5:7b"
    assert seen["messages"] == [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "question"},
    ]
    assert seen["stream"] is False
    assert seen["options"] == {"temperature": 0, "num_ctx": 8192}


def test_missing_model_says_how_to_fix_it():
    with pytest.raises(LLMError, match="ollama pull qwen2.5:7b"):
        _client(lambda r: httpx.Response(404, text="not found")).complete("s", "u")


def test_not_running_says_how_to_fix_it():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMError, match="Is it running"):
        _client(refuse).complete("s", "u")


def test_factory_uses_settings(settings):
    llm = make_llm(settings)
    assert llm.model == settings.llm.model
