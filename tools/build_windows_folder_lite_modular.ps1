param(
    [string]$Version = "8.3.1",
    [string]$AppName = "",
    [string]$Flavor = "lite",
    [string]$DependencyProfile = "modular",
    [string]$ManagerSource = "",
    [switch]$Console,
    [switch]$SkipInstall,
    [switch]$KeepPrevious
)

# Experimental analyzer-only ("lite") + modular Windows build.
#
# Copy of tools/build_windows_folder_lite.ps1 for VM freeze trials. Do not use
# this as the default product packager. The original lite/full scripts remain
# bundled and are not modified by this path.
#
# Differences from the lite product builder:
# - flavor and dependency_profile are separate parameters. This experimental
#   script only accepts lite+modular; unsupported combinations error out.
#   The product lite/full scripts remain bundled and are not modified.
# - Requests --profile modular so av/scipy/h5py are excluded from Analysis/PYZ
#   (dropping --collect-all is not enough; asammdf can re-pull scipy/h5py).
# - Writes a separate AppName, workpath, specpath, and evidence tree so it
#   cannot wipe dist\TraceLabAnalyzer<version>\.
# - Does not reuse the Lite SciPy OpenBLAS file-delete; a leftover scipy.libs
#   is a leak, not something to prune into a false success.
# - Emits core.json / core-files.json, content-addressed component ZIPs,
#   licenses, dependency lists, native-identity audit, and a tested-manager
#   copy step (placeholder when no Windows installer.exe is supplied).
# - Importer gates are split: base expected-missing vs installed-available.
#   A permanent skip is not recorded as success. Frozen WAV/MP4 reads are
#   not claimed without a frozen child.
#
# python-can / cantools are intentionally NOT excluded: the Analyzer itself uses
# them to import BLF (Vector CAN log) files.
# Every attempt keeps build.log, environment/argument output, PyInstaller
# diagnostics and render-child logs/images under .state/build-evidence/lite-modular/.
# The final console line prints the unique run directory; share that whole
# directory when reporting a build failure (logs may contain local paths).

if (-not $AppName) {
    $AppName = "TraceLabAnalyzer${Version}-modular"
}

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step {
    param([string]$Message)
    $script:BuildStage = $Message
    Write-Host ""
    Write-Host "==> [$(Get-Date -Format o)] $Message" -ForegroundColor Cyan
}

function Invoke-LoggedNative {
    param([string]$Executable, [string[]]$Arguments, [switch]$CaptureStdout)
    # Windows PowerShell 5.1 turns redirected native stderr into ErrorRecords.
    # stderr is not failure (pip/PyInstaller use it for progress); exit code is.
    $ErrorActionPreference = "Continue"
    $PSNativeCommandUseErrorActionPreference = $false
    $nativeCommand = Get-Command $Executable -CommandType Application -ErrorAction Stop
    Write-Host "Command: $Executable $($Arguments | ConvertTo-Json -Compress)"
    if ($CaptureStdout) {
        # Keep machine-readable JSON separate from diagnostics.
        $stderrPath = Join-Path $BuildEvidenceDir "dependency-args-stderr.log"
        $stdout = & $nativeCommand.Source @Arguments 2> $stderrPath
        $nativeExitCode = $LASTEXITCODE
        Get-Content -LiteralPath $stderrPath -ErrorAction Stop | ForEach-Object { Write-Host $_ }
        $stdout | ForEach-Object { Write-Host $_ }
    } else {
        & $nativeCommand.Source @Arguments 2>&1 | ForEach-Object { Write-Host $_.ToString() }
        $nativeExitCode = $LASTEXITCODE
    }
    Write-Host "Native exit code: $nativeExitCode"
    if ($nativeExitCode -ne 0) {
        throw "Native command failed with exit code ${nativeExitCode}: $Executable"
    }
    if ($CaptureStdout) { return $stdout }
}

