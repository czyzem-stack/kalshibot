# Create a sibling git worktree on branch `test` so you can run a third stack alongside `develop` and `main`.
#
# Prereq: branch `test` must exist (create once from develop):
#   git branch test develop
#   .\scripts\setup-test-worktree.ps1
#
# Default path: ..\Kalshibot-test (next to this repo). Override:
#   .\scripts\setup-test-worktree.ps1 -WorktreePath "D:\repos\Kalshibot-test"
#
# After setup:  .\scripts\bootstrap-test-worktree.ps1
# Then:         .\scripts\launch_local.ps1   (starts develop + optional main + optional test)

param(
    [Parameter(Mandatory = $false)]
    [string]$WorktreePath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $WorktreePath) {
    $WorktreePath = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "..\Kalshibot-test"))
} else {
    $WorktreePath = [System.IO.Path]::GetFullPath($WorktreePath)
}

if (Test-Path -LiteralPath (Join-Path $WorktreePath ".git")) {
    Write-Host "Worktree already exists at:" -ForegroundColor Yellow
    Write-Host "  $WorktreePath" -ForegroundColor Gray
    Write-Host "Bootstrap env:  .\scripts\bootstrap-test-worktree.ps1 -WorktreePath `"$WorktreePath`"" -ForegroundColor Cyan
    exit 0
}

$parentDir = Split-Path -Parent $WorktreePath
if (-not (Test-Path -LiteralPath $parentDir)) {
    New-Item -ItemType Directory -Path $parentDir -Force | Out-Null
}

Write-Host "Adding worktree: test -> $WorktreePath" -ForegroundColor Cyan
git -C $RepoRoot worktree add $WorktreePath test
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "If git said branch 'test' is missing, create it from develop first:" -ForegroundColor Yellow
    Write-Host "  git branch test develop" -ForegroundColor Gray
    Write-Host "  .\scripts\setup-test-worktree.ps1" -ForegroundColor Gray
    exit $LASTEXITCODE
}

$exampleTest = @"
# --- Kalshibot TEST worktree (parallel to develop + main) ---
# Copy into .env in THIS worktree. This checkout has its own repo-root data/ (separate SQLite from develop/main).
#
# REQUIRED: API port distinct from develop (8765) and main (8770):
KALSHI_BOT_PORT=8775
#
# Recommended: relative paths stay inside this worktree only:
SQLITE_PATH=data/bot.sqlite3
DATA_LOG_DIR=data/logs
#
# CORS: launch_local.ps1 / bootstrap scripts add Vite 5173 (main), 5174 (develop), 5175 (test) for triple-local.
"@

$exampleFe = @"
# Point this worktree's Vite dev server at the TEST API port.
VITE_API_ORIGIN=http://127.0.0.1:8775
VITE_UI_TRACK=test
"@

Set-Content -LiteralPath (Join-Path $WorktreePath "ENV_SIDECAR.example") -Value $exampleTest -Encoding UTF8
New-Item -ItemType Directory -Path (Join-Path $WorktreePath "frontend") -Force | Out-Null
Set-Content -LiteralPath (Join-Path $WorktreePath "frontend\ENV_SIDECAR.example") -Value $exampleFe -Encoding UTF8

Write-Host ""
Write-Host "Done. Next:" -ForegroundColor Green
Write-Host "  .\scripts\bootstrap-test-worktree.ps1 -WorktreePath `"$WorktreePath`"" -ForegroundColor Gray
Write-Host "  .\scripts\launch_local.ps1" -ForegroundColor Gray
Write-Host ""
Write-Host "Ports: develop 8765+5174, main 8770+5173, test 8775+5175. Git flow: test -> develop -> main (merge/PR as you prefer)." -ForegroundColor Cyan
