# TODO

Current: **Phase 1 · Week 1 (29 Sep – 5 Oct 2026)**

## Now — Week 1: foundations
- [x] Architecture proposal (Opus) → `docs/ARCHITECTURE.md`
- [x] CLAUDE.md, TODO.md, README, .gitignore, .gitattributes, Claude Code project settings
- [ ] Install toolchain on Windows (git, gh, uv, VS Code, Docker Desktop) and on Omarchy
- [ ] `git init`, first commit, create GitHub repo, push
- [ ] Answer open questions: note formats/languages/volume, answer LLM (Claude API vs Ollama), rights over material
- [ ] Devcontainer + `docker-compose.yml` (app + Qdrant)
- [ ] `pyproject.toml` with uv, empty package `src/notes_agent/`, pytest running
- [ ] `config/settings.yaml` + `config/sources.yaml` + `config.py` loader + `DocumentMetadata` model + tests
- [ ] (Ignasi, no AI) Organise 2–3 subjects of typed notes into `notes/<university>/<degree>/<subject>/<doc_type>/`
- [ ] Learn: reading Python (modules, imports, type hints, dataclasses/Pydantic, pytest)
- [ ] Sunday: `docs/weekly/week-01.md`

## Phase 1 — First version (to 25 Oct)
- [ ] W2 (6–12 Oct): loaders (PDF, Markdown) + registry, chunking with page numbers, `inspect` command, tests
- [ ] W3 (13–19 Oct): embeddings, Qdrant collection + payload indexes (user_id as tenant, subject), idempotent ingest, filtered search; `ingest` / `search` CLI
- [ ] W4 (20–25 Oct): LLMClient + Claude implementation, `ask` with citations, 20 golden questions, hit@k script
- 🛑 26–30 Oct: exams

## Phase 2 — Agent, interface, retrieval (2 Nov – 22 Dec)
- [ ] Eval baseline (hit@k, MRR) on 30–50 questions
- [ ] Hybrid search (dense + sparse) and reranking; measure the delta
- [ ] Agent design session (Opus): tools `search_notes`, `list_subjects`, `get_document`
- [ ] Agent implementation + tests
- [ ] FastAPI + Streamlit UI
- [ ] Query/response logging with user_id; faithfulness eval (LLM judge)
- 🛑 23 Dec – 29 Jan: Christmas + exams

## Phase 3 — Polish (1 – 28 Feb)
- [ ] Demo corpus (material Ignasi owns) + deployment
- [ ] README with diagram, screenshots, results table; CV bullets
- [ ] Final architecture review (Opus)

## Phase 4 — Rehearsal (1 – 17 Mar)
- [ ] Demo script, interview Q&A drills, final project summary (Opus)

## Parking lot
- OCR for scanned/handwritten notes (only if needed)
- DOCX / PPTX loaders

## Session log
- 2026-09-29: Architecture proposed (Opus). Repo scaffold: CLAUDE.md, TODO.md, docs, Claude settings.
