# Week 2 (6 – 12 Oct 2026): from PDFs to grounded answers

> Written 8 Oct (draft), completed Sunday 11 Oct with the real-corpus numbers available so far.
> Still pending, because the first full index had not finished: `eval` (hit@5, MRR) and
> `detect --evaluate` (marked TODO below). Fill them in when they exist; don't estimate them.

## What we built
- **Validated extraction on the real corpus** on two machines (Omarchy, Windows): 108 PDFs,
  2,059 pages, 0 errors, **identical document IDs on Linux and Windows**. Fixed what the real data
  showed: an empty-pages crash and the title heuristic (bullets taken as titles; big callouts low
  on a slide).
- **The rest of the ingestion pipeline**: boilerplate cleaning with an audit list, size-based
  chunking with a contextual header, bge-m3 embeddings through Ollama, Qdrant with per-user
  filtering inside the query, idempotent indexing, and pruning of deleted or replaced PDFs.
- **Grounded answers**: `ask` answers only from the notes, cites `[n]` → (document, page), and
  abstains through two gates (a similarity threshold, and the model's own `NOT_FOUND`). Every
  question is logged with its `user_id`.
- **Measurement tools before features**: a retrieval eval (hit@k, MRR, abstention sweep,
  end-to-end citation quality), `images` (content hidden in screenshots), `detect --evaluate`
  (metadata auto-detection accuracy), `duplicates` (near-duplicate documents).
- **Hybrid search** (dense + BM25 keywords) built into the collection layout before the first
  index, switchable per run.
- 219 automated tests, plus 5 integration tests against a real Qdrant 1.19.1; scale test of 2,000
  synthetic pages: extraction ~30 s, a second run does no work.
- **First real-corpus numbers**: 108 PDFs → 2,059 pages → **2,366 chunks**. Content not fully
  readable as text (image-only pages, or text plus an image covering ≥ 25% of the page):
  **Disseny de Software 31%**, Arquitectura 17%, IS 3% → OCR/vision (D30) matters mostly for one
  subject. Embedding speed with bge-m3 on a laptop CPU: **~29 chunks/min** (~80 min for the corpus),
  which is why indexing is incremental and resumable.
- **Machine setup as part of the product**: a second Windows PC showed that Docker can't start with
  virtualization off in the BIOS; the setup script now detects it, Qdrant can run without Docker,
  and `doctor` says whether Ollama runs on the GPU or the CPU.

## Why (key decisions)
- **Size decides how a page is chunked**, not its shape: one rule covers slides (~400 chars) and
  dense exam pages (~3,000 chars). A chunk that mixes topics gives a vector that matches nothing well.
- **Two abstention gates**: a cheap score check that avoids wasting LLM time, plus the model's own
  judgement after reading the sources. "Not in your notes" is a feature, not a failure.
- **The manifest is the source of truth** for where a document is and what it is. Moving a PDF
  costs one metadata update, not hours of re-embedding.
- **Prune only on evidence**: an unmounted OneDrive folder must never look like "everything was
  deleted". Found by automated review before it could happen.
- **Metadata detection without an LLM**: nearest subject centroid, measured leave-one-out. We also
  avoided a leak: stored vectors contain the subject's name, which would have faked a perfect score.

## What I learned
- How dense embeddings and keyword (BM25) search complement each other, and why rank fusion (RRF)
  scores can't be used as a relevance threshold.
- Evaluation vocabulary: hit@k, MRR, abstention accuracy, citation precision, leave-one-out.
- Idempotency and versioned stages: re-running the pipeline is cheap and safe.
- Reviewing AI-written code: three review rounds found 25+ issues, several of which would have
  destroyed data or produced misleading metrics. Round 3 (11 Oct) examples: an empty OneDrive
  folder mid-sync would have made `ingest` wipe every embedding (now held back until `prune
  --force`); Ollama silently truncates prompts longer than its context (now measured and warned);
  a fix for LaTeX accents would have turned the Catalan "l´any" into "lány".
- Accepting design decisions as the reviewer: D30–D33 (image measurement, LLM interface, grounded
  answers with two abstention gates, query log) accepted after reading the code and its trade-offs.

## Interview questions this week prepares me for
- **"How do you stop the model from making things up?"** It only sees numbered excerpts from the
  user's notes and must cite them. If retrieval is weak it abstains before the LLM is called; if
  the model says the sources don't answer, it abstains too. Citations map back to pages, and
  `eval --answers` measures how often they point to the right page.
- **"How do you know retrieval is good?"** A golden set of my own questions with the expected
  pages, in three languages: hit@5 = TODO, MRR = TODO. Every change is compared before and after.
- **"What happens when a file changes?"** Its content hash changes. The new version is indexed,
  the old one is pruned, and a moved file only gets its metadata updated.
- **"How does it handle several users?"** `user_id` is a parameter everywhere and a tenant index
  in Qdrant. Filtering happens inside the vector query, and tests check that one user never sees
  another user's chunks.

## CV bullets
- Built a multilingual (ca/es/en) RAG system over 2,000+ pages of course material with cited,
  page-level answers and abstention, using local models only (Ollama, bge-m3, Qdrant); retrieval
  hit@5 of TODO% on a hand-written golden set.
- Designed an idempotent, versioned ingestion pipeline (content-hash IDs, incremental stages,
  safe pruning) verified on Linux and Windows and covered by 200+ automated tests.

## Risks / open issues
- The first full index was interrupted at 943 of 2,366 chunks (resumable); `ask` has not run with
  a real LLM on the real corpus yet.
- D34–D37 are still proposed (PR #3); D30–D33 accepted 9 Oct.
- The golden set is not written yet; until then, retrieval quality is unmeasured.
- Two cleaning choices to decide after the first searches: "Solució:"/"Solution:" labels are removed
  as boilerplate (chunks lose where a solution starts), and so are topic headers like
  "P5: Jerarquía de Memoria" (could feed the chunk header instead).
