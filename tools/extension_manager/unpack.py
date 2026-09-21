"""ZIP path-safety validator and extractor for TraceLab extension packages.

Same-volume staging, locking, probing, and ``active.json`` commit are caller
concerns. This module only enforces archive policy and writes files into a
caller-provided staging directory that has already been identified as part of
the extensions tree.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import stat
from zipfile import ZipFile, ZipInfo

from mf4_analyzer.extensions.contract import (
    FileEntry,
    ReasonCode,
    VerifiedPackage,
    canonical_windows_relpath,
    inspect_windows_relpath,
)

VERIFICATION_FAILED = ReasonCode.VERIFICATION_FAILED

_STARTUP_SCRIPT_NAMES = frozenset({"sitecustomize.py", "usercustomize.py"})
_WINDOWS_REPARSE_POINT = 0x400
_READ_CHUNK = 1024 * 1024


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
    """Unique unpack adapter for ``FileEntry``. SHA-256 is required."""

    relative_path: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        if self.size < 0:
            raise ValueError("manifest file size must be >= 0")
        if not str(self.sha256).strip():
            raise ValueError("manifest file sha256 is required")

    def to_file_entry(self) -> FileEntry:
        return FileEntry(
            relpath=self.relative_path,
            size=self.size,
            sha256=str(self.sha256).strip().lower(),
        )


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
    sha256: str


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


def _is_startup_script(basename: str) -> bool:
    return basename.casefold() in _STARTUP_SCRIPT_NAMES


def _is_pth_file(basename: str) -> bool:
    return basename.casefold().endswith(".pth")


def normalize_zip_path(name: str, *, allow_directory: bool = False) -> str:
    """Return a canonical relative POSIX path, or raise ``UnpackError``.

    Shared Windows relative-path policy lives in the neutral contract.
    This function adds ZIP-only rules: directory members, ``.pth``, and
    Python startup scripts. Parent segments are a hard failure.
    """

    if not isinstance(name, str) or not name:
        _fail("empty_path", "archive member path is empty")
    raw = name.replace("\\", "/")
    is_directory = raw.endswith("/")
    if is_directory and not allow_directory:
        _fail("directory_entry", f"unexpected directory member: {name!r}")
    inspected = raw.rstrip("/") if is_directory else name
    issue = inspect_windows_relpath(inspected)
    if issue is not None:
        messages = {
            "empty_path": "archive member path is empty",
            "nul_byte": f"archive member path contains a NUL byte: {name!r}",
            "control_char": f"archive member path contains a control character: {name!r}",
            "absolute_path": f"absolute archive member path is not allowed: {name!r}",
            "unc_path": f"UNC archive member path is not allowed: {name!r}",
            "empty_segment": f"archive member path has an empty segment: {name!r}",
            "dot_segment": f"archive member path has a '.' segment: {name!r}",
            "parent_escape": f"archive member path escapes the staging root: {name!r}",
            "drive_letter": f"archive member path includes a drive letter: {name!r}",
            "ads": f"archive member path includes an NTFS stream: {name!r}",
            "device_name": f"archive member path uses a Windows device name: {name!r}",
            "illegal_char": (
                f"archive member path contains an illegal filename character: {name!r}"
            ),
            "trailing_junk": f"archive member path has a trailing space or dot: {name!r}",
            "too_long": f"archive member path is too long: {name!r}",
        }
        _fail(issue, messages.get(issue, f"unsafe archive member path: {name!r}"))
    relative = canonical_windows_relpath(inspected)
    basename = relative.rsplit("/", 1)[-1]
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
    manifest: Sequence[FileEntry | ManifestFile],
) -> tuple[FileEntry, ...]:
    """Accept ``FileEntry`` or the unique ``ManifestFile`` adapter only."""

    files: list[FileEntry] = []
    for item in manifest:
        if isinstance(item, FileEntry):
            entry = item
        elif isinstance(item, ManifestFile):
            entry = item.to_file_entry()
        else:
            _fail(
                "manifest",
                "unpack requires FileEntry from mf4_analyzer.extensions.contract "
                "or the ManifestFile adapter; dict keys relative_path/path/name "
                "are not accepted",
            )
        if entry.size < 0:
            raise ValueError("manifest file size must be >= 0")
        digest = str(entry.sha256 or "").strip().lower()
        if not digest:
            _fail("missing_hash", f"manifest entry {entry.relpath!r} is missing SHA-256")
        files.append(FileEntry(relpath=entry.relpath, size=entry.size, sha256=digest))
    return tuple(files)


def _index_manifest(
    manifest: Sequence[FileEntry | ManifestFile],
) -> dict[str, FileEntry]:
    files = coerce_manifest(manifest)
    indexed: dict[str, FileEntry] = {}
    seen_case: dict[str, str] = {}
    for entry in files:
        relative = normalize_zip_path(entry.relpath, allow_directory=False)
        folded = _casefold_key(relative)
        if folded in seen_case:
            _fail(
                "case_collision",
                "manifest has case-normalized duplicate paths "
                f"{seen_case[folded]!r} and {relative!r}",
            )
        seen_case[folded] = relative
        indexed[relative] = FileEntry(
            relpath=relative,
            size=entry.size,
            sha256=entry.sha256,
        )
    return indexed


def validate_zip(
    archive: str | Path,
    manifest: Sequence[FileEntry | ManifestFile],
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


def _cleanup_extract(
    files: Sequence[Path],
    dirs: Sequence[Path],
    staging: Path | None = None,
) -> None:
    """Remove this attempt's files and created directories, including partial writes.

    Cleanup-only: OSError is ignored so the original unpack failure propagates.
    If ``staging`` is provided it must have been empty at the start of this
    attempt; leftover files and empty directories are removed so a retry is
    not blocked by a non-empty staging tree.
    """

    for path in reversed(list(files)):
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
        except OSError:
            continue
    for path in reversed(list(dirs)):
        try:
            path.rmdir()
        except OSError:
            continue
    if staging is None or not staging.is_dir():
        return
    for path in sorted(staging.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        except OSError:
            continue


def _mkdir_parents(dest: Path, staging: Path, created_dirs: list[Path]) -> None:
    parent = dest.parent
    relatives = parent.relative_to(staging).parts if parent != staging else ()
    current = staging
    for part in relatives:
        current = current / part
        existed = current.exists()
        current.mkdir(exist_ok=True)
        if not existed:
            created_dirs.append(current)


def _copy_limited(
    source,
    destination,
    *,
    declared_size: int,
    expected_sha256: str,
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
    digest = hasher.hexdigest()
    expected = expected_sha256.lower().strip()
    if digest != expected:
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
    manifest: Sequence[FileEntry | ManifestFile],
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
    created_dirs: list[Path] = []
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
                _mkdir_parents(dest, staging, created_dirs)
                if dest.exists() or dest.is_symlink():
                    _fail("destination", f"refusing to overwrite {str(dest)!r}")
                with zip_file.open(member.zip_name, "r") as source:
                    with open(dest, "wb") as handle:
                        written.append(dest)
                        copied = _copy_limited(
                            source,
                            handle,
                            declared_size=member.size,
                            expected_sha256=member.sha256,
                        )
                os.chmod(dest, 0o644)
                extracted.append(member.relative_path)
                total += copied
    except Exception:
        _cleanup_extract(written, created_dirs, staging=staging)
        raise

    extracted_sorted = tuple(sorted(extracted))
    return UnpackedPackage(
        staging_dir=staging,
        files=extracted_sorted,
        uncompressed_bytes=total,
    )


def extract_verified_package(
    archive: str | Path,
    staging_dir: str | Path,
    *,
    extensions_root: str | Path,
    verified: VerifiedPackage,
    app_root: str | Path | None = None,
    extra_forbidden_roots: Sequence[str | Path] = (),
) -> UnpackedPackage:
    """Unpack a snapshot-bound package and require ZIP package.json bytes to match."""

    limits = UnpackLimits(
        max_uncompressed_size=verified.package.max_extract_bytes,
        max_file_count=len(verified.unpack_manifest()),
    )
    result = extract_verified_zip(
        archive,
        staging_dir,
        extensions_root=extensions_root,
        manifest=verified.unpack_manifest(),
        limits=limits,
        app_root=app_root,
        extra_forbidden_roots=extra_forbidden_roots,
    )
    embedded = result.staging_dir / "package.json"
    try:
        if not embedded.is_file():
            _fail("missing_manifest_entry", "extracted package is missing package.json")
        if embedded.read_bytes() != verified.package_json_bytes:
            _fail(
                "hash_mismatch",
                "ZIP package.json does not match the independently verified target",
            )
    except Exception:
        files = [result.staging_dir / relative for relative in result.files]
        dirs = sorted(
            {path.parent for path in files if path.parent != result.staging_dir},
            key=lambda item: len(item.parts),
            reverse=True,
        )
        _cleanup_extract(files, dirs, staging=result.staging_dir)
        raise
    return result


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
