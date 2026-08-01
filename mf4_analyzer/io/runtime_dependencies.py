"""Frozen-build runtime dependencies for optional data import formats.

The importers deliberately keep heavyweight libraries as lazy imports so the
normal application startup stays fast.  PyInstaller cannot always discover
those imports, therefore this module is the single contract shared by the
Windows build scripts and their regression checks.
"""
from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import re
import sys
from typing import Iterable


@dataclass(frozen=True)
class FrozenImportDependency:
    """A package required by a frozen product runtime path."""

    package: str
    requirement_name: str
    extensions: tuple[str, ...]
    purpose: str


WINDOWS_BUILD_FLAVORS = frozenset({"full", "lite"})


# Keep this list small and product-facing: a package belongs here only when a
# documented import or export path needs it at runtime.  The Windows builders turn
# it into ``--collect-all`` arguments, including compiled extensions and data
# files which a lazy import might otherwise evade during PyInstaller analysis.
FROZEN_IMPORT_DEPENDENCIES = (
    FrozenImportDependency(
        package="asammdf",
        requirement_name="asammdf",
        extensions=(".mf4", ".mdf"),
        purpose="ASAM MDF reader",
    ),
    FrozenImportDependency(
        package="openpyxl",
        requirement_name="openpyxl",
        extensions=(".xlsx",),
        purpose="Office Open XML workbook reader",
    ),
    FrozenImportDependency(
        package="xlrd",
        requirement_name="xlrd",
        extensions=(".xls",),
        purpose="legacy binary Excel workbook reader",
    ),
    FrozenImportDependency(
        package="can",
        requirement_name="python-can",
        extensions=(".blf",),
        purpose="Vector BLF reader",
    ),
    FrozenImportDependency(
        package="cantools",
        requirement_name="cantools",
        extensions=(".blf",),
        purpose="BLF DBC decoder",
    ),
    FrozenImportDependency(
        package="nptdms",
        requirement_name="nptdms",
        extensions=(".tdms",),
        purpose="NI TDMS reader",
    ),
    FrozenImportDependency(
        package="av",
        requirement_name="av",
        extensions=(
            ".mp4", ".mov", ".mkv", ".m4v", ".mp3", ".m4a", ".aac",
            ".wav", ".flac",
        ),
        purpose="audio/video reader",
    ),
    FrozenImportDependency(
        package="scipy",
        requirement_name="scipy",
        extensions=(".mat",),
        purpose="MATLAB v4-v7 reader (scipy.io.loadmat)",
    ),
    FrozenImportDependency(
        package="h5py",
        requirement_name="h5py",
        extensions=(".mat",),
        purpose="MATLAB v7.3 (HDF5) reader",
    ),
)

LITE_SCIPY_EXCLUDED_MODULES = (
    "scipy.optimize",
    "scipy.special",
    "scipy.linalg",
    "scipy.spatial",
    "scipy.interpolate",
    "scipy.stats",
    "scipy.signal",
    "scipy.fft",
    "scipy.integrate",
    "scipy.ndimage",
)


# These are deliberate build-flavor boundaries, not missing runtime packages.
# Full builds vendor the native acquisition roots outside PyInstaller analysis;
# lite builds omit the acquisition feature entirely.  Lite additionally prunes
# only the SciPy submodules listed above after keeping ``scipy.io`` available.
INTENTIONAL_EXCLUDED_ROOTS_BY_FLAVOR = {
    "full": frozenset({"pyxcp", "pya2l"}),
    "lite": frozenset(
        {
            "mf4_analyzer.acquisition",
            "mf4_analyzer.acquisition_ui",
            "mf4_analyzer.acquisition_capture",
            "pyxcp",
            "pya2l",
        }
    ),
}
INTENTIONAL_EXCLUDED_SUBMODULES_BY_FLAVOR = {
    "full": frozenset(),
    "lite": frozenset(LITE_SCIPY_EXCLUDED_MODULES),
}
REQUIRED_EXTERNAL_RUNTIME_ROOTS_BY_FLAVOR = {
    flavor: frozenset(
        dependency.package for dependency in FROZEN_IMPORT_DEPENDENCIES
    )
    for flavor in WINDOWS_BUILD_FLAVORS
}


def dependencies_for_extension(extension: str) -> tuple[FrozenImportDependency, ...]:
    """Return the frozen runtime dependencies for a supported suffix."""
    suffix = str(extension or "").lower()
    if suffix and not suffix.startswith("."):
        suffix = f".{suffix}"
    return tuple(
        dependency
        for dependency in FROZEN_IMPORT_DEPENDENCIES
        if suffix in dependency.extensions
    )


def pyinstaller_collection_args(flavor: str = "full") -> tuple[str, ...]:
    """Return PyInstaller arguments for a supported Windows build flavor."""
    if flavor not in WINDOWS_BUILD_FLAVORS:
        raise ValueError(f"unknown frozen-build flavor: {flavor}")

    args: list[str] = []
    for dependency in FROZEN_IMPORT_DEPENDENCIES:
        if flavor == "lite" and dependency.package == "scipy":
            # Let PyInstaller trace the loadmat import graph instead of adding
            # unrelated SciPy toolkits. Its standard SciPy hook still includes
            # the native dependency closure required by the discovered modules.
            args.extend(("--hidden-import", "scipy.io"))
            args.extend(("--hidden-import", "scipy.io.matlab"))
            continue
        args.extend(("--collect-all", dependency.package))
    if flavor == "lite":
        for module in LITE_SCIPY_EXCLUDED_MODULES:
            args.extend(("--exclude-module", module))
    return tuple(args)


