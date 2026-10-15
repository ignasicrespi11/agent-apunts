"""Large language model access (D4, D31).

`LLMClient` is the interface the RAG code uses; `OllamaClient` is the free, local implementation.
A paid provider (Claude API) would be one more class here, chosen in settings.yaml: nothing else in
the project changes. Only free providers are implemented for now.
"""

import json
import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from agent_apunts.config import Settings


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    latency_ms: int
    # Tokens read and written, when the provider reports them. prompt_tokens close to the context
    # size means the prompt may have been cut (Ollama truncates silently); both also give the cost
    # of an answer when a paid provider is compared (phase 2).
    prompt_tokens: int | None = None
    output_tokens: int | None = None


class LLMClient(Protocol):
    model: str

    def complete(self, system: str, user: str) -> LLMResponse:
        """One answer to `user`, following the rules in `system`. No conversation memory."""
        ...


class LLMError(RuntimeError):
    """The LLM service failed; the message says what to do about it."""


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict


@dataclass(frozen=True)
class ChatResponse:
    """One assistant turn: either tool calls to run, or (no tool calls) the final text."""

    text: str
    tool_calls: list[ToolCall]
    model: str
    latency_ms: int
    prompt_tokens: int | None = None
    output_tokens: int | None = None


class ChatClient(Protocol):
    """A model that can call tools (the agent, D38). Separate from LLMClient: single-shot `ask`
    doesn't need tools, and not every model supports them."""

    model: str

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatResponse:
        """Next assistant turn for this conversation. tools: JSON-schema tool definitions."""
        ...


class ToolsNotSupportedError(LLMError):
    """The configured model can't call tools: the agent falls back to single-shot `ask`."""


class OllamaClient:
    """Chat with a local model through Ollama's POST /api/chat (non-streaming)."""

    def __init__(
        self,
        url: str,
        model: str,
        temperature: float,
        num_ctx: int,
        timeout: float = 600.0,  # a 7B model on a CPU can take minutes for a long answer
        transport: httpx.BaseTransport | None = None,  # tests pass a fake Ollama here
    ) -> None:
        self.model = model
        self.num_ctx = num_ctx
        self._options = {"temperature": temperature, "num_ctx": num_ctx}
        self._client = httpx.Client(base_url=url, timeout=timeout, transport=transport)

    def complete(self, system: str, user: str) -> LLMResponse:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        data, latency = self._post({"messages": messages})
        return LLMResponse(
            text=data.get("message", {}).get("content", "").strip(),
            model=self.model,
            latency_ms=latency,
            prompt_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
        )

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatResponse:
        data, latency = self._post({"messages": messages, **({"tools": tools} if tools else {})})
        message = data.get("message", {})
        calls = [
            ToolCall(
                name=c.get("function", {}).get("name", ""),
                arguments=_arguments(c.get("function", {}).get("arguments")),
            )
            for c in message.get("tool_calls") or []
        ]
        return ChatResponse(
            text=(message.get("content") or "").strip(),
            tool_calls=calls,
            model=self.model,
            latency_ms=latency,
            prompt_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
        )

    def _post(self, fields: dict) -> tuple[dict, int]:
        body = {"model": self.model, "stream": False, "options": self._options, **fields}
        start = time.perf_counter()
        try:
            response = self._client.post("/api/chat", json=body)
        except httpx.ConnectError as e:
            raise LLMError(
                f"cannot reach Ollama at {self._client.base_url}. Is it running? "
                "(start the Ollama app, or `ollama serve`)"
            ) from e
        except httpx.TimeoutException as e:
            raise LLMError(
                f"'{self.model}' took too long to answer: try a smaller model in settings.yaml"
            ) from e
        except httpx.TransportError as e:  # connection dropped mid-request: Ollama crashed
            raise LLMError(
                f"Ollama stopped answering ({type(e).__name__}): it may have run out of GPU "
                f"memory for '{self.model}'. Restart Ollama, or use a smaller model"
            ) from e
        if response.status_code == 404:
            raise LLMError(f"Ollama has no model '{self.model}': run `ollama pull {self.model}`")
        if response.status_code == 400 and "does not support tools" in response.text:
            raise ToolsNotSupportedError(f"'{self.model}' can't call tools")
        if response.status_code != 200:
            raise LLMError(f"Ollama error {response.status_code}: {response.text[:300]}")
        return response.json(), int((time.perf_counter() - start) * 1000)


def _arguments(raw: object) -> dict:
    """Ollama sends tool arguments as an object; some models put a JSON string there instead."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def make_llm(settings: Settings) -> LLMClient:
    s = settings.llm
    if s.provider == "ollama":
        return OllamaClient(settings.ollama.url, s.model, s.temperature, s.num_ctx)
    raise ValueError(f"unknown LLM provider {s.provider!r}")


def make_chat(settings: Settings) -> ChatClient:
    """The tool-calling client for the agent (D38): same provider and model as make_llm."""
    s = settings.llm
    if s.provider == "ollama":
        return OllamaClient(settings.ollama.url, s.model, s.temperature, s.num_ctx)
    raise ValueError(f"unknown LLM provider {s.provider!r}")
