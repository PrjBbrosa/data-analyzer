param(
    [string]$ManagerVersion = "1.0.0",
    [string]$AppName = "TraceLabExtensionManager",
    [string]$RepositoryConfig = "",
    [string]$PythonExe = "python",
    [switch]$Console,
    [switch]$SkipInstall
)

# ManagerVersion is independent of APP_VERSION.
# This builder does not generate production TUF keys or write dist\TraceLabAnalyzer*.
# Independent manager runtime. Never install TUF into the analyzer environment.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ($env:OS -ne "Windows_NT") { throw "Build the manager on Windows x64." }
if ($ManagerVersion -notmatch '^\d+\.\d+\.\d+([+-][0-9A-Za-z.-]+)?$') { throw "Invalid manager SemVer." }
if (-not $RepositoryConfig) { throw "RepositoryConfig is required: supply the official repository.json and its trusted root; no production keys are generated." }
if ($AppName -notmatch '^TraceLabExtensionManager[-a-zA-Z0-9_.]*$') { throw "Use a dedicated TraceLabExtensionManager output name." }
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EntryScript = Join-Path $RepoRoot "tools\extension_installer.py"
$Requirements = Join-Path $RepoRoot "tools\extension_manager\requirements.txt"
$ConfigPath = (Resolve-Path -LiteralPath $RepositoryConfig).Path
$Config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
if ($Config.schema -ne 1) { throw "Unsupported repository configuration." }
$BootstrapRoot = Join-Path (Split-Path $ConfigPath) $Config.bootstrap_root
if (-not (Test-Path -LiteralPath $BootstrapRoot -PathType Leaf)) { throw "Trusted bootstrap root missing." }
$OutputDir = Join-Path $RepoRoot "dist\$AppName"
$WorkDir = Join-Path $RepoRoot "build\pyinstaller-extension-manager"
$SpecDir = Join-Path $RepoRoot "build\spec-extension-manager"
$EvidenceDir = Join-Path $RepoRoot ".state\build-evidence\extension-manager"
$VenvDir = Join-Path $RepoRoot "build\.venv-extension-manager"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Executable" }
}
Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Force -Path $OutputDir, $WorkDir, $SpecDir, $EvidenceDir | Out-Null
    if (-not (Test-Path $VenvPython)) {
        Invoke-Checked $PythonExe @("-m", "venv", $VenvDir)
    }
    Invoke-Checked $VenvPython @("-c", "import platform,struct; assert struct.calcsize('P')==8 and platform.machine().lower() in ('amd64','x86_64'), 'Windows x64 Python required'; import tkinter")
    if (-not $SkipInstall) {
        Invoke-Checked $VenvPython @("-m", "pip", "install", "-r", $Requirements)
        Invoke-Checked $VenvPython @("-m", "pip", "install", "pyinstaller")
    }
    Invoke-Checked $VenvPython @("-c", "from tools.extension_manager.app import MANAGER_VERSION; assert MANAGER_VERSION == '$ManagerVersion', 'manager_version must match its independent source constant'")
    # Normalize resources without modifying publisher-owned configuration.
    $Resources = Join-Path $WorkDir "trust-resources"
    New-Item -ItemType Directory -Force -Path $Resources | Out-Null
    $Config.bootstrap_root = "root.json"
    $Config | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $Resources "repository.json") -Encoding UTF8
    Copy-Item -LiteralPath $BootstrapRoot -Destination (Join-Path $Resources "root.json") -Force
    $BuildArgs = @("-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--noupx",
        "--name", "installer", "--distpath", $OutputDir, "--workpath", $WorkDir,
        "--specpath", $SpecDir, "--paths", $RepoRoot,
        "--add-data", "${Resources}\repository.json;.", "--add-data", "${Resources}\root.json;.",
        "--collect-all", "tuf", "--collect-all", "securesystemslib", "--collect-all", "cryptography",
        "--exclude-module", "PyQt5", "--exclude-module", "numpy", "--exclude-module", "pandas",
        "--exclude-module", "av", "--exclude-module", "scipy", "--exclude-module", "h5py",
        "--exclude-module", "mf4_analyzer.io", "--exclude-module", "mf4_analyzer.ui",
        "--exclude-module", "mf4_analyzer.extensions.native_probe", "--exclude-module", "mf4_analyzer.extensions.health")
    $BuildArgs += $(if ($Console) { "--console" } else { "--windowed" })
    $BuildArgs += $EntryScript
    Invoke-Checked $VenvPython $BuildArgs
    $ManagerExe = Join-Path $OutputDir "installer.exe"
    if (-not (Test-Path -LiteralPath $ManagerExe)) { throw "No installer.exe produced." }
    $SelfTest = Join-Path $EvidenceDir "manager-self-test.json"
    Remove-Item -LiteralPath $SelfTest -ErrorAction SilentlyContinue
    $Process = Start-Process -FilePath $ManagerExe -ArgumentList @("--self-test-json", "`"$SelfTest`"") -PassThru
    if (-not $Process.WaitForExit(60000)) { $Process.Kill(); throw "Manager self-test timed out." }
    if ($Process.ExitCode -ne 0 -or -not (Test-Path $SelfTest)) { throw "Manager frozen self-test failed." }
    $Result = Get-Content -LiteralPath $SelfTest -Raw | ConvertFrom-Json
    if (-not $Result.ok -or $Result.manager_version -ne $ManagerVersion) { throw "Manager self-test/version mismatch." }
    $Hash = (Get-FileHash -LiteralPath $ManagerExe -Algorithm SHA256).Hash.ToLowerInvariant()
    @{ manager_version=$ManagerVersion; sha256=$Hash; size=(Get-Item $ManagerExe).Length; self_test=$Result } |
        ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $OutputDir "manager-build.json") -Encoding UTF8
    Write-Host "Built and self-tested: $ManagerExe ($Hash)"
    Write-Host "Tk foreground Chinese text/DPI and target transaction acceptance remain separate gates."
} finally { Pop-Location }
