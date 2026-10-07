# TODO

Current: **Phase 1 · Week 2 (6–12 Oct 2026)**. Weeks 2–4 code is built (5–8 Oct); extraction is validated on the
real corpus (Omarchy + Windows). Next: review PR #3 (proposed D31–D35), run `ingest` + `ask` on the real corpus,
write the golden set.

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
- First real extraction (2026-10-06, Omarchy): 108 docs, 2,059 pages, 0 errors, register idempotent. 20 pages with
  no text: exam pages 16–24 of `examen1_2024_25-solucions` are **blank pages** (checked by Ignasi), the rest are
  blank/separator pages in the problem books → no scanned content found, OCR stays in the parking lot.
  Title heuristic: bullets taken as title (fixed, loader v2); big callouts low on the slide taken as titles (fixed, v3:
  top 30% only). Windows run (2026-10-07) gives identical doc_ids, page counts and empty pages as Omarchy.

## Now — Week 1: foundations
- [x] Architecture proposal (Opus) → `docs/ARCHITECTURE.md`
- [x] CLAUDE.md, TODO.md, README, .gitignore, .gitattributes, Claude Code project settings
- [x] Install toolchain on Windows (git, gh, uv, VS Code) — Docker Desktop + Omarchy pending
- [x] `git init`, first commit, public repo github.com/ignasicrespi11/agent-apunts
- [x] Open questions answered: slide PDFs (text+images, ca/es/en), Ollama first → Claude API later, material is copyrighted
- [x] Data pipeline decisions D11–D17 → `docs/ARCHITECTURE.md`; pre-commit hook blocking course material
- [x] `docker-compose.yml` (Qdrant v1.19.1, localhost-only ports, named volume). No devcontainer: app runs natively with uv (GPU, OneDrive)
- [x] `pyproject.toml` with uv, package `agent_apunts`, pytest + ruff running
- [x] `config/settings.yaml` + `config/sources.yaml` + `config.py` loader (D20) + `DocumentMetadata` (D21) + tests
- [x] (Ignasi) Labelled set: 3 subjects, 110 PDFs in `testing/apunts_testing/<subject>/<doc_type>/`
- [x] Setup scripts for Windows + Omarchy (`docs/SETUP.md`)
- [x] (Ignasi) Windows: WSL2 + Docker Desktop working
- [x] Labelled PDFs copied to OneDrive (108 PDFs, `OneDrive - UAB\_UNI\apunts_testing`).
- [x] Deny rule fixed (only `.env` / `.env.local`); `.env.example` documents `APUNTS_DIR` / `TESTING_DIR`
- [x] `docs/SETUP.md`: 3 steps per machine (script → OneDrive → `.env`), incl. OneDrive on Omarchy
- [ ] (Ignasi) This Windows PC: create `.env` from `.env.example` with `TESTING_DIR` (not done yet as of 2026-09-30)
- [ ] (Ignasi) Omarchy + second Windows PC: follow `docs/SETUP.md` steps 1–3
- [x] Config loader reads `APUNTS_DIR` / `TESTING_DIR` / `QDRANT_URL` from `.env`; `uv run agent-apunts config` prints resolved paths + document counts
- [ ] (Ignasi) On each machine (Omarchy ✓ 2026-10-06, Windows PC 2 ✓ 2026-10-07): `uv run agent-apunts config` must show 108 documents (110 analysed minus 2 exact duplicates removed) and no "problem" lines
- [ ] (Ignasi) Check subject names in `config/sources.yaml` (written by Claude from the folder names)
- [ ] (Ignasi) Once `TESTING_DIR` works, delete the duplicate local copy in `testing/apunts_testing/` (keep OneDrive as the single source)
- [ ] Learn: reading Python (modules, imports, type hints, dataclasses/Pydantic, pytest)
- [x] Sunday: `docs/weekly/week-01.md`

