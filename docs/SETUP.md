# Setup

One script per platform installs the tools, logs in to GitHub, clones the repo, enables the
pre-commit hook and installs Python 3.12. Both scripts are safe to re-run.

## Windows 11

Fresh machine (no git yet), in PowerShell:

```powershell
irm https://raw.githubusercontent.com/ignasicrespi11/agent-apunts/main/scripts/setup-windows.ps1 -OutFile setup-windows.ps1
powershell -ExecutionPolicy Bypass -File setup-windows.ps1
```

Already cloned: `powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1`

On the PC with the GTX 1080, add `-WithOllama`.

## Omarchy (Arch Linux)

Fresh machine:

```bash
curl -fsSL https://raw.githubusercontent.com/ignasicrespi11/agent-apunts/main/scripts/setup-omarchy.sh -o setup-omarchy.sh
bash setup-omarchy.sh
```

Already cloned: `bash scripts/setup-omarchy.sh`

## Troubleshooting

| Symptom | Fix |
|---|---|
| `docker` not recognized (Windows) | Docker Desktop needs WSL2: in an **admin** PowerShell run `wsl --install --no-distribution`, reboot, open Docker Desktop once, then open a new terminal. |
| `docker: permission denied` (Arch) | Log out and back in after the script adds you to the `docker` group. |
| uv: `Missing expected target directory for Python minor version link` (Windows) | Harmless: Python is installed. Check with `uv run --python 3.12 --no-project python --version`. |
| Script blocked by execution policy | Use `powershell -ExecutionPolicy Bypass -File ...` as shown above. |
| A new tool is "not recognized" right after installing | Open a new terminal (PATH is only refreshed in new sessions). |

## After setup
- Real PDFs go in `apunts/`; the manually labelled set in `testing/apunts_testing/<subject>/<doc_type>/`. Neither is ever committed.
- Start a Claude Code session in the repo folder, choose Sonnet, run `/start-session`.
