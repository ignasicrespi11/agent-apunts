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
function Succeeds([scriptblock]$Command) {
    # Native tools (wsl, gh, docker) write to stderr when a check fails. Windows PowerShell 5.1 turns
    # that into a terminating error under ErrorActionPreference=Stop, which aborted the script on a
    # PC without WSL. So run the check with Continue and only look at the exit code.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Command *> $null; return ($LASTEXITCODE -eq 0) }
    catch { return $false }
    finally { $ErrorActionPreference = $previous }
}
function Winget-Install($id) {
    if (Succeeds { winget list --id $id -e --accept-source-agreements }) {
        Write-Host "  $id already installed"; return
    }
    winget install --id $id -e --silent --accept-source-agreements --accept-package-agreements
}

Step "Installing tools with winget"
$tools = @("Git.Git", "GitHub.cli", "astral-sh.uv", "Microsoft.VisualStudioCode", "Docker.DockerDesktop")
if ($WithOllama) { $tools += "Ollama.Ollama" }
foreach ($t in $tools) { Winget-Install $t }
Refresh-Path

Step "Checking WSL2 (required by Docker Desktop)"
if (-not (Succeeds { wsl --status })) {
    Write-Host "  WSL2 is not installed. Run this in an ADMIN PowerShell, reboot, then re-run this script:" -ForegroundColor Yellow
    Write-Host "      wsl --install --no-distribution" -ForegroundColor Yellow
    Write-Host "  (Docker/Qdrant is only needed from week 3: the rest of the setup continues.)" -ForegroundColor Yellow
} else { Write-Host "  WSL2 OK" }

Step "Git identity"
if (-not (git config --global user.name))  { git config --global user.name  (Read-Host "  Your full name for commits") }
if (-not (git config --global user.email)) { git config --global user.email (Read-Host "  Your GitHub email") }
git config --global init.defaultBranch main

Step "GitHub login"
if (-not (Succeeds { gh auth status })) { gh auth login --hostname github.com --git-protocol https --web }

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
if ($LASTEXITCODE -ne 0) {
    # Seen on a fresh Windows 11 PC: exit code 0xc0e90002 = STATUS_SYSTEM_INTEGRITY_POLICY_VIOLATION.
    Write-Host "  Python was installed but Windows refused to run it." -ForegroundColor Yellow
    Write-Host "  If the error says 0xc0e90002, Smart App Control is blocking unsigned programs: see" -ForegroundColor Yellow
    Write-Host "  docs\SETUP.md > Troubleshooting (turn it off, or work inside WSL2)." -ForegroundColor Yellow
}

Step "Local config"
$EnvFile = "$Dir\.env"
if (-not (Test-Path $EnvFile)) { Copy-Item "$Dir\.env.example" $EnvFile; Write-Host "  Created .env" }
New-Item -ItemType Directory -Force "$Dir\apunts", "$Dir\testing\apunts_testing" | Out-Null
# Point TESTING_DIR at the OneDrive copy of the labelled set, if it exists and .env leaves it empty.
# OneDriveCommercial is set by the OneDrive client for work/school accounts (UAB).
$Corpus = @($env:OneDriveCommercial, "$HOME\OneDrive - UAB") |
    Where-Object { $_ } | ForEach-Object { Join-Path $_ "_UNI\apunts_testing" } |
    Where-Object { Test-Path $_ } | Select-Object -First 1
$EnvLines = [string[]](Get-Content $EnvFile)
if ($Corpus -and ($EnvLines -contains "TESTING_DIR=")) {
    $EnvLines = [string[]]($EnvLines | ForEach-Object { if ($_ -eq "TESTING_DIR=") { "TESTING_DIR=$Corpus" } else { $_ } })
    # WriteAllLines writes UTF-8 without BOM (Set-Content in PowerShell 5.1 would use ANSI or add a BOM).
    [System.IO.File]::WriteAllLines($EnvFile, $EnvLines)
    Write-Host "  TESTING_DIR set to $Corpus"
} elseif ($Corpus) { Write-Host "  TESTING_DIR already set in .env (left as is)" }
else { Write-Host "  OneDrive folder _UNI\apunts_testing not found yet: sign in to OneDrive (UAB), then re-run" -ForegroundColor Yellow }

Step "Docker"
if (Get-Command docker -ErrorAction SilentlyContinue) {
    if (Succeeds { docker info }) { Write-Host "  Docker is running" }
    else { Write-Host "  Docker installed but not running: open Docker Desktop once and wait for it to start." -ForegroundColor Yellow }
} else { Write-Host "  'docker' not on PATH yet: open Docker Desktop once, then open a NEW terminal." -ForegroundColor Yellow }

Step "Done"
Write-Host "  NEXT, in a NEW terminal:  cd $Dir ; uv sync ; uv run agent-apunts config"
Write-Host "  (config must list the labelled set: 108 documents. See docs\SETUP.md steps 4-5.)"
