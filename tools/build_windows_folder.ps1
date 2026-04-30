param(
    [string]$AppName = "MF4DataAnalyzer",
    [switch]$Console,
    [switch]$SkipInstall,
    [switch]$KeepPrevious
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-BasePython {
    param([string[]]$Arguments)

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        & $pyLauncher.Source -3 @Arguments
        return
    }

    $python = Get-Command python -ErrorAction Stop
    & $python.Source @Arguments
}

if ($env:OS -ne "Windows_NT") {
    Write-Warning "This script is intended to build a Windows .exe from Windows."
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EntryScript = Join-Path $RepoRoot "MF4 Data Analyzer V1.py"
$Requirements = Join-Path $RepoRoot "requirements.txt"
$StyleQss = Join-Path $RepoRoot "mf4_analyzer\ui\style.qss"
$VenvDir = Join-Path $RepoRoot ".venv-build-win"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$DistDir = Join-Path $RepoRoot "dist"
$WorkDir = Join-Path $RepoRoot "build\pyinstaller"
$SpecDir = Join-Path $RepoRoot "build\spec"
$OutputDir = Join-Path $DistDir $AppName
$ExePath = Join-Path $OutputDir "$AppName.exe"
# Default output: dist\MF4DataAnalyzer\MF4DataAnalyzer.exe

foreach ($RequiredPath in @($EntryScript, $Requirements, $StyleQss)) {
    if (-not (Test-Path $RequiredPath)) {
        throw "Required file not found: $RequiredPath"
    }
}

Write-Step "Preparing build environment"
if (-not (Test-Path $VenvPython)) {
    Invoke-BasePython -Arguments @("-m", "venv", $VenvDir)
}

if (-not $SkipInstall) {
    & $VenvPython -m pip install --upgrade pip setuptools wheel
    & $VenvPython -m pip install -r $Requirements
    & $VenvPython -m pip install --upgrade pyinstaller qtawesome
}

if (-not $KeepPrevious) {
    foreach ($PathToRemove in @($OutputDir, $WorkDir, $SpecDir)) {
        if (Test-Path $PathToRemove) {
            Remove-Item -Recurse -Force $PathToRemove
        }
    }
}

New-Item -ItemType Directory -Force -Path $DistDir, $WorkDir, $SpecDir | Out-Null

Write-Step "Building folder-style exe with PyInstaller"
$AddDataStyle = "$StyleQss;mf4_analyzer\ui"
$PyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onedir"
)
if ($Console) {
    $PyInstallerArgs += "--console"
} else {
    $PyInstallerArgs += "--windowed"
}
$PyInstallerArgs += @(
    "--name", $AppName,
    "--distpath", $DistDir,
    "--workpath", $WorkDir,
    "--specpath", $SpecDir,
    "--hidden-import", "mf4_analyzer._fonts",
    "--hidden-import", "mf4_analyzer.ui",
    "--hidden-import", "mf4_analyzer.ui.main_window",
    "--hidden-import", "mf4_analyzer.ui.icons",
    "--add-data", $AddDataStyle,
    "--collect-all", "qtawesome",
    "--collect-all", "asammdf",
    $EntryScript
)

& $VenvPython @PyInstallerArgs

if (-not (Test-Path $ExePath)) {
    throw "Build finished but exe was not found: $ExePath"
}

Write-Step "Build output"
Write-Host "Folder: $OutputDir"
Write-Host "Exe:    $ExePath"
Write-Host "Run:    $ExePath"
