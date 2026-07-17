param(
    [string]$Version = "7.6",
    [string]$AppName = "",
    [switch]$Console,
    [switch]$SkipInstall,
    [switch]$KeepPrevious
)

# Analyzer-only ("lite") Windows build.
#
# This is tools/build_windows_folder.ps1 with the entire acquisition packaging
# path removed: no pyxcp/pya2l vendoring, no runtime hook, no MSVCP140 swap, no
# acquisition runtime smoke, and none of the acquisition_ui / acquisition_capture
# hidden imports. Because the cockpit is imported lazily inside
# MainWindow.open_acquisition_cockpit(), PyInstaller's static analysis never
# reaches the acquisition packages — so simply NOT listing them as hidden
# imports keeps the acquisition source, the acquisition_ui widget tree, and the
# acquisition-only native deps (pyxcp / pya2l) entirely out of the bundle. The
# cockpit menu entry degrades gracefully (a "分析版不含采集" dialog) in this build.
#
# python-can / cantools are intentionally NOT excluded: the Analyzer itself uses
# them to import BLF (Vector CAN log) files.

if (-not $AppName) {
    $AppName = "TraceLabAnalyzer$Version"
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
$VenvDir = Join-Path $RepoRoot ".venv-build-win"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$DistDir = Join-Path $RepoRoot "dist"
$WorkDir = Join-Path $RepoRoot "build\pyinstaller-lite"
$SpecDir = Join-Path $RepoRoot "build\spec-lite"
$OutputDir = Join-Path $DistDir $AppName
$ExePath = Join-Path $OutputDir "$AppName.exe"
# Default output: dist\TraceLabAnalyzer7.6\TraceLabAnalyzer7.6.exe
# (override with -Version or -AppName)

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
    # Analyzer-only: base requirements only (no acquisition extras installed).
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

Write-Step "Building analyzer-only folder-style exe with PyInstaller"
$AddDataStyle = "$StyleQss;mf4_analyzer\ui_kit"
$AddDataIcons = "$IconsDir;assets\icons"
$BrandingDir = Join-Path $RepoRoot "assets\branding"
$AddDataBranding = "$BrandingDir;assets\branding"
# Help docs (panel guides + software manual) ship INSIDE the package; help_dir()
# resolves to _MEIPASS\mf4_analyzer\help under the frozen build.
$HelpDir = Join-Path $RepoRoot "mf4_analyzer\help"
$AddDataHelp = "$HelpDir;mf4_analyzer\help"
$HiddenImports = @(
    # DataLoader imports npTDMS lazily, so add it explicitly for frozen builds.
    "nptdms",
    "mf4_analyzer.ui_kit",
    "mf4_analyzer.ui_kit.fonts",
    "mf4_analyzer.ui_kit.icons",
    "mf4_analyzer.ui_kit.stylesheet",
    "mf4_analyzer.ui_kit.widgets.searchable_combo",
    "mf4_analyzer.ui",
    "mf4_analyzer.ui.main_window",
    "mf4_analyzer.ui.pg_canvases"
    # NOTE: no mf4_analyzer.acquisition_capture.* / acquisition_ui.* here — that
    # omission is what makes this the lite build. Likewise the full build's
    # logging.config / logging.handlers / timeit hidden imports are gone: they
    # existed only to satisfy pyxcp's rich / pya2l's SQLAlchemy closures.
)
# The whole repo (Analyzer + acquisition) only imports QtWidgets/QtCore/QtGui —
# verified by grep across every .py. But --collect-submodules pyqtgraph (below)
# drags in pyqtgraph's alternate-Qt-backend submodules, which import a pile of
# Qt modules nothing here uses (biggest win: dropping QtQml/QtQuick removes the
# ~20 MB qml tree). KEEP QtOpenGL (pyqtgraph GL render), QtSvg (icons) and
# QtPrintSupport (pyqtgraph export) — pyqtgraph imports them INDIRECTLY, so they
# never show up in an app-code grep; excluding them would break rendering.
# QtNetwork is deliberately NOT excluded: pyqtgraph's remote view could import
# it, and it costs only ~1-2 MB — not worth the risk. Re-verify chart curves +
# icons render in the packaged exe after any change here.
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
    # --noupx: UPX-compressing bundled Qt5 GL/render DLLs is a known cause of
    # "works from source, breaks when frozen" rendering faults. Ship Qt/GL DLLs
    # byte-intact; disk grows, correctness wins.
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
    "--add-data", $AddDataHelp,
    # matplotlib + scipy were dropped from the app (matplotlib->pyqtgraph,
    # scipy->numpy windows); --collect-submodules pyqtgraph would otherwise drag
    # them back in via pyqtgraph's Matplotlib* submodules.
    "--exclude-module", "matplotlib",
    "--exclude-module", "scipy",
    # Belt-and-suspenders: keep the acquisition packages and their native-only
    # deps out even if some indirect reference appears. The Analyzer never needs
    # them at runtime (cockpit is lazy-imported and guarded).
    "--exclude-module", "mf4_analyzer.acquisition",
    "--exclude-module", "mf4_analyzer.acquisition_ui",
    "--exclude-module", "mf4_analyzer.acquisition_capture",
    "--exclude-module", "pyxcp",
    "--exclude-module", "pya2l",
    "--collect-submodules", "pyqtgraph",
    "--collect-all", "qtawesome",
    "--collect-all", "asammdf"
)
foreach ($HiddenImport in $HiddenImports) {
    $PyInstallerArgs += @("--hidden-import", $HiddenImport)
}
foreach ($QtModule in $UnusedQtModules) {
    $PyInstallerArgs += @("--exclude-module", $QtModule)
}
$PyInstallerArgs += $EntryScript

& $VenvPython @PyInstallerArgs

if (-not (Test-Path $ExePath)) {
    throw "Build finished but exe was not found: $ExePath"
}

Write-Step "Build output"
$SizeBytes = (Get-ChildItem -Recurse -Force $OutputDir | Measure-Object -Property Length -Sum).Sum
$SizeMB = [math]::Round($SizeBytes / 1MB, 1)
Write-Host "Folder: $OutputDir"
Write-Host "Exe:    $ExePath"
Write-Host "Size:   $SizeMB MB (analyzer-only, acquisition excluded)"
Write-Host "Run:    $ExePath"
