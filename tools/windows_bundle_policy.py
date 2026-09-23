"""Shared, build-only slimming policy for Windows Full, Lite and Modular.

Python modules are excluded during Analysis, never deleted out of a frozen
archive. Post-collection pruning handles Qt's unconditional extra DLLs and
collect-all's resource/source copies. Validate the entire plan before deleting
anything; the builders must run their frozen acceptance checks AFTER this tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


COMMON_EXCLUDES = (
    "pytest", "_pytest", "nptdms.test", "numexpr.tests",
    "pyqtgraph.examples", "pyqtgraph.opengl", "asammdf.gui", "asammdf.tool",
    "qtawesome.tests", "qtawesome.icon_browser",
    "PIL.AvifImagePlugin", "PIL._avif",
    "lxml.objectify", "lxml.html", "lxml.doctestcompare", "lxml.usedoctest",
)
# Full's vendored pya2l/pyxcp closure uses SQLAlchemy and rich/Pygments.
# Do not apply analyzer-only exclusions to that build or its vendor directories.
LITE_EXCLUDES = ("sqlalchemy", "pygments")
UNUSED_QT_MODULES = (
    "PyQt5.QtOpenGL", "PyQt5.QtQml", "PyQt5.QtQuick",
    "PyQt5.QtQuickWidgets", "PyQt5.QtWebSockets",
)
UNUSED_QT_BINARIES = frozenset({
    "opengl32sw.dll", "libEGL.dll", "libGLESv2.dll", "d3dcompiler_47.dll",
    "Qt5OpenGL.dll", "Qt5Quick.dll", "Qt5Qml.dll", "Qt5QmlModels.dll",
    "Qt5WebSockets.dll",
})
UNUSED_RESOURCE_TREES = (
    "asammdf/gui", "nptdms/test", "pyqtgraph/examples", "qtawesome/tests",
)
# These audited importers use frozen bytecode, not their source text. Never
# strip vendor sources, arbitrary .py files, metadata, licenses, or schemas.
SOURCE_COPY_ROOTS = frozenset({"asammdf", "openpyxl", "xlrd", "nptdms", "can"})
REQUIRED_FILES = (
    "PyQt5/Qt5/bin/Qt5Core.dll", "PyQt5/Qt5/bin/Qt5Gui.dll",
    "PyQt5/Qt5/bin/Qt5Widgets.dll",
    "PyQt5/Qt5/plugins/platforms/qwindows.dll",
    "PyQt5/Qt5/plugins/platforms/qoffscreen.dll",
)


def excluded_modules(flavor: str) -> tuple[str, ...]:
    if flavor not in {"full", "lite"}:
        raise ValueError(f"Unknown build flavor: {flavor}")
    return COMMON_EXCLUDES + (LITE_EXCLUDES if flavor == "lite" else ())


def pyinstaller_args(flavor: str) -> list[str]:
    return [part for name in excluded_modules(flavor)
            for part in ("--exclude-module", name)]


def prune_reason(relative: Path, modules: set[str]) -> str | None:
    """Select only named payloads beneath _internal; unknown files are kept."""
    name = relative.as_posix()
    if relative.parent.as_posix() == "PyQt5/Qt5/bin" and relative.name in UNUSED_QT_BINARIES:
        return "unused Qt OpenGL/QML runtime"
    if name == "PyQt5/Qt5/plugins/platforms/qwebgl.dll":
        return "unused WebGL platform"
    if name.startswith("PyQt5/Qt5/translations/") and relative.suffix == ".qm":
        if not relative.stem.endswith(("_zh_CN", "_zh_TW", "_en", "_en_GB", "_en_US")):
            return "unused Qt translation"
    if any(name.startswith(tree + "/") for tree in UNUSED_RESOURCE_TREES):
        return "third-party GUI/test/example resources"
    # Keep the SVG fallback and the actual plot-control icons (auto, lock, ...).
    if name.startswith("pyqtgraph/icons/peegee/") and relative.suffix == ".png":
        return "redundant pyqtgraph brand raster (SVG retained)"
    if relative.parts[0] in SOURCE_COPY_ROOTS and relative.suffix == ".py":
        module = name[:-3].replace("/", ".").removesuffix(".__init__")
        if module in modules:
            return "source copy already present as frozen bytecode"
    return None


def read_frozen_modules(exe: Path) -> set[str]:
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(exe))
    names = [name for name, entry in archive.toc.items() if entry[-1] == "z"]
    if len(names) != 1:
        raise ValueError(f"Expected one PYZ archive in {exe}, found {names}")
    return set(archive.open_embedded_archive(names[0]).toc)


def read_pe_imports(path: Path) -> set[str]:
    import pefile  # Installed with PyInstaller on Windows; never a product dependency.

    pe = pefile.PE(str(path), fast_load=True)
    try:
        pe.parse_data_directories(directories=[1, 13])  # imports + delay imports
        return {
            entry.dll.decode("ascii").lower()
            for attr in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT")
            for entry in getattr(pe, attr, ())
        }
    finally:
        pe.close()


def read_pe_runtime_signature(path: Path) -> tuple[int, tuple[int, ...], set[tuple[int, bytes | None]]]:
    import pefile

    pe = pefile.PE(str(path))
    try:
        if not getattr(pe, "VS_FIXEDFILEINFO", None) or not getattr(pe, "DIRECTORY_ENTRY_EXPORT", None):
            raise ValueError(f"MSVC runtime lacks version/export evidence: {path}")
        info = pe.VS_FIXEDFILEINFO[0]
        version = (info.FileVersionMS >> 16, info.FileVersionMS & 0xffff,
                   info.FileVersionLS >> 16, info.FileVersionLS & 0xffff)
        exports = {(item.ordinal, item.name) for item in pe.DIRECTORY_ENTRY_EXPORT.symbols}
        return pe.FILE_HEADER.Machine, version, exports
    finally:
        pe.close()


def modular_crt_duplicates(internal: Path) -> dict[Path, str]:
    """Retain Python's x64 CRT only after proving it covers Qt's older copy."""
    canonical_files = {p.name.lower(): p for p in internal.iterdir() if p.is_file()}
    duplicates = {}
    for duplicate in (internal / "PyQt5/Qt5/bin").iterdir():
        if duplicate.name.lower() not in {"vcruntime140.dll", "vcruntime140_1.dll"}:
            continue
        canonical = canonical_files.get(duplicate.name.lower())
        if canonical is None:
            raise ValueError(f"MSVC runtime has no canonical base copy: {duplicate}")
        machine, version, exports = read_pe_runtime_signature(canonical)
        old_machine, old_version, old_exports = read_pe_runtime_signature(duplicate)
        if (machine != 0x8664 or old_machine != machine or version[0] != 14
                or old_version[0] != 14 or version < old_version
                or not old_exports or not old_exports <= exports):
            raise ValueError(f"MSVC runtime replacement is not compatible: {canonical} vs {duplicate}")
        duplicates[duplicate] = f"duplicate MSVC runtime; retain validated _internal/{canonical.name}"
    return duplicates


def prune_bundle(exe: Path, flavor: str, report: Path, *, dry_run: bool = False,
                 profile: str = "bundled") -> dict:
    if profile not in {"bundled", "modular"}:
        raise ValueError(f"Unknown dependency profile: {profile}")
    excluded = excluded_modules(flavor) + UNUSED_QT_MODULES
    exe = exe.absolute()
    root = exe.parent
    internal = root / "_internal"
    if not exe.is_file() or exe.suffix.lower() != ".exe" or not internal.is_dir():
        raise ValueError("Expected a generated Windows onedir exe with _internal")
    if report.resolve().is_relative_to(root.resolve()):
        raise ValueError("Prune report must be outside the bundle")
    # Reject links/junctions before enumerating deletion candidates. In
    # particular, never follow a packaged vendor link into a build environment.
    paths = [root, *root.rglob("*")]
    for path in paths:
        is_junction = getattr(path, "is_junction", lambda: False)
        if path.is_symlink() or is_junction() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Bundle link or escaped path is not supported: {path}")
    for name in REQUIRED_FILES:
        if not (internal / name).is_file():
            raise ValueError(f"Required Qt runtime file missing: {name}")
    modules = read_frozen_modules(exe)
    leaks = sorted(name for name in modules
                   if any(name == item or name.startswith(item + ".") for item in excluded))
    if leaks:
        raise ValueError(f"Excluded modules leaked into PYZ; fix Analysis arguments: {leaks}")
    files = [path for path in paths if path.is_file()]
    candidates = {}
    for path in files:
        if path.is_relative_to(internal):
            reason = prune_reason(path.relative_to(internal), modules)
            if reason:
                candidates[path] = reason
    crt_duplicates = modular_crt_duplicates(internal) if profile == "modular" else {}
    candidates.update(crt_duplicates)
    # CRT basenames remain available from the validated canonical base files.
    # No other same-basename or dependency conflict is exempted here.
    removed_dlls = {p.name.lower() for p in candidates
                   if p.suffix.lower() == ".dll" and p not in crt_duplicates}
    # Qt also loads plugins dynamically; the explicit policy above covers those.
    # This guard additionally rejects new native dependencies after Qt upgrades.
    for path in files:
        if path not in candidates and path.suffix.lower() in {".dll", ".pyd", ".exe"}:
            needed = {name.lower() for name in read_pe_imports(path)} & removed_dlls
            if needed:
                raise ValueError(f"Retained binary {path} depends on pruned DLLs: {sorted(needed)}")
    entries = [{"path": str(p.relative_to(root)), "bytes": p.stat().st_size, "reason": reason}
               for p, reason in sorted(candidates.items())]
    before = sum(p.stat().st_size for p in files)
    candidate_bytes = sum(entry["bytes"] for entry in entries)
    result = {
        "flavor": flavor, "profile": profile, "exe": str(exe), "dry_run": dry_run,
        "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
        "before_bytes": before, "candidate_bytes": candidate_bytes,
        "removed_bytes": 0, "after_bytes": before, "files": entries,
        "status": "validated" if dry_run else "pending",
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if not dry_run:
        for path in candidates:
            path.unlink()
        result.update(status="pruned", removed_bytes=candidate_bytes,
                      after_bytes=before - candidate_bytes)
        report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flavor", choices=("full", "lite"), required=True)
    parser.add_argument("--profile", choices=("bundled", "modular"), default="bundled")
    parser.add_argument("--pyinstaller-args-json", action="store_true")
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.pyinstaller_args_json:
        print(json.dumps(pyinstaller_args(args.flavor)))
    else:
        if args.exe is None or args.report is None:
            parser.error("pruning requires --exe and --report")
        result = prune_bundle(args.exe, args.flavor, args.report, dry_run=args.dry_run, profile=args.profile)
        print(f"Bundle policy: {result['status']}; removed {result['removed_bytes'] / 2**20:.2f} MiB; "
              f"after {result['after_bytes'] / 2**20:.2f} MiB; report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
