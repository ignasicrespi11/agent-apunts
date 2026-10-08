"""Metadata auto-detection for unorganised PDFs (D18, revised as D36, proposed).

Folder hints always win (D18). For a PDF dropped in the inbox without folders:

- subject: nearest subject centroid. Each subject is represented by the mean of its labelled
  documents' vectors (the user's own folders are the training data). A document's vector is the
  mean embedding of a sample of its chunks' PLAIN text: the stored vectors can't be reused because
  their header contains the subject's name, which an unorganised PDF doesn't have (comparing
  those would leak the answer and fake a perfect score). The confidence is the *margin* between
  the best and second-best subject: equally close to two subjects is not a confident guess.
- doc_type: keywords in the file name, then in the first page (ca/es/en), else "theory".
- academic_year: from the file name (metadata.year_from_filename).

No LLM: free and deterministic. It embeds a few header-free samples per document (one batched
call) and caches each document vector by content + model, so only new or changed documents cost
anything on later runs. Accuracy is measured leave-one-out on the labelled set: each labelled
document is predicted as if it were unorganised, with centroids built from all the OTHER documents.
"""

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from agent_apunts.embeddings import Embedder
from agent_apunts.ingestion.manifest import DocumentRecord
from agent_apunts.metadata import DocType, year_from_filename

# Keywords per doc_type, accent-free lowercase, matched as whole words or word prefixes.
# Order matters: an "exam with exercises" is an exam.
_DOC_TYPE_KEYWORDS: list[tuple[DocType, tuple[str, ...]]] = [
    (DocType.EXAMS, ("exam", "parcial", "final", "recupera", "midterm", "prova")),
    (DocType.LABS, ("lab", "practica", "pract", "sessio de laboratori", "assignment")),
    (DocType.EXERCISES, ("exercic", "ejercic", "exercise", "problem", "llista", "seminari")),
    (DocType.THEORY, ("tema", "teoria", "theory", "slides", "apunts", "lecture", "unit")),
]


def _plain(text: str) -> str:
    """Lowercase, accents removed, separators to spaces: 'Pràctica_2' -> 'practica 2'."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text)


def _keyword_type(text: str) -> DocType | None:
    words = _plain(text)
    for doc_type, keywords in _DOC_TYPE_KEYWORDS:
        for keyword in keywords:
            if re.search(rf"\b{re.escape(keyword)}", words):
                return doc_type
    return None


def guess_doc_type(filename: str, first_page: str) -> tuple[DocType, str]:
    """(doc_type, where it came from): 'filename', 'first_page' or 'default'."""
    stem = filename.rsplit(".", 1)[0]
    if found := _keyword_type(stem):
        return found, "filename"
    if found := _keyword_type(first_page[:400]):  # header area: "Examen final", "Pràctica 3"
        return found, "first_page"
    return DocType.THEORY, "default"


def sample_texts(texts: list[str], k: int) -> list[str]:
    """Up to k texts spread evenly over the document (beginning, middle, end), not just the
    first pages, which are often a cover or an index."""
    if len(texts) <= k:
        return list(texts)
    step = (len(texts) - 1) / (k - 1) if k > 1 else 0
    return [texts[round(i * step)] for i in range(k)]


def _cache_key(model: str, texts: list[str]) -> str:
    return hashlib.sha256("\x00".join([model, *texts]).encode()).hexdigest()[:24]


def document_vectors(
    texts_by_doc: dict[str, list[str]], embedder: Embedder, cache_path: Path | None = None
) -> dict[str, np.ndarray]:
    """doc_id -> document vector. Cached by (model, sampled texts): unchanged documents are not
    re-embedded; the rest go to the embedder in one batched call."""
    cache: dict[str, list[float]] = {}
    if cache_path and cache_path.is_file():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    keys = {doc_id: _cache_key(embedder.model, texts) for doc_id, texts in texts_by_doc.items()}
    missing = [d for d in texts_by_doc if keys[d] not in cache]
    order = [(doc_id, t) for doc_id in missing for t in texts_by_doc[doc_id]]
    vectors = embedder.embed([t for _, t in order]) if order else []
    grouped: dict[str, list[list[float]]] = {}
    for (doc_id, _), vector in zip(order, vectors, strict=True):
        grouped.setdefault(doc_id, []).append(vector)
    for doc_id, vs in grouped.items():
        cache[keys[doc_id]] = [round(float(x), 6) for x in document_vector(vs)]
    if cache_path and grouped:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        live = {keys[d] for d in texts_by_doc}  # forget vectors of deleted/changed documents
        tmp = cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({k: v for k, v in cache.items() if k in live}), encoding="utf-8")
        tmp.replace(cache_path)
    return {d: np.array(cache[keys[d]], dtype=np.float32) for d in texts_by_doc if keys[d] in cache}


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vector)
    return vector / norm if norm else vector


def document_vector(chunk_vectors: list[list[float]]) -> np.ndarray:
    """One vector per document: the mean of its (normalised) chunk vectors."""
    matrix = np.array(chunk_vectors, dtype=np.float32)
    rows = matrix / np.clip(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12, None)
    return _unit(rows.mean(axis=0))


def subject_centroids(
    doc_vectors: dict[str, np.ndarray], labels: dict[str, str]
) -> dict[str, np.ndarray]:
    """subject -> normalised mean of its labelled documents' vectors. labels: doc_id -> subject."""
    by_subject: dict[str, list[np.ndarray]] = {}
    for doc_id, subject in labels.items():
        if doc_id in doc_vectors:
            by_subject.setdefault(subject, []).append(doc_vectors[doc_id])
    return {s: _unit(np.mean(vs, axis=0)) for s, vs in by_subject.items()}


