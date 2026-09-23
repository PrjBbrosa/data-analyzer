from pathlib import Path
import json
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
LITE = ROOT / "tools" / "build_windows_folder_lite.ps1"
MODULAR = ROOT / "tools" / "build_windows_folder_lite_modular.ps1"
MODULAR_BAT = ROOT / "tools" / "build_windows_folder_lite_modular.bat"
EXTENSIONS = ROOT / "tools" / "build_windows_extensions.py"
VERIFY = ROOT / "tools" / "verify_extension_installation.py"
MANAGER_BUILD = ROOT / "tools" / "build_windows_extension_installer.ps1"
MANAGER_BAT = ROOT / "tools" / "build_windows_extension_installer.bat"


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows path handling")
def test_combination_matrix_cleans_long_extension_paths(tmp_path, monkeypatch):
    from mf4_analyzer.extensions.locking import extensions_root
    from tools import verify_extension_delivery as delivery

    root = tmp_path / "base"
    root.mkdir()
    (root / "core.json").write_text(json.dumps({"exe_relpath": "app.exe"}))

    class Engine:
        def __init__(self, target):
            self.target = target

        def install(self, sources):
            payload = extensions_root(self.target) / ("x" * 90) / ("y" * 90) / "payload.pyd"
            assert len(str(payload)) > 260
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"test")

        def uninstall(self, names):
            pass

    monkeypatch.setattr(delivery, "build_sources", lambda audit: {"media": "media", "matlab": "matlab"})
    monkeypatch.setattr(delivery, "InstallEngine", Engine)
    monkeypatch.setattr(delivery, "verify", lambda **kwargs: (0, {"ok": True}))
    assert delivery.run_matrix(root, {})["ok"]
    assert list(tmp_path.iterdir()) == [root]


def test_matrix_cleanup_does_not_hide_verification_failure(tmp_path, monkeypatch):
    import tempfile
    from tools import verify_extension_delivery as delivery

    root = tmp_path / 'base'
    root.mkdir()
    (root / 'core.json').write_text(json.dumps({'exe_relpath': 'app.exe'}))

    class BlockedCleanup(tempfile.TemporaryDirectory):
        def cleanup(self):
            self._finalizer.detach()
            raise PermissionError('temporary native file still busy')

    def fail_verification(**kwargs):
        raise ValueError('primary verification failure')

    monkeypatch.setattr(delivery.tempfile, 'TemporaryDirectory', BlockedCleanup)
    monkeypatch.setattr(delivery, 'build_sources', lambda audit: {'media': None, 'matlab': None})
    monkeypatch.setattr(delivery, 'verify', fail_verification)
    with pytest.raises(ValueError, match='primary verification failure'):
        delivery.run_matrix(root, {})


