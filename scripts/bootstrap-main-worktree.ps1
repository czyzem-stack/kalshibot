# One-shot: ensure a [main] git worktree exists next to develop (or at -WorktreePath), then write
# worktree .env + frontend/.env so .\scripts\launch_local.ps1 can start dual UI (5173 + 5174).
#
# - Calls setup-main-worktree.ps1 when the folder is not yet a worktree (git worktree add).
# - If the worktree has no .env: copies develop's .env (if present) else .env.example, then sets
#   KALSHI_BOT_PORT=8770, SQLITE_PATH, DATA_LOG_DIR, CORS_ORIGINS for sidecar + Vite 5174.
# - If .env already exists: only updates those keys (and VITE_API_ORIGIN + VITE_UI_TRACK in frontend/.env).
#
# Usage (from repo root):
#   .\scripts\bootstrap-main-worktree.ps1
#   .\scripts\bootstrap-main-worktree.ps1 -WorktreePath "D:\repos\Kalshibot-main"
#
# Then:  .\scripts\launch_local.ps1

param(
    [string]$WorktreePath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Get-LinkedMainWorktreePath([string]$Repo) {
    try {
        $wtLines = @(git -C $Repo worktree list 2>$null)
    } catch {
        return $null
    }
    if (-not $wtLines) { return $null }
    $repoCanon = [System.IO.Path]::GetFullPath($Repo)
    foreach ($wtLine in $wtLines) {
        if ($wtLine -notmatch '\s\[main\]\s*$') { continue }
        if ($wtLine -match '\s+([0-9a-f]{7,})\s+\[main\]\s*$') {
            $pathPart = $wtLine.Substring(0, $wtLine.Length - $matches[0].Length).Trim()
            if (-not $pathPart) { continue }
            $p = [System.IO.Path]::GetFullPath($pathPart)
            if ($p -ne $repoCanon) { return $p }
        }
    }
    return $null
}

function Assert-EnvFileIsSmallTextFile {
    param(
        [Parameter(Mandatory = $true)][string]$LiteralPath,
        [Parameter(Mandatory = $true)][string]$DisplayLabel
    )
    if (-not (Test-Path -LiteralPath $LiteralPath)) { return }
    $item = Get-Item -LiteralPath $LiteralPath -ErrorAction Stop
    if ($item.PSIsContainer) {
        Write-Error "Expected a file but found a directory: $LiteralPath ($DisplayLabel)."
        exit 1
    }
    $maxBytes = 1MB
    if ($item.Length -gt $maxBytes) {
        $mb = [math]::Round($item.Length / 1MB, 2)
        Write-Error (
            "File too large for bootstrap (${mb} MB; max 1 MB): $LiteralPath ($DisplayLabel).`n" +
            ".env files must be small text. Back up the file, delete or replace it (e.g. copy from develop frontend/.env), then re-run:`n" +
            "  .\scripts\bootstrap-main-worktree.ps1"
        )
        exit 1
    }
}

function Set-EnvKeyInFile {
    param(
        [Parameter(Mandatory = $true)][string]$TargetEnvFile,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string]$Value
    )
    Assert-EnvFileIsSmallTextFile -LiteralPath $TargetEnvFile -DisplayLabel "worktree frontend/.env"
    $utf8Read = New-Object System.Text.UTF8Encoding $false
    $envRows = [System.Collections.ArrayList]@([System.IO.File]::ReadAllLines($TargetEnvFile, $utf8Read))
    $re = "^\s*$([regex]::Escape($Key))\s*="
    $found = $false
    for ($i = 0; $i -lt $envRows.Count; $i++) {
        $envLine = [string]$envRows[$i]
        if ($envLine -match '^\s*#') { continue }
        if ([string]::IsNullOrWhiteSpace($envLine)) { continue }
        if ($envLine -match $re) {
            $envRows[$i] = "$Key=$Value"
            $found = $true
            break
        }
    }
    if (-not $found) {
        [void]$envRows.Add("$Key=$Value")
    }
    $utf8 = New-Object System.Text.UTF8Encoding $false
    $outArr = New-Object string[] $envRows.Count
    for ($j = 0; $j -lt $envRows.Count; $j++) {
        $outArr[$j] = [string]$envRows[$j]
    }
    [System.IO.File]::WriteAllLines($TargetEnvFile, $outArr, $utf8)
}