function ConvertTo-Win32ArgumentList {
    param([string[]]$Arguments)
    $parts = @(foreach ($Argument in @($Arguments)) {
        if ($null -eq $Argument) { continue }
        $text = [string]$Argument
        if ($text -notmatch '[ \t"]') {
            $text
        } else {
            '"' + ($text -replace '"', '\"') + '"'
        }
    })
    return [string]($parts -join ' ')
}

function Stop-OwnedProcessTree {
    param([System.Diagnostics.Process]$Process)
    # Only descendants of the process this script started. Do not kill user
    # TraceLab / unrelated python processes.
    if ($null -eq $Process) { return }
    $rootId = $Process.Id
    $owned = New-Object System.Collections.Generic.List[int]
    [void]$owned.Add($rootId)
    try {
        $pending = New-Object System.Collections.Generic.Queue[int]
        $pending.Enqueue($rootId)
        while ($pending.Count -gt 0) {
            $parentId = $pending.Dequeue()
            $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$parentId" -ErrorAction SilentlyContinue)
            foreach ($child in @($children)) {
                if ($null -eq $child) { continue }
                $childId = [int]$child.ProcessId
                if ($owned.Contains($childId)) { continue }
                [void]$owned.Add($childId)
                $pending.Enqueue($childId)
            }
        }
    } catch {
        try {
            $children = @(Get-WmiObject Win32_Process -Filter "ParentProcessId=$rootId" -ErrorAction SilentlyContinue)
            foreach ($child in @($children)) {
                if ($null -eq $child) { continue }
                $childId = [int]$child.ProcessId
                if ($owned.Contains($childId)) { continue }
                [void]$owned.Add($childId)
            }
        } catch { }
    }
    $descendantRows = @(foreach ($procId in $owned) {
        if ($procId -eq $rootId) { continue }
        [pscustomobject]@{ ProcessId = $procId }
    })
    foreach ($row in $descendantRows) {
        try { Stop-Process -Id $row.ProcessId -Force -ErrorAction SilentlyContinue } catch { }
    }
    try { $Process.Kill() } catch { }
}

function Wait-RedirectedOutput {
    param($Task, [int]$TimeoutMs = 2000)
    if ($null -eq $Task) { return "" }
    try {
        if ($Task.Wait($TimeoutMs)) {
            return [string]$Task.Result
        }
    } catch { }
    return ""
}

function Get-PostCheckRecord {
    param([string]$Name)
    foreach ($item in @($script:PostCheckResults)) {
        if ($item.Name -eq $Name) { return $item }
    }
    return $null
}

function Get-PostCheckStatus {
    param([string]$Name)
    $item = Get-PostCheckRecord $Name
    if ($null -eq $item) { return "not_run" }
    return [string]$item.Status
}

function Test-AllPostChecksPassed {
    foreach ($name in @("offscreen", "windows", "importer-base-missing")) {
        if ((Get-PostCheckStatus $name) -ne "passed") { return $false }
    }
    return $true
}

function Write-PostCheckSummary {
    $exeGenerated = [bool]$script:ExeGenerated
    $off = Get-PostCheckStatus "offscreen"
    $win = Get-PostCheckStatus "windows"
    $impBase = Get-PostCheckStatus "importer-base-missing"
    $impInstalled = Get-PostCheckStatus "importer-installed-contract"
    $impFallback = Get-PostCheckStatus "importer-fallback-contract"
    Write-Host "EXE generated: $exeGenerated"
    Write-Host "offscreen: $off"
    Write-Host "windows: $win"
    Write-Host "importer-base-missing: $impBase"
    Write-Host "importer-installed-contract: $impInstalled"
    Write-Host "importer-fallback-contract: $impFallback"
    Write-Host "frozen WAV/MP4/MAT: not_run (not claimed as success without a frozen child read)"
}

