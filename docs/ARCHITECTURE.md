# Architecture

Status: proposed 2026-09-29 (Opus). Each decision lists **why** and the **rejected alternative**, so it can be defended in interviews.

## Data flow

```
INGESTION
 notes/ ─► Loader (per format) ─► Document (text + validated metadata)
        ─► Chunker (~500 tokens, keeps page numbers) ─► Embedder ─► Qdrant (vector + payload)

QUERY
 question + user_id (+ subject) ─► Embedder (same model) ─► Qdrant search WITH filter
        ─► top-k chunks ─► prompt with numbered sources ─► LLM ─► Answer (text + citations + user_id) ─► log
```

Phase 2 wraps the query side in an agent: the LLM chooses tools (`search_notes`, `list_subjects`, `get_document`).

## Decisions

| # | Decision | Why | Rejected |
|---|---|---|---|
| D1 | Hand-written RAG pipeline | ~300 lines, every step explainable; easier to debug | LangChain / LlamaIndex: hides the internals, APIs change often |
| D2 | Qdrant in Docker | Filtering inside the query; documented multi-tenant pattern (payload index on `user_id`); hybrid search | Chroma (weaker multi-tenancy), pgvector (more SQL work now) |
| D3 | Local multilingual embeddings (bge-m3 / multilingual-e5) | Notes are in Catalan/Spanish/English; free and private | English-only models; paid embedding APIs |
| D4 | Claude API behind an `LLMClient` interface | Cheap grounded answers (Haiku); swap to Sonnet or Ollama via config | Coupling code to one provider |
| D5 | Metadata from folder path + `config/sources.yaml`, validated by Pydantic | No hardcoding; new subject = config change | Metadata in code; free-form dicts |
| D6 | Deterministic chunk IDs | Re-ingest is idempotent (no duplicates) | Random UUIDs |
| D7 | `user_id` passed explicitly everywhere | Multi-user later only changes where the value comes from | Global constant |
| D8 | Evaluation from week 4 (hit@k, MRR, faithfulness) | Proves improvements with numbers | "Looks good" manual testing |
| D9 | CLI first, then FastAPI + Streamlit | Fast to develop and evaluate; demo UI later | Building a web UI first |
| D10 | uv + devcontainer + docker-compose + pytest | Identical environment on Arch and Windows | Manual venvs per machine |

## Known risks (verify AI output here)
- Filter applied after retrieval instead of in the Qdrant call → check `retrieval.py`.
- Outdated Qdrant client API → check the docs for the installed version.
- e5 models need `query: ` / `passage: ` prefixes.
- Garbled PDF extraction (formulas, columns) → inspect random chunks.
- Duplicates on re-ingest → the point count must stay the same after running ingest twice.

## Out of scope (roadmap)
Authentication, billing/quotas, distributed deployment.
