# Week 1 (29 Sep – 5 Oct 2026): foundations

## What we built
- **Architecture with 25 recorded decisions** (`docs/ARCHITECTURE.md`): each has its why and the rejected
  alternative. The ones that changed after looking at real data: layout-aware chunking (D13) and near-duplicate grouping (D19).
- **Corpus analysis** of the labelled set: 110 PDFs, 2,087 pages, 3 subjects. Found two page kinds (slides
  ~330 chars/page vs A4 documents ~4,000), per-document languages and years, and missing professors.
- **Reproducible dev environment** on Windows and Omarchy: setup scripts, uv + lockfile, Qdrant in Docker, private PDFs
  via OneDrive + `.env`, plus a pre-commit hook that blocks copyrighted material from the public repo.
- **Config + metadata layer**: `settings.yaml` / `sources.yaml` / `.env` merged by a hand-written loader into one
  validated `Settings`; `DocumentMetadata` Pydantic model; `agent-apunts config` checks each machine's setup.
- **Pipeline stages 1–2, pulled forward from week 2**: a SQLite manifest with content-hash document IDs (idempotent, survives
  renames, detects duplicates). A loader registry by file extension. PDF extraction (PyMuPDF) to per-document JSON
  with per-page text, title guess, language, thumbnail and an "image-only" flag. `inspect` to check the output against the PDF.
- **71 tests** on self-generated PDFs (no course material in the repo). On a synthetic PDF, extraction runs at ~15 ms/page.

## Why (key decisions)
- **Hand-written RAG pipeline instead of LangChain**: every line can be explained and debugged; frameworks hide the steps.
- **Staged pipeline with files in between** (register → extract → …): each stage can be re-run alone and its output
  opened and read. A new chunking rule doesn't require reading the PDFs again.
- **Document ID = hash of the content**, not the filename: re-ingesting doesn't create duplicates, renaming a
  file costs nothing, and identical copies are detected.
- **Hand-written config loader instead of `pydantic-settings`**: it's obvious where each value comes from. It's isolated, so moving to
  env-var config (deployment) or a user database (multi-user) only changes `config.py`.
- **`user_id` passed explicitly everywhere** (manifest keys, output folders): multi-user later changes where the
  value comes from, not the code.
- **Layout-aware chunking** (decided now, built in week 3): slides and dense A4 pages need different chunk sizes. One rule for
  both would either split slides or average many topics into one vector.

## What I learned
- How a RAG system is split into ingestion (once per file) and query (never touches the PDFs), and why the
  embedding model must be the same on both sides.
- Pydantic: data validated at the boundary (YAML, JSON, SQLite) so the rest of the code can trust it.
- Content hashing (SHA-256) as an identity for files; idempotency as a design goal.
- Why measuring the corpus first changes the design (D13 was revised after counting characters per page).

## Interview questions this week prepares me for
- **"Why didn't you use LangChain?"** The pipeline is a few hundred lines, so I can explain and test each step. Frameworks
  hide the prompts and the retrieval logic, and their APIs change often. I can still adopt one later if a feature justifies it.
- **"How do you avoid duplicates when re-ingesting?"** A document's ID is the SHA-256 of its bytes. A manifest records
  which stages each ID has completed. Re-running skips finished work, a moved file keeps its ID, and copies are reported.
- **"How would this scale to many users?"** `user_id` is already a parameter everywhere: on manifest keys and output folders now,
  and on the vector DB payload index later. Per-user filtering happens inside the vector query. Config is isolated, so user profiles can move to a database.
- **"How do you handle copyrighted material in a public repo?"** `.gitignore` plus a pre-commit hook that rejects PDFs and data
  folders, even if someone runs `git add -f`. Tests generate their own PDFs, and the public demo will use a separate corpus.

## CV bullets
- Designed a staged, idempotent document-ingestion pipeline in Python (Pydantic, SQLite, PyMuPDF) with content-hash IDs and
  per-stage versioning. Processes a 2,000-page multilingual (ca/es/en) course corpus, covered by 71 automated tests.
- Set up a reproducible cross-platform dev environment (uv, Docker, setup scripts) with automated safeguards that keep
  copyrighted material out of a public repository.

## Risks / open issues
- Extraction has only been tested on synthetic PDFs (this week's coding ran in a cloud session without the real corpus). **Next: run
  `register` + `extract` on the 108 real PDFs and check titles, languages and empty pages with `inspect`.**
- The title heuristic (largest font) may fail on decorative text or image titles; language detection may fail on very short pages.
- `.env` is not yet created on every machine; Omarchy setup is still pending.
- Docker was installed on Windows but the Qdrant stack hasn't been exercised by code yet (week 3).
