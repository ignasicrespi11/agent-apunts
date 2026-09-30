# TODO

Current: **Phase 1 · Week 1 (29 Sep – 5 Oct 2026)**

## Corpus findings (2026-09-29, labelled set)
- 110 PDFs, 2,087 pages. No encrypted/broken files.
- Two kinds of PDF: **landscape slides** (disseny_software theory, median ~330 chars/page) and **portrait A4 documents**
  (all of arquitectura_computadors, IS exams/exercises: median 1,800–4,000 chars/page).
  → D13 revised: layout-aware chunking (accepted).
- Exact duplicates: both fixed (access_control_system kept in labs; IS2425-Parcial1 deleted).
- Metadata (2026-09-30): draft in `testing/sources_draft.yaml` (private), all subjects taken in 2025-26 (confirmed).
  **Professors appear in no PDF and Ignasi chose not to record them** → `professor` optional (nullable) in `DocumentMetadata`. **academic_year varies per document** (exams 2022-23 → 2025-26)
  → store the document's year (from filename/content) separately from the year the subject was taken.
  **Languages are per document, not per subject** (IS: ca 47% / en 42% / es 10%) → `languages` list in config; D16 per page.
- Many near-duplicates (ES/EN translations, statement vs solutions, book with/without solutions) → D19 (phase 2).
- Image-heavy: ~16% of disseny_software pages have <80 chars (D14 relevant there).

## Now — Week 1: foundations
- [x] Architecture proposal (Opus) → `docs/ARCHITECTURE.md`
- [x] CLAUDE.md, TODO.md, README, .gitignore, .gitattributes, Claude Code project settings
- [x] Install toolchain on Windows (git, gh, uv, VS Code) — Docker Desktop + Omarchy pending
- [x] `git init`, first commit, public repo github.com/ignasicrespi11/agent-apunts
- [x] Open questions answered: slide PDFs (text+images, ca/es/en), Ollama first → Claude API later, material is copyrighted
- [x] Data pipeline decisions D11–D17 → `docs/ARCHITECTURE.md`; pre-commit hook blocking course material
- [ ] **Next:** Devcontainer + `docker-compose.yml` (app + Qdrant)
- [ ] `pyproject.toml` with uv, package `agent_apunts`, pytest running
- [ ] `config/settings.yaml` + `config/sources.yaml` (from `testing/sources_draft.yaml`; no personal data, can be committed) + `config.py` loader + `DocumentMetadata` model + tests
- [x] (Ignasi) Labelled set: 3 subjects, 110 PDFs in `testing/apunts_testing/<subject>/<doc_type>/`
- [x] Setup scripts for Windows + Omarchy (`docs/SETUP.md`)
- [x] (Ignasi) Windows: WSL2 + Docker Desktop working
- [ ] (Ignasi) Omarchy: run `scripts/setup-omarchy.sh`
- [ ] Learn: reading Python (modules, imports, type hints, dataclasses/Pydantic, pytest)
- [ ] Sunday: `docs/weekly/week-01.md`

## Phase 1 — First version (to 25 Oct)
- [ ] W2 (6–12 Oct): manifest (content-hash doc IDs) + PDF extractor (PyMuPDF: title, text, language, thumbnail, image flag) → `data/processed/*.json`; `inspect` command; tests
- [ ] W3 (13–19 Oct): boilerplate cleaning + slide chunking with contextual header; embeddings (bge-m3), Qdrant collection + payload indexes (user_id as tenant, subject), idempotent ingest, filtered search; `ingest` / `search` CLI
- [ ] W4 (20–25 Oct): LLMClient + Ollama implementation (Windows GPU), grounded `ask` with citations + abstention, 20 golden questions (ca/es/en), hit@k script; metadata auto-detection (D18) + accuracy vs manually organised subjects
- 🛑 26–30 Oct: exams

## Phase 2 — Agent, interface, retrieval (2 Nov – 22 Dec)
- [ ] Eval baseline (hit@k, MRR, abstention) on 30–50 questions
- [ ] Claude API LLMClient; compare vs Ollama on the eval
- [ ] Vision enrichment for image-heavy slides (D14), measured
- [ ] Near-duplicate grouping + collapse results by `group_id` (D19)
- [ ] Hybrid search (dense + sparse) and reranking; measure the delta
- [ ] Agent design session (Opus): tools `search_notes`, `list_subjects`, `get_document`
- [ ] Agent implementation + tests
- [ ] FastAPI + Streamlit UI, including upload feeding the same pipeline; show cited slide thumbnails
- [ ] Folder watcher on `apunts/` (auto-ingest new PDFs); confirm-metadata step for low-confidence detections
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
- 2026-09-29: Added idempotent setup scripts (Windows/Omarchy) + docs/SETUP.md. Docker blocked on this PC: WSL2 missing.
- 2026-09-29: D18 accepted: automatic metadata detection (week 4), folder watcher + upload (phase 2).
- 2026-09-29: Renamed notes/ → apunts/ (inbox) + testing/apunts_testing/ (labelled set, 110 PDFs, 3 subjects). Package name: agent_apunts. Corpus analysed: see Corpus findings.
- 2026-09-29: Local folder renamed to agent-apunts. D13 revised (layout-aware chunking) and D19 (near-duplicate grouping) accepted.
- 2026-09-30: Metadata draft generated from PDFs (testing/sources_draft.yaml); findings on professor/year/language recorded. Model policy: Opus for first coding sessions.
