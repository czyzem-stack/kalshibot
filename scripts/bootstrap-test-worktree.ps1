# One-shot: ensure a [test] git worktree exists, then write worktree .env + frontend/.env for the TEST sidecar (8775 + 5175).
#
# Usage (from develop repo root):
#   git branch test develop   # once, if branch test does not exist
#   .\scripts\bootstrap-test-worktree.ps1
#   .\scripts\launch_local.ps1
#
# - Calls setup-test-worktree.ps1 when the folder is not yet a worktree.
# - Sets KALSHI_BOT_PORT=8775, SQLITE_PATH, DATA_LOG_DIR, CORS (main+develop+test: 5173+5174+5175), VITE_API_ORIGIN, VITE_UI_TRACK=test.

param(
    [string]$WorktreePath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

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
        Write-Error "File too large for bootstrap (${mb} MB; max 1 MB): $LiteralPath ($DisplayLabel)."
        exit 1
    }
}

function Write-EnvSidecarExamples([string]$WtRoot) {
    $exampleTest = @"
# --- Kalshibot TEST worktree ---
KALSHI_BOT_PORT=8775
SQLITE_PATH=data/bot.sqlite3
DATA_LOG_DIR=data/logs
"@
    $exampleFe = @"
VITE_API_ORIGIN=http://127.0.0.1:8775
VITE_UI_TRACK=test
"@
    Set-Content -LiteralPath (Join-Path $WtRoot "ENV_SIDECAR.example") -Value $exampleTest -Encoding utf8
    $fe = Join-Path $WtRoot "frontend"
    if (-not (Test-Path -LiteralPath $fe)) {
        New-Item -ItemType Directory -Path $fe -Force | Out-Null
    }
    Set-Content -LiteralPath (Join-Path $fe "ENV_SIDECAR.example") -Value $exampleFe -Encoding utf8
}

if (-not $WorktreePath) {
    $fromGit = Get-LinkedTestWorktreePath $RepoRoot
    if ($fromGit) {
        $WorktreePath = $fromGit
        Write-Host "[bootstrap-test] Using test worktree from git: $WorktreePath" -ForegroundColor DarkGray
    } else {
        $WorktreePath = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "..\Kalshibot-test"))
    }
} else {
    $WorktreePath = [System.IO.Path]::GetFullPath($WorktreePath)
}

$WorktreePath = [System.IO.Path]::GetFullPath([string]$WorktreePath.Trim())
if ([string]::IsNullOrWhiteSpace($WorktreePath)) {
    Write-Error "Resolved test worktree path is empty."
    exit 1
}

Write-Host ""
Write-Host "bootstrap-test-worktree -> $WorktreePath" -ForegroundColor Cyan

$setup = Join-Path $PSScriptRoot "setup-test-worktree.ps1"
& $setup -WorktreePath $WorktreePath

$wtGit = Join-Path $WorktreePath ".git"
if (-not (Test-Path -LiteralPath $wtGit)) {
    Write-Error "Worktree path is not a git checkout: $WorktreePath"
    exit 1
}

Write-EnvSidecarExamples $WorktreePath

$scPaths = [ordered]@{
    RootDotEnv  = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($WorktreePath, ".env"))
    FrontDir    = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($WorktreePath, "frontend"))
    FrontDotEnv = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($WorktreePath, "frontend", ".env"))
}
$devEnv = Join-Path $RepoRoot ".env"
$devEx = Join-Path $RepoRoot ".env.example"

if (-not (Test-Path -LiteralPath ($scPaths['RootDotEnv']))) {
    if (Test-Path -LiteralPath $devEnv) {
        Write-Host "Creating worktree .env from develop .env ..." -ForegroundColor Gray
        Copy-Item -LiteralPath $devEnv -Destination ($scPaths['RootDotEnv'])
    } elseif (Test-Path -LiteralPath $devEx) {
        Write-Host "Creating worktree .env from .env.example ..." -ForegroundColor Yellow
        Copy-Item -LiteralPath $devEx -Destination ($scPaths['RootDotEnv'])
    } else {
        Write-Error "No develop .env or .env.example at $RepoRoot"
        exit 1
    }
} else {
    Write-Host 'Worktree .env already exists; updating sidecar keys only ...' -ForegroundColor Gray
}

if (-not (Test-Path -LiteralPath ($scPaths['FrontDir']))) {
    New-Item -ItemType Directory -Path ($scPaths['FrontDir']) -Force | Out-Null
}

$cors = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:5175,http://127.0.0.1:5175"
$rootDotEnvPath = [string]($scPaths['RootDotEnv'])
Assert-EnvFileIsSmallTextFile -LiteralPath $rootDotEnvPath -DisplayLabel "worktree .env"
$sidecarKeys = @("KALSHI_BOT_PORT", "SQLITE_PATH", "DATA_LOG_DIR", "CORS_ORIGINS")
$sidecarVals = @("8775", "data/bot.sqlite3", "data/logs", $cors)
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

if (-not (Test-Path -LiteralPath ($scPaths['FrontDotEnv']))) {
    if (Test-Path -LiteralPath $devFeEnv) {
        Copy-Item -LiteralPath $devFeEnv -Destination ($scPaths['FrontDotEnv'])
    } elseif (Test-Path -LiteralPath $devFeEx) {
        Copy-Item -LiteralPath $devFeEx -Destination ($scPaths['FrontDotEnv'])
    } else {
        $utf8 = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::WriteAllLines(($scPaths['FrontDotEnv']), @(""), $utf8)
    }
} else {
    Write-Host 'Worktree frontend/.env exists; updating VITE_API_ORIGIN + VITE_UI_TRACK ...' -ForegroundColor Gray
}

$frontDotEnvPath = [string]($scPaths['FrontDotEnv'])
Set-EnvKeyInFile -TargetEnvFile $frontDotEnvPath -Key "VITE_API_ORIGIN" -Value "http://127.0.0.1:8775"
Set-EnvKeyInFile -TargetEnvFile $frontDotEnvPath -Key "VITE_UI_TRACK" -Value "test"

Write-Host ""
Write-Host "Done. TEST worktree is ready (8775 + 5175, own data/bot.sqlite3 under that folder)." -ForegroundColor Green
Write-Host "Next:  .\scripts\launch_local.ps1" -ForegroundColor Cyan
Write-Host "Re-bootstrap main after this if you need CORS on main to include 5175:  .\scripts\bootstrap-main-worktree.ps1" -ForegroundColor DarkGray
Write-Host ""
