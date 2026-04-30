# Run from the DEVELOP repo root (API :8765 + Vite :5174).
#
# Enforces the same rule as bootstrap-main-worktree.ps1: **this checkout always uses its own SQLite file**
# inside THIS repo's data/ folder — never shared with the main worktree unless you paste one absolute path everywhere.
#
# Writes / updates (merge into root .env):
#   KALSHIBOT_DATA_PROFILE=develop
#   SQLITE_PATH=data/bot-develop.sqlite3
#   DATA_LOG_DIR=data/logs-develop
#
# Why trading data can look "wiped": SQLite never moves rows when you change SQLITE_PATH — the API simply opens
# a different file (often empty). This script copies legacy data/bot.sqlite3 -> data/bot-develop.sqlite3 **only when**
# bot-develop.sqlite3 does not exist yet. If you already started the API once with SQLITE_PATH=bot-develop, an empty
# file may exist and this script will NOT overwrite it — stop the API, delete or rename bot-develop.sqlite3, then re-run.
#
# Usage:
#   .\scripts\bootstrap-develop-env.ps1
#
# Deprecated (no-op): -UseSeparateSqliteFiles — behavior is always "separate sqlite for develop track".

param(
    [string]$RepoRoot = "",
    [switch]$UseSeparateSqliteFiles
)

$ErrorActionPreference = "Stop"
if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)
}

if ($UseSeparateSqliteFiles) {
    Write-Host "[bootstrap-develop-env] Note: -UseSeparateSqliteFiles is deprecated (develop always uses bot-develop.sqlite3)." -ForegroundColor DarkGray
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

$envPath = Join-Path $RepoRoot ".env"
if (-not (Test-Path -LiteralPath $envPath)) {
    $ex = Join-Path $RepoRoot ".env.example"
    if (Test-Path -LiteralPath $ex) {
        Copy-Item -LiteralPath $ex -Destination $envPath
        Write-Host "[bootstrap-develop-env] Created .env from .env.example" -ForegroundColor Gray
    } else {
        Write-Error "No .env or .env.example at $RepoRoot"
        exit 1
    }
}

$dataDir = Join-Path $RepoRoot "data"
if (-not (Test-Path -LiteralPath $dataDir)) {
    New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
}
$legacyDb = Join-Path $dataDir "bot.sqlite3"
$developDb = Join-Path $dataDir "bot-develop.sqlite3"
if (-not (Test-Path -LiteralPath $developDb) -and (Test-Path -LiteralPath $legacyDb)) {
    try {
        $sz = (Get-Item -LiteralPath $legacyDb).Length
        if ($sz -gt 0) {
            Copy-Item -LiteralPath $legacyDb -Destination $developDb -Force
            Write-Host "[bootstrap-develop-env] One-time copy: data\bot.sqlite3 -> data\bot-develop.sqlite3 (kept your existing DB)" -ForegroundColor Cyan
        }
    } catch {
        Write-Warning "Could not copy legacy bot.sqlite3 to bot-develop.sqlite3: $_"
    }
}

Assert-EnvFileIsSmallTextFile -LiteralPath $envPath -DisplayLabel "develop .env"

$developKeys = @("KALSHIBOT_DATA_PROFILE", "SQLITE_PATH", "DATA_LOG_DIR")
$developVals = @("develop", "data/bot-develop.sqlite3", "data/logs-develop")

$utf8Read = New-Object System.Text.UTF8Encoding $false
$rootRows = [System.Collections.ArrayList]@([System.IO.File]::ReadAllLines($envPath, $utf8Read))

for ($kidx = 0; $kidx -lt $developKeys.Length; $kidx++) {
    $Key = $developKeys[$kidx]
    $Value = [string]$developVals[$kidx]
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
[System.IO.File]::WriteAllLines($envPath, $rootOut, $utf8Root)

Write-Host "[bootstrap-develop-env] Root .env: develop profile + SQLITE_PATH=data/bot-develop.sqlite3 + DATA_LOG_DIR=data/logs-develop" -ForegroundColor Green

# --- frontend/.env (VITE_* only; does not touch DB paths) ---
$utf8 = New-Object System.Text.UTF8Encoding $false
$fe = Join-Path $RepoRoot "frontend\.env"
if (-not (Test-Path -LiteralPath $fe)) {
    $fex = Join-Path $RepoRoot "frontend\.env.example"
    if (Test-Path -LiteralPath $fex) {
        Copy-Item -LiteralPath $fex -Destination $fe
    }
}
if (Test-Path -LiteralPath $fe) {
    $fel = [System.Collections.ArrayList]@([System.IO.File]::ReadAllLines($fe, $utf8))
    function Fe-Has([string]$Key) {
        $re = "^\s*$([regex]::Escape($Key))\s*="
        foreach ($fl in $fel) {
            $s = [string]$fl
            if ($s -match '^\s*#') { continue }
            if ([string]::IsNullOrWhiteSpace($s)) { continue }
            if ($s -match $re) { return $true }
        }
        return $false
    }
    $addedFe = $false
    if (-not (Fe-Has "VITE_API_ORIGIN")) {
        [void]$fel.Add("VITE_API_ORIGIN=http://127.0.0.1:8765")
        $addedFe = $true
    }
    if (-not (Fe-Has "VITE_UI_TRACK")) {
        [void]$fel.Add("VITE_UI_TRACK=dev")
        $addedFe = $true
    }
    if (-not (Fe-Has "VITE_DEV_PORT")) {
        [void]$fel.Add("VITE_DEV_PORT=5174")
        $addedFe = $true
    }
    if ($addedFe) {
        $fo = New-Object string[] $fel.Count
        for ($j = 0; $j -lt $fel.Count; $j++) { $fo[$j] = [string]$fel[$j] }
        [System.IO.File]::WriteAllLines($fe, $fo, $utf8)
        Write-Host "[bootstrap-develop-env] Updated frontend/.env (VITE_* defaults)" -ForegroundColor Cyan
    }
}

Write-Host "[bootstrap-develop-env] Restart the develop API so SQLITE_PATH is picked up." -ForegroundColor Green
