"""Keep bundle slimming scoped, dependency-checked, and ahead of acceptance."""
from pathlib import Path

import pytest

from tools import windows_bundle_policy as policy


def test_lite_excludes_optional_sql_and_highlighting_but_full_preserves_them():
    for flavor in ("full", "lite"):
        excluded = policy.excluded_modules(flavor)
        assert {"pytest", "_pytest", "nptdms.test", "asammdf.gui",
                "pyqtgraph.examples", "pyqtgraph.opengl", "PIL._avif"} <= set(excluded)
        assert not {"numpy", "pandas", "lxml.etree", "can", "av", "scipy", "h5py"} & set(excluded)
    assert {"sqlalchemy", "pygments"} <= set(policy.excluded_modules("lite"))
    assert not {"sqlalchemy", "pygments"} & set(policy.excluded_modules("full"))
    with pytest.raises(ValueError):
        policy.excluded_modules("unknown")


def test_precise_resource_selection_preserves_runtime_data_and_vendor_sources():
    modules = {"asammdf.mdf", "openpyxl", "nptdms.tdms"}
    for name in ("PyQt5/Qt5/bin/opengl32sw.dll", "PyQt5/Qt5/bin/libEGL.dll",
                 "PyQt5/Qt5/bin/Qt5Qml.dll", "PyQt5/Qt5/plugins/platforms/qwebgl.dll",
                 "PyQt5/Qt5/translations/qtbase_de.qm", "asammdf/gui/ui/resource_rc.py",
                 "nptdms/test/test_tdms.py", "asammdf/mdf.py", "openpyxl/__init__.py",
                 "pyqtgraph/icons/peegee/peegee_512px.png"):
        assert policy.prune_reason(Path(name), modules), name
    for name in ("PyQt5/Qt5/plugins/platforms/qwindows.dll",
                 "PyQt5/Qt5/plugins/platforms/qoffscreen.dll",
                 "PyQt5/Qt5/bin/Qt5Gui.dll", "PyQt5/Qt5/bin/MSVCP140.dll",
                 "PyQt5/Qt5/translations/qtbase_zh_CN.qm",
                 "PyQt5/Qt5/translations/qtbase_en.qm", "PyQt5/Qt5/bin/future.dll",
                 "numpy.libs/libscipy_openblas.dll", "av/codec.pyd",
                 "asammdf/blocks/unrecognized.py", "asammdf/blocks/schema.xsd",
                 "qtawesome/fonts/materialdesignicons.ttf", "mf4_analyzer/help/a.png",
                 "pyqtgraph/icons/auto.png", "pyqtgraph/icons/peegee/peegee.svg",
                 "_vendor_pya2l/sqlalchemy/orm.py", "_vendor_pyxcp/pygments/lexer.py"):
        assert policy.prune_reason(Path(name), modules) is None, name


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    root = tmp_path / "output"
    internal = root / "_internal"
    for name in policy.REQUIRED_FILES:
        dest = internal / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"runtime")
    removable = internal / "PyQt5/Qt5/bin/opengl32sw.dll"
    removable.write_bytes(b"unused GL")
    exe = root / "TraceLab.exe"
    exe.write_bytes(b"frozen exe")
    monkeypatch.setattr(policy, "read_frozen_modules", lambda _: {"mf4_analyzer.app"})
    monkeypatch.setattr(policy, "read_pe_imports", lambda _: set())
    return exe, removable, tmp_path / "evidence/report.json"


def test_prune_records_bytes_and_does_not_change_exe(bundle):
    exe, removable, report = bundle
    result = policy.prune_bundle(exe, "lite", report)
    assert not removable.exists()
    assert exe.read_bytes() == b"frozen exe"
    assert result["removed_bytes"] == len(b"unused GL")
    assert result["before_bytes"] - result["after_bytes"] == result["removed_bytes"]
    assert report.is_file()


def test_dry_run_does_not_modify_bundle(bundle):
    exe, removable, report = bundle
    result = policy.prune_bundle(exe, "lite", report, dry_run=True)
    assert removable.exists()
    assert result["removed_bytes"] == 0
    assert result["candidate_bytes"] == len(b"unused GL")