function Write-EnvSidecarExamples([string]$WtRoot) {
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
# Shown next to the app title so this window is not confused with develop (5173).
VITE_UI_TRACK=main
# VITE_API_BEARER_TOKEN=   # if you set KALSHI_API_BEARER_TOKEN in root .env for this worktree
"@
    Set-Content -LiteralPath (Join-Path $WtRoot "ENV_SIDECAR.example") -Value $exampleMain -Encoding utf8
    $fe = Join-Path $WtRoot "frontend"
    if (-not (Test-Path -LiteralPath $fe)) {
        New-Item -ItemType Directory -Path $fe -Force | Out-Null
    }
    Set-Content -LiteralPath (Join-Path $fe "ENV_SIDECAR.example") -Value $exampleFe -Encoding utf8
}

if (-not $WorktreePath) {
    $fromGit = Get-LinkedMainWorktreePath $RepoRoot
    if ($fromGit) {
        $WorktreePath = $fromGit
        Write-Host "[bootstrap] Using main worktree from git: $WorktreePath" -ForegroundColor DarkGray
    } else {
        $WorktreePath = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "..\Kalshibot-main"))
    }
} else {
    $WorktreePath = [System.IO.Path]::GetFullPath($WorktreePath)
}

$WorktreePath = [System.IO.Path]::GetFullPath([string]$WorktreePath.Trim())
if ([string]::IsNullOrWhiteSpace($WorktreePath)) {
    Write-Error "Resolved main worktree path is empty."
    exit 1
}

Write-Host ""
Write-Host "bootstrap-main-worktree -> $WorktreePath" -ForegroundColor Cyan

$setup = Join-Path $PSScriptRoot "setup-main-worktree.ps1"
& $setup -WorktreePath $WorktreePath

$wtGit = Join-Path $WorktreePath ".git"
if (-not (Test-Path -LiteralPath $wtGit)) {
    Write-Error "Worktree path is not a git checkout: $WorktreePath (setup-main-worktree.ps1 may have failed)."
    exit 1
}

Write-EnvSidecarExamples $WorktreePath

$scPaths = [ordered]@{
    RootDotEnv = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($WorktreePath, ".env"))
    FrontDir   = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($WorktreePath, "frontend"))
    FrontDotEnv = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($WorktreePath, "frontend", ".env"))
}
$devEnv = Join-Path $RepoRoot ".env"
$devEx = Join-Path $RepoRoot ".env.example"

if (-not (Test-Path -LiteralPath ($scPaths['RootDotEnv']))) {
    if (Test-Path -LiteralPath $devEnv) {
        Write-Host "Creating worktree .env from develop .env ..." -ForegroundColor Gray
        Copy-Item -LiteralPath $devEnv -Destination ($scPaths['RootDotEnv'])
    } elseif (Test-Path -LiteralPath $devEx) {
        Write-Host "Creating worktree .env from .env.example (develop has no .env yet) ..." -ForegroundColor Yellow
        Copy-Item -LiteralPath $devEx -Destination ($scPaths['RootDotEnv'])
    } else {
        Write-Error "No develop .env or .env.example at $RepoRoot - cannot create worktree .env."
        exit 1
    }
} else {
    Write-Host 'Worktree .env already exists; updating sidecar keys only ...' -ForegroundColor Gray
}

if (-not (Test-Path -LiteralPath ($scPaths['FrontDir']))) {
    New-Item -ItemType Directory -Path ($scPaths['FrontDir']) -Force | Out-Null
}

