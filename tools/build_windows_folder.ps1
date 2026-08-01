param(
    [string]$Version = "7.9.1",
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
$env:MPLBACKEND = "Agg"

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
$RuntimeDependencyTool = Join-Path $PSScriptRoot "windows_runtime_dependencies.py"
$MatplotlibContractTool = Join-Path $PSScriptRoot "matplotlib_frozen_contract.py"
$BatchRenderSmokeTool = Join-Path $PSScriptRoot "verify_frozen_batch_render.py"
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
$BuildEvidenceDir = Join-Path $RepoRoot ".state\build-evidence"
# Default output: dist\TraceLab7.9.1\TraceLab7.9.1.exe (override with -Version or -AppName)

foreach ($RequiredPath in @($EntryScript, $Requirements, $AcquisitionRequirements, $RuntimeVerifier, $StyleQss, $RuntimeHookPyxcp, $RuntimeDependencyTool, $MatplotlibContractTool, $BatchRenderSmokeTool)) {
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

New-Item -ItemType Directory -Force -Path $EvidenceDir, $BuildEvidenceDir | Out-Null
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

Write-Step "Verifying frozen import dependency contract"
& $VenvPython $RuntimeDependencyTool --verify --require-installed --requirements $Requirements --build-script $PSCommandPath
if ($LASTEXITCODE -ne 0) {
    throw "Frozen import dependency contract failed"
}
$RuntimeDependencyArgsJson = & $VenvPython $RuntimeDependencyTool --pyinstaller-args-json --flavor full
if ($LASTEXITCODE -ne 0) {
    throw "Could not resolve frozen import dependency arguments"
}
try {
    $RuntimeDependencyArgs = @($RuntimeDependencyArgsJson | ConvertFrom-Json)
} catch {
    throw "Frozen import dependency arguments were not valid JSON: $_"
}
$MatplotlibContractJson = & $VenvPython $MatplotlibContractTool --pyinstaller-excludes-json
if ($LASTEXITCODE -ne 0) {
    throw "Could not resolve Matplotlib frozen packaging contract"
}
try {
    $MatplotlibContract = $MatplotlibContractJson | ConvertFrom-Json
    $MatplotlibExcludedModules = @($MatplotlibContract.excluded_modules)
} catch {
    throw "Matplotlib frozen packaging contract was not valid JSON: $_"
}

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
$PyxcpMetadata = Join-Path $VendorPyxcpDir "pyxcp-0.29.14.dist-info"
foreach ($RequiredVendorPath in @($PyxcpPackage, $PyxcpMetadata)) {
    if (-not (Test-Path $RequiredVendorPath)) {
        throw "Pinned pyxcp vendor closure is incomplete: $RequiredVendorPath"
    }
}

if (Test-Path $VendorPya2lDir) {
    Remove-Item -Recurse -Force $VendorPya2lDir
}
New-Item -ItemType Directory -Force -Path $VendorPya2lDir | Out-Null
# Windows PowerShell 5.1 drops embedded double-quotes when building a native
# command line, so importlib.metadata.version("pya2ldb") would reach python as
# version(pya2ldb) -> NameError. Single-quote the package name so the arg
# survives both Windows PowerShell 5.1 and PowerShell 7.
$Pya2lVersionScript = @'
import importlib.metadata
print(importlib.metadata.version('pya2ldb'))
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
    # pyxcp/pya2l are --exclude-module (vendored), so PyInstaller cannot see
    # their import closure and does not auto-collect stdlib modules that ONLY
    # that closure imports. Verified against PYZ-00.toc + base_library.zip that
    # exactly these are missing yet needed by the frozen import/parse probes:
    #   logging.config / logging.handlers -> pyxcp 0.29.14's ``rich`` dependency
    #   timeit                            -> pya2l's SQLAlchemy dependency
    # Without them the frozen probes fail with "No module named '<name>'".
    "logging.config",
    "logging.handlers",
    "timeit",
    "mf4_analyzer.ui_kit",
    "mf4_analyzer.ui_kit.fonts",
    "mf4_analyzer.ui_kit.icons",
    "mf4_analyzer.ui_kit.stylesheet",
    "mf4_analyzer.ui_kit.widgets.searchable_combo",
    "mf4_analyzer.ui",
    "mf4_analyzer.ui.main_window",
    "mf4_analyzer.ui.pg_canvases",
    "mf4_analyzer.io.importer_runtime_smoke",
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
# Both the Analyzer AND the acquisition packages only import QtWidgets/QtCore/
# QtGui — verified by grep across every .py (acquisition_ui widgets included).
# --collect-submodules pyqtgraph otherwise drags in pyqtgraph's alternate-Qt-
# backend submodules, which import a pile of Qt modules nothing here uses
# (biggest win: dropping QtQml/QtQuick removes the ~20 MB qml tree). KEEP
# QtOpenGL (pyqtgraph GL render), QtSvg (icons) and QtPrintSupport (pyqtgraph
# export) — pyqtgraph imports them INDIRECTLY, so they never appear in an
# app-code grep; excluding them would break rendering. QtNetwork is
# deliberately NOT excluded (pyqtgraph remote view may import it; ~1-2 MB, not
# worth the risk). Re-verify chart curves + icons render in the packaged exe.
$UnusedQtModules = @(
    "PyQt5.QtWebEngine",
    "PyQt5.QtWebEngineCore",
    "PyQt5.QtWebEngineWidgets",
    "PyQt5.QtQml",
    "PyQt5.QtQuick",
    "PyQt5.QtQuickWidgets",
    "PyQt5.QtMultimedia",
    "PyQt5.QtMultimediaWidgets",
    "PyQt5.QtSql",
    "PyQt5.QtBluetooth",
    "PyQt5.QtNfc",
    "PyQt5.QtPositioning",
    "PyQt5.QtSensors",
    "PyQt5.QtSerialPort",
    "PyQt5.QtWebSockets",
    "PyQt5.QtWebChannel",
    "PyQt5.QtCharts",
    "PyQt5.QtDataVisualization",
    "PyQt5.QtDesigner",
    "PyQt5.QtHelp",
    "PyQt5.QtTest",
    "PyQt5.QtXmlPatterns",
    "PyQt5.Qt3DCore",
    "PyQt5.Qt3DRender",
    "PyQt5.Qt3DInput",
    "PyQt5.Qt3DLogic",
    "PyQt5.Qt3DAnimation",
    "PyQt5.Qt3DExtras"
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
    "--collect-submodules", "mf4_analyzer.acquisition_ui.widgets",
    "--collect-submodules", "pyqtgraph",
    "--collect-all", "qtawesome"
)
$PyInstallerArgs += $RuntimeDependencyArgs
foreach ($HiddenImport in $HiddenImports) {
    $PyInstallerArgs += @("--hidden-import", $HiddenImport)
}
foreach ($QtModule in $UnusedQtModules) {
    $PyInstallerArgs += @("--exclude-module", $QtModule)
}
foreach ($MatplotlibModule in $MatplotlibExcludedModules) {
    $PyInstallerArgs += @("--exclude-module", $MatplotlibModule)
}
$PyInstallerArgs += $EntryScript

$MatplotlibPruneEvidence = Join-Path $BuildEvidenceDir "$AppName-matplotlib-prune.json"
$BatchRenderSmokeEvidence = Join-Path $BuildEvidenceDir "$AppName-batch-render-smoke.json"
foreach ($StaleEvidencePath in @($MatplotlibPruneEvidence, $BatchRenderSmokeEvidence)) {
    if (Test-Path -LiteralPath $StaleEvidencePath) {
        Remove-Item -LiteralPath $StaleEvidencePath -Force
    }
}
& $VenvPython @PyInstallerArgs
$PyInstallerExitCode = $LASTEXITCODE
if ($PyInstallerExitCode -ne 0) {
    throw "PyInstaller failed with exit code $PyInstallerExitCode"
}

if (-not (Test-Path $ExePath)) {
    throw "Build finished but exe was not found: $ExePath"
}

Write-Step "Pruning collected Matplotlib data"
& $VenvPython $MatplotlibContractTool `
    --prune-internal (Join-Path $OutputDir "_internal") `
    --evidence-json $MatplotlibPruneEvidence
if ($LASTEXITCODE -ne 0) {
    throw "Matplotlib frozen-data pruning failed"
}

# PyQt5 bundles an old MSVC runtime at Qt5\bin\MSVCP140.dll (~14.26.28720.3), and
# PyInstaller's PyQt5 hook puts that dir on the process DLL search path for EVERY
# invocation of the exe -- including the Qt-free A2L parser / pya2l probe children.
# pya2l's native a2lparser_ext.pyd is built against a newer msvcp140 and access-
# violates (0xC0000005) when it binds to 14.26. Overwrite Qt's copy with the build
# machine's newer system runtime so the frozen pya2l/A2L imports load a compatible
# msvcp140. Verified: without this the packaged A2L parse child crashes with
# 0xC0000005 (faulting module MSVCP140.dll 14.26.28720.3).
$QtBinDir = Join-Path $OutputDir "_internal\PyQt5\Qt5\bin"
foreach ($dllName in @("MSVCP140.dll", "MSVCP140_1.dll")) {
    $sysDll = Join-Path $env:WINDIR "System32\$dllName"
    $qtDll = Join-Path $QtBinDir $dllName
    if ((Test-Path $sysDll) -and (Test-Path $qtDll)) {
        $sysVer = [version]((Get-Item $sysDll).VersionInfo.FileVersion.Split(' ')[0])
        $qtVer = [version]((Get-Item $qtDll).VersionInfo.FileVersion.Split(' ')[0])
        if ($sysVer -gt $qtVer) {
            Copy-Item -LiteralPath $sysDll -Destination $qtDll -Force
            Write-Host "Replaced bundled $dllName ($qtVer) with system $sysVer to fix pya2l native crash"
        }
    }
}

Write-Step "Verifying frozen batch rendering (4 kinds x 3 formats)"
& $VenvPython $BatchRenderSmokeTool --exe $ExePath --evidence-json $BatchRenderSmokeEvidence
if ($LASTEXITCODE -ne 0) {
    throw "Frozen batch render smoke failed; see $BatchRenderSmokeEvidence"
}

# Warm the freshly-built exe once: its first launch pays a Windows Defender scan
# and a cold load of the 500 MB+ _internal tree, which can exceed the smoke's
# per-probe subprocess timeout. Running it once here (result discarded) means the
# smoke's probe children below run against a warm, already-scanned binary.
& $ExePath --pyxcp-import-probe-child | Out-Null

$PackagedSmokeJson = Join-Path $EvidenceDir "packaged-runtime-smoke.json"
# Stale evidence must not mask a crash that never writes fresh JSON.
Remove-Item $PackagedSmokeJson -Force -ErrorAction SilentlyContinue
# The packaged exe is --windowed (GUI subsystem); PowerShell's call operator does
# NOT reliably surface its exit code (it reports 0 even when the app exits 2), so
# the old `$LASTEXITCODE` check silently shipped broken packages. Launch via
# Start-Process -Wait for a real exit code and gate on the evidence JSON's `ok`
# flag, which runtime_smoke.run always writes.
$smoke = Start-Process -FilePath $ExePath `
    -ArgumentList "--acquisition-runtime-smoke --json `"$PackagedSmokeJson`"" `
    -Wait -PassThru -NoNewWindow
$smokeOk = $false
if (Test-Path $PackagedSmokeJson) {
    try { $smokeOk = [bool]((Get-Content -Raw $PackagedSmokeJson | ConvertFrom-Json).ok) } catch { $smokeOk = $false }
}
if (-not $smokeOk) {
    throw "Packaged Vector/XCP runtime smoke failed (exe exit=$($smoke.ExitCode); see $PackagedSmokeJson)"
}

Write-Step "Build output"
Write-Host "Folder: $OutputDir"
Write-Host "Exe:    $ExePath"
Write-Host "Run:    $ExePath"