function Invoke-IndependentPostCheck {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Executable,
        [string[]]$Arguments,
        [int]$TimeoutSeconds = 300
    )
    # Independent post-EXE checks must keep going after an ordinary failure.
    # Do not throw here; the caller aggregates exit codes once.
    $ErrorActionPreference = "Continue"
    $PSNativeCommandUseErrorActionPreference = $false
    $record = New-Object psobject -Property @{
        Name = $Name
        Status = "failed"
        ExitCode = $null
        TimedOut = $false
        Error = ""
    }
    $process = $null
    try {
        $nativeCommand = Get-Command $Executable -CommandType Application -ErrorAction Stop
        Write-Host "Post-check ${Name}: $Executable $($Arguments | ConvertTo-Json -Compress)"
        $startInfo = New-Object System.Diagnostics.ProcessStartInfo
        $startInfo.FileName = $nativeCommand.Source
        $startInfo.Arguments = ConvertTo-Win32ArgumentList -Arguments $Arguments
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $startInfo
        [void]$process.Start()
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            Stop-OwnedProcessTree -Process $process
            [void]$process.WaitForExit(10000)
            $record.TimedOut = $true
            $record.Status = "timeout"
            $record.ExitCode = -1
            Write-Host "Post-check ${Name} timed out after ${TimeoutSeconds}s; process terminated"
        } else {
            $record.ExitCode = [int]$process.ExitCode
            if ($record.ExitCode -eq 0) {
                $record.Status = "passed"
            } else {
                $record.Status = "failed"
            }
            Write-Host "Post-check ${Name} exit code: $($record.ExitCode)"
        }
        # Bound the redirected-stream drain. Never wait indefinitely on
        # Task.Result after a timeout or a stuck child.
        $outText = Wait-RedirectedOutput -Task $stdoutTask -TimeoutMs 2000
        $errText = Wait-RedirectedOutput -Task $stderrTask -TimeoutMs 2000
        if ($outText) { Write-Host $outText }
        if ($errText) { Write-Host $errText }
    } catch {
        $record.Status = "failed"
        $record.Error = "$_"
        Write-Host "Post-check ${Name} error: $_"
        Write-Host "Native exit code: $($record.ExitCode)"
    } finally {
        if ($null -ne $process) { $process.Dispose() }
        [void]$script:PostCheckResults.Add($record)
    }
}

function Invoke-BasePython {
    param([string[]]$Arguments)

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        Invoke-LoggedNative -Executable $pyLauncher.Source -Arguments (@("-3") + $Arguments)
        return
    }

    $python = Get-Command python -ErrorAction Stop
    Invoke-LoggedNative -Executable $python.Source -Arguments $Arguments
}

function Save-BuildDiagnostics {
    # Only archive this attempt's PyInstaller files, never a previous build's.
    if (-not $script:PyInstallerStarted) { return }
    foreach ($DiagnosticPath in @(
        (Join-Path $WorkDir "$AppName\warn-$AppName.txt"),
        (Join-Path $WorkDir "$AppName\xref-$AppName.html"),
        (Join-Path $SpecDir "$AppName.spec")
    )) {
        if ((Test-Path -LiteralPath $DiagnosticPath) -and
            (Get-Item -LiteralPath $DiagnosticPath).LastWriteTime -ge $BuildStartedAt) {
            Copy-Item -LiteralPath $DiagnosticPath -Destination $BuildEvidenceDir -Force
        }
    }
}

