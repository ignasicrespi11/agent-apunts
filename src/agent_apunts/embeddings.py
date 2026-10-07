"""Turn text into vectors (D3, D28).

An embedding is a list of numbers (1024 for bge-m3) that represents what a text means: texts about
the same thing get vectors that point in similar directions, whatever their language. Retrieval
compares the question's vector with every chunk's vector, so chunks and questions MUST be embedded
by the same model; the model name is therefore stored in the Qdrant collection and checked.

`Embedder` is the interface the rest of the code uses; `OllamaEmbedder` is today's implementation.
Swapping provider = a new class + one line in `make_embedder`, nothing else changes.
"""

from collections.abc import Sequence
from typing import Protocol

import httpx

from agent_apunts.config import Settings


class Embedder(Protocol):
    model: str  # stored in the collection metadata: chunks and queries must use the same one
    dimension: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text, same order."""
        ...


class EmbeddingError(RuntimeError):
    """The embedding service failed; the message says what to do about it."""


class OllamaEmbedder:
    """bge-m3 served by a local Ollama (`ollama pull bge-m3`), via POST /api/embed."""

    def __init__(
        self,
        url: str,
        model: str,
        dimension: int,
        batch_size: int,
        timeout: float = 300.0,
        transport: httpx.BaseTransport | None = None,  # tests pass a fake Ollama here
    ) -> None:
        self.model = model
        self.dimension = dimension
        self._batch_size = batch_size
        self._client = httpx.Client(base_url=url, timeout=timeout, transport=transport)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        # Batches: one HTTP call per text would be slow; one call for 4,000 chunks would be huge.
        for start in range(0, len(texts), self._batch_size):
            vectors += self._embed_batch(list(texts[start : start + self._batch_size]))
        return vectors

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        try:
            response = self._client.post("/api/embed", json={"model": self.model, "input": batch})
        except httpx.ConnectError as e:
            raise EmbeddingError(
                f"cannot reach Ollama at {self._client.base_url}. Is it running? "
                "(start the Ollama app, or `ollama serve`)"
            ) from e
        if response.status_code == 404:
            raise EmbeddingError(
                f"Ollama has no model '{self.model}': run `ollama pull {self.model}`"
            )
        if response.status_code != 200:
            raise EmbeddingError(f"Ollama error {response.status_code}: {response.text[:300]}")

        vectors = response.json().get("embeddings", [])
        if len(vectors) != len(batch):
            raise EmbeddingError(f"Ollama returned {len(vectors)} vectors for {len(batch)} texts")
        for vector in vectors:
            if len(vector) != self.dimension:
                raise EmbeddingError(
                    f"'{self.model}' returns {len(vector)} dimensions, settings.yaml says "
                    f"{self.dimension}: fix embedding.dimension (and re-index)"
                )
        return vectors


def make_embedder(settings: Settings) -> Embedder:
    e = settings.embedding
    if e.provider == "ollama":
        return OllamaEmbedder(settings.ollama.url, e.model, e.dimension, e.batch_size)
    raise ValueError(f"unknown embedding provider {e.provider!r}")
