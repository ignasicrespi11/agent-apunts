"""Sparse (keyword) vectors for hybrid search (D37, proposed).

Dense embeddings capture meaning but can blur exact tokens: acronyms (TLB, DMA), pattern and class
names (Creator, PaymentInCash), numbers. A sparse vector is a bag of words: one dimension per word,
so an exact match counts directly. Qdrant multiplies each weight by the word's IDF (rarer words
weigh more, Modifier.IDF), which turns this into BM25 scoring:

    weight(word, chunk) = tf * (k1 + 1) / (tf + k1 * (1 - b + b * len / avg_len))   [here]
    score = sum over query words of IDF(word) * weight(word, chunk)                  [Qdrant]

No model to download: words are normalised (lowercase, accents removed) and hashed to indices.
Not stemmed, so "processador" and "processadors" are different words; dense search covers that.
"""

import re
import unicodedata
import zlib
from collections import Counter
from dataclasses import dataclass

K1 = 1.2  # BM25 term-frequency saturation: the 5th repetition of a word adds little
B = 0.75  # BM25 length normalisation: matches in long chunks count a bit less


@dataclass(frozen=True)
class Sparse:
    indices: list[int]
    values: list[float]


def tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    # Single letters are noise ("a", "i", "y" are also words in ca/es); numbers are kept.
    return [t for t in re.findall(r"[a-z0-9]+", text) if len(t) > 1 or t.isdigit()]


def _index(token: str) -> int:
    return zlib.crc32(token.encode())  # stable across runs and machines (unlike hash())


def encode_document(text: str, avg_len: float) -> Sparse:
    counts = Counter(_index(t) for t in tokens(text))  # collisions just add up
    length = sum(counts.values())
    if not length:
        return Sparse([], [])
    norm = K1 * (1 - B + B * length / max(avg_len, 1.0))
    indices = sorted(counts)
    values = [round(counts[i] * (K1 + 1) / (counts[i] + norm), 4) for i in indices]
    return Sparse(indices, values)


def encode_query(text: str) -> Sparse:
    """Each query word weighs 1; Qdrant's IDF does the rest."""
    indices = sorted({_index(t) for t in tokens(text)})
    return Sparse(indices, [1.0] * len(indices))
