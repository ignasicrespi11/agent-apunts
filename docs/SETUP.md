# Setup

Per machine there are 4 steps: **(1) run the setup script**, **(2) get the private PDFs via OneDrive**,
**(3) create `.env`** pointing to them, **(4) `uv sync` + check config + start Qdrant**. Step 5 is the first pipeline run. The scripts are safe to re-run.

The script installs the tools, logs in to GitHub, clones the repo, enables the pre-commit hook
(blocks committing course material) and installs Python 3.12.

## 1. Setup script

### Windows 11
Fresh machine (no git yet), in PowerShell:

```powershell
irm https://raw.githubusercontent.com/ignasicrespi11/agent-apunts/main/scripts/setup-windows.ps1 -OutFile setup-windows.ps1
powershell -ExecutionPolicy Bypass -File setup-windows.ps1
```

Already cloned: `powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1`

- The script also installs **Ollama** and pulls `bge-m3` (embeddings, ~1.2 GB). On the PC with the GTX 1080
  Ollama uses the GPU automatically; elsewhere the CPU is enough for embeddings.
- Docker Desktop needs WSL2. If the script warns about it, in an **admin** PowerShell run
  `wsl --install --no-distribution`, reboot, open Docker Desktop once, then re-run the script.

### Omarchy (Arch Linux)
```bash
curl -fsSL https://raw.githubusercontent.com/ignasicrespi11/agent-apunts/main/scripts/setup-omarchy.sh -o setup-omarchy.sh
bash setup-omarchy.sh
```

Already cloned: `bash scripts/setup-omarchy.sh`. Log out and back in afterwards (docker group).

Both scripts clone the repo to **`~/code/agent-apunts`** (Windows: `$HOME\code\agent-apunts`; change it with
`DIR=...` / `-Dir ...`) and create `.env` from `.env.example` if it doesn't exist yet. If the OneDrive folder `_UNI/apunts_testing` is already synced, they also fill in `TESTING_DIR` (re-run the script after OneDrive finishes syncing). Every later command runs from that folder.

## 2. Private PDFs (OneDrive)

Course material is copyrighted and **never in git**. The single source of truth is OneDrive (UAB account):
`OneDrive - UAB/_UNI/apunts_testing/<subject>/<doc_type>/*.pdf` (labelled set) and, later, `_UNI/apunts/` (inbox).
The pipeline only reads these files, so syncing them is safe (unlike putting the repo itself in OneDrive).

### Windows
Nothing to do: sign in to OneDrive with the UAB account; the folder appears at
`C:\Users\<you>\OneDrive - UAB\_UNI\apunts_testing`.

### Omarchy
Microsoft has no official Linux client. Use the open-source `onedrive` client (supports work/school accounts):

```bash
yay -S onedrive-abraunegg
mkdir -p ~/.config/onedrive
printf '_UNI/apunts_testing\n_UNI/apunts\n' > ~/.config/onedrive/sync_list   # sync only these folders
onedrive                 # first run: open the URL, sign in with UAB, paste the final URL back
onedrive --sync --resync # first full sync (needed after creating/changing sync_list)
systemctl --user enable --now onedrive   # keep it in sync in the background
```

Files end up in `~/OneDrive/_UNI/...`.
- If UAB blocks the app ("admin approval required"), use `rclone` (`sudo pacman -S rclone`, `rclone config` → OneDrive → Business),
  or copy the folder once from Windows (USB / `scp`). The labelled set rarely changes.

## 3. `.env` (one per machine, never committed)

```bash
cd ~/code/agent-apunts
cp -n .env.example .env   # Windows: copy .env.example .env  (skip if the script already created it)
```

Then edit `.env` and set the folder from step 2:

```
TESTING_DIR=C:\Users\<you>\OneDrive - UAB\_UNI\apunts_testing   # Windows
TESTING_DIR=/home/<you>/OneDrive/_UNI/apunts_testing            # Omarchy
```

Empty values fall back to `./apunts` and `./testing/apunts_testing`. Claude Code is denied access to `.env`
(it will hold API keys), so this file is always edited by hand.

Check the path is right (should print `True`):

```powershell
Test-Path "C:\Users\<you>\OneDrive - UAB\_UNI\apunts_testing"
```
```bash
test -d ~/OneDrive/_UNI/apunts_testing && echo True
```

## 4. Python environment, Qdrant and Ollama

The Python code runs natively (uv); Qdrant (vector database) runs in Docker; Ollama (embedding model,
later the LLM) runs natively as a background service (installed by the setup script).

```bash
uv sync                  # creates .venv/ with the exact versions from uv.lock
uv run pytest            # should pass
docker compose up -d     # starts Qdrant (Docker Desktop must be running on Windows)
```

One command checks the whole machine (folders, Ollama and its models, Qdrant, pipeline progress) and
prints the fix for anything missing:

```bash
uv run agent-apunts doctor
```

Check `.env` is read correctly (paths resolved, PDFs counted per subject; secrets are never printed):

```bash
uv run agent-apunts config   # labelled set: 108 documents, no "problem" lines
```

Check Qdrant is up: `curl.exe http://localhost:6333/readyz` (Windows) or `curl http://localhost:6333/readyz`
should print `all shards are ready`. Dashboard: http://localhost:6333/dashboard.
Vectors live in the Docker volume `qdrant_storage` (survives restarts). `docker compose down -v` deletes them;
they can always be rebuilt by re-ingesting.

