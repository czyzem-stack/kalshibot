# Create a sibling git worktree on branch `main` so you can run stable main alongside `develop`.
#
# Usage (from repo root, while on develop or any branch):
#   .\scripts\setup-main-worktree.ps1
#
# Default path: ..\Kalshibot-main (next to this repo folder). Override:
#   .\scripts\setup-main-worktree.ps1 -WorktreePath "D:\repos\Kalshibot-main"
#
# After setup: copy your secrets into the worktree `.env` (see ENV_SIDECAR.example written there),
# run `.\scripts\create_venv.ps1` once inside the worktree if you want an isolated venv, or reuse
# this repo's `.venv` when launching (see launch-main-sidecar.ps1).

param(
    [Parameter(Mandatory = $false)]
    [string]$WorktreePath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $WorktreePath) {
    $WorktreePath = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "..\Kalshibot-main"))
} else {
    $WorktreePath = [System.IO.Path]::GetFullPath($WorktreePath)
}

if (Test-Path -LiteralPath (Join-Path $WorktreePath ".git")) {
    Write-Host "Worktree already exists at:" -ForegroundColor Yellow
    Write-Host "  $WorktreePath" -ForegroundColor Gray
    Write-Host "To create .env files for dual UI:  .\scripts\bootstrap-main-worktree.ps1 -WorktreePath `"$WorktreePath`"" -ForegroundColor Cyan
    Write-Host "Remove later:  git worktree remove <path>   (from any checkout)" -ForegroundColor DarkGray
    exit 0
}

$parentDir = Split-Path -Parent $WorktreePath
if (-not (Test-Path -LiteralPath $parentDir)) {
    New-Item -ItemType Directory -Path $parentDir -Force | Out-Null
}

Write-Host "Adding worktree: main -> $WorktreePath" -ForegroundColor Cyan
git -C $RepoRoot worktree add $WorktreePath main

$exampleMain = @"
# --- Kalshibot MAIN sidecar (parallel to develop) ---
# Copy into .env in THIS worktree (merge with your Kalshi keys from develop if you want).
# Each checkout uses its own repo-root data/ (relative paths resolve there, not cwd).
#
# REQUIRED: different API port than develop (default 8765):
KALSHI_BOT_PORT=8770
#
# Recommended: keep these relative so this worktree never shares DB/JSONL with develop:
SQLITE_PATH=data/bot.sqlite3
DATA_LOG_DIR=data/logs
#
# If you use API bearer auth, use a different token OR the same token (both APIs must match frontend .env).
# CORS: add second Vite origin when running UI on 5174 (see frontend ENV example next to this file).
# CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174
"@

$exampleFe = @"
# Point this worktree's Vite dev server at the MAIN sidecar API port.
VITE_API_ORIGIN=http://127.0.0.1:8770
VITE_UI_TRACK=main
# VITE_API_BEARER_TOKEN=   # if you set KALSHI_API_BEARER_TOKEN in root .env for this worktree
"@

Set-Content -LiteralPath (Join-Path $WorktreePath "ENV_SIDECAR.example") -Value $exampleMain -Encoding UTF8
New-Item -ItemType Directory -Path (Join-Path $WorktreePath "frontend") -Force | Out-Null
Set-Content -LiteralPath (Join-Path $WorktreePath "frontend\ENV_SIDECAR.example") -Value $exampleFe -Encoding UTF8

Write-Host ""
Write-Host "Done. Next steps:" -ForegroundColor Green
Write-Host "  From develop repo (automates .env + frontend/.env):" -ForegroundColor Gray
Write-Host "    .\scripts\bootstrap-main-worktree.ps1 -WorktreePath `"$WorktreePath`"" -ForegroundColor Gray
Write-Host "  Or manually: copy .env / frontend/.env from develop and merge ENV_SIDECAR.example files." -ForegroundColor DarkGray
Write-Host "  Then:  .\scripts\launch_local.ps1   or   .\scripts\launch-main-sidecar.ps1 -WorktreePath `"$WorktreePath`"" -ForegroundColor Gray
Write-Host ""
Write-Host "Develop: keep using .\scripts\launch_local.ps1 (8765 + 5173). Main sidecar: 8770 + 5174." -ForegroundColor Cyan