def rank_subjects(vector: np.ndarray, centroids: dict[str, np.ndarray]) -> list[tuple[str, float]]:
    scores = [(s, float(np.dot(vector, c))) for s, c in centroids.items()]
    return sorted(scores, key=lambda sc: -sc[1])


@dataclass
class Detection:
    doc_id: str
    rel_path: str
    subject: str | None  # None: no centroid to compare with (no labelled documents yet)
    score: float
    margin: float  # best minus second-best similarity; confident if >= min_margin
    confident: bool
    doc_type: DocType
    doc_type_source: str
    academic_year: str | None


def detect(
    record: DocumentRecord,
    vector: np.ndarray | None,
    first_page: str,
    centroids: dict[str, np.ndarray],
    min_margin: float,
) -> Detection:
    filename = record.rel_path.rsplit("/", 1)[-1]
    doc_type, source = guess_doc_type(filename, first_page)
    ranking = rank_subjects(vector, centroids) if vector is not None and centroids else []
    subject, score = ranking[0] if ranking else (None, 0.0)
    # A margin needs a second subject: with only one there is nothing to rule out, so the guess
    # is never confident (margin 0), whatever the similarity.
    margin = score - ranking[1][1] if len(ranking) > 1 else 0.0
    return Detection(
        doc_id=record.doc_id,
        rel_path=record.rel_path,
        subject=subject,
        score=round(score, 4),
        margin=round(margin, 4),
        confident=subject is not None and margin >= min_margin,
        doc_type=doc_type,
        doc_type_source=source,
        academic_year=year_from_filename(filename),
    )


@dataclass
class DetectionEval:
    documents: int = 0
    subject_correct: int = 0
    doc_type_correct: int = 0
    confident: int = 0
    confident_correct: int = 0
    confusion: Counter[tuple[str, str]] = field(default_factory=Counter)  # (true, predicted)
    mistakes: list[tuple[str, str, str]] = field(default_factory=list)  # (path, true, predicted)

    def rate(self, part: int, whole: int) -> float:
        return round(part / whole, 3) if whole else 0.0


def evaluate_leave_one_out(
    labelled: list[DocumentRecord],
    doc_vectors: dict[str, np.ndarray],
    first_pages: dict[str, str],
    min_margin: float,
) -> DetectionEval:
    """Predict every labelled document as if it were unorganised, with centroids from the others."""
    labels = {r.doc_id: r.metadata.subject for r in labelled if r.metadata}
    result = DetectionEval()
    for record in labelled:
        if record.metadata is None or record.doc_id not in doc_vectors:
            continue
        others = {d: s for d, s in labels.items() if d != record.doc_id}
        centroids = subject_centroids(doc_vectors, others)
        guess = detect(
            record,
            doc_vectors[record.doc_id],
            first_pages.get(record.doc_id, ""),
            centroids,
            min_margin,
        )
        truth = record.metadata.subject
        result.documents += 1
        result.subject_correct += guess.subject == truth
        result.doc_type_correct += guess.doc_type == record.metadata.doc_type
        result.confident += guess.confident
        result.confident_correct += guess.confident and guess.subject == truth
        result.confusion[(truth, guess.subject or "-")] += 1
        if guess.subject != truth:
            result.mistakes.append((record.rel_path, truth, guess.subject or "-"))
    return result


def similar_pairs(
    doc_vectors: dict[str, np.ndarray], min_similarity: float
) -> list[tuple[str, str, float]]:
    """Document pairs whose vectors' cosine similarity is >= min_similarity, most similar first.
    Input to near-duplicate grouping (D19): translations, statement vs solutions, re-uploads."""
    ids = sorted(doc_vectors)
    if len(ids) < 2:
        return []
    matrix = np.array([doc_vectors[i] for i in ids])
    similarity = matrix @ matrix.T  # vectors are unit length: dot product = cosine
    pairs = [
        (ids[i], ids[j], round(float(similarity[i, j]), 4))
        for i in range(len(ids))
        for j in range(i + 1, len(ids))
        if similarity[i, j] >= min_similarity
    ]
    return sorted(pairs, key=lambda p: -p[2])


def group_pairs(pairs: list[tuple[str, str, float]]) -> list[set[str]]:
    """Connected groups of documents (if A~B and B~C, then {A, B, C}): union-find."""
    parent: dict[str, str] = {}

    def root(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]  # path halving keeps the trees flat
            x = parent[x]
        return x

    for a, b, _ in pairs:
        parent[root(a)] = root(b)
    groups: dict[str, set[str]] = {}
    for x in parent:
        groups.setdefault(root(x), set()).add(x)
    return list(groups.values())