if ($env:OS -ne "Windows_NT") {
    Write-Warning "This script is intended to build a Windows .exe from Windows."
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EntryScript = Join-Path $RepoRoot "MF4 Data Analyzer V1.py"
$Requirements = Join-Path $RepoRoot "requirements.txt"
$StyleQss = Join-Path $RepoRoot "mf4_analyzer\ui_kit\style.qss"
$QssIconFallbackDir = Join-Path $RepoRoot "mf4_analyzer\ui_kit\resources"
$IconsDir = Join-Path $RepoRoot "assets\icons"
$AppIcon = Join-Path $IconsDir "tracelab.ico"
$RuntimeDependencyTool = Join-Path $PSScriptRoot "windows_runtime_dependencies.py"
$BundlePolicyTool = Join-Path $PSScriptRoot "windows_bundle_policy.py"
$BatchRenderSmokeTool = Join-Path $PSScriptRoot "verify_frozen_batch_render.py"
$ExtensionBuildTool = Join-Path $PSScriptRoot "build_windows_extensions.py"
$ExtensionVerifyTool = Join-Path $PSScriptRoot "verify_extension_installation.py"
$ExtensionInstallerScript = Join-Path $PSScriptRoot "build_windows_extension_installer.ps1"
$VenvDir = Join-Path $RepoRoot ".venv-build-win"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$DistDir = Join-Path $RepoRoot "dist"
$WorkDir = Join-Path $RepoRoot "build\pyinstaller-lite-modular"
$SpecDir = Join-Path $RepoRoot "build\spec-lite-modular"
$OutputDir = Join-Path $DistDir $AppName
$ExePath = Join-Path $OutputDir "$AppName.exe"
$BuildRunId = "$(Get-Date -Format 'yyyyMMdd-HHmmss-fff')-$([guid]::NewGuid().ToString('N'))"
$BuildEvidenceDir = Join-Path $RepoRoot ".state\build-evidence\lite-modular\$BuildRunId"
$BuildLog = Join-Path $BuildEvidenceDir "build.log"
$BuildStartedAt = Get-Date
$script:BuildStage = "Initializing"
$script:PyInstallerStarted = $false
$script:ExeGenerated = $false
$script:PostCheckResults = New-Object System.Collections.ArrayList
$BuildSucceeded = $false
New-Item -ItemType Directory -Force -Path $BuildEvidenceDir | Out-Null
Start-Transcript -LiteralPath $BuildLog -NoClobber | Out-Host
try {
# Keep the build body in this script's scope; finally closes even failed runs.
Write-Host "Evidence: $BuildEvidenceDir"
Write-Host "Repo: $RepoRoot"
Write-Host "Working directory: $((Get-Location).Path)"
Write-Host "PowerShell: $($PSVersionTable.PSVersion); OS: $([Environment]::OSVersion)"
Write-Host "Version=$Version AppName=$AppName Flavor=$Flavor DependencyProfile=$DependencyProfile Console=$Console SkipInstall=$SkipInstall KeepPrevious=$KeepPrevious ManagerSource=$ManagerSource"
if ($Flavor -ne "lite" -or $DependencyProfile -ne "modular") {
    throw "unsupported frozen delivery combination flavor=$Flavor dependency_profile=$DependencyProfile; first modular release accepts only lite+modular"
}
if (Get-Command git -ErrorAction SilentlyContinue) {
    & git -C $RepoRoot rev-parse HEAD | Out-Host
    & git -C $RepoRoot status --short | Out-Host
}
Copy-Item -LiteralPath $PSCommandPath -Destination $BuildEvidenceDir
# Default output: dist\TraceLabAnalyzer8.3.1-modular\TraceLabAnalyzer8.3.1-modular.exe
# (override with -Version or -AppName). Does not replace dist\TraceLabAnalyzer8.3.1\.

foreach ($RequiredPath in @($EntryScript, $Requirements, $StyleQss, $RuntimeDependencyTool, $BundlePolicyTool, $BatchRenderSmokeTool, $ExtensionBuildTool, $ExtensionVerifyTool, $ExtensionInstallerScript)) {
    if (-not (Test-Path $RequiredPath)) {
        throw "Required file not found: $RequiredPath"
    }
}
Copy-Item -LiteralPath $Requirements -Destination $BuildEvidenceDir

Write-Step "Preparing build environment"
if (-not (Test-Path $VenvPython)) {
    Invoke-BasePython -Arguments @("-m", "venv", $VenvDir)
}

if (-not $SkipInstall) {
    Write-Step "Installing build dependencies"
    Invoke-LoggedNative -Executable $VenvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel")
    # Analyzer-only: base requirements only (no acquisition extras installed).
    Invoke-LoggedNative -Executable $VenvPython -Arguments @("-m", "pip", "install", "-r", $Requirements)
    Invoke-LoggedNative -Executable $VenvPython -Arguments @("-m", "pip", "install", "--upgrade", "pyinstaller", "qtawesome")
}

Write-Step "Recording Python and installed package versions"
Invoke-LoggedNative -Executable $VenvPython -Arguments @("-c", "import sys, platform; print(sys.executable); print(sys.version); print(platform.platform()); print(platform.machine())")
Invoke-LoggedNative -Executable $VenvPython -Arguments @("-m", "pip", "freeze", "--all")

Write-Step "Preparing output directories"
if (-not $KeepPrevious) {
    foreach ($PathToRemove in @($OutputDir, $WorkDir, $SpecDir)) {
        if (Test-Path $PathToRemove) {
            Remove-Item -Recurse -Force $PathToRemove
        }
    }
}

New-Item -ItemType Directory -Force -Path $DistDir, $WorkDir, $SpecDir, $BuildEvidenceDir | Out-Null

Write-Step "Verifying frozen import dependency contract"
Invoke-LoggedNative -Executable $VenvPython -Arguments @($RuntimeDependencyTool, "--verify", "--require-installed", "--requirements", $Requirements, "--build-script", $PSCommandPath)
$RuntimeDependencyArgsJson = Invoke-LoggedNative -Executable $VenvPython -Arguments (@($RuntimeDependencyTool) + ("--pyinstaller-args-json --flavor $Flavor --profile $DependencyProfile" -split " ")) -CaptureStdout
Write-Host "Runtime dependency arguments: $RuntimeDependencyArgsJson"
try {
    # PowerShell 5.1 emits the JSON array as one pipeline object. An outer @()
    # nests it, and Invoke-LoggedNative's [string[]] then joins all flags into
    # one argument. Convert the returned array directly to a flat string[].
    $RuntimeDependencyArgs = [string[]](ConvertFrom-Json -InputObject $RuntimeDependencyArgsJson)
} catch {
    throw "Frozen import dependency arguments were not valid JSON: $_"
}
Write-Step "Building analyzer-only modular folder-style exe with PyInstaller"
$BundlePolicyArgsJson = Invoke-LoggedNative -Executable $VenvPython -Arguments @($BundlePolicyTool, "--pyinstaller-args-json", "--flavor", $Flavor) -CaptureStdout
$BundlePolicyArgs = [string[]](ConvertFrom-Json -InputObject $BundlePolicyArgsJson)
Copy-Item -LiteralPath $BundlePolicyTool -Destination $BuildEvidenceDir
$AddDataStyle = "$StyleQss;mf4_analyzer\ui_kit"
$AddDataQssIconFallbacks = "$QssIconFallbackDir;mf4_analyzer\ui_kit\resources"
$AddDataIcons = "$IconsDir;assets\icons"
$BrandingDir = Join-Path $RepoRoot "assets\branding"
$AddDataBranding = "$BrandingDir;assets\branding"
$WwtTemplateDir = Join-Path $RepoRoot "assets\wwt"
$AddDataWwt = "$WwtTemplateDir;assets\wwt"
# Help docs (panel guides + software manual) ship INSIDE the package; help_dir()
# resolves to _MEIPASS\mf4_analyzer\help under the frozen build.
$HelpDir = Join-Path $RepoRoot "mf4_analyzer\help"
$AddDataHelp = "$HelpDir;mf4_analyzer\help"
$HiddenImports = @(
    "mf4_analyzer.ui_kit",
    "mf4_analyzer.ui_kit.fonts",
    "mf4_analyzer.ui_kit.icons",
    "mf4_analyzer.ui_kit.stylesheet",
    "mf4_analyzer.ui_kit.dialog_geometry",
    "mf4_analyzer.ui_kit.layout_diagnostics",
    "mf4_analyzer.ui_kit.message_dialog",
    "mf4_analyzer.ui_kit.widgets.searchable_combo",
    "mf4_analyzer.ui",
    "mf4_analyzer.ui.layout_probe",
    "mf4_analyzer.ui.main_window",
    "mf4_analyzer.ui.main_window.frf_coordinator",
    "mf4_analyzer.ui.pg_canvases",
    "mf4_analyzer.signal.frf",
    "mf4_analyzer.batch_frf",
    "mf4_analyzer.io.importer_runtime_smoke",
    # WWT export is imported lazily inside the channel-editor handler; name the
    # modules so the frozen build cannot lose the export path.
    "mf4_analyzer.io.wwt_export",
    "mf4_analyzer.io.wwt_display",
    "mf4_analyzer.io.wwt_writer",
    "mf4_analyzer.io.wwt_inplace",
    "mf4_analyzer.io.wwt_quantize"
    # NOTE: no mf4_analyzer.acquisition_capture.* / acquisition_ui.* here — that
    # omission is what makes this the lite build. Likewise the full build's
    # logging.config / logging.handlers / timeit hidden imports are gone: they
    # existed only to satisfy pyxcp's rich / pya2l's SQLAlchemy closures.
)
# Product charts use raster rendering; OpenGL is not enabled. Preserve SVG,
# print/export and network support. The shared policy also checks and removes
# unused native Qt payloads that module exclusions alone do not eliminate.
$UnusedQtModules = @(
    "PyQt5.QtOpenGL",
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
    "--add-data", $AddDataQssIconFallbacks,
    "--add-data", $AddDataIcons,
    "--add-data", $AddDataBranding,
    "--add-data", $AddDataWwt,
    "--add-data", $AddDataHelp,
    # Belt-and-suspenders: keep the acquisition packages and their native-only
    # deps out even if some indirect reference appears. The Analyzer never needs
    # them at runtime (cockpit is lazy-imported and guarded).
    "--exclude-module", "mf4_analyzer.acquisition",
    "--exclude-module", "mf4_analyzer.acquisition_ui",
    "--exclude-module", "mf4_analyzer.acquisition_capture",
    "--exclude-module", "pyxcp",
    "--exclude-module", "pya2l",
    # Product rendering is Qt/pyqtgraph-only.  Keep a stale build environment
    # from reintroducing Matplotlib through PyInstaller's analysis graph.
    "--exclude-module", "matplotlib",
    "--hidden-import", "pyqtgraph",
    "--hidden-import", "qtawesome"
)
$PyInstallerArgs += $RuntimeDependencyArgs
$PyInstallerArgs += $BundlePolicyArgs
foreach ($HiddenImport in $HiddenImports) {
    $PyInstallerArgs += @("--hidden-import", $HiddenImport)
}
foreach ($QtModule in $UnusedQtModules) {
    $PyInstallerArgs += @("--exclude-module", $QtModule)
}
$PyInstallerArgs += $EntryScript

$BatchRenderOffscreenSmokeEvidence = Join-Path $BuildEvidenceDir "$AppName-batch-render-offscreen-smoke.json"
$BatchRenderWindowsSmokeEvidence = Join-Path $BuildEvidenceDir "$AppName-batch-render-windows-smoke.json"
foreach ($StaleEvidencePath in @($BatchRenderOffscreenSmokeEvidence, $BatchRenderWindowsSmokeEvidence)) {
    if (Test-Path -LiteralPath $StaleEvidencePath) {
        Remove-Item -LiteralPath $StaleEvidencePath -Force
    }
}
Write-Host "Python: $VenvPython"
Write-Host "PyInstaller arguments: $($PyInstallerArgs | ConvertTo-Json -Compress)"
$script:PyInstallerStarted = $true
Invoke-LoggedNative -Executable $VenvPython -Arguments $PyInstallerArgs

if (-not (Test-Path $ExePath)) {
    throw "Build finished but exe was not found: $ExePath"
}

Write-Step "Verifying required Qt platform plugins"
$QtPlatformsDir = Join-Path $OutputDir "_internal\PyQt5\Qt5\plugins\platforms"
foreach ($QtPlatformPlugin in @("qoffscreen.dll", "qwindows.dll")) {
    $QtPlatformPluginPath = Join-Path $QtPlatformsDir $QtPlatformPlugin
    if (-not (Test-Path -LiteralPath $QtPlatformPluginPath)) {
        throw "Required Qt platform plugin missing: $QtPlatformPluginPath"
    }
}

# Modular base must not contain optional importer trees. Do not delete them to
# fake a split: leftover av/scipy/h5py here means Analysis still bundled them.
Write-Step "Rejecting optional importer trees in the modular base"
$InternalDir = Join-Path $OutputDir "_internal"
$OptionalLeakNames = @(
    "av",
    "av.libs",
    "scipy",
    "scipy.libs",
    "h5py",
    "h5py.libs",
    "hdf5storage"
)
$OptionalLeaks = @()
foreach ($Name in $OptionalLeakNames) {
    $Candidate = Join-Path $InternalDir $Name
    if (Test-Path -LiteralPath $Candidate) {
        $OptionalLeaks += $Candidate
    }
}
if ($OptionalLeaks.Count -ne 0) {
    throw "Modular base leaked optional importer trees: $($OptionalLeaks -join '; ')"
}

Write-Step "Pruning unused bundle payloads"
Invoke-LoggedNative -Executable $VenvPython -Arguments @($BundlePolicyTool, "--flavor", $Flavor, "--exe", $ExePath, "--report", (Join-Path $BuildEvidenceDir "bundle-prune.json"))

Write-Step "Emitting core manifests, component ZIPs, identity audit, and manager copy"
$ExtensionOutputDir = Join-Path $BuildEvidenceDir "extension-delivery"
New-Item -ItemType Directory -Force -Path $ExtensionOutputDir | Out-Null
$SitePackagesJson = Invoke-LoggedNative -Executable $VenvPython -Arguments @("-c", "import json, site; print(json.dumps(site.getsitepackages()))") -CaptureStdout
$SitePackagesList = @(ConvertFrom-Json -InputObject $SitePackagesJson)
$SitePackages = [string]$SitePackagesList[0]
$ExtensionEmitArgs = @(
    $ExtensionBuildTool,
    "--flavor", $Flavor,
    "--profile", $DependencyProfile,
    "--app-root", $OutputDir,
    "--exe-relpath", "$AppName.exe",
    "--site-packages", $SitePackages,
    "--output-dir", $ExtensionOutputDir
)
if ($ManagerSource) {
    $ExtensionEmitArgs += @("--manager-source", $ManagerSource)
} else {
    Write-Host "Manager copy: verified Windows installer.exe not supplied; writing placeholder (no fabricated hash). Independent entry: $ExtensionInstallerScript"
}
Invoke-LoggedNative -Executable $VenvPython -Arguments $ExtensionEmitArgs

$script:ExeGenerated = $true
Write-Step "Verifying frozen batch rendering (independent post-checks)"
Invoke-IndependentPostCheck -Name "offscreen" -Executable $VenvPython -Arguments @($BatchRenderSmokeTool, "--exe", $ExePath, "--platform", "offscreen", "--evidence-json", $BatchRenderOffscreenSmokeEvidence, "--diagnostics-dir", (Join-Path $BuildEvidenceDir "render-offscreen")) -TimeoutSeconds 300
Invoke-IndependentPostCheck -Name "windows" -Executable $VenvPython -Arguments @($BatchRenderSmokeTool, "--exe", $ExePath, "--platform", "windows", "--evidence-json", $BatchRenderWindowsSmokeEvidence, "--diagnostics-dir", (Join-Path $BuildEvidenceDir "render-windows")) -TimeoutSeconds 300
$CoreJson = Join-Path $OutputDir "core.json"
$FirstPackageJson = $null
$PackageJsonCandidates = @(
    foreach ($item in @(Get-ChildItem -LiteralPath (Join-Path $ExtensionOutputDir "staging") -Filter "package.json" -Recurse -ErrorAction SilentlyContinue)) {
        $item.FullName
    }
)
if ($PackageJsonCandidates.Count -ge 1) { $FirstPackageJson = [string]$PackageJsonCandidates[0] }
$BaseMissingEvidence = Join-Path $BuildEvidenceDir "importer-base-missing.json"
$InstalledContractEvidence = Join-Path $BuildEvidenceDir "importer-installed-contract.json"
$FallbackEvidence = Join-Path $BuildEvidenceDir "importer-fallback-contract.json"
Invoke-IndependentPostCheck -Name "importer-base-missing" -Executable $VenvPython -Arguments @($ExtensionVerifyTool, "--mode", "combination-contract", "--core-json", $CoreJson, "--expect-missing", "--app-root", $OutputDir, "--evidence-json", $BaseMissingEvidence) -TimeoutSeconds 60
if ($FirstPackageJson) {
    Invoke-IndependentPostCheck -Name "importer-installed-contract" -Executable $VenvPython -Arguments @($ExtensionVerifyTool, "--mode", "combination-contract", "--core-json", $CoreJson, "--package-json", $FirstPackageJson, "--app-root", $OutputDir, "--evidence-json", $InstalledContractEvidence) -TimeoutSeconds 60
} else {
    Write-Host "importer-installed-contract: not_run (no component package.json; not claimed as WAV/MP4 success)"
}
if ($FirstPackageJson) {
    Invoke-IndependentPostCheck -Name "importer-fallback-contract" -Executable $VenvPython -Arguments @($ExtensionVerifyTool, "--mode", "fallback-contract", "--core-json", $CoreJson, "--remaining-package-json", $FirstPackageJson, "--removed-component", "matlab", "--app-root", $OutputDir, "--evidence-json", $FallbackEvidence) -TimeoutSeconds 60
} else {
    Write-Host "importer-fallback-contract: not_run (no remaining package; not claimed as success)"
}
Write-Host "Not invoking verify_lite_importer_runtime.py: that gate requires frozen av/MAT success and is the bundled Lite path."
Write-Host "frozen importer-base-missing / installed-available child reads: not_run (A1-A15 / four frozen combinations UNKNOWN)"
Write-PostCheckSummary
if (-not (Test-AllPostChecksPassed)) {
    throw "Post-build checks failed; EXE generated; see evidence under $BuildEvidenceDir"
}

Write-Step "Build output"
$SizeBytes = (Get-ChildItem -Recurse -Force $OutputDir | Measure-Object -Property Length -Sum).Sum
$SizeMB = [math]::Round($SizeBytes / 1MB, 1)
Write-Host "Folder: $OutputDir"
Write-Host "Exe:    $ExePath"
Write-Host "Size:   $SizeMB MB (analyzer-only modular base; av/scipy/h5py excluded)"
Write-Host "Run:    $ExePath"
$BuildSucceeded = $true
} catch {
    Write-Host "BUILD FAILED at stage: $script:BuildStage" -ForegroundColor Red
    Write-Host ($_ | Format-List * -Force | Out-String)
    Write-Host $_.ScriptStackTrace
    throw
} finally {
    try {
        Save-BuildDiagnostics
    } catch {
        Write-Warning "Could not archive all PyInstaller diagnostics: $_"
    }
    $BuildElapsed = (Get-Date) - $BuildStartedAt
    Write-PostCheckSummary
    Write-Host "Build succeeded: $BuildSucceeded; elapsed: $BuildElapsed; last stage: $script:BuildStage"
    Write-Host "Full build log: $BuildLog"
    Stop-Transcript | Out-Host
}
