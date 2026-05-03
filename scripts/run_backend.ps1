# Runs the API with the repo .venv (does not change your default Python).
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Py = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Py)) {
    Write-Error "Missing .venv. Run first:  .\scripts\create_venv.ps1"
    exit 1
}

Set-Location $RepoRoot

# Port 8000 is often blocked on Windows (excluded port ranges / Hyper-V). Override if needed:
#   $env:KALSHI_BOT_PORT = "8080"; .\scripts\run_backend.ps1
$port = 8765
if ($env:KALSHI_BOT_PORT -and $env:KALSHI_BOT_PORT -match "^\d+$") {
    $port = [int]$env:KALSHI_BOT_PORT
}

Write-Host "Starting API on http://127.0.0.1:$port (set KALSHI_BOT_PORT to change)" -ForegroundColor Cyan
Write-Host "Note: --reload restarts Python on file saves; Vite may log ECONNRESET for in-flight /api/* until the browser retries. Omit --reload for a stable long-run panel." -ForegroundColor DarkGray
& $Py -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port $port
