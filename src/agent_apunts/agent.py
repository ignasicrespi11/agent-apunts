"""Tool-using agent over the notes (D38, proposed; design in docs/design/phase-2-agent.md).

`ask` (D32) does one retrieval and one answer. Some questions need several searches or a choice
of filters ("compare what the 2023-24 and 2024-25 exams asked about signatures"), a listing
("which subjects do I have notes for?") or a direct lookup ("page 12 of slides_grasp"). Here the
model chooses tools, reads their results and decides again, within hard limits:

    system rules + tool schemas + question
    loop (at most agent.max_tool_calls tool calls):
        model -> tool calls?  run them (user_id injected), append results, continue
                 no calls     final answer
    limit reached -> one last turn WITHOUT tools: answer from what was found, or NOT_FOUND

Grounding is the same as `ask`: every chunk a tool returns gets a global number [n]; the answer
must cite them, citations are mapped back to (document, page), NOT_FOUND abstains. Two safety
properties hold whatever the model writes:
- `user_id` is never a tool argument: the runtime adds it, and Qdrant filters by it (CLAUDE.md).
  A prompt-injected document can't make the model read another user's notes.
- Chunks below retrieval.min_score are never shown to the model (the cheap gate of D32, per call).
"""

import json
import time
from dataclasses import dataclass, field

from agent_apunts.config import Settings
from agent_apunts.embeddings import Embedder
from agent_apunts.ingestion.manifest import Manifest
from agent_apunts.llm import ChatClient, ToolCall
from agent_apunts.metadata import DocType
from agent_apunts.rag import (
    NOT_FOUND,
    AgentStep,
    Answer,
    Source,
    _not_in_notes,
    is_not_found,
    parse_citations,
)
from agent_apunts.retrieval import search
from agent_apunts.store import Hit, VectorStore

AGENT_SYSTEM_PROMPT = f"""You answer a university student's questions about their own course \
material (slides, exams, exercises). You have tools to search the notes, list subjects and \
documents, and read a page.

Rules:
1. Facts must come only from tool results. Never add facts from your own knowledge.
2. For any question about course content, call search_notes first. Use its filters (subject, \
doc_type, academic_year) when the question names them. If the results don't answer, search again \
with other words or other filters.
3. Tool results number every source like [3]. After each sentence that uses a source, cite it with \
that exact number, e.g. [3] or [1][4].
4. Answer in the same language as the question (Catalan, Spanish or English).
5. If the notes don't contain the answer, reply with exactly {NOT_FOUND} and nothing else.
6. Be concise; keep formulas, names and code exactly as written in the sources."""

LIMIT_REACHED = (
    "Tool call limit reached. Answer now using only the sources above, citing their numbers, "
    f"or reply with exactly {NOT_FOUND}."
)


def tool_schemas(settings: Settings) -> list[dict]:
    """JSON-schema tool definitions (Ollama/OpenAI style). Enums come from the config, so the
    model can only name subjects and doc_types that exist; user_id is deliberately absent."""
    subjects = sorted(settings.subjects)
    doc_types = [d.value for d in DocType]

    def tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
        parameters = {"type": "object", "properties": properties, "required": required}
        return {
            "type": "function",
            "function": {"name": name, "description": description, "parameters": parameters},
        }

    subject = {"type": "string", "enum": subjects, "description": "Subject folder name."}
    doc_type = {"type": "string", "enum": doc_types, "description": "Kind of document."}
    return [
        tool(
            "search_notes",
            "Search the student's notes for passages about a topic. Returns numbered sources.",
            {
                "query": {"type": "string", "description": "What to look for, in any language."},
                "subject": subject,
                "doc_type": doc_type,
                "academic_year": {
                    "type": "string",
                    "description": "Year of the document, like 2024-25 (exams have one).",
                },
            },
            ["query"],
        ),
        tool("list_subjects", "List the subjects and how many documents of each kind.", {}, []),
        tool(
            "list_documents",
            "List document paths (subject/doc_type/file.pdf) with their year.",
            {"subject": subject, "doc_type": doc_type},
            [],
        ),
        tool(
            "get_page",
            "Read one page of a document. Returns numbered sources.",
            {
                "document": {"type": "string", "description": "Path from list_documents."},
                "page": {"type": "integer", "description": "Page number, from 1."},
            },
            ["document", "page"],
        ),
    ]


