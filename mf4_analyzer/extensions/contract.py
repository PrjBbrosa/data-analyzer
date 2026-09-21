"""Neutral optional-extension schemas, versions, and compatibility rules.

This module is stdlib plus ``app_meta``.  It must stay import-safe for both
the frozen app and the standalone installer: no Qt, MainWindow, av, SciPy,
h5py, or matplotlib.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from mf4_analyzer.app_meta import APP_NAME, APP_VERSION

from mf4_analyzer.extensions.runtime_recipe import (
    compute_runtime_id,
    runtimes_match,
)


DISCOVERY_SCHEMA_V1 = 1
CURRENT_PROTOCOL_MAJOR = 1
CURRENT_PROTOCOL_MINOR = 0
PACKAGE_SCHEMA_V1 = 1
CORE_FILES_SCHEMA_V1 = 1
ACTIVE_SCHEMA_V1 = 1
TRANSACTION_SCHEMA_V1 = 1
RECEIPT_SCHEMA_V1 = 1
MANAGER_STATUS_SCHEMA_V1 = 1

PRODUCT_ID = APP_NAME
OFFICIAL_COMPONENTS = frozenset({"media", "matlab"})
INSTALLER_EXE_NAME = "installer.exe"

KNOWN_REQUIRED_FEATURES = frozenset(
    {
        "store_layout_v1",
        "native_probe_v1",
        "file_manifest_sha256",
    }
)
KNOWN_PROBE_TYPES = frozenset({"media_wav_mp4_v1", "matlab_mat_v73_v1"})
FORBIDDEN_PACKAGE_COMMAND_KEYS = frozenset(
    {
        "install_command",
        "uninstall_command",
        "scripts",
        "post_install",
        "pre_install",
        "entry_points",
    }
)
FORBIDDEN_MODULE_ROOTS = frozenset(
    {
        "mf4_analyzer",
        "numpy",
        "pandas",
        "PyQt5",
        "pyqtgraph",
        "sip",
    }
)
TRANSACTION_STAGES = (
    "prepared",
    "verified",
    "probed",
    "committed",
    "cleanup",
)

MAX_DISCOVERY_JSON_BYTES = 64 * 1024
MAX_CORE_FILES_JSON_BYTES = 8 * 1024 * 1024
MAX_PACKAGE_JSON_BYTES = 2 * 1024 * 1024
MAX_ACTIVE_JSON_BYTES = 256 * 1024
MAX_TRANSACTION_JSON_BYTES = 256 * 1024
MAX_RECEIPT_JSON_BYTES = 256 * 1024
MAX_MANAGER_STATUS_JSON_BYTES = 64 * 1024
MAX_RELPATH_CHARS = 512

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))"
    r"?(?:\+[0-9A-Za-z.-]+)?$"
)
_DEVICE_NAME_RE = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(\..*)?$",
    re.IGNORECASE,
)
_WINDOWS_ILLEGAL_CHARS = frozenset('<>"|?*')
_FORBIDDEN_ACTIVE_ROOTS = frozenset({".staging", "cache"})


class ReasonCode:
    COMPONENT_MISSING = "COMPONENT_MISSING"
    COMPONENT_INCOMPATIBLE = "COMPONENT_INCOMPATIBLE"
    COMPONENT_CORRUPT = "COMPONENT_CORRUPT"
    MANAGER_TOO_OLD = "MANAGER_TOO_OLD"
    PROTOCOL_UNSUPPORTED = "PROTOCOL_UNSUPPORTED"
    NO_COMPATIBLE_PACKAGE = "NO_COMPATIBLE_PACKAGE"
    CORE_INCONSISTENT = "CORE_INCONSISTENT"
    APP_RUNNING = "APP_RUNNING"
    UNSUPPORTED_FILESYSTEM = "UNSUPPORTED_FILESYSTEM"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    PROBE_FAILED = "PROBE_FAILED"
    TRANSACTION_RECOVERY_REQUIRED = "TRANSACTION_RECOVERY_REQUIRED"


REASON_CODES = frozenset(
    (
        ReasonCode.COMPONENT_MISSING,
        ReasonCode.COMPONENT_INCOMPATIBLE,
        ReasonCode.COMPONENT_CORRUPT,
        ReasonCode.MANAGER_TOO_OLD,
        ReasonCode.PROTOCOL_UNSUPPORTED,
        ReasonCode.NO_COMPATIBLE_PACKAGE,
        ReasonCode.CORE_INCONSISTENT,
        ReasonCode.APP_RUNNING,
        ReasonCode.UNSUPPORTED_FILESYSTEM,
        ReasonCode.VERIFICATION_FAILED,
        ReasonCode.PROBE_FAILED,
        ReasonCode.TRANSACTION_RECOVERY_REQUIRED,
    )
)


class ManagerExitCode:
    SUCCESS = 0
    BAD_ARGS = 2
    CANCELLED = 3
    TARGET_OR_COMPAT = 10
    MANAGER_OR_PROTOCOL_TOO_OLD = 11
    NETWORK_OR_METADATA = 12
    BUSY_FS_OR_PERM = 13
    VERIFY_OR_PROBE = 14
    RECOVERY_REQUIRED = 15


MANAGER_EXIT_CODES = frozenset(
    (
        ManagerExitCode.SUCCESS,
        ManagerExitCode.BAD_ARGS,
        ManagerExitCode.CANCELLED,
        ManagerExitCode.TARGET_OR_COMPAT,
        ManagerExitCode.MANAGER_OR_PROTOCOL_TOO_OLD,
        ManagerExitCode.NETWORK_OR_METADATA,
        ManagerExitCode.BUSY_FS_OR_PERM,
        ManagerExitCode.VERIFY_OR_PROBE,
        ManagerExitCode.RECOVERY_REQUIRED,
    )
)

_EXIT_CODE_BY_REASON = {
    ReasonCode.COMPONENT_MISSING: ManagerExitCode.TARGET_OR_COMPAT,
    ReasonCode.COMPONENT_INCOMPATIBLE: ManagerExitCode.TARGET_OR_COMPAT,
    ReasonCode.NO_COMPATIBLE_PACKAGE: ManagerExitCode.TARGET_OR_COMPAT,
    ReasonCode.CORE_INCONSISTENT: ManagerExitCode.TARGET_OR_COMPAT,
    ReasonCode.MANAGER_TOO_OLD: ManagerExitCode.MANAGER_OR_PROTOCOL_TOO_OLD,
    ReasonCode.PROTOCOL_UNSUPPORTED: ManagerExitCode.MANAGER_OR_PROTOCOL_TOO_OLD,
    ReasonCode.APP_RUNNING: ManagerExitCode.BUSY_FS_OR_PERM,
    ReasonCode.UNSUPPORTED_FILESYSTEM: ManagerExitCode.BUSY_FS_OR_PERM,
    ReasonCode.COMPONENT_CORRUPT: ManagerExitCode.VERIFY_OR_PROBE,
    ReasonCode.VERIFICATION_FAILED: ManagerExitCode.VERIFY_OR_PROBE,
    ReasonCode.PROBE_FAILED: ManagerExitCode.VERIFY_OR_PROBE,
    ReasonCode.TRANSACTION_RECOVERY_REQUIRED: ManagerExitCode.RECOVERY_REQUIRED,
}


class ExtensionError(Exception):
    """Contract or compatibility failure with a stable ``reason_code``.

    UI and logs must match ``reason_code``, never localized ``str(self)``.
    """

    def __init__(self, reason_code: str, message: str = "") -> None:
        if reason_code not in REASON_CODES:
            raise ValueError(f"unknown reason_code: {reason_code}")
        self.reason_code = reason_code
        super().__init__(message or reason_code)


def exit_code_for_reason(reason_code: str) -> int:
    try:
        return _EXIT_CODE_BY_REASON[reason_code]
    except KeyError as exc:
        raise ValueError(f"unknown reason_code: {reason_code}") from exc


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dumps_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


@dataclass(frozen=True, order=False)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: str) -> SemVer:
        text = str(value).strip()
        match = _SEMVER_RE.fullmatch(text)
        if match is None:
            raise ExtensionError(
                ReasonCode.PROTOCOL_UNSUPPORTED,
                f"not a strict SemVer: {value!r}",
            )
        prerelease = tuple(match.group(4).split(".")) if match.group(4) else ()
        return cls(int(match.group(1)), int(match.group(2)), int(match.group(3)), prerelease)

    def __str__(self) -> str:
        core = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            return f"{core}-{'.'.join(self.prerelease)}"
        return core

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return (
            self.major,
            self.minor,
            self.patch,
            self.prerelease,
        ) == (other.major, other.minor, other.patch, other.prerelease)

    def __lt__(self, other: SemVer) -> bool:
        if (self.major, self.minor, self.patch) != (other.major, other.minor, other.patch):
            return (self.major, self.minor, self.patch) < (
                other.major,
                other.minor,
                other.patch,
            )
        if self.prerelease and not other.prerelease:
            return True
        if not self.prerelease and other.prerelease:
            return False
        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            left_digit, right_digit = left.isdigit(), right.isdigit()
            if left_digit and right_digit:
                return int(left) < int(right)
            if left_digit != right_digit:
                return left_digit
            return left < right
        return len(self.prerelease) < len(other.prerelease)

    def __le__(self, other: SemVer) -> bool:
        return self == other or self < other

    def __gt__(self, other: SemVer) -> bool:
        return other < self

    def __ge__(self, other: SemVer) -> bool:
        return self == other or other < self


def compare_semver(left: str, right: str) -> int:
    """Strict SemVer compare; not string lexicographic / dictionary order."""
    parsed_left, parsed_right = SemVer.parse(left), SemVer.parse(right)
    if parsed_left < parsed_right:
        return -1
    if parsed_left > parsed_right:
        return 1
    return 0


def manager_satisfies(manager_version: str, minimum: str) -> bool:
    return SemVer.parse(manager_version) >= SemVer.parse(minimum)


def _as_object(
    payload: str | bytes | Mapping[str, Any],
    *,
    limit: int,
    what: str,
) -> dict[str, Any]:
    if isinstance(payload, Mapping):
        return dict(payload)
    raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    if len(raw) > limit:
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            f"{what} exceeds {limit} bytes",
        )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            f"{what} is not valid JSON",
        ) from exc
    if not isinstance(value, dict):
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            f"{what} must be a JSON object",
        )
    return value


def _require(mapping: Mapping[str, Any], key: str, *, what: str) -> Any:
    if key not in mapping:
        raise ExtensionError(
            ReasonCode.PROTOCOL_UNSUPPORTED,
            f"{what} missing required field {key}",
        )
    return mapping[key]


def _require_str(mapping: Mapping[str, Any], key: str, *, what: str) -> str:
    value = _require(mapping, key, what=what)
    if not isinstance(value, str) or not value.strip():
        raise ExtensionError(
            ReasonCode.PROTOCOL_UNSUPPORTED,
            f"{what} field {key} must be a non-empty string",
        )
    return value.strip()


def _require_int(mapping: Mapping[str, Any], key: str, *, what: str, minimum: int | None = None) -> int:
    value = _require(mapping, key, what=what)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExtensionError(
            ReasonCode.PROTOCOL_UNSUPPORTED,
            f"{what} field {key} must be an integer",
        )
    if minimum is not None and value < minimum:
        raise ExtensionError(
            ReasonCode.PROTOCOL_UNSUPPORTED,
            f"{what} field {key} must be >= {minimum}",
        )
    return value


def _require_sha256(value: str, *, what: str) -> str:
    digest = value.strip().lower()
    if _SHA256_RE.fullmatch(digest) is None:
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            f"{what} is not a SHA-256 hex digest",
        )
    return digest


def normalize_relpath(value: str) -> str:
    return str(value).replace("\\", "/").strip()


def inspect_windows_relpath(name: str) -> str | None:
    """Return a shared path-policy issue code, or ``None`` if the ref is allowed.

    Codes match the unpack detail vocabulary so JSON manifests, active pointers,
    and ZIP members share one Windows relative-path policy.
    """

    if not isinstance(name, str) or not name:
        return "empty_path"
    if "\x00" in name:
        return "nul_byte"
    if any(ord(char) < 32 for char in name):
        return "control_char"

    raw = name.replace("\\", "/")
    if raw.startswith("/") or name.startswith("\\"):
        return "absolute_path"
    if raw.startswith("//") or name.startswith("\\\\"):
        return "unc_path"
    if re.match(r"^[A-Za-z]:", raw) or re.match(r"^[A-Za-z]:", name):
        return "drive_letter"

    parts = raw.split("/")
    if raw.endswith("/") and parts and parts[-1] == "":
        parts = parts[:-1]
    if not parts:
        return "empty_path"
    if len("/".join(parts)) > MAX_RELPATH_CHARS:
        return "too_long"

    for part in parts:
        if part == "":
            return "empty_segment"
        if part == ".":
            return "dot_segment"
        if part == "..":
            return "parent_escape"
        if len(part) >= 2 and part[0].isalpha() and part[1] == ":":
            return "drive_letter"
        if ":" in part:
            return "ads"
        if _DEVICE_NAME_RE.fullmatch(part.rstrip(" .")):
            return "device_name"
        if any(char in _WINDOWS_ILLEGAL_CHARS for char in part):
            return "illegal_char"
        if part.rstrip(" .") != part:
            return "trailing_junk"
    return None


def canonical_windows_relpath(name: str) -> str:
    issue = inspect_windows_relpath(name)
    if issue is not None:
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            f"unsafe relative path ({issue}): {name!r}",
        )
    return "/".join(part for part in name.replace("\\", "/").split("/") if part)


def validate_relative_ref(value: str, *, what: str = "path") -> str:
    """Reject absolute paths, parent escapes, ADS, device names, and empty refs."""
    text = normalize_relpath(value)
    if not text or len(text) > MAX_RELPATH_CHARS:
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            f"{what} is missing or longer than {MAX_RELPATH_CHARS} characters",
        )
    issue = inspect_windows_relpath(value)
    if issue is not None:
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            f"{what} is not a safe relative path ({issue})",
        )
    return canonical_windows_relpath(value)


def store_package_relpath(runtime_id: str, component: str, package_sha256: str) -> str:
    """Canonical active pointer: ``store/<runtime>/<component>/<sha256>``."""

    runtime = str(runtime_id).strip()
    comp = str(component).strip()
    digest = _require_sha256(package_sha256, what="package_sha256")
    for label, value in (("runtime_id", runtime), ("component", comp)):
        if not value or "/" in value or "\\" in value:
            raise ExtensionError(
                ReasonCode.VERIFICATION_FAILED,
                f"store path {label} is missing or not a single segment",
            )
        issue = inspect_windows_relpath(value)
        if issue is not None:
            raise ExtensionError(
                ReasonCode.VERIFICATION_FAILED,
                f"store path {label} is not a safe relative path ({issue})",
            )
    return f"store/{runtime}/{comp}/{digest}"


def validate_active_store_relpath(
    relpath: str,
    *,
    runtime_id: str,
    component: str,
    package_sha256: str,
) -> str:
    """Active pointers must land exactly on the immutable store entry."""

    text = validate_relative_ref(relpath, what="active.json package_relpath")
    folded = [part.casefold() for part in text.split("/")]
    if any(part in _FORBIDDEN_ACTIVE_ROOTS for part in folded):
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            "active.json must not point at staging or download cache",
        )
    expected = store_package_relpath(runtime_id, component, package_sha256)
    if text != expected:
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            "active.json must point at store/<runtime>/<component>/<hash>",
        )
    return text


@dataclass(frozen=True)
class ComponentCapability:
    component: str
    component_api: str
    available: bool = True


@dataclass(frozen=True)
class DiscoveryEnvelope:
    """Outer ``discovery_schema=1`` envelope.  Permanently stable field set."""

    discovery_schema: int
    product_id: str
    exe_relpath: str
    app_version: str
    core_build_id: str
    runtime_id: str
    component_capabilities: Mapping[str, ComponentCapability]
    protocol_major: int
    protocol_minor: int
    min_manager_version: str
    manager_download_page: str
    exe_sha256: str | None = None
    core_files_digest: str | None = None
    extras: Mapping[str, Any] = field(default_factory=dict)

    @property
    def protocol_understood(self) -> bool:
        return self.protocol_major == CURRENT_PROTOCOL_MAJOR

    def component_api(self, component: str) -> str | None:
        capability = self.component_capabilities.get(component)
        if capability is None or not capability.available:
            return None
        return capability.component_api


_DISCOVERY_KNOWN_KEYS = frozenset(
    {
        "discovery_schema",
        "product_id",
        "exe_relpath",
        "app_version",
        "core_build_id",
        "runtime_id",
        "component_capabilities",
        "protocol_major",
        "protocol_minor",
        "min_manager_version",
        "manager_download_page",
        "exe_sha256",
        "core_files_digest",
    }
)


def parse_discovery_envelope(
    payload: str | bytes | Mapping[str, Any],
) -> DiscoveryEnvelope:
    data = _as_object(payload, limit=MAX_DISCOVERY_JSON_BYTES, what="core.json")
    schema = _require_int(data, "discovery_schema", what="core.json", minimum=1)
    if schema != DISCOVERY_SCHEMA_V1:
        raise ExtensionError(
            ReasonCode.PROTOCOL_UNSUPPORTED,
            f"unsupported discovery_schema {schema}",
        )
    capabilities_raw = _require(data, "component_capabilities", what="core.json")
    if not isinstance(capabilities_raw, dict):
        raise ExtensionError(
            ReasonCode.PROTOCOL_UNSUPPORTED,
            "component_capabilities must be an object",
        )
    capabilities: dict[str, ComponentCapability] = {}
    for name, spec in capabilities_raw.items():
        if not isinstance(name, str) or not name.strip():
            raise ExtensionError(
                ReasonCode.PROTOCOL_UNSUPPORTED,
                "component capability names must be non-empty strings",
            )
        if not isinstance(spec, dict):
            raise ExtensionError(
                ReasonCode.PROTOCOL_UNSUPPORTED,
                f"component {name} capability must be an object",
            )
        api = spec.get("component_api")
        if not isinstance(api, str) or not api.strip():
            raise ExtensionError(
                ReasonCode.PROTOCOL_UNSUPPORTED,
                f"component {name} is missing component_api",
            )
        available = spec.get("available", True)
        if not isinstance(available, bool):
            raise ExtensionError(
                ReasonCode.PROTOCOL_UNSUPPORTED,
                f"component {name} available must be a boolean",
            )
        capabilities[name.strip()] = ComponentCapability(
            component=name.strip(),
            component_api=api.strip(),
            available=available,
        )
    exe_relpath = validate_relative_ref(
        _require_str(data, "exe_relpath", what="core.json"),
        what="exe_relpath",
    )
    if "/" in exe_relpath:
        raise ExtensionError(
            ReasonCode.CORE_INCONSISTENT,
            "exe_relpath must be a file in the install root",
        )
    exe_sha256 = data.get("exe_sha256")
    core_files_digest = data.get("core_files_digest")
    return DiscoveryEnvelope(
        discovery_schema=schema,
        product_id=_require_str(data, "product_id", what="core.json"),
        exe_relpath=exe_relpath,
        app_version=_require_str(data, "app_version", what="core.json"),
        core_build_id=_require_str(data, "core_build_id", what="core.json"),
        runtime_id=_require_str(data, "runtime_id", what="core.json"),
        component_capabilities=capabilities,
        protocol_major=_require_int(data, "protocol_major", what="core.json", minimum=0),
        protocol_minor=_require_int(data, "protocol_minor", what="core.json", minimum=0),
        min_manager_version=str(SemVer.parse(_require_str(data, "min_manager_version", what="core.json"))),
        manager_download_page=_require_str(data, "manager_download_page", what="core.json"),
        exe_sha256=_require_sha256(exe_sha256, what="exe_sha256") if isinstance(exe_sha256, str) else None,
        core_files_digest=(
            _require_sha256(core_files_digest, what="core_files_digest")
            if isinstance(core_files_digest, str)
            else None
        ),
        extras={key: value for key, value in data.items() if key not in _DISCOVERY_KNOWN_KEYS},
    )


def generate_discovery_envelope(
    *,
    exe_relpath: str,
    core_build_id: str,
    runtime_id: str,
    component_capabilities: Mapping[str, str | Mapping[str, Any]],
    min_manager_version: str,
    manager_download_page: str,
    app_version: str | None = None,
    product_id: str | None = None,
    protocol_major: int = CURRENT_PROTOCOL_MAJOR,
    protocol_minor: int = CURRENT_PROTOCOL_MINOR,
    exe_sha256: str | None = None,
    core_files_digest: str | None = None,
) -> dict[str, Any]:
    capabilities: dict[str, dict[str, Any]] = {}
    for name, spec in component_capabilities.items():
        if isinstance(spec, str):
            capabilities[name] = {"component_api": spec, "available": True}
        else:
            api = spec["component_api"]
            capabilities[name] = {
                "component_api": str(api),
                "available": bool(spec.get("available", True)),
            }
    payload: dict[str, Any] = {
        "discovery_schema": DISCOVERY_SCHEMA_V1,
        "product_id": product_id or PRODUCT_ID,
        "exe_relpath": validate_relative_ref(exe_relpath, what="exe_relpath"),
        "app_version": app_version if app_version is not None else APP_VERSION,
        "core_build_id": core_build_id,
        "runtime_id": runtime_id,
        "component_capabilities": capabilities,
        "protocol_major": int(protocol_major),
        "protocol_minor": int(protocol_minor),
        "min_manager_version": str(SemVer.parse(min_manager_version)),
        "manager_download_page": manager_download_page,
    }
    if exe_sha256 is not None:
        payload["exe_sha256"] = _require_sha256(exe_sha256, what="exe_sha256")
    if core_files_digest is not None:
        payload["core_files_digest"] = _require_sha256(core_files_digest, what="core_files_digest")
    return payload


@dataclass(frozen=True)
class FileEntry:
    relpath: str
    size: int
    sha256: str


def parse_file_entry(raw: Mapping[str, Any], *, what: str) -> FileEntry:
    if not isinstance(raw, Mapping):
        raise ExtensionError(ReasonCode.PROTOCOL_UNSUPPORTED, f"{what} file entry must be an object")
    size = raw.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ExtensionError(ReasonCode.PROTOCOL_UNSUPPORTED, f"{what} file size must be a non-negative int")
    return FileEntry(
        relpath=validate_relative_ref(str(raw.get("relpath", "")), what=f"{what} relpath"),
        size=size,
        sha256=_require_sha256(str(raw.get("sha256", "")), what=f"{what} sha256"),
    )


def files_digest(entries: Sequence[FileEntry]) -> str:
    payload = [
        {"relpath": entry.relpath, "size": entry.size, "sha256": entry.sha256}
        for entry in sorted(entries, key=lambda item: item.relpath)
    ]
    return sha256_hex(canonical_json_bytes(payload))


@dataclass(frozen=True)
class CoreFilesManifest:
    schema: int
    files: tuple[FileEntry, ...]

    @property
    def digest(self) -> str:
        return files_digest(self.files)

    def by_relpath(self) -> dict[str, FileEntry]:
        return {entry.relpath: entry for entry in self.files}


def parse_core_files(payload: str | bytes | Mapping[str, Any]) -> CoreFilesManifest:
    data = _as_object(payload, limit=MAX_CORE_FILES_JSON_BYTES, what="core-files.json")
    schema = _require_int(data, "schema", what="core-files.json", minimum=1)
    if schema != CORE_FILES_SCHEMA_V1:
        raise ExtensionError(
            ReasonCode.PROTOCOL_UNSUPPORTED,
            f"unsupported core-files schema {schema}",
        )
    raw_files = _require(data, "files", what="core-files.json")
    if not isinstance(raw_files, list) or not raw_files:
        raise ExtensionError(ReasonCode.CORE_INCONSISTENT, "core-files.json files must be a non-empty array")
    files = tuple(parse_file_entry(item, what="core-files.json") for item in raw_files)
    seen: set[str] = set()
    for entry in files:
        if entry.relpath in seen:
            raise ExtensionError(
                ReasonCode.CORE_INCONSISTENT,
                f"duplicate core-files path {entry.relpath}",
            )
        seen.add(entry.relpath)
    return CoreFilesManifest(schema=schema, files=files)


def generate_core_files(files: Sequence[Mapping[str, Any] | FileEntry]) -> dict[str, Any]:
    entries = []
    for item in files:
        if isinstance(item, FileEntry):
            entries.append({"relpath": item.relpath, "size": item.size, "sha256": item.sha256})
        else:
            entry = parse_file_entry(item, what="core-files.json")
            entries.append({"relpath": entry.relpath, "size": entry.size, "sha256": entry.sha256})
    return {"schema": CORE_FILES_SCHEMA_V1, "files": entries}


@dataclass(frozen=True)
class PackageManifest:
    schema: int
    component: str
    package_revision: int
    runtime_id: str
    component_api: str
    min_manager_version: str
    python_tag: str
    platform_tag: str
    module_roots: tuple[str, ...]
    dll_directories: tuple[str, ...]
    dependency_ownership: Mapping[str, str]
    files: tuple[FileEntry, ...]
    max_extract_bytes: int
    probe_type: str
    required_features: tuple[str, ...] = ()
    extras: Mapping[str, Any] = field(default_factory=dict)

    @property
    def files_digest(self) -> str:
        return files_digest(self.files)

    @property
    def content_identity(self) -> str:
        """Immutable identity is the content hash, not package_revision."""
        return self.files_digest


_PACKAGE_KNOWN_KEYS = frozenset(
    {
        "schema",
        "component",
        "package_revision",
        "runtime_id",
        "component_api",
        "min_manager_version",
        "python_tag",
        "platform_tag",
        "module_roots",
        "dll_directories",
        "dependency_ownership",
        "files",
        "max_extract_bytes",
        "probe_type",
        "required_features",
    }
)


def parse_package_manifest(payload: str | bytes | Mapping[str, Any]) -> PackageManifest:
    data = _as_object(payload, limit=MAX_PACKAGE_JSON_BYTES, what="package.json")
    forbidden = FORBIDDEN_PACKAGE_COMMAND_KEYS.intersection(data)
    if forbidden:
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            f"package.json must not contain install commands: {sorted(forbidden)}",
        )
    schema = _require_int(data, "schema", what="package.json", minimum=1)
    if schema != PACKAGE_SCHEMA_V1:
        raise ExtensionError(
            ReasonCode.PROTOCOL_UNSUPPORTED,
            f"unsupported package schema {schema}",
        )
    required_features_raw = data.get("required_features", [])
    if not isinstance(required_features_raw, list) or not all(
        isinstance(item, str) for item in required_features_raw
    ):
        raise ExtensionError(
            ReasonCode.PROTOCOL_UNSUPPORTED,
            "required_features must be an array of strings",
        )
    required_features = tuple(item.strip() for item in required_features_raw if item.strip())
    unknown_features = [item for item in required_features if item not in KNOWN_REQUIRED_FEATURES]
    if unknown_features:
        raise ExtensionError(
            ReasonCode.PROTOCOL_UNSUPPORTED,
            f"unknown required feature: {unknown_features[0]}",
        )
    component = _require_str(data, "component", what="package.json")
    if component not in OFFICIAL_COMPONENTS:
        raise ExtensionError(
            ReasonCode.COMPONENT_INCOMPATIBLE,
            f"unknown official component {component}",
        )
    module_roots_raw = _require(data, "module_roots", what="package.json")
    dll_raw = _require(data, "dll_directories", what="package.json")
    ownership_raw = _require(data, "dependency_ownership", what="package.json")
    files_raw = _require(data, "files", what="package.json")
    if not isinstance(module_roots_raw, list) or not module_roots_raw:
        raise ExtensionError(ReasonCode.PROTOCOL_UNSUPPORTED, "module_roots must be a non-empty array")
    if not isinstance(dll_raw, list):
        raise ExtensionError(ReasonCode.PROTOCOL_UNSUPPORTED, "dll_directories must be an array")
    if not isinstance(ownership_raw, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in ownership_raw.items()
    ):
        raise ExtensionError(ReasonCode.PROTOCOL_UNSUPPORTED, "dependency_ownership must be a string map")
    if not isinstance(files_raw, list) or not files_raw:
        raise ExtensionError(ReasonCode.PROTOCOL_UNSUPPORTED, "package files must be a non-empty array")
    module_roots = tuple(
        validate_relative_ref(str(item), what="module_roots") for item in module_roots_raw
    )
    if any(root.split("/", 1)[0] in FORBIDDEN_MODULE_ROOTS for root in module_roots):
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            "package module_roots must not overlay the core runtime",
        )
    dll_directories = tuple(
        validate_relative_ref(str(item), what="dll_directories") for item in dll_raw
    )
    files = tuple(parse_file_entry(item, what="package.json") for item in files_raw)
    max_extract_bytes = _require_int(data, "max_extract_bytes", what="package.json", minimum=0)
    total_size = sum(entry.size for entry in files)
    if total_size > max_extract_bytes:
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            "package file sizes exceed max_extract_bytes",
        )
    probe_type = _require_str(data, "probe_type", what="package.json")
    if probe_type not in KNOWN_PROBE_TYPES:
        raise ExtensionError(
            ReasonCode.PROTOCOL_UNSUPPORTED,
            f"unknown probe_type {probe_type}",
        )
    return PackageManifest(
        schema=schema,
        component=component,
        package_revision=_require_int(data, "package_revision", what="package.json", minimum=1),
        runtime_id=_require_str(data, "runtime_id", what="package.json"),
        component_api=_require_str(data, "component_api", what="package.json"),
        min_manager_version=str(SemVer.parse(_require_str(data, "min_manager_version", what="package.json"))),
        python_tag=_require_str(data, "python_tag", what="package.json"),
        platform_tag=_require_str(data, "platform_tag", what="package.json"),
        module_roots=module_roots,
        dll_directories=dll_directories,
        dependency_ownership={key: value for key, value in ownership_raw.items()},
        files=files,
        max_extract_bytes=max_extract_bytes,
        probe_type=probe_type,
        required_features=required_features,
        extras={key: value for key, value in data.items() if key not in _PACKAGE_KNOWN_KEYS},
    )


def generate_package_manifest(
    *,
    component: str,
    package_revision: int,
    runtime_id: str,
    component_api: str,
    min_manager_version: str,
    python_tag: str,
    platform_tag: str,
    module_roots: Sequence[str],
    dll_directories: Sequence[str],
    dependency_ownership: Mapping[str, str],
    files: Sequence[Mapping[str, Any] | FileEntry],
    max_extract_bytes: int,
    probe_type: str,
    required_features: Sequence[str] = (),
    extra_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": PACKAGE_SCHEMA_V1,
        "component": component,
        "package_revision": int(package_revision),
        "runtime_id": runtime_id,
        "component_api": component_api,
        "min_manager_version": min_manager_version,
        "python_tag": python_tag,
        "platform_tag": platform_tag,
        "module_roots": list(module_roots),
        "dll_directories": list(dll_directories),
        "dependency_ownership": dict(dependency_ownership),
        "files": [
            {"relpath": item.relpath, "size": item.size, "sha256": item.sha256}
            if isinstance(item, FileEntry)
            else dict(item)
            for item in files
        ],
        "max_extract_bytes": int(max_extract_bytes),
        "probe_type": probe_type,
        "required_features": list(required_features),
    }
    if extra_fields:
        payload.update(extra_fields)
    parse_package_manifest(payload)
    return payload


def package_trusted_target_id(package: PackageManifest) -> str:
    """Independent trusted target binding for package.json / ZIP content."""
    payload = {
        "component": package.component,
        "files_digest": package.files_digest,
        "package_revision": package.package_revision,
        "runtime_id": package.runtime_id,
    }
    return sha256_hex(canonical_json_bytes(payload))


@dataclass(frozen=True)
class ArtifactIdentity:
    """One TUF target identity bound into a verification snapshot."""

    target: str
    sha256: str
    length: int

    def __post_init__(self) -> None:
        target = str(self.target).strip()
        if not target or inspect_windows_relpath(target) not in {None, "absolute_path"}:
            # Targets are repository paths such as packages/media-3.zip; still
            # reject parent-escape / ADS / device names while allowing no drive.
            issue = inspect_windows_relpath(target)
            if not target:
                raise ExtensionError(ReasonCode.VERIFICATION_FAILED, "artifact target is missing")
            if issue in {"parent_escape", "ads", "device_name", "dot_segment", "empty_segment", "nul_byte"}:
                raise ExtensionError(
                    ReasonCode.VERIFICATION_FAILED,
                    f"artifact target is not a safe relative path ({issue})",
                )
        digest = _require_sha256(self.sha256, what="artifact sha256")
        if isinstance(self.length, bool) or not isinstance(self.length, int) or self.length < 0:
            raise ExtensionError(
                ReasonCode.PROTOCOL_UNSUPPORTED,
                "artifact length must be a non-negative int",
            )
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "sha256", digest)


@dataclass(frozen=True)
class VerifiedPackage:
    """ZIP + independent package.json, bound to one verification snapshot.

    Receipts record this result later.  They are not a local trust root.
    """

    snapshot_id: str
    component: str
    runtime_id: str
    package_revision: int
    component_api: str
    min_manager_version: str
    zip: ArtifactIdentity
    manifest: ArtifactIdentity
    package: PackageManifest
    package_json_bytes: bytes

    @property
    def files(self) -> tuple[FileEntry, ...]:
        return self.package.files

    def unpack_manifest(self) -> tuple[FileEntry, ...]:
        """FileEntry list for unpack, including the trusted package.json bytes."""
        entries = list(self.package.files)
        if not any(entry.relpath == "package.json" for entry in entries):
            entries.append(
                FileEntry(
                    relpath="package.json",
                    size=len(self.package_json_bytes),
                    sha256=self.manifest.sha256,
                )
            )
        return tuple(entries)


def bind_verified_package(
    *,
    snapshot_id: str,
    component: str,
    runtime_id: str,
    package_revision: int,
    component_api: str,
    min_manager_version: str,
    zip_target: str,
    zip_sha256: str,
    zip_length: int,
    manifest_target: str,
    manifest_sha256: str,
    manifest_length: int,
    package_json_bytes: bytes,
) -> VerifiedPackage:
    """Parse package.json once and bind it to ZIP / manifest target identities."""

    if not str(snapshot_id).strip():
        raise ExtensionError(ReasonCode.VERIFICATION_FAILED, "verification snapshot id is missing")
    raw = bytes(package_json_bytes)
    zip_identity = ArtifactIdentity(target=zip_target, sha256=zip_sha256, length=zip_length)
    manifest_identity = ArtifactIdentity(
        target=manifest_target,
        sha256=manifest_sha256,
        length=manifest_length,
    )
    if len(raw) != manifest_identity.length:
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            "package.json length does not match the trusted manifest target",
        )
    if sha256_hex(raw) != manifest_identity.sha256:
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            "package.json hash does not match the trusted manifest target",
        )
    package = parse_package_manifest(raw)
    if (
        package.component != component
        or package.runtime_id != runtime_id
        or package.package_revision != package_revision
        or package.component_api != component_api
    ):
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            "package.json identity does not match the catalog / snapshot binding",
        )
    if str(SemVer.parse(package.min_manager_version)) != str(SemVer.parse(min_manager_version)):
        raise ExtensionError(
            ReasonCode.VERIFICATION_FAILED,
            "package.json min_manager_version does not match the catalog binding",
        )
    return VerifiedPackage(
        snapshot_id=str(snapshot_id).strip(),
        component=package.component,
        runtime_id=package.runtime_id,
        package_revision=package.package_revision,
        component_api=package.component_api,
        min_manager_version=package.min_manager_version,
        zip=zip_identity,
        manifest=manifest_identity,
        package=package,
        package_json_bytes=raw,
    )


@dataclass(frozen=True)
class ActiveSelection:
    component: str
    package_relpath: str
    package_sha256: str


@dataclass(frozen=True)
class ActiveState:
    schema: int
    generation: int
    by_runtime: Mapping[str, Mapping[str, ActiveSelection]]

    def iter_selections(self) -> Iterable[ActiveSelection]:
        for mapping in self.by_runtime.values():
            yield from mapping.values()


def parse_active_state(payload: str | bytes | Mapping[str, Any]) -> ActiveState:
    data = _as_object(payload, limit=MAX_ACTIVE_JSON_BYTES, what="active.json")
    schema = _require_int(data, "schema", what="active.json", minimum=1)
    if schema != ACTIVE_SCHEMA_V1:
        raise ExtensionError(
            ReasonCode.PROTOCOL_UNSUPPORTED,
            f"unsupported active.json schema {schema}",
        )
    by_runtime_raw = _require(data, "by_runtime", what="active.json")
    if not isinstance(by_runtime_raw, dict):
        raise ExtensionError(ReasonCode.PROTOCOL_UNSUPPORTED, "by_runtime must be an object")
    by_runtime: dict[str, dict[str, ActiveSelection]] = {}
    for runtime_id, mapping in by_runtime_raw.items():
        if not isinstance(runtime_id, str) or not runtime_id.strip():
            raise ExtensionError(ReasonCode.PROTOCOL_UNSUPPORTED, "runtime_id keys must be strings")
        if not isinstance(mapping, dict):
            raise ExtensionError(ReasonCode.PROTOCOL_UNSUPPORTED, "active runtime mapping must be an object")
        parsed: dict[str, ActiveSelection] = {}
        for component, spec in mapping.items():
            if not isinstance(spec, dict):
                raise ExtensionError(ReasonCode.PROTOCOL_UNSUPPORTED, "active selection must be an object")
            digest = _require_sha256(
                str(spec.get("package_sha256", "")),
                what="active.json package_sha256",
            )
            relpath = validate_active_store_relpath(
                str(spec.get("package_relpath", "")),
                runtime_id=runtime_id.strip(),
                component=str(component),
                package_sha256=digest,
            )
            parsed[str(component)] = ActiveSelection(
                component=str(component),
                package_relpath=relpath,
                package_sha256=digest,
            )
        by_runtime[runtime_id.strip()] = parsed
    return ActiveState(
        schema=schema,
        generation=_require_int(data, "generation", what="active.json", minimum=0),
        by_runtime=by_runtime,
    )


def generate_active_state(
    *,
    generation: int,
    by_runtime: Mapping[str, Mapping[str, Mapping[str, str]]],
) -> dict[str, Any]:
    payload = {
        "schema": ACTIVE_SCHEMA_V1,
        "generation": int(generation),
        "by_runtime": {
            runtime_id: {
                component: {
                    "package_relpath": spec["package_relpath"],
                    "package_sha256": spec["package_sha256"],
                }
                for component, spec in mapping.items()
            }
            for runtime_id, mapping in by_runtime.items()
        },
    }
    parse_active_state(payload)
    return payload


@dataclass(frozen=True)
class TransactionLog:
    schema: int
    transaction_id: str
    stage: str
    core_build_id: str
    runtime_id: str
    old_active_generation: int
    old_active_sha256: str | None
    new_active_generation: int | None
    package_hashes: tuple[str, ...]
    cleanup_pending: tuple[str, ...] = ()


def parse_transaction_log(payload: str | bytes | Mapping[str, Any]) -> TransactionLog:
    data = _as_object(payload, limit=MAX_TRANSACTION_JSON_BYTES, what="transaction.json")
    schema = _require_int(data, "schema", what="transaction.json", minimum=1)
    if schema != TRANSACTION_SCHEMA_V1:
        raise ExtensionError(
            ReasonCode.PROTOCOL_UNSUPPORTED,
            f"unsupported transaction schema {schema}",
        )
    stage = _require_str(data, "stage", what="transaction.json")
    if stage not in TRANSACTION_STAGES:
        raise ExtensionError(ReasonCode.PROTOCOL_UNSUPPORTED, f"unknown transaction stage {stage}")
    hashes_raw = data.get("package_hashes", [])
    pending_raw = data.get("cleanup_pending", [])
    if not isinstance(hashes_raw, list) or not isinstance(pending_raw, list):
        raise ExtensionError(ReasonCode.PROTOCOL_UNSUPPORTED, "transaction hash lists must be arrays")
    old_hash = data.get("old_active_sha256")
    new_generation = data.get("new_active_generation")
    return TransactionLog(
        schema=schema,
        transaction_id=_require_str(data, "transaction_id", what="transaction.json"),
        stage=stage,
        core_build_id=_require_str(data, "core_build_id", what="transaction.json"),
        runtime_id=_require_str(data, "runtime_id", what="transaction.json"),
        old_active_generation=_require_int(data, "old_active_generation", what="transaction.json", minimum=0),
        old_active_sha256=_require_sha256(old_hash, what="old_active_sha256") if isinstance(old_hash, str) else None,
        new_active_generation=new_generation if isinstance(new_generation, int) and not isinstance(new_generation, bool) else None,
        package_hashes=tuple(_require_sha256(str(item), what="package_hashes") for item in hashes_raw),
        cleanup_pending=tuple(str(item) for item in pending_raw),
    )


@dataclass(frozen=True)
class TrustedTarget:
    component: str
    runtime_id: str
    package_revision: int
    files_digest: str


@dataclass(frozen=True)
class Receipt:
    schema: int
    core_build_id: str
    runtime_id: str
    component: str
    package_revision: int
    package_sha256: str
    package_json_sha256: str
    files_digest: str
    trusted_target: TrustedTarget
    probe_ok: bool
    probe_type: str
    extras: Mapping[str, Any] = field(default_factory=dict)

    @property
    def trusted_target_id(self) -> str:
        return sha256_hex(
            canonical_json_bytes(
                {
                    "component": self.trusted_target.component,
                    "files_digest": self.trusted_target.files_digest,
                    "package_revision": self.trusted_target.package_revision,
                    "runtime_id": self.trusted_target.runtime_id,
                }
            )
        )


def parse_receipt(payload: str | bytes | Mapping[str, Any]) -> Receipt:
    data = _as_object(payload, limit=MAX_RECEIPT_JSON_BYTES, what="receipt.json")
    schema = _require_int(data, "schema", what="receipt.json", minimum=1)
    if schema != RECEIPT_SCHEMA_V1:
        raise ExtensionError(ReasonCode.PROTOCOL_UNSUPPORTED, f"unsupported receipt schema {schema}")
    target_raw = _require(data, "trusted_target", what="receipt.json")
    if not isinstance(target_raw, dict):
        raise ExtensionError(ReasonCode.PROTOCOL_UNSUPPORTED, "trusted_target must be an object")
    probe_raw = data.get("probe", {})
    if probe_raw is None:
        probe_raw = {}
    if not isinstance(probe_raw, dict):
        raise ExtensionError(ReasonCode.PROTOCOL_UNSUPPORTED, "probe must be an object")
    known = {
        "schema",
        "core_build_id",
        "runtime_id",
        "component",
        "package_revision",
        "package_sha256",
        "package_json_sha256",
        "files_digest",
        "trusted_target",
        "probe",
    }
    return Receipt(
        schema=schema,
        core_build_id=_require_str(data, "core_build_id", what="receipt.json"),
        runtime_id=_require_str(data, "runtime_id", what="receipt.json"),
        component=_require_str(data, "component", what="receipt.json"),
        package_revision=_require_int(data, "package_revision", what="receipt.json", minimum=1),
        package_sha256=_require_sha256(_require_str(data, "package_sha256", what="receipt.json"), what="package_sha256"),
        package_json_sha256=_require_sha256(
            _require_str(data, "package_json_sha256", what="receipt.json"),
            what="package_json_sha256",
        ),
        files_digest=_require_sha256(_require_str(data, "files_digest", what="receipt.json"), what="files_digest"),
        trusted_target=TrustedTarget(
            component=_require_str(target_raw, "component", what="trusted_target"),
            runtime_id=_require_str(target_raw, "runtime_id", what="trusted_target"),
            package_revision=_require_int(target_raw, "package_revision", what="trusted_target", minimum=1),
            files_digest=_require_sha256(
                _require_str(target_raw, "files_digest", what="trusted_target"),
                what="trusted_target files_digest",
            ),
        ),
        probe_ok=bool(probe_raw.get("ok", False)),
        probe_type=str(probe_raw.get("probe_type", "")),
        extras={key: value for key, value in data.items() if key not in known},
    )


def generate_receipt(
    *,
    core_build_id: str,
    package: PackageManifest,
    package_sha256: str,
    package_json_sha256: str,
    probe_ok: bool,
) -> dict[str, Any]:
    target = {
        "component": package.component,
        "runtime_id": package.runtime_id,
        "package_revision": package.package_revision,
        "files_digest": package.files_digest,
    }
    return {
        "schema": RECEIPT_SCHEMA_V1,
        "core_build_id": core_build_id,
        "runtime_id": package.runtime_id,
        "component": package.component,
        "package_revision": package.package_revision,
        "package_sha256": _require_sha256(package_sha256, what="package_sha256"),
        "package_json_sha256": _require_sha256(package_json_sha256, what="package_json_sha256"),
        "files_digest": package.files_digest,
        "trusted_target": target,
        "probe": {"ok": bool(probe_ok), "probe_type": package.probe_type},
    }


@dataclass(frozen=True)
class ManagerStatusV1:
    schema: int
    latest_manager_version: str
    minimum_supported_manager_version: str
    reason_code: str | None
    installer_filename: str
    installer_sha256: str
    help_page: str
    extras: Mapping[str, Any] = field(default_factory=dict)


def parse_manager_status_v1(payload: str | bytes | Mapping[str, Any]) -> ManagerStatusV1:
    data = _as_object(payload, limit=MAX_MANAGER_STATUS_JSON_BYTES, what="manager-status-v1.json")
    schema = _require_int(data, "schema", what="manager-status-v1.json", minimum=1)
    if schema != MANAGER_STATUS_SCHEMA_V1:
        raise ExtensionError(
            ReasonCode.PROTOCOL_UNSUPPORTED,
            f"unsupported manager-status schema {schema}",
        )
    latest = str(SemVer.parse(_require_str(data, "latest_manager_version", what="manager-status-v1.json")))
    minimum = str(
        SemVer.parse(
            _require_str(data, "minimum_supported_manager_version", what="manager-status-v1.json")
        )
    )
    reason_raw = data.get("reason_code")
    reason_code = None
    if isinstance(reason_raw, str) and reason_raw.strip():
        if reason_raw not in REASON_CODES:
            raise ExtensionError(
                ReasonCode.PROTOCOL_UNSUPPORTED,
                f"unknown manager-status reason_code {reason_raw}",
            )
        reason_code = reason_raw
    artifact = _require(data, "installer_artifact", what="manager-status-v1.json")
    if not isinstance(artifact, dict):
        raise ExtensionError(ReasonCode.PROTOCOL_UNSUPPORTED, "installer_artifact must be an object")
    known = {
        "schema",
        "latest_manager_version",
        "minimum_supported_manager_version",
        "reason_code",
        "installer_artifact",
        "help_page",
    }
    return ManagerStatusV1(
        schema=schema,
        latest_manager_version=latest,
        minimum_supported_manager_version=minimum,
        reason_code=reason_code,
        installer_filename=_require_str(artifact, "filename", what="installer_artifact"),
        installer_sha256=_require_sha256(
            _require_str(artifact, "sha256", what="installer_artifact"),
            what="installer sha256",
        ),
        help_page=_require_str(data, "help_page", what="manager-status-v1.json"),
        extras={key: value for key, value in data.items() if key not in known},
    )


@dataclass(frozen=True)
class CompatibilityDecision:
    allowed: bool
    reason_code: str | None = None
    update_target: str | None = None

    def __post_init__(self) -> None:
        if self.allowed:
            if self.reason_code is not None:
                raise ValueError("successful compatibility decision cannot carry reason_code")
            return
        if self.reason_code is None or self.reason_code not in REASON_CODES:
            raise ValueError("rejected compatibility decision requires a known reason_code")


def _reject(reason_code: str, update_target: str | None = None) -> CompatibilityDecision:
    return CompatibilityDecision(False, reason_code, update_target)


def _allow() -> CompatibilityDecision:
    return CompatibilityDecision(True)


def evaluate_install_compatibility(
    *,
    core: DiscoveryEnvelope,
    package: PackageManifest | None,
    manager_version: str,
    core_consistent: bool = True,
    files_verified: bool = True,
    source_verified: bool = True,
    revoked: bool = False,
    probe_ok: bool = True,
) -> CompatibilityDecision:
    """Install / activate gates.  Manager version is enforced here only."""
    if not core_consistent or core.product_id != PRODUCT_ID:
        return _reject(ReasonCode.CORE_INCONSISTENT)
    if not core.protocol_understood:
        if not manager_satisfies(manager_version, core.min_manager_version):
            return _reject(ReasonCode.MANAGER_TOO_OLD, "manager")
        return _reject(ReasonCode.PROTOCOL_UNSUPPORTED, "manager")
    if not manager_satisfies(manager_version, core.min_manager_version):
        return _reject(ReasonCode.MANAGER_TOO_OLD, "manager")
    if package is None:
        return _reject(ReasonCode.NO_COMPATIBLE_PACKAGE, "package")
    if not manager_satisfies(manager_version, package.min_manager_version):
        return _reject(ReasonCode.MANAGER_TOO_OLD, "manager")
    if package.schema != PACKAGE_SCHEMA_V1:
        return _reject(ReasonCode.PROTOCOL_UNSUPPORTED, "manager")
    if not runtimes_match(package.runtime_id, core.runtime_id):
        return _reject(ReasonCode.COMPONENT_INCOMPATIBLE, "package")
    expected_api = core.component_api(package.component)
    if expected_api is None or expected_api != package.component_api:
        return _reject(ReasonCode.COMPONENT_INCOMPATIBLE, "package")
    if revoked:
        return _reject(ReasonCode.COMPONENT_INCOMPATIBLE, "package")
    if not files_verified or not source_verified:
        return _reject(ReasonCode.VERIFICATION_FAILED)
    if not probe_ok:
        return _reject(ReasonCode.PROBE_FAILED)
    return _allow()


def evaluate_load_compatibility(
    *,
    core: DiscoveryEnvelope,
    package: PackageManifest | None,
    files_verified: bool,
    revoked: bool = False,
    installer_available: bool = False,
    manager_version: str | None = None,
) -> CompatibilityDecision:
    """Load an already-installed component.  Installer presence is irrelevant."""
    del installer_available, manager_version
    if package is None:
        return _reject(ReasonCode.COMPONENT_MISSING, "package")
    if core.product_id != PRODUCT_ID:
        return _reject(ReasonCode.CORE_INCONSISTENT)
    if not runtimes_match(package.runtime_id, core.runtime_id):
        return _reject(ReasonCode.COMPONENT_INCOMPATIBLE, "package")
    expected_api = core.component_api(package.component)
    if expected_api is None or expected_api != package.component_api:
        return _reject(ReasonCode.COMPONENT_INCOMPATIBLE, "package")
    if revoked:
        return _reject(ReasonCode.COMPONENT_INCOMPATIBLE, "package")
    if not files_verified:
        return _reject(ReasonCode.COMPONENT_CORRUPT)
    return _allow()


def can_reuse_installed_package(
    *,
    previous_core: DiscoveryEnvelope,
    new_core: DiscoveryEnvelope,
    package: PackageManifest,
) -> bool:
    """Same runtime + component API: a UI-only app upgrade reuses the package."""
    if previous_core.runtime_id != new_core.runtime_id:
        return False
    return evaluate_load_compatibility(
        core=new_core,
        package=package,
        files_verified=True,
    ).allowed


# Re-export so other agents can mint IDs without importing the recipe module.
__all__ = (
    "ACTIVE_SCHEMA_V1",
    "APP_VERSION",
    "CompatibilityDecision",
    "ComponentCapability",
    "CoreFilesManifest",
    "CURRENT_PROTOCOL_MAJOR",
    "CURRENT_PROTOCOL_MINOR",
    "DISCOVERY_SCHEMA_V1",
    "DiscoveryEnvelope",
    "ExtensionError",
    "FileEntry",
    "KNOWN_REQUIRED_FEATURES",
    "MANAGER_EXIT_CODES",
    "MANAGER_STATUS_SCHEMA_V1",
    "ManagerExitCode",
    "ManagerStatusV1",
    "OFFICIAL_COMPONENTS",
    "PACKAGE_SCHEMA_V1",
    "PRODUCT_ID",
    "PackageManifest",
    "REASON_CODES",
    "Receipt",
    "ReasonCode",
    "SemVer",
    "TRANSACTION_STAGES",
    "TransactionLog",
    "ArtifactIdentity",
    "TrustedTarget",
    "VerifiedPackage",
    "bind_verified_package",
    "can_reuse_installed_package",
    "canonical_json_bytes",
    "canonical_windows_relpath",
    "compare_semver",
    "compute_runtime_id",
    "dumps_json",
    "evaluate_install_compatibility",
    "evaluate_load_compatibility",
    "exit_code_for_reason",
    "files_digest",
    "generate_active_state",
    "generate_core_files",
    "generate_discovery_envelope",
    "generate_package_manifest",
    "generate_receipt",
    "inspect_windows_relpath",
    "manager_satisfies",
    "package_trusted_target_id",
    "parse_active_state",
    "parse_core_files",
    "parse_discovery_envelope",
    "parse_manager_status_v1",
    "parse_package_manifest",
    "parse_receipt",
    "parse_transaction_log",
    "sha256_hex",
    "store_package_relpath",
    "validate_active_store_relpath",
    "validate_relative_ref",
)
