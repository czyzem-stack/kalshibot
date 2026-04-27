# Run API + Vite locally (Windows PowerShell).
#
# Default: starts **develop** (this repo) — API :8765 + UI http://localhost:5174
#
# Local Vite convention: **main = :5173**, **develop = :5174**, **test = :5175** (CORS in bootstrap scripts list all three).
#
# Optional **main** worktree: sibling ..\Kalshibot-main (or `git worktree list` → [main]) with its own `.env`
#   → API :8770 + UI http://localhost:5173
#
# Optional **test** worktree: sibling ..\Kalshibot-test (or `git worktree list` → [test]) with its own `.env`
#   → API :8775 + UI http://localhost:5175 — **separate SQLite** under that checkout (see bootstrap scripts).
#
# Git flow (suggested): work on **test** → merge to **develop** → merge to **main**; run all three stacks together for comparison.
#
# Usage (from develop repo root):
#   .\scripts\launch_local.ps1
#
# This script **auto-wires** missing sidecar ``.env`` files by calling ``bootstrap-main-worktree.ps1`` /
# ``bootstrap-test-worktree.ps1`` when the checkout exists (``.git``) but ``.env`` is absent. If the conventional
# sibling ``..\Kalshibot-test`` does not exist yet, it runs ``setup-test-worktree.ps1`` (creates branch ``test`` + worktree)
# unless you set ``KALSHIBOT_TEST_WORKTREE`` to a custom path (then only bootstrap runs when .env is missing).
#
#   .\scripts\launch_local.ps1 -SkipMainSidecar          # develop + test only (if test worktree exists)
#   .\scripts\launch_local.ps1 -SkipTestSidecar        # develop + main only (legacy dual)
#   .\scripts\launch_local.ps1 -SkipMainSidecar -SkipTestSidecar   # single develop stack (API new window + Vite here)
#   .\scripts\launch_local.ps1 -WorktreePath "D:\repos\Kalshibot-main" -TestWorktreePath "D:\repos\Kalshibot-test"
#
# First time only:  .\scripts\create_venv.ps1
# Override test folder:   $env:KALSHIBOT_TEST_WORKTREE = "D:\path\to\checkout"

