# Run API + Vite locally (Windows PowerShell).
#
# Default: starts **develop** (this repo) — API :8765 + UI http://localhost:5173
#
# If a **main** git worktree exists (sibling ..\Kalshibot-main **or** any path from `git worktree list`
# with branch [main]) **and** that checkout has a `.env` file, also starts that stack in separate windows —
# API :8770 + UI http://localhost:5174 (see scripts\setup-main-worktree.ps1).
#
# Usage (from repo root):
#   .\scripts\launch_local.ps1
#   .\scripts\launch_local.ps1 -SkipMainSidecar          # only develop (legacy single-UI flow in THIS window)
#   .\scripts\launch_local.ps1 -WorktreePath "D:\repos\Kalshibot-main"
#
# First time only:  .\scripts\create_venv.ps1

param(
    [switch]$SkipMainSidecar,
    [string]$WorktreePath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Py = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Py)) {
    Write-Error "Missing .venv. Run first:  .\scripts\create_venv.ps1"
    exit 1
}

function Get-LinkedMainWorktreePath([string]$Repo) {
    try {
        $lines = @(git -C $Repo worktree list 2>$null)
    } catch {
        return $null
    }
    if (-not $lines) { return $null }
    $repoCanon = [System.IO.Path]::GetFullPath($Repo)
    foreach ($line in $lines) {
        if ($line -notmatch '\s\[main\]\s*$') { continue }
        if ($line -match '\s+([0-9a-f]{7,})\s+\[main\]\s*$') {
            $pathPart = $line.Substring(0, $line.Length - $matches[0].Length).TrimEnd()
            if (-not $pathPart) { continue }
            $p = [System.IO.Path]::GetFullPath($pathPart)
            if ($p -ne $repoCanon) { return $p }
        }
    }
    return $null
}

if (-not $WorktreePath) {
    $fromGit = Get-LinkedMainWorktreePath $RepoRoot
    if ($fromGit) {
        $WorktreePath = $fromGit
        Write-Host "[launch_local] Main worktree path from git: $WorktreePath" -ForegroundColor DarkGray
    } else {
        $WorktreePath = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "..\Kalshibot-main"))
    }
} else {
    $WorktreePath = [System.IO.Path]::GetFullPath($WorktreePath)
}

$useMainSidecar = $false
$wtGit = Join-Path $WorktreePath ".git"
$wtEnv = Join-Path $WorktreePath ".env"
if (-not $SkipMainSidecar) {
    $hasGit = Test-Path -LiteralPath $wtGit
    $hasEnv = Test-Path -LiteralPath $wtEnv
    if ($hasGit -and $hasEnv) {
        $useMainSidecar = $true
    } elseif (-not $hasGit -and -not $hasEnv) {
        Write-Host ""
        Write-Host "[launch_local] Dual UI (5173+5174): OFF - no main checkout at:" -ForegroundColor Yellow
        Write-Host "           $WorktreePath" -ForegroundColor DarkGray
        Write-Host "           Run:  .\scripts\setup-main-worktree.ps1  then  .\scripts\bootstrap-main-worktree.ps1" -ForegroundColor Yellow
    } elseif ($hasGit -and -not $hasEnv) {
        Write-Host ""
        Write-Host "[launch_local] Dual UI: OFF - main worktree exists but there is no .env file:" -ForegroundColor Yellow
        Write-Host "           $wtEnv" -ForegroundColor DarkGray
        Write-Host "           Run:  .\scripts\bootstrap-main-worktree.ps1   (or copy .env.example -> .env and merge ENV_SIDECAR.example)" -ForegroundColor Yellow
    }
}

$devPort = 8765
if ($env:KALSHI_BOT_PORT -and $env:KALSHI_BOT_PORT -match "^\d+$") {
    $devPort = [int]$env:KALSHI_BOT_PORT
}

function Wait-Health([string]$Url, [string]$Label) {
    Write-Host "Waiting for $Label ($Url)..." -ForegroundColor DarkGray
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($r.StatusCode -eq 200) { return $true }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

# --- Develop API ---
Write-Host ""
Write-Host "Starting DEVELOP API in a new window..." -ForegroundColor Cyan
Write-Host "  http://127.0.0.1:$devPort (override with `$env:KALSHI_BOT_PORT)" -ForegroundColor DarkGray

$backendScript = Join-Path $RepoRoot "scripts\run_backend.ps1"
Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-File", $backendScript
) -WorkingDirectory $RepoRoot

$mainPort = 8770
if ($useMainSidecar) {
    $envFile = Join-Path $WorktreePath ".env"
    $m = Select-String -Path $envFile -Pattern '^\s*KALSHI_BOT_PORT\s*=\s*(\d+)\s*$' | Select-Object -First 1
    if ($null -ne $m -and $m.Matches.Count -gt 0) {
        $mainPort = [int]$m.Matches[0].Groups[1].Value
    }
    if ($mainPort -eq $devPort) {
        Write-Warning "Main worktree KALSHI_BOT_PORT ($mainPort) matches develop ($devPort). Set a different port in $envFile (e.g. 8770). Skipping main sidecar."
        $useMainSidecar = $false
    }
}

