# Sanity-check develop + main worktrees: distinct SQLite files and frontend API URLs (avoids empty charts / shared state).
# Does not modify files. Run from develop repo root:
#   .\scripts\verify-dual-instances.ps1
#
param(
    [string]$MainWorktreePath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

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

function Resolve-SqliteAbsolute([string]$RepoRootDir, [string]$DotEnvPath) {
    if (-not (Test-Path -LiteralPath $DotEnvPath)) { return $null }
    $md = Select-String -LiteralPath $DotEnvPath -Pattern '^\s*SQLITE_PATH\s*=\s*(.+)\s*$' | Select-Object -First 1
    $raw = $null
    if ($null -ne $md -and $md.Matches.Count -gt 0) {
        $raw = $md.Matches[0].Groups[1].Value.Trim().Trim('"').Trim("'")
    }
    if ($null -eq $raw -or [string]::IsNullOrWhiteSpace($raw)) {
        return [System.IO.Path]::GetFullPath((Join-Path $RepoRootDir "data\bot.sqlite3"))
    }
    if ([System.IO.Path]::IsPathRooted($raw)) {
        return [System.IO.Path]::GetFullPath($raw)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $RepoRootDir $raw))
}

function Read-EnvKey([string]$Path, [string]$Key) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $re = "^\s*$([regex]::Escape($Key))\s*=\s*(.+)\s*$"
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*#') { continue }
        if ($line -match $re) { return $matches[1].Trim().Trim('"').Trim("'") }
    }
    return $null
}

if (-not $MainWorktreePath) {
    $MainWorktreePath = Get-LinkedMainWorktreePath $RepoRoot
    if (-not $MainWorktreePath) {
        $MainWorktreePath = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "..\Kalshibot-main"))
    }
} else {
    $MainWorktreePath = [System.IO.Path]::GetFullPath($MainWorktreePath)
}

Write-Host ""
Write-Host "verify-dual-instances" -ForegroundColor Cyan
Write-Host "  develop: $RepoRoot" -ForegroundColor Gray
Write-Host "  main:    $MainWorktreePath" -ForegroundColor Gray
Write-Host ""

$devEnv = Join-Path $RepoRoot ".env"
$mainEnv = Join-Path $MainWorktreePath ".env"
$devFe = Join-Path $RepoRoot "frontend\.env"
$mainFe = Join-Path $MainWorktreePath "frontend\.env"

$sqlDev = Resolve-SqliteAbsolute $RepoRoot $devEnv
$sqlMain = $null
if (Test-Path -LiteralPath (Join-Path $MainWorktreePath ".git")) {
    $sqlMain = Resolve-SqliteAbsolute $MainWorktreePath $mainEnv
}

