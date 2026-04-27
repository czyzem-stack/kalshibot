# Run API + Vite locally (Windows PowerShell).
#
# Default: starts **develop** (this repo) — API :8765 + UI http://localhost:5174
#
# Local Vite: **main = :5173**, **develop = :5174** (see `bootstrap-main-worktree.ps1` for CORS).
#
# Optional **main** worktree: sibling ..\Kalshibot-main (or `git worktree list` → [main]) with its own `.env`
#   → API :8770 + UI http://localhost:5173
#
# Git flow (suggested): **develop** → **main** (PRs or local merges as you prefer).
#
# Usage (from develop repo root):
#   .\scripts\launch_local.ps1
#
# Auto-wires a missing main sidecar **.env** by running **bootstrap-main-worktree.ps1** when that checkout
# has **.git** but no **.env**.
#
#   .\scripts\launch_local.ps1 -SkipMainSidecar   # only develop: API in one new window, Vite in *this* terminal
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

$wtGit = Join-Path $WorktreePath ".git"
$wtEnv = Join-Path $WorktreePath ".env"

$bootstrapMain = Join-Path $PSScriptRoot "bootstrap-main-worktree.ps1"

if (-not $SkipMainSidecar -and (Test-Path -LiteralPath $wtGit) -and -not (Test-Path -LiteralPath $wtEnv) -and (Test-Path -LiteralPath $bootstrapMain)) {
    Write-Host ""
    Write-Host "[launch_local] Main worktree missing .env - running bootstrap-main-worktree.ps1 ..." -ForegroundColor Cyan
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $bootstrapMain -WorktreePath $WorktreePath
    } catch {
        Write-Warning "bootstrap-main-worktree.ps1: $_"
    }
    $ErrorActionPreference = $prevEap
}

$hasGit = Test-Path -LiteralPath $wtGit
$hasEnv = Test-Path -LiteralPath $wtEnv

$useMainSidecar = $false
if (-not $SkipMainSidecar) {
    if ($hasGit -and $hasEnv) {
        $useMainSidecar = $true
    } elseif (-not $hasGit -and -not $hasEnv) {
        Write-Host ""
        Write-Host "[launch_local] Main sidecar: OFF - no main checkout at:" -ForegroundColor Yellow
        Write-Host "           $WorktreePath" -ForegroundColor DarkGray
        Write-Host "           Run:  .\scripts\setup-main-worktree.ps1  (then re-run launch_local.ps1)" -ForegroundColor Yellow
    } elseif ($hasGit -and -not $hasEnv) {
        Write-Host ""
        Write-Host "[launch_local] Main sidecar: OFF - still no .env after auto-bootstrap; fix errors above or run:" -ForegroundColor Yellow
        Write-Host "           .\scripts\bootstrap-main-worktree.ps1" -ForegroundColor DarkGray
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
        Write-Warning "Main worktree KALSHI_BOT_PORT ($mainPort) matches develop ($devPort). Skipping main sidecar."
        $useMainSidecar = $false
    }
}

$devEnvPath = Join-Path $RepoRoot ".env"
$pathsForSql = @(
    @{ Label = "develop"; Path = $devEnvPath }
)
if ($useMainSidecar) {
    $pathsForSql += @{ Label = "main"; Path = (Join-Path $WorktreePath ".env") }
}
$sqlByLabel = @{}
foreach ($entry in $pathsForSql) {
    $p = $entry.Path
    if (-not (Test-Path -LiteralPath $p)) { continue }
    $md = Select-String -LiteralPath $p -Pattern '^\s*SQLITE_PATH\s*=\s*(.+)\s*$' | Select-Object -First 1
    if ($null -ne $md -and $md.Matches.Count -gt 0) {
        $sqlByLabel[$entry.Label] = $md.Matches[0].Groups[1].Value.Trim().Trim('"').Trim("'")
    }
}
$sqlPaths = @($sqlByLabel.Values | Where-Object { $_ })
if ($sqlPaths.Count -gt 0 -and (($sqlPaths | Select-Object -Unique).Count -lt $sqlPaths.Count)) {
    $dup = ($sqlByLabel.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join "; "
    Write-Warning "Two or more stacks share the same SQLITE_PATH ($dup). Use separate checkouts or distinct paths."
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
        Write-Warning "Main worktree API did not respond on port $mainPort. Check that worktree `.env` and `frontend/.env` match this port."
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

# When main sidecar is on, only the **main** Vite needs a second terminal; develop Vite runs here so
# you keep one home window (this one) on :5174.
if ($useMainSidecar) {
    $mainFe = Join-Path $WorktreePath "frontend"
    Write-Host ""
    Write-Host "Starting MAIN Vite in a new window (port 5173)..." -ForegroundColor Cyan
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-NoProfile",
        "-Command",
        "npm run dev -- --port 5173 --strictPort"
    ) -WorkingDirectory $mainFe

    Write-Host ""
    Write-Host "Open in your browser:" -ForegroundColor Green
    Write-Host "  DEVELOP  ->  http://localhost:5174  (Vite in this terminal)  ->  API http://127.0.0.1:$devPort" -ForegroundColor Green
    Write-Host "  MAIN     ->  http://localhost:5173  (Vite in the other window)  ->  API http://127.0.0.1:$mainPort" -ForegroundColor Green
    Write-Host ""
    Write-Host "This terminal: develop Vite. Close the main-Vite window to stop that UI. Ctrl+C here stops develop Vite; close API windows for backends." -ForegroundColor DarkGray
    Write-Host "Tip: re-run bootstrap-main-worktree.ps1 if this repo’s CORS must allow both :5173 and :5174." -ForegroundColor DarkGray
}

# --- develop Vite in *this* window (always) ---
Set-Location $devFrontend
Write-Host ""
if ($useMainSidecar) {
    Write-Host "Starting DEVELOP Vite in this window - http://localhost:5174" -ForegroundColor Cyan
    Write-Host ""
} else {
    Write-Host "Starting dashboard here (Vite). Open:" -ForegroundColor Cyan
    Write-Host "  http://localhost:5174" -ForegroundColor Green
    Write-Host ""
    Write-Host "Press Ctrl+C in this window to stop the UI. Close the other window to stop the API." -ForegroundColor DarkGray
    Write-Host "Tip: run bootstrap-main-worktree.ps1, then launch again to also start main on 5173." -ForegroundColor DarkGray
    Write-Host ""
}

npm run dev
