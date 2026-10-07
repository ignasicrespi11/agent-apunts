# Week 2 (6 – 12 Oct 2026): from PDFs to grounded answers

> **DRAFT** written on 8 Oct during an autonomous session. Finish it on Sunday with the real
> numbers from `eval`, `detect --evaluate` and `images` (marked TODO below).

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
- 203 automated tests, plus integration tests against a real Qdrant 1.19.1; scale test of 2,000
  synthetic pages: extraction ~30 s, a second run does no work.

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
- Reviewing AI-written code: two review rounds found 20+ issues, several of which would have
  destroyed data or produced misleading metrics.

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
- Week 3–4 code has not yet run with Ollama on the real corpus.
- Proposed decisions D30–D37 are waiting for review (PR #3).
- The golden set is not written yet; until then, quality claims are unmeasured.
