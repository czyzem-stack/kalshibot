# Run API + Vite for the `main` worktree while you use `develop` in this repo (different ports + data/).
#
# Prereqs:
#   - Ran .\scripts\setup-main-worktree.ps1
#   - Worktree has root .env (KALSHI_BOT_PORT=8770 recommended) and frontend/.env (VITE_API_ORIGIN=http://127.0.0.1:8770)
#   - Optional: .\scripts\create_venv.ps1 inside the worktree; else this script uses THIS repo's .venv
#
# Usage (from DEVELOP repo root):
#   .\scripts\launch-main-sidecar.ps1
#   .\scripts\launch-main-sidecar.ps1 -WorktreePath "D:\repos\Kalshibot-main"
#
# Opens API in a new PowerShell window; runs Vite on port 5174 in this window.

param(
    [string]$WorktreePath = ""
)

$ErrorActionPreference = "Stop"
$DevelopRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $WorktreePath) {
    $WorktreePath = [System.IO.Path]::GetFullPath((Join-Path $DevelopRoot "..\Kalshibot-main"))
} else {
    $WorktreePath = [System.IO.Path]::GetFullPath($WorktreePath)
}

if (-not (Test-Path -LiteralPath (Join-Path $WorktreePath ".git"))) {
    Write-Error "Worktree not found at: $WorktreePath`nRun:  .\scripts\setup-main-worktree.ps1"
}

$PyWt = Join-Path $WorktreePath ".venv\Scripts\python.exe"
$PyDev = Join-Path $DevelopRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $PyWt) {
    $Py = $PyWt
} elseif (Test-Path -LiteralPath $PyDev) {
    $Py = $PyDev
    Write-Host "Using develop repo venv: $Py" -ForegroundColor DarkYellow
} else {
    Write-Error "No Python at $PyWt or $PyDev. Run .\scripts\create_venv.ps1 in develop or in the worktree."
}

$port = 8770
$envFile = Join-Path $WorktreePath ".env"
if (Test-Path -LiteralPath $envFile) {
    $m = Select-String -Path $envFile -Pattern '^\s*KALSHI_BOT_PORT\s*=\s*(\d+)\s*$' | Select-Object -First 1
    if ($null -ne $m -and $m.Matches.Count -gt 0) {
        $port = [int]$m.Matches[0].Groups[1].Value
    }
}

$runner = Join-Path $DevelopRoot "scripts\run_backend_at.ps1"

Write-Host "Starting MAIN worktree API in new window (port $port)..." -ForegroundColor Cyan
Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-File", $runner,
    "-RepoRoot", $WorktreePath,
    "-PythonExe", $Py,
    "-Port", "$port"
) -WorkingDirectory $WorktreePath

$healthUrl = "http://127.0.0.1:$port/api/health"
Write-Host "Waiting for $healthUrl ..." -ForegroundColor DarkGray
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $r = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) {
    Write-Warning "API did not respond yet. Check the new window for errors (missing .env, port in use, etc.)."
}

$fe = Join-Path $WorktreePath "frontend"
if (-not (Test-Path -LiteralPath (Join-Path $fe "node_modules"))) {
    Write-Host "Installing frontend deps in worktree..." -ForegroundColor Yellow
    Set-Location $fe
    npm install
} else {
    Set-Location $fe
}

Write-Host ""
Write-Host "Starting MAIN dashboard (Vite) on http://localhost:5174 - proxy -> $healthUrl" -ForegroundColor Green
Write-Host "Develop stays on http://localhost:5173 -> http://127.0.0.1:8765" -ForegroundColor DarkGray
Write-Host "Press Ctrl+C here to stop Vite only; close the API window to stop uvicorn." -ForegroundColor DarkGray
Write-Host ""

npm run dev -- --port 5174 --strictPort