Check Ollama has the embedding model: `ollama list` must show `bge-m3`. If not: `ollama pull bge-m3`
(Windows: open the Ollama app once first; Omarchy: `systemctl status ollama`).

## 5. First pipeline run (labelled set)

```bash
uv run agent-apunts register          # stage 1: content-hash IDs -> data/manifest.sqlite
uv run agent-apunts extract           # stage 2: text, title, language, thumbnails -> data/processed/
uv run agent-apunts inspect IS2425    # what was extracted from a document (part of its name or doc_id)
uv run agent-apunts inspect IS2425 --page 3   # full text of one page: compare it with the PDF
uv run agent-apunts chunk             # stages 3+4: remove boilerplate, split into chunks -> data/chunks/
uv run agent-apunts inspect IS2425 --chunks   # chunks of a document + the boilerplate that was removed
uv run agent-apunts index             # stage 5: embed with Ollama, store in Qdrant (needs both running)
uv run agent-apunts search "què és el patró observer?"   # nearest chunks, any language
uv run agent-apunts search "TLB" --subject arquitectura_computadors
```

Or all stages at once: `uv run agent-apunts ingest` (register → prune → extract → chunk → index). Every
stage is incremental: re-running only processes new or changed work (`--force` redoes all), re-indexing
never duplicates points, and moving a PDF between folders only updates its metadata in Qdrant.
`prune` (also run by `ingest`) forgets PDFs you deleted or replaced; `prune --dry-run` lists them first.

```bash
uv run agent-apunts images            # how much content hides in images (code screenshots, diagrams)
```

## 6. Answers and evaluation (week 4)

```bash
ollama pull qwen2.5:7b                # local LLM (free); on a CPU-only machine answers are slow
uv run agent-apunts ask "Què diu el patró Creator?"          # answer + [n] citations, or abstains
uv run agent-apunts ask "TLB" --subject arquitectura_computadors
cp eval/golden.example.yaml eval/golden.yaml   # then write your own questions (eval/README.md)
uv run agent-apunts eval --sweep      # hit@k, MRR, abstention; pick retrieval.min_score from the sweep
```
Every `ask` is appended to `logs/queries.jsonl` (gitignored) with your user_id.

```bash
uv run agent-apunts detect --evaluate # accuracy of subject/doc_type auto-detection on your labelled PDFs
uv run agent-apunts detect            # suggestions for PDFs dropped in apunts/ without folders
```
Everything goes to `data/` (gitignored: it is derived from copyrighted material).

Optional, with Qdrant running: `QDRANT_TEST_URL=http://localhost:6333 uv run pytest tests/test_store_server.py`
(Windows PowerShell: `$env:QDRANT_TEST_URL="http://localhost:6333"; uv run pytest tests/test_store_server.py`)
tests the store against the real server in a throwaway collection.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `docker` not recognized (Windows) | WSL2 missing: see step 1. Then open Docker Desktop once and open a new terminal. |
| `docker: permission denied` (Arch) | Log out and back in after the script adds you to the `docker` group. |
| uv: `Missing expected target directory for Python minor version link` (Windows) | Harmless: Python is installed. Check with `uv run --python 3.12 --no-project python --version`. |
| Script blocked by execution policy | Use `powershell -ExecutionPolicy Bypass -File ...` as shown above. |
| A new tool is "not recognized" right after installing | Open a new terminal (PATH is only refreshed in new sessions). |
| `.env` saved as `.env.txt` (Notepad) | Rename it, or save with "All files (*.*)" as the type. Check with `dir /a` or `ls -a`. |
| `failed to connect to the docker API ... dockerDesktopLinuxEngine` | Docker Desktop is not running: open it and wait until it says "Engine running". |
| `cannot reach Ollama` / `ollama pull bge-m3` in `index` or `search` | Start Ollama (Windows: the Ollama app; Omarchy: `sudo systemctl start ollama`) and pull the model. |
| `ask` is very slow on Omarchy | A 7B model on a CPU takes minutes. Use the GTX 1080 PC, or a smaller model in `settings.yaml` (`llm.model`, e.g. `qwen2.5:3b`). |
| `cannot reach Qdrant` | `docker compose up -d` (Windows: Docker Desktop must be running). |
| `collection 'apunts' was built with ...` | The embedding model changed: set a new `qdrant.collection` in `settings.yaml` and run `index`. |
| OneDrive (Omarchy) syncs nothing | After editing `sync_list`, run `onedrive --sync --resync`. |
| uv: `Querying Python ... failed with exit status exit code: 0xc0e90002` (Windows 11) | **Smart App Control** blocks unsigned programs (uv's Python, and wheels like PyMuPDF/numpy). Either turn it off (Settings → Privacy & security → Windows Security → App & browser control → Smart App Control → Off; read Windows' warning: it may not be re-enabled without reinstalling) and run `uv python install 3.12 --reinstall`, or keep it on and work inside WSL2 (follow the Omarchy steps there). |

## After setup
Start a Claude Code session in the repo folder, pick the model (Opus for new foundations, Sonnet otherwise) and run `/start-session`.
