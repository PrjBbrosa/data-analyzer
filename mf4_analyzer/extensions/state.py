"""Bound core identity, active pointers, and receipt verification.

Filesystem checks stay in the standard library.  This module does not import
Qt, MainWindow, or optional native importers.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from mf4_analyzer.extensions.contract import (
    PRODUCT_ID,
    ActiveState,
    CoreFilesManifest,
    DiscoveryEnvelope,
    ExtensionError,
    FileEntry,
    INSTALLER_EXE_NAME,
    PackageManifest,
    Receipt,
    ReasonCode,
    files_digest,
    package_trusted_target_id,
    parse_active_state,
    parse_core_files,
    parse_discovery_envelope,
    sha256_hex,
    validate_relative_ref,
)


@dataclass(frozen=True)
class CoreIdentity:
    """Validated pairing of core.json and core-files.json."""

    envelope: DiscoveryEnvelope
    files: CoreFilesManifest
    exe: FileEntry

    @property
    def exe_relpath(self) -> str:
        return self.exe.relpath

    @property
    def runtime_id(self) -> str:
        return self.envelope.runtime_id

    @property
    def core_build_id(self) -> str:
        return self.envelope.core_build_id


def _root_executables(files: CoreFilesManifest) -> tuple[FileEntry, ...]:
    found = []
    for entry in files.files:
        name = entry.relpath.rsplit("/", 1)[-1].lower()
        if "/" in entry.relpath:
            continue
        if name.endswith(".exe"):
            found.append(entry)
    return tuple(found)


def bind_core_identity(
    envelope: DiscoveryEnvelope,
    files: CoreFilesManifest,
) -> CoreIdentity:
    """Reject mixed / partial cores whose exe name or hash disagrees."""
    if envelope.product_id != PRODUCT_ID:
        raise ExtensionError(
            ReasonCode.CORE_INCONSISTENT,
            f"product_id {envelope.product_id!r} is not {PRODUCT_ID}",
        )
    lookup = files.by_relpath()
    exe = lookup.get(envelope.exe_relpath)
    if exe is None:
        raise ExtensionError(
            ReasonCode.CORE_INCONSISTENT,
            f"core.json exe {envelope.exe_relpath!r} is missing from core-files.json",
        )
    if envelope.exe_sha256 is not None and envelope.exe_sha256 != exe.sha256:
        raise ExtensionError(
            ReasonCode.CORE_INCONSISTENT,
            "core.json exe hash does not match core-files.json",
        )
    digest = files.digest
    if envelope.core_files_digest is not None and envelope.core_files_digest != digest:
        raise ExtensionError(
            ReasonCode.CORE_INCONSISTENT,
            "core.json core_files_digest does not match core-files.json",
        )
    expected_build = f"cb1-{digest}"
    if envelope.core_build_id not in {digest, expected_build}:
        raise ExtensionError(
            ReasonCode.CORE_INCONSISTENT,
            "core_build_id does not match the core-files digest",
        )
    extras = [
        entry
        for entry in _root_executables(files)
        if entry.relpath != envelope.exe_relpath
        and entry.relpath.rsplit("/", 1)[-1].lower() != INSTALLER_EXE_NAME
    ]
    if extras:
        raise ExtensionError(
            ReasonCode.CORE_INCONSISTENT,
            "core-files.json lists more than one application exe; mixed core rejected",
        )
    return CoreIdentity(envelope=envelope, files=files, exe=exe)


def bind_core_payloads(
    core_json: str | bytes | Mapping[str, object],
    core_files_json: str | bytes | Mapping[str, object],
) -> CoreIdentity:
    return bind_core_identity(
        parse_discovery_envelope(core_json),
        parse_core_files(core_files_json),
    )


def core_build_id_for_files(files: CoreFilesManifest | tuple[FileEntry, ...]) -> str:
    digest = files.digest if isinstance(files, CoreFilesManifest) else files_digest(files)
    return f"cb1-{digest}"


def resolve_inside(root: Path, relpath: str) -> Path:
    """Resolve a versioned relative pointer and reject symlink / ``..`` escape."""
    safe = validate_relative_ref(relpath, what="relative ref")
    root_resolved = Path(root).resolve()
    candidate = root_resolved.joinpath(*safe.split("/"))
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            "path escapes the install root",
        ) from exc
    return resolved


def load_active_state(path: Path, *, extensions_root: Path) -> ActiveState:
    state = parse_active_state(Path(path).read_bytes())
    for selection in state.iter_selections():
        resolve_inside(extensions_root, selection.package_relpath)
    return state


def verify_receipt(
    receipt: Receipt,
    *,
    package_json_bytes: bytes,
    package: PackageManifest,
    package_sha256: str,
    trusted_target_id: str | None = None,
) -> None:
    """Receipt is not a trust root.  Tampered receipt or package.json must fail."""
    actual_json_hash = sha256_hex(package_json_bytes)
    if receipt.package_json_sha256 != actual_json_hash:
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            "receipt package.json hash does not match the on-disk package.json",
        )
    if trusted_target_id is not None and trusted_target_id != actual_json_hash:
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            "package.json does not match the independently verified target",
        )
    if receipt.package_sha256 != package_sha256:
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            "receipt package hash does not match the package content hash",
        )
    if receipt.files_digest != package.files_digest:
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            "receipt files digest does not match package.json",
        )
    computed_target = package_trusted_target_id(package)
    if receipt.trusted_target_id != computed_target:
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            "receipt trusted target does not match package.json binding",
        )
    if (
        receipt.component != package.component
        or receipt.runtime_id != package.runtime_id
        or receipt.package_revision != package.package_revision
    ):
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            "receipt identity does not match package.json",
        )
