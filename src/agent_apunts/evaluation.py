"""Retrieval evaluation against a golden set (D8, D34).

Measures the retrieval half of RAG (no LLM: fast, free, deterministic), so every change to
cleaning, chunking, OCR (D30) or the model gets a before/after number:

- hit@k: share of answerable questions with a correct chunk among the first k results.
- MRR (mean reciprocal rank): average of 1/rank of the first correct chunk (0 if none in top-k).
  1.0 = always first; 0.5 = typically second. Rewards ranking the right page high.
- Abstention (the score gate of D32): unanswerable questions should score below min_score
  (correct abstention), answerable ones above it (no false abstention). `sweep` tries thresholds.
"""

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from agent_apunts.config import Settings
from agent_apunts.embeddings import Embedder
from agent_apunts.store import Hit, VectorStore


class Expected(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: str  # rel_path as shown by `inspect`, e.g. disseny_software/theory/slides_grasp.pdf
    pages: list[int] = Field(default_factory=list)  # empty = any page of the document counts


class GoldenQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    language: str  # ca / es / en: results are broken down by it (cross-lingual retrieval, D3)
    subject: str | None = None  # for the breakdown; with --filter-subject also a query filter
    answerable: bool = True
    expected: list[Expected] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)  # e.g. code-image (D30), formula, definition


class GoldenSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[GoldenQuestion]


def load_golden(path: Path) -> GoldenSet:
    golden = GoldenSet.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    ids = [q.id for q in golden.questions]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate question ids: {sorted(duplicates)}")
    for q in golden.questions:
        if q.answerable and not q.expected:
            raise ValueError(f"{q.id}: answerable questions need at least one expected document")
    return golden


def first_correct_rank(hits: list[Hit], expected: list[Expected]) -> int | None:
    """1-based rank of the first hit matching any expected (document, page), or None."""
    for rank, hit in enumerate(hits, start=1):
        for e in expected:
            if hit.payload.get("rel_path") == e.document and (
                not e.pages or hit.payload.get("page") in e.pages
            ):
                return rank
    return None


class QuestionResult(BaseModel):
    id: str
    language: str
    subject: str | None
    tags: list[str]
    answerable: bool
    rank: int | None  # None: no correct chunk in the top-k (or unanswerable)
    best_score: float | None
    top: list[str]  # "rel_path p.N (score)" of the retrieved chunks, for reading failures


def run_questions(
    golden: GoldenSet,
    user_id: str,
    embedder: Embedder,
    store: VectorStore,
    k: int,
    filter_subject: bool = False,
    hybrid: bool = False,
) -> list[QuestionResult]:
    # One batched embedding call for all questions: much faster than one call each.
    vectors = embedder.embed([q.question for q in golden.questions])
    results = []
    for q, vector in zip(golden.questions, vectors, strict=True):
        subject = q.subject if filter_subject else None
        hits = store.search(
            user_id, vector, limit=k, subject=subject, query_text=q.question if hybrid else None
        )
        results.append(
            QuestionResult(
                id=q.id,
                language=q.language,
                subject=q.subject,
                tags=q.tags,
                answerable=q.answerable,
                rank=first_correct_rank(hits, q.expected) if q.answerable else None,
                best_score=round(max(h.score for h in hits), 4) if hits else None,
                top=[
                    f"{h.payload.get('rel_path')} p.{h.payload.get('page')} ({h.score:.3f})"
                    for h in hits
                ],
            )
        )
    return results


class Metrics(BaseModel):
    questions: int
    hit_at: dict[int, float]  # k -> hit rate
    mrr: float


def metrics(results: list[QuestionResult], ks: tuple[int, ...]) -> Metrics:
    answerable = [r for r in results if r.answerable]
    n = len(answerable)
    if n == 0:
        return Metrics(questions=0, hit_at={k: 0.0 for k in ks}, mrr=0.0)
    hit_at = {k: sum(r.rank is not None and r.rank <= k for r in answerable) / n for k in ks}
    mrr = sum(1 / r.rank for r in answerable if r.rank) / n
    return Metrics(
        questions=n, hit_at={k: round(v, 3) for k, v in hit_at.items()}, mrr=round(mrr, 3)
    )


def breakdown(results: list[QuestionResult], ks: tuple[int, ...]) -> dict[str, dict[str, Metrics]]:
    """Metrics per language, per subject and per tag (a question can have several tags)."""
    groups: dict[str, dict[str, list[QuestionResult]]] = {
        "language": defaultdict(list),
        "subject": defaultdict(list),
        "tag": defaultdict(list),
    }
    for r in results:
        groups["language"][r.language].append(r)
        groups["subject"][r.subject or "-"].append(r)
        for tag in r.tags:
            groups["tag"][tag].append(r)
    return {
        name: {key: metrics(items, ks) for key, items in sorted(by.items())}
        for name, by in groups.items()
    }


