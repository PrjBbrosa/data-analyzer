from pathlib import Path
import json
import re
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _powershell_literal(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def test_windows_folder_build_script_uses_onedir_pyinstaller_contract():
    script = ROOT / "tools" / "build_windows_folder.ps1"

    assert script.exists()
    text = script.read_text(encoding="utf-8")

    for token in (
        "PyInstaller",
        "--onedir",
        "--windowed",
        "--add-data",
        "style.qss",
        "--hidden-import",
        "qtawesome",
        "MF4 Data Analyzer V1.py",
        "TraceLab8.3.2",
    ):
        assert token in text


def test_windows_folder_build_script_bundles_help_docs_inside_app():
    """Help docs (panel guides + software manual) are integrated into the app
    and opened from inside the bundle, so they ship INSIDE the package via
    --add-data — NOT copied next to the exe anymore.

    The old "copy user guides next to exe" step was removed once the in-app
    help system (mf4_analyzer/help/ + status-bar / per-panel buttons) replaced
    the loose-files-beside-exe approach.
    """
    script = ROOT / "tools" / "build_windows_folder.ps1"

    assert script.exists()
    text = script.read_text(encoding="utf-8")

    # Help tree is bundled into the frozen app at mf4_analyzer\help.
    assert "mf4_analyzer\\help" in text
    assert "$AddDataHelp" in text
    assert "$AddDataWwt" in text or "assets\\wwt" in text


def test_windows_build_scripts_name_the_wwt_export_modules():
    """导出 WWT 的模块是函数体内惰性 import，冻结构建要显式点名。

    资源（模板骨架 + 显示尾块）走 assets\\wwt 目录整体打包。
    """
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for script_name in ("build_windows_folder.ps1", "build_windows_folder_lite.ps1"):
        text = (root / "tools" / script_name).read_text(encoding="utf-8")
        for module_name in (
            "mf4_analyzer.io.wwt_export",
            "mf4_analyzer.io.wwt_display",
            "mf4_analyzer.io.wwt_writer",
            "mf4_analyzer.io.wwt_inplace",
            "mf4_analyzer.io.wwt_quantize",
        ):
            assert module_name in text, f"{script_name} misses {module_name}"
        assert "$AddDataWwt" in text, f"{script_name} misses assets\\wwt bundling"

    # The retired copy-next-to-exe step must be gone.
    assert "Copying user guides next to exe" not in text
    assert '"TraceLab-*.html"' not in text
    assert 'TraceLab-v$Version-*.html' not in text


def test_windows_folder_build_script_vendors_native_acquisition_packages_without_analysis_import():
    script = ROOT / "tools" / "build_windows_folder.ps1"
    runtime_hook = ROOT / "tools" / "pyinstaller_rthook_pyxcp_vendor.py"

    assert script.exists()
    assert runtime_hook.exists()
    text = script.read_text(encoding="utf-8")

    assert "_vendor_pyxcp" in text
    assert "_vendor_pya2l" in text
    assert "--runtime-hook" in text
    assert "pyinstaller_rthook_pyxcp_vendor.py" in text
    assert "--exclude-module" in text
    for module in ("pyxcp", "pya2l"):
        assert f'"--exclude-module", "{module}"' in text
    assert "requirements-windows-acquisition.txt" in text
    assert "verify_windows_acquisition_runtime.py" in text
    assert "--acquisition-runtime-smoke" in text


def test_windows_folder_build_vendors_pinned_pyxcp_metadata_and_dependencies():
    script = ROOT / "tools" / "build_windows_folder.ps1"
    text = script.read_text(encoding="utf-8")

    assert "-m pip install" in text
    assert "--target" in text
    assert "$AcquisitionRequirements" in text
    assert "pyxcp-0.29.14.dist-info" in text
    assert "import pathlib, pyxcp" not in text
    assert "Copy-Item -Recurse -Force -Path $PyxcpSrc" not in text


def test_windows_folder_build_vendors_exact_pya2ldb_metadata_and_dependencies():
    script = ROOT / "tools" / "build_windows_folder.ps1"
    text = script.read_text(encoding="utf-8")

    assert 'importlib.metadata.version("pya2ldb")' in text
    assert '"pya2ldb==$Pya2lVersion"' in text
    assert "--target $VendorPya2lDir" in text
    assert '"pya2ldb-$Pya2lVersion.dist-info"' in text
    assert "import pathlib, pya2l" not in text
    assert "Copy-Item -Recurse -Force -Path $Pya2lSrc" not in text
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "pya2ldb==1.0.332" in requirements


def test_frozen_entry_has_dedicated_pyxcp_import_probe_child():
    entry = (ROOT / "MF4 Data Analyzer V1.py").read_text(encoding="utf-8")

    assert "--pyxcp-import-probe-child" in entry
    assert "run_import_probe_child" in entry
    assert entry.index("if args.pyxcp_import_probe_child") < entry.index(
        "from mf4_analyzer.app import main"
    )


def test_frozen_entry_has_dedicated_a2l_and_pya2l_probe_children():
    entry = (ROOT / "MF4 Data Analyzer V1.py").read_text(encoding="utf-8")

    for flag in ("--a2l-probe-child", "--pya2l-import-probe-child"):
        assert flag in entry
    assert "_a2l_subprocess import main as a2l_child_main" in entry
    assert "run_pya2l_import_probe_child" in entry
    assert entry.index("if args.a2l_probe_child") < entry.index(
        "from mf4_analyzer.app import main"
    )


def test_vector_runbook_uses_default_build_name_and_separate_evidence_files():
    runbook = (
        ROOT / "docs/analyzer/acquisition/runbooks/stage-8-pr4-bench.md"
    ).read_text(encoding="utf-8")

    assert r".\dist\TraceLab8.3.2\TraceLab8.3.2.exe" in runbook
    assert "build-api-contract.json" in runbook
    assert "packaged-runtime-smoke.json" in runbook
    assert "MF4DataAnalyzer" not in runbook
    assert (
        "powershell -ExecutionPolicy Bypass -File "
        "tools\\build_windows_folder.ps1\n"
    ) in runbook
    assert "build_windows_folder.ps1 -Console" not in runbook
    assert "console-build PASS does not" in runbook


def test_windows_build_scripts_share_frozen_import_dependency_contract():
    """Both package flavors must build every documented Analyzer importer.

    The concrete PyInstaller arguments are generated by
    ``tools/windows_runtime_dependencies.py``.  This keeps a lazy importer
    from silently drifting away from one of the two PowerShell build scripts.
    """
    for filename in ("build_windows_folder.ps1", "build_windows_folder_lite.ps1"):
        text = (ROOT / "tools" / filename).read_text(encoding="utf-8")
        assert "windows_runtime_dependencies.py" in text
        assert "$RuntimeDependencyArgs" in text
        assert '"--exclude-module", "scipy"' not in text
        assert '"--exclude-module", "h5py"' not in text
        assert '"--exclude-module", "matplotlib"' in text
        assert "$env:MPLBACKEND" not in text
        assert "matplotlib_frozen_contract.py" not in text
        assert "--prune-internal" not in text

    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "scipy" in requirements
    assert "h5py" in requirements
    assert not any(
        line.split("#", 1)[0].strip().lower().startswith("matplotlib")
        for line in requirements.splitlines()
    )


def test_windows_build_scripts_require_both_qt_platform_plugins_and_smoke_them():
    """Every flavor must prove both headless and native Windows Qt platforms."""
    for filename in ("build_windows_folder.ps1", "build_windows_folder_lite.ps1"):
        text = (ROOT / "tools" / filename).read_text(encoding="utf-8")
        for plugin in ("qoffscreen.dll", "qwindows.dll"):
            assert plugin in text
        assert re.search(r'--platform(?: |", ")offscreen', text)
        assert re.search(r'--platform(?: |", ")windows', text)
        assert "batch-render-offscreen-smoke.json" in text
        assert "batch-render-windows-smoke.json" in text


def test_windows_build_scripts_request_their_collection_flavors():
    full = (ROOT / "tools" / "build_windows_folder.ps1").read_text(
        encoding="utf-8"
    )
    lite = (ROOT / "tools" / "build_windows_folder_lite.ps1").read_text(
        encoding="utf-8"
    )

    assert "--pyinstaller-args-json --flavor full" in full
    assert "--pyinstaller-args-json --flavor lite" in lite
    assert "--profile modular" not in lite
    assert '"--collect-all", "scipy"' not in lite


def test_lite_build_prunes_only_the_resolved_scipy_openblas_dll():
    """The optional native SciPy prune must fail closed on future layouts."""
    lite = (ROOT / "tools" / "build_windows_folder_lite.ps1").read_text(
        encoding="utf-8"
    )

    assert "_internal\\scipy.libs" in lite
    assert '"libscipy_openblas*.dll"' in lite
    assert "$SciPyOpenBlas.Count -ne 1" in lite
    assert "Expected exactly one SciPy OpenBLAS DLL" in lite
    assert "Expected scipy.libs to be empty after OpenBLAS removal" in lite


def test_windows_folder_build_script_can_make_console_diagnostic_build():
    script = ROOT / "tools" / "build_windows_folder.ps1"

    assert script.exists()
    text = script.read_text(encoding="utf-8")

    assert "[switch]$Console" in text
    assert "--console" in text
    assert "--windowed" in text
    assert "$Console" in text


def test_windows_build_bat_wraps_powershell_with_execution_policy_bypass():
    wrapper = ROOT / "tools" / "build_windows_folder.bat"

    assert wrapper.exists()
    text = wrapper.read_text(encoding="utf-8").lower()

    assert "powershell" in text
    assert "-executionpolicy bypass" in text
    assert "build_windows_folder.ps1" in text


def test_lite_build_script_uses_onedir_pyinstaller_contract():
    """The analyzer-only ("lite") build shares the frozen contract that matters
    for the Analyzer half: onedir/windowed, style.qss + help bundled inside,
    qtawesome collected, and all data-import dependencies are collected through
    the shared frozen-import contract."""
    script = ROOT / "tools" / "build_windows_folder_lite.ps1"

    assert script.exists()
    text = script.read_text(encoding="utf-8")

    for token in (
        "PyInstaller",
        "--onedir",
        "--windowed",
        "--add-data",
        "style.qss",
        "mf4_analyzer\\help",
        "--hidden-import",
        "qtawesome",
        "MF4 Data Analyzer V1.py",
    ):
        assert token in text, f"lite build script must contain {token!r}"


def test_windows_build_scripts_default_to_current_release():
    for filename in ("build_windows_folder.ps1", "build_windows_folder_lite.ps1"):
        script = ROOT / "tools" / filename
        text = script.read_text(encoding="utf-8")

        assert '[string]$Version = "8.3.2"' in text

    lite_script = ROOT / "tools" / "build_windows_folder_lite.ps1"
    assert "TraceLabAnalyzer8.3.2" in lite_script.read_text(encoding="utf-8")


def test_lite_build_script_omits_acquisition_and_native_deps():
    """The whole point of the lite build: acquisition packaging is gone.

    No pyxcp/pya2l vendoring, no runtime hook, no acquisition requirements/smoke,
    and none of the acquisition_ui / acquisition_capture hidden imports — while
    pyxcp/pya2l are additionally --exclude-module'd as belt-and-suspenders."""
    script = ROOT / "tools" / "build_windows_folder_lite.ps1"
    text = script.read_text(encoding="utf-8")

    # Acquisition-only packaging machinery must NOT appear.
    for absent in (
        "_vendor_pyxcp",
        "_vendor_pya2l",
        "--runtime-hook",
        "pyinstaller_rthook_pyxcp_vendor.py",
        "requirements-windows-acquisition.txt",
        "--acquisition-runtime-smoke",
        # Submodules that only ever appear in the full build's hidden-import list.
        "acquisition_capture.controller",
        "acquisition_ui.review_modal",
    ):
        assert absent not in text, f"lite build script must NOT contain {absent!r}"

    # But it must still hard-exclude the native acquisition deps as a safety net.
    for module in ("pyxcp", "pya2l"):
        assert f'"--exclude-module", "{module}"' in text


def test_lite_build_script_excludes_unused_qt_modules_but_keeps_render_deps():
    """The app only imports QtWidgets/QtCore/QtGui, but --collect-submodules
    pyqtgraph drags in unused Qt backends (QtWebEngine ships Chromium). The lite
    build excludes those, while KEEPING the Qt modules the render/export/icon
    paths actually need."""
    script = ROOT / "tools" / "build_windows_folder_lite.ps1"
    text = script.read_text(encoding="utf-8")

    # Heavy unused Qt modules must be excluded.
    for module in (
        "PyQt5.QtWebEngine",
        "PyQt5.QtWebEngineWidgets",
        "PyQt5.QtQml",
        "PyQt5.QtQuick",
        "PyQt5.QtMultimedia",
        "PyQt5.Qt3DRender",
    ):
        assert f'"{module}"' in text, f"lite build should exclude {module}"

    # Render/export/icon Qt deps must NOT be excluded (they are used).
    assert '"PyQt5.QtOpenGL"' in text  # Product charts do not enable OpenGL.
    for keep in ("PyQt5.QtSvg", "PyQt5.QtPrintSupport"):
        assert keep not in text, (
            f"{keep} must NOT be excluded — pyqtgraph GL render / icons / export "
            f"depend on it"
        )


def test_full_build_script_excludes_unused_qt_but_keeps_acquisition_and_render_deps():
    """The full (acquisition-inclusive) build also trims unused Qt modules for
    size — verified safe because grep shows the whole repo (acquisition_ui
    included) only uses QtWidgets/QtCore/QtGui. It must NOT break acquisition
    packaging, must keep the render/export Qt deps, and must keep QtNetwork
    (the one module pyqtgraph might import indirectly)."""
    script = ROOT / "tools" / "build_windows_folder.ps1"
    text = script.read_text(encoding="utf-8")

    # Unused Qt modules trimmed (mirror of the lite build).
    for module in (
        "PyQt5.QtWebEngine",
        "PyQt5.QtQml",
        "PyQt5.QtQuick",
        "PyQt5.QtMultimedia",
        "PyQt5.Qt3DRender",
    ):
        assert f'"{module}"' in text, f"full build should exclude {module}"

    # Render/export Qt deps must stay (pyqtgraph uses them indirectly).
    assert '"PyQt5.QtOpenGL"' in text
    for keep in ("PyQt5.QtSvg", "PyQt5.QtPrintSupport"):
        assert keep not in text, f"{keep} must NOT be excluded in the full build"

    # Conservative: QtNetwork kept in BOTH builds.
    assert "PyQt5.QtNetwork" not in text

    # Trimming Qt must not have disturbed acquisition packaging.
    assert "acquisition_capture.controller" in text
    assert "_vendor_pyxcp" in text
    assert '"--exclude-module", "pyxcp"' in text


def test_lite_build_keeps_qtnetwork_conservatively():
    """QtNetwork is intentionally NOT excluded in the lite build either — it is
    the only module pyqtgraph might import indirectly, and it is tiny."""
    script = ROOT / "tools" / "build_windows_folder_lite.ps1"
    text = script.read_text(encoding="utf-8")

    assert "PyQt5.QtNetwork" not in text


def test_lite_build_records_each_attempt_and_checks_environment_exit_codes():
    text = (ROOT / "tools/build_windows_folder_lite.ps1").read_text(encoding="utf-8")
    # Logging must start before validation/install; a failed attempt is evidence too.
    assert text.index("Start-Transcript") < text.index("foreach ($RequiredPath")
    assert "[guid]::NewGuid()" in text
    assert 'Join-Path $BuildEvidenceDir "build.log"' in text
    assert "Stop-Transcript" in text
    assert "BUILD FAILED" in text
    assert "$_.ScriptStackTrace" in text
    helper = text[text.index("function Invoke-LoggedNative"):text.index("function Invoke-BasePython")]
    assert "2>&1" in helper
    assert '$ErrorActionPreference = "Continue"' in helper
    assert "if ($nativeExitCode -ne 0)" in helper
    assert 'throw "Native command failed' in helper
    # No bootstrap, installer or smoke native call may bypass the checked logger.
    assert not re.search(r"^\s*& \$(VenvPython|pyLauncher|python)\b", text, re.MULTILINE)
    for arguments in (
        '@("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel")',
        '@("-m", "pip", "install", "-r", $Requirements)',
        '@("-m", "pip", "install", "--upgrade", "pyinstaller", "qtawesome")',
    ):
        assert "Invoke-LoggedNative -Executable $VenvPython -Arguments " + arguments in text


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows PowerShell 5.1")
@pytest.mark.parametrize("flavor", ["lite", "full"])
def test_windows_build_dependency_json_preserves_native_argument_boundaries(tmp_path, flavor):
    filename = "build_windows_folder_lite.ps1" if flavor == "lite" else "build_windows_folder.ps1"
    text = (ROOT / "tools" / filename).read_text(encoding="utf-8")
    dependency_json = subprocess.check_output(
        [sys.executable, str(ROOT / "tools/windows_runtime_dependencies.py"),
         "--pyinstaller-args-json", "--flavor", flavor],
        text=True,
    ).strip()
    expected = json.loads(dependency_json)
    # Execute the actual conversion and append statements, then inspect argv in
    # a native child. Merely testing JSON parsing misses PowerShell 5.1 nesting.
    conversion = re.search(r"^\s*\$RuntimeDependencyArgs = .+$", text, re.MULTILINE).group()
    append = re.search(r"^\$PyInstallerArgs \+= \$RuntimeDependencyArgs$", text, re.MULTILINE).group()
    child = tmp_path / "record arguments.py"
    output = tmp_path / "native argv.json"
    entry = tmp_path / "project with spaces" / "MF4 Data Analyzer V1.py"
    child.write_text(
        "import json, pathlib, sys\n"
        "pathlib.Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]), encoding='utf-8')\n",
        encoding="utf-8",
    )
    helper = ""
    invocation = "& $VenvPython @ChildArgs"
    if flavor == "lite":
        helper = text[text.index("function Invoke-LoggedNative"):text.index("function Invoke-BasePython")]
        invocation = "Invoke-LoggedNative -Executable $VenvPython -Arguments $ChildArgs"
    probe = "\n".join([
        '$ErrorActionPreference = "Stop"', 'Set-StrictMode -Version Latest', helper,
        f"$VenvPython = {_powershell_literal(Path(sys.executable))}",
        "$RuntimeDependencyArgsJson = '" + dependency_json.replace("'", "''") + "'",
        conversion,
        '$PyInstallerArgs = @("-m", "PyInstaller", "--collect-all", "qtawesome")',
        append,
        f"$PyInstallerArgs += {_powershell_literal(entry)}",
        f"$ChildArgs = @({_powershell_literal(child)}, {_powershell_literal(output)}) + $PyInstallerArgs",
        invocation,
        "if ($LASTEXITCODE -ne 0) { throw 'Native argv probe failed' }",
    ])
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", probe],
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(output.read_text(encoding="utf-8")) == [
        "-m", "PyInstaller", "--collect-all", "qtawesome", *expected, str(entry),
    ]


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows PowerShell 5.1")
@pytest.mark.parametrize("exit_code,capture", [(0, False), (23, False), (0, True)])
def test_lite_native_logger_keeps_stdout_stderr_and_exit_status(tmp_path, exit_code, capture):
    text = (ROOT / "tools/build_windows_folder_lite.ps1").read_text(encoding="utf-8")
    helper = text[text.index("function Invoke-LoggedNative"):text.index("function Invoke-BasePython")]
    child = tmp_path / "native output.py"
    child.write_text(
        'import sys\nprint(\'["stdout-first", "stdout-last"]\', flush=True)\n'
        'print("stderr-first\\nstderr-last", file=sys.stderr, flush=True)\n'
        f"sys.exit({exit_code})\n", encoding="utf-8",
    )
    transcript = tmp_path / "build.log"
    command = (
        f"Invoke-LoggedNative -Executable {_powershell_literal(Path(sys.executable))} "
        f"-Arguments @({_powershell_literal(child)})"
    )
    if capture:
        command = "$json = " + command + " -CaptureStdout\n$json | ConvertFrom-Json | Out-Null"
    probe = "\n".join([
        '$ErrorActionPreference = "Stop"', 'Set-StrictMode -Version Latest', helper,
        f"$BuildEvidenceDir = {_powershell_literal(tmp_path)}",
        f"Start-Transcript -LiteralPath {_powershell_literal(transcript)} | Out-Null",
        "try {", command, 'Write-Host "REACHED_AFTER_COMMAND"',
        '} finally { Stop-Transcript | Out-Null }',
    ])
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", probe],
        capture_output=True, text=True, timeout=30,
    )
    assert (completed.returncode == 0) == (exit_code == 0), completed.stderr
    log = transcript.read_text(encoding="utf-8-sig")
    for marker in ("stdout-first", "stdout-last", "stderr-first", "stderr-last"):
        assert marker in log
    assert f"Native exit code: {exit_code}" in log
    assert ("REACHED_AFTER_COMMAND\r" in log or "REACHED_AFTER_COMMAND\n" in log) == (exit_code == 0)


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows PowerShell 5.1")
def test_lite_early_failures_leave_separate_complete_transcripts(tmp_path):
    # Exercise the actual script, failing before any venv/install/output mutation.
    script = tmp_path / "tools/build_windows_folder_lite.ps1"
    script.parent.mkdir()
    script.write_bytes((ROOT / "tools/build_windows_folder_lite.ps1").read_bytes())
    for _ in range(2):
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode != 0
    logs = list((tmp_path / ".state/build-evidence/lite").glob("*/build.log"))
    assert len(logs) == 2
    for log in logs:
        text = log.read_text(encoding="utf-8-sig")
        assert "Required file not found" in text
        assert "BUILD FAILED at stage: Initializing" in text
        assert "Build succeeded: False" in text
        assert "PowerShell transcript end" in text


