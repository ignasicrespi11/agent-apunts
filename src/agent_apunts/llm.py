"""Large language model access (D4, D31).

`LLMClient` is the interface the RAG code uses; `OllamaClient` is the free, local implementation.
A paid provider (Claude API) would be one more class here, chosen in settings.yaml: nothing else in
the project changes. Only free providers are implemented for now.
"""

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


class LLMClient(Protocol):
    model: str

    def complete(self, system: str, user: str) -> LLMResponse:
        """One answer to `user`, following the rules in `system`. No conversation memory."""
        ...


class LLMError(RuntimeError):
    """The LLM service failed; the message says what to do about it."""


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
        self._options = {"temperature": temperature, "num_ctx": num_ctx}
        self._client = httpx.Client(base_url=url, timeout=timeout, transport=transport)

    def complete(self, system: str, user: str) -> LLMResponse:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "options": self._options,
        }
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
        if response.status_code == 404:
            raise LLMError(f"Ollama has no model '{self.model}': run `ollama pull {self.model}`")
        if response.status_code != 200:
            raise LLMError(f"Ollama error {response.status_code}: {response.text[:300]}")
        text = response.json().get("message", {}).get("content", "")
        latency = int((time.perf_counter() - start) * 1000)
        return LLMResponse(text=text.strip(), model=self.model, latency_ms=latency)


def make_llm(settings: Settings) -> LLMClient:
    s = settings.llm
    if s.provider == "ollama":
        return OllamaClient(settings.ollama.url, s.model, s.temperature, s.num_ctx)
    raise ValueError(f"unknown LLM provider {s.provider!r}")
