"""Trusted TUF metadata, catalog selection, and download orchestration.

Network I/O in this module is thread-safe with respect to Tk/Qt: it never
imports a GUI toolkit. Callers must invoke refresh/download off the UI thread.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict

from tuf.api.exceptions import (
    BadVersionNumberError,
    DownloadError,
    DownloadLengthMismatchError,
    ExpiredMetadataError,
    LengthOrHashMismatchError,
    RepositoryError as TUFRepositoryError,
    UnsignedMetadataError,
)
from tuf.api.metadata import TargetFile
from tuf.ngclient import Updater, UpdaterConfig
from tuf.ngclient.fetcher import FetcherInterface

from .download import (
    DownloadCancelled,
    DownloadPolicy,
    DownloadPolicyError,
    assert_https_trusted_url,
    build_policy_opener,
    download_verified_file,
)

# --- Reason codes (spec S11.1 + repository-layer codes that are not not_installed)

def _load_contract() -> Any | None:
    try:
        from mf4_analyzer.extensions import contract as contract_mod
    except Exception:
        return None
    return contract_mod


def _reason(name: str) -> str:
    contract = _load_contract()
    if contract is None:
        return name
    value = getattr(contract, name, None)
    if isinstance(value, str):
        return value
    if value is not None and hasattr(value, "value") and isinstance(value.value, str):
        return value.value
    for holder_name in ("REASON_CODES", "ReasonCode", "ReasonCodes"):
        holder = getattr(contract, holder_name, None)
        if holder is None:
            continue
        if isinstance(holder, Mapping) and name in holder:
            item = holder[name]
            return str(item.value if hasattr(item, "value") else item)
        item = getattr(holder, name, None)
        if isinstance(item, str):
            return item
        if item is not None and hasattr(item, "value") and isinstance(item.value, str):
            return item.value
    return name


COMPONENT_MISSING = _reason("COMPONENT_MISSING")
COMPONENT_INCOMPATIBLE = _reason("COMPONENT_INCOMPATIBLE")
COMPONENT_CORRUPT = _reason("COMPONENT_CORRUPT")
MANAGER_TOO_OLD = _reason("MANAGER_TOO_OLD")
PROTOCOL_UNSUPPORTED = _reason("PROTOCOL_UNSUPPORTED")
NO_COMPATIBLE_PACKAGE = _reason("NO_COMPATIBLE_PACKAGE")
CORE_INCONSISTENT = _reason("CORE_INCONSISTENT")
APP_RUNNING = _reason("APP_RUNNING")
UNSUPPORTED_FILESYSTEM = _reason("UNSUPPORTED_FILESYSTEM")
VERIFICATION_FAILED = _reason("VERIFICATION_FAILED")
PROBE_FAILED = _reason("PROBE_FAILED")
TRANSACTION_RECOVERY_REQUIRED = _reason("TRANSACTION_RECOVERY_REQUIRED")
NETWORK_CHECK_FAILED = _reason("NETWORK_CHECK_FAILED")
METADATA_EXPIRED = _reason("METADATA_EXPIRED")
TARGET_REVOKED = _reason("TARGET_REVOKED")

# Install state names (spec S6.2). This module never reports not_installed
# for a network or metadata-check failure, and never uninstalls anything.
INSTALL_STATE_NOT_INSTALLED = "not_installed"
INSTALL_STATE_REVOKED = "revoked"

MANAGER_STATUS_TARGET = "manager-status-v1.json"
COMPONENT_CATALOG_V1_TARGET = "component-catalog-v1.json"
MANAGER_STATUS_SCHEMA = "manager-status-v1"
COMPONENT_CATALOG_V1_SCHEMA = "component-catalog-v1"
SUPPORTED_CATALOG_SCHEMAS = frozenset({COMPONENT_CATALOG_V1_SCHEMA})
SUPPORTED_PROTOCOL_MAJOR = 1

CACHE_METADATA = Path("extensions") / "cache" / "metadata"
CACHE_DOWNLOADS = Path("extensions") / "cache" / "downloads"
CACHE_MANAGER_UPDATES = Path("extensions") / "cache" / "manager-updates"
REVOCATION_STORE_NAME = "observed-revocations.json"

_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)


class ManagerStatusV1(TypedDict, total=False):
    schema: str
    latest_manager_version: str
    min_supported_manager_version: str
    reason_code: str
    installer_target: str
    help_page: str


class PackageRecord(TypedDict, total=False):
    component: str
    package_revision: int
    runtime_id: str
    component_api: str
    min_manager_version: str
    python_tag: str
    platform_tag: str
    target: str
    sha256: str
    length: int


class RevocationRecord(TypedDict, total=False):
    sha256: str
    component: str
    target: str
    package_revision: int


class ComponentCatalogV1(TypedDict, total=False):
    schema: str
    protocol_major: int
    protocol_minor: int
    min_manager_version: str
    packages: list[PackageRecord]
    revoked: list[RevocationRecord]


class CoreIdentity(TypedDict, total=False):
    runtime_id: str
    capabilities: dict[str, str]
    protocol_major: int
    protocol_minor: int
    min_manager_version: str
    python_tag: str
    platform_tag: str


@dataclass(frozen=True)
class PackageSelection:
    ok: bool
    reason_code: str | None
    package: PackageRecord | None = None


@dataclass
class RefreshResult:
    ok: bool
    reason_code: str | None
    manager_status: ManagerStatusV1 | None = None
    catalog: ComponentCatalogV1 | None = None
    catalog_schema: str | None = None
    # Repository checks are not component install states.
    component_install_state: None = None
    uninstalled: Literal[False] = False


@dataclass(frozen=True)
class InstalledTrust:
    may_run: bool
    reason_code: str | None = None
    required_fresh_metadata: bool = False


@dataclass
class ObservedRevocations:
    items: list[RevocationRecord] = field(default_factory=list)

    def hashes(self) -> frozenset[str]:
        return frozenset(
            str(item.get("sha256", "")).lower()
            for item in self.items
            if item.get("sha256")
        )


def _status_minimum(status: Mapping[str, Any]) -> str:
    """Prefer the contract field; keep the draft alias during fixture migration."""

    return str(
        status.get("minimum_supported_manager_version")
        or status.get("min_supported_manager_version")
        or ""
    )


class ExtensionRepositoryError(Exception):
    def __init__(self, message: str, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def compare_semver(left: str, right: str) -> int:
    """Strict SemVer compare: negative if left < right. Not string lexicographic."""

    contract = _load_contract()
    if contract is not None:
        for name in ("compare_semver", "compare_manager_version", "manager_version_cmp"):
            func = getattr(contract, name, None)
            if callable(func):
                return int(func(left, right))
    return _compare_semver(left, right)


def _parse_semver(value: str) -> tuple[int, int, int, tuple[str, ...]]:
    match = _SEMVER_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"not a strict SemVer value: {value!r}")
    pre_raw = match.group("pre")
    pre = tuple(pre_raw.split(".")) if pre_raw else ()
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        pre,
    )


def _pre_key(part: str) -> tuple[int, int | str]:
    if part.isdigit():
        return (0, int(part))
    return (1, part)


def _compare_semver(left: str, right: str) -> int:
    lmaj, lmin, lpat, lpre = _parse_semver(left)
    rmaj, rmin, rpat, rpre = _parse_semver(right)
    core = (lmaj, lmin, lpat)
    other = (rmaj, rmin, rpat)
    if core < other:
        return -1
    if core > other:
        return 1
    if not lpre and not rpre:
        return 0
    if not lpre:
        return 1
    if not rpre:
        return -1
    for left_part, right_part in zip(lpre, rpre):
        if _pre_key(left_part) < _pre_key(right_part):
            return -1
        if _pre_key(left_part) > _pre_key(right_part):
            return 1
    if len(lpre) < len(rpre):
        return -1
    if len(lpre) > len(rpre):
        return 1
    return 0


def manager_meets_minimum(manager_version: str, minimum: str) -> bool:
    if not minimum:
        return True
    return compare_semver(manager_version, minimum) >= 0


def cache_download_path(app_root: Path, sha256: str) -> Path:
    digest = sha256.lower()
    return Path(app_root) / CACHE_DOWNLOADS / f"{digest}.bin"


def manager_update_path(app_root: Path, manager_version: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", manager_version)
    return Path(app_root) / CACHE_MANAGER_UPDATES / f"installer-{safe}.exe"


def revocation_store_path(app_root: Path) -> Path:
    return Path(app_root) / CACHE_METADATA / REVOCATION_STORE_NAME


def load_observed_revocations(path: Path) -> ObservedRevocations:
    if not path.is_file():
        return ObservedRevocations()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ObservedRevocations()
    items = payload.get("items") if isinstance(payload, dict) else None
    records: list[RevocationRecord] = []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("sha256"):
                records.append(item)  # type: ignore[arg-type]
    return ObservedRevocations(items=records)


def save_observed_revocations(path: Path, store: ObservedRevocations) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "schema": "observed-revocations-v1",
        "items": list(store.items),
    }
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def merge_revocations(
    existing: ObservedRevocations,
    catalog: ComponentCatalogV1 | None,
) -> ObservedRevocations:
    by_hash: dict[str, RevocationRecord] = {
        str(item.get("sha256", "")).lower(): item for item in existing.items if item.get("sha256")
    }
    if catalog is not None:
        for item in catalog.get("revoked") or []:
            digest = str(item.get("sha256", "")).lower()
            if digest:
                by_hash[digest] = item
    return ObservedRevocations(items=list(by_hash.values()))


def is_hash_revoked(sha256: str, store: ObservedRevocations) -> bool:
    return sha256.lower() in store.hashes()


def installed_component_may_run(
    package_sha256: str,
    *,
    revocation_store: Path,
) -> InstalledTrust:
    """Already-installed verified components do not need metadata freshness.

    Offline callers cannot invent revocations that were never observed. A new
    install or update must go through ``RepositoryClient.refresh`` with
    unexpired metadata instead of this function.
    """

    store = load_observed_revocations(revocation_store)
    if is_hash_revoked(package_sha256, store):
        return InstalledTrust(may_run=False, reason_code=TARGET_REVOKED)
    return InstalledTrust(may_run=True)


def select_compatible_package(
    catalog: ComponentCatalogV1 | None,
    *,
    component: str,
    runtime_id: str,
    component_api: str,
    manager_version: str,
    platform_tag: str,
    core_capabilities: Mapping[str, str],
    known_revocations: Collection[str] | None = None,
    python_tag: str | None = None,
) -> PackageSelection:
    """Exact match on capability, runtime_id, component_api, platform, manager.

    There is no closest-version fallback. Catalog entries for capabilities the
    core did not declare are ignored.
    """

    if catalog is None:
        return PackageSelection(False, NO_COMPATIBLE_PACKAGE)
    schema = str(catalog.get("schema") or "")
    if schema not in SUPPORTED_CATALOG_SCHEMAS:
        return PackageSelection(False, PROTOCOL_UNSUPPORTED)
    protocol_major = int(catalog.get("protocol_major") or 0)
    if protocol_major and protocol_major > SUPPORTED_PROTOCOL_MAJOR:
        return PackageSelection(False, PROTOCOL_UNSUPPORTED)
    catalog_min = str(catalog.get("min_manager_version") or "")
    if catalog_min and not manager_meets_minimum(manager_version, catalog_min):
        return PackageSelection(False, MANAGER_TOO_OLD)
    declared_api = core_capabilities.get(component)
    if declared_api is None:
        return PackageSelection(False, NO_COMPATIBLE_PACKAGE)
    if declared_api != component_api:
        return PackageSelection(False, NO_COMPATIBLE_PACKAGE)

    revoked = {item.lower() for item in (known_revocations or ())}
    exact: list[PackageRecord] = []
    manager_blocked: list[PackageRecord] = []
    for raw in catalog.get("packages") or []:
        record: PackageRecord = raw
        if str(record.get("component") or "") != component:
            continue
        if str(record.get("runtime_id") or "") != runtime_id:
            continue
        if str(record.get("component_api") or "") != component_api:
            continue
        pkg_platform = str(record.get("platform_tag") or "")
        if pkg_platform and pkg_platform != platform_tag:
            continue
        pkg_python = str(record.get("python_tag") or "")
        if python_tag and pkg_python and pkg_python != python_tag:
            continue
        digest = str(record.get("sha256") or "").lower()
        if digest and digest in revoked:
            continue
        minimum = str(record.get("min_manager_version") or "")
        if minimum and not manager_meets_minimum(manager_version, minimum):
            manager_blocked.append(record)
            continue
        exact.append(record)

    if not exact and manager_blocked:
        return PackageSelection(False, MANAGER_TOO_OLD)
    if not exact:
        return PackageSelection(False, NO_COMPATIBLE_PACKAGE)
    chosen = max(exact, key=lambda item: int(item.get("package_revision") or 0))
    return PackageSelection(True, None, chosen)


class LocalPathFetcher(FetcherInterface):
    """Serve TUF metadata and targets from a local offline bundle directory."""

    def __init__(self, bundle_dir: Path) -> None:
        self.bundle_dir = Path(bundle_dir)

    def _fetch(self, url: str):  # type: ignore[override]
        from tuf.api.exceptions import DownloadHTTPError

        parsed = urllib.parse.urlparse(url)
        parts = [part for part in parsed.path.split("/") if part]
        local: Path | None = None
        if "metadata" in parts:
            rel = "/".join(parts[parts.index("metadata") + 1 :])
            local = self.bundle_dir / "metadata" / rel
        elif "targets" in parts:
            rel = "/".join(parts[parts.index("targets") + 1 :])
            local = self.bundle_dir / "targets" / rel
        elif parts:
            name = parts[-1]
            candidate = self.bundle_dir / "metadata" / name
            local = candidate if candidate.is_file() else self.bundle_dir / "targets" / name
        if local is None or not local.is_file():
            raise DownloadHTTPError(f"offline bundle missing {url}", 404)
        yield local.read_bytes()


class PolicyFetcher(FetcherInterface):
    """HTTPS + trusted-origin fetcher used for online TUF metadata."""

    def __init__(
        self,
        policy: DownloadPolicy,
        *,
        cancel_event: Any | None = None,
        urlopen: Callable[..., Any] | None = None,
    ) -> None:
        self.policy = policy
        self.cancel_event = cancel_event
        self._urlopen = urlopen

    def _fetch(self, url: str):  # type: ignore[override]
        from tuf.api.exceptions import DownloadHTTPError, DownloadLengthMismatchError

        try:
            assert_https_trusted_url(
                url,
                self.policy.trusted_origins,
                require_https=self.policy.require_https,
            )
        except DownloadPolicyError as exc:
            raise DownloadHTTPError(str(exc), 400) from exc
        import urllib.error
        import urllib.request

        request = urllib.request.Request(url, method="GET")
        timeout = min(self.policy.connect_timeout_s, self.policy.read_timeout_s)
        try:
            if self._urlopen is not None:
                try:
                    response = self._urlopen(request, timeout=timeout)
                except TypeError:
                    response = self._urlopen(request)
            else:
                opener = build_policy_opener(self.policy)
                response = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            raise DownloadHTTPError(str(exc), exc.code) from exc
        except urllib.error.URLError as exc:
            raise DownloadError(str(exc.reason or exc)) from exc
        chunks: list[bytes] = []
        total = 0
        try:
            while True:
                if self.cancel_event is not None and self.cancel_event.is_set():
                    raise DownloadCancelled("metadata fetch cancelled")
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > self.policy.max_length:
                    raise DownloadLengthMismatchError("metadata exceeded length cap")
                chunks.append(chunk)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        yield b"".join(chunks)


def _map_tuf_error(exc: BaseException) -> ExtensionRepositoryError:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ExpiredMetadataError):
            return ExtensionRepositoryError(str(current), METADATA_EXPIRED)
        if isinstance(current, DownloadCancelled):
            return ExtensionRepositoryError(str(current), NETWORK_CHECK_FAILED)
        if isinstance(current, DownloadPolicyError):
            return ExtensionRepositoryError(str(current), current.reason_code)
        if isinstance(
            current,
            (
                UnsignedMetadataError,
                LengthOrHashMismatchError,
                DownloadLengthMismatchError,
                BadVersionNumberError,
            ),
        ):
            return ExtensionRepositoryError(str(current), VERIFICATION_FAILED)
        if isinstance(current, DownloadError):
            return ExtensionRepositoryError(str(current), NETWORK_CHECK_FAILED)
        if isinstance(current, TUFRepositoryError):
            return ExtensionRepositoryError(str(current), VERIFICATION_FAILED)
        current = current.__cause__ or current.__context__
    return ExtensionRepositoryError(str(exc), NETWORK_CHECK_FAILED)


class RepositoryClient:
    """Verify manager-status-v1 first, then a compatible component catalog."""

    def __init__(
        self,
        *,
        metadata_cache_dir: Path,
        bootstrap_root: bytes,
        metadata_base_url: str,
        target_base_url: str,
        trusted_origins: Sequence[str],
        manager_version: str,
        fetcher: FetcherInterface | None = None,
        download_policy: DownloadPolicy | None = None,
        revocation_store: Path | None = None,
        cancel_event: Any | None = None,
        urlopen: Callable[..., Any] | None = None,
        prefix_targets_with_hash: bool = False,
    ) -> None:
        self.metadata_cache_dir = Path(metadata_cache_dir)
        self.metadata_cache_dir.mkdir(parents=True, exist_ok=True)
        self.bootstrap_root = bootstrap_root
        self.metadata_base_url = metadata_base_url.rstrip("/") + "/"
        self.target_base_url = target_base_url.rstrip("/") + "/"
        self.trusted_origins = tuple(trusted_origins)
        self.manager_version = manager_version
        self.revocation_store = (
            Path(revocation_store)
            if revocation_store is not None
            else self.metadata_cache_dir / REVOCATION_STORE_NAME
        )
        self.cancel_event = cancel_event
        self._urlopen = urlopen
        self.policy = download_policy or DownloadPolicy(trusted_origins=self.trusted_origins)
        if fetcher is not None:
            self.fetcher = fetcher
            self._http_download = False
        else:
            self.fetcher = PolicyFetcher(
                self.policy,
                cancel_event=cancel_event,
                urlopen=urlopen,
            )
            self._http_download = True
        self._target_dir = self.metadata_cache_dir / "targets"
        self._target_dir.mkdir(parents=True, exist_ok=True)
        self._config = UpdaterConfig(prefix_targets_with_hash=prefix_targets_with_hash)
        self._updater: Updater | None = None
        self._last_status: ManagerStatusV1 | None = None
        self._last_catalog: ComponentCatalogV1 | None = None

    def _new_updater(self) -> Updater:
        return Updater(
            str(self.metadata_cache_dir),
            self.metadata_base_url,
            str(self._target_dir),
            self.target_base_url,
            fetcher=self.fetcher,
            config=self._config,
            bootstrap=self.bootstrap_root,
        )

    def refresh(self, *, require_fresh: bool = True) -> RefreshResult:
        """Refresh trusted metadata. Failures are not ``not_installed``."""

        if not require_fresh:
            status = self._last_status
            catalog = self._last_catalog
            return RefreshResult(
                ok=status is not None,
                reason_code=None if status is not None else NETWORK_CHECK_FAILED,
                manager_status=status,
                catalog=catalog,
                catalog_schema=(catalog or {}).get("schema") if catalog else None,
            )
        try:
            updater = self._new_updater()
            updater.refresh()
            status = self._load_status(updater)
            self._last_status = status
            catalog, catalog_reason = self._load_catalog(updater, status)
            self._last_catalog = catalog
            self._updater = updater
            if catalog is not None:
                merged = merge_revocations(
                    load_observed_revocations(self.revocation_store),
                    catalog,
                )
                save_observed_revocations(self.revocation_store, merged)
            reason = catalog_reason
            if reason is None and not manager_meets_minimum(
                self.manager_version,
                _status_minimum(status),
            ):
                reason = MANAGER_TOO_OLD
            ok = reason is None
            return RefreshResult(
                ok=ok,
                reason_code=reason,
                manager_status=status,
                catalog=catalog,
                catalog_schema=(catalog or {}).get("schema") if catalog else str(
                    status.get("schema") or MANAGER_STATUS_SCHEMA
                ),
            )
        except ExtensionRepositoryError as exc:
            return RefreshResult(ok=False, reason_code=exc.reason_code, manager_status=self._last_status)
        except Exception as exc:  # noqa: BLE001 — always a repository check, never uninstall
            mapped = _map_tuf_error(exc)
            return RefreshResult(
                ok=False,
                reason_code=mapped.reason_code,
                manager_status=self._last_status,
            )

    def _load_status(self, updater: Updater) -> ManagerStatusV1:
        info = updater.get_targetinfo(MANAGER_STATUS_TARGET)
        if info is None:
            raise ExtensionRepositoryError(
                "trusted repository is missing manager-status-v1.json",
                VERIFICATION_FAILED,
            )
        payload = self._read_target(updater, info)
        try:
            from mf4_analyzer.extensions.contract import (
                ExtensionError,
                parse_manager_status_v1,
            )

            parsed = parse_manager_status_v1(payload)
        except ExtensionError as exc:
            raise ExtensionRepositoryError(str(exc), exc.reason_code) from exc
        except Exception as exc:
            raise ExtensionRepositoryError(
                "manager-status-v1 is not a trusted v1 document",
                VERIFICATION_FAILED,
            ) from exc
        return {
            "schema": parsed.schema,
            "latest_manager_version": parsed.latest_manager_version,
            "minimum_supported_manager_version": parsed.minimum_supported_manager_version,
            "reason_code": parsed.reason_code or "",
            "installer_filename": parsed.installer_filename,
            "installer_target": parsed.installer_filename,
            "installer_sha256": parsed.installer_sha256,
            "help_page": parsed.help_page,
        }

    def _load_catalog(
        self,
        updater: Updater,
        status: ManagerStatusV1,
    ) -> tuple[ComponentCatalogV1 | None, str | None]:
        info = updater.get_targetinfo(COMPONENT_CATALOG_V1_TARGET)
        if info is None:
            if not manager_meets_minimum(
                self.manager_version,
                _status_minimum(status),
            ):
                return None, MANAGER_TOO_OLD
            return None, PROTOCOL_UNSUPPORTED
        payload = self._read_target(updater, info)
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, PROTOCOL_UNSUPPORTED
        if not isinstance(data, dict):
            return None, PROTOCOL_UNSUPPORTED
        schema = str(data.get("schema") or "")
        if schema not in SUPPORTED_CATALOG_SCHEMAS:
            if not manager_meets_minimum(
                self.manager_version,
                _status_minimum(status) or str(data.get("min_manager_version") or ""),
            ):
                return None, MANAGER_TOO_OLD
            return None, PROTOCOL_UNSUPPORTED
        protocol_major = int(data.get("protocol_major") or 0)
        if protocol_major and protocol_major > SUPPORTED_PROTOCOL_MAJOR:
            return None, PROTOCOL_UNSUPPORTED
        catalog: ComponentCatalogV1 = data  # type: ignore[assignment]
        catalog_min = str(catalog.get("min_manager_version") or "")
        if catalog_min and not manager_meets_minimum(self.manager_version, catalog_min):
            return catalog, MANAGER_TOO_OLD
        return catalog, None

    def _read_target(self, updater: Updater, info: TargetFile) -> bytes:
        path = updater.download_target(info)
        data = Path(path).read_bytes()
        info.verify_length_and_hashes(data)
        return data

    def select_package(
        self,
        component: str,
        core: CoreIdentity,
        *,
        platform_tag: str,
        python_tag: str | None = None,
        catalog: ComponentCatalogV1 | None = None,
    ) -> PackageSelection:
        capabilities = core.get("capabilities") or {}
        extra = str(component)
        if extra not in capabilities:
            return PackageSelection(False, NO_COMPATIBLE_PACKAGE)
        store = load_observed_revocations(self.revocation_store)
        return select_compatible_package(
            catalog if catalog is not None else self._last_catalog,
            component=component,
            runtime_id=str(core.get("runtime_id") or ""),
            component_api=str(capabilities[component]),
            manager_version=self.manager_version,
            platform_tag=platform_tag,
            core_capabilities=capabilities,
            known_revocations=store.hashes(),
            python_tag=python_tag or core.get("python_tag"),
        )

    def download_package(
        self,
        package: PackageRecord,
        app_root: Path,
        *,
        cancel_event: Any | None = None,
    ) -> Path:
        digest = str(package.get("sha256") or "").lower()
        length = int(package.get("length") or -1)
        target = str(package.get("target") or "")
        if not digest or length < 0 or not target:
            raise ExtensionRepositoryError("package record is incomplete", VERIFICATION_FAILED)
        dest = cache_download_path(app_root, digest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        updater = self._updater or self._new_updater()
        info = updater.get_targetinfo(target)
        if info is None:
            raise ExtensionRepositoryError(f"unknown TUF target {target}", VERIFICATION_FAILED)
        expected = info.hashes.get("sha256", digest).lower()
        if expected != digest:
            raise ExtensionRepositoryError(
                "package sha256 does not match trusted target metadata",
                VERIFICATION_FAILED,
            )
        if self._http_download:
            url = urllib.parse.urljoin(self.target_base_url, info.path)
            download_verified_file(
                url,
                dest,
                expected_sha256=expected,
                expected_length=int(info.length),
                policy=self.policy,
                cancel_event=cancel_event or self.cancel_event,
                urlopen=self._urlopen,
            )
        else:
            updater.download_target(info, filepath=str(dest))
        payload = dest.read_bytes()
        info.verify_length_and_hashes(payload)
        if hashlib.sha256(payload).hexdigest() != digest:
            dest.unlink(missing_ok=True)
            raise ExtensionRepositoryError("package SHA-256 mismatch", VERIFICATION_FAILED)
        return dest

    def download_manager_installer(
        self,
        app_root: Path,
        *,
        status: ManagerStatusV1 | None = None,
        cancel_event: Any | None = None,
    ) -> Path:
        """Download a verified installer next to cache/manager-updates/.

        Does not overwrite ``installer.exe`` in the application root.
        """

        current = status or self._last_status
        if current is None:
            raise ExtensionRepositoryError("manager-status-v1 has not been verified", VERIFICATION_FAILED)
        target = str(
            current.get("installer_filename")
            or current.get("installer_target")
            or ""
        )
        version = str(current.get("latest_manager_version") or "unknown")
        if not target:
            raise ExtensionRepositoryError(
                "manager-status-v1 has no installer artifact filename",
                VERIFICATION_FAILED,
            )
        dest = manager_update_path(app_root, version)
        if dest.resolve() == (Path(app_root) / "installer.exe").resolve():
            raise ExtensionRepositoryError(
                "refusing in-place overwrite of installer.exe",
                VERIFICATION_FAILED,
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        updater = self._updater or self._new_updater()
        info = updater.get_targetinfo(target)
        if info is None:
            raise ExtensionRepositoryError(f"unknown installer target {target}", VERIFICATION_FAILED)
        if self._http_download:
            url = urllib.parse.urljoin(self.target_base_url, info.path)
            sha256 = str(info.hashes["sha256"])
            download_verified_file(
                url,
                dest,
                expected_sha256=sha256,
                expected_length=int(info.length),
                policy=self.policy,
                cancel_event=cancel_event or self.cancel_event,
                urlopen=self._urlopen,
            )
        else:
            updater.download_target(info, filepath=str(dest))
        info.verify_length_and_hashes(dest.read_bytes())
        root_installer = Path(app_root) / "installer.exe"
        if dest.resolve() == root_installer.resolve():
            raise ExtensionRepositoryError(
                "refusing in-place overwrite of installer.exe",
                VERIFICATION_FAILED,
            )
        return dest

    def observed_revocation_hashes(self) -> frozenset[str]:
        return load_observed_revocations(self.revocation_store).hashes()

    @classmethod
    def from_offline_bundle(
        cls,
        bundle_dir: Path,
        *,
        metadata_cache_dir: Path,
        bootstrap_root: bytes,
        manager_version: str,
        revocation_store: Path | None = None,
        trusted_origins: Sequence[str] = ("offline.test",),
    ) -> RepositoryClient:
        """Open an offline issuance set through the same TUF trust chain."""

        return cls(
            metadata_cache_dir=metadata_cache_dir,
            bootstrap_root=bootstrap_root,
            metadata_base_url="https://offline.test/metadata/",
            target_base_url="https://offline.test/targets/",
            trusted_origins=trusted_origins,
            manager_version=manager_version,
            fetcher=LocalPathFetcher(bundle_dir),
            revocation_store=revocation_store,
            download_policy=DownloadPolicy(
                trusted_origins=tuple(trusted_origins),
                require_https=True,
            ),
        )


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
