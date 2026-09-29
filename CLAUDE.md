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
- Chunk IDs are deterministic (hash of user_id + path + index + content), so re-ingesting is idempotent.
- The embedding model used for ingestion and for queries must be the same. It's stored in config and in the collection metadata.
- Pipeline is staged and incremental (register → extract → clean → chunk → index); intermediate outputs in `data/`. Queries never read PDFs.
- Metadata auto-detection (D18, week 4+): folder name wins if present; manual folders are the ground truth to measure it.
- Chunk unit = one slide, with a contextual header. Answers only from retrieved notes, with citations; abstain if nothing relevant.
- **Course material is copyrighted: never commit PDFs, processed text, thumbnails or `data/`.** Test fixtures must be self-generated.
- Out of scope (roadmap only): authentication, billing/quotas, distributed deployment.

## Stack
Python 3.12 · uv · Qdrant (Docker) · PyMuPDF · local multilingual embeddings (bge-m3) ·
`LLMClient` interface (Ollama local now → Claude API later) · Typer CLI → FastAPI + Streamlit (phase 2) · pytest.
No LangChain/LlamaIndex. The RAG pipeline is hand-written so every line can be defended in interviews.
Full rationale: `docs/ARCHITECTURE.md`.

## Layout
- `src/notes_agent/`: code (ingestion/loaders, chunking, embeddings, store, retrieval, llm, rag, agent, cli)
- `config/`: settings.yaml, sources.yaml · `notes/<subject>/<doc_type>/`: raw PDFs · `data/`: processed outputs (both **gitignored, never commit**)
- `eval/`: golden set + eval scripts · `tests/`: pytest · `docs/`: architecture, weekly summaries

## Commands
- New machine: `scripts/setup-windows.ps1` or `scripts/setup-omarchy.sh` (see `docs/SETUP.md`); they also enable the pre-commit hook

## Session workflow (quota-efficient)
- Start: read this file + `TODO.md` only. Don't scan the whole repo unless the task needs it.
- One task per session. Prefer small diffs. Run the tests before saying something works.
- End: update `TODO.md` (tick tasks, next step, one line in the Session log). Commit with a clear message.
- Sunday: write `docs/weekly/week-NN.md` ("what we built and why" + 1–2 CV bullets). Use `/weekly-summary`.
- Models: Sonnet by default. Opus only for structural decisions (architecture, agent design, final review, interview summary). Haiku for docs/formatting/cleanup.

## Calendar
No work 26–30 Oct 2026 or 23 Dec 2026–29 Jan 2027 (exams). Phase dates are in `TODO.md`.