param(
    [switch]$SkipMainSidecar,
    [switch]$SkipTestSidecar,
    [string]$WorktreePath = "",
    [string]$TestWorktreePath = ""
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

function Get-LinkedTestWorktreePath([string]$Repo) {
    try {
        $lines = @(git -C $Repo worktree list 2>$null)
    } catch {
        return $null
    }
    if (-not $lines) { return $null }
    $repoCanon = [System.IO.Path]::GetFullPath($Repo)
    foreach ($line in $lines) {
        if ($line -notmatch '\s\[test\]\s*$') { continue }
        if ($line -match '\s+([0-9a-f]{7,})\s+\[test\]\s*$') {
            $pathPart = $line.Substring(0, $line.Length - $matches[0].Length).TrimEnd()
            if (-not $pathPart) { continue }
            $p = [System.IO.Path]::GetFullPath($pathPart)
            if ($p -ne $repoCanon) { return $p }
        }
    }
    return $null
}

function Test-PathIsGitCheckout([string]$Dir) {
    if ([string]::IsNullOrWhiteSpace($Dir)) { return $false }
    return Test-Path -LiteralPath (Join-Path $Dir ".git")
}

# Prefer KALSHIBOT_TEST_WORKTREE env, then -TestWorktreePath, then git [test] worktree, then sibling Kalshibot-test / kalshibot-test if .git exists (any branch).
function Resolve-TestWorktreeRoot([string]$RepoRoot, [string]$ExplicitFromParam) {
    $envOverride = $env:KALSHIBOT_TEST_WORKTREE
    if (-not [string]::IsNullOrWhiteSpace($envOverride)) {
        return [System.IO.Path]::GetFullPath($envOverride.Trim())
    }
    if (-not [string]::IsNullOrWhiteSpace($ExplicitFromParam)) {
        return [System.IO.Path]::GetFullPath($ExplicitFromParam.Trim())
    }
    $fromGit = Get-LinkedTestWorktreePath $RepoRoot
    if ($fromGit) { return $fromGit }
    $repoCanon = [System.IO.Path]::GetFullPath($RepoRoot)
    $parent = Split-Path -Parent $RepoRoot
    foreach ($leaf in @("Kalshibot-test", "kalshibot-test")) {
        $cand = [System.IO.Path]::GetFullPath((Join-Path $parent $leaf))
        if ($cand -eq $repoCanon) { continue }
        if (Test-PathIsGitCheckout $cand) { return $cand }
    }
    return [System.IO.Path]::GetFullPath((Join-Path $parent "Kalshibot-test"))
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

if (-not $TestWorktreePath) {
    $resolved = Resolve-TestWorktreeRoot $RepoRoot ""
    $TestWorktreePath = $resolved
    $viaGit = Get-LinkedTestWorktreePath $RepoRoot
    $envMark = if ([string]::IsNullOrWhiteSpace($env:KALSHIBOT_TEST_WORKTREE)) { "" } else { " (KALSHIBOT_TEST_WORKTREE)" }
    if ($viaGit -and ($resolved -eq $viaGit)) {
        Write-Host "[launch_local] Test checkout from git worktree list [test]: $TestWorktreePath$envMark" -ForegroundColor DarkGray
    } elseif (Test-PathIsGitCheckout $resolved) {
        Write-Host "[launch_local] Test checkout folder (sibling or env): $TestWorktreePath$envMark" -ForegroundColor DarkGray
    } else {
        Write-Host "[launch_local] Test sidecar default path (no checkout yet): $TestWorktreePath" -ForegroundColor DarkGray
    }
} else {
    $TestWorktreePath = [System.IO.Path]::GetFullPath($TestWorktreePath)
}

$wtGit = Join-Path $WorktreePath ".git"
$wtEnv = Join-Path $WorktreePath ".env"
$ttGit = Join-Path $TestWorktreePath ".git"
$ttEnv = Join-Path $TestWorktreePath ".env"

function Test-IsConventionalSiblingTestPath([string]$RepoRoot, [string]$TestPath) {
    $p = Split-Path -Parent $RepoRoot
    $a = [System.IO.Path]::GetFullPath((Join-Path $p "Kalshibot-test"))
    $b = [System.IO.Path]::GetFullPath((Join-Path $p "kalshibot-test"))
    $c = [System.IO.Path]::GetFullPath($TestPath)
    return (
        [string]::Equals($c, $a, [StringComparison]::OrdinalIgnoreCase) -or
        [string]::Equals($c, $b, [StringComparison]::OrdinalIgnoreCase)
    )
}

$bootstrapMain = Join-Path $PSScriptRoot "bootstrap-main-worktree.ps1"
$bootstrapTest = Join-Path $PSScriptRoot "bootstrap-test-worktree.ps1"
$setupTest = Join-Path $PSScriptRoot "setup-test-worktree.ps1"

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

if (-not $SkipTestSidecar) {
    $testFromEnv = -not [string]::IsNullOrWhiteSpace($env:KALSHIBOT_TEST_WORKTREE)
    $testLinked = Get-LinkedTestWorktreePath $RepoRoot
    $conventionalTest = Test-IsConventionalSiblingTestPath $RepoRoot $TestWorktreePath
    $mayAutoAddWorktree = $conventionalTest -and (-not $testFromEnv) -and ($null -eq $testLinked)

    if (-not (Test-Path -LiteralPath $ttGit) -and $mayAutoAddWorktree -and (Test-Path -LiteralPath $setupTest)) {
        Write-Host ""
        Write-Host "[launch_local] No test checkout at $TestWorktreePath - running setup-test-worktree.ps1 ..." -ForegroundColor Cyan
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            git -C $RepoRoot branch test develop 2>$null | Out-Null
            & $setupTest -WorktreePath $TestWorktreePath
        } catch {
            Write-Warning "setup-test-worktree.ps1: $_"
        }
        $ErrorActionPreference = $prevEap
    }

    if ((Test-Path -LiteralPath $ttGit) -and -not (Test-Path -LiteralPath $ttEnv) -and (Test-Path -LiteralPath $bootstrapTest)) {
        Write-Host ""
        Write-Host "[launch_local] Test checkout missing .env - running bootstrap-test-worktree.ps1 ..." -ForegroundColor Cyan
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & $bootstrapTest -WorktreePath $TestWorktreePath
        } catch {
            Write-Warning "bootstrap-test-worktree.ps1: $_"
        }
        $ErrorActionPreference = $prevEap
    }
}

