# agent-apunts

An AI agent that answers questions about your university subjects **grounded in, and citing, your own course notes**.
It uses retrieval-augmented generation (RAG) over a vector database.

> 🚧 Work in progress — portfolio project, target demo: March 2027.

## Features (planned for v1)
- Modular ingestion per file format (PDF, Markdown, …) with rich metadata (university, degree, subject, professor, year, document type)
- Multilingual semantic search (Catalan / Spanish / English) with filtering by user and subject inside the vector DB query
- Answers with citations (subject, document, page)
- Evaluation harness (retrieval hit@k, answer faithfulness)
- Agent with tools, CLI and web UI

## Setup
Windows 11 and Omarchy (Arch Linux): see [docs/SETUP.md](docs/SETUP.md).

## Architecture
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Stack
Python 3.12 · uv · Qdrant · sentence-transformers · Claude API · Typer · FastAPI · Streamlit · pytest · Docker devcontainer

## Roadmap (beyond v1)
- Multi-user support with authentication (the data model already carries `user_id` on every chunk and query)
- Other degrees and universities (driven by config, no code changes)
- Usage quotas / billing
- Distributed deployment

## Privacy
Course notes are never committed (`apunts/` and `testing/` are gitignored). The public demo uses a separate demo corpus.
