param(
    [string]$ManagerVersion = "1.0.0",
    [string]$AppName = "TraceLabExtensionManager",
    [string]$RepositoryConfig = "",
    [string]$PythonExe = "",
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
if ($AppName -notmatch '^TraceLabExtensionManager[-a-zA-Z0-9_.]*$') { throw "Use a dedicated TraceLabExtensionManager output name." }
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).ProviderPath
if (-not $RepositoryConfig) {
    $RepositoryConfig = Join-Path $RepoRoot "configs\extension-release\local\repository.json"
}
$EntryScript = Join-Path $RepoRoot "tools\extension_installer.py"
$Requirements = Join-Path $RepoRoot "tools\extension_manager\requirements.txt"
$ConfigPath = (Resolve-Path -LiteralPath $RepositoryConfig).ProviderPath
$Config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
if ($Config.schema -ne 1) { throw "Unsupported repository configuration." }
if ($Config.PSObject.Properties.Name -contains "distribution" -and $Config.distribution -eq "local-placeholder") {
    Write-Warning "Using local placeholder repository configuration. This build cannot install online extensions until a real repository and trusted root are configured."
}
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
    # Windows PowerShell 5.1 wraps ordinary native stderr as error records.
    $ErrorActionPreference = "Continue"
    Write-Host "Command: $Executable $($Arguments | ConvertTo-Json -Compress)"
    & $Executable @Arguments 2>&1 | ForEach-Object { Write-Host $_.ToString() }
    $NativeExitCode = $LASTEXITCODE
    Write-Host "Native exit code: $NativeExitCode"
    if ($NativeExitCode -ne 0) { throw "Command failed ($NativeExitCode): $Executable" }
}

function Test-ManagerPython {
    param([string]$Executable)
    if (-not (Get-Command $Executable -ErrorAction SilentlyContinue)) { return $false }
    $ErrorActionPreference = "Continue"
    # platform.machine() reports ARM64 even for x64 Python under Windows emulation.
    $Probe = "import sysconfig,tkinter; print(sysconfig.get_platform()); assert sysconfig.get_platform() == 'win-amd64', 'Windows x64 Python required'; tkinter.Tcl()"
    Write-Host "Checking installer Python: $Executable"
    & $Executable -c $Probe 2>&1 | ForEach-Object { Write-Host $_.ToString() }
    return ($LASTEXITCODE -eq 0)
}

function Initialize-ManagerEnvironment {
    if ((Test-Path -LiteralPath $VenvPython) -and (Test-ManagerPython $VenvPython)) {
        return $false
    }
    # Select and validate before moving an existing environment. Keep manager
    # dependencies isolated; a base interpreter is only used to create its venv.
    $Candidates = if ($PythonExe) { @($PythonExe) } else {
        @((Join-Path $RepoRoot ".build-tools\python312-x64\python.exe"),
          (Join-Path $RepoRoot ".venv-build-win\Scripts\python.exe"), "python")
    }
    $BasePython = $null
    foreach ($Candidate in $Candidates) {
        if (Test-ManagerPython $Candidate) {
            $BasePython = $Candidate
            break
        }
    }
    if (-not $BasePython) {
        throw "No working Windows x64 Python with tkinter found. Supply -PythonExe with an x64 python.exe path; existing environments were preserved."
    }
    if (Test-Path -LiteralPath $VenvDir) {
        $Backup = "$VenvDir.incompatible-$(Get-Date -Format 'yyyyMMdd-HHmmss')-$([guid]::NewGuid().ToString('N'))"
        Move-Item -LiteralPath $VenvDir -Destination $Backup
        Write-Host "Preserved incompatible installer environment: $Backup"
    }
    Invoke-Checked $BasePython @("-m", "venv", $VenvDir)
    if (-not (Test-ManagerPython $VenvPython)) {
        throw "Created installer environment failed the x64/tkinter check: $VenvPython"
    }
    return $true
}
Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Force -Path $OutputDir, $WorkDir, $SpecDir, $EvidenceDir | Out-Null
    $EnvironmentCreated = Initialize-ManagerEnvironment
    if (-not $SkipInstall -or $EnvironmentCreated) {
        if ($SkipInstall) { Write-Host "New installer environment requires dependency installation despite -SkipInstall." }
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