$cors = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174"
$rootDotEnvPath = [string]($scPaths['RootDotEnv'])
Assert-EnvFileIsSmallTextFile -LiteralPath $rootDotEnvPath -DisplayLabel "worktree .env"
$sidecarKeys = @("KALSHI_BOT_PORT", "SQLITE_PATH", "DATA_LOG_DIR", "CORS_ORIGINS")
$sidecarVals = @("8770", "data/bot.sqlite3", "data/logs", $cors)
$utf8ReadRoot = New-Object System.Text.UTF8Encoding $false
$rootRows = [System.Collections.ArrayList]@([System.IO.File]::ReadAllLines($rootDotEnvPath, $utf8ReadRoot))
for ($kidx = 0; $kidx -lt $sidecarKeys.Length; $kidx++) {
    $Key = $sidecarKeys[$kidx]
    $Value = [string]$sidecarVals[$kidx]
    $re = "^\s*$([regex]::Escape($Key))\s*="
    $found = $false
    for ($i = 0; $i -lt $rootRows.Count; $i++) {
        $envLine = [string]$rootRows[$i]
        if ($envLine -match '^\s*#') { continue }
        if ([string]::IsNullOrWhiteSpace($envLine)) { continue }
        if ($envLine -match $re) {
            $rootRows[$i] = "$Key=$Value"
            $found = $true
            break
        }
    }
    if (-not $found) {
        [void]$rootRows.Add("$Key=$Value")
    }
}
$utf8Root = New-Object System.Text.UTF8Encoding $false
$rootOut = New-Object string[] $rootRows.Count
for ($j = 0; $j -lt $rootRows.Count; $j++) {
    $rootOut[$j] = [string]$rootRows[$j]
}
[System.IO.File]::WriteAllLines($rootDotEnvPath, $rootOut, $utf8Root)

$devFeEnv = Join-Path $RepoRoot "frontend\.env"
$devFeEx = Join-Path $RepoRoot "frontend\.env.example"

if (-not (Test-Path -LiteralPath ($scPaths['FrontDotEnv']))) {
    if (Test-Path -LiteralPath $devFeEnv) {
        Write-Host "Creating worktree frontend/.env from develop frontend/.env ..." -ForegroundColor Gray
        Copy-Item -LiteralPath $devFeEnv -Destination ($scPaths['FrontDotEnv'])
    } elseif (Test-Path -LiteralPath $devFeEx) {
        Write-Host "Creating worktree frontend/.env from frontend/.env.example ..." -ForegroundColor Gray
        Copy-Item -LiteralPath $devFeEx -Destination ($scPaths['FrontDotEnv'])
    } else {
        Write-Host "WARNING: no develop frontend/.env or .env.example - creating minimal frontend/.env" -ForegroundColor Yellow
        $utf8 = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::WriteAllLines(($scPaths['FrontDotEnv']), @(""), $utf8)
    }
} else {
    Write-Host 'Worktree frontend/.env exists; updating VITE_API_ORIGIN + VITE_UI_TRACK ...' -ForegroundColor Gray
}

$frontDotEnvPath = [string]($scPaths['FrontDotEnv'])
Set-EnvKeyInFile -TargetEnvFile $frontDotEnvPath -Key "VITE_API_ORIGIN" -Value "http://127.0.0.1:8770"
Set-EnvKeyInFile -TargetEnvFile $frontDotEnvPath -Key "VITE_UI_TRACK" -Value "main"

Write-Host ""
Write-Host "Done. Main worktree is ready for dual launch." -ForegroundColor Green
Write-Host "  $($scPaths['RootDotEnv'])" -ForegroundColor Gray
Write-Host "  $($scPaths['FrontDotEnv'])" -ForegroundColor Gray
Write-Host ""
Write-Host "Next:  .\scripts\launch_local.ps1" -ForegroundColor Cyan
Write-Host "Optional: cd `"$WorktreePath`"; .\scripts\create_venv.ps1  (isolated venv for main)" -ForegroundColor DarkGray
Write-Host ""
