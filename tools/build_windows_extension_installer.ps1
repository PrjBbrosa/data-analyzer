param(
    [string]$ManagerVersion = "1.0.0",
    [string]$AppName = "TraceLabExtensionManager",
    [switch]$Console,
    [switch]$SkipInstall
)

# Independent Windows packager for the TraceLab extension manager.
#
# This is not the analyzer Lite/Full product builder.  manager_version is an
# independent SemVer and must not be copied from APP_VERSION.  Output goes to
# dist\TraceLabExtensionManager\ so it cannot wipe dist\TraceLabAnalyzer*.
# Do not generate production TUF keys here.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> [$(Get-Date -Format o)] $Message" -ForegroundColor Cyan
}

if ($env:OS -ne "Windows_NT") {
    Write-Warning "This script is intended to build a Windows .exe from Windows."
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EntryScript = Join-Path $RepoRoot "tools\extension_installer.py"
$Requirements = Join-Path $RepoRoot "tools\extension_manager\requirements.txt"
$DistDir = Join-Path $RepoRoot "dist"
$OutputDir = Join-Path $DistDir $AppName
$WorkDir = Join-Path $RepoRoot "build\pyinstaller-extension-manager"
$SpecDir = Join-Path $RepoRoot "build\spec-extension-manager"
$EvidenceDir = Join-Path $RepoRoot ".state\build-evidence\extension-manager"

if (-not (Test-Path -LiteralPath $EntryScript)) {
    throw "Manager entry is missing: $EntryScript (W6b owns tools/extension_installer.py). Refusing to invent a manager EXE or hash."
}
if (-not (Test-Path -LiteralPath $Requirements)) {
    throw "Manager requirements missing: $Requirements"
}

Write-Host "ManagerVersion=$ManagerVersion (independent of APP_VERSION)"
Write-Host "Output: $OutputDir"
Write-Host "This script does not generate production TUF keys."
Write-Host "This script does not write into dist\TraceLabAnalyzer*."

Write-Step "Manager freeze is a separate Windows job"
Write-Host "Entry: $EntryScript"
Write-Host "Workpath: $WorkDir"
Write-Host "Specpath: $SpecDir"
Write-Host "Evidence: $EvidenceDir"
Write-Host "Console=$Console SkipInstall=$SkipInstall"
Write-Host "Copy the tested installer.exe into a lite+modular tree via build_windows_folder_lite_modular.ps1 -ManagerSource."
