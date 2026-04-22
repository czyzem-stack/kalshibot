# Initialize a git repository in the project root (run from repo root or anywhere).
# Requires Git for Windows: https://git-scm.com/download/win

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$git = $null
foreach ($c in @("git", "$env:ProgramFiles\Git\bin\git.exe", "$env:ProgramFiles\Git\cmd\git.exe", "${env:ProgramFiles(x86)}\Git\bin\git.exe")) {
  try {
    if ($c -eq "git") {
      $g = Get-Command git -ErrorAction SilentlyContinue
      if ($g) { $git = $g.Source; break }
    } elseif (Test-Path $c) { $git = $c; break }
  } catch { }
}

if (-not $git) {
  Write-Host "Git was not found on PATH or in Program Files." -ForegroundColor Yellow
  Write-Host "Install Git for Windows, then re-open the terminal and run:" -ForegroundColor Yellow
  Write-Host "  .\scripts\init_git.ps1" -ForegroundColor Cyan
  exit 1
}

Write-Host "Using: $git" -ForegroundColor DarkGray

if (Test-Path (Join-Path $root ".git")) {
  Write-Host "Already a git repo at $root" -ForegroundColor Green
  & $git -C $root status
  exit 0
}

& $git init
& $git add -A
& $git status

$email = & $git config user.email 2>$null
$name = & $git config user.name 2>$null
if (-not $email -or -not $name) {
  Write-Host "Git needs your name and email once (stored in global config):" -ForegroundColor Yellow
  if (-not $name) {
    $n = Read-Host "user.name (e.g. Your Name)"
    if ($n) { & $git config --global user.name $n }
  }
  if (-not $email) {
    $e = Read-Host "user.email (e.g. you@example.com)"
    if ($e) { & $git config --global user.email $e }
  }
}

$msg = Read-Host "Initial commit message (Enter for 'Initial commit')"
if ([string]::IsNullOrWhiteSpace($msg)) { $msg = "Initial commit" }
& $git commit -m $msg
Write-Host "Done. Next: create a GitHub repo and run:" -ForegroundColor Green
Write-Host "  git remote add origin https://github.com/<you>/<repo>.git" -ForegroundColor Cyan
Write-Host "  git branch -M main" -ForegroundColor Cyan
Write-Host "  git push -u origin main" -ForegroundColor Cyan
