function Install-TraceLabStartupLauncher {
    param(
        [Parameter(Mandatory = $true)][string]$AppName,
        [Parameter(Mandatory = $true)][string]$OutputDir,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Python
    )

    $ErrorActionPreference = "Stop"
    # Opt-in only. The default Windows package keeps the PyInstaller EXE as the
    # public name until the native panel passes on a real Windows desktop.
    $publicExe = Join-Path $OutputDir "$AppName.exe"
    $runtimeExe = Join-Path $OutputDir "$AppName-runtime.exe"
    if (-not (Test-Path -LiteralPath $publicExe)) {
        throw "Native launcher install expected the PyInstaller runtime at $publicExe"
    }
    if (Test-Path -LiteralPath $runtimeExe) {
        throw "Refusing to overwrite an existing runtime EXE: $runtimeExe"
    }
    $internal = Join-Path $OutputDir "_internal"
    if (-not (Test-Path -LiteralPath $internal)) {
        throw "Native launcher install expected _internal beside the runtime so install-root resolution stays unchanged."
    }
    $staged = Join-Path $OutputDir "$AppName.launcher-new.exe"
    & (Join-Path $PSScriptRoot "build_startup_launcher.ps1") -RepoRoot $RepoRoot -OutputPath $staged -Python $Python -RuntimeExe $publicExe
    if (-not (Test-Path -LiteralPath $staged)) {
        throw "Native launcher staging file was not produced: $staged"
    }
    Move-Item -LiteralPath $publicExe -Destination $runtimeExe
    Move-Item -LiteralPath $staged -Destination $publicExe
    if (-not (Test-Path -LiteralPath $runtimeExe) -or -not (Test-Path -LiteralPath $publicExe)) {
        throw "Native launcher install did not leave both $AppName.exe and $AppName-runtime.exe in $OutputDir"
    }
}
