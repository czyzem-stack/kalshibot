# Run uvicorn from an arbitrary repo root (used by launch-main-sidecar.ps1 for a git worktree).
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,
    [Parameter(Mandatory = $true)]
    [string]$PythonExe,
    [Parameter(Mandatory = $true)]
    [int]$Port
)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $RepoRoot
Write-Host "uvicorn backend.app.main:app @ $RepoRoot port $Port" -ForegroundColor Cyan
& $PythonExe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port $Port