class Abstention(BaseModel):
    threshold: float
    correct_abstention: float | None  # unanswerable questions that would abstain (want 1.0)
    false_abstention: float | None  # answerable questions that would abstain (want 0.0)
    balanced: float | None  # mean of correct_abstention and (1 - false_abstention)


def abstention(results: list[QuestionResult], threshold: float) -> Abstention:
    def rate(items: list[QuestionResult]) -> float | None:
        if not items:
            return None
        return round(sum((r.best_score or 0.0) < threshold for r in items) / len(items), 3)

    correct = rate([r for r in results if not r.answerable])
    false = rate([r for r in results if r.answerable])
    balanced = (
        round((correct + (1 - false)) / 2, 3) if correct is not None and false is not None else None
    )
    return Abstention(
        threshold=threshold, correct_abstention=correct, false_abstention=false, balanced=balanced
    )


def sweep(results: list[QuestionResult]) -> list[Abstention]:
    """Abstention quality for thresholds 0.20, 0.25, ... 0.80: pick min_score from the best row."""
    return [abstention(results, round(0.20 + 0.05 * i, 2)) for i in range(13)]


def save_run(
    settings: Settings,
    results: list[BaseModel],
    summary: dict,
    out_dir: Path,
    kind: str = "retrieval",
) -> Path:
    """Write the run with the settings that produced it, so two runs can be compared later."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{kind}-{stamp}.json"
    run = {
        "timestamp": stamp,
        "settings": {
            "embedding": settings.embedding.model_dump(),
            "chunking": settings.chunking.model_dump(),
            "cleaning": settings.cleaning.model_dump(),
            "retrieval": settings.retrieval.model_dump(),
            "llm": settings.llm.model_dump(),
            "collection": settings.qdrant.collection,
        },
        "summary": summary,
        "results": [r.model_dump() for r in results],
    }
    path.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# --- End-to-end answers (D32): needs the LLM, so slower; still no judge model -----------------


class AnswerResult(BaseModel):
    id: str
    answerable: bool
    abstained: bool
    reason: str | None
    cited: list[str]  # "rel_path p.N" of the cited sources
    cited_expected: int  # how many cited sources are an expected (document, page)
    uncited: bool
    latency_ms: int
    answer: str


class AnswerMetrics(BaseModel):
    questions: int
    abstention_accuracy: float  # answered the answerable ones, abstained on the others
    false_abstentions: int  # answerable questions it refused
    missed_abstentions: int  # unanswerable questions it answered anyway (the dangerous case)
    citation_hit: float  # answered + answerable: share citing at least one expected page
    citation_precision: float  # share of all citations that point to an expected page
    uncited: int  # answers that cite nothing valid
    mean_latency_s: float


def _matches(source, expected: list[Expected]) -> bool:
    return any(
        source.rel_path == e.document and (not e.pages or source.page in e.pages) for e in expected
    )


def run_answers(
    golden: GoldenSet,
    user_id: str,
    settings: Settings,
    embedder: Embedder,
    store: VectorStore,
    llm,  # LLMClient (imported lazily to keep this module free of the LLM for retrieval runs)
    filter_subject: bool = False,
    on_answer=None,  # progress callback: answers take seconds each
) -> list[AnswerResult]:
    from agent_apunts.rag import ask

    results = []
    for q in golden.questions:
        subject = q.subject if filter_subject else None
        a = ask(q.question, user_id, settings, embedder, store, llm, subject=subject)
        cited = [s for s in a.sources if s.number in a.cited]
        results.append(
            AnswerResult(
                id=q.id,
                answerable=q.answerable,
                abstained=a.abstained,
                reason=a.reason,
                cited=[f"{s.rel_path} p.{s.page}" for s in cited],
                cited_expected=sum(_matches(s, q.expected) for s in cited),
                uncited=a.uncited,
                latency_ms=a.latency_ms,
                answer=a.answer,
            )
        )
        if on_answer:
            on_answer(results[-1])
    return results


def answer_metrics(results: list[AnswerResult]) -> AnswerMetrics:
    n = len(results)
    correct_abstention = sum(r.abstained != r.answerable for r in results)
    answered = [r for r in results if r.answerable and not r.abstained]
    citations = sum(len(r.cited) for r in answered)
    return AnswerMetrics(
        questions=n,
        abstention_accuracy=round(correct_abstention / n, 3) if n else 0.0,
        false_abstentions=sum(r.answerable and r.abstained for r in results),
        missed_abstentions=sum(not r.answerable and not r.abstained for r in results),
        citation_hit=round(sum(r.cited_expected > 0 for r in answered) / len(answered), 3)
        if answered
        else 0.0,
        citation_precision=round(sum(r.cited_expected for r in answered) / citations, 3)
        if citations
        else 0.0,
        uncited=sum(r.uncited for r in results if not r.abstained),
        mean_latency_s=round(sum(r.latency_ms for r in results) / n / 1000, 1) if n else 0.0,
    )