def validate_windows_packaging_contract(
    requirements_path: Path,
    build_scripts: Iterable[Path],
    *,
    require_installed: bool = False,
) -> tuple[str, ...]:
    """Return human-readable contract violations without mutating anything."""
    installed = _requirements_packages(requirements_path)
    failures = [
        f"requirements.txt 缺少 {dependency.requirement_name}；"
        f"{', '.join(dependency.extensions)} 导入需要它"
        for dependency in FROZEN_IMPORT_DEPENDENCIES
        if _normalize_package(dependency.requirement_name) not in installed
    ]
    if require_installed:
        failures.extend(
            f"构建虚拟环境缺少 {dependency.package}；不要在依赖未安装时使用 -SkipInstall"
            for dependency in FROZEN_IMPORT_DEPENDENCIES
            if importlib.util.find_spec(dependency.package) is None
        )

    for script in build_scripts:
        try:
            text = Path(script).read_text(encoding="utf-8")
        except OSError as exc:
            failures.append(f"无法读取 Windows 构建脚本 {script}: {exc}")
            continue
        label = Path(script).name
        if "windows_runtime_dependencies.py" not in text:
            failures.append(f"{label} 未调用统一的运行依赖清单")
        flavor = _build_script_flavor(text)
        if flavor is None:
            failures.append(f"{label} does not declare a frozen-build flavor")
            continue
        failures.extend(
            _excluded_runtime_dependency_failures(
                label, flavor, _script_excluded_modules(text)
            )
        )
        failures.extend(
            _excluded_runtime_dependency_failures(
                "shared frozen runtime arguments",
                flavor,
                _pyinstaller_excluded_modules(pyinstaller_collection_args(flavor)),
            )
        )

    declared_modules = {
        dependency.package.split(".", 1)[0]
        for dependency in FROZEN_IMPORT_DEPENDENCIES
    }
    lazy_modules = lazy_import_dependency_roots(
        Path(requirements_path).parent / "mf4_analyzer" / "io"
    )
    undeclared = sorted(lazy_modules - declared_modules)
    if undeclared:
        failures.append(
            "io 懒导入未登记到冻结包运行依赖清单: "
            + ", ".join(undeclared)
        )
    if not FROZEN_IMPORT_DEPENDENCIES:
        failures.append("冻结包运行依赖清单不能为空")
    return tuple(failures)


def _build_script_flavor(text: str) -> str | None:
    match = re.search(r"--pyinstaller-args-json\s+--flavor\s+(full|lite)\b", text)
    return match.group(1) if match else None


def _script_excluded_modules(text: str) -> tuple[str, ...]:
    return tuple(
        re.findall(
            r'["\']--exclude-module["\']\s*,\s*["\']([^"\']+)["\']',
            text,
            flags=re.IGNORECASE,
        )
    )


def _pyinstaller_excluded_modules(args: Iterable[str]) -> tuple[str, ...]:
    arguments = tuple(args)
    return tuple(
        value
        for argument, value in zip(arguments, arguments[1:])
        if argument == "--exclude-module"
    )


def _excluded_runtime_dependency_failures(
    label: str, flavor: str, exclusions: Iterable[str]
) -> list[str]:
    """Check only declared product dependencies for this build flavor.

    The PowerShell scripts intentionally exclude vendored acquisition roots and
    lite-only SciPy submodules.  Do not turn this into a source-wide import
    scan: development-only ``tools/`` imports and unrelated PyInstaller
    pruning are outside the frozen product runtime contract.
    """
    required_roots = REQUIRED_EXTERNAL_RUNTIME_ROOTS_BY_FLAVOR[flavor]
    intentional_roots = INTENTIONAL_EXCLUDED_ROOTS_BY_FLAVOR[flavor]
    intentional_submodules = INTENTIONAL_EXCLUDED_SUBMODULES_BY_FLAVOR[flavor]
    failures: list[str] = []
    for module in exclusions:
        normalized = module.lower()
        root = normalized.split(".", 1)[0]
        if normalized in intentional_roots or normalized in intentional_submodules:
            continue
        if normalized in required_roots:
            failures.append(
                f"{label} excludes required runtime dependency {normalized} for {flavor}"
            )
        elif root in required_roots and "." in normalized:
            failures.append(
                f"{label} excludes required runtime dependency submodule {normalized} for {flavor}"
            )
    return failures


def _requirements_packages(path: Path) -> set[str]:
    packages: set[str] = set()
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith(("-", ".")):
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)", line)
        if match:
            packages.add(_normalize_package(match.group(1)))
    return packages


def _normalize_package(value: str) -> str:
    return str(value).strip().lower().replace("_", "-")


def lazy_import_dependency_roots(io_dir: Path) -> set[str]:
    """Find third-party imports nested in importer functions.

    Top-level dependencies are visible to PyInstaller's static graph.  Imports
    nested in functions are intentionally lazy but need an explicit frozen
    contract.  Scanning all ``io/*.py`` means a new format importer cannot add
    a lazy package and accidentally ship without it.
    """
    import ast

    stdlib = set(getattr(sys, "stdlib_module_names", set())) | {
        "csv", "io", "typing", "collections", "contextlib", "dataclasses",
        "functools", "itertools", "json", "math", "os", "pathlib", "re",
        "statistics", "sys", "time", "warnings",
    }
    roots: set[str] = set()
    for source in Path(io_dir).rglob("*.py"):
        if source.name == "runtime_dependencies.py":
            continue
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        except (OSError, SyntaxError):
            continue
        for function in (
            node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            for node in ast.walk(function):
                modules: tuple[str, ...]
                if isinstance(node, ast.Import):
                    modules = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    modules = (node.module,)
                else:
                    continue
                for module in modules:
                    root = module.split(".", 1)[0]
                    if root in stdlib or root == "mf4_analyzer":
                        continue
                    roots.add(root)
    return roots