def test_double_click_builds_have_defaults_and_keep_the_result_visible():
    modular = MODULAR.read_text(encoding="utf-8")
    manager = MANAGER_BUILD.read_text(encoding="utf-8")
    assert '[string]$RepositoryConfig = ""' in modular
    assert 'if (-not $ManagerSource)' in modular
    assert '& $ExtensionInstallerScript @ManagerBuildArgs' in modular
    assert modular.index('Start-Transcript') < modular.index('& $ExtensionInstallerScript @ManagerBuildArgs')
    assert 'Join-Path $RepoRoot "configs\\extension-release\\local\\repository.json"' in manager
    for path in (MODULAR_BAT, MANAGER_BAT):
        bat = path.read_text(encoding="utf-8")
        assert 'set "BUILD_EXIT_CODE=%ERRORLEVEL%"' in bat
        assert 'if "%~1"=="" pause' in bat
        assert 'exit /b %BUILD_EXIT_CODE%' in bat
        assert 'exit /b 2' not in bat


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows PowerShell 5.1")
@pytest.mark.parametrize("mode", ["default", "custom_config", "explicit_manager", "failed_manager", "missing_output", "missing_explicit"])
def test_modular_manager_preparation(tmp_path, mode):
    """Execute real preparation with only the expensive installer build stubbed."""
    repo = tmp_path / "repo with spaces"
    scripts = repo / "tools"
    scripts.mkdir(parents=True)
    required = [
        "MF4 Data Analyzer V1.py", "requirements.txt", "mf4_analyzer/ui_kit/style.qss",
        "tools/windows_runtime_dependencies.py", "tools/windows_bundle_policy.py",
        "tools/verify_frozen_batch_render.py", "tools/build_windows_extensions.py",
        "tools/verify_extension_installation.py",
    ]
    for name in required:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    marker = repo / "manager-args.json"
    manager_script = scripts / MANAGER_BUILD.name
    manager_script.write_text(
        'param([string]$RepositoryConfig, [switch]$SkipInstall, [switch]$Console)\n'
        '$root = Split-Path $PSScriptRoot\n'
        '@{config=$RepositoryConfig; skip=[bool]$SkipInstall; console=[bool]$Console} | '
        'ConvertTo-Json | Set-Content (Join-Path $root "manager-args.json")\n'
        + ('throw "manager probe failure"\n' if mode == "failed_manager" else '')
        + ('' if mode == "missing_output" else
           '$output = Join-Path $root "dist/TraceLabExtensionManager"\n'
           'New-Item -ItemType Directory -Force $output | Out-Null\n'
           'Set-Content (Join-Path $output "installer.exe") "probe"\n'),
        encoding="utf-8",
    )
    text = MODULAR.read_text(encoding="utf-8")
    preparation = text.split('Write-Step "Preparing build environment"', 1)[0]
    script = scripts / MODULAR.name
    script.write_text(
        preparation + '\nSet-Content (Join-Path $RepoRoot "selected-manager.txt") $ManagerSource\n'
        '} finally { Stop-Transcript | Out-Null }\n', encoding="utf-8",
    )
    args = ["-SkipInstall", "-Console"]
    custom = repo / "publisher config.json"
    custom.write_text("{}", encoding="utf-8")
    if mode == "custom_config":
        args += ["-RepositoryConfig", str(custom)]
    if mode in {"explicit_manager", "missing_explicit"}:
        supplied = repo / "supplied manager.exe"
        if mode == "explicit_manager":
            supplied.touch()
        args += ["-ManagerSource", str(supplied)]
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args],
        cwd=tmp_path, capture_output=True, text=True, timeout=60,
    )
    if mode in {"failed_manager", "missing_output", "missing_explicit"}:
        assert result.returncode != 0, result.stdout + result.stderr
        assert not (repo / "selected-manager.txt").exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        selected = (repo / "selected-manager.txt").read_text(encoding="utf-8-sig").strip()
        expected = supplied if mode == "explicit_manager" else repo / "dist/TraceLabExtensionManager/installer.exe"
        assert Path(selected) == expected
    if mode in {"explicit_manager", "missing_explicit"}:
        assert not marker.exists()
    else:
        call = json.loads(marker.read_text(encoding="utf-8-sig"))
        assert call["config"] == (str(custom) if mode == "custom_config" else "")
        assert call["skip"] and call["console"]


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows cmd and PowerShell")
@pytest.mark.parametrize("source", [MODULAR_BAT, MANAGER_BAT])
@pytest.mark.parametrize("exit_code", [0, 23])
@pytest.mark.parametrize("with_args", [False, True])
def test_bat_keeps_child_exit_code_and_forwards_arguments(tmp_path, source, exit_code, with_args):
    scripts = tmp_path / "scripts with spaces"
    scripts.mkdir()
    bat = scripts / source.name
    bat.write_bytes(source.read_bytes())
    bat.with_suffix(".ps1").write_text(
        'param([switch]$SkipInstall)\n'
        'Set-Content (Join-Path $PSScriptRoot "called.txt") ([bool]$SkipInstall)\n'
        f'exit {exit_code}\n', encoding="utf-8",
    )
    args = ["-SkipInstall"] if with_args else []
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", str(bat), *args],
        cwd=tmp_path, input="\n", capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert (scripts / "called.txt").read_text().strip() == str(with_args)


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows PowerShell 5.1")
@pytest.mark.parametrize("mode", ["default", "custom", "missing_config", "missing_root"])
def test_installer_repository_defaults(tmp_path, mode):
    repo = tmp_path / "repo with spaces"
    scripts = repo / "tools"
    scripts.mkdir(parents=True)
    config = repo / ("custom config/repository.json" if mode == "custom" else
                     "configs/extension-release/local/repository.json")
    config.parent.mkdir(parents=True)
    if mode != "missing_config":
        config.write_text(json.dumps({"schema": 1, "bootstrap_root": "root.json"}), encoding="utf-8")
    if mode != "missing_root":
        (config.parent / "root.json").write_text("{}", encoding="utf-8")
    script = scripts / MANAGER_BUILD.name
    script.write_text(
        MANAGER_BUILD.read_text(encoding="utf-8").split('Push-Location $RepoRoot', 1)[0]
        + '\nSet-Content (Join-Path $RepoRoot "selected-config.txt") $ConfigPath\n', encoding="utf-8",
    )
    args = ["-RepositoryConfig", str(config)] if mode == "custom" else []
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    if mode.startswith("missing_"):
        assert result.returncode != 0, result.stdout + result.stderr
        assert not (repo / "selected-config.txt").exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert Path((repo / "selected-config.txt").read_text().strip()) == config


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows PowerShell 5.1")
def test_extension_emitter_receives_one_real_site_packages_directory(tmp_path):
    import sysconfig

    text = MODULAR.read_text(encoding="utf-8")
    helper = text[text.index("function Invoke-LoggedNative"):text.index("function ConvertTo-Win32ArgumentList")]
    selection = text[text.index("$SitePackagesJson ="):text.index("$ExtensionEmitArgs =")]
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    result_path = tmp_path / "selected-site.json"
    probe = tmp_path / "probe.ps1"
    probe.write_text(
        '$ErrorActionPreference = "Stop"\nSet-StrictMode -Version Latest\n'
        + f'$VenvPython = {quote(sys.executable)}\n$BuildEvidenceDir = {quote(tmp_path)}\n'
        + helper + selection
        + f'$SitePackages | ConvertTo-Json | Set-Content {quote(result_path)}\n', encoding="utf-8",
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    selected = json.loads(result_path.read_text(encoding="utf-8-sig"))
    assert selected == sysconfig.get_path("platlib")
    assert Path(selected).is_dir()


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows PowerShell 5.1")
def test_frozen_verification_copies_to_local_temp_without_moving_output(tmp_path):
    import shutil
    import tempfile
    import uuid

    text = MODULAR.read_text(encoding="utf-8")
    start = text.index('Write-Step "Preparing local Windows verification copy"')
    stop = text.index('Write-Step "Verifying frozen batch rendering', start)
    source = tmp_path / "Build output"
    source.mkdir()
    (source / "Build output.exe").write_bytes(b"frozen artifact")
    record = tmp_path / "copy.json"
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    script = tmp_path / "copy.ps1"
    script.write_text(
        '$ErrorActionPreference = "Stop"\nfunction Write-Step { param($Message) }\n'
        + f'$OutputDir = {quote(source)}\n$AppName = "Build output"\n$BuildRunId = "{uuid.uuid4()}"\n'
        + text[start:stop]
        + f'@{{root=$SmokeRoot; exe=$VerificationExe}} | ConvertTo-Json | Set-Content {quote(record)}\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(record.read_text(encoding="utf-8-sig"))
    local = Path(data["root"])
    try:
        assert local.parent.resolve() == Path(tempfile.gettempdir()).resolve()
        assert Path(data["exe"]).read_bytes() == b"frozen artifact"
        assert (source / "Build output.exe").read_bytes() == b"frozen artifact"
    finally:
        shutil.rmtree(local)


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


def test_modular_packager_keeps_startup_splash_modules():
    """Modular base drops media/MAT but must still analyse splash imports."""

    text = MODULAR.read_text(encoding="utf-8")
    assert "MF4 Data Analyzer V1.py" in text
    for module_name in (
        "mf4_analyzer.startup_feedback",
        "mf4_analyzer.startup_splash_child",
        "mf4_analyzer.ui.startup_splash",
    ):
        assert f'"--exclude-module", "{module_name}"' not in text
    # Optional importers stay excluded; splash is unrelated to those trees.
    assert '"--exclude-module", "matplotlib"' in text


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
    assert '"--mode", "base-expected-missing", "--exe", $VerificationExe' in text
    assert "do not mint manager_version from APP_VERSION" not in LITE.read_text(encoding="utf-8")
    assert EXTENSIONS.is_file()
    assert VERIFY.is_file()
    assert MANAGER_BUILD.is_file()
    manager = MANAGER_BUILD.read_text(encoding="utf-8")
    assert "independent of APP_VERSION" in manager
    assert "does not generate production TUF keys" in manager
    assert r"dist\TraceLabAnalyzer" in manager
    bat = MANAGER_BAT.read_text(encoding="utf-8")
    assert MANAGER_BAT.is_file()
    assert "build_windows_extension_installer.ps1" in bat
    assert "build_windows_folder_lite" not in bat
    assert "dist\\TraceLabExtensionManager\\installer.exe" in bat
    assert "configs\\extension-release\\local\\repository.json" in bat
    local_config = ROOT / "configs" / "extension-release" / "local"
    assert (local_config / "repository.json").is_file()
    assert (local_config / "root.json").is_file()


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
