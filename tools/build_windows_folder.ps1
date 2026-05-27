param(
    [string]$Version = "3.0",
    [string]$AppName = "",
    [switch]$Console,
    [switch]$SkipInstall,
    [switch]$KeepPrevious
)

if (-not $AppName) {
    $AppName = "TraceLab$Version"
}

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
$StyleQss = Join-Path $RepoRoot "mf4_analyzer\ui_kit\style.qss"
$IconsDir = Join-Path $RepoRoot "assets\icons"
$AppIcon = Join-Path $IconsDir "tracelab.ico"
$RuntimeHookPyxcp = Join-Path $PSScriptRoot "pyinstaller_rthook_pyxcp_vendor.py"
$VenvDir = Join-Path $RepoRoot ".venv-build-win"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$DistDir = Join-Path $RepoRoot "dist"
$WorkDir = Join-Path $RepoRoot "build\pyinstaller"
$SpecDir = Join-Path $RepoRoot "build\spec"
$VendorPyxcpDir = Join-Path $WorkDir "_vendor_pyxcp"
$OutputDir = Join-Path $DistDir $AppName
$ExePath = Join-Path $OutputDir "$AppName.exe"
# Default output: dist\TraceLab3.0\TraceLab3.0.exe (override with -Version or -AppName)

foreach ($RequiredPath in @($EntryScript, $Requirements, $StyleQss, $RuntimeHookPyxcp)) {
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

# pyxcp triggers a 0xC0000005 inside a PyQt-loaded process if PyInstaller's
# analysis phase imports it (native DLL loaded twice). Vendor the package
# into _vendor_pyxcp at build time and exclude pyxcp from analysis; the
# runtime hook puts _vendor_pyxcp on sys.path before any acquisition code
# runs. See docs/lessons-learned/codex-windows-native-import-guard.md.
Write-Step "Vendoring pyxcp to _vendor_pyxcp (avoid analysis-time native import)"
if (Test-Path $VendorPyxcpDir) {
    Remove-Item -Recurse -Force $VendorPyxcpDir
}
New-Item -ItemType Directory -Force -Path $VendorPyxcpDir | Out-Null
$PyxcpLocateScript = @"
import pathlib, pyxcp
print(pathlib.Path(pyxcp.__file__).parent)
"@
$PyxcpSrc = (& $VenvPython -c $PyxcpLocateScript).Trim()
if (-not $PyxcpSrc -or -not (Test-Path $PyxcpSrc)) {
    throw "pyxcp not found in venv: ensure it is listed in requirements.txt"
}
Copy-Item -Recurse -Force -Path $PyxcpSrc -Destination (Join-Path $VendorPyxcpDir "pyxcp")

Write-Step "Building folder-style exe with PyInstaller"
$AddDataStyle = "$StyleQss;mf4_analyzer\ui_kit"
$AddDataIcons = "$IconsDir;assets\icons"
$AddDataVendorPyxcp = "$VendorPyxcpDir;_vendor_pyxcp"
$HiddenImports = @(
    "mf4_analyzer.ui_kit",
    "mf4_analyzer.ui_kit.fonts",
    "mf4_analyzer.ui_kit.icons",
    "mf4_analyzer.ui_kit.stylesheet",
    "mf4_analyzer.ui_kit.widgets.searchable_combo",
    "mf4_analyzer.ui",
    "mf4_analyzer.ui.main_window",
    "mf4_analyzer.acquisition_capture",
    "mf4_analyzer.acquisition_capture.thresholds",
    "mf4_analyzer.acquisition_capture.health",
    "mf4_analyzer.acquisition_capture.ring_buffer",
    "mf4_analyzer.acquisition_capture.backends",
    "mf4_analyzer.acquisition_capture.controller",
    "mf4_analyzer.acquisition_capture.writer",
    "mf4_analyzer.acquisition_capture.session",
    "mf4_analyzer.acquisition_capture.search",
    "mf4_analyzer.acquisition_capture.a2l_events",
    "mf4_analyzer.acquisition_capture.config_store",
    "mf4_analyzer.acquisition_capture.preflight_estimates",
    "mf4_analyzer.acquisition_ui",
    "mf4_analyzer.acquisition_ui.main_window",
    "mf4_analyzer.acquisition_ui.state",
    "mf4_analyzer.acquisition_ui.review_modal",
    "mf4_analyzer.acquisition_ui.settings_dialog",
    "mf4_analyzer.acquisition_ui.history_tab",
    "mf4_analyzer.acquisition_ui.replay_tab"
)
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
    "--icon", $AppIcon,
    "--distpath", $DistDir,
    "--workpath", $WorkDir,
    "--specpath", $SpecDir,
    "--add-data", $AddDataStyle,
    "--add-data", $AddDataIcons,
    "--add-data", $AddDataVendorPyxcp,
    "--runtime-hook", $RuntimeHookPyxcp,
    "--exclude-module", "pyxcp",
    "--collect-submodules", "mf4_analyzer.acquisition_ui.widgets",
    "--collect-all", "qtawesome",
    "--collect-all", "asammdf"
)
foreach ($HiddenImport in $HiddenImports) {
    $PyInstallerArgs += @("--hidden-import", $HiddenImport)
}
$PyInstallerArgs += $EntryScript

& $VenvPython @PyInstallerArgs

if (-not (Test-Path $ExePath)) {
    throw "Build finished but exe was not found: $ExePath"
}

Write-Step "Build output"
Write-Host "Folder: $OutputDir"
Write-Host "Exe:    $ExePath"
Write-Host "Run:    $ExePath"
