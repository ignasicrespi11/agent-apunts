# TODO

Current: **Phase 1 · Week 1 (29 Sep – 5 Oct 2026)**

## Now — Week 1: foundations
- [x] Architecture proposal (Opus) → `docs/ARCHITECTURE.md`
- [x] CLAUDE.md, TODO.md, README, .gitignore, .gitattributes, Claude Code project settings
- [x] Install toolchain on Windows (git, gh, uv, VS Code) — Docker Desktop + Omarchy pending
- [x] `git init`, first commit, public repo github.com/ignasicrespi11/agent-apunts
- [x] Open questions answered: slide PDFs (text+images, ca/es/en), Ollama first → Claude API later, material is copyrighted
- [x] Data pipeline decisions D11–D17 → `docs/ARCHITECTURE.md`; pre-commit hook blocking course material
- [ ] **Next:** Devcontainer + `docker-compose.yml` (app + Qdrant)
- [ ] `pyproject.toml` with uv, empty package (name to decide, e.g. `apunts`), pytest running
- [ ] `config/settings.yaml` + `config/sources.yaml` + `config.py` loader + `DocumentMetadata` model + tests
- [ ] (Ignasi, no AI) Copy 2–3 subjects of slide PDFs into `notes/<subject>/<doc_type>/` (lowercase, no accents/spaces)
- [ ] (Ignasi) Install Docker Desktop on Windows; docker on Omarchy; clone repo on Omarchy + `git config core.hooksPath .githooks`
- [ ] Learn: reading Python (modules, imports, type hints, dataclasses/Pydantic, pytest)
- [ ] Sunday: `docs/weekly/week-01.md`

## Phase 1 — First version (to 25 Oct)
- [ ] W2 (6–12 Oct): manifest (content-hash doc IDs) + PDF extractor (PyMuPDF: title, text, language, thumbnail, image flag) → `data/processed/*.json`; `inspect` command; tests
- [ ] W3 (13–19 Oct): boilerplate cleaning + slide chunking with contextual header; embeddings (bge-m3), Qdrant collection + payload indexes (user_id as tenant, subject), idempotent ingest, filtered search; `ingest` / `search` CLI
- [ ] W4 (20–25 Oct): LLMClient + Ollama implementation (Windows GPU), grounded `ask` with citations + abstention, 20 golden questions (ca/es/en), hit@k script
- 🛑 26–30 Oct: exams

## Phase 2 — Agent, interface, retrieval (2 Nov – 22 Dec)
- [ ] Eval baseline (hit@k, MRR, abstention) on 30–50 questions
- [ ] Claude API LLMClient; compare vs Ollama on the eval
- [ ] Vision enrichment for image-heavy slides (D14), measured
- [ ] Hybrid search (dense + sparse) and reranking; measure the delta
- [ ] Agent design session (Opus): tools `search_notes`, `list_subjects`, `get_document`
- [ ] Agent implementation + tests
- [ ] FastAPI + Streamlit UI, including upload feeding the same pipeline; show cited slide thumbnails
- [ ] Query/response logging with user_id; faithfulness eval (LLM judge)
- 🛑 23 Dec – 29 Jan: Christmas + exams

## Phase 3 — Polish (1 – 28 Feb)
- [ ] Demo corpus (own or Creative Commons material, or professor permission) + deployment
- [ ] README with diagram, screenshots, results table; CV bullets
- [ ] Final architecture review (Opus)

## Phase 4 — Rehearsal (1 – 17 Mar)
- [ ] Demo script, interview Q&A drills, final project summary (Opus)

## Parking lot
- OCR for scanned/handwritten notes (only if needed)
- DOCX / PPTX / Markdown loaders
- Docling as fallback extractor if PyMuPDF text order is bad

## Session log
- 2026-09-29: Architecture proposed (Opus). Repo scaffold: CLAUDE.md, TODO.md, docs, Claude settings.
- 2026-09-29: Toolchain installed on Windows; repo pushed to GitHub (public), topics + main branch protection (no force-push/delete).
- 2026-09-29: Repo renamed notes-agent → agent-apunts (Python package name still to decide).
- 2026-09-29: Accepted data pipeline design (D11–D17), Ollama-first LLM, copyright safeguards (gitignore + pre-commit hook).
