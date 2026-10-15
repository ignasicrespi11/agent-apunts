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


def test_token_counts_are_reported_when_ollama_sends_them():
    def handler(request):
        body = {"message": {"content": "ok"}, "prompt_eval_count": 3120, "eval_count": 85}
        return httpx.Response(200, json=body)

    response = _client(handler).complete("s", "u")
    assert (response.prompt_tokens, response.output_tokens) == (3120, 85)
    bare = _client(lambda r: httpx.Response(200, json={"message": {"content": "ok"}}))
    assert bare.complete("s", "u").prompt_tokens is None


def test_ollama_crash_mid_answer_says_what_to_do():
    def crash(request):
        raise httpx.RemoteProtocolError("server disconnected", request=request)

    with pytest.raises(LLMError, match="stopped answering"):
        _client(crash).complete("s", "u")


def test_chat_sends_tools_and_parses_tool_calls():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        message = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "search_notes", "arguments": {"query": "TLB"}}},
                # some models send the arguments as a JSON string
                {"function": {"name": "get_page", "arguments": '{"document": "a.pdf", "page": 2}'}},
            ],
        }
        return httpx.Response(200, json={"message": message, "prompt_eval_count": 900})

    tools = [{"type": "function", "function": {"name": "search_notes"}}]
    response = _client(handler).chat([{"role": "user", "content": "q"}], tools)
    assert seen["tools"] == tools and seen["stream"] is False
    assert [(c.name, c.arguments) for c in response.tool_calls] == [
        ("search_notes", {"query": "TLB"}),
        ("get_page", {"document": "a.pdf", "page": 2}),
    ]
    assert response.prompt_tokens == 900


def test_chat_without_tools_sends_no_tools_field():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": " Final [1]. "}})

    response = _client(handler).chat([{"role": "user", "content": "q"}])
    assert "tools" not in seen and response.text == "Final [1]." and response.tool_calls == []


def test_model_without_tool_support_is_reported():
    from agent_apunts.llm import ToolsNotSupportedError

    def handler(request):
        return httpx.Response(400, json={"error": "llama2 does not support tools"})

    with pytest.raises(ToolsNotSupportedError):
        _client(handler).chat([{"role": "user", "content": "q"}], [{"type": "function"}])
