"""ZIP path-safety validator and extractor for TraceLab extension packages.

Same-volume staging, locking, probing, and ``active.json`` commit are caller
concerns. This module only enforces archive policy and writes files into a
caller-provided staging directory that has already been identified as part of
the extensions tree.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
from typing import Any
from zipfile import ZipFile, ZipInfo


_FALLBACK_VERIFICATION_FAILED = "VERIFICATION_FAILED"

_DEVICE_NAME_RE = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(\..*)?$",
    re.IGNORECASE,
)
_STARTUP_SCRIPT_NAMES = frozenset({"sitecustomize.py", "usercustomize.py"})
_WINDOWS_REPARSE_POINT = 0x400
_READ_CHUNK = 1024 * 1024
_WINDOWS_ILLEGAL_CHARS = frozenset('<>"|?*')


def _verification_failed_code() -> str:
    """Prefer the shared contract constant when the extensions package exists."""

    try:
        from mf4_analyzer.extensions.contract import ReasonCode
    except ImportError:
        return _FALLBACK_VERIFICATION_FAILED
    value = getattr(ReasonCode, "VERIFICATION_FAILED", None)
    if isinstance(value, str) and value:
        return value
    return _FALLBACK_VERIFICATION_FAILED


VERIFICATION_FAILED = _verification_failed_code()


class UnpackError(Exception):
    """Structured unpack/path-policy failure for the installer UI and logs."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str | None = None,
        detail: str = "",
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code or VERIFICATION_FAILED
        self.detail = detail
        self.message = message

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class ManifestFile:
    """One trusted file entry from a verified package manifest."""

    relative_path: str
    size: int
    sha256: str | None = None

    def __post_init__(self) -> None:
        if self.size < 0:
            raise ValueError("manifest file size must be >= 0")


@dataclass(frozen=True)
class UnpackLimits:
    """Expansion ceilings taken from the verified package declaration."""

    max_uncompressed_size: int
    max_file_count: int

    def __post_init__(self) -> None:
        if self.max_uncompressed_size < 0:
            raise ValueError("max_uncompressed_size must be >= 0")
        if self.max_file_count < 0:
            raise ValueError("max_file_count must be >= 0")


@dataclass(frozen=True)
class ValidatedMember:
    zip_name: str
    relative_path: str
    size: int
    sha256: str | None


@dataclass(frozen=True)
class ValidatedArchive:
    members: tuple[ValidatedMember, ...]
    uncompressed_bytes: int


@dataclass(frozen=True)
class UnpackedPackage:
    staging_dir: Path
    files: tuple[str, ...]
    uncompressed_bytes: int


@dataclass(frozen=True)
class DiskSpaceStatus:
    required_bytes: int
    margin_bytes: int
    available_bytes: int
    ok: bool
    reason_code: str | None = None
    message: str = ""
    detail: str = ""


def _fail(detail: str, message: str) -> None:
    raise UnpackError(
        message,
        reason_code=VERIFICATION_FAILED,
        detail=detail,
    )