@dataclass
class NoteTools:
    """Runs the agent's tool calls for ONE user and keeps the sources they returned, numbered
    globally across calls (the same chunk keeps its first number)."""

    user_id: str
    settings: Settings
    embedder: Embedder
    store: VectorStore
    sources: list[Source] = field(default_factory=list)
    _numbers: dict[str, int] = field(default_factory=dict)
    _words_shown: int = 0  # source words sent to the model so far (agent.max_source_words)

    def run(self, call: ToolCall) -> tuple[str, str]:
        """(text for the model, short summary for the log). Bad arguments come back as text the
        model can read and correct; they never raise."""
        handlers = {
            "search_notes": self.search_notes,
            "list_subjects": self.list_subjects,
            "list_documents": self.list_documents,
            "get_page": self.get_page,
        }
        handler = handlers.get(call.name)
        if handler is None:
            return f"Unknown tool {call.name!r}.", "error: unknown tool"
        try:
            return handler(**_known(call.arguments, handler))
        except ValueError as e:
            return f"Error: {e}", f"error: {e}"

    # --- tools ----------------------------------------------------------------------------------

    def search_notes(
        self,
        query: str = "",
        subject: str | None = None,
        doc_type: str | None = None,
        academic_year: str | None = None,
    ) -> tuple[str, str]:
        if not str(query).strip():
            raise ValueError("search_notes needs a non-empty query")
        subject, doc_type = self._check_subject(subject), self._check_doc_type(doc_type)
        hits = search(
            str(query),
            self.user_id,
            self.embedder,
            self.store,
            self.settings.agent.max_chunks,
            subject,
            doc_type,
            hybrid=self.settings.retrieval.hybrid,
            academic_year=academic_year or None,
        )
        relevant = [h for h in hits if h.score >= self.settings.retrieval.min_score]
        if not relevant:
            return "No relevant notes found. Try other words or fewer filters.", "0 sources"
        return self._numbered(relevant)

    def list_subjects(self) -> tuple[str, str]:
        counts: dict[str, dict[str, int]] = {}
        for record in self._documents():
            if record.metadata:
                by_type = counts.setdefault(record.metadata.subject, {})
                kind = record.metadata.doc_type.value
                by_type[kind] = by_type.get(kind, 0) + 1
        lines = []
        for slug, subject in sorted(self.settings.subjects.items()):
            kinds = ", ".join(f"{n} {t}" for t, n in sorted(counts.get(slug, {}).items()))
            lines.append(f"- {slug} ({subject.name}): {kinds or 'no documents'}")
        return "\n".join(lines), f"{len(lines)} subjects"

    def list_documents(
        self, subject: str | None = None, doc_type: str | None = None
    ) -> tuple[str, str]:
        subject, doc_type = self._check_subject(subject), self._check_doc_type(doc_type)
        lines = []
        for record in self._documents():
            meta = record.metadata
            if subject and (meta is None or meta.subject != subject):
                continue
            if doc_type and (meta is None or meta.doc_type.value != doc_type):
                continue
            year = f" ({meta.academic_year})" if meta and meta.academic_year else ""
            lines.append(f"- {record.rel_path}{year}")
        if not lines:
            return "No documents match.", "0 documents"
        shown = lines[:60]  # a long listing would fill the context: ask for a filter instead
        more = (
            f"\n... and {len(lines) - 60} more: filter by subject or doc_type."
            if len(lines) > 60
            else ""
        )
        return "\n".join(shown) + more, f"{len(lines)} documents"

    def get_page(self, document: str = "", page: int | str = 0) -> tuple[str, str]:
        try:
            number = int(page)
        except (TypeError, ValueError) as e:
            raise ValueError(f"page must be a number, got {page!r}") from e
        hits = self.store.page_chunks(self.user_id, str(document), number)
        if not hits:
            raise ValueError(
                f"no page {number} in {document!r} (use a path exactly as list_documents shows it)"
            )
        return self._numbered(hits)

    # --- helpers --------------------------------------------------------------------------------

    def _numbered(self, hits: list[Hit]) -> tuple[str, str]:
        """Number the hits globally and render them for the model, within the word budget.
        A chunk already shown keeps its number and is not sent again (it is in the context)."""
        budget = self.settings.agent.max_source_words
        blocks, numbers = [], []
        for hit in hits:
            p = hit.payload
            n = self._numbers.get(hit.chunk_id)
            if n is not None:
                blocks.append(f"[{n}] (already shown above)")
                numbers.append(n)
                continue
            text = p.get("text", "")
            words = len(text.split())
            if self._words_shown + words > budget:
                blocks.append(
                    "Source budget for this question reached: answer with the sources above."
                )
                break
            self._words_shown += words
            n = len(self.sources) + 1
            self._numbers[hit.chunk_id] = n
            self.sources.append(
                Source(
                    number=n,
                    chunk_id=hit.chunk_id,
                    score=round(hit.score, 4),
                    rel_path=p.get("rel_path", "?"),
                    page=p.get("page", 0),
                    subject=p.get("subject"),
                    title=p.get("title"),
                )
            )
            numbers.append(n)
            blocks.append(f"[{n}] {p.get('header', '')} (page {p.get('page')})\n{text}")
        if not numbers:
            return blocks[0] if blocks else "No sources.", "0 sources (budget reached)"
        summary = f"{len(numbers)} sources " + " ".join(f"[{n}]" for n in numbers)
        return "\n\n".join(blocks), summary

    def _documents(self):
        with Manifest(self.settings.paths.manifest) as manifest:
            return manifest.documents(self.user_id)

    def _check_subject(self, subject: str | None) -> str | None:
        if subject and subject not in self.settings.subjects:
            known = ", ".join(sorted(self.settings.subjects))
            raise ValueError(f"unknown subject {subject!r} (known: {known})")
        return subject or None

    def _check_doc_type(self, doc_type: str | None) -> str | None:
        known = [d.value for d in DocType]
        if doc_type and doc_type not in known:
            raise ValueError(f"unknown doc_type {doc_type!r} (known: {', '.join(known)})")
        return doc_type or None


