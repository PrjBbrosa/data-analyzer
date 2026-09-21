from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import zipfile

import pytest

from mf4_analyzer.extensions.contract import (
    FileEntry,
    bind_verified_package,
    generate_package_manifest,
    parse_package_manifest,
)
from tools.extension_manager.unpack import (
    VERIFICATION_FAILED,
    ManifestFile,
    UnpackError,
    UnpackLimits,
    check_disk_space,
    extract_verified_zip,
    normalize_zip_path,
    require_disk_space,
    validate_zip,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest(files: dict[str, bytes]) -> list[ManifestFile]:
    return [
        ManifestFile(relative_path=name, size=len(payload), sha256=_sha256(payload))
        for name, payload in files.items()
    ]


def _limits(files: dict[str, bytes], *, extra_bytes: int = 64, extra_files: int = 8) -> UnpackLimits:
    return UnpackLimits(
        max_uncompressed_size=sum(len(payload) for payload in files.values()) + extra_bytes,
        max_file_count=len(files) + extra_files,
    )


def _write_zip(path: Path, members: list[tuple[zipfile.ZipInfo | str, bytes]]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for spec, payload in members:
            archive.writestr(spec, payload)
    return path


def _write_files_zip(path: Path, files: dict[str, bytes]) -> Path:
    return _write_zip(path, [(name, payload) for name, payload in files.items()])


def _layout(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    app_root = tmp_path / "TraceLab"
    extensions = app_root / "extensions"
    internal = app_root / "_internal"
    staging = extensions / ".staging" / "txn-1"
    extensions.mkdir(parents=True, exist_ok=True)
    internal.mkdir(exist_ok=True)
    return app_root, extensions, internal, staging


def _extract(
    tmp_path: Path,
    files: dict[str, bytes],
    *,
    members: list[tuple[zipfile.ZipInfo | str, bytes]] | None = None,
    manifest: list[ManifestFile] | None = None,
    limits: UnpackLimits | None = None,
    staging: Path | None = None,
    extensions_root: Path | None = None,
    app_root: Path | None = None,
):
    app, extensions, _internal, default_staging = _layout(tmp_path)
    archive = _write_zip(
        tmp_path / "pkg.zip",
        members if members is not None else [(name, payload) for name, payload in files.items()],
    )
    return extract_verified_zip(
        archive,
        staging if staging is not None else default_staging,
        extensions_root=extensions_root if extensions_root is not None else extensions,
        manifest=manifest if manifest is not None else _manifest(files),
        limits=limits if limits is not None else _limits(files),
        app_root=app_root if app_root is not None else app,
    )


def _raises_verification(tmp_path: Path, **kwargs) -> UnpackError:
    with pytest.raises(UnpackError) as caught:
        _extract(tmp_path, **kwargs)
    assert caught.value.reason_code == VERIFICATION_FAILED
    return caught.value


NESTED_SAFE_FILES = {
    "package.json": b'{"component":"media"}',
    "site-packages/av/__init__.py": b"__version__ = '1'\n",
    "site-packages/av/codec/native.py": b"payload = 1\n",
    "native/ffmpeg/libav.bin": b"dll-bytes",
}


def test_happy_path_extracts_nested_safe_paths_only_into_staging(tmp_path: Path):
    app_root, extensions, internal, staging = _layout(tmp_path)
    archive = _write_files_zip(tmp_path / "pkg.zip", NESTED_SAFE_FILES)

    result = extract_verified_zip(
        archive,
        staging,
        extensions_root=extensions,
        manifest=_manifest(NESTED_SAFE_FILES),
        limits=_limits(NESTED_SAFE_FILES),
        app_root=app_root,
    )

    assert result.staging_dir == staging.resolve()
    assert set(result.files) == set(NESTED_SAFE_FILES)
    assert result.uncompressed_bytes == sum(len(item) for item in NESTED_SAFE_FILES.values())
    for relative, payload in NESTED_SAFE_FILES.items():
        written = staging / relative
        assert written.is_file()
        assert written.read_bytes() == payload
        assert not written.is_symlink()
    assert not (internal / "package.json").exists()
    assert not (app_root / "package.json").exists()
    assert not (extensions / "package.json").exists()


@pytest.mark.parametrize(
    "name",
    (
        "../evil.txt",
        "../../evil.txt",
        "safe/../../escape.txt",
        "safe/../../../outside.txt",
        "/etc/passwd",
        "/tmp/abs.txt",
        "\\windows\\system32\\evil.txt",
        "..\\..\\evil.txt",
        "C:/Windows/system.ini",
        "C:\\Windows\\system.ini",
        "C:relative.txt",
        "//server/share/file.txt",
    ),
)
def test_zipslip_and_drive_paths_are_rejected(tmp_path: Path, name: str):
    payload = {name: b"nope"}
    error = _raises_verification(
        tmp_path,
        files=payload,
        manifest=[ManifestFile(relative_path="safe.txt", size=4, sha256=_sha256(b"nope"))],
    )
    assert error.detail in {
        "parent_escape",
        "absolute_path",
        "unc_path",
        "drive_letter",
        "ads",
        "empty_segment",
    }
    extensions = tmp_path / "TraceLab" / "extensions"
    staging = extensions / ".staging" / "txn-1"
    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path / "outside.txt").exists()
    assert not (extensions / "evil.txt").exists()
    if staging.exists():
        assert list(staging.rglob("*")) == []


def test_zipslip_does_not_write_outside_staging_even_if_name_is_in_manifest(tmp_path: Path):
    name = "../escape.txt"
    files = {name: b"stolen"}
    with pytest.raises(UnpackError) as caught:
        _extract(tmp_path, files=files, manifest=_manifest(files))
    assert caught.value.reason_code == VERIFICATION_FAILED
    assert not (tmp_path / "TraceLab" / "escape.txt").exists()
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.parametrize(
    "name",
    (
        "payload.txt:hidden",
        "payload.txt:secret:$DATA",
        "site-packages/av/mod.py:stream",
    ),
)
def test_ntfs_ads_names_are_rejected(tmp_path: Path, name: str):
    error = _raises_verification(tmp_path, files={name: b"ads"})
    assert error.detail == "ads"


@pytest.mark.parametrize(
    "name",
    (
        "CON",
        "NUL",
        "AUX",
        "COM1",
        "LPT1",
        "con.txt",
        "aux.log",
        "site-packages/COM1/mod.py",
        "native/NUL/data.bin",
        "lpt9.dat",
    ),
)
def test_windows_device_names_are_rejected(tmp_path: Path, name: str):
    error = _raises_verification(tmp_path, files={name: b"dev"})
    assert error.detail == "device_name"


def test_case_normalized_duplicate_names_are_rejected(tmp_path: Path):
    files = {
        "site-packages/Foo.py": b"A",
        "site-packages/foo.py": b"B",
    }
    error = _raises_verification(tmp_path, files=files)
    assert error.detail == "case_collision"


def test_unix_symlink_zip_entries_are_rejected(tmp_path: Path):
    info = zipfile.ZipInfo("site-packages/av/link.py")
    info.create_system = 3
    info.external_attr = (0o120777 << 16)
    info.compress_type = zipfile.ZIP_STORED
    files = {"site-packages/av/link.py": b"/tmp/target"}
    error = _raises_verification(
        tmp_path,
        files=files,
        members=[(info, b"/tmp/target")],
        manifest=_manifest(files),
    )
    assert error.detail == "symlink"
    _app, _extensions, _internal, staging = _layout(tmp_path)
    assert not (staging / "site-packages/av/link.py").exists()


def test_windows_reparse_zip_entries_are_rejected(tmp_path: Path):
    info = zipfile.ZipInfo("native/reparse.bin")
    info.create_system = 0
    info.external_attr = 0x400
    info.compress_type = zipfile.ZIP_STORED
    files = {"native/reparse.bin": b"reparse"}
    error = _raises_verification(
        tmp_path,
        files=files,
        members=[(info, b"reparse")],
        manifest=_manifest(files),
    )
    assert error.detail == "symlink"


def test_oversize_uncompressed_total_is_rejected(tmp_path: Path):
    files = {
        "site-packages/av/a.py": b"x" * 40,
        "site-packages/av/b.py": b"y" * 40,
    }
    error = _raises_verification(
        tmp_path,
        files=files,
        limits=UnpackLimits(max_uncompressed_size=50, max_file_count=10),
    )
    assert error.detail == "oversize"


def test_oversize_file_count_is_rejected(tmp_path: Path):
    files = {
        "site-packages/av/a.py": b"a",
        "site-packages/av/b.py": b"b",
    }
    error = _raises_verification(
        tmp_path,
        files=files,
        limits=UnpackLimits(max_uncompressed_size=10_000, max_file_count=1),
    )
    assert error.detail == "oversize"


def test_extra_files_beyond_manifest_are_rejected(tmp_path: Path):
    files = {
        "site-packages/av/__init__.py": b"ok",
        "site-packages/av/extra.py": b"nope",
    }
    error = _raises_verification(
        tmp_path,
        files=files,
        manifest=_manifest({"site-packages/av/__init__.py": b"ok"}),
    )
    assert error.detail == "extra_file"


@pytest.mark.parametrize(
    "name",
    (
        "site-packages/av.pth",
        "av.pth",
        "native/evil.PTH",
        "sitecustomize.py",
        "site-packages/usercustomize.py",
    ),
)
def test_pth_and_startup_scripts_are_rejected_even_if_manifested(tmp_path: Path, name: str):
    files = {name: b"import evil\n"}
    error = _raises_verification(tmp_path, files=files, manifest=_manifest(files))
    assert error.detail in {"pth", "startup_script"}


def test_missing_manifest_entries_are_rejected(tmp_path: Path):
    files = {"site-packages/av/__init__.py": b"ok"}
    error = _raises_verification(
        tmp_path,
        files=files,
        manifest=_manifest(
            {
                "site-packages/av/__init__.py": b"ok",
                "site-packages/av/missing.py": b"gone",
            }
        ),
    )
    assert error.detail == "missing_manifest_entry"


def test_destination_outside_extensions_root_is_rejected(tmp_path: Path):
    files = dict(NESTED_SAFE_FILES)
    outside = tmp_path / "not-extensions" / "staging"
    error = _raises_verification(tmp_path, files=files, staging=outside)
    assert error.detail == "destination"
    assert not (outside / "package.json").exists()


def test_extract_refuses_internal_and_exe_dir_when_they_are_not_the_staging_tree(
    tmp_path: Path,
):
    files = {"site-packages/av/__init__.py": b"ok"}
    app_root, extensions, internal, _staging = _layout(tmp_path)
    archive = _write_files_zip(tmp_path / "pkg.zip", files)
    manifest = _manifest(files)
    limits = _limits(files)

    with pytest.raises(UnpackError) as into_internal:
        extract_verified_zip(
            archive,
            internal / "payload",
            extensions_root=extensions,
            manifest=manifest,
            limits=limits,
            app_root=app_root,
        )
    assert into_internal.value.reason_code == VERIFICATION_FAILED
    assert not (internal / "payload" / "site-packages/av/__init__.py").exists()

    with pytest.raises(UnpackError) as into_exe:
        extract_verified_zip(
            archive,
            app_root / "dropped",
            extensions_root=extensions,
            manifest=manifest,
            limits=limits,
            app_root=app_root,
        )
    assert into_exe.value.reason_code == VERIFICATION_FAILED


def test_validate_zip_is_pure_and_does_not_extract(tmp_path: Path):
    _app_root, extensions, _internal, staging = _layout(tmp_path)
    archive = _write_files_zip(tmp_path / "pkg.zip", NESTED_SAFE_FILES)
    validated = validate_zip(
        archive,
        _manifest(NESTED_SAFE_FILES),
        _limits(NESTED_SAFE_FILES),
    )
    assert {member.relative_path for member in validated.members} == set(NESTED_SAFE_FILES)
    assert not staging.exists()
    assert list(extensions.rglob("*")) == []


def test_normalize_zip_path_rejects_parent_and_ads_without_windows():
    with pytest.raises(UnpackError) as parent:
        normalize_zip_path("../x")
    assert parent.value.detail == "parent_escape"
    with pytest.raises(UnpackError) as ads:
        normalize_zip_path("file.txt:stream")
    assert ads.value.detail == "ads"
    assert normalize_zip_path("site-packages/av/nested/mod.py") == "site-packages/av/nested/mod.py"


def test_check_disk_space_uses_fake_free_space_callback(tmp_path: Path):
    calls: list[Path] = []

    def fake_free_space(path: Path) -> int:
        calls.append(path)
        return 1_099

    too_small = check_disk_space(
        tmp_path / "missing" / "staging",
        required_bytes=1_000,
        margin_bytes=100,
        free_space=fake_free_space,
    )
    assert too_small.ok is False
    assert too_small.reason_code == VERIFICATION_FAILED
    assert too_small.available_bytes == 1_099
    assert too_small.detail == "disk_space"
    assert calls == [tmp_path / "missing" / "staging"]

    enough = check_disk_space(
        tmp_path,
        required_bytes=1_000,
        margin_bytes=100,
        free_space=lambda _path: 1_100,
    )
    assert enough.ok is True
    assert enough.reason_code is None

    with pytest.raises(UnpackError) as caught:
        require_disk_space(
            tmp_path,
            required_bytes=8_000,
            margin_bytes=2_000,
            free_space=lambda _path: 9_999,
        )
    assert caught.value.reason_code == VERIFICATION_FAILED
    assert caught.value.detail == "disk_space"


def test_default_free_space_probe_does_not_fill_the_disk(tmp_path: Path):
    before = os.statvfs(tmp_path)
    status = check_disk_space(tmp_path, required_bytes=1, margin_bytes=0)
    after = os.statvfs(tmp_path)
    assert status.available_bytes >= 0
    assert after.f_bavail >= before.f_bavail - 1
    assert isinstance(status.ok, bool)


def test_unix_symlink_mode_detection_does_not_need_windows():
    assert stat.S_ISLNK(0o120777)
    assert not stat.S_ISLNK(0o100644)


def _real_package_bytes() -> tuple[bytes, dict[str, bytes]]:
    files = {
        "site-packages/av/__init__.py": b"__version__ = '1'\n",
        "native/av/lib.bin": b"dll-bytes",
    }
    manifest = generate_package_manifest(
        component="media",
        package_revision=3,
        runtime_id="rt1-0123456789abcdef0123456789abcdef",
        component_api="1",
        min_manager_version="1.0.0",
        python_tag="cp311",
        platform_tag="win_amd64",
        module_roots=["site-packages/av"],
        dll_directories=["native/av"],
        dependency_ownership={"av": "media"},
        files=[
            {"relpath": name, "size": len(payload), "sha256": _sha256(payload)}
            for name, payload in files.items()
        ],
        max_extract_bytes=10_000,
        probe_type="media_wav_mp4_v1",
        required_features=["store_layout_v1", "native_probe_v1", "file_manifest_sha256"],
    )
    json_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    packed = dict(files)
    packed["package.json"] = json_bytes
    return json_bytes, packed


def test_contract_file_entries_unpack_a_real_zip(tmp_path: Path):
    json_bytes, packed = _real_package_bytes()
    package = parse_package_manifest(json_bytes)
    app_root, extensions, _internal, staging = _layout(tmp_path)
    archive = _write_files_zip(tmp_path / "media.zip", packed)
    entries = list(package.files) + [
        FileEntry(relpath="package.json", size=len(json_bytes), sha256=_sha256(json_bytes))
    ]
    result = extract_verified_zip(
        archive,
        staging,
        extensions_root=extensions,
        manifest=entries,
        limits=_limits(packed),
        app_root=app_root,
    )
    assert set(result.files) == set(packed)
    assert (staging / "package.json").read_bytes() == json_bytes
    assert (staging / "site-packages/av/__init__.py").read_bytes() == packed["site-packages/av/__init__.py"]


def test_fixture_relpath_dicts_are_not_accepted_as_unpack_manifest(tmp_path: Path):
    fixture = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "extensions" / "package-valid.json").read_text(
            encoding="utf-8"
        )
    )
    error = _raises_verification(
        tmp_path,
        files={"site-packages/av/__init__.py": b"x" * 128},
        manifest=fixture["files"],
    )
    assert error.detail == "manifest"


