from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LITE = ROOT / "tools" / "build_windows_folder_lite.ps1"
MODULAR = ROOT / "tools" / "build_windows_folder_lite_modular.ps1"
MODULAR_BAT = ROOT / "tools" / "build_windows_folder_lite_modular.bat"
EXTENSIONS = ROOT / "tools" / "build_windows_extensions.py"
VERIFY = ROOT / "tools" / "verify_extension_installation.py"
MANAGER_BUILD = ROOT / "tools" / "build_windows_extension_installer.ps1"


def test_original_lite_packager_stays_bundled():
    text = LITE.read_text(encoding="utf-8")
    assert "--profile modular" not in text
    assert "--pyinstaller-args-json --flavor lite" in text
    assert "--pyinstaller-args-json --flavor lite --profile modular" not in text
    assert 'Join-Path $RepoRoot ".state\\build-evidence\\lite\\$BuildRunId"' in text
    assert "TraceLabAnalyzer${Version}-modular" not in text
    assert "build_windows_extensions.py" not in text
    assert 'Invoke-IndependentPostCheck -Name "importer"' in text
    assert "verify_lite_importer_runtime.py" in text


def test_modular_packager_is_a_separate_lite_copy():
    text = MODULAR.read_text(encoding="utf-8")
    bat = MODULAR_BAT.read_text(encoding="utf-8")

    assert MODULAR.exists()
    assert '[string]$Flavor = "lite"' in text
    assert '[string]$DependencyProfile = "modular"' in text
    assert "--pyinstaller-args-json --flavor $Flavor --profile $DependencyProfile" in text
    assert "first modular release accepts only lite+modular" in text
    assert "[string[]](ConvertFrom-Json -InputObject $RuntimeDependencyArgsJson)" in text
    assert 'Join-Path $RepoRoot "build\\pyinstaller-lite-modular"' in text
    assert 'Join-Path $RepoRoot "build\\spec-lite-modular"' in text
    assert 'Join-Path $RepoRoot ".state\\build-evidence\\lite-modular\\$BuildRunId"' in text
    assert "TraceLabAnalyzer${Version}-modular" in text
    assert "libscipy_openblas*.dll" not in text
    assert "Modular base leaked optional importer trees" in text
    assert "build_windows_folder_lite_modular.ps1" in bat
    assert "build_windows_folder_lite.ps1" not in bat.replace(
        "build_windows_folder_lite_modular.ps1", ""
    )


def test_modular_packager_emits_manifests_zips_audit_and_manager_copy():
    text = MODULAR.read_text(encoding="utf-8")
    assert "build_windows_extensions.py" in text
    assert "verify_extension_installation.py" in text
    assert "build_windows_extension_installer.ps1" in text
    assert "--app-root" in text
    assert "--exe-relpath" in text
    assert "--site-packages" in text
    assert "--manager-source" in text
    assert "modular release refuses a placeholder manager" in text
    assert '"--mode", "base-expected-missing", "--exe", $ExePath' in text
    assert "do not mint manager_version from APP_VERSION" not in LITE.read_text(encoding="utf-8")
    assert EXTENSIONS.is_file()
    assert VERIFY.is_file()
    assert MANAGER_BUILD.is_file()
    manager = MANAGER_BUILD.read_text(encoding="utf-8")
    assert "independent of APP_VERSION" in manager
    assert "does not generate production TUF keys" in manager
    assert r"dist\TraceLabAnalyzer" in manager


def test_modular_importer_gates_are_split_and_not_skipped_as_success():
    text = MODULAR.read_text(encoding="utf-8")
    assert 'Invoke-IndependentPostCheck -Name "importer-base-missing"' in text
    assert 'Invoke-IndependentPostCheck -Name "importer-installed-contract"' in text
    assert 'Invoke-IndependentPostCheck -Name "importer-fallback-contract"' in text
    assert 'combination-contract' in text
    assert "Skipping lite importer smoke" not in text
    assert 'importer: skipped' not in text
    assert 'Invoke-IndependentPostCheck -Name "extension-combinations"' in text
    assert "verify_extension_delivery.py" in text
    assert "Not invoking verify_lite_importer_runtime.py" in text
    assert 'Invoke-IndependentPostCheck -Name "importer"' not in text
    assert 'importer-base-missing' in text[
        text.index("function Test-AllPostChecksPassed") : text.index(
            "function Write-PostCheckSummary"
        )
    ]


def test_modular_post_check_timeout_is_bounded_to_owned_tree():
    text = MODULAR.read_text(encoding="utf-8")
    helper = text[
        text.index("function Stop-OwnedProcessTree") : text.index(
            "function Invoke-IndependentPostCheck"
        )
    ]
    assert "Stop-OwnedProcessTree" in helper
    assert "Wait-RedirectedOutput" in helper
    assert "$Task.Wait($TimeoutMs)" in helper
    assert "$stdoutTask.Result" not in text.split("function Invoke-IndependentPostCheck", 1)[1].split(
        "function Invoke-BasePython", 1
    )[0]
    assert "Only descendants of the process this script started" in helper
    assert "$descendantRows = @(foreach ($procId in $owned)" in helper
    check = text[
        text.index("function Invoke-IndependentPostCheck") : text.index(
            "function Invoke-BasePython"
        )
    ]
    assert "Wait-RedirectedOutput -Task $stdoutTask" in check
    assert "Wait-RedirectedOutput -Task $stderrTask" in check


def test_powershell_foreach_is_collected_before_joining_arguments():
    text = MODULAR.read_text(encoding="utf-8")
    assert "$parts = @(foreach ($Argument in @($Arguments))" in text
    assert "} | ConvertTo-Json" not in text