if ($useMainSidecar) {
    $devEnvPath = Join-Path $RepoRoot ".env"
    $wtEnvPath = Join-Path $WorktreePath ".env"
    $sqlDev = $null
    $sqlWt = $null
    if (Test-Path -LiteralPath $devEnvPath) {
        $md = Select-String -LiteralPath $devEnvPath -Pattern '^\s*SQLITE_PATH\s*=\s*(.+)\s*$' | Select-Object -First 1
        if ($null -ne $md -and $md.Matches.Count -gt 0) {
            $sqlDev = $md.Matches[0].Groups[1].Value.Trim().Trim('"').Trim("'")
        }
    }
    if (Test-Path -LiteralPath $wtEnvPath) {
        $mw = Select-String -LiteralPath $wtEnvPath -Pattern '^\s*SQLITE_PATH\s*=\s*(.+)\s*$' | Select-Object -First 1
        if ($null -ne $mw -and $mw.Matches.Count -gt 0) {
            $sqlWt = $mw.Matches[0].Groups[1].Value.Trim().Trim('"').Trim("'")
        }
    }
    if ($sqlDev -and $sqlWt -and ($sqlDev -eq $sqlWt)) {
        Write-Warning "Develop and main worktree .env both set SQLITE_PATH to the same value ($sqlDev). Both APIs will share one database file. Remove SQLITE_PATH from one or both (defaults are separate per checkout) or use different paths."
    }
}

$runnerAt = Join-Path $RepoRoot "scripts\run_backend_at.ps1"
$PyMain = $Py
$PyWt = Join-Path $WorktreePath ".venv\Scripts\python.exe"
if ($useMainSidecar -and (Test-Path -LiteralPath $PyWt)) {
    $PyMain = $PyWt
}

if ($useMainSidecar) {
    Write-Host ""
    Write-Host "Starting MAIN worktree API in a new window..." -ForegroundColor Cyan
    Write-Host "  http://127.0.0.1:$mainPort  (worktree: $WorktreePath)" -ForegroundColor DarkGray
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-File", $runnerAt,
        "-RepoRoot", $WorktreePath,
        "-PythonExe", $PyMain,
        "-Port", "$mainPort"
    ) -WorkingDirectory $WorktreePath
}

if (-not (Wait-Health "http://127.0.0.1:$devPort/api/health" "develop API")) {
    Write-Warning "Develop API did not respond on port $devPort. Check the backend window for errors."
}

if ($useMainSidecar) {
    if (-not (Wait-Health "http://127.0.0.1:$mainPort/api/health" "main worktree API")) {
        Write-Warning "Main worktree API did not respond on port $mainPort. Check that worktree `.env` and `frontend/.env` (VITE_API_ORIGIN) match this port."
    }
}

$devFrontend = Join-Path $RepoRoot "frontend"
if (-not (Test-Path -LiteralPath (Join-Path $devFrontend "node_modules"))) {
    Write-Host ""
    Write-Host "First run (develop): npm install in frontend..." -ForegroundColor Yellow
    Set-Location $devFrontend
    npm install
}

if ($useMainSidecar) {
    $mainFe = Join-Path $WorktreePath "frontend"
    if (-not (Test-Path -LiteralPath (Join-Path $mainFe "node_modules"))) {
        Write-Host "First run (main worktree): npm install in frontend..." -ForegroundColor Yellow
        Push-Location $mainFe
        try { npm install } finally { Pop-Location }
    }
}

if ($useMainSidecar) {
    Write-Host ""
    Write-Host "Starting Vite in two new windows..." -ForegroundColor Cyan
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-NoProfile",
        "-Command",
        "npm run dev -- --port 5173 --strictPort"
    ) -WorkingDirectory $devFrontend

    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-NoProfile",
        "-Command",
        "npm run dev -- --port 5174 --strictPort"
    ) -WorkingDirectory $mainFe

    Write-Host ""
    Write-Host "Open in your browser:" -ForegroundColor Green
    Write-Host "  DEVELOP  →  http://localhost:5173  →  API http://127.0.0.1:$devPort" -ForegroundColor Green
    Write-Host "  MAIN     →  http://localhost:5174  →  API http://127.0.0.1:$mainPort" -ForegroundColor Green
    Write-Host ""
    Write-Host "Four PowerShell windows are running (2x API, 2x Vite). Close each window to stop that process." -ForegroundColor DarkGray
    Write-Host "Tip: without the main worktree + .env, only develop starts; run  .\scripts\setup-main-worktree.ps1  first." -ForegroundColor DarkGray
    exit 0
}

# --- Legacy: single develop UI in this window ---
Set-Location $devFrontend
Write-Host ""
Write-Host "Starting dashboard here (Vite). Open:" -ForegroundColor Cyan
Write-Host "  http://localhost:5173" -ForegroundColor Green
Write-Host ""
Write-Host "Press Ctrl+C in this window to stop the UI. Close the other window to stop the API." -ForegroundColor DarkGray
if (-not $SkipMainSidecar) {
    Write-Host "Tip: run  .\scripts\bootstrap-main-worktree.ps1  once, then  .\scripts\launch_local.ps1  again for dual UI (5173+5174)." -ForegroundColor DarkGray
}
Write-Host ""

npm run dev