@pytest.mark.parametrize("case", ["compatible", "older", "wrong_arch", "missing_export", "missing_canonical", "bundled"])
def test_modular_crt_dedup_requires_compatible_canonical_before_any_deletion(bundle, monkeypatch, case):
    exe, removable, report = bundle
    internal = exe.parent / "_internal"
    canonical = internal / "VCRUNTIME140.dll"
    duplicate = internal / "PyQt5/Qt5/bin/VCRUNTIME140.dll"
    duplicate.write_bytes(b"Qt older CRT")
    if case != "missing_canonical":
        canonical.write_bytes(b"Python newer CRT")
    old = (0x8664, (14, 26, 0, 0), {(1, b"memcpy")})
    current = (0x8664, (14, 42, 0, 0), {(1, b"memcpy"), (2, b"extra")})
    if case == "older":
        current = (current[0], (14, 20, 0, 0), current[2])
    elif case == "wrong_arch":
        current = (0xAA64, current[1], current[2])
    elif case == "missing_export":
        current = (current[0], current[1], {(2, b"extra")})
    monkeypatch.setattr(policy, "read_pe_runtime_signature", lambda p: current if p == canonical else old)
    monkeypatch.setattr(policy, "read_pe_imports", lambda _: {"VCRUNTIME140.dll"})
    if case in {"compatible", "bundled"}:
        result = policy.prune_bundle(exe, "lite", report, profile="bundled" if case == "bundled" else "modular")
        assert duplicate.exists() == (case == "bundled")
        assert canonical.read_bytes() == b"Python newer CRT"
        assert result["status"] == "pruned"
    else:
        with pytest.raises(ValueError, match="MSVC runtime"):
            policy.prune_bundle(exe, "lite", report, profile="modular")
        assert duplicate.exists()
        assert removable.exists()


def test_native_dependency_blocks_entire_prune_before_any_deletion(bundle, monkeypatch):
    exe, removable, report = bundle
    monkeypatch.setattr(policy, "read_pe_imports", lambda _: {"OPENGL32SW.dll"})
    with pytest.raises(ValueError, match="depends on"):
        policy.prune_bundle(exe, "lite", report)
    assert removable.exists()


def test_excluded_code_in_pyz_is_a_build_failure(bundle, monkeypatch):
    exe, removable, report = bundle
    monkeypatch.setattr(policy, "read_frozen_modules", lambda _: {"_pytest.config"})
    with pytest.raises(ValueError, match="_pytest.config"):
        policy.prune_bundle(exe, "lite", report)
    assert removable.exists()


def test_missing_required_plugin_blocks_pruning(bundle):
    exe, removable, report = bundle
    (exe.parent / "_internal/PyQt5/Qt5/plugins/platforms/qwindows.dll").unlink()
    with pytest.raises(ValueError, match="qwindows.dll"):
        policy.prune_bundle(exe, "lite", report)
    assert removable.exists()


def test_report_cannot_overwrite_bundle_file(bundle):
    exe, removable, _ = bundle
    with pytest.raises(ValueError, match="report"):
        policy.prune_bundle(exe, "lite", exe)
    assert removable.exists()
    assert exe.read_bytes() == b"frozen exe"


def test_symlink_is_rejected_before_pruning(bundle, tmp_path):
    exe, removable, report = bundle
    outside = tmp_path / "outside.dll"
    outside.write_bytes(b"keep")
    removable.unlink()
    try:
        removable.symlink_to(outside)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("This Windows session lacks permission to create symlinks")
        raise
    with pytest.raises(ValueError, match="link"):
        policy.prune_bundle(exe, "lite", report)
    assert outside.read_bytes() == b"keep"


@pytest.mark.parametrize("script_name", ["build_windows_folder.ps1",
    "build_windows_folder_lite.ps1", "build_windows_folder_lite_modular.ps1"])
def test_all_builders_use_policy_and_prune_before_frozen_checks(script_name):
    root = Path(__file__).resolve().parents[1]
    text = (root / "tools" / script_name).read_text(encoding="utf-8")
    assert "windows_bundle_policy.py" in text
    assert "$PyInstallerArgs += $BundlePolicyArgs" in text
    assert '"--collect-submodules", "pyqtgraph"' not in text
    assert '"--hidden-import", "pyqtgraph"' in text
    assert '"--hidden-import", "qtawesome"' in text
    assert '"PyQt5.QtOpenGL"' in text
    prune = text.index('Write-Step "Pruning unused bundle payloads"')
    assert prune < text.index('Write-Step "Verifying frozen batch rendering')
    assert "bundle-prune.json" in text
