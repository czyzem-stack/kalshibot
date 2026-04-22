# Creates .venv in the repo root using a Python you choose - does NOT replace your default Python.
# Usage:
#   .\scripts\create_venv.ps1
#   .\scripts\create_venv.ps1 -PythonExe "C:\...\python.exe"
#   .\scripts\create_venv.ps1 -PythonExe "C:\...\Python313"   # folder ok, appends python.exe
# Or: $env:PYTHON_EXE = "C:\...\python.exe"; .\scripts\create_venv.ps1
#
# Python 3.14: not recommended. pydantic-core often has no wheel and must compile Rust
# (needs Visual Studio C++ Build Tools / link.exe). Prefer 3.12 or 3.13. To force 3.14 anyway:
#   .\scripts\create_venv.ps1 -AllowPython314 -PythonExe "C:\Python314\python.exe"

param(
    [string] $PythonExe = "",
    [switch] $AllowPython314
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvDir = Join-Path $RepoRoot ".venv"

function Normalize-PythonPath {
    param([string] $PathIn)
    $p = $PathIn.Trim([char[]](34, 39)).Trim()
    if (-not $p) { return $null }
    if (Test-Path -LiteralPath $p -PathType Container) {
        $try = Join-Path $p "python.exe"
        if (Test-Path -LiteralPath $try) { return (Resolve-Path -LiteralPath $try).Path }
    }
    if (Test-Path -LiteralPath $p -PathType Leaf) {
        return (Resolve-Path -LiteralPath $p).Path
    }
    return $null
}

function Test-UsablePythonExe {
    param([string] $ExePath)
    if (-not (Test-Path -LiteralPath $ExePath)) { return $false }
    try {
        $len = (Get-Item -LiteralPath $ExePath).Length
        if ($len -lt 10240) { return $false }
    } catch {
        return $false
    }
    $lower = $ExePath.ToLowerInvariant()
    if ($lower -like "*\windowsapps\*") {
        try {
            if ($len -lt 500000) { return $false }
        } catch {
            return $false
        }
    }
    return $true
}

function Get-PythonVersionString {
    param([string] $ExePath)
    try {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        $out = & $ExePath "--version" 2>&1 | Out-String
        $ErrorActionPreference = $prev
        return $out.Trim()
    } catch {
        return ""
    }
}

function Find-PythonViaPyLauncher {
    foreach ($ver in @("3.13", "3.12", "3.11")) {
        try {
            $out = & py "-$ver" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -ne 0) { continue }
            $candidate = ($out | Out-String).Trim()
            if ($candidate -and (Test-UsablePythonExe $candidate)) {
                Write-Host "Using py launcher: Python $ver -> $candidate"
                return $candidate
            }
        } catch {
            continue
        }
    }
    return $null
}

function Find-PythonViaPyZeroP {
    $found = @()
    try {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        $lines = & py -0p 2>$null
        $ErrorActionPreference = $prev
        if (-not $lines) { return $found }
        foreach ($line in $lines) {
            if ($line -notmatch "(?i)([a-z]:\\[^\r\n]+\.exe)") { continue }
            $p = $Matches[1].Trim()
            if (Test-UsablePythonExe $p) { $found += $p }
        }
    } catch {
        return $found
    }
    return $found | Select-Object -Unique
}

function Find-PythonViaWhere {
    $found = @()
    foreach ($name in @("python.exe", "python3.exe", "python3.13.exe", "python3.12.exe", "python3.11.exe")) {
        try {
            $prev = $ErrorActionPreference
            $ErrorActionPreference = "SilentlyContinue"
            $out = & where.exe $name 2>$null
            $ErrorActionPreference = $prev
            if ($LASTEXITCODE -ne 0) { continue }
            foreach ($line in ($out -split "`r?`n")) {
                $t = $line.Trim()
                if ($t -and (Test-UsablePythonExe $t)) { $found += $t }
            }
        } catch {
            continue
        }
    }
    return $found | Select-Object -Unique
}

