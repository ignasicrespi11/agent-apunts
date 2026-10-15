# Phase 2 design proposal: the agent, the API and the UI

Status: **proposal, 2026-10-08** (written during an autonomous session; nothing here is built).
To be discussed and approved by Ignasi before implementation (TODO, phase 2: "Agent design
session (Opus)"). Free, local tools only.

## 1. Why an agent at all

`ask` (D32) is single-shot: one retrieval, one answer. It is the right tool for "what does the
Creator pattern say?". It cannot handle questions that need **several searches or a choice of
filters**:

- "Compare what the 2023-24 and 2024-25 IS exams asked about digital signatures."
  (two searches, each filtered by document year)
- "Which subjects do I have notes for, and how many exams of each?" (no search: a listing)
- "Show me page 12 of slides_grasp." (direct lookup, no similarity involved)
- "Is the Observer pattern in my Disseny exams?" (search restricted to doc_type=exams)

An agent lets the LLM decide which tool to call, read the result and decide again, up to a limit.

## 2. Tools (proposed)

| Tool | Arguments (chosen by the model) | Returns |
|---|---|---|
| `search_notes` | `query`, optional `subject`, `doc_type`, `academic_year`, `k` (≤ 8) | numbered chunks: `[n] subject · document · p. N` + text |
| `list_subjects` | — | subjects with document counts per doc_type |
| `list_documents` | optional `subject`, `doc_type` | document paths, years, page counts |
| `get_page` | `document`, `page` | that page's cleaned text |

**`user_id` is never a tool argument.** The runtime adds it to every call from the session
(D7). The model can't pick another user's notes, even if a prompt-injected document asks it to:
the filter is still applied inside Qdrant (CLAUDE.md).

## 3. The loop

```
system rules (same grounding rules as D32) + tool schemas + question
loop, at most 4 tool calls:
    model -> tool call?  yes: run it (user_id injected), append result, continue
                         no:  final answer
final answer must cite [n] from the sources collected across ALL tool calls
(global numbering); none valid -> uncited flag; no sources at all -> abstain (D32)
```

- Ollama's `/api/chat` supports native tool calling (`tools` field) for models such as
  qwen2.5. If the configured model doesn't support tools, fall back to `ask` (single-shot).
- Hard limits: 4 tool calls, 8 chunks per search, total context under `num_ctx`.
- Every step (tool, arguments, result IDs, latency) goes to the query log (D33), so failures
  can be read afterwards.

## 4. How we will know it helps (eval first, D8)

- Add ~10 **multi-step questions** to `eval/golden.yaml` with tag `multi-step`.
- Run `eval --answers` for `ask` and for the agent on the same set. Compare abstention accuracy,
  citation hit and precision, and latency, per tag. The agent is worth keeping only if it wins
  on `multi-step` without losing on the simple questions.
- Expected risk: 7B local models are mediocre at tool use (wrong arguments, loops). The limits
  above bound the damage; the eval shows the real rate. The GTX 1080 PC is the reference machine.

## 5. API and UI (after the agent works in the CLI)

**FastAPI** (thin layer, same library functions the CLI calls: D9):

| Endpoint | Calls |
|---|---|
| `POST /ask` `{question, subject?, mode: "rag" \| "agent"}` | `rag.ask` / agent |
| `POST /search` `{query, subject?, doc_type?, hybrid?}` | `retrieval.search` |
| `GET /subjects`, `GET /documents` | manifest |
| `GET /documents/{doc_id}/pages/{n}/thumbnail` | `data/thumbnails/...` (cited slide preview) |
| `POST /upload` | saves to `apunts/` inbox, runs `ingest` in the background |

`user_id` comes from config for now (authentication is out of scope); every handler passes it
explicitly, so adding auth later only changes where it comes from (D7).

**Streamlit** chat page: question box, answer with clickable `[n]` citations showing the cited
page's thumbnail, the subject filter, and an upload box. Detection suggestions (D36) for uploaded
PDFs appear as "confirm subject" before indexing.

## 6. Order of work (proposed)

1. Agent loop + tools + tests with a scripted fake model (like `ScriptedLLM`).
2. Multi-step golden questions; `eval --answers --mode agent`.
3. Decide on the agent with numbers; then FastAPI, then Streamlit.
4. In parallel, measurement-driven retrieval work already prepared: OCR stage if `images` shows a
   real gap (D30), near-duplicate collapsing if `duplicates` shows real groups (D19), hybrid on
   or off from `eval --hybrid` (D37).

## 7. Decisions needed from Ignasi

1. Agree on the 4 tools (any missing, e.g. "summarise a whole document"?).
2. Agent limits: 4 tool calls / 8 chunks: fine for a 7B model on the GTX 1080?
3. API before UI, or a Streamlit-only demo first (faster to show, less to defend)?
