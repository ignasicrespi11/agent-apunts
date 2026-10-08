# Code tour

A guided reading of the code for reviewing it: what each module does, in which order to read it,
and the Python ideas you will meet. Line numbers are approximate; use your editor's "go to
definition" (F12 in VS Code) to jump around.

## 1. The map

```
config/settings.yaml, sources.yaml, .env
        │  config.py  load_settings() -> Settings (one validated object)
        ▼
cli.py  (Typer: every `agent-apunts <command>` is a function here; thin: load settings, call library)
        │
        ├─ INGESTION (src/agent_apunts/ingestion/)            outputs in data/
        │   discovery.py   which files exist (find_files)
        │   register.py    stage 1: SHA-256 doc_id, metadata from folders  -> manifest.sqlite
        │   prune.py       forget deleted/replaced PDFs (D35)
        │   loaders/       one loader per format: base.py (Protocol), pdf.py (PyMuPDF)
        │   extract.py     stage 2: pages -> processed/<user>/<doc_id>.json (+ language.py)
        │   cleaning.py    stage 3: repeated lines, page numbers (D27)
        │   chunking.py    stage 4a: split a page's text by size (D26)
        │   chunk.py       stage 4b: header, IDs -> chunks/<user>/<doc_id>.json
        │   index.py       stage 5: embeddings.py + store.py -> Qdrant
        │   manifest.py    SQLite: which documents exist, which stages are done
        │   image_report.py  how much content hides in images (D30)
        │
        └─ QUERY
            retrieval.py   question -> embedding -> store.search (user filter inside Qdrant)
            rag.py         ask(): abstain or LLM answer with [n] citations (llm.py), log
            evaluation.py  golden set metrics (hit@k, MRR, abstention, citations)
            detection.py   subject/doc_type suggestions for unorganised PDFs (D36)
            doctor.py      environment checks
```

## 2. Reading order (about 2 hours)

1. `config.py`: how settings are loaded. Everything else receives a `Settings`.
2. `metadata.py`: `DocumentMetadata`, the one model every document carries.
3. `ingestion/register.py` + `ingestion/manifest.py`: identity (hash) and memory (SQLite).
4. `ingestion/loaders/base.py` → `pdf.py` → `ingestion/extract.py`: from PDF to JSON.
5. `ingestion/cleaning.py` → `chunking.py` → `chunk.py`: from pages to chunks.
6. `embeddings.py` → `store.py` → `ingestion/index.py`: from chunks to vectors in Qdrant.
7. `retrieval.py` → `rag.py`: the question side. **This is the heart of the demo.**
8. `evaluation.py`: how we prove it works.

For each file, read the module docstring first (the text at the top): it says *why* the file
exists. Then the tests in `tests/test_<name>.py`: they are executable examples of what it does.

## 3. Python ideas you will meet

| Idea | What it is | Where |
|---|---|---|
| Type hints | `def f(x: int) -> str` documents and lets tools check types; Python doesn't enforce them at runtime | everywhere |
| Pydantic `BaseModel` | a class whose fields are **validated** when created (wrong type or missing field = error) | `config.py`, `metadata.py`, `extract.py` |
| `ConfigDict(extra="forbid", frozen=True)` | unknown fields are errors; objects can't be modified after creation | `config.py` `_Strict` |
| `Protocol` | an interface by shape: any class with these methods fits, no inheritance needed | `embeddings.py` `Embedder`, `llm.py` `LLMClient`, `loaders/base.py` `Loader` |
| `@dataclass` | a plain class for holding data, with `__init__` generated | `register.py` `RegisterReport` |
| Context manager (`with`) | guarantees cleanup (closing a DB) even if an error happens | `with Manifest(path) as m:` in `cli.py` |
| `with self._conn:` | one SQLite **transaction**: all changes commit together or none do | `manifest.py` |
| Generator / `rglob` | lazily walks folders | `discovery.py` |
| `pathlib.Path` | paths as objects (`root / "a" / "b.pdf"`) that work on Windows and Linux | everywhere |
| Dependency injection | functions receive their collaborators (`embedder`, `store`, `llm`) as parameters instead of creating them; tests pass fakes | `rag.ask`, `index.index_all` |
| `httpx.MockTransport` | fake HTTP server inside the test: real client code, no network | `tests/test_embeddings.py`, `tests/test_llm.py` |
| pytest fixtures | reusable test setup, injected by parameter name | `tests/conftest.py` (`project`, `settings`) |
| `monkeypatch` | temporarily replace something during a test (env var, function) | `tests/test_cli.py` `fake_services` |

## 4. How to check things yourself

```bash
uv run pytest tests/test_rag.py -v              # one file, verbose: each test name = one behaviour
uv run pytest -k citations -v                   # tests whose name contains "citations"
uv run pytest tests/test_rag.py -x --pdb        # stop at the first failure inside the debugger
```
- Put `breakpoint()` in any line and run a command: execution stops there (`n` next line,
  `p variable` print, `c` continue, `q` quit).
- The manifest is a normal SQLite file: `sqlite3 data/manifest.sqlite "select rel_path from documents"`
  (or open it with DB Browser for SQLite).
- Every stage output is JSON you can open: `data/processed/<user>/<doc_id>.json`, `data/chunks/...`.
- Qdrant has a web dashboard: http://localhost:6333/dashboard (collections, points, payloads).
- Every `ask` is a line in `logs/queries.jsonl`.

## 5. Where AI-written code is most likely to be wrong here

These are the places to review hardest (each already has tests, but tests only cover what someone
thought of):
- **Heuristics tuned on few examples**: title detection (`loaders/pdf.py` `guess_title`),
  boilerplate thresholds (`cleaning.py`), doc_type keywords (`detection.py`). Check them on more
  real documents with `inspect` and `chunk`'s audit list.
- **Deleting things**: `prune.py`. Read the rules for when deletion is allowed.
- **Anything that filters by user**: `store.py` `_user_filter`. A bug there leaks one user's notes
  to another (`tests/test_store.py` has an isolation test).
- **The prompt**: `rag.py` `SYSTEM_PROMPT`. Its effect is only known by running `eval --answers`.
