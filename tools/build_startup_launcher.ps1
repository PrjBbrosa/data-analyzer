param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$RuntimeExe
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-PeMachine {
    param([string]$Path)
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $buffer = New-Object byte[] 64
        [void]$stream.Read($buffer, 0, 64)
        $peOffset = [BitConverter]::ToInt32($buffer, 60)
        $stream.Position = $peOffset + 4
        $machine = New-Object byte[] 2
        [void]$stream.Read($machine, 0, 2)
        return [BitConverter]::ToUInt16($machine, 0)
    } finally {
        $stream.Close()
    }
}

$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path -LiteralPath $vswhere)) {
    throw "MSVC is required for the native startup launcher. vswhere.exe was not found. This build will not emit a package that looks the same but has no early splash."
}
$install = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $install) {
    throw "MSVC C++ toolset was not found. Install the Desktop development with C++ workload. Refusing to package without the native launcher."
}
$vcvars = Join-Path $install "VC\Auxiliary\Build\vcvarsall.bat"
if (-not (Test-Path -LiteralPath $vcvars)) {
    throw "vcvarsall.bat was not found under $install. Refusing to package without the native launcher."
}

$machine = Get-PeMachine -Path $RuntimeExe
switch ($machine) {
    0x8664 { $arch = "x64" }
    0xAA64 { $arch = "x64_arm64" }
    default { throw "Runtime PE machine 0x$("{0:X}" -f $machine) has no supported MSVC launcher target. x64 and ARM64 must be built natively for that architecture." }
}

$generated = Join-Path ([System.IO.Path]::GetDirectoryName($OutputPath)) "startup-launcher-generated"
New-Item -ItemType Directory -Force -Path $generated | Out-Null
& $Python (Join-Path $RepoRoot "tools\generate_startup_launcher_resources.py") --output-dir $generated
if ($LASTEXITCODE -ne 0) {
    throw "Startup visual resource generation failed."
}

$sourceDir = Join-Path $RepoRoot "native\startup_launcher"
$sources = @(
    "launcher_win32.cc",
    "tip_clock.cc",
    "json_value.cc",
    "protocol.cc",
    "session_machine.cc",
    "launch_dispatch.cc"
) | ForEach-Object { Join-Path $sourceDir $_ }
$quotedSources = ($sources | ForEach-Object { '"' + $_ + '"' }) -join " "
$include = '"' + $generated + '" "' + $sourceDir + '"'
$outQuoted = '"' + $OutputPath + '"'
$command = "`"$vcvars`" $arch && cl /nologo /EHsc /O2 /utf-8 /std:c++17 /DUNICODE /D_UNICODE /I $include $quotedSources /Fe:$outQuoted /link /SUBSYSTEM:WINDOWS /ENTRY:wWinMainCRTStartup"
cmd.exe /c $command
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $OutputPath)) {
    throw "Native startup launcher compile failed. The package was not given a public EXE without an early panel."
}