def test_missing_hash_is_rejected(tmp_path: Path):
    files = {"site-packages/av/__init__.py": b"ok"}
    with pytest.raises((UnpackError, ValueError)):
        _extract(
            tmp_path,
            files=files,
            manifest=[ManifestFile(relative_path="site-packages/av/__init__.py", size=2, sha256="")],
        )


def test_hash_mismatch_during_extract_cleans_partial_files(tmp_path: Path):
    files = {
        "site-packages/av/a.py": b"ok-a",
        "site-packages/av/b.py": b"ok-b-payload",
    }
    manifest = _manifest(files)
    manifest[1] = ManifestFile(
        relative_path="site-packages/av/b.py",
        size=len(files["site-packages/av/b.py"]),
        sha256="0" * 64,
    )
    app_root, extensions, _internal, staging = _layout(tmp_path)
    archive = _write_files_zip(tmp_path / "pkg.zip", files)
    with pytest.raises(UnpackError) as caught:
        extract_verified_zip(
            archive,
            staging,
            extensions_root=extensions,
            manifest=manifest,
            limits=_limits(files),
            app_root=app_root,
        )
    assert caught.value.reason_code == VERIFICATION_FAILED
    assert caught.value.detail == "hash_mismatch"
    leftover = [path for path in staging.rglob("*") if path.is_file()] if staging.exists() else []
    assert leftover == []
    retry_manifest = _manifest(files)
    result = extract_verified_zip(
        archive,
        staging,
        extensions_root=extensions,
        manifest=retry_manifest,
        limits=_limits(files),
        app_root=app_root,
    )
    assert set(result.files) == set(files)