def test_windows_run_built_exe_wrapper_pauses_after_exit():
    wrapper = ROOT / "tools" / "run_windows_exe.bat"

    assert wrapper.exists()
    text = wrapper.read_text(encoding="utf-8").lower()

    assert "dist\\%appname%\\%appname%.exe" in text
    assert "exit code" in text
    assert "pause" in text


@pytest.mark.skipif(
    sys.platform != "win32", reason="executes powershell.exe against native .cmd"
)
def test_windows_builds_reject_failed_pyinstaller_before_reusing_old_exe_or_evidence(
    tmp_path,
):
    """Exit 23 must stop both flavors even when -KeepPrevious left a stale EXE."""
    fake_python = tmp_path / "failed-python.cmd"
    fake_python.write_text("@echo off\r\nexit /b 23\r\n", encoding="utf-8")

    for filename in ("build_windows_folder.ps1", "build_windows_folder_lite.ps1"):
        text = (ROOT / "tools" / filename).read_text(encoding="utf-8")
        is_lite = "_lite" in filename
        helper = ""
        if is_lite:
            invocation = text.index("Invoke-LoggedNative -Executable $VenvPython -Arguments $PyInstallerArgs")
            exit_capture = invocation
            helper = text[text.index("function Invoke-LoggedNative"):text.index("function Invoke-BasePython")]
        else:
            invocation = text.index("& $VenvPython @PyInstallerArgs")
            exit_capture = text.index("$PyInstallerExitCode = $LASTEXITCODE")
        exe_check = text.index("if (-not (Test-Path $ExePath))", invocation)
        smoke_step = text.index(
            'Write-Step "Verifying frozen batch rendering and importer runtime (independent post-checks)"'
            if is_lite else
            'Write-Step "Verifying frozen batch rendering (offscreen + windows)"'
        )
        offscreen_evidence = text.index(
            "$BatchRenderOffscreenSmokeEvidence =", 0, invocation
        )
        windows_evidence = text.index(
            "$BatchRenderWindowsSmokeEvidence =", 0, invocation
        )
        assert invocation <= exit_capture < exe_check < smoke_step
        assert offscreen_evidence < invocation
        assert windows_evidence < invocation

        flavor_directory = tmp_path / Path(filename).stem
        evidence_directory = flavor_directory / "evidence"
        old_exe = flavor_directory / "old" / "TraceLabProbe.exe"
        old_exe.parent.mkdir(parents=True)
        evidence_directory.mkdir(parents=True)
        old_exe.write_bytes(b"stale executable")
        stale_offscreen = (
            evidence_directory / "TraceLabProbe-batch-render-offscreen-smoke.json"
        )
        stale_windows = (
            evidence_directory / "TraceLabProbe-batch-render-windows-smoke.json"
        )
        stale_offscreen.write_text('{"stale": true}', encoding="utf-8")
        stale_windows.write_text('{"stale": true}', encoding="utf-8")

        gate = text[offscreen_evidence:smoke_step]
        probe = "\n".join(
            (
                '$ErrorActionPreference = "Stop"',
                'Set-StrictMode -Version Latest',
                '$AppName = "TraceLabProbe"',
                f"$BuildEvidenceDir = {_powershell_literal(evidence_directory)}",
                f"$VenvPython = {_powershell_literal(fake_python)}",
                "$PyInstallerArgs = @()",
                f"$ExePath = {_powershell_literal(old_exe)}",
                helper,
                gate,
            )
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", probe],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert completed.returncode != 0
        assert "failed with exit code 23" in (
            completed.stdout + completed.stderr
        )
        assert not stale_offscreen.exists()
        assert not stale_windows.exists()


@pytest.mark.parametrize(
    "filename",
    ("build_windows_folder.ps1", "build_windows_folder_lite.ps1"),
)
def test_frozen_render_smoke_runs_after_every_packaged_tree_mutation(filename):
    mutation_command = re.compile(
        r"^\s*(Copy-Item|Move-Item|Rename-Item|Set-Content|Add-Content|"
        r"Clear-Content|New-Item|Remove-Item)\b",
        re.IGNORECASE,
    )
    text = (ROOT / "tools" / filename).read_text(encoding="utf-8")
    smoke_command = (
        'Invoke-IndependentPostCheck -Name "offscreen"'
        if "_lite" in filename else "& $VenvPython $BatchRenderSmokeTool"
    )
    smoke = text.index(smoke_command)
    assert "--prune-internal" not in text
    if filename == "build_windows_folder.ps1":
        assert (
            text.index("Copy-Item -LiteralPath $sysDll -Destination $qtDll -Force")
            < smoke
        )
    else:
        assert (
            text.index("Remove-Item -LiteralPath $SciPyOpenBlas[0].FullName -Force")
            < smoke
        )
        assert text.index('Invoke-IndependentPostCheck -Name "windows"') > smoke
        importer = text.index('Invoke-IndependentPostCheck -Name "importer"')
        assert importer > smoke
        assert "verify_lite_importer_runtime.py" in text
        assert text.index("$ImporterSmokeTool") < smoke

    for line in text[smoke:].splitlines()[1:]:
        match = mutation_command.match(line)
        if match and "$PackagedSmokeJson" not in line:
            pytest.fail(
                f"{filename} mutates the finalized package after render smoke: "
                f"{line.strip()}"
            )


def test_lite_post_checks_are_independent_and_summarized_after_prune():
    text = (ROOT / "tools/build_windows_folder_lite.ps1").read_text(encoding="utf-8")
    helper = text[
        text.index("function Invoke-IndependentPostCheck"):
        text.index("function Invoke-BasePython")
    ]
    assert "aggregates exit codes" in helper
    assert not re.search(r"^\s*throw\b", helper, re.MULTILINE)
    assert "$process.Kill()" in helper
    assert "WaitForExit" in helper
    prune = text.index("Remove-Item -LiteralPath $SciPyOpenBlas[0].FullName -Force")
    offscreen = text.index('Invoke-IndependentPostCheck -Name "offscreen"')
    windows = text.index('Invoke-IndependentPostCheck -Name "windows"')
    importer = text.index('Invoke-IndependentPostCheck -Name "importer"')
    assert prune < offscreen < windows < importer
    assert "verify_lite_importer_runtime.py" in text
    assert "$ImporterSmokeTool" in text
    assert 'Write-Host "EXE generated: $exeGenerated"' in text
    assert 'Write-Host "offscreen: $off"' in text
    assert 'Write-Host "windows: $win"' in text
    assert 'Write-Host "importer: $imp"' in text
    assert "Test-AllPostChecksPassed" in text
    assert "function Invoke-LoggedNative" in text
    assert text.index("Invoke-LoggedNative -Executable $VenvPython -Arguments $PyInstallerArgs") < offscreen
    required = text[
        text.index("foreach ($RequiredPath in @("):
        text.index("if (-not (Test-Path $RequiredPath))")
    ]
    assert "$ImporterSmokeTool" in required


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows PowerShell 5.1")
@pytest.mark.parametrize("failed", ["offscreen", "windows", "importer"])
def test_lite_injected_post_check_failure_still_collects_the_others(tmp_path, failed):
    text = (ROOT / "tools/build_windows_folder_lite.ps1").read_text(encoding="utf-8")
    helper = text[
        text.index("function ConvertTo-Win32ArgumentList"):
        text.index("function Invoke-BasePython")
    ]
    ok_child = tmp_path / "ok.py"
    fail_child = tmp_path / "fail.py"
    ok_child.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    fail_child.write_text("import sys\nsys.exit(23)\n", encoding="utf-8")
    names = ("offscreen", "windows", "importer")
    children = {
        name: fail_child if name == failed else ok_child for name in names
    }
    exe = tmp_path / "TraceLabProbe.exe"
    exe.write_bytes(b"fake")
    calls = []
    for name in names:
        child = children[name]
        calls.append(
            f'Invoke-IndependentPostCheck -Name "{name}" '
            f"-Executable {_powershell_literal(Path(sys.executable))} "
            f"-Arguments @({_powershell_literal(child)}) -TimeoutSeconds 15"
        )
    probe = "\n".join(
        [
            '$ErrorActionPreference = "Stop"',
            "Set-StrictMode -Version Latest",
            helper,
            "$script:PostCheckResults = New-Object System.Collections.ArrayList",
            "$script:ExeGenerated = $true",
            f"$ExePath = {_powershell_literal(exe)}",
            *calls,
            "Write-PostCheckSummary",
            "if (Test-AllPostChecksPassed) { $BuildSucceeded = $true } else { $BuildSucceeded = $false }",
            'Write-Host "Build succeeded: $BuildSucceeded"',
        ]
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", probe],
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert "EXE generated: True" in output
    for name in names:
        expected = "failed" if name == failed else "passed"
        assert f"{name}: {expected}" in output
    assert "Build succeeded: False" in output
    assert "Build succeeded: True" not in output.replace("Build succeeded: False", "")


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows PowerShell 5.1")
def test_lite_post_check_timeout_kills_child_then_runs_the_next(tmp_path):
    text = (ROOT / "tools/build_windows_folder_lite.ps1").read_text(encoding="utf-8")
    helper = text[
        text.index("function ConvertTo-Win32ArgumentList"):
        text.index("function Invoke-BasePython")
    ]
    hang = tmp_path / "hang.py"
    ok_child = tmp_path / "ok.py"
    hang.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    ok_child.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    probe = "\n".join(
        [
            '$ErrorActionPreference = "Stop"',
            "Set-StrictMode -Version Latest",
            helper,
            "$script:PostCheckResults = New-Object System.Collections.ArrayList",
            "$script:ExeGenerated = $true",
            f"$ExePath = {_powershell_literal(tmp_path / 'TraceLabProbe.exe')}",
            f'Invoke-IndependentPostCheck -Name "offscreen" -Executable {_powershell_literal(Path(sys.executable))} -Arguments @({_powershell_literal(hang)}) -TimeoutSeconds 2',
            f'Invoke-IndependentPostCheck -Name "windows" -Executable {_powershell_literal(Path(sys.executable))} -Arguments @({_powershell_literal(ok_child)}) -TimeoutSeconds 15',
            f'Invoke-IndependentPostCheck -Name "importer" -Executable {_powershell_literal(Path(sys.executable))} -Arguments @({_powershell_literal(ok_child)}) -TimeoutSeconds 15',
            "Write-PostCheckSummary",
            "if (Test-AllPostChecksPassed) { $BuildSucceeded = $true } else { $BuildSucceeded = $false }",
            'Write-Host "Build succeeded: $BuildSucceeded"',
        ]
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", probe],
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert "offscreen: timeout" in output
    assert "windows: passed" in output
    assert "importer: passed" in output
    assert "Build succeeded: False" in output
    assert "process terminated" in output
