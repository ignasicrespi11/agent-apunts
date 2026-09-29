# Setup agent-apunts on a Windows 11 machine. Safe to re-run (idempotent).
# Usage (from an existing clone):   powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1
# Usage (fresh machine): see docs/SETUP.md
# Options: -Dir <path>   where to clone (default: $HOME\code\agent-apunts)
#          -WithOllama   also install Ollama (only on the machine with the GPU)
param(
    [string]$Dir = "$HOME\code\agent-apunts",
    [switch]$WithOllama
)
$ErrorActionPreference = "Stop"
$Repo = "ignasicrespi11/agent-apunts"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}
function Winget-Install($id) {
    winget list --id $id -e --accept-source-agreements *> $null
    if ($LASTEXITCODE -eq 0) { Write-Host "  $id already installed"; return }
    winget install --id $id -e --silent --accept-source-agreements --accept-package-agreements
}

Step "Installing tools with winget"
$tools = @("Git.Git", "GitHub.cli", "astral-sh.uv", "Microsoft.VisualStudioCode", "Docker.DockerDesktop")
if ($WithOllama) { $tools += "Ollama.Ollama" }
foreach ($t in $tools) { Winget-Install $t }
Refresh-Path

Step "Checking WSL2 (required by Docker Desktop)"
wsl --status *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  WSL2 is not installed. Run this in an ADMIN PowerShell, reboot, then re-run this script:" -ForegroundColor Yellow
    Write-Host "      wsl --install --no-distribution" -ForegroundColor Yellow
} else { Write-Host "  WSL2 OK" }

Step "Git identity"
if (-not (git config --global user.name))  { git config --global user.name  (Read-Host "  Your full name for commits") }
if (-not (git config --global user.email)) { git config --global user.email (Read-Host "  Your GitHub email") }
git config --global init.defaultBranch main

Step "GitHub login"
gh auth status *> $null
if ($LASTEXITCODE -ne 0) { gh auth login --hostname github.com --git-protocol https --web }

Step "Repository"
if (-not (Test-Path "$Dir\.git")) {
    New-Item -ItemType Directory -Force (Split-Path $Dir) | Out-Null
    gh repo clone $Repo $Dir
} else { Write-Host "  Already cloned at $Dir"; git -C $Dir pull --ff-only }
git -C $Dir config core.hooksPath .githooks
Write-Host "  Pre-commit hook enabled (blocks committing course material)"

Step "Python 3.12 via uv"
# uv may print 'Missing expected target directory for Python minor version link': harmless on Windows.
uv python install 3.12
uv run --python 3.12 --no-project python --version

Step "Local config"
if (-not (Test-Path "$Dir\.env")) { Copy-Item "$Dir\.env.example" "$Dir\.env"; Write-Host "  Created .env (fill it in later)" }
New-Item -ItemType Directory -Force "$Dir\apunts", "$Dir\testing\apunts_testing" | Out-Null

Step "Docker"
if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker info *> $null
    if ($LASTEXITCODE -eq 0) { Write-Host "  Docker is running" }
    else { Write-Host "  Docker installed but not running: open Docker Desktop once and wait for it to start." -ForegroundColor Yellow }
} else { Write-Host "  'docker' not on PATH yet: open Docker Desktop once, then open a NEW terminal." -ForegroundColor Yellow }

Step "Done"
Write-Host "  Open the project: code `"$Dir`"  (VS Code will offer 'Reopen in Container' once the devcontainer exists)"
Write-Host "  Copy your PDFs into $Dir\apunts\ (labelled set: $Dir\testing\apunts_testing\<subject>\<doc_type>\) (they are never committed)"
