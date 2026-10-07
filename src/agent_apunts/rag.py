"""Grounded question answering: retrieve, decide whether to answer, answer with citations (D32).

    question -> embed -> Qdrant (user/subject filter) -> best score < min_score? -> abstain
             -> numbered sources + rules -> LLM -> "NOT_FOUND"? -> abstain
             -> answer + [n] citations mapped back to (document, page)

"Answer only from the notes" cannot be guaranteed 100%; it is made likely (strict prompt, cheap
score gate, model's own NOT_FOUND) and checkable (every claim points to a page). The eval measures
it (D34). Every answer is logged with its user_id (D33).
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from agent_apunts.config import Settings
from agent_apunts.embeddings import Embedder
from agent_apunts.ingestion.language import detect_language
from agent_apunts.llm import LLMClient
from agent_apunts.retrieval import search
from agent_apunts.store import Hit, VectorStore

NOT_FOUND = "NOT_FOUND"

SYSTEM_PROMPT = f"""You answer a university student's questions using ONLY excerpts from their own \
course material (slides, exams, exercises), given as numbered sources.

Rules:
1. Use only the information in the sources. Never add facts from your own knowledge.
2. After each sentence that uses a source, cite it with its number in brackets, e.g. [2] or [1][3].
3. Answer in the same language as the question (Catalan, Spanish or English).
4. If the sources do not contain the answer, reply with exactly {NOT_FOUND} and nothing else.
5. Be concise and precise; keep formulas, names and code exactly as written in the sources."""

# Shown when abstaining, in the question's language.
NOT_IN_NOTES = {
    "ca": "No ho he trobat als teus apunts.",
    "es": "No lo he encontrado en tus apuntes.",
    "en": "I couldn't find this in your notes.",
}

AbstainReason = Literal["no_results", "low_score", "not_found"]


class Source(BaseModel):
    number: int  # [n] as shown to the LLM
    chunk_id: str
    score: float
    rel_path: str
    page: int
    subject: str | None
    title: str | None


class Answer(BaseModel):
    user_id: str
    question: str
    filters: dict[str, str]
    answer: str  # the model's answer, or the "not in your notes" message when abstaining
    abstained: bool
    reason: AbstainReason | None = None
    sources: list[Source]  # everything retrieved, in rank order
    cited: list[int]  # source numbers the answer actually cites, in order of first use
    uncited: bool = False  # answered but cited nothing valid: treat with suspicion
    model: str | None = None
    latency_ms: int = 0


def format_sources(hits: list[Hit]) -> str:
    blocks = []
    for n, hit in enumerate(hits, start=1):
        p = hit.payload
        blocks.append(f"[{n}] {p.get('header', '')} (page {p.get('page')})\n{p.get('text', '')}")
    return "\n\n".join(blocks)


def build_user_prompt(question: str, hits: list[Hit]) -> str:
    return f"Sources:\n\n{format_sources(hits)}\n\nQuestion: {question}"


# A citation bracket must not follow a name, digit or closing paren: "v[1]", "buf[2]", "f(x)[0]"
# are code. It may follow another citation: "[1][3]".
_CITATION = re.compile(r"(?<![\w)])\[([\d,\s]+)\]")


def parse_citations(text: str, n_sources: int) -> list[int]:
    """Source numbers cited as [n] (also [1, 3] or [1][3]), valid ones only, first use first."""
    cited: list[int] = []
    for group in _CITATION.findall(text):
        for number in re.findall(r"\d+", group):
            n = int(number)
            if 1 <= n <= n_sources and n not in cited:
                cited.append(n)
    return cited


def is_not_found(text: str) -> bool:
    """The model's "the sources don't say", tolerating how models actually write it:
    **NOT_FOUND**, `NOT_FOUND`, "NOT FOUND", or a short sentence ending with it."""
    plain = re.sub(r"[*`_\s.!]+", " ", text).strip().upper()
    return plain.startswith("NOT FOUND") or plain.endswith("NOT FOUND")


def _sources(hits: list[Hit]) -> list[Source]:
    return [
        Source(
            number=n,
            chunk_id=h.chunk_id,
            score=round(h.score, 4),
            rel_path=h.payload.get("rel_path", "?"),
            page=h.payload.get("page", 0),
            subject=h.payload.get("subject"),
            title=h.payload.get("title"),
        )
        for n, h in enumerate(hits, start=1)
    ]


def _not_in_notes(question: str, settings: Settings) -> str:
    # Questions are short ("Què és un TLB?"): a lower bar than for pages, and if still unsure,
    # the user's first configured language rather than English.
    language = detect_language(question, tuple(settings.languages), min_chars=5, min_confidence=0.5)
    return NOT_IN_NOTES.get(language or settings.languages[0], NOT_IN_NOTES["en"])


def ask(
    question: str,
    user_id: str,
    settings: Settings,
    embedder: Embedder,
    store: VectorStore,
    llm: LLMClient,
    subject: str | None = None,
    doc_type: str | None = None,
) -> Answer:
    filters = {k: v for k, v in {"subject": subject, "doc_type": doc_type}.items() if v}
    hits = search(
        question,
        user_id,
        embedder,
        store,
        settings.retrieval.top_k,
        subject,
        doc_type,
        hybrid=settings.retrieval.hybrid,
    )
    base = {"user_id": user_id, "question": question, "filters": filters, "sources": _sources(hits)}

    # Gate 1 (cheap): nothing similar enough in the notes -> don't spend LLM time. max(), not the
    # first hit: with hybrid search the top-ranked chunk isn't always the most similar one.
    if not hits or max(h.score for h in hits) < settings.retrieval.min_score:
        reason: AbstainReason = "no_results" if not hits else "low_score"
        message = _not_in_notes(question, settings)
        return Answer(**base, answer=message, abstained=True, reason=reason, cited=[])

    response = llm.complete(SYSTEM_PROMPT, build_user_prompt(question, hits))
    # Gate 2: the model read the sources and says they don't answer the question.
    if is_not_found(response.text):
        return Answer(
            **base,
            answer=_not_in_notes(question, settings),
            abstained=True,
            reason="not_found",
            cited=[],
            model=response.model,
            latency_ms=response.latency_ms,
        )
    cited = parse_citations(response.text, len(hits))
    return Answer(
        **base,
        answer=response.text,
        abstained=False,
        cited=cited,
        uncited=not cited,
        model=response.model,
        latency_ms=response.latency_ms,
    )


def log_answer(answer: Answer, logs_dir: Path) -> Path:
    """Append one JSON line to logs/queries.jsonl (D33). Returns the log file path."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / "queries.jsonl"
    record = {"timestamp": datetime.now(UTC).isoformat(timespec="seconds"), **answer.model_dump()}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path