$hasGit = Test-Path -LiteralPath $wtGit
$hasEnv = Test-Path -LiteralPath $wtEnv
$tHasGit = Test-Path -LiteralPath $ttGit
$tHasEnv = Test-Path -LiteralPath $ttEnv

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

$useTestSidecar = $false
if (-not $SkipTestSidecar) {
    if ($tHasGit -and $tHasEnv) {
        $useTestSidecar = $true
    } elseif (-not $tHasGit -and -not $tHasEnv) {
        Write-Host ""
        Write-Host "[launch_local] Test sidecar: OFF - no test checkout at:" -ForegroundColor Yellow
        Write-Host "           $TestWorktreePath" -ForegroundColor DarkGray
        Write-Host "           (Conventional ``..\Kalshibot-test`` is created automatically when possible; otherwise run setup-test-worktree.ps1.)" -ForegroundColor Yellow
    } elseif ($tHasGit -and -not $tHasEnv) {
        Write-Host ""
        Write-Host "[launch_local] Test sidecar: OFF - still no .env after auto-bootstrap; fix errors above or run:" -ForegroundColor Yellow
        Write-Host "           .\scripts\bootstrap-test-worktree.ps1" -ForegroundColor DarkGray
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

$testPort = 8775
if ($useTestSidecar) {
    $tEnvFile = Join-Path $TestWorktreePath ".env"
    $tm = Select-String -Path $tEnvFile -Pattern '^\s*KALSHI_BOT_PORT\s*=\s*(\d+)\s*$' | Select-Object -First 1
    if ($null -ne $tm -and $tm.Matches.Count -gt 0) {
        $testPort = [int]$tm.Matches[0].Groups[1].Value
    }
    if ($testPort -eq $devPort) {
        Write-Warning "Test worktree KALSHI_BOT_PORT ($testPort) matches develop ($devPort). Skipping test sidecar."
        $useTestSidecar = $false
    } elseif ($useMainSidecar -and $testPort -eq $mainPort) {
        Write-Warning "Test worktree KALSHI_BOT_PORT ($testPort) matches main ($mainPort). Skipping test sidecar."
        $useTestSidecar = $false
    }
}

$devEnvPath = Join-Path $RepoRoot ".env"
$pathsForSql = @(
    @{ Label = "develop"; Path = $devEnvPath }
)
if ($useMainSidecar) {
    $pathsForSql += @{ Label = "main"; Path = (Join-Path $WorktreePath ".env") }
}
if ($useTestSidecar) {
    $pathsForSql += @{ Label = "test"; Path = (Join-Path $TestWorktreePath ".env") }
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

$PyTest = $Py
$PyTestWt = Join-Path $TestWorktreePath ".venv\Scripts\python.exe"
if ($useTestSidecar -and (Test-Path -LiteralPath $PyTestWt)) {
    $PyTest = $PyTestWt
}

if ($useTestSidecar) {
    Write-Host ""
    Write-Host "Starting TEST worktree API in a new window..." -ForegroundColor Cyan
    Write-Host "  http://127.0.0.1:$testPort  (worktree: $TestWorktreePath)" -ForegroundColor DarkGray
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-File", $runnerAt,
        "-RepoRoot", $TestWorktreePath,
        "-PythonExe", $PyTest,
        "-Port", "$testPort"
    ) -WorkingDirectory $TestWorktreePath
}

if (-not (Wait-Health "http://127.0.0.1:$devPort/api/health" "develop API")) {
    Write-Warning "Develop API did not respond on port $devPort. Check the backend window for errors."
}

if ($useMainSidecar) {
    if (-not (Wait-Health "http://127.0.0.1:$mainPort/api/health" "main worktree API")) {
        Write-Warning "Main worktree API did not respond on port $mainPort. Check that worktree `.env` and `frontend/.env` match this port."
    }
}

if ($useTestSidecar) {
    if (-not (Wait-Health "http://127.0.0.1:$testPort/api/health" "test worktree API")) {
        Write-Warning "Test worktree API did not respond on port $testPort. Check that worktree `.env` and `frontend/.env` match this port."
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

if ($useTestSidecar) {
    $testFe = Join-Path $TestWorktreePath "frontend"
    if (-not (Test-Path -LiteralPath (Join-Path $testFe "node_modules"))) {
        Write-Host "First run (test worktree): npm install in frontend..." -ForegroundColor Yellow
        Push-Location $testFe
        try { npm install } finally { Pop-Location }
    }
}

$multiLocal = $useMainSidecar -or $useTestSidecar
if ($multiLocal) {
    Write-Host ""
    Write-Host "Starting Vite in new window(s)..." -ForegroundColor Cyan
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-NoProfile",
        "-Command",
        "npm run dev -- --port 5174 --strictPort"
    ) -WorkingDirectory $devFrontend

    if ($useMainSidecar) {
        $mainFe = Join-Path $WorktreePath "frontend"
        Start-Process -FilePath "powershell.exe" -ArgumentList @(
            "-NoExit",
            "-ExecutionPolicy", "Bypass",
            "-NoProfile",
            "-Command",
            "npm run dev -- --port 5173 --strictPort"
        ) -WorkingDirectory $mainFe
    }

    if ($useTestSidecar) {
        $testFe = Join-Path $TestWorktreePath "frontend"
        Start-Process -FilePath "powershell.exe" -ArgumentList @(
            "-NoExit",
            "-ExecutionPolicy", "Bypass",
            "-NoProfile",
            "-Command",
            "npm run dev -- --port 5175 --strictPort"
        ) -WorkingDirectory $testFe
    }

    Write-Host ""
    Write-Host "Open in your browser:" -ForegroundColor Green
    Write-Host "  DEVELOP  ->  http://localhost:5174  ->  API http://127.0.0.1:$devPort" -ForegroundColor Green
    if ($useMainSidecar) {
        Write-Host "  MAIN     ->  http://localhost:5173  ->  API http://127.0.0.1:$mainPort" -ForegroundColor Green
    } else {
        Write-Host "  MAIN     ->  (not started) 5173 only when main sidecar is ON" -ForegroundColor DarkGray
    }
    if ($useTestSidecar) {
        Write-Host "  TEST     ->  http://localhost:5175  ->  API http://127.0.0.1:$testPort" -ForegroundColor Green
        Write-Host "           Look for a separate PowerShell window running Vite on :5175 (third UI)." -ForegroundColor DarkGray
    } else {
        Write-Host "  TEST     ->  (not started) http://localhost:5175 is ONLY used when the test worktree is enabled" -ForegroundColor Yellow
        if ($SkipTestSidecar) {
            Write-Host "           Reason: you passed -SkipTestSidecar" -ForegroundColor DarkGray
        } elseif (-not $tHasGit) {
            Write-Host "           Reason: no git checkout at: $TestWorktreePath" -ForegroundColor DarkGray
        } elseif (-not $tHasEnv) {
            Write-Host "           Reason: missing .env - create with:  .\scripts\bootstrap-test-worktree.ps1" -ForegroundColor DarkGray
        } else {
            Write-Host "           Reason: test KALSHI_BOT_PORT matched develop/main, or test API health check failed (see warnings above)" -ForegroundColor DarkGray
        }
    }
    $nApi = 1 + $(if ($useMainSidecar) { 1 } else { 0 }) + $(if ($useTestSidecar) { 1 } else { 0 })
    $nFe = $nApi
    Write-Host ""
    Write-Host "$nApi API window(s) + $nFe Vite window(s) running. Close each window to stop that process." -ForegroundColor DarkGray
    Write-Host "Tip: 5175 (test) needs ..\Kalshibot-test (or KALSHIBOT_TEST_WORKTREE) with .git + .env. Re-run bootstrap-main-worktree.ps1 so main CORS includes :5175 and :5174 (develop)." -ForegroundColor DarkGray
    exit 0
}

# --- Legacy: single develop UI in this window ---
Set-Location $devFrontend
Write-Host ""
Write-Host "Starting dashboard here (Vite). Open:" -ForegroundColor Cyan
Write-Host "  http://localhost:5174" -ForegroundColor Green
Write-Host ""
Write-Host "Press Ctrl+C in this window to stop the UI. Close the other window to stop the API." -ForegroundColor DarkGray
Write-Host "Tip: run bootstrap-main-worktree.ps1 and/or bootstrap-test-worktree.ps1, then launch again for 5173 (main) and/or 5175 (test)." -ForegroundColor DarkGray
Write-Host ""

npm run dev
