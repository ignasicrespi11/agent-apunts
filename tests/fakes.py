"""Test doubles for services that need a running server (Ollama)."""

import re
import zlib
from collections.abc import Sequence


class HashEmbedder:
    """Deterministic bag-of-words embedder: texts sharing words get similar vectors.

    Good enough to test that retrieval returns the right chunk and respects filters, without
    downloading a model. It knows nothing about meaning or languages (bge-m3 does).
    """

    def __init__(self, dimension: int = 64, model: str = "fake-hash") -> None:
        self.dimension = dimension
        self.model = model
        self.calls = 0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        vectors = []
        for text in texts:
            vector = [0.0] * self.dimension
            for word in re.findall(r"\w+", text.lower()):
                vector[zlib.crc32(word.encode()) % self.dimension] += 1.0
            vector[0] += 1e-6  # never all-zero (cosine is undefined for a zero vector)
            vectors.append(vector)
        return vectors
