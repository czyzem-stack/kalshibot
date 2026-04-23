# One command to run the API + dashboard locally (Windows PowerShell).
# Opens the backend in a new window; runs the Vite dev server in this window.
#
# Usage (from repo root):
#   .\scripts\launch_local.ps1
#
# First time only:  .\scripts\create_venv.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Py = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Py)) {
    Write-Error "Missing .venv. Run first:  .\scripts\create_venv.ps1"
    exit 1
}

$backendScript = Join-Path $RepoRoot "scripts\run_backend.ps1"

Write-Host ""
Write-Host "Starting backend in a new window..." -ForegroundColor Cyan
Write-Host "  (API: http://127.0.0.1:8765 unless KALSHI_BOT_PORT is set)" -ForegroundColor DarkGray

Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-File", $backendScript
) -WorkingDirectory $RepoRoot

$port = 8765
if ($env:KALSHI_BOT_PORT -and $env:KALSHI_BOT_PORT -match "^\d+$") {
    $port = [int]$env:KALSHI_BOT_PORT
}
Write-Host "Waiting for API (http://127.0.0.1:$port/api/health)..." -ForegroundColor DarkGray
$ready = $false
$healthUrl = "http://127.0.0.1:$port/api/health"
for ($i = 0; $i -lt 60; $i++) {
    try {
        $r = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {
        # uvicorn still starting or port in use elsewhere
    }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) {
    Write-Warning "API did not respond on $healthUrl yet. If the UI shows an error, wait a few seconds and click Refresh, or check the backend window for Python errors."
}

$frontend = Join-Path $RepoRoot "frontend"
if (-not (Test-Path -LiteralPath (Join-Path $frontend "node_modules"))) {
    Write-Host ""
    Write-Host "First run: installing frontend dependencies (npm install)..." -ForegroundColor Yellow
    Set-Location $frontend
    npm install
} else {
    Set-Location $frontend
}

Write-Host ""
Write-Host "Starting dashboard here (Vite). Open:" -ForegroundColor Cyan
Write-Host "  http://localhost:5173" -ForegroundColor Green
Write-Host ""
Write-Host "Press Ctrl+C in this window to stop the UI. Close the other window to stop the API." -ForegroundColor DarkGray
Write-Host ""

npm run dev