Write-Host "SQLite (resolved):" -ForegroundColor Yellow
Write-Host "  develop -> $sqlDev"
if ($sqlMain) {
    Write-Host "  main    -> $sqlMain"
    if ($sqlDev -and $sqlMain -and ($sqlDev -eq $sqlMain)) {
        Write-Warning "Develop and main point at the SAME database file. Charts and resets will look shared. Use distinct SQLITE_PATH (see bootstrap scripts)."
    }
} else {
    Write-Host "  main    -> (no main checkout at path)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Frontend proxy (VITE_API_ORIGIN):" -ForegroundColor Yellow
$oDev = Read-EnvKey $devFe "VITE_API_ORIGIN"
$oMain = Read-EnvKey $mainFe "VITE_API_ORIGIN"
Write-Host "  develop frontend/.env -> $(if ($oDev) { $oDev } else { '(missing - defaults http://127.0.0.1:8765)' })"
if (Test-Path -LiteralPath (Join-Path $MainWorktreePath "frontend\package.json")) {
    Write-Host "  main    frontend/.env -> $(if ($oMain) { $oMain } else { '(missing)' })"
    if ($oDev -and $oMain -and ($oDev -eq $oMain)) {
        Write-Warning "Both frontends proxy to the SAME API. Open :5173 vs :5174 tabs will show duplicate data - fix frontend/.env per worktree."
    }
}

Write-Host ""
Write-Host "VITE_DEV_PORT (vite.config uses this so manual npm run dev does not collide):" -ForegroundColor Yellow
Write-Host "  develop -> $(if (Read-EnvKey $devFe 'VITE_DEV_PORT') { Read-EnvKey $devFe 'VITE_DEV_PORT' } else { '(unset - default 5174)' })"
if (Test-Path -LiteralPath (Join-Path $MainWorktreePath "frontend\package.json")) {
    Write-Host "  main    -> $(if (Read-EnvKey $mainFe 'VITE_DEV_PORT') { Read-EnvKey $mainFe 'VITE_DEV_PORT' } else { '(unset - default 5174)' })"
}

Write-Host ""
Write-Host "Git: each worktree has its own branch; you can commit or push main without touching develop." -ForegroundColor Yellow
if (Test-Path -LiteralPath (Join-Path $RepoRoot ".git")) {
    Push-Location $RepoRoot
    try {
        Write-Host "  develop:  $(git branch --show-current 2>$null) @ $(git rev-parse --short HEAD 2>$null)"
    } finally { Pop-Location }
}
if (Test-Path -LiteralPath (Join-Path $MainWorktreePath ".git")) {
    Push-Location $MainWorktreePath
    try {
        Write-Host "  main wt:  $(git branch --show-current 2>$null) @ $(git rev-parse --short HEAD 2>$null)"
    } finally { Pop-Location }
}

function Get-ApiPortFromEnv([string]$DotEnvPath, [int]$DefaultPort) {
    $v = Read-EnvKey $DotEnvPath "KALSHI_BOT_PORT"
    if ($null -ne $v -and $v -match '^\d+$') { return [int]$v }
    return $DefaultPort
}

function Try-JsonStorage([string]$BaseOrigin) {
    $uri = "$BaseOrigin/api/data/storage".TrimEnd('/')
    try {
        $r = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        $j = $r.Content | ConvertFrom-Json
        return @{ ok = $true; sqlite_path = [string]$j.sqlite_path }
    } catch {
        return @{ ok = $false; sqlite_path = $null }
    }
}

function Try-Health([string]$BaseOrigin) {
    $uri = "$BaseOrigin/api/health".TrimEnd('/')
    try {
        $r = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 4 -ErrorAction Stop
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

$devPort = Get-ApiPortFromEnv $devEnv 8765
$mainPort = if (Test-Path -LiteralPath $mainEnv) { Get-ApiPortFromEnv $mainEnv 8770 } else { 8770 }
$devOrigin = "http://127.0.0.1:$devPort"
$mainOrigin = "http://127.0.0.1:$mainPort"

Write-Host ""
Write-Host "API ports (.env KALSHI_BOT_PORT, defaults 8765 develop / 8770 main):" -ForegroundColor Yellow
Write-Host "  develop -> $devPort"
Write-Host "  main    -> $mainPort"

Write-Host ""
Write-Host "Live probes (API must be running):" -ForegroundColor Yellow
$devUp = Try-Health $devOrigin
$mainUp = Try-Health $mainOrigin
Write-Host "  GET $devOrigin/api/health -> $(if ($devUp) { 'OK' } else { 'no response (start API or check port)' })"
Write-Host "  GET $mainOrigin/api/health -> $(if ($mainUp) { 'OK' } else { 'no response (start API or check port)' })"

if ($devUp) {
    $st = Try-JsonStorage $devOrigin
    if ($st.ok) {
        Write-Host "  develop sqlite (runtime): $($st.sqlite_path)" -ForegroundColor DarkGray
    }
}
if ($mainUp) {
    $st = Try-JsonStorage $mainOrigin
    if ($st.ok) {
        Write-Host "  main    sqlite (runtime): $($st.sqlite_path)" -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "If develop works but main looks wrong:" -ForegroundColor Yellow
if (-not $mainUp -and $devUp) {
    Write-Host "  - Main API is not reachable on $mainOrigin - start it from the main worktree (e.g. launch-main-sidecar.ps1 / launch_local.ps1)." -ForegroundColor DarkGray
}
if ($sqlMain -and $mainUp -and $devUp) {
    $stM = Try-JsonStorage $mainOrigin
    if ($stM.ok -and $sqlMain -and ($stM.sqlite_path -ne $sqlMain)) {
        Write-Warning "Main .env SQLITE_PATH resolves to '$sqlMain' but running API uses '$($stM.sqlite_path)' - restart the API after editing .env."
    }
}
if (Test-Path -LiteralPath (Join-Path $RepoRoot ".git")) {
    Push-Location $RepoRoot
    try {
        $ahead = git rev-list --count main..develop 2>$null
        if ($LASTEXITCODE -eq 0 -and $ahead -match '^\d+$' -and [int]$ahead -gt 0) {
            Write-Host "  - Local branch develop is $ahead commit(s) ahead of main - the main checkout/worktree can lack fixes without any push; merge or cherry-pick if you need the same code." -ForegroundColor DarkGray
        }
    } catch {} finally { Pop-Location }
}

Write-Host ""
