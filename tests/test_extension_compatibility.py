"""Install / load compatibility rules for optional extensions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mf4_analyzer.extensions.contract import (
    ExtensionError,
    ReasonCode,
    can_reuse_installed_package,
    compute_runtime_id,
    evaluate_install_compatibility,
    evaluate_load_compatibility,
    generate_discovery_envelope,
    generate_package_manifest,
    generate_receipt,
    parse_core_files,
    parse_discovery_envelope,
    parse_package_manifest,
    parse_receipt,
    sha256_hex,
)
from mf4_analyzer.extensions.native_identity import (
    KIND_NATIVE_SHARED,
    KIND_PYTHON_MODULE,
    NativeIdentityError,
    OWNER_BASE,
    OWNER_MATLAB,
    OWNER_MEDIA,
    REASON_NATIVE_DLL_CONFLICT,
    SharedLibraryIdentity,
    assert_native_combination,
    collect_file_identities,
    find_native_conflicts,
)
from mf4_analyzer.extensions.runtime_recipe import compute_python_build_id
from mf4_analyzer.extensions.state import (
    bind_core_identity,
    bind_core_payloads,
    load_active_state,
    resolve_inside,
    verify_receipt,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "extensions"

_PYTHON_BUILD_A = compute_python_build_id(
    implementation_name="CPython",
    hexversion=0x030B09F0,
    soabi="cp311",
    compiler="MSC v.1938 64 bit (AMD64)",
)
_PYTHON_DLL = hashlib.sha256(b"cpython-shared-artifact-build-a").hexdigest()
_NUMPY_DLL = hashlib.sha256(b"numpy-openblas-artifact-build-a").hexdigest()

_RUNTIME_A = dict(
    python_implementation="CPython",
    python_version="3.11.9",
    python_abi="cp311",
    python_build_id=_PYTHON_BUILD_A,
    arch="win-amd64",
    numpy_version="1.26.4",
    numpy_abi="cp311",
    core_shared_libraries=(
        SharedLibraryIdentity(
            name="python",
            role="cpython_shared",
            basename="python311.dll",
            sha256=_PYTHON_DLL,
        ),
        SharedLibraryIdentity(
            name="numpy",
            role="capi",
            basename="libopenblas.dll",
            sha256=_NUMPY_DLL,
        ),
    ),
)


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _envelope(**overrides):
    runtime_id = overrides.pop("runtime_id", compute_runtime_id(**_RUNTIME_A))
    payload = generate_discovery_envelope(
        exe_relpath=overrides.pop("exe_relpath", "TraceLabAnalyzer.exe"),
        core_build_id=overrides.pop("core_build_id", "cb1-" + "a" * 64),
        runtime_id=runtime_id,
        component_capabilities=overrides.pop("component_capabilities", {"media": "1", "matlab": "1"}),
        min_manager_version=overrides.pop("min_manager_version", "1.0.0"),
        manager_download_page="https://example.invalid/tracelab/extension-manager",
        app_version=overrides.pop("app_version", "v8.3.1"),
        protocol_major=overrides.pop("protocol_major", 1),
        protocol_minor=overrides.pop("protocol_minor", 0),
        exe_sha256=overrides.pop("exe_sha256", None),
        core_files_digest=overrides.pop("core_files_digest", None),
    )
    payload.update(overrides)
    return parse_discovery_envelope(payload)


def _package(**overrides):
    payload = generate_package_manifest(
        component=overrides.pop("component", "media"),
        package_revision=overrides.pop("package_revision", 1),
        runtime_id=overrides.pop("runtime_id", compute_runtime_id(**_RUNTIME_A)),
        component_api=overrides.pop("component_api", "1"),
        min_manager_version=overrides.pop("min_manager_version", "1.0.0"),
        python_tag="cp311",
        platform_tag="win_amd64",
        module_roots=["site-packages/av"],
        dll_directories=["native/av"],
        dependency_ownership={"av": "media"},
        files=[
            {
                "relpath": "site-packages/av/__init__.py",
                "size": 16,
                "sha256": "d" * 64,
            }
        ],
        max_extract_bytes=1024,
        probe_type="media_wav_mp4_v1",
    )
    payload.update(overrides)
    return parse_package_manifest(payload)


def test_same_runtime_ui_upgrade_reuses_installed_package():
    runtime_id = compute_runtime_id(**_RUNTIME_A)
    previous = _envelope(app_version="v8.3.1", core_build_id="cb1-" + "a" * 64, runtime_id=runtime_id)
    upgraded = _envelope(app_version="v8.4.0", core_build_id="cb1-" + "b" * 64, runtime_id=runtime_id)
    package = _package(runtime_id=runtime_id, component_api="1")

    assert previous.app_version != upgraded.app_version
    assert previous.core_build_id != upgraded.core_build_id
    assert previous.runtime_id == upgraded.runtime_id
    assert can_reuse_installed_package(
        previous_core=previous,
        new_core=upgraded,
        package=package,
    )
    load = evaluate_load_compatibility(core=upgraded, package=package, files_verified=True)
    assert load.allowed
    assert load.reason_code is None


def test_python_numpy_or_arch_change_rejects_old_package():
    old_runtime = compute_runtime_id(**_RUNTIME_A)
    new_runtime = compute_runtime_id(**{**_RUNTIME_A, "python_version": "3.12.0"})
    numpy_runtime = compute_runtime_id(**{**_RUNTIME_A, "numpy_abi": "cp312"})
    arch_runtime = compute_runtime_id(**{**_RUNTIME_A, "arch": "win-arm64"})
    package = _package(runtime_id=old_runtime)

    for runtime_id in (new_runtime, numpy_runtime, arch_runtime):
        core = _envelope(runtime_id=runtime_id)
        install = evaluate_install_compatibility(
            core=core,
            package=package,
            manager_version="1.0.0",
        )
        load = evaluate_load_compatibility(core=core, package=package, files_verified=True)
        assert not install.allowed
        assert not load.allowed
        assert install.reason_code == ReasonCode.COMPONENT_INCOMPATIBLE
        assert load.reason_code == ReasonCode.COMPONENT_INCOMPATIBLE
        assert install.update_target == "package"


def test_component_api_change_requires_new_package_not_manager():
    runtime_id = compute_runtime_id(**_RUNTIME_A)
    core = _envelope(runtime_id=runtime_id, component_capabilities={"media": "2", "matlab": "1"})
    package = _package(runtime_id=runtime_id, component_api="1")
    decision = evaluate_install_compatibility(core=core, package=package, manager_version="1.0.0")
    assert not decision.allowed
    assert decision.reason_code == ReasonCode.COMPONENT_INCOMPATIBLE
    assert decision.update_target == "package"
    assert decision.reason_code != ReasonCode.MANAGER_TOO_OLD


def test_old_manager_reads_new_discovery_envelope():
    envelope = parse_discovery_envelope(_load("discovery-new-protocol.json"))
    assert envelope.discovery_schema == 1
    assert envelope.min_manager_version == "2.0.0"
    assert envelope.manager_download_page.endswith("/extension-manager")
    assert envelope.protocol_major == 2
    assert envelope.extras["future_inner_field"]["algorithm"] == "not-understood-by-v1"
    assert not envelope.protocol_understood

    decision = evaluate_install_compatibility(
        core=envelope,
        package=None,
        manager_version="1.0.0",
    )
    assert not decision.allowed
    assert decision.reason_code == ReasonCode.MANAGER_TOO_OLD
    assert decision.update_target == "manager"

    load = evaluate_load_compatibility(
        core=_envelope(runtime_id=envelope.runtime_id, component_capabilities={"media": "2"}),
        package=_package(runtime_id=envelope.runtime_id, component_api="2"),
        files_verified=True,
        installer_available=False,
        manager_version="0.0.1",
    )
    assert load.allowed


def test_mixed_core_exe_and_hash_are_rejected():
    files = parse_core_files(_load("core-files-valid.json"))
    mixed_hash = parse_discovery_envelope(_load("core-mixed-hash.json"))
    mixed_exe = parse_discovery_envelope(_load("core-mixed-exe.json"))

    with pytest.raises(ExtensionError) as hash_info:
        bind_core_identity(mixed_hash, files)
    assert hash_info.value.reason_code == ReasonCode.CORE_INCONSISTENT

    with pytest.raises(ExtensionError) as exe_info:
        bind_core_identity(mixed_exe, files)
    assert exe_info.value.reason_code == ReasonCode.CORE_INCONSISTENT

    with pytest.raises(ExtensionError) as overlay:
        bind_core_payloads(_load("core-valid.json"), _load("core-files-mixed.json"))
    assert overlay.value.reason_code == ReasonCode.CORE_INCONSISTENT

    identity = bind_core_payloads(_load("core-valid.json"), _load("core-files-valid.json"))
    assert identity.exe_relpath == "TraceLabAnalyzer.exe"


def test_load_does_not_require_installer_or_min_manager_version():
    runtime_id = compute_runtime_id(**_RUNTIME_A)
    core = _envelope(runtime_id=runtime_id, min_manager_version="9.0.0")
    package = _package(runtime_id=runtime_id, min_manager_version="9.0.0")

    load = evaluate_load_compatibility(
        core=core,
        package=package,
        files_verified=True,
        installer_available=False,
        manager_version="0.1.0",
    )
    assert load.allowed

    install = evaluate_install_compatibility(
        core=core,
        package=package,
        manager_version="0.1.0",
    )
    assert not install.allowed
    assert install.reason_code == ReasonCode.MANAGER_TOO_OLD


def test_no_compatible_package_is_not_a_manager_update():
    core = _envelope()
    decision = evaluate_install_compatibility(core=core, package=None, manager_version="1.0.0")
    assert decision.reason_code == ReasonCode.NO_COMPATIBLE_PACKAGE
    assert decision.update_target == "package"


def test_tampered_receipt_or_package_json_fails_verification():
    package_bytes = _load("package-valid.json")
    package = parse_package_manifest(package_bytes)
    package_sha256 = sha256_hex(b"zip-bytes")
    receipt_payload = generate_receipt(
        core_build_id="cb1-" + "a" * 64,
        package=package,
        package_sha256=package_sha256,
        package_json_sha256=sha256_hex(package_bytes),
        probe_ok=True,
    )
    receipt = parse_receipt(receipt_payload)
    trusted_json_hash = sha256_hex(package_bytes)
    verify_receipt(
        receipt,
        package_json_bytes=package_bytes,
        package=package,
        package_sha256=package_sha256,
        trusted_target_id=trusted_json_hash,
    )

    tampered_package = json.loads(package_bytes)
    tampered_package["notes"] = "rewritten"
    tampered_bytes = json.dumps(tampered_package).encode("utf-8")
    with pytest.raises(ExtensionError) as tampered_json:
        verify_receipt(
            receipt,
            package_json_bytes=tampered_bytes,
            package=parse_package_manifest(tampered_bytes),
            package_sha256=package_sha256,
            trusted_target_id=trusted_json_hash,
        )
    assert tampered_json.value.reason_code == ReasonCode.VERIFICATION_FAILED

    tampered_receipt_payload = dict(receipt_payload)
    tampered_receipt_payload["package_json_sha256"] = sha256_hex(tampered_bytes)
    tampered_receipt = parse_receipt(tampered_receipt_payload)
    with pytest.raises(ExtensionError) as tampered_receipt_error:
        verify_receipt(
            tampered_receipt,
            package_json_bytes=tampered_bytes,
            package=parse_package_manifest(tampered_bytes),
            package_sha256=package_sha256,
            trusted_target_id=trusted_json_hash,
        )
    assert tampered_receipt_error.value.reason_code == ReasonCode.VERIFICATION_FAILED


def test_active_symlink_escape_is_rejected(tmp_path: Path):
    extensions_root = tmp_path / "extensions"
    extensions_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload").write_text("nope", encoding="utf-8")
    (extensions_root / "escape").symlink_to(outside)

    active = {
        "schema": 1,
        "generation": 1,
        "by_runtime": {
            "rt1-0123456789abcdef0123456789abcdef": {
                "media": {
                    "package_relpath": "escape/payload",
                    "package_sha256": "d" * 64,
                }
            }
        },
    }
    path = extensions_root / "active.json"
    path.write_text(json.dumps(active), encoding="utf-8")
    with pytest.raises(ExtensionError) as info:
        load_active_state(path, extensions_root=extensions_root)
    assert info.value.reason_code == ReasonCode.VERIFICATION_FAILED

    with pytest.raises(ExtensionError):
        resolve_inside(extensions_root, "escape/payload")


def test_active_store_symlink_is_rejected(tmp_path: Path):
    runtime = "rt1-0123456789abcdef0123456789abcdef"
    digest = "d" * 64
    relpath = f"store/{runtime}/media/{digest}"
    extensions_root = tmp_path / "extensions"
    store_parent = extensions_root / "store" / runtime / "media"
    store_parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / digest).write_text("nope", encoding="utf-8")
    (store_parent / digest).symlink_to(outside / digest)
    active = {
        "schema": 1,
        "generation": 1,
        "by_runtime": {
            runtime: {
                "media": {
                    "package_relpath": relpath,
                    "package_sha256": digest,
                }
            }
        },
    }
    path = extensions_root / "active.json"
    path.write_text(json.dumps(active), encoding="utf-8")
    with pytest.raises(ExtensionError) as info:
        load_active_state(path, extensions_root=extensions_root)
    assert info.value.reason_code == ReasonCode.VERIFICATION_FAILED


def _write_tree(root: Path, files: dict[str, bytes]) -> None:
    for relpath, content in files.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def test_collect_file_identities_classifies_python_and_native(tmp_path: Path):
    root = tmp_path / "base"
    _write_tree(
        root,
        {
            "site-packages/numpy/__init__.py": b"numpy-module",
            "_internal/python311.dll": b"cpython-shared-artifact-build-a",
            "_internal/Qt5Core.dll": b"qt-core-bytes",
            "readme.txt": b"not-a-runtime-artifact",
        },
    )
    identities = collect_file_identities(root, owner=OWNER_BASE)
    by_relpath = {item.relpath: item for item in identities}
    assert by_relpath["site-packages/numpy/__init__.py"].kind == KIND_PYTHON_MODULE
    assert by_relpath["_internal/python311.dll"].kind == KIND_NATIVE_SHARED
    assert by_relpath["_internal/Qt5Core.dll"].kind == KIND_NATIVE_SHARED
    assert by_relpath["readme.txt"].kind == "other"
    assert by_relpath["_internal/python311.dll"].sha256 == hashlib.sha256(
        b"cpython-shared-artifact-build-a"
    ).hexdigest()


def test_same_basename_different_content_dll_is_refused(tmp_path: Path):
    base = tmp_path / "base"
    media = tmp_path / "media"
    matlab = tmp_path / "matlab"
    _write_tree(
        base,
        {
            "_internal/python311.dll": b"cpython-shared-artifact-build-a",
            "site-packages/numpy/__init__.py": b"numpy-base",
        },
    )
    _write_tree(
        media,
        {
            "site-packages/av/__init__.py": b"av-module",
            "native/av.libs/zlib.dll": b"zlib-from-av",
        },
    )
    _write_tree(
        matlab,
        {
            "site-packages/h5py/__init__.py": b"h5py-module",
            "native/h5py/zlib.dll": b"zlib-from-h5py-different-bytes",
        },
    )
    trees = (
        collect_file_identities(base, owner=OWNER_BASE),
        collect_file_identities(media, owner=OWNER_MEDIA),
        collect_file_identities(matlab, owner=OWNER_MATLAB),
    )
    conflicts = find_native_conflicts(*trees)
    mismatch = [item for item in conflicts if item.kind == "basename_hash_mismatch"]
    assert mismatch
    assert mismatch[0].reason_code == ReasonCode.NATIVE_DLL_CONFLICT
    assert mismatch[0].reason_code == REASON_NATIVE_DLL_CONFLICT
    assert mismatch[0].basename.lower() == "zlib.dll"
    assert mismatch[0].left_sha256 != mismatch[0].right_sha256
    with pytest.raises(NativeIdentityError) as info:
        assert_native_combination(*trees)
    assert info.value.reason_code == ReasonCode.NATIVE_DLL_CONFLICT
    assert info.value.conflicts


def test_component_must_not_copy_base_shared_python_or_qt(tmp_path: Path):
    base = tmp_path / "base"
    media = tmp_path / "media"
    _write_tree(
        base,
        {
            "_internal/python311.dll": b"cpython-shared-artifact-build-a",
            "_internal/Qt5Core.dll": b"qt-core-bytes",
            "site-packages/numpy/__init__.py": b"numpy-base",
        },
    )
    _write_tree(
        media,
        {
            "site-packages/av/__init__.py": b"av-module",
            "site-packages/numpy/core.py": b"copied-numpy",
            "native/python311.dll": b"cpython-shared-artifact-build-a",
        },
    )
    trees = (
        collect_file_identities(base, owner=OWNER_BASE),
        collect_file_identities(media, owner=OWNER_MEDIA),
    )
    conflicts = find_native_conflicts(*trees)
    kinds = {item.kind for item in conflicts}
    assert "base_owned_module" in kinds
    assert "base_owned_native" in kinds
    assert all(item.reason_code == ReasonCode.NATIVE_DLL_CONFLICT for item in conflicts)
    with pytest.raises(NativeIdentityError) as info:
        assert_native_combination(*trees)
    assert info.value.reason_code == ReasonCode.NATIVE_DLL_CONFLICT


def test_identical_zlib_bytes_are_not_a_basename_conflict(tmp_path: Path):
    media = tmp_path / "media"
    matlab = tmp_path / "matlab"
    shared = b"zlib-identical-bytes"
    _write_tree(media, {"native/av.libs/zlib.dll": shared, "site-packages/av/__init__.py": b"av"})
    _write_tree(matlab, {"native/h5py/zlib.dll": shared, "site-packages/h5py/__init__.py": b"h5"})
    assert_native_combination(
        collect_file_identities(media, owner=OWNER_MEDIA),
        collect_file_identities(matlab, owner=OWNER_MATLAB),
    )
