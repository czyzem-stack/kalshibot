# Git pull (and optional pip/npm) on **develop** (this repo) + **main** + **test** checkouts.
# Path rules match ``launch_local.ps1`` (git worktree list, siblings Kalshibot-main / Kalshibot-test, KALSHIBOT_TEST_WORKTREE).
#
# Usage (from develop repo root):
#   .\scripts\update_all_worktrees.ps1
#   .\scripts\update_all_worktrees.ps1 -Pip -Npm
#   .\scripts\update_all_worktrees.ps1 -SkipMain -SkipTest
#   .\scripts\update_all_worktrees.ps1 -MainWorktreePath "D:\repos\Kalshibot-main" -TestWorktreePath "D:\repos\Kalshibot-test"

param(
    [string]$MainWorktreePath = "",
    [string]$TestWorktreePath = "",
    [switch]$SkipMain,
    [switch]$SkipTest,
    [switch]$Pip,
    [switch]$Npm
)

$ErrorActionPreference = "Continue"
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

function Test-HasGitMeta([string]$Dir) {
    if ([string]::IsNullOrWhiteSpace($Dir)) { return $false }
    return Test-Path -LiteralPath (Join-Path $Dir ".git")
}

function Resolve-MainWorktreeRoot([string]$RepoRoot, [string]$ExplicitFromParam) {
    if (-not [string]::IsNullOrWhiteSpace($ExplicitFromParam)) {
        return [System.IO.Path]::GetFullPath($ExplicitFromParam.Trim())
    }
    $fromGit = Get-LinkedMainWorktreePath $RepoRoot
    if ($fromGit) { return $fromGit }
    return [System.IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $RepoRoot) "Kalshibot-main"))
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
    $repoCanon = [System.IO.Path]::GetFullPath($RepoRoot)
    $parent = Split-Path -Parent $RepoRoot
    foreach ($leaf in @("Kalshibot-test", "kalshibot-test")) {
        $cand = [System.IO.Path]::GetFullPath((Join-Path $parent $leaf))
        if ($cand -eq $repoCanon) { continue }
        if (Test-HasGitMeta $cand) { return $cand }
    }
    return [System.IO.Path]::GetFullPath((Join-Path $parent "Kalshibot-test"))
}

function Update-OneCheckout {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $hasGit = Test-HasGitMeta $Path
    if (-not $hasGit) {
        Write-Host ""
        Write-Host "[update_all_worktrees] Skip $Label - not a git checkout: $Path" -ForegroundColor Yellow
        return 0
    }
    Write-Host ""
    Write-Host "======== $Label ========" -ForegroundColor Cyan
    Write-Host $Path -ForegroundColor DarkGray
    Push-Location -LiteralPath $Path
    try {
        git status -sb 2>&1 | Write-Host
        git fetch origin 2>&1 | Write-Host
        git pull --ff-only 2>&1 | Write-Host
        $code = $LASTEXITCODE
        if ($code -ne 0) {
            Write-Warning "git pull --ff-only exited $code in $Label. Fix upstream / merge locally, then re-run."
            return $code
        }
        if ($Pip) {
            $venvPy = Join-Path $Path ".venv\Scripts\python.exe"
            $req = Join-Path $Path "requirements.txt"
            if ((Test-Path -LiteralPath $venvPy) -and (Test-Path -LiteralPath $req)) {
                Write-Host "pip install -r requirements.txt ..." -ForegroundColor Yellow
                & $venvPy -m pip install -r $req 2>&1 | Write-Host
                if ($LASTEXITCODE -ne 0) { return $LASTEXITCODE }
            } else {
                Write-Host "Skip pip ($Label): missing .venv or requirements.txt" -ForegroundColor DarkGray
            }
        }
        if ($Npm) {
            $fe = Join-Path $Path "frontend"
            $pkg = Join-Path $fe "package.json"
            if (Test-Path -LiteralPath $pkg) {
                Write-Host "npm install (frontend) ..." -ForegroundColor Yellow
                Push-Location -LiteralPath $fe
                try {
                    npm install 2>&1 | Write-Host
                    if ($LASTEXITCODE -ne 0) { return $LASTEXITCODE }
                } finally {
                    Pop-Location
                }
            } else {
                Write-Host "Skip npm ($Label): no frontend/package.json" -ForegroundColor DarkGray
            }
        }
        return 0
    } finally {
        Pop-Location
    }
}

$mainResolved = Resolve-MainWorktreeRoot $RepoRoot $MainWorktreePath
$testResolved = Resolve-TestWorktreeRoot $RepoRoot $TestWorktreePath

Write-Host "update_all_worktrees - develop: $RepoRoot" -ForegroundColor Green
if (-not $SkipMain) {
    Write-Host "  main:  $mainResolved" -ForegroundColor Green
} else {
    Write-Host "  main:  (skipped -SkipMain)" -ForegroundColor DarkGray
}
if (-not $SkipTest) {
    Write-Host "  test:  $testResolved" -ForegroundColor Green
} else {
    Write-Host "  test:  (skipped -SkipTest)" -ForegroundColor DarkGray
}

$bad = 0
$bad = [Math]::Max($bad, (Update-OneCheckout -Path $RepoRoot -Label "develop"))

if (-not $SkipMain) {
    if (([System.IO.Path]::GetFullPath($mainResolved)) -eq ([System.IO.Path]::GetFullPath($RepoRoot))) {
        Write-Warning "Main path equals develop root; skipping second pull on develop."
    } else {
        $bad = [Math]::Max($bad, (Update-OneCheckout -Path $mainResolved -Label "main"))
    }
}

if (-not $SkipTest) {
    if (([System.IO.Path]::GetFullPath($testResolved)) -eq ([System.IO.Path]::GetFullPath($RepoRoot))) {
        Write-Warning "Test path equals develop root; skipping second pull on develop."
    } elseif (([System.IO.Path]::GetFullPath($testResolved)) -eq ([System.IO.Path]::GetFullPath($mainResolved)) -and -not $SkipMain) {
        Write-Warning "Test path equals main path; skipping duplicate."
    } else {
        $bad = [Math]::Max($bad, (Update-OneCheckout -Path $testResolved -Label "test"))
    }
}

Write-Host ""
if ($bad -ne 0) {
    Write-Host "Done with errors (exit $bad from at least one step). See messages above." -ForegroundColor Yellow
    exit $bad
}
Write-Host "All requested checkouts updated." -ForegroundColor Green
exit 0
