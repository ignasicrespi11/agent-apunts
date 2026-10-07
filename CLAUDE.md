# CLAUDE.md — agent-apunts

Loaded at the start of every session. Keep it short: every line costs quota.

## What this project is
A RAG-based AI agent over Ignasi's university notes (Computer Engineering, UAB). It answers questions
grounded in, and citing, the professors' own material. It's a portfolio project for the MEMEnginy job fair (18 Mar 2027).
Built for one user first, and designed to later scale to other degrees, universities and users.

## Who you are working with
- Ignasi: CS student with a systems/networking/IT-admin background. Not yet advanced in Python, DL or agents.
- His future role is directing and reviewing AI-written code. So, always:
  1. Explain each design decision in simple terms, and why, **before** implementing it. Wait for his OK on structural choices.
  2. Say exactly which file each piece of code goes in.
  3. Point out where your output could be wrong and give him a concrete way to check it (a command, a test, a doc link).
  4. Teach the concept behind the code briefly (Python, LLMs, embeddings, RAG, evaluation, data organization).
- Chat language: follow his language (Catalan/Spanish/English). **All repo content (code, comments, docs, commits) in English.**

## Non-negotiable architecture rules
- Every document carries metadata: university, degree, subject, professor, academic_year, doc_type (validated by one Pydantic model).
- `user_id` is on every chunk, query, response and log entry. It's passed explicitly as a parameter, never a global. For now it's a fixed value from config.
- User/subject filtering happens **inside the vector DB query** (a Qdrant filter), never after retrieval.
- No hardcoded subjects, paths, universities or model names. They come from `config/*.yaml` and `.env`.
- Ingestion is modular: one loader per file format, registered by extension.
- Chunk IDs are deterministic (hash of user_id + doc_id + index + content; doc_id, not path, so moves keep IDs), so re-ingesting is idempotent.
- The embedding model used for ingestion and for queries must be the same. It's stored in config and in the collection metadata.
- Pipeline is staged and incremental (register → extract → clean → chunk → index); intermediate outputs in `data/`. Queries never read PDFs.
- Metadata auto-detection (D18, week 4+): folder name wins if present; manual folders are the ground truth to measure it.
- Chunking (D13, D26): size decides — page ≤ 450 words = 1 chunk, longer pages split by paragraphs (~350 words); page number + contextual header always. Answers only from retrieved notes, with citations; abstain if nothing relevant.
- **Course material is copyrighted: never commit PDFs, processed text, thumbnails or `data/`.** Test fixtures must be self-generated.
- Out of scope (roadmap only): authentication, billing/quotas, distributed deployment.

## Stack
Python 3.12 · uv · Qdrant (Docker) · PyMuPDF · local multilingual embeddings (bge-m3) ·
`LLMClient` interface (Ollama local now → Claude API later) · Typer CLI → FastAPI + Streamlit (phase 2) · pytest.
No LangChain/LlamaIndex. The RAG pipeline is hand-written so every line can be defended in interviews.
Full rationale: `docs/ARCHITECTURE.md`.

## Layout
- `src/agent_apunts/`: code (ingestion/loaders, chunking, embeddings, store, retrieval, llm, rag, agent, cli)
- `config/`: settings.yaml, sources.yaml · `apunts/`: real PDFs (inbox) · `testing/apunts_testing/<subject>/<doc_type>/`: manually labelled PDFs (dev corpus + ground truth) · `data/`: processed outputs (both **gitignored, never commit**)
- `eval/`: golden set + eval scripts · `tests/`: pytest · `docs/`: architecture, code tour, weekly summaries

## Commands
- New machine: `scripts/setup-windows.ps1` or `scripts/setup-omarchy.sh` (see `docs/SETUP.md`); they also enable the pre-commit hook

## Session workflow (use the whole token budget, document every why)
- Start: read this file + `TODO.md` only. Don't scan the whole repo unless the task needs it.
- A session's goal is to **use its token budget fully**, not to be short: chain tasks from `TODO.md` in order.
  Approve the structural decisions up front (one batch of questions), then work through them.
- One commit per task; small, reviewable diffs. Run the tests before saying something works.
- Every decision is documented with its **why** and the rejected alternative: `docs/ARCHITECTURE.md` (decision table)
  for design choices, the commit message for smaller ones, a short comment in code only when the why isn't obvious.
- Git: code changes go on a branch `feat/<topic>` (or `fix/`, `test/`) and end with a PR (`gh pr create`) with a clear description; Ignasi reviews the diff and merges on GitHub. Small docs-only changes may go straight to `main`.
- End: update `TODO.md` (tick tasks, next step, one line in the Session log). Commit with a clear message.
- Sunday: write `docs/weekly/week-NN.md` ("what we built and why" + 1–2 CV bullets). Use `/weekly-summary`.
- Models — rule of thumb: **task creates a new interface/pattern → Opus; task follows an existing pattern → Sonnet.**
  Opus: foundations (config + metadata model, loader interface/registry, manifest, store/LLM interfaces), agent and eval design, final review.
  Sonnet: new loaders, CLI commands, tests, bug fixes, UI. Switch to Sonnet anyway if quota gets tight. Haiku for docs/formatting/cleanup. Within a long session, follow the plan agreed at the start.

## Calendar
No work 26–30 Oct 2026 or 23 Dec 2026–29 Jan 2027 (exams). Phase dates are in `TODO.md`.
