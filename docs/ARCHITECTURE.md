# Architecture

Status: accepted 2026-09-29 (Opus). Each decision lists **why** and the **rejected alternative**, so it can be defended in interviews.

## Product idea
Users upload their course material (slides, exams). The system processes it once and then answers questions
**only from that material**, citing the exact slide, not from the model's general knowledge or the internet.

## Data flow

```
INGESTION (once per file, incremental)
 notes/ (originals, never modified)
   1. REGISTER   file hash = document ID; skip if already processed           → data/manifest.sqlite
   2. EXTRACT    per slide: title, text, language, PNG thumbnail, "mostly image" flag
                                                                               → data/processed/<doc_id>.json
   3. CLEAN      remove boilerplate repeated on every slide (logo, professor, page number)
   4. CHUNK      1 slide = 1 chunk (merge consecutive same-title slides), contextual header
   5. INDEX      embed + upsert to Qdrant (vector + metadata payload + user_id)

QUERY (never touches the PDFs)
 question + user_id (+ subject) ─► embed (same model) ─► Qdrant search WITH filter
   ─► relevance threshold (abstain if nothing relevant) ─► prompt with numbered sources
   ─► LLM ─► answer with citations (subject, document, slide) + user_id ─► log
```

Phase 2 wraps the query side in an agent: the LLM chooses tools (`search_notes`, `list_subjects`, `get_document`),
adds an upload UI that feeds the same pipeline, and an optional vision enrichment step (D14).

## Decisions

| # | Decision | Why | Rejected |
|---|---|---|---|
| D1 | Hand-written RAG pipeline | ~300 lines, every step explainable; easier to debug | LangChain / LlamaIndex: hides internals, APIs change often |
| D2 | Qdrant in Docker | Filtering inside the query; multi-tenant pattern (payload index on `user_id`); hybrid search | Chroma (weaker multi-tenancy), pgvector (more SQL work now) |
| D3 | Local multilingual embeddings (bge-m3) | Slides mix Catalan/Spanish/English; cross-lingual retrieval; free and private | English-only models; paid embedding APIs |
| D4 | `LLMClient` interface: **Ollama (local) first**, Claude API later via config | Free while developing; switching is a config line; the eval measures the quality gain | Coupling code to one provider |
| D5 | Metadata: university/degree from user profile in config; subject + doc_type from path `notes/<subject>/<doc_type>/`; professor/year from `sources.yaml`; one Pydantic model | Simple for the user; a future upload form fills the same model | Metadata in code; deep folder trees |
| D6 | Deterministic chunk IDs | Re-ingest is idempotent (no duplicates) | Random UUIDs |
| D7 | `user_id` passed explicitly everywhere | Multi-user later only changes where the value comes from | Global constant |
| D8 | Evaluation from week 4 (hit@k, MRR, faithfulness, abstention) | Proves improvements with numbers | "Looks good" manual testing |
| D9 | CLI first, then FastAPI + Streamlit | Fast to develop and evaluate; demo UI later | Building a web UI first |
| D10 | uv + devcontainer + docker-compose + pytest | Identical environment on Arch and Windows | Manual venvs per machine |
| D11 | Staged pipeline with persisted intermediate outputs | Inspectable (open the JSON); re-run one stage only (new chunking or embedding model without re-reading PDFs) | One script PDF → Qdrant |
| D12 | Document ID = content hash + manifest of stage status | Incremental, detects duplicates, survives renames | Filename as ID |
| D13 | Chunk unit = slide, with contextual header `[subject · document · slide title]` | Slides are semantic units; exact citations; header makes terse slides findable | Fixed 500-token windows (mix unrelated slides) |
| D14 | Images: phase 1 text + thumbnail + "mostly image" flag; phase 2 optional vision-model description, config-toggled and measured | Diagrams hold knowledge, but vision is slow/costly: measure first | OCR only (reads words, not diagrams); ignoring images |
| D15 | PyMuPDF for extraction (AGPL, fine for open source) | Fast, per-page text, renders thumbnails for the demo | pypdf (weaker); Docling kept as fallback if layout order is bad |
| D16 | Language detected per slide, stored as metadata | Enables per-language analysis; verifies cross-lingual retrieval | Assuming one language per document |
| D17 | Course material never leaves the machine: `.gitignore` + pre-commit hook block PDFs/Office files, `notes/`, `data/` | Professors' slides and exams are copyrighted; the repo is public | Relying on `.gitignore` alone (`git add -f` bypasses it) |

## Grounding ("answer only from the notes")
Cannot be guaranteed 100%, but it is controlled and measured:
system prompt restricts to the retrieved sources · mandatory citations · relevance threshold → "not found in your notes" ·
faithfulness eval (LLM judge) in the golden set.

## Known risks (verify AI output here)
- Filter applied after retrieval instead of in the Qdrant call → check `retrieval.py`.
- Outdated Qdrant client API → check the docs for the installed version.
- Jumbled slide text order → compare processed JSON vs slide with `inspect`.
- Boilerplate removal deleting real repeated content (formulas) → compare char counts before/after.
- Image-only or protected PDFs silently empty → ingest report lists slides with no text.
- Duplicates on re-ingest → point count must stay the same after running ingest twice.

## Hardware notes
- Windows PC: 16 GB RAM + GTX 1080 (8 GB VRAM) → 7–8B local models at usable speed.
- MateBook 14 (Omarchy): CPU only → embeddings fine (one-off), local LLM limited to small models or slow.
- Ollama runs natively on the host, not inside the devcontainer (GPU passthrough on Windows is fragile).

## Out of scope (roadmap)
Authentication, billing/quotas, distributed deployment.