def _known(arguments: dict, handler) -> dict:
    """Only the arguments the tool accepts: an invented one (or a "user_id") is dropped."""
    accepted = handler.__code__.co_varnames[1 : handler.__code__.co_argcount]
    return {k: v for k, v in arguments.items() if k in accepted}


def run_agent(
    question: str,
    user_id: str,
    settings: Settings,
    embedder: Embedder,
    store: VectorStore,
    llm: ChatClient,
) -> Answer:
    """Answer with tools, under the agent limits. Same Answer as `ask`, with mode="agent" and
    the tool calls in `steps`; logged the same way (D33)."""
    tools = NoteTools(user_id, settings, embedder, store)
    schemas = tool_schemas(settings)
    messages: list[dict] = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    steps: list[AgentStep] = []
    latency = 0
    max_prompt, output_tokens = None, None
    start = time.perf_counter()
    final = ""
    model = getattr(llm, "model", None)

    while True:
        limit_reached = len(steps) >= settings.agent.max_tool_calls
        if limit_reached:
            messages.append({"role": "user", "content": LIMIT_REACHED})
        response = llm.chat(messages, None if limit_reached else schemas)
        model = response.model
        if response.prompt_tokens is not None:
            max_prompt = max(max_prompt or 0, response.prompt_tokens)
        if response.output_tokens is not None:
            output_tokens = (output_tokens or 0) + response.output_tokens
        if limit_reached or not response.tool_calls:
            final = response.text
            break
        messages.append(
            {
                "role": "assistant",
                "content": response.text,
                "tool_calls": [
                    {"function": {"name": c.name, "arguments": c.arguments}}
                    for c in response.tool_calls
                ],
            }
        )
        for call in response.tool_calls:
            if len(steps) >= settings.agent.max_tool_calls:
                result, summary = "Not run: tool call limit reached.", "skipped: limit"
            else:
                result, summary = tools.run(call)
                steps.append(AgentStep(tool=call.name, arguments=call.arguments, result=summary))
            messages.append({"role": "tool", "content": result, "tool_name": call.name})
    latency = int((time.perf_counter() - start) * 1000)

    base = {
        "user_id": user_id,
        "question": question,
        "filters": {},
        "sources": tools.sources,
        "model": model,
        "latency_ms": latency,
        "prompt_tokens": max_prompt,
        "output_tokens": output_tokens,
        "context_near_limit": (max_prompt or 0) >= 0.9 * settings.llm.num_ctx,
        "mode": "agent",
        "steps": steps,
    }
    if not final.strip() or is_not_found(final):
        reason = "no_results" if not tools.sources else "not_found"
        return Answer(
            **base,
            answer=_not_in_notes(question, settings),
            abstained=True,
            reason=reason,
            cited=[],
        )
    cited = parse_citations(final, len(tools.sources))
    # Uncited is suspicious only when there were sources to cite, or when no tool was used at all
    # (an answer from the model's own knowledge). A pure listing answer has nothing to cite.
    content_tools = any(s.tool in ("search_notes", "get_page") for s in steps)
    uncited = not cited and (bool(tools.sources) or content_tools or not steps)
    return Answer(**base, answer=final, abstained=False, cited=cited, uncited=uncited)


def describe_tools(settings: Settings) -> str:
    """The tool schemas as pretty JSON (for docs and debugging)."""
    return json.dumps(tool_schemas(settings), indent=2, ensure_ascii=False)
