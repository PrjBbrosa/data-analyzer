param(
    [string]$Version = "7.5",
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
$AcquisitionRequirements = Join-Path $RepoRoot "requirements-windows-acquisition.txt"
$RuntimeVerifier = Join-Path $RepoRoot "scripts\verify_windows_acquisition_runtime.py"
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
$VendorPya2lDir = Join-Path $WorkDir "_vendor_pya2l"
$OutputDir = Join-Path $DistDir $AppName
$ExePath = Join-Path $OutputDir "$AppName.exe"
$EvidenceDir = Join-Path $RepoRoot "docs\analyzer\acquisition\evidence\vector-xcp"
# Default output: dist\TraceLab7.5\TraceLab7.5.exe (override with -Version or -AppName)

foreach ($RequiredPath in @($EntryScript, $Requirements, $AcquisitionRequirements, $RuntimeVerifier, $StyleQss, $RuntimeHookPyxcp)) {
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
    & $VenvPython -m pip install -r $AcquisitionRequirements
    & $VenvPython -m pip install --upgrade pyinstaller qtawesome
}

New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
& $VenvPython $RuntimeVerifier --json (Join-Path $EvidenceDir "build-api-contract.json")
if ($LASTEXITCODE -ne 0) { throw "Pinned Vector/XCP runtime contract failed before packaging" }

if (-not $KeepPrevious) {
    foreach ($PathToRemove in @($OutputDir, $WorkDir, $SpecDir)) {
        if (Test-Path $PathToRemove) {
            Remove-Item -Recurse -Force $PathToRemove
        }
    }
}

New-Item -ItemType Directory -Force -Path $DistDir, $WorkDir, $SpecDir | Out-Null

# pyxcp and pya2l trigger 0xC0000005-class failures when PyInstaller's
# analysis phase imports their native pieces. Vendor them at build time and
# exclude them from analysis; the runtime hook puts the vendor dirs on
# sys.path before any acquisition code runs. See
# docs/lessons-learned/codex-windows-native-import-guard.md.
Write-Step "Vendoring native acquisition packages (avoid analysis-time imports)"
if (Test-Path $VendorPyxcpDir) {
    Remove-Item -Recurse -Force $VendorPyxcpDir
}
New-Item -ItemType Directory -Force -Path $VendorPyxcpDir | Out-Null
# Install the exact acquisition requirement set into one self-contained target.
# Unlike copying only ``pyxcp/``, pip --target retains pyxcp's dist-info (needed
# by importlib.metadata.version) and resolves its runtime dependency closure.
& $VenvPython -m pip install --disable-pip-version-check --upgrade --target $VendorPyxcpDir -r $AcquisitionRequirements
if ($LASTEXITCODE -ne 0) {
    throw "Failed to vendor pinned Vector/XCP requirements"
}
$PyxcpPackage = Join-Path $VendorPyxcpDir "pyxcp"
$PyxcpMetadata = Join-Path $VendorPyxcpDir "pyxcp-0.29.10.dist-info"
foreach ($RequiredVendorPath in @($PyxcpPackage, $PyxcpMetadata)) {
    if (-not (Test-Path $RequiredVendorPath)) {
        throw "Pinned pyxcp vendor closure is incomplete: $RequiredVendorPath"
    }
}

if (Test-Path $VendorPya2lDir) {
    Remove-Item -Recurse -Force $VendorPya2lDir
}
New-Item -ItemType Directory -Force -Path $VendorPya2lDir | Out-Null
$Pya2lVersionScript = @'
import importlib.metadata
print(importlib.metadata.version("pya2ldb"))
'@
$Pya2lVersion = (& $VenvPython -c $Pya2lVersionScript).Trim()
if (-not $Pya2lVersion) {
    throw "pya2ldb metadata not found in build venv"
}
$Pya2lRequirement = "pya2ldb==$Pya2lVersion"
& $VenvPython -m pip install --disable-pip-version-check --upgrade --target $VendorPya2lDir $Pya2lRequirement
if ($LASTEXITCODE -ne 0) {
    throw "Failed to vendor exact pya2ldb runtime: $Pya2lRequirement"
}
$Pya2lPackage = Join-Path $VendorPya2lDir "pya2l"
$Pya2lMetadata = Join-Path $VendorPya2lDir "pya2ldb-$Pya2lVersion.dist-info"
foreach ($RequiredVendorPath in @($Pya2lPackage, $Pya2lMetadata)) {
    if (-not (Test-Path $RequiredVendorPath)) {
        throw "Pinned pya2ldb vendor closure is incomplete: $RequiredVendorPath"
    }
}

Write-Step "Building folder-style exe with PyInstaller"
$AddDataStyle = "$StyleQss;mf4_analyzer\ui_kit"
$AddDataIcons = "$IconsDir;assets\icons"
$BrandingDir = Join-Path $RepoRoot "assets\branding"
$AddDataBranding = "$BrandingDir;assets\branding"
$AddDataVendorPyxcp = "$VendorPyxcpDir;_vendor_pyxcp"
$AddDataVendorPya2l = "$VendorPya2lDir;_vendor_pya2l"
# Help docs (panel guides + software manual) are integrated into the app and
# opened in the browser from inside the bundle, so they ship INSIDE the package
# (no longer copied next to the exe). help_dir() resolves to
# _MEIPASS\mf4_analyzer\help under the frozen build.
$HelpDir = Join-Path $RepoRoot "mf4_analyzer\help"
$AddDataHelp = "$HelpDir;mf4_analyzer\help"
$HiddenImports = @(
    "mf4_analyzer.ui_kit",
    "mf4_analyzer.ui_kit.fonts",
    "mf4_analyzer.ui_kit.icons",
    "mf4_analyzer.ui_kit.stylesheet",
    "mf4_analyzer.ui_kit.widgets.searchable_combo",
    "mf4_analyzer.ui",
    "mf4_analyzer.ui.main_window",
    "mf4_analyzer.ui.pg_canvases",
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
    # --noupx: UPX-compressing the bundled Qt5 GL/render DLLs is a known cause
    # of "works from source, breaks when frozen" rendering faults. The GPU
    # render toggle blanks the chart curves ONLY in the packaged app, while the
    # GL diagnostic proves the frozen build gets the SAME desktop GL 4.6 backend
    # as source (AA_UseDesktopOpenGL on, openGLModuleType LibGL, isOpenGLES
    # False). Same backend + works-unpacked/breaks-packed ⇒ the binaries are the
    # suspect → ship Qt/GL DLLs byte-intact. Disk grows; correctness wins.
    "--noupx",
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
    "--add-data", $AddDataBranding,
    "--add-data", $AddDataVendorPyxcp,
    "--add-data", $AddDataVendorPya2l,
    "--add-data", $AddDataHelp,
    "--runtime-hook", $RuntimeHookPyxcp,
    "--exclude-module", "pyxcp",
    "--exclude-module", "pya2l",
    # matplotlib + scipy were dropped from the app (matplotlib->pyqtgraph,
    # scipy->numpy windows). --collect-submodules pyqtgraph below pulls in
    # pyqtgraph's Matplotlib* submodules (which import matplotlib) and its
    # optional scipy use, so without these excludes PyInstaller follows those
    # imports and re-bundles matplotlib (+ PIL/contourpy/kiwisolver/cycler/
    # fontTools) and scipy -- dead weight the app no longer calls. Guarded by
    # tests/test_windows_build_script.py.
    "--exclude-module", "matplotlib",
    "--exclude-module", "scipy",
    "--collect-submodules", "mf4_analyzer.acquisition_ui.widgets",
    "--collect-submodules", "pyqtgraph",
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

& $ExePath --acquisition-runtime-smoke --json (Join-Path $EvidenceDir "packaged-runtime-smoke.json")
if ($LASTEXITCODE -ne 0) { throw "Packaged Vector/XCP runtime smoke failed" }

Write-Step "Build output"
Write-Host "Folder: $OutputDir"
Write-Host "Exe:    $ExePath"
Write-Host "Run:    $ExePath"