function Discover-PythonUnderFolder {
    param([string] $Root, [int] $MaxResults = 40)
    if (-not (Test-Path -LiteralPath $Root)) { return @() }
    try {
        return @(Get-ChildItem -LiteralPath $Root -Recurse -Filter "python.exe" -ErrorAction SilentlyContinue |
                Select-Object -First $MaxResults |
                ForEach-Object { $_.FullName } |
                Where-Object { Test-UsablePythonExe $_ })
    } catch {
        return @()
    }
}

function Discover-PythonInstalls {
    $found = @()

    $roots = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python"),
        (Join-Path $env:LOCALAPPDATA "Python"),
        (Join-Path $env:ProgramFiles "Python312"),
        (Join-Path $env:ProgramFiles "Python313"),
        (Join-Path $env:ProgramFiles "Python311"),
        "C:\Python312",
        "C:\Python313",
        "C:\Python311"
    )
    foreach ($r in $roots) {
        $found += Discover-PythonUnderFolder -Root $r -MaxResults 40
    }

    $pf = $env:ProgramFiles
    if ($pf -and (Test-Path -LiteralPath $pf)) {
        Get-ChildItem -LiteralPath $pf -Directory -Filter "Python*" -ErrorAction SilentlyContinue |
            ForEach-Object { $found += Discover-PythonUnderFolder -Root $_.FullName -MaxResults 20 }
    }

    $found += Find-PythonViaPyZeroP
    $found += Find-PythonViaWhere

    foreach ($dir in ($env:PATH -split ";")) {
        $d = $dir.Trim()
        if (-not $d) { continue }
        $candidate = Join-Path $d "python.exe"
        if (Test-UsablePythonExe $candidate) { $found += $candidate }
        $candidate3 = Join-Path $d "python3.exe"
        if (Test-UsablePythonExe $candidate3) { $found += $candidate3 }
    }

    return $found | Select-Object -Unique
}

function Pick-BestPython {
    param([string[]] $Candidates, [bool] $AllowPython314 = $false)
    $ranked = @()
    foreach ($c in ($Candidates | Select-Object -Unique)) {
        if (-not (Test-UsablePythonExe $c)) { continue }
        $ver = Get-PythonVersionString $c
        $score = 0
        if ($ver -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 14 -and -not $AllowPython314) {
                continue
            }
            if ($minor -eq 13) { $score = 300 + $minor }
            elseif ($minor -eq 12) { $score = 200 + $minor }
            elseif ($minor -eq 11) { $score = 100 + $minor }
            elseif ($minor -eq 14) { $score = 50 + $minor }
            else { $score = $minor }
        } else {
            $score = 1
        }
        $ranked += [pscustomobject]@{ Path = $c; Version = $ver; Score = $score }
    }
    if ($ranked.Count -eq 0) { return $null }
    return ($ranked | Sort-Object Score -Descending | Select-Object -First 1).Path
}

$PythonExe = $PythonExe.Trim()

$py = $null
if ($PythonExe) {
    $py = Normalize-PythonPath -PathIn $PythonExe
    if (-not $py) {
        Write-Host "ERROR: That path is not a valid python.exe (or folder containing it):" -ForegroundColor Red
        Write-Host "  $PythonExe" -ForegroundColor Yellow
        $parent = Split-Path -Parent $PythonExe
        if ($parent -and (Test-Path -LiteralPath $parent)) {
            Write-Host ""
            Write-Host "Contents of parent folder:" -ForegroundColor Cyan
            Get-ChildItem -LiteralPath $parent | ForEach-Object { Write-Host "  $($_.Name)" }
        }
    }
}

if (-not $py -and $env:PYTHON_EXE) {
    $py = Normalize-PythonPath -PathIn $env:PYTHON_EXE.Trim()
}

if (-not $py) {
    $py = Find-PythonViaPyLauncher
}

