"""Fixed native reads in the target interpreter; imports stay inside the probe."""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys

from .contract import ExtensionError, ReasonCode, parse_package_manifest
from .runtime import verify_package_tree
from .state import resolve_inside


def fixture_directory() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "assets" / "extension-probe"


def run_native_reads(package_roots: dict[str, Path]) -> dict:
    """Verify allowed trees, import their modules and read fixed bundled data."""
    original_path = list(sys.path)
    handles = []
    origins = {}
    checked = []
    files = []
    manifests = {}
    try:
        for component, root in package_roots.items():
            manifest = parse_package_manifest((root / "package.json").read_bytes())
            manifests[component] = manifest
            if manifest.component != component:
                raise ExtensionError(ReasonCode.PROBE_FAILED, "component identity mismatch")
            verify_package_tree(root, manifest.files, extensions=root.parent)
            # module_roots describe packages, not sys.path entries.
            for relative in manifest.module_roots:
                parent = str(resolve_inside(root, relative).parent)
                if parent not in sys.path:
                    sys.path.insert(0, parent)
            for relative in manifest.dll_directories:
                if hasattr(os, "add_dll_directory"):
                    handles.append(os.add_dll_directory(str(resolve_inside(root, relative))))
        from .native_identity import FileIdentity, assert_native_combination, classify_relpath
        groups = []
        for component, manifest in manifests.items():
            groups.append(tuple(FileIdentity(relpath=e.relpath, basename=Path(e.relpath).name,
                sha256=e.sha256, size=e.size, kind=classify_relpath(e.relpath), owner=component)
                for e in manifest.files))
        if getattr(sys, "frozen", False):
            from .runtime import identify_core
            core = identify_core(Path(sys.executable).resolve().parent)
            groups.append(tuple(FileIdentity(relpath=e.relpath, basename=Path(e.relpath).name,
                sha256=e.sha256, size=e.size, kind=classify_relpath(e.relpath), owner="base")
                for e in core.files.files))
        assert_native_combination(*groups)
        importlib.invalidate_caches()
        for component, root in package_roots.items():
            names = ("av",) if component == "media" else ("scipy", "h5py")
            for name in names:
                module = importlib.import_module(name)
                origin = Path(module.__file__).resolve()
                if not origin.is_relative_to(root.resolve()):
                    raise ExtensionError(ReasonCode.PROBE_FAILED,
                                         f"{name} loaded outside selected extension: {origin}")
                origins[name] = str(origin)
        from mf4_analyzer.io.loader import DataLoader

        for component in package_roots:
            names = ("sample.wav", "sample.mp4") if component == "media" else ("legacy.mat", "sample-v73.mat")
            for name in names:
                path = fixture_directory() / name
                if component == "media":
                    data, channels, _units, _fs, _meta = DataLoader.load_audio_video(path)
                    count = len(channels)
                    if not getattr(data, "size", 0):
                        raise ExtensionError(ReasonCode.PROBE_FAILED, f"empty samples: {name}")
                else:
                    groups = DataLoader.load_mat(path)
                    count = sum(len(group["channels"]) for group in groups)
                if count <= 0:
                    raise ExtensionError(ReasonCode.PROBE_FAILED, f"empty native read: {name}")
                files.append({"name": name, "channels": count})
            checked.append(component)
        # Check extension submodule origins too, including native .pyd/.so.
        for name, module in tuple(sys.modules.items()):
            top = name.split(".")[0]
            component = "media" if top == "av" else "matlab" if top in {"scipy", "h5py", "hdf5storage"} else None
            origin = getattr(module, "__file__", None)
            if component in package_roots and origin:
                if not Path(origin).resolve().is_relative_to(package_roots[component].resolve()):
                    raise ExtensionError(ReasonCode.PROBE_FAILED, f"foreign native/module origin: {name}")
        dll_origins = _loaded_extension_dlls(manifests, package_roots) if os.name == "nt" else {}
        return {"ok": True, "checked": checked, "files": files, "module_origins": origins,
                "dll_origins": dll_origins, "native_reads": True, "frozen": bool(getattr(sys, "frozen", False))}
    finally:
        sys.path[:] = original_path
        for handle in handles:
            handle.close()


def _loaded_extension_dlls(manifests, package_roots):
    """Observe this child's loaded modules; never open another process."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.K32EnumProcessModules.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE),
                                            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel.K32EnumProcessModules.restype = wintypes.BOOL
    kernel.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetModuleFileNameW.restype = wintypes.DWORD
    modules = (wintypes.HMODULE * 4096)()
    needed = wintypes.DWORD()
    if not kernel.K32EnumProcessModules(kernel.GetCurrentProcess(), modules, ctypes.sizeof(modules), ctypes.byref(needed)):
        raise ctypes.WinError(ctypes.get_last_error())
    if needed.value > ctypes.sizeof(modules):
        raise RuntimeError("loaded module list exceeded probe capacity")
    paths = []
    for module in modules[:needed.value // ctypes.sizeof(wintypes.HMODULE)]:
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel.GetModuleFileNameW(module, buffer, len(buffer))
        if not length or length >= len(buffer):
            raise ctypes.WinError(ctypes.get_last_error())
        paths.append(Path(buffer.value))
    core_root, core_files = None, ()
    if getattr(sys, "frozen", False):
        from .runtime import identify_core
        core_root = Path(sys.executable).resolve().parent
        core_files = identify_core(core_root).files.files
    return _audit_loaded_native_paths(paths, manifests=manifests, package_roots=package_roots,
                                      core_root=core_root, core_files=core_files)


def _native_path_key(path):
    # GetModuleFileNameW can return the ordinary spelling while the store uses
    # extended paths. Resolve first, then compare the equivalent path spelling.
    text = os.path.normcase(str(Path(path).resolve()))
    if text.startswith("\\\\?\\"):
        text = text[4:]
        if text.lower().startswith("unc\\"):
            text = "\\\\" + text[4:]
    return text


def _audit_loaded_native_paths(paths, *, manifests, package_roots, core_root=None, core_files=()):
    from .native_identity import sha256_file

    expected = {}
    watched_names = set()
    for component, manifest in manifests.items():
        for entry in manifest.files:
            relative = Path(entry.relpath)
            if relative.suffix.lower() in {".dll", ".pyd"}:
                path = package_roots[component] / relative
                expected[_native_path_key(path)] = (path, entry.sha256)
                watched_names.add(relative.name.lower())
    # PYD names are package-scoped: pandas and scipy may both load their own
    # _cyutility.pyd. Base copies must match the base manifest at that exact
    # path, not the component's same-basename hash. Shared-DLL basename
    # conflicts are still rejected by assert_native_combination before loading.
    if core_root is not None:
        for entry in core_files:
            if Path(entry.relpath).name.lower() in watched_names:
                path = core_root / entry.relpath
                expected[_native_path_key(path)] = (path, entry.sha256)
    origins = {}
    for observed in paths:
        path = Path(observed).resolve()
        if path.name.lower() not in watched_names:
            continue
        entry = expected.get(_native_path_key(path))
        if entry is None or sha256_file(entry[0]) != entry[1]:
            raise ExtensionError(ReasonCode.PROBE_FAILED, f"foreign loaded DLL: {path}")
        # Full-path keys retain both package-scoped modules in the evidence.
        origins[str(path)] = str(path)
    return origins
