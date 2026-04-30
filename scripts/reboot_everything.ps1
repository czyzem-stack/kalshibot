# One-shot: stop Kalshibot listeners on this machine, then run launch_local.ps1 (develop API + Vite; optional main worktree).
#
# Stops processes **listening** on the ports from your .env files (defaults: API 8765 / 8770, Vite 5174 / 5173).
# Close anything else using those ports before running if you share ports with other apps.
#
# Usage (from develop repo root):
#   .\scripts\reboot_everything.ps1
#   .\scripts\reboot_everything.ps1 -SkipMainSidecar
#   .\scripts\reboot_everything.ps1 -WorktreePath "D:\repos\Kalshibot-main"
#   .\scripts\reboot_everything.ps1 -WhatIf    # list ports only; no kill, no launch

param(
    [switch]$SkipMainSidecar,
    [string]$WorktreePath = "",
    [switch]$WhatIf
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

function Read-DotEnvKey([string]$LiteralPath, [string]$Key) {
    if (-not (Test-Path -LiteralPath $LiteralPath)) { return $null }
    $re = "^\s*$([regex]::Escape($Key))\s*=\s*(.+)\s*$"
    foreach ($line in Get-Content -LiteralPath $LiteralPath -ErrorAction Stop) {
        if ($line -match '^\s*#') { continue }
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line -match $re) { return $matches[1].Trim().Trim('"').Trim("'") }
    }
    return $null
}

function Parse-PositiveInt([string]$Raw, [int]$Default) {
    if ([string]::IsNullOrWhiteSpace($Raw)) { return $Default }
    try {
        $n = [int]$Raw.Trim()
        if ($n -ge 1 -and $n -le 65535) { return $n }
    } catch { }
    return $Default
}

function Stop-ListenersOnPort([int]$Port) {
    try {
        $conns = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    } catch {
        return
    }
    $seen = @{}
    foreach ($c in $conns) {
        $procId = [int]$c.OwningProcess
        if ($procId -lt 1 -or $seen.ContainsKey($procId)) { continue }
        $seen[$procId] = $true
        try {
            $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
            $name = if ($p) { $p.ProcessName } else { "pid" }
            Write-Host "  Stopping $name (PID $procId) on port $Port" -ForegroundColor Yellow
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        } catch { }
    }
}

if (-not $WorktreePath) {
    $wt = Get-LinkedMainWorktreePath $RepoRoot
    if ($wt) {
        $WorktreePath = $wt
    } else {
        $WorktreePath = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "..\Kalshibot-main"))
    }
} else {
    $WorktreePath = [System.IO.Path]::GetFullPath($WorktreePath)
}

$wtGit = Join-Path $WorktreePath ".git"
$wtEnv = Join-Path $WorktreePath ".env"
$useMainSidecar = $false
if (-not $SkipMainSidecar -and (Test-Path -LiteralPath $wtGit) -and (Test-Path -LiteralPath $wtEnv)) {
    $useMainSidecar = $true
}

$devEnv = Join-Path $RepoRoot ".env"
$devFe = Join-Path $RepoRoot "frontend\.env"

$devPort = 8765
if ($env:KALSHI_BOT_PORT -and $env:KALSHI_BOT_PORT -match "^\d+$") {
    $devPort = [int]$env:KALSHI_BOT_PORT
} else {
    $ds = Read-DotEnvKey $devEnv "KALSHI_BOT_PORT"
    if ($ds -and $ds -match "^\d+$") { $devPort = [int]$ds }
}

$mainPort = 8770
if ($useMainSidecar) {
    $ms = Read-DotEnvKey $wtEnv "KALSHI_BOT_PORT"
    if ($ms -and $ms -match "^\d+$") { $mainPort = [int]$ms }
    if ($mainPort -eq $devPort) {
        Write-Warning "Main API port equals develop ($devPort); treating as single-stack for reboot (main sidecar off)."
        $useMainSidecar = $false
    }
}

$devVite = Parse-PositiveInt (Read-DotEnvKey $devFe "VITE_DEV_PORT") 5174
$mainVite = 5173
if ($useMainSidecar) {
    $mainFeEnv = Join-Path $WorktreePath "frontend\.env"
    $mainVite = Parse-PositiveInt (Read-DotEnvKey $mainFeEnv "VITE_DEV_PORT") 5173
}

$ports = @($devPort, $devVite)
if ($useMainSidecar) {
    $ports += $mainPort, $mainVite
}
$sorted = @($ports | Sort-Object -Unique)

Write-Host ""
Write-Host "reboot_everything - ports: $($sorted -join ', ')" -ForegroundColor Cyan
Write-Host "  develop repo: $RepoRoot" -ForegroundColor DarkGray
if ($useMainSidecar) {
    Write-Host "  main worktree: $WorktreePath" -ForegroundColor DarkGray
} else {
    Write-Host "  main sidecar: off (-SkipMainSidecar or no main .env)" -ForegroundColor DarkGray
}

if ($WhatIf) {
    Write-Host ""
    Write-Host "-WhatIf: no processes stopped; launch_local not run." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "Stopping listeners (best effort)..." -ForegroundColor Yellow
foreach ($pp in $sorted) {
    Stop-ListenersOnPort $pp
}
Start-Sleep -Seconds 1

$launch = Join-Path $PSScriptRoot "launch_local.ps1"
Write-Host ""
Write-Host "Starting launch_local.ps1" -ForegroundColor Green
if ($SkipMainSidecar) {
    & $launch -SkipMainSidecar -WorktreePath $WorktreePath
} else {
    & $launch -WorktreePath $WorktreePath
}