if (-not $py) {
    $all = @(Discover-PythonInstalls)
    $py = Pick-BestPython -Candidates $all -AllowPython314:$AllowPython314
    if (-not $py -and -not $AllowPython314) {
        $only314 = @()
        foreach ($c in ($all | Select-Object -Unique)) {
            if (-not (Test-UsablePythonExe $c)) { continue }
            $vs = Get-PythonVersionString $c
            if ($vs -match "Python 3\.14") { $only314 += $c }
        }
        if ($only314.Count -gt 0) {
            Write-Host ""
            Write-Host "Found only Python 3.14 (e.g. $($only314[0]))." -ForegroundColor Yellow
            Write-Host "This stack needs Python 3.12 or 3.13 so pip can install pydantic-core from a wheel." -ForegroundColor Yellow
            Write-Host "Install from: https://www.python.org/downloads/windows/" -ForegroundColor Cyan
            Write-Host "Then run: .\scripts\create_venv.ps1 -PythonExe `"C:\Path\to\Python312\python.exe`"" -ForegroundColor Cyan
            Write-Host ""
            Write-Host "Advanced (not recommended): Visual Studio Build Tools with C++ workload, then:" -ForegroundColor DarkYellow
            Write-Host "  .\scripts\create_venv.ps1 -AllowPython314 -PythonExe `"C:\Python314\python.exe`"" -ForegroundColor DarkYellow
            Write-Host ""
        }
    }
    if ($py) {
        Write-Host "Auto-selected Python:" -ForegroundColor Green
        Write-Host "  $(Get-PythonVersionString $py)" -ForegroundColor Green
        Write-Host "  $py" -ForegroundColor Green
        Write-Host ""
    }
}

if (-not $py) {
    Write-Host ""
    Write-Host "No usable Python found." -ForegroundColor Red
    Write-Host ""
    Write-Host "Try these in PowerShell and paste a real path from the output:" -ForegroundColor Cyan
    Write-Host "  py -0p"
    Write-Host "  where.exe python"
    Write-Host "  Get-Command python, py -ErrorAction SilentlyContinue | Format-List Source"
    Write-Host ""
    Write-Host "Then run:" -ForegroundColor Cyan
    Write-Host '  .\scripts\create_venv.ps1 -PythonExe "FULL_PATH\python.exe"'
    Write-Host ""
    Write-Host "Install if needed (Windows installer):" -ForegroundColor Cyan
    Write-Host "  https://www.python.org/downloads/windows/"
    Write-Host ""
    Write-Error "No python.exe found. Install Python 3.12/3.13 or pass -PythonExe."
    exit 1
}

if (-not $AllowPython314) {
    $vs = Get-PythonVersionString $py
    if ($vs -match "Python 3\.14") {
        Write-Host ""
        Write-Host "Refusing Python 3.14 for this project (pydantic-core needs a wheel or MSVC link.exe)." -ForegroundColor Red
        Write-Host "Install Python 3.12 or 3.13, then:" -ForegroundColor Cyan
        Write-Host '  .\scripts\create_venv.ps1 -PythonExe "C:\Path\to\Python312\python.exe"' -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Or after installing Visual Studio Build Tools (C++), force 3.14 with -AllowPython314." -ForegroundColor DarkYellow
        Write-Host ""
        Write-Error "Use Python 3.12/3.13, or pass -AllowPython314 with MSVC installed."
        exit 1
    }
}

Write-Host "Creating venv at: $VenvDir"
Write-Host "Interpreter: $py"

if (Test-Path -LiteralPath $VenvDir) {
    Write-Host "Removing existing .venv ..."
    Remove-Item -LiteralPath $VenvDir -Recurse -Force
}

& $py -m venv $VenvDir

$venvPython = Join-Path $VenvDir "Scripts\python.exe"
& $venvPython -m pip install -U pip
& $venvPython -m pip install -r (Join-Path $RepoRoot "requirements.txt")

Write-Host ""
Write-Host "Done. Activate the venv with:" -ForegroundColor Green
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "Or run the API with:" -ForegroundColor Green
Write-Host "  .\scripts\run_backend.ps1"
Write-Host ""
