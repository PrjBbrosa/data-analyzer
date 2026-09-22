from pathlib import Path
import json
import sys
import zipfile

import pytest

from mf4_analyzer.app_meta import APP_VERSION
from mf4_analyzer.extensions.contract import (
    parse_discovery_envelope,
    parse_package_manifest,
)
from mf4_analyzer.extensions.native_identity import sha256_file
from mf4_analyzer.extensions.runtime_recipe import compute_python_build_id
from mf4_analyzer.extensions.state import bind_core_payloads
from mf4_analyzer.io.runtime_dependencies import DEFAULT_DEPENDENCY_PROFILE


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_windows_extensions import (  # noqa: E402
    UnsupportedDeliveryCombination,
    collection_plan,
    content_addressed_zip_name,
    emit_delivery,
    is_pyinstaller_archive_member,
    main as emit_main,
    refuse_pyinstaller_payload,
    require_supported_combination,
)


_PYTHON_BUILD = compute_python_build_id(
    implementation_name="CPython",
    hexversion=0x030B09F0,
    soabi="cp311",
    compiler="MSC v.1938 64 bit (AMD64)",
)
_RUNTIME_KWARGS = {
    "python_implementation": "CPython",
    "python_version": "3.11.9",
    "python_abi": "cp311",
    "python_build_id": _PYTHON_BUILD,
    "arch": "win-amd64",
    "numpy_version": "1.26.4",
    "numpy_abi": "cp311",
}


