from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
        "asammdf",
        "MF4 Data Analyzer V1.py",
        "TraceLab7.5",
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


def test_windows_folder_build_script_excludes_matplotlib_and_scipy():
    """The app dropped matplotlib + scipy; the package must not re-bundle them.

    ``--collect-submodules pyqtgraph`` pulls in pyqtgraph's MatplotlibWidget /
    MatplotlibExporter submodules, which ``import matplotlib`` — so without an
    explicit exclude PyInstaller follows that import and bundles matplotlib
    (plus its PIL/contourpy/kiwisolver/cycler/fontTools deps), bloating the
    package with code the app no longer uses. The exclude list mirrors the
    matplotlib→pyqtgraph migration's local .spec.
    """
    script = ROOT / "tools" / "build_windows_folder.ps1"

    assert script.exists()
    text = script.read_text(encoding="utf-8")

    for module in ("matplotlib", "scipy"):
        assert f'"--exclude-module", "{module}"' in text, (
            f"build script must --exclude-module {module} so PyInstaller does "
            f"not re-bundle the removed dependency via collect-submodules pyqtgraph"
        )


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


def test_windows_run_built_exe_wrapper_pauses_after_exit():
    wrapper = ROOT / "tools" / "run_windows_exe.bat"

    assert wrapper.exists()
    text = wrapper.read_text(encoding="utf-8").lower()

    assert "dist\\%appname%\\%appname%.exe" in text
    assert "exit code" in text
    assert "pause" in text
