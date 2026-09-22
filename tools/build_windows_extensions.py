"""Emit lite+modular core manifests, component ZIPs, and identity audit.

This is the experimental modular delivery helper.  It is not the product
default packager.  flavor and dependency_profile are independent; the CLI
default profile remains bundled, and the first supported *release* combination
is only lite+modular.  Component archives are importable module trees, not a
second PyInstaller PYZ.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
import json
from pathlib import Path
import shutil
import sys
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mf4_analyzer.app_meta import APP_VERSION  # noqa: E402
from mf4_analyzer.extensions.contract import (  # noqa: E402
    CURRENT_PROTOCOL_MAJOR,
    CURRENT_PROTOCOL_MINOR,
    FileEntry,
    KNOWN_REQUIRED_FEATURES,
    PRODUCT_ID,
    dumps_json,
    generate_core_files,
    generate_discovery_envelope,
    generate_package_manifest,
    parse_core_files,
    parse_discovery_envelope,
    parse_package_manifest,
    sha256_hex,
)
from mf4_analyzer.extensions.native_identity import (  # noqa: E402
    NativeIdentityError,
    OWNER_BASE,
    OWNER_MATLAB,
    OWNER_MEDIA,
    assert_native_combination,
    collect_file_identities,
    find_native_conflicts,
    sha256_file,
)
from mf4_analyzer.extensions.runtime_recipe import (  # noqa: E402
    collect_live_python_build_id,
    runtime_id_from_inputs,
    runtime_inputs_from_base_tree,
)
from mf4_analyzer.extensions.state import (  # noqa: E402
    bind_core_payloads,
    core_build_id_for_files,
)
from mf4_analyzer.io.runtime_dependencies import (  # noqa: E402
    COMPONENT_MATLAB,
    COMPONENT_MEDIA,
    DEFAULT_DEPENDENCY_PROFILE,
    MODULAR_EXCLUDED_MODULES,
    component_ownership,
    dependencies_for_component,
    frozen_dependencies_for_profile,
    pyinstaller_collection_args,
)


SUPPORTED_RELEASE_COMBINATIONS = frozenset({("lite", "modular")})
DEFAULT_MIN_MANAGER_VERSION = "1.0.0"
DEFAULT_COMPONENT_API = "1"
DEFAULT_PACKAGE_REVISION = 1
DEFAULT_MANAGER_DOWNLOAD_PAGE = (
    "https://example.invalid/tracelab/extension-manager"
)
COMPONENT_PROBE_TYPES = {
    COMPONENT_MEDIA: "media_wav_mp4_v1",
    COMPONENT_MATLAB: "matlab_mat_v73_v1",
}
OPTIONAL_MATLAB_PACKAGES = frozenset({"hdf5storage"})
PYINSTALLER_ARCHIVE_NAMES = frozenset(
    {
        "pyz.pyz",
        "pyz-00.pyz",
        "pyz-01.pyz",
        "base_library.zip",
        "pyimod01_os_path",
        "pyimod02_importers",
        "pyimod03_ctypes",
        "pyimod04_pywin32",
        "struct",
    }
)
SKIP_COPY_DIR_NAMES = frozenset({"__pycache__", ".git", "tests", "test"})
SKIP_COPY_SUFFIXES = frozenset({".pyc", ".pyo", ".pth"})
CORE_FILES_SKIP_NAMES = frozenset(
    {
        "core.json",
        "core-files.json",
        "installer.exe",
        "manager-delivery.json",
        "delivery-audit.json",
        "licenses.json",
        "dependency-list.json",
    }
)
CORE_FILES_SKIP_DIRS = frozenset({"extensions", "packages"})
WINDOWS_NATIVE_SUFFIXES = frozenset({".dll", ".pyd"})
UNIX_NATIVE_SUFFIXES = frozenset({".so", ".dylib"})


class UnsupportedDeliveryCombination(ValueError):
    """flavor × profile is not a first-release modular combination."""


class ExtensionBuildError(RuntimeError):
    """Modular delivery could not be emitted from the given trees."""


def supported_release_combination(flavor: str, profile: str) -> bool:
    return (str(flavor), str(profile)) in SUPPORTED_RELEASE_COMBINATIONS


def require_supported_combination(flavor: str, profile: str) -> tuple[str, str]:
    if not supported_release_combination(flavor, profile):
        raise UnsupportedDeliveryCombination(
            "unsupported frozen delivery combination "
            f"flavor={flavor!r} dependency_profile={profile!r}; "
            "first modular release accepts only lite+modular "
            f"(default profile remains {DEFAULT_DEPENDENCY_PROFILE!r})"
        )
    return flavor, profile


def collection_plan(flavor: str, profile: str) -> dict[str, Any]:
    """Export base vs component collect/exclude from the unified contract."""
    require_supported_combination(flavor, profile)
    ownership = component_ownership()
    base_packages = tuple(
        item.package for item in frozen_dependencies_for_profile(profile)
    )
    media_packages = tuple(
        item.package for item in dependencies_for_component(COMPONENT_MEDIA)
    )
    matlab_packages = tuple(
        item.package for item in dependencies_for_component(COMPONENT_MATLAB)
    )
    return {
        "flavor": flavor,
        "dependency_profile": profile,
        "pyinstaller_args": list(pyinstaller_collection_args(flavor, profile)),
        "base_collect": list(base_packages),
        "component_collect": {
            COMPONENT_MEDIA: list(media_packages),
            COMPONENT_MATLAB: list(matlab_packages) + sorted(OPTIONAL_MATLAB_PACKAGES),
        },
        "base_exclude": list(MODULAR_EXCLUDED_MODULES),
        "ownership": dict(ownership),
    }


def _posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _should_skip_file(path: Path) -> bool:
    name = path.name
    if name in CORE_FILES_SKIP_NAMES:
        return True
    if path.suffix.lower() in SKIP_COPY_SUFFIXES:
        return True
    return False


def iter_core_files(app_root: Path) -> tuple[Path, ...]:
    root = Path(app_root)
    collected: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root)
        if any(part.lower() in CORE_FILES_SKIP_DIRS for part in rel.parts):
            continue
        if path.name.lower() in {name.lower() for name in CORE_FILES_SKIP_NAMES}:
            continue
        if path.suffix.lower() in {".zip", ".json"} and path.parent == root:
            if path.name.lower().endswith(".zip") or path.stem in {
                "core",
                "core-files",
                "manager-delivery",
                "delivery-audit",
                "licenses",
                "dependency-list",
            }:
                continue
        collected.append(path)
    return tuple(collected)


def file_entry_for(path: Path, relpath: str) -> FileEntry:
    return FileEntry(
        relpath=relpath,
        size=path.stat().st_size,
        sha256=sha256_file(path),
    )


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps_json(payload), encoding="utf-8")


def content_addressed_zip_name(component: str, files_digest: str) -> str:
    return f"{component}-{files_digest}.zip"


def is_pyinstaller_archive_member(relpath: str) -> bool:
    name = Path(relpath).name.lower()
    if name in PYINSTALLER_ARCHIVE_NAMES:
        return True
    lowered = relpath.replace("\\", "/").lower()
    return lowered.endswith(".pyz") or "/pyz-00.pyz" in lowered


def refuse_pyinstaller_payload(relpaths: Iterable[str]) -> None:
    offenders = [item for item in relpaths if is_pyinstaller_archive_member(item)]
    if offenders:
        raise ExtensionBuildError(
            "component ZIP must be an importable module tree, not a "
            f"PyInstaller archive: {offenders[0]}"
        )


def refuse_unix_natives_for_windows(relpaths: Iterable[str], *, platform_tag: str) -> None:
    if platform_tag != "win_amd64":
        return
    for relpath in relpaths:
        lowered = relpath.lower()
        suffix = Path(lowered).suffix
        if suffix in UNIX_NATIVE_SUFFIXES or ".so." in Path(lowered).name:
            raise ExtensionBuildError(
                "win_amd64 component must not include Unix native "
                f"{relpath}; collect from a Windows build environment"
            )


def _copy_tree(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_file():
        if _should_skip_file(src):
            return
        shutil.copy2(src, dest)
        return
    shutil.copytree(
        src,
        dest,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(*SKIP_COPY_DIR_NAMES, "*.pyc", "*.pyo", "*.pth"),
        copy_function=shutil.copy2,
    )


def _dist_info_dirs(site_packages: Path, package: str) -> tuple[Path, ...]:
    matches = []
    for child in sorted(site_packages.iterdir()) if site_packages.is_dir() else []:
        if not child.is_dir():
            continue
        name = child.name.lower()
        if name == f"{package}.dist-info" or name.startswith(f"{package}-"):
            if name.endswith(".dist-info"):
                matches.append(child)
    return tuple(matches)


def collect_component_staging(
    site_packages: Path,
    component: str,
    staging_root: Path,
) -> Path:
    """Copy independently importable modules into a ZIP staging tree."""
    packages = list(
        item.package for item in dependencies_for_component(component)
    )
    if component == COMPONENT_MATLAB:
        packages.extend(sorted(OPTIONAL_MATLAB_PACKAGES))
    site_dest = staging_root / "site-packages"
    copied: list[str] = []
    for package in packages:
        src = site_packages / package
        libs = site_packages / f"{package}.libs"
        if not src.exists() and package in OPTIONAL_MATLAB_PACKAGES:
            continue
        if not src.exists():
            raise ExtensionBuildError(
                f"component {component} is missing importable package "
                f"{package} under {site_packages}"
            )
        _copy_tree(src, site_dest / package)
        copied.append(package)
        if libs.exists():
            _copy_tree(libs, site_dest / f"{package}.libs")
        for dist_info in _dist_info_dirs(site_packages, package):
            _copy_tree(dist_info, site_dest / dist_info.name)
    if not copied:
        raise ExtensionBuildError(f"component {component} copied no packages")
    return staging_root


def _module_roots_and_dlls(staging_root: Path) -> tuple[list[str], list[str]]:
    site = staging_root / "site-packages"
    native = staging_root / "native"
    roots: list[str] = []
    dlls: list[str] = []
    if site.is_dir():
        for child in sorted(site.iterdir()):
            if child.name.endswith(".dist-info"):
                continue
            if child.name.endswith(".libs"):
                dlls.append(_posix(child, staging_root))
                continue
            if child.is_dir() or child.suffix.lower() in {".py", ".pyd"}:
                roots.append(_posix(child, staging_root))
    if native.is_dir():
        dlls.append("native")
    if not roots:
        raise ExtensionBuildError("component staging has no module_roots")
    return roots, dlls


def _iter_staging_files(staging_root: Path) -> tuple[Path, ...]:
    files = []
    for path in sorted(staging_root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if path.name == "package.json":
            continue
        files.append(path)
    return tuple(files)


def _license_records(staging_root: Path, component: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    site = staging_root / "site-packages"
    if not site.is_dir():
        return records
    for dist_info in sorted(site.glob("*.dist-info")):
        for candidate in ("LICENSE", "LICENSE.txt", "LICENCE", "METADATA"):
            path = dist_info / candidate
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            records.append(
                {
                    "component": component,
                    "source": _posix(path, staging_root),
                    "sha256": sha256_file(path),
                    "excerpt": text[:400],
                }
            )
            break
    return records


def _requires_dist(staging_root: Path, component: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    site = staging_root / "site-packages"
    if not site.is_dir():
        return records
    for dist_info in sorted(site.glob("*.dist-info")):
        metadata = dist_info / "METADATA"
        if not metadata.is_file():
            continue
        name = dist_info.name[: -len(".dist-info")]
        requires: list[str] = []
        for line in metadata.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Requires-Dist:"):
                requires.append(line.split(":", 1)[1].strip())
        records.append(
            {
                "component": component,
                "distribution": name,
                "requires": "; ".join(requires),
            }
        )
    return records


def _live_numpy_identity() -> tuple[str, str]:
    try:
        import numpy as np
    except ImportError as exc:
        raise ExtensionBuildError(
            "numpy is required to mint runtime_id unless --numpy-version "
            f"and --numpy-abi are provided: {exc}"
        ) from exc
    numpy_abi = sys.implementation.cache_tag or "cp3"
    return str(np.__version__), numpy_abi


def _runtime_kwargs_from_args(args: argparse.Namespace) -> dict[str, str]:
    numpy_version = args.numpy_version
    numpy_abi = args.numpy_abi
    if not numpy_version or not numpy_abi:
        live_version, live_abi = _live_numpy_identity()
        numpy_version = numpy_version or live_version
        numpy_abi = numpy_abi or live_abi
    return {
        "python_implementation": args.python_implementation
        or sys.implementation.name.capitalize().replace("Cpython", "CPython"),
        "python_version": args.python_version
        or f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "python_abi": args.python_abi or (sys.implementation.cache_tag or ""),
        "python_build_id": args.python_build_id or collect_live_python_build_id(),
        "arch": args.arch or "win-amd64",
        "numpy_version": numpy_version,
        "numpy_abi": numpy_abi,
    }


def emit_core_manifests(
    app_root: Path,
    *,
    exe_relpath: str,
    runtime_kwargs: Mapping[str, str],
    min_manager_version: str = DEFAULT_MIN_MANAGER_VERSION,
    manager_download_page: str = DEFAULT_MANAGER_DOWNLOAD_PAGE,
) -> dict[str, Any]:
    root = Path(app_root)
    exe = root / exe_relpath
    if not exe.is_file():
        raise ExtensionBuildError(f"core executable not found: {exe}")
    files = [
        file_entry_for(path, _posix(path, root))
        for path in iter_core_files(root)
        if path != root / "core.json" and path != root / "core-files.json"
    ]
    if not any(entry.relpath == exe_relpath.replace("\\", "/") for entry in files):
        files.insert(0, file_entry_for(exe, exe_relpath.replace("\\", "/")))
    core_files_payload = generate_core_files(files)
    core_files = parse_core_files(core_files_payload)
    core_build_id = core_build_id_for_files(core_files)
    inputs = runtime_inputs_from_base_tree(
        root,
        python_implementation=runtime_kwargs["python_implementation"],
        python_version=runtime_kwargs["python_version"],
        python_abi=runtime_kwargs["python_abi"],
        python_build_id=runtime_kwargs["python_build_id"],
        arch=runtime_kwargs["arch"],
        numpy_version=runtime_kwargs["numpy_version"],
        numpy_abi=runtime_kwargs["numpy_abi"],
    )
    runtime_id = runtime_id_from_inputs(inputs)
    envelope = generate_discovery_envelope(
        exe_relpath=exe_relpath.replace("\\", "/"),
        core_build_id=core_build_id,
        runtime_id=runtime_id,
        component_capabilities={
            COMPONENT_MEDIA: {"component_api": DEFAULT_COMPONENT_API, "available": True},
            COMPONENT_MATLAB: {"component_api": DEFAULT_COMPONENT_API, "available": True},
        },
        min_manager_version=min_manager_version,
        manager_download_page=manager_download_page,
        app_version=APP_VERSION,
        product_id=PRODUCT_ID,
        protocol_major=CURRENT_PROTOCOL_MAJOR,
        protocol_minor=CURRENT_PROTOCOL_MINOR,
        exe_sha256=sha256_file(exe),
        core_files_digest=core_files.digest,
    )
    write_json(root / "core-files.json", core_files_payload)
    write_json(root / "core.json", envelope)
    bind_core_payloads(
        (root / "core.json").read_text(encoding="utf-8"),
        (root / "core-files.json").read_text(encoding="utf-8"),
    )
    return {
        "core_json": str(root / "core.json"),
        "core_files_json": str(root / "core-files.json"),
        "exe_relpath": envelope["exe_relpath"],
        "app_version": envelope["app_version"],
        "core_build_id": core_build_id,
        "runtime_id": runtime_id,
        "exe_sha256": envelope["exe_sha256"],
    }


def emit_component_zip(
    *,
    component: str,
    staging_root: Path,
    output_dir: Path,
    runtime_id: str,
    python_tag: str,
    platform_tag: str,
    package_revision: int = DEFAULT_PACKAGE_REVISION,
    min_manager_version: str = DEFAULT_MIN_MANAGER_VERSION,
) -> dict[str, Any]:
    files = [
        file_entry_for(path, _posix(path, staging_root))
        for path in _iter_staging_files(staging_root)
    ]
    if not files:
        raise ExtensionBuildError(f"component {component} staging is empty")
    relpaths = [entry.relpath for entry in files]
    refuse_pyinstaller_payload(relpaths)
    refuse_unix_natives_for_windows(relpaths, platform_tag=platform_tag)
    module_roots, dll_directories = _module_roots_and_dlls(staging_root)
    ownership = {
        item.package: item.component
        for item in dependencies_for_component(component)
    }
    if component == COMPONENT_MATLAB:
        for extra in OPTIONAL_MATLAB_PACKAGES:
            if (staging_root / "site-packages" / extra).exists():
                ownership[extra] = COMPONENT_MATLAB
    total = sum(entry.size for entry in files)
    manifest = generate_package_manifest(
        component=component,
        package_revision=package_revision,
        runtime_id=runtime_id,
        component_api=DEFAULT_COMPONENT_API,
        min_manager_version=min_manager_version,
        python_tag=python_tag,
        platform_tag=platform_tag,
        module_roots=module_roots,
        dll_directories=dll_directories,
        dependency_ownership=ownership,
        files=files,
        max_extract_bytes=max(total * 2, total + 1024),
        probe_type=COMPONENT_PROBE_TYPES[component],
        required_features=sorted(KNOWN_REQUIRED_FEATURES),
    )
    parse_package_manifest(manifest)
    write_json(staging_root / "package.json", manifest)
    digest = parse_package_manifest(manifest).files_digest
    zip_name = content_addressed_zip_name(component, digest)
    zip_path = output_dir / zip_name
    output_dir.mkdir(parents=True, exist_ok=True)
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.write(staging_root / "package.json", "package.json")
        for path in _iter_staging_files(staging_root):
            archive.write(path, _posix(path, staging_root))
        refuse_pyinstaller_payload(archive.namelist())
    return {
        "component": component,
        "zip": str(zip_path),
        "zip_name": zip_name,
        "sha256": sha256_file(zip_path),
        "size": zip_path.stat().st_size,
        "files_digest": digest,
        "package_json": str(staging_root / "package.json"),
        "licenses": _license_records(staging_root, component),
        "dependencies": _requires_dist(staging_root, component),
        "module_roots": module_roots,
        "dll_directories": dll_directories,
    }


def audit_native_trees(
    *,
    app_root: Path,
    component_stagings: Mapping[str, Path],
) -> dict[str, Any]:
    base_identities = collect_file_identities(app_root, owner=OWNER_BASE)
    leaked = [
        item.relpath
        for item in base_identities
        if any(
            part.lower() in {name.lower() for name in MODULAR_EXCLUDED_MODULES}
            or part.lower() in {f"{name}.libs" for name in MODULAR_EXCLUDED_MODULES}
            for part in item.relpath.replace("\\", "/").split("/")
        )
    ]
    if leaked:
        raise ExtensionBuildError(
            "modular base leaked optional importer trees; do not delete "
            f"directories to fake a split: {leaked[0]}"
        )
    groups = [base_identities]
    owner_map = {COMPONENT_MEDIA: OWNER_MEDIA, COMPONENT_MATLAB: OWNER_MATLAB}
    collected: dict[str, int] = {"base": len(base_identities)}
    for component, staging in component_stagings.items():
        identities = collect_file_identities(staging, owner=owner_map[component])
        groups.append(identities)
        collected[component] = len(identities)
    try:
        assert_native_combination(*groups)
    except NativeIdentityError as exc:
        raise ExtensionBuildError(
            f"{exc.reason_code}: {exc}"
        ) from exc
    conflicts = find_native_conflicts(*groups)
    pyz_members = [
        item.relpath
        for item in base_identities
        if is_pyinstaller_archive_member(item.relpath)
    ]
    return {
        "ok": True,
        "files_scanned": collected,
        "native_conflicts": [conflict.reason_code for conflict in conflicts],
        "pyz_audit": "unknown" if not pyz_members else "names_present_on_disk",
        "pyz_note": (
            "Windows PYZ toc inside the frozen EXE is UNKNOWN on this host; "
            "directory leak scan is not a PYZ proof"
        ),
        "openblas_policy": (
            "modular matlab keeps the component OpenBLAS closure; "
            "do not reuse the Lite bundled scipy.libs file-delete"
        ),
    }


def copy_tested_manager(
    *,
    app_root: Path,
    manager_source: Path | None,
) -> dict[str, Any]:
    """Copy a previously tested manager binary.  Never invent a SHA-256."""
    dest = Path(app_root) / "installer.exe"
    if manager_source is None:
        payload = {
            "copied": False,
            "placeholder": True,
            "reason": "verified_manager_binary_not_provided",
            "installer_relpath": "installer.exe",
            "sha256": None,
            "size": None,
            "source": None,
            "manager_version": None,
            "note": (
                "modular delivery copies an already-tested manager; "
                "it does not mint manager_version from APP_VERSION or "
                "fabricate installer.exe hashes"
            ),
        }
        write_json(Path(app_root) / "manager-delivery.json", payload)
        return payload
    source = Path(manager_source)
    if not source.is_file():
        raise ExtensionBuildError(f"manager source is not a file: {source}")
    shutil.copy2(source, dest)
    payload = {
        "copied": True,
        "placeholder": False,
        "reason": "copied_tested_manager_binary",
        "installer_relpath": "installer.exe",
        "sha256": sha256_file(dest),
        "size": dest.stat().st_size,
        "source": str(source),
        "manager_version": None,
        "note": (
            "manager_version is independent of APP_VERSION; supply it from "
            "the manager release, never from the current app build"
        ),
    }
    write_json(Path(app_root) / "manager-delivery.json", payload)
    return payload


def emit_delivery(
    *,
    flavor: str,
    profile: str,
    app_root: Path,
    exe_relpath: str,
    site_packages: Path | None,
    output_dir: Path,
    runtime_kwargs: Mapping[str, str],
    manager_source: Path | None = None,
    python_tag: str,
    platform_tag: str,
    package_revision: int = DEFAULT_PACKAGE_REVISION,
    min_manager_version: str = DEFAULT_MIN_MANAGER_VERSION,
) -> dict[str, Any]:
    require_supported_combination(flavor, profile)
    plan = collection_plan(flavor, profile)
    core = emit_core_manifests(
        app_root,
        exe_relpath=exe_relpath,
        runtime_kwargs=runtime_kwargs,
        min_manager_version=min_manager_version,
    )
    packages_dir = Path(output_dir) / "packages"
    staging_root = Path(output_dir) / "staging"
    if staging_root.exists():
        shutil.rmtree(staging_root)
    component_reports: list[dict[str, Any]] = []
    stagings: dict[str, Path] = {}
    licenses: list[dict[str, str]] = []
    dependencies: list[dict[str, str]] = []
    if site_packages is not None:
        for component in (COMPONENT_MEDIA, COMPONENT_MATLAB):
            staging = staging_root / component
            collect_component_staging(Path(site_packages), component, staging)
            stagings[component] = staging
            report = emit_component_zip(
                component=component,
                staging_root=staging,
                output_dir=packages_dir,
                runtime_id=core["runtime_id"],
                python_tag=python_tag,
                platform_tag=platform_tag,
                package_revision=package_revision,
                min_manager_version=min_manager_version,
            )
            component_reports.append(report)
            licenses.extend(report["licenses"])
            dependencies.extend(report["dependencies"])
    audit = audit_native_trees(app_root=app_root, component_stagings=stagings)
    manager = copy_tested_manager(app_root=app_root, manager_source=manager_source)
    delivery = {
        "flavor": flavor,
        "dependency_profile": profile,
        "collection_plan": plan,
        "core": core,
        "components": component_reports,
        "licenses": licenses,
        "dependencies": dependencies,
        "audit": audit,
        "manager": manager,
        "app_version_source": "mf4_analyzer.app_meta.APP_VERSION",
        "not_product_default": True,
    }
    write_json(Path(output_dir) / "delivery-audit.json", delivery)
    write_json(Path(app_root) / "licenses.json", {"licenses": licenses})
    write_json(Path(app_root) / "dependency-list.json", {"dependencies": dependencies})
    return delivery


def _add_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--flavor", choices=("full", "lite"), default="lite")
    parser.add_argument(
        "--profile",
        choices=("bundled", "modular"),
        default=DEFAULT_DEPENDENCY_PROFILE,
        help="Delivery profile. Default remains bundled; only lite+modular is emitted.",
    )
    parser.add_argument("--python-implementation")
    parser.add_argument("--python-version")
    parser.add_argument("--python-abi")
    parser.add_argument("--python-build-id")
    parser.add_argument("--arch", default="win-amd64")
    parser.add_argument("--numpy-version")
    parser.add_argument("--numpy-abi")
    parser.add_argument("--python-tag")
    parser.add_argument("--platform-tag", default="win_amd64")
    parser.add_argument(
        "--min-manager-version",
        default=DEFAULT_MIN_MANAGER_VERSION,
    )
    parser.add_argument("--package-revision", type=int, default=DEFAULT_PACKAGE_REVISION)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    _add_runtime_args(parser)
    parser.add_argument("--app-root", type=Path)
    parser.add_argument("--exe-relpath")
    parser.add_argument("--site-packages", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--manager-source", type=Path)
    parser.add_argument(
        "--plan-json",
        action="store_true",
        help="Print the unified collection plan and exit",
    )
    args = parser.parse_args(argv)
    try:
        require_supported_combination(args.flavor, args.profile)
    except UnsupportedDeliveryCombination as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.plan_json:
        print(json.dumps(collection_plan(args.flavor, args.profile), ensure_ascii=False, indent=2))
        return 0
    missing = [
        name
        for name, value in (
            ("--app-root", args.app_root),
            ("--exe-relpath", args.exe_relpath),
            ("--output-dir", args.output_dir),
        )
        if value in (None, "")
    ]
    if missing:
        parser.error("emit requires " + ", ".join(missing))
    runtime_kwargs = _runtime_kwargs_from_args(args)
    python_tag = args.python_tag or runtime_kwargs["python_abi"]
    try:
        delivery = emit_delivery(
            flavor=args.flavor,
            profile=args.profile,
            app_root=args.app_root,
            exe_relpath=args.exe_relpath,
            site_packages=args.site_packages,
            output_dir=args.output_dir,
            runtime_kwargs=runtime_kwargs,
            manager_source=args.manager_source,
            python_tag=python_tag,
            platform_tag=args.platform_tag,
            package_revision=args.package_revision,
            min_manager_version=args.min_manager_version,
        )
    except (UnsupportedDeliveryCombination, ExtensionBuildError, NativeIdentityError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(dumps_json(delivery), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
