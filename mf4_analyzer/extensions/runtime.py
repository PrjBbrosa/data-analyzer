"""Neutral extension runtime identity, availability, and start-up lease.

Does not import Qt, UI, av, SciPy, h5py, or TUF. Source adapters consume the
bootstrap snapshot. A staging directory name is never treated as verified.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import secrets
import sys
from typing import Any, Mapping, Sequence

from mf4_analyzer.extensions.contract import (
    ActiveState,
    ExtensionError,
    FileEntry,
    OFFICIAL_COMPONENTS,
    PackageManifest,
    ReasonCode,
    dumps_json,
    evaluate_load_compatibility,
    generate_active_state,
    parse_package_manifest,
    parse_receipt,
    parse_transaction_log,
    sha256_hex,
    store_package_relpath,
)
from mf4_analyzer.extensions.locking import (
    Lease,
    LockBackend,
    acquire_shared_lease,
    extensions_root as _extensions_root,
    same_volume,
)
from mf4_analyzer.extensions.native_identity import sha256_file
from mf4_analyzer.extensions.revocations import load_revocation_records, revocation_store_path
from mf4_analyzer.extensions.state import (
    CoreIdentity,
    bind_core_payloads,
    load_active_state,
    resolve_inside,
    verify_receipt,
)


STATUS_NOT_INSTALLED = "not_installed"
STATUS_READY = "ready"
STATUS_INCOMPATIBLE = "incompatible"
STATUS_CORRUPT = "corrupt"
STATUS_REPAIR_REQUIRED = "repair_required"
STATUS_REVOKED = "revoked"
COMPONENT_STATUSES = frozenset(
    {
        STATUS_NOT_INSTALLED,
        STATUS_READY,
        STATUS_INCOMPATIBLE,
        STATUS_CORRUPT,
        STATUS_REPAIR_REQUIRED,
        STATUS_REVOKED,
    }
)
MODE_SOURCE = "source"
MODE_BUNDLED = "bundled"
MODE_MODULAR = "modular"
WINDOWS_FROZEN_MEDIA_READ = "UNKNOWN"


def extensions_root(app_root: str | Path) -> Path:
    return _extensions_root(app_root)


def active_path(app_root: str | Path) -> Path:
    return extensions_root(app_root) / "active.json"


def transaction_log_path(app_root: str | Path) -> Path:
    return extensions_root(app_root) / "transaction.json"


def rollback_path(app_root: str | Path) -> Path:
    return extensions_root(app_root) / "rollback.json"


def store_root(app_root: str | Path) -> Path:
    return extensions_root(app_root) / "store"


def staging_root(app_root: str | Path) -> Path:
    return extensions_root(app_root) / ".staging"


def install_id_path(app_root: str | Path) -> Path:
    return extensions_root(app_root) / "install-id"


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    data = dumps_json(dict(payload)).encode("utf-8")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_bytes().decode("utf-8"))


def empty_active(*, generation: int = 0) -> dict[str, Any]:
    return generate_active_state(generation=generation, by_runtime={})


def detect_runtime_mode(
    *,
    frozen: bool | None = None,
    app_root: Path | None = None,
    use_extensions: bool | None = None,
) -> str:
    """source / bundled / modular.  Dev defaults to source and ignores extensions."""

    is_frozen = bool(getattr(sys, "frozen", False) if frozen is None else frozen)
    if use_extensions is False:
        return MODE_BUNDLED if is_frozen else MODE_SOURCE
    if not is_frozen and not use_extensions:
        return MODE_SOURCE
    if app_root is not None and ((app_root / "core.json").is_file() or install_id_path(app_root).is_file()):
        return MODE_MODULAR
    return MODE_BUNDLED if is_frozen else MODE_SOURCE


def identify_core(app_root: str | Path) -> CoreIdentity:
    root = Path(app_root).expanduser().resolve()
    core_json = root / "core.json"
    core_files = root / "core-files.json"
    if not core_json.is_file() or not core_files.is_file():
        raise ExtensionError(ReasonCode.CORE_INCONSISTENT, "core.json / core-files.json missing")
    identity = bind_core_payloads(core_json.read_bytes(), core_files.read_bytes())
    exe = root / identity.exe_relpath
    if not exe.is_file():
        raise ExtensionError(
            ReasonCode.CORE_INCONSISTENT,
            f"identified exe {identity.exe_relpath!r} is missing",
        )
    return identity


def verify_core_files(app_root: Path, core: CoreIdentity) -> None:
    for entry in core.files.files:
        path = resolve_inside(app_root, entry.relpath)
        if not path.is_file() or path.stat().st_size != entry.size or sha256_file(path) != entry.sha256:
            raise ExtensionError(ReasonCode.CORE_INCONSISTENT, f"core file changed: {entry.relpath}")


def ensure_install_id(app_root: str | Path) -> str:
    path = install_id_path(app_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    token = secrets.token_hex(16)
    path.write_text(token + "\n", encoding="utf-8")
    return token


def load_optional_active(app_root: str | Path) -> ActiveState | None:
    path = active_path(app_root)
    if not path.is_file():
        return None
    return load_active_state(path, extensions_root=extensions_root(app_root))


def verify_package_tree(package_root: Path, files: Sequence[FileEntry], *, extensions: Path) -> None:
    root = Path(package_root)
    for entry in files:
        path = resolve_inside(root, entry.relpath)
        if not path.is_file():
            raise ExtensionError(
                ReasonCode.COMPONENT_CORRUPT,
                f"missing package file {entry.relpath}",
            )
        if path.stat().st_size != entry.size or sha256_file(path) != entry.sha256:
            raise ExtensionError(
                ReasonCode.COMPONENT_CORRUPT,
                f"package file {entry.relpath} failed size/SHA-256 verification",
            )


@dataclass(frozen=True)
class ComponentAvailability:
    component: str
    status: str
    reason_code: str | None = None
    package_sha256: str | None = None
    package_relpath: str | None = None

    def __post_init__(self) -> None:
        if self.status not in COMPONENT_STATUSES:
            raise ValueError(f"unknown component status {self.status}")


@dataclass
class PlannedSearchPath:
    module_roots: tuple[Path, ...] = ()
    dll_directories: tuple[Path, ...] = ()


@dataclass
class RuntimeSnapshot:
    mode: str
    app_root: Path
    core: CoreIdentity | None
    active: ActiveState | None
    lease: Lease | None
    components: Mapping[str, ComponentAvailability]
    repair_required: bool = False
    affected_components: tuple[str, ...] = ()
    planned: PlannedSearchPath = field(default_factory=PlannedSearchPath)
    windows_frozen_media_read: str = WINDOWS_FROZEN_MEDIA_READ

    def availability(self, component: str) -> ComponentAvailability:
        return self.components[component]


def _transaction_repair_flag(app_root: Path) -> tuple[bool, tuple[str, ...]]:
    path = transaction_log_path(app_root)
    if not path.is_file():
        return False, ()
    raw = read_json(path)
    log = parse_transaction_log(raw)
    if raw.get("repair_required"):
        affected = tuple(str(item) for item in raw.get("affected_components") or [])
        return True, affected
    if log.stage in {"prepared", "verified", "probed"}:
        # Incomplete log is not proof of a new selection.  Recovery owns the
        # decision; runtime only reports that repair may be required.
        affected = tuple(str(item) for item in raw.get("affected_components") or log.package_hashes and [])
        names = tuple(str(item) for item in raw.get("affected_components") or ())
        return True, names
    return False, ()


def _package_at_store(app_root: Path, relpath: str) -> tuple[Path, PackageManifest] | None:
    try:
        package_root = resolve_inside(extensions_root(app_root), relpath)
    except ExtensionError:
        return None
    manifest_path = package_root / "package.json"
    if not manifest_path.is_file():
        return None
    try:
        package = parse_package_manifest(manifest_path.read_bytes())
    except ExtensionError:
        return None
    return package_root, package


def availability_for(
    *,
    core: CoreIdentity,
    active: ActiveState | None,
    component: str,
    app_root: Path,
    repair_required: bool,
    affected: Sequence[str],
    revoked_hashes: Sequence[str] = (),
) -> ComponentAvailability:
    if repair_required and (not affected or component in affected):
        return ComponentAvailability(
            component=component,
            status=STATUS_REPAIR_REQUIRED,
            reason_code=ReasonCode.TRANSACTION_RECOVERY_REQUIRED,
        )
    selection = None
    if active is not None:
        selection = active.by_runtime.get(core.runtime_id, {}).get(component)
    if selection is None:
        return ComponentAvailability(
            component=component,
            status=STATUS_NOT_INSTALLED,
            reason_code=ReasonCode.COMPONENT_MISSING,
        )
    if selection.package_sha256 in set(revoked_hashes):
        return ComponentAvailability(
            component=component,
            status=STATUS_REVOKED,
            reason_code=ReasonCode.COMPONENT_INCOMPATIBLE,
            package_sha256=selection.package_sha256,
            package_relpath=selection.package_relpath,
        )
    loaded = _package_at_store(app_root, selection.package_relpath)
    if loaded is None:
        return ComponentAvailability(
            component=component,
            status=STATUS_CORRUPT,
            reason_code=ReasonCode.COMPONENT_CORRUPT,
            package_sha256=selection.package_sha256,
            package_relpath=selection.package_relpath,
        )
    package_root, package = loaded
    expected = store_package_relpath(core.runtime_id, component, selection.package_sha256)
    if selection.package_relpath != expected:
        return ComponentAvailability(
            component=component,
            status=STATUS_CORRUPT,
            reason_code=ReasonCode.COMPONENT_CORRUPT,
            package_sha256=selection.package_sha256,
            package_relpath=selection.package_relpath,
        )
    try:
        receipt = parse_receipt((package_root / "receipt.json").read_bytes())
        verify_receipt(receipt, package_json_bytes=(package_root / "package.json").read_bytes(),
                       package=package, package_sha256=selection.package_sha256)
        if package.component != component or not receipt.probe_ok:
            raise ExtensionError(ReasonCode.COMPONENT_CORRUPT, "package receipt is not a successful matching install")
        verify_package_tree(package_root, package.files, extensions=extensions_root(app_root))
        files_verified = True
    except (ExtensionError, OSError, ValueError):
        files_verified = False
    decision = evaluate_load_compatibility(
        core=core.envelope,
        package=package,
        files_verified=files_verified,
    )
    if not files_verified:
        status = STATUS_CORRUPT
    elif not decision.allowed:
        status = STATUS_INCOMPATIBLE
    else:
        status = STATUS_READY
    return ComponentAvailability(
        component=component,
        status=status,
        reason_code=None if status == STATUS_READY else decision.reason_code,
        package_sha256=selection.package_sha256,
        package_relpath=selection.package_relpath,
    )


def planned_search_path(app_root: Path, snapshot_components: Mapping[str, ComponentAvailability]) -> PlannedSearchPath:
    module_roots: list[Path] = []
    dll_dirs: list[Path] = []
    for availability in snapshot_components.values():
        if availability.status != STATUS_READY or not availability.package_relpath:
            continue
        loaded = _package_at_store(app_root, availability.package_relpath)
        if loaded is None:
            continue
        package_root, package = loaded
        for rel in package.module_roots:
            module_roots.append(resolve_inside(package_root, rel).parent)
        for rel in package.dll_directories:
            dll_dirs.append(package_root / rel)
    return PlannedSearchPath(module_roots=tuple(module_roots), dll_directories=tuple(dll_dirs))


def load_runtime(
    app_root: str | Path,
    *,
    acquire_lease: bool = True,
    lock_backend: LockBackend | None = None,
    frozen: bool | None = None,
    use_extensions: bool | None = None,
    revoked_hashes: Sequence[str] = (),
) -> RuntimeSnapshot:
    root = Path(app_root).expanduser().resolve()
    mode = detect_runtime_mode(frozen=frozen, app_root=root, use_extensions=use_extensions)
    lease = None
    core = None
    active = None
    repair_required = False
    affected: tuple[str, ...] = ()
    components: dict[str, ComponentAvailability] = {}
    if mode in {MODE_SOURCE, MODE_BUNDLED} and not use_extensions:
        for name in sorted(OFFICIAL_COMPONENTS):
            components[name] = ComponentAvailability(
                component=name,
                status=STATUS_NOT_INSTALLED,
                reason_code=ReasonCode.COMPONENT_MISSING,
            )
        return RuntimeSnapshot(
            mode=mode,
            app_root=root,
            core=None,
            active=None,
            lease=None,
            components=components,
        )
    if acquire_lease:
        lease = acquire_shared_lease(root, backend=lock_backend)
    try:
        core = identify_core(root)
        verify_core_files(root, core)
    except BaseException:
        if lease is not None:
            lease.release()
        raise
    try:
        if mode == MODE_MODULAR or use_extensions:
            records = load_revocation_records(revocation_store_path(root))
            revoked_hashes = tuple({str(item["sha256"]).lower() for item in records}
                                   | {digest.lower() for digest in revoked_hashes})
            repair_required, affected = _transaction_repair_flag(root)
            try:
                active = load_optional_active(root)
            except ExtensionError:
                repair_required = True
                active = None
            for name in sorted(OFFICIAL_COMPONENTS):
                components[name] = availability_for(
                    core=core,
                    active=active,
                    component=name,
                    app_root=root,
                    repair_required=repair_required,
                    affected=affected,
                    revoked_hashes=revoked_hashes,
                )
        else:
            for name in sorted(OFFICIAL_COMPONENTS):
                components[name] = ComponentAvailability(
                    component=name,
                    status=STATUS_NOT_INSTALLED,
                    reason_code=ReasonCode.COMPONENT_MISSING,
                )
        planned = planned_search_path(root, components) if mode == MODE_MODULAR or use_extensions else PlannedSearchPath()
        return RuntimeSnapshot(
            mode=mode,
            app_root=root,
            core=core,
            active=active,
            lease=lease,
            components=components,
            repair_required=repair_required,
            affected_components=affected,
            planned=planned,
        )
    except BaseException:
        if lease is not None:
            lease.release()
        raise


def active_payload_from_state(state: ActiveState) -> dict[str, Any]:
    by_runtime = {
        runtime_id: {
            component: {
                "package_relpath": selection.package_relpath,
                "package_sha256": selection.package_sha256,
            }
            for component, selection in mapping.items()
        }
        for runtime_id, mapping in state.by_runtime.items()
    }
    return generate_active_state(generation=state.generation, by_runtime=by_runtime)


def selections_equal(left: Mapping[str, Any] | None, right: Mapping[str, Any] | None) -> bool:
    if left is None or right is None:
        return left is right
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, sort_keys=True, separators=(",", ":")
    )


def content_identity_bytes(payload: Mapping[str, Any]) -> str:
    return sha256_hex(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def require_same_volume_staging(staging: Path, store: Path) -> None:
    if not same_volume(staging, store):
        raise ExtensionError(
            ReasonCode.UNSUPPORTED_FILESYSTEM,
            "staging must be on the same volume as the immutable store",
        )


__all__ = (
    "COMPONENT_STATUSES",
    "ComponentAvailability",
    "MODE_BUNDLED",
    "MODE_MODULAR",
    "MODE_SOURCE",
    "PlannedSearchPath",
    "RuntimeSnapshot",
    "STATUS_CORRUPT",
    "STATUS_INCOMPATIBLE",
    "STATUS_NOT_INSTALLED",
    "STATUS_READY",
    "STATUS_REPAIR_REQUIRED",
    "STATUS_REVOKED",
    "WINDOWS_FROZEN_MEDIA_READ",
    "active_path",
    "active_payload_from_state",
    "content_identity_bytes",
    "detect_runtime_mode",
    "empty_active",
    "ensure_install_id",
    "extensions_root",
    "identify_core",
    "install_id_path",
    "load_optional_active",
    "load_runtime",
    "read_json",
    "require_same_volume_staging",
    "rollback_path",
    "selections_equal",
    "staging_root",
    "store_root",
    "transaction_log_path",
    "verify_package_tree",
    "write_json_atomic",
)
