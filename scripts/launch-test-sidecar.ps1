# Run API + Vite for the `test` worktree (parallel to develop / main).
#
# Prereqs:
#   .\scripts\bootstrap-test-worktree.ps1   (or any sibling checkout Kalshibot-test / kalshibot-test with .env)
# Optional: $env:KALSHIBOT_TEST_WORKTREE = "D:\path\to\checkout"
#
# Usage (from DEVELOP repo root):
#   .\scripts\launch-test-sidecar.ps1
#   .\scripts\launch-test-sidecar.ps1 -WorktreePath "D:\repos\Kalshibot-test"

param(
    [string]$WorktreePath = ""
)

$ErrorActionPreference = "Stop"
$DevelopRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Get-LinkedTestWorktreePath([string]$Repo) {
    try {
        $wtLines = @(git -C $Repo worktree list 2>$null)
    } catch {
        return $null
    }
    if (-not $wtLines) { return $null }
    $repoCanon = [System.IO.Path]::GetFullPath($Repo)
    foreach ($wtLine in $wtLines) {
        if ($wtLine -notmatch '\s\[test\]\s*$') { continue }
        if ($wtLine -match '\s+([0-9a-f]{7,})\s+\[test\]\s*$') {
            $pathPart = $wtLine.Substring(0, $wtLine.Length - $matches[0].Length).Trim()
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
    $parent = Split-Path -Parent $RepoRoot
    foreach ($leaf in @("Kalshibot-test", "kalshibot-test")) {
        $cand = [System.IO.Path]::GetFullPath((Join-Path $parent $leaf))
        if ($cand -eq [System.IO.Path]::GetFullPath($RepoRoot)) { continue }
        if (Test-PathIsGitCheckout $cand) { return $cand }
    }
    return [System.IO.Path]::GetFullPath((Join-Path $parent "Kalshibot-test"))
}

if (-not $WorktreePath) {
    $WorktreePath = Resolve-TestWorktreeRoot $DevelopRoot ""
} else {
    $WorktreePath = [System.IO.Path]::GetFullPath($WorktreePath)
}

if (-not (Test-Path -LiteralPath (Join-Path $WorktreePath ".git"))) {
    Write-Error "Test worktree not found at: $WorktreePath`nRun:  git branch test develop`n      .\scripts\bootstrap-test-worktree.ps1"
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

$port = 8775
$envFile = Join-Path $WorktreePath ".env"
if (Test-Path -LiteralPath $envFile) {
    $m = Select-String -Path $envFile -Pattern '^\s*KALSHI_BOT_PORT\s*=\s*(\d+)\s*$' | Select-Object -First 1
    if ($null -ne $m -and $m.Matches.Count -gt 0) {
        $port = [int]$m.Matches[0].Groups[1].Value
    }
}

$runner = Join-Path $DevelopRoot "scripts\run_backend_at.ps1"

Write-Host "Starting TEST worktree API in new window (port $port)..." -ForegroundColor Cyan
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
    Write-Warning "API did not respond yet. Check the new window for errors."
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
Write-Host "Starting TEST dashboard (Vite) on http://localhost:5175 -> $healthUrl" -ForegroundColor Green
Write-Host "Develop: http://localhost:5174 -> http://127.0.0.1:8765" -ForegroundColor DarkGray
Write-Host "Press Ctrl+C here to stop Vite only; close the API window to stop uvicorn." -ForegroundColor DarkGray
Write-Host ""

npm run dev -- --port 5175 --strictPort