def _is_strict_within(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return relative != Path(".")


def _casefold_key(relative_path: str) -> str:
    return relative_path.replace("\\", "/").casefold()


def _looks_like_ads(component: str) -> bool:
    if ":" not in component:
        return False
    if len(component) >= 2 and component[0].isalpha() and component[1] == ":":
        return False
    return True


def _has_drive_letter(name: str, component: str) -> bool:
    if len(name) >= 2 and name[0].isalpha() and name[1] == ":":
        return True
    return len(component) >= 2 and component[0].isalpha() and component[1] == ":"


def _is_device_name(component: str) -> bool:
    return bool(_DEVICE_NAME_RE.fullmatch(component.rstrip(" .")))


def _is_startup_script(basename: str) -> bool:
    return basename.casefold() in _STARTUP_SCRIPT_NAMES


def _is_pth_file(basename: str) -> bool:
    return basename.casefold().endswith(".pth")


def normalize_zip_path(name: str, *, allow_directory: bool = False) -> str:
    """Return a canonical relative POSIX path, or raise ``UnpackError``.

    Rejects ZipSlip, drive letters, ADS, device names, and empty/dot segments.
    Does **not** collapse ``..``; parent segments are always a hard failure.
    """

    if not isinstance(name, str) or not name:
        _fail("empty_path", "archive member path is empty")
    if "\x00" in name:
        _fail("nul_byte", f"archive member path contains a NUL byte: {name!r}")
    if any(ord(char) < 32 for char in name):
        _fail("control_char", f"archive member path contains a control character: {name!r}")

    raw = name.replace("\\", "/")
    is_directory = raw.endswith("/")
    if is_directory and not allow_directory:
        _fail("directory_entry", f"unexpected directory member: {name!r}")

    if raw.startswith("/") or name.startswith("\\"):
        _fail("absolute_path", f"absolute archive member path is not allowed: {name!r}")
    if raw.startswith("//") or name.startswith("\\\\"):
        _fail("unc_path", f"UNC archive member path is not allowed: {name!r}")

    parts = [part for part in raw.split("/")]
    if is_directory and parts and parts[-1] == "":
        parts = parts[:-1]
    if not parts:
        _fail("empty_path", f"archive member path is empty: {name!r}")

    safe_parts: list[str] = []
    for part in parts:
        if part == "":
            _fail("empty_segment", f"archive member path has an empty segment: {name!r}")
        if part == ".":
            _fail("dot_segment", f"archive member path has a '.' segment: {name!r}")
        if part == "..":
            _fail("parent_escape", f"archive member path escapes the staging root: {name!r}")
        if _has_drive_letter(name, part):
            _fail("drive_letter", f"archive member path includes a drive letter: {name!r}")
        if _looks_like_ads(part) or ":" in part:
            _fail("ads", f"archive member path includes an NTFS stream: {name!r}")
        if _is_device_name(part):
            _fail("device_name", f"archive member path uses a Windows device name: {name!r}")
        if any(char in _WINDOWS_ILLEGAL_CHARS for char in part):
            _fail(
                "illegal_char",
                f"archive member path contains an illegal filename character: {name!r}",
            )
        trimmed = part.rstrip(" .")
        if trimmed != part:
            _fail(
                "trailing_junk",
                f"archive member path has a trailing space or dot: {name!r}",
            )
        safe_parts.append(part)

    relative = "/".join(safe_parts)
    basename = safe_parts[-1]
    if _is_pth_file(basename):
        _fail("pth", f".pth files are not allowed in extension packages: {name!r}")
    if _is_startup_script(basename):
        _fail(
            "startup_script",
            f"Python startup scripts are not allowed in extension packages: {name!r}",
        )
    if is_directory:
        return relative + "/"
    return relative


def _member_kind(info: ZipInfo) -> str:
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    windows_attrs = info.external_attr & 0xFFFF
    if unix_mode and stat.S_ISLNK(unix_mode):
        return "symlink"
    if windows_attrs & _WINDOWS_REPARSE_POINT:
        return "reparse"
    if unix_mode and (
        stat.S_ISCHR(unix_mode)
        or stat.S_ISBLK(unix_mode)
        or stat.S_ISFIFO(unix_mode)
        or stat.S_ISSOCK(unix_mode)
    ):
        return "special"
    if info.is_dir() or (unix_mode and stat.S_ISDIR(unix_mode)):
        return "directory"
    return "file"


def coerce_manifest(
    manifest: Sequence[ManifestFile | Mapping[str, Any] | str],
) -> tuple[ManifestFile, ...]:
    files: list[ManifestFile] = []
    for item in manifest:
        if isinstance(item, ManifestFile):
            files.append(item)
            continue
        if isinstance(item, str):
            files.append(ManifestFile(relative_path=item, size=0))
            continue
        if not isinstance(item, Mapping):
            raise TypeError(f"unsupported manifest entry type: {type(item)!r}")
        relative = item.get("relative_path", item.get("path", item.get("name")))
        if not isinstance(relative, str) or not relative:
            _fail("manifest", "manifest entry is missing a relative path")
        size_raw = item.get("size", item.get("uncompressed_size"))
        if size_raw is None:
            _fail("manifest", f"manifest entry {relative!r} is missing size")
        sha_raw = item.get("sha256", item.get("sha256_hex"))
        sha256 = str(sha_raw) if sha_raw else None
        files.append(
            ManifestFile(relative_path=relative, size=int(size_raw), sha256=sha256)
        )
    return tuple(files)


def _index_manifest(
    manifest: Sequence[ManifestFile | Mapping[str, Any] | str],
) -> dict[str, ManifestFile]:
    files = coerce_manifest(manifest)
    indexed: dict[str, ManifestFile] = {}
    seen_case: dict[str, str] = {}
    for entry in files:
        relative = normalize_zip_path(entry.relative_path, allow_directory=False)
        folded = _casefold_key(relative)
        if folded in seen_case:
            _fail(
                "case_collision",
                "manifest has case-normalized duplicate paths "
                f"{seen_case[folded]!r} and {relative!r}",
            )
        seen_case[folded] = relative
        indexed[relative] = ManifestFile(
            relative_path=relative,
            size=entry.size,
            sha256=entry.sha256,
        )
    return indexed


def validate_zip(
    archive: str | Path,
    manifest: Sequence[ManifestFile | Mapping[str, Any] | str],
    limits: UnpackLimits,
) -> ValidatedArchive:
    """Validate ZIP policy and manifest membership without writing files."""

    archive_path = Path(archive)
    if not archive_path.is_file():
        _fail("archive_missing", f"archive does not exist: {archive_path}")

    expected = _index_manifest(manifest)
    members: list[ValidatedMember] = []
    seen_case: dict[str, str] = {}
    directory_prefixes: list[str] = []
    total_size = 0

    with ZipFile(archive_path) as zip_file:
        for info in zip_file.infolist():
            if info.flag_bits & 0x1:
                _fail("encrypted", f"encrypted archive member is not allowed: {info.filename!r}")
            kind = _member_kind(info)
            if kind in {"symlink", "reparse"}:
                _fail(
                    "symlink",
                    "symbolic links and reparse-point members are not allowed: "
                    f"{info.filename!r}",
                )
            if kind == "special":
                _fail(
                    "special_file",
                    f"special archive members are not allowed: {info.filename!r}",
                )
            if kind == "directory":
                relative = normalize_zip_path(info.filename, allow_directory=True)
                directory_prefixes.append(relative.rstrip("/"))
                continue

            relative = normalize_zip_path(info.filename, allow_directory=False)
            folded = _casefold_key(relative)
            if folded in seen_case:
                _fail(
                    "case_collision",
                    "archive has case-normalized duplicate paths "
                    f"{seen_case[folded]!r} and {relative!r}",
                )
            seen_case[folded] = relative

            if relative not in expected:
                _fail(
                    "extra_file",
                    f"archive contains a file that is not in the manifest: {relative!r}",
                )
            declared = expected[relative]
            if info.file_size != declared.size:
                _fail(
                    "size_mismatch",
                    f"uncompressed size for {relative!r} is {info.file_size}, "
                    f"manifest declares {declared.size}",
                )
            if info.file_size < 0:
                _fail("oversize", f"archive member {relative!r} has a negative size")
            total_size += info.file_size
            if total_size > limits.max_uncompressed_size:
                _fail(
                    "oversize",
                    "archive uncompressed size exceeds the declared maximum "
                    f"({total_size} > {limits.max_uncompressed_size})",
                )
            members.append(
                ValidatedMember(
                    zip_name=info.filename,
                    relative_path=relative,
                    size=declared.size,
                    sha256=declared.sha256,
                )
            )

    if len(members) > limits.max_file_count:
        _fail(
            "oversize",
            "archive file count exceeds the declared maximum "
            f"({len(members)} > {limits.max_file_count})",
        )

    found = {member.relative_path for member in members}
    missing = [path for path in expected if path not in found]
    if missing:
        _fail(
            "missing_manifest_entry",
            "archive is missing manifest files: " + ", ".join(repr(item) for item in missing),
        )

    for prefix in directory_prefixes:
        if not any(
            member.relative_path == prefix or member.relative_path.startswith(prefix + "/")
            for member in members
        ):
            _fail(
                "extra_file",
                f"archive contains a directory that is not in the manifest: {prefix!r}",
            )

    return ValidatedArchive(members=tuple(members), uncompressed_bytes=total_size)


def _user_document_roots() -> tuple[Path, ...]:
    home = Path.home()
    return (home / "Documents",)


def resolve_staging_directory(
    staging_dir: str | Path,
    extensions_root: str | Path,
    *,
    app_root: str | Path | None = None,
    extra_forbidden_roots: Sequence[str | Path] = (),
) -> Path:
    """Resolve staging and refuse destinations outside the extensions tree.

    ``_internal``, the exe directory, and user documents are always refused
    unless they *are* the verified extensions staging tree passed in.
    """

    root = Path(extensions_root).expanduser().resolve()
    if not root.is_dir():
        _fail("destination", f"extensions root is not a directory: {root}")

    staging = Path(staging_dir).expanduser().resolve()
    if not _is_strict_within(staging, root):
        _fail(
            "destination",
            f"staging directory {str(staging)!r} is outside the identified "
            f"extensions root {str(root)!r}",
        )

    forbidden: list[Path] = []
    if app_root is not None:
        app = Path(app_root).expanduser().resolve()
        forbidden.append(app)
        forbidden.append(app / "_internal")
    forbidden.extend(_user_document_roots())
    forbidden.extend(Path(item).expanduser() for item in extra_forbidden_roots)

    for candidate in forbidden:
        try:
            candidate_resolved = candidate.resolve()
        except OSError:
            continue
        if _is_strict_within(root, candidate_resolved) or root == candidate_resolved:
            # The verified extensions tree itself lives here; allow it.
            continue
        if staging == candidate_resolved or _is_strict_within(staging, candidate_resolved):
            _fail(
                "destination",
                f"refusing to extract into {str(candidate_resolved)!r}",
            )
    return staging


def _cleanup_written(paths: Sequence[Path]) -> None:
    for path in reversed(paths):
        try:
            if path.is_file() or path.is_symlink():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        except OSError:
            continue


def _copy_limited(
    source,
    destination,
    *,
    declared_size: int,
    expected_sha256: str | None,
) -> int:
    hasher = hashlib.sha256()
    copied = 0
    while True:
        chunk = source.read(_READ_CHUNK)
        if not chunk:
            break
        copied += len(chunk)
        if copied > declared_size:
            _fail(
                "oversize",
                f"decompressed member exceeded declared size {declared_size}",
            )
        hasher.update(chunk)
        destination.write(chunk)
    if copied != declared_size:
        _fail(
            "size_mismatch",
            f"decompressed size {copied} does not match declared size {declared_size}",
        )
    if expected_sha256:
        digest = hasher.hexdigest()
        if digest.lower() != expected_sha256.lower().strip():
            _fail(
                "hash_mismatch",
                f"SHA-256 mismatch: got {digest}, expected {expected_sha256}",
            )
    return copied


def extract_verified_zip(
    archive: str | Path,
    staging_dir: str | Path,
    *,
    extensions_root: str | Path,
    manifest: Sequence[ManifestFile | Mapping[str, Any] | str],
    limits: UnpackLimits,
    app_root: str | Path | None = None,
    extra_forbidden_roots: Sequence[str | Path] = (),
) -> UnpackedPackage:
    """Validate archive policy, then extract into ``staging_dir`` only."""

    validated = validate_zip(archive, manifest, limits)
    staging = resolve_staging_directory(
        staging_dir,
        extensions_root,
        app_root=app_root,
        extra_forbidden_roots=extra_forbidden_roots,
    )
    if staging.exists() and not staging.is_dir():
        _fail("destination", f"staging path exists and is not a directory: {staging}")
    if staging.exists() and any(staging.iterdir()):
        _fail("destination", f"staging directory is not empty: {staging}")
    staging.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    extracted: list[str] = []
    total = 0
    try:
        with ZipFile(archive) as zip_file:
            for member in validated.members:
                dest = (staging / member.relative_path).resolve()
                if not _is_strict_within(dest, staging):
                    _fail(
                        "destination",
                        f"resolved member path escaped staging: {member.relative_path!r}",
                    )
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists() or dest.is_symlink():
                    _fail("destination", f"refusing to overwrite {str(dest)!r}")
                with zip_file.open(member.zip_name, "r") as source:
                    with open(dest, "wb") as handle:
                        copied = _copy_limited(
                            source,
                            handle,
                            declared_size=member.size,
                            expected_sha256=member.sha256,
                        )
                os.chmod(dest, 0o644)
                written.append(dest)
                extracted.append(member.relative_path)
                total += copied
    except Exception:
        _cleanup_written(written)
        raise

    extracted_sorted = tuple(sorted(extracted))
    return UnpackedPackage(
        staging_dir=staging,
        files=extracted_sorted,
        uncompressed_bytes=total,
    )


def default_free_space(path: str | Path) -> int:
    """Return free bytes for ``path`` without allocating or filling the disk."""

    probe = Path(path)
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            break
        probe = parent
    return int(shutil.disk_usage(probe).free)


def check_disk_space(
    path: str | Path,
    required_bytes: int,
    margin_bytes: int = 0,
    *,
    free_space: Callable[[Path], int] | None = None,
) -> DiskSpaceStatus:
    """Return a structured space-budget result. Never fills the disk."""

    if required_bytes < 0 or margin_bytes < 0:
        raise ValueError("required_bytes and margin_bytes must be >= 0")
    probe = Path(path)
    getter = free_space or default_free_space
    available = int(getter(probe))
    need = required_bytes + margin_bytes
    if available >= need:
        return DiskSpaceStatus(
            required_bytes=required_bytes,
            margin_bytes=margin_bytes,
            available_bytes=available,
            ok=True,
        )
    message = (
        f"need {need} bytes (required {required_bytes} + margin {margin_bytes}), "
        f"only {available} bytes free at {probe}"
    )
    return DiskSpaceStatus(
        required_bytes=required_bytes,
        margin_bytes=margin_bytes,
        available_bytes=available,
        ok=False,
        reason_code=VERIFICATION_FAILED,
        message=message,
        detail="disk_space",
    )


def require_disk_space(
    path: str | Path,
    required_bytes: int,
    margin_bytes: int = 0,
    *,
    free_space: Callable[[Path], int] | None = None,
) -> DiskSpaceStatus:
    """Raise ``UnpackError`` when the caller-supplied budget cannot be met."""

    status = check_disk_space(
        path,
        required_bytes,
        margin_bytes,
        free_space=free_space,
    )
    if not status.ok:
        raise UnpackError(
            status.message,
            reason_code=status.reason_code or VERIFICATION_FAILED,
            detail=status.detail or "disk_space",
        )
    return status