def _write(path: Path, data: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    return path


def _core_tree(root: Path) -> Path:
    _write(root / "TraceLabAnalyzer-modular.exe", b"MZ-core-executable-bytes")
    _write(root / "_internal" / "python311.dll", b"cpython-shared-artifact-build-a")
    _write(root / "_internal" / "numpy.libs" / "libopenblas.dll", b"numpy-openblas-artifact-build-a")
    _write(root / "_internal" / "numpy" / "__init__.py", "x = 1\n")
    return root


def _site_packages(root: Path) -> Path:
    _write(root / "av" / "__init__.py", "backend = 'pyav'\n")
    _write(root / "av" / "av.pyd", b"pyd-av")
    _write(root / "av.libs" / "av-1.dll", b"av-native-dll")
    _write(
        root / "av-1.0.dist-info" / "METADATA",
        "Name: av\nRequires-Dist: numpy\n",
    )
    _write(root / "av-1.0.dist-info" / "LICENSE", "PyAV license\n")
    _write(root / "scipy" / "io" / "__init__.py", "def loadmat():\n    return {}\n")
    _write(root / "scipy" / "io" / "matlab" / "__init__.py", "")
    _write(root / "h5py" / "__init__.py", "class File:\n    pass\n")
    _write(root / "h5py.libs" / "hdf5.dll", b"h5-native-dll")
    _write(root / "scipy-1.0.dist-info" / "METADATA", "Name: scipy\n")
    _write(root / "h5py-1.0.dist-info" / "METADATA", "Name: h5py\n")
    _write(root / "hdf5storage" / "__init__.py", "")
    return root


def test_default_profile_is_bundled_and_only_lite_modular_is_released():
    assert DEFAULT_DEPENDENCY_PROFILE == "bundled"
    require_supported_combination("lite", "modular")
    with pytest.raises(UnsupportedDeliveryCombination, match="lite\\+modular"):
        require_supported_combination("lite", "bundled")
    with pytest.raises(UnsupportedDeliveryCombination, match="lite\\+modular"):
        require_supported_combination("full", "modular")
    with pytest.raises(UnsupportedDeliveryCombination, match="lite\\+modular"):
        require_supported_combination("full", "bundled")


def test_cli_defaults_to_bundled_and_rejects_it(tmp_path):
    code = emit_main(
        [
            "--app-root",
            str(tmp_path),
            "--exe-relpath",
            "missing.exe",
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert code == 2


def test_collection_plan_comes_from_unified_manifest():
    plan = collection_plan("lite", "modular")
    assert "--exclude-module" in plan["pyinstaller_args"]
    assert "av" in plan["base_exclude"]
    assert "av" not in plan["base_collect"]
    assert plan["component_collect"]["media"] == ["av"]
    assert "scipy" in plan["component_collect"]["matlab"]
    assert "h5py" in plan["component_collect"]["matlab"]


def test_component_zip_is_importable_tree_not_pyz(tmp_path):
    app_root = _core_tree(tmp_path / "app")
    site = _site_packages(tmp_path / "site-packages")
    delivery = emit_delivery(
        flavor="lite",
        profile="modular",
        app_root=app_root,
        exe_relpath="TraceLabAnalyzer-modular.exe",
        site_packages=site,
        output_dir=tmp_path / "out",
        runtime_kwargs=_RUNTIME_KWARGS,
        python_tag="cp311",
        platform_tag="win_amd64",
    )
    zips = {item["component"]: Path(item["zip"]) for item in delivery["components"]}
    assert zips["media"].name == content_addressed_zip_name(
        "media", delivery["components"][0]["files_digest"]
    )
    with zipfile.ZipFile(zips["media"]) as archive:
        names = archive.namelist()
        assert "package.json" in names
        assert "site-packages/av/__init__.py" in names
        assert "site-packages/av-1.0.dist-info/METADATA" in names
        assert not any(is_pyinstaller_archive_member(name) for name in names)
        source = archive.read("site-packages/av/__init__.py")
        compile(source, "av/__init__.py", "exec")
    assert delivery["core"]["app_version"] == APP_VERSION
    envelope = parse_discovery_envelope((app_root / "core.json").read_bytes())
    assert envelope.exe_relpath == "TraceLabAnalyzer-modular.exe"
    assert envelope.core_build_id == delivery["core"]["core_build_id"]
    assert envelope.runtime_id == delivery["core"]["runtime_id"]
    bind_core_payloads(
        (app_root / "core.json").read_text(encoding="utf-8"),
        (app_root / "core-files.json").read_text(encoding="utf-8"),
    )
    parse_package_manifest((tmp_path / "out" / "staging" / "media" / "package.json").read_bytes())
    assert delivery["manager"]["placeholder"] is True
    assert delivery["manager"]["sha256"] is None
    assert (app_root / "licenses.json").is_file()
    assert (app_root / "dependency-list.json").is_file()
    assert delivery["audit"]["ok"] is True
    assert delivery["audit"]["pyz_audit"] == "unknown"


def test_manager_copy_uses_real_bytes_and_does_not_invent_hash(tmp_path):
    app_root = _core_tree(tmp_path / "app")
    site = _site_packages(tmp_path / "site-packages")
    manager = _write(tmp_path / "tested-installer.exe", b"MZ-tested-manager")
    (tmp_path / "manager-build.json").write_text(json.dumps({
        "sha256": sha256_file(manager), "size": manager.stat().st_size,
        "manager_version": "1.0.0", "self_test": {"ok": True, "frozen": True, "manager_version": "1.0.0"},
    }))
    delivery = emit_delivery(
        flavor="lite",
        profile="modular",
        app_root=app_root,
        exe_relpath="TraceLabAnalyzer-modular.exe",
        site_packages=site,
        output_dir=tmp_path / "out",
        runtime_kwargs=_RUNTIME_KWARGS,
        manager_source=manager,
        python_tag="cp311",
        platform_tag="win_amd64",
    )
    copied = app_root / "installer.exe"
    assert copied.read_bytes() == manager.read_bytes()
    assert delivery["manager"]["sha256"] == sha256_file(copied)
    assert delivery["manager"]["placeholder"] is False
    payload = json.loads((app_root / "manager-delivery.json").read_text(encoding="utf-8"))
    assert payload["manager_version"] == "1.0.0"
    assert APP_VERSION not in str(payload["manager_version"])


def test_same_basename_dll_conflict_refuses_combination(tmp_path):
    app_root = _core_tree(tmp_path / "app")
    site = _site_packages(tmp_path / "site-packages")
    _write(site / "av.libs" / "libopenblas.dll", b"different-openblas-bytes")
    with pytest.raises(Exception, match="NATIVE_DLL_CONFLICT"):
        emit_delivery(
            flavor="lite",
            profile="modular",
            app_root=app_root,
            exe_relpath="TraceLabAnalyzer-modular.exe",
            site_packages=site,
            output_dir=tmp_path / "out",
            runtime_kwargs=_RUNTIME_KWARGS,
            python_tag="cp311",
            platform_tag="win_amd64",
        )


def test_refuses_pyinstaller_pyz_as_component_payload():
    with pytest.raises(Exception, match="PyInstaller"):
        refuse_pyinstaller_payload(["site-packages/av/__init__.py", "PYZ.pyz"])


def test_unix_native_is_refused_for_win_amd64(tmp_path):
    app_root = _core_tree(tmp_path / "app")
    site = _site_packages(tmp_path / "site-packages")
    _write(site / "av" / "core.so", b"not-a-windows-dll")
    with pytest.raises(Exception, match="Unix native"):
        emit_delivery(
            flavor="lite",
            profile="modular",
            app_root=app_root,
            exe_relpath="TraceLabAnalyzer-modular.exe",
            site_packages=site,
            output_dir=tmp_path / "out",
            runtime_kwargs=_RUNTIME_KWARGS,
            python_tag="cp311",
            platform_tag="win_amd64",
        )
