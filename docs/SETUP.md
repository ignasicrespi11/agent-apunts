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

- On the PC with the GTX 1080, add `-WithOllama`.
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

## 4. Python environment and Qdrant

The Python code runs natively (uv); only Qdrant (vector database) runs in Docker.

```bash
uv sync                  # creates .venv/ with the exact versions from uv.lock
uv run pytest            # should pass
docker compose up -d     # starts Qdrant (Docker Desktop must be running on Windows)
```

Check `.env` is read correctly (paths resolved, PDFs counted per subject; secrets are never printed):

```bash
uv run agent-apunts config   # labelled set: 108 documents, no "problem" lines
```

Check Qdrant is up: `curl.exe http://localhost:6333/readyz` (Windows) or `curl http://localhost:6333/readyz`
should print `all shards are ready`. Dashboard: http://localhost:6333/dashboard.
Vectors live in the Docker volume `qdrant_storage` (survives restarts). `docker compose down -v` deletes them;
they can always be rebuilt by re-ingesting.

## 5. First pipeline run (labelled set)

```bash
uv run agent-apunts register          # stage 1: content-hash IDs -> data/manifest.sqlite
uv run agent-apunts extract           # stage 2: text, title, language, thumbnails -> data/processed/
uv run agent-apunts inspect IS2425    # what was extracted from a document (part of its name or doc_id)
uv run agent-apunts inspect IS2425 --page 3   # full text of one page: compare it with the PDF
```

Both stages are incremental: re-running only processes new or changed files (`extract --force` redoes all).
Everything goes to `data/` (gitignored: it is derived from copyrighted material).

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
| OneDrive (Omarchy) syncs nothing | After editing `sync_list`, run `onedrive --sync --resync`. |

## After setup
Start a Claude Code session in the repo folder, pick the model (Opus for new foundations, Sonnet otherwise) and run `/start-session`.