## Phase 1 — First version (to 25 Oct)
- [x] W2 (built 5 Oct): manifest (D22) + loader registry (D23) + PDF extractor (D24, language D25) → `data/processed/<user>/<doc_id>.json`; `register` / `extract` / `inspect` commands; 71 tests on synthetic PDFs
- [x] Real-corpus extraction check (Omarchy + Windows PC 2): register idempotent, 0 errors, titles checked on slides_grasp
- [x] Fix extraction issues found on the real corpus (empty-pages crash; title heuristic v2 bullets, v3 top 30%)
- [x] W3 (built 7 Oct, D26–D29): boilerplate cleaning + size-based chunking with contextual header; Embedder interface + Ollama bge-m3; Qdrant collection with model metadata + payload indexes (user_id tenant, subject…); idempotent index; filtered search; `chunk` / `index` / `ingest` / `search` CLI; 112 tests (+3 opt-in against a real Qdrant, verified on 1.19.1)
- [ ] **Next (Ignasi, machine with PDFs):** `git pull`, re-run the setup script (installs Ollama + pulls bge-m3), `docker compose up -d`, then `uv run agent-apunts ingest`. Check: (1) `chunk` output's boilerplate list has no real sentences/formulas; (2) `inspect IS2526-ExamenFinal --chunks` splits the dense pages; (3) running `ingest` twice keeps the same point count; (4) 5 `search` questions in ca/es/en find the right slides (note results for week 4)
- [ ] Tune cleaning/chunking thresholds from that check (settings.yaml; changing them re-chunks automatically)
- [x] W4 code (built 8 Oct overnight, PR #3, *proposed* D30–D36): `images` report (hidden image content); LLMClient + Ollama; `ask` with [n] citations, two abstention gates, query log; eval harness (hit@k, MRR, abstention sweep, `--answers` end to end); prune of deleted/replaced PDFs; payload-only updates on moves; `detect` (D36, D18 without LLM) + `--evaluate`; `duplicates` report (D19 step 1); `doctor`; `docs/CODE_TOUR.md`; review fixes. 187 tests
- [ ] **(Ignasi)** Review PR #3; accept or change the proposed decisions D30–D35 in `docs/ARCHITECTURE.md`
- [ ] **(Ignasi)** Write `eval/golden.yaml`: 20 questions (ca/es/en, 3–4 unanswerable, some tagged `code-image`), see `eval/README.md`
- [ ] Run `eval --sweep` on the real corpus → set `retrieval.min_score`; first numbers for the weekly summary
- [ ] `ollama pull qwen2.5:7b` on the GTX 1080 PC; try `ask` on 10 questions, note wrong/uncited answers
- [ ] Run `images` on the real corpus → decide whether an OCR stage (D30 step 3) is worth building
- [ ] Run `detect --evaluate` on the real corpus → subject accuracy (CV number), tune `detection.min_margin`
- [ ] Run `duplicates` → decide D19 threshold and how search collapses groups
- [ ] (Ignasi) Read `docs/CODE_TOUR.md` before reviewing PR #3
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
- Devcontainer (only if deployment or onboarding needs it)
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
- 2026-09-30: Dev environment: pyproject + uv.lock (Python 3.12, minimal deps), Qdrant via docker-compose, smoke tests. Devcontainer dropped (native uv).
- 2026-10-05: (cloud session, Opus) New rule: sessions use the whole token budget, every why documented. Config + DocumentMetadata, `config` command, manifest + loader registry + PDF extraction + `inspect` (D20–D25), week-01 summary. 71 tests pass. Not yet run on real PDFs. Push was blocked (GitHub App access) at first.
- 2026-10-06/07: First real-corpus runs (Omarchy, Windows PC 2): 2 extraction fixes (empty-pages crash, title heuristic v2/v3), setup scripts fixed (clone path, WSL check aborting on PS 5.1, TESTING_DIR auto-fill, Smart App Control diagnosis).
- 2026-10-07: Week 3 built in the cloud session (D26–D29 approved in one batch): cleaning + chunking + Ollama embedder + Qdrant store/index/search. Tests caught 3 cleaning traps (exam-table numbers, numbered headings, page 0) and an `ingest` bug. Not yet run on real PDFs/Ollama.
- 2026-10-08: (autonomous overnight, Opus) PR #2 merged after evaluation. PR #3: D30 image measurement, faster re-index, week-4 ask/LLM/log + eval harness (proposed D31–D34), prune (D35). Self-review + automated review found 14 issues, all fixed (incl. prune wiping an unmounted OneDrive source, moved files keeping stale metadata). Nothing run on real PDFs/Ollama yet.
