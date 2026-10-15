# Run Qdrant natively on Windows, WITHOUT Docker. Fallback for PCs where Docker Desktop cannot start
# (e.g. "Virtualization is disabled in firmware" and the BIOS can't be changed right now).
# Usage (from the repo folder; keep this window open, Ctrl+C stops Qdrant):
#   powershell -ExecutionPolicy Bypass -File scripts\qdrant-windows.ps1
# Same version as docker-compose.yml (read from it, so the two never drift), same localhost-only port.
# Vectors are stored in $HOME\.qdrant\storage, NOT in the Docker volume: switching between the two
# means re-running `agent-apunts index` (the index stage notices the empty collection and rebuilds it).
$ErrorActionPreference = "Stop"

$Compose = Join-Path $PSScriptRoot "..\docker-compose.yml"
$Match = Select-String -Path $Compose -Pattern "qdrant/qdrant:v([\d.]+)" | Select-Object -First 1
if (-not $Match) { throw "Could not read the Qdrant version from docker-compose.yml" }
$Version = $Match.Matches[0].Groups[1].Value

$Root = Join-Path $HOME ".qdrant"
$BinDir = Join-Path $Root "v$Version"
$Exe = Join-Path $BinDir "qdrant.exe"
if (-not (Test-Path $Exe)) {
    New-Item -ItemType Directory -Force $BinDir | Out-Null
    $Zip = Join-Path $Root "qdrant-$Version.zip"
    $Url = "https://github.com/qdrant/qdrant/releases/download/v$Version/qdrant-x86_64-pc-windows-msvc.zip"
    Write-Host "Downloading Qdrant $Version (~30 MB) from GitHub releases..."
    Invoke-WebRequest -Uri $Url -OutFile $Zip -UseBasicParsing
    Expand-Archive -Path $Zip -DestinationPath $BinDir -Force
    Remove-Item $Zip
}

# Qdrant reads its settings from QDRANT__SECTION__KEY environment variables.
$env:QDRANT__SERVICE__HOST = "127.0.0.1"   # localhost only, like the Docker port mapping
$env:QDRANT__STORAGE__STORAGE_PATH = Join-Path $Root "storage"
$env:QDRANT__STORAGE__SNAPSHOTS_PATH = Join-Path $Root "snapshots"
# Run from its own folder: Qdrant also reads ./config/*.yaml, and the repo's config/ is ours, not Qdrant's.
Set-Location $BinDir
Write-Host "Qdrant $Version on http://localhost:6333 (storage: $env:QDRANT__STORAGE__STORAGE_PATH). Ctrl+C to stop."
& $Exe
