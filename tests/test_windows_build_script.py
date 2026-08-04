from pathlib import Path
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
        "--collect-all",
        "qtawesome",
        "MF4 Data Analyzer V1.py",
        "TraceLab7.9.3",
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

    assert r".\dist\TraceLab7.9.3\TraceLab7.9.3.exe" in runbook
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
        assert "--platform offscreen" in text
        assert "--platform windows" in text
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
        "--collect-all",
        "qtawesome",
        "MF4 Data Analyzer V1.py",
    ):
        assert token in text, f"lite build script must contain {token!r}"


def test_windows_build_scripts_default_to_current_release():
    for filename in ("build_windows_folder.ps1", "build_windows_folder_lite.ps1"):
        script = ROOT / "tools" / filename
        text = script.read_text(encoding="utf-8")

        assert '[string]$Version = "7.9.3"' in text

    lite_script = ROOT / "tools" / "build_windows_folder_lite.ps1"
    assert "TraceLabAnalyzer7.9.3" in lite_script.read_text(encoding="utf-8")


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
    for keep in ("PyQt5.QtOpenGL", "PyQt5.QtSvg", "PyQt5.QtPrintSupport"):
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
    for keep in ("PyQt5.QtOpenGL", "PyQt5.QtSvg", "PyQt5.QtPrintSupport"):
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
        invocation = text.index("& $VenvPython @PyInstallerArgs")
        exit_capture = text.index("$PyInstallerExitCode = $LASTEXITCODE")
        exe_check = text.index("if (-not (Test-Path $ExePath))", invocation)
        smoke_step = text.index(
            'Write-Step "Verifying frozen batch rendering (offscreen + windows)"'
        )
        offscreen_evidence = text.index(
            "$BatchRenderOffscreenSmokeEvidence =", 0, invocation
        )
        windows_evidence = text.index(
            "$BatchRenderWindowsSmokeEvidence =", 0, invocation
        )
        assert invocation < exit_capture < exe_check < smoke_step
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
        assert "PyInstaller failed with exit code 23" in (
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
    smoke = text.index("& $VenvPython $BatchRenderSmokeTool")
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

    for line in text[smoke:].splitlines()[1:]:
        match = mutation_command.match(line)
        if match and "$PackagedSmokeJson" not in line:
            pytest.fail(
                f"{filename} mutates the finalized package after render smoke: "
                f"{line.strip()}"
            )
