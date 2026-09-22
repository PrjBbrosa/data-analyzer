"""Content identity for native shared libraries and Python modules.

This module is stdlib-only.  It must not import Qt, TUF, av, SciPy, or h5py.
File-tree collection is path + SHA-256; macOS temp files are enough to prove
the contract.  Windows DLL artifacts are not required.

Same-basename native files with different content refuse a combination.
Shared NumPy / Python / Qt trees belong to base; a component may not copy
or overlay them.  Directory search order is not a compatibility strategy.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable, Mapping, Sequence


KIND_PYTHON_MODULE = "python_module"
KIND_NATIVE_SHARED = "native_shared"
KIND_OTHER = "other"

OWNER_BASE = "base"
OWNER_MEDIA = "media"
OWNER_MATLAB = "matlab"
COMPONENT_OWNERS = frozenset({OWNER_MEDIA, OWNER_MATLAB})

REASON_NATIVE_DLL_CONFLICT = "NATIVE_DLL_CONFLICT"

NATIVE_SUFFIXES = frozenset({".dll", ".pyd", ".so", ".dylib"})
PYTHON_MODULE_SUFFIXES = frozenset({".py", ".pyc", ".pyo", ".pyi"})

BASE_PROTECTED_MODULE_ROOTS = frozenset(
    {
        "numpy",
        "pandas",
        "pyqt5",
        "pyqtgraph",
        "mf4_analyzer",
    }
)
BASE_PROTECTED_PATH_PARTS = frozenset(
    {
        "numpy",
        "numpy.libs",
        "pandas",
        "pyqt5",
        "pyqtgraph",
        "mf4_analyzer",
    }
)
BASE_PROTECTED_NATIVE_PREFIXES = (
    "python3",
    "python311",
    "python312",
    "python313",
    "libpython",
    "qt5core",
    "qt6core",
    "qt5gui",
    "qt6gui",
    "qt5widgets",
    "qt6widgets",
)

# Selectors for libraries hashed into runtime_id.  Qt is base-owned but not
# a native-extension ABI input, so it is excluded from the fingerprint.
CORE_LIBRARY_SELECTORS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("python", "cpython_shared", ("python3", "libpython")),
    ("numpy", "capi", ("openblas",)),
    ("msvc_runtime", "ucrt", ("vcruntime", "msvcp140")),
)

REQUIRED_CORE_SHARED_LIBRARY_NAMES = frozenset({"python", "numpy"})

_SHA256_HEX_LEN = 64


@dataclass(frozen=True)
class SharedLibraryIdentity:
    """One shared library whose bytes participate in ``runtime_id``."""

    name: str
    role: str
    basename: str
    sha256: str
    size: int = 0
    relpath: str = ""

    def to_payload(self) -> dict[str, str]:
        return {
            "basename": self.basename,
            "name": self.name,
            "role": self.role,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class FileIdentity:
    """Path + SHA-256 snapshot of one file in a real tree."""

    relpath: str
    basename: str
    sha256: str
    size: int
    kind: str
    owner: str = "unknown"


@dataclass(frozen=True)
class NativeConflict:
    """One reason a base + component combination must be refused."""

    reason_code: str
    kind: str
    basename: str
    left_relpath: str
    right_relpath: str
    left_owner: str
    right_owner: str
    left_sha256: str
    right_sha256: str


class NativeIdentityError(Exception):
    """Combination or build identity was refused with a stable reason code."""

    def __init__(
        self,
        reason_code: str,
        message: str = "",
        conflicts: Sequence[NativeConflict] = (),
    ) -> None:
        self.reason_code = reason_code
        self.conflicts = tuple(conflicts)
        super().__init__(message or reason_code)


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def classify_relpath(relpath: str) -> str:
    name = str(relpath).rsplit("/", 1)[-1].lower()
    if name.endswith((".dll", ".pyd", ".dylib")):
        return KIND_NATIVE_SHARED
    if name.endswith(".so") or ".so." in name:
        return KIND_NATIVE_SHARED
    if name.endswith(tuple(PYTHON_MODULE_SUFFIXES)):
        return KIND_PYTHON_MODULE
    return KIND_OTHER


def python_module_root(relpath: str) -> str | None:
    parts = [part for part in str(relpath).replace("\\", "/").split("/") if part]
    if not parts:
        return None
    if "site-packages" in parts:
        index = parts.index("site-packages")
        if index + 1 >= len(parts):
            return None
        nxt = parts[index + 1]
        if nxt.endswith(tuple(PYTHON_MODULE_SUFFIXES)):
            return nxt.rsplit(".", 1)[0]
        return nxt
    first = parts[0]
    if first.endswith(tuple(PYTHON_MODULE_SUFFIXES)):
        return first.rsplit(".", 1)[0]
    if classify_relpath(relpath) == KIND_PYTHON_MODULE:
        return first
    return None


def is_base_protected(identity: FileIdentity) -> bool:
    """True when a file belongs to a shared dependency the base must own."""
    root = python_module_root(identity.relpath)
    if root is not None and root.lower() in BASE_PROTECTED_MODULE_ROOTS:
        return True
    parts = {part.lower() for part in identity.relpath.replace("\\", "/").split("/")}
    if parts & BASE_PROTECTED_PATH_PARTS:
        return True
    basename = identity.basename.lower()
    return any(basename.startswith(prefix) for prefix in BASE_PROTECTED_NATIVE_PREFIXES)


def collect_file_identities(
    root: Path,
    *,
    owner: str = "unknown",
) -> tuple[FileIdentity, ...]:
    """Walk a real directory tree and return path + SHA-256 identities."""
    base = Path(root)
    if not base.is_dir():
        raise FileNotFoundError(f"identity root is not a directory: {base}")
    collected: list[FileIdentity] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relpath = path.relative_to(base).as_posix()
        collected.append(
            FileIdentity(
                relpath=relpath,
                basename=path.name,
                sha256=sha256_file(path),
                size=path.stat().st_size,
                kind=classify_relpath(relpath),
                owner=str(owner),
            )
        )
    return tuple(collected)


def select_core_shared_libraries(
    identities: Sequence[FileIdentity],
) -> tuple[SharedLibraryIdentity, ...]:
    """Pick ABI-affecting base libraries from a collected identity list."""
    selected: list[SharedLibraryIdentity] = []
    seen: set[tuple[str, str]] = set()
    for identity in identities:
        if identity.kind != KIND_NATIVE_SHARED:
            continue
        lowered = identity.basename.lower()
        for name, role, needles in CORE_LIBRARY_SELECTORS:
            if not any(needle in lowered for needle in needles):
                continue
            key = (name, identity.basename.lower())
            if key in seen:
                break
            seen.add(key)
            selected.append(
                SharedLibraryIdentity(
                    name=name,
                    role=role,
                    basename=identity.basename,
                    sha256=identity.sha256,
                    size=identity.size,
                    relpath=identity.relpath,
                )
            )
            break
    return tuple(sorted(selected, key=lambda item: (item.name, item.basename, item.sha256)))


def collect_core_shared_libraries(
    root: Path,
    *,
    owner: str = OWNER_BASE,
) -> tuple[SharedLibraryIdentity, ...]:
    return select_core_shared_libraries(collect_file_identities(root, owner=owner))


def find_native_conflicts(
    *groups: Sequence[FileIdentity],
) -> tuple[NativeConflict, ...]:
    """Return combination refusals; empty means the trees may be composed."""
    identities = tuple(item for group in groups for item in group)
    conflicts: list[NativeConflict] = []
    seen: set[tuple[str, str, str, str]] = set()

    def _add(conflict: NativeConflict) -> None:
        key = (
            conflict.kind,
            conflict.basename.lower(),
            conflict.left_relpath,
            conflict.right_relpath,
        )
        if key in seen:
            return
        seen.add(key)
        conflicts.append(conflict)

    base_files = [item for item in identities if item.owner == OWNER_BASE]
    for identity in identities:
        if identity.owner not in COMPONENT_OWNERS:
            continue
        if not is_base_protected(identity):
            continue
        counterpart = next(
            (
                item
                for item in base_files
                if item.basename.lower() == identity.basename.lower()
                or python_module_root(item.relpath) == python_module_root(identity.relpath)
            ),
            None,
        )
        kind = (
            "base_owned_native"
            if identity.kind == KIND_NATIVE_SHARED
            else "base_owned_module"
        )
        _add(
            NativeConflict(
                reason_code=REASON_NATIVE_DLL_CONFLICT,
                kind=kind,
                basename=identity.basename,
                left_relpath=counterpart.relpath if counterpart else "",
                right_relpath=identity.relpath,
                left_owner=OWNER_BASE,
                right_owner=identity.owner,
                left_sha256=counterpart.sha256 if counterpart else "",
                right_sha256=identity.sha256,
            )
        )

    natives_by_name: dict[str, list[FileIdentity]] = {}
    for identity in identities:
        if identity.kind != KIND_NATIVE_SHARED:
            continue
        natives_by_name.setdefault(identity.basename.lower(), []).append(identity)
    for basename, items in natives_by_name.items():
        hashes = {item.sha256 for item in items}
        if len(hashes) < 2:
            continue
        left, right = items[0], next(item for item in items if item.sha256 != items[0].sha256)
        _add(
            NativeConflict(
                reason_code=REASON_NATIVE_DLL_CONFLICT,
                kind="basename_hash_mismatch",
                basename=left.basename,
                left_relpath=left.relpath,
                right_relpath=right.relpath,
                left_owner=left.owner,
                right_owner=right.owner,
                left_sha256=left.sha256,
                right_sha256=right.sha256,
            )
        )
    return tuple(conflicts)


def assert_native_combination(*groups: Sequence[FileIdentity]) -> None:
    """Refuse a combination that would paper over same-name DLL mismatch."""
    conflicts = find_native_conflicts(*groups)
    if not conflicts:
        return
    first = conflicts[0]
    raise NativeIdentityError(
        first.reason_code,
        (
            f"{first.kind}: {first.basename} "
            f"({first.left_owner}:{first.left_relpath} vs "
            f"{first.right_owner}:{first.right_relpath})"
        ),
        conflicts,
    )


def require_sha256(value: str, *, what: str = "sha256") -> str:
    digest = str(value).strip().lower()
    if len(digest) != _SHA256_HEX_LEN or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{what} must be 64 lowercase hex characters")
    return digest


def shared_library_from_mapping(raw: Mapping[str, object]) -> SharedLibraryIdentity:
    return SharedLibraryIdentity(
        name=str(raw.get("name", "")).strip(),
        role=str(raw.get("role", "")).strip(),
        basename=str(raw.get("basename", "")).strip(),
        sha256=require_sha256(str(raw.get("sha256", "")), what="shared library sha256"),
        size=int(raw.get("size", 0) or 0),
        relpath=str(raw.get("relpath", "")).strip(),
    )


def iter_owned_identities(
    trees: Mapping[str, Path] | Iterable[tuple[str, Path]],
) -> dict[str, tuple[FileIdentity, ...]]:
    if isinstance(trees, Mapping):
        items = trees.items()
    else:
        items = trees
    return {owner: collect_file_identities(path, owner=owner) for owner, path in items}