def test_verified_package_rejects_embedded_package_json_mismatch(tmp_path: Path):
    json_bytes, packed = _real_package_bytes()
    packed["package.json"] = json_bytes + b"\n"
    verified = bind_verified_package(
        snapshot_id="snap-1",
        component="media",
        runtime_id="rt1-0123456789abcdef0123456789abcdef",
        package_revision=3,
        component_api="1",
        min_manager_version="1.0.0",
        zip_target="packages/media-3.zip",
        zip_sha256="a" * 64,
        zip_length=16,
        manifest_target="packages/media-3.package.json",
        manifest_sha256=_sha256(json_bytes),
        manifest_length=len(json_bytes),
        package_json_bytes=json_bytes,
    )
    app_root, extensions, _internal, staging = _layout(tmp_path)
    archive = _write_files_zip(tmp_path / "mismatch.zip", packed)
    with pytest.raises(UnpackError) as caught:
        extract_verified_zip(
            archive,
            staging,
            extensions_root=extensions,
            manifest=verified.unpack_manifest(),
            limits=_limits(packed),
            app_root=app_root,
        )
    assert caught.value.detail in {"size_mismatch", "hash_mismatch"}
    leftover = [path for path in staging.rglob("*") if path.is_file()] if staging.exists() else []
    assert leftover == []
