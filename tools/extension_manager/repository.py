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
from dataclasses import dataclass, field, replace
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

from mf4_analyzer.extensions.contract import (
    ExtensionError,
    ManagerStatusV1 as TrustedManagerStatus,
    ReasonCode,
    VerifiedPackage,
    bind_verified_package,
    compare_semver as contract_compare_semver,
    parse_manager_status_v1,
    sha256_hex,
)

from .download import (
    DownloadCancelled,
    DownloadPolicy,
    DownloadPolicyError,
    assert_https_trusted_url,
    build_policy_opener,
    download_verified_file,
)

# S11.1 reason codes come from the neutral contract. Repository-layer codes
# below are not install-state names and are not a second schema fallback.
COMPONENT_MISSING = ReasonCode.COMPONENT_MISSING
COMPONENT_INCOMPATIBLE = ReasonCode.COMPONENT_INCOMPATIBLE
COMPONENT_CORRUPT = ReasonCode.COMPONENT_CORRUPT
MANAGER_TOO_OLD = ReasonCode.MANAGER_TOO_OLD
PROTOCOL_UNSUPPORTED = ReasonCode.PROTOCOL_UNSUPPORTED
NO_COMPATIBLE_PACKAGE = ReasonCode.NO_COMPATIBLE_PACKAGE
CORE_INCONSISTENT = ReasonCode.CORE_INCONSISTENT
APP_RUNNING = ReasonCode.APP_RUNNING
UNSUPPORTED_FILESYSTEM = ReasonCode.UNSUPPORTED_FILESYSTEM
VERIFICATION_FAILED = ReasonCode.VERIFICATION_FAILED
PROBE_FAILED = ReasonCode.PROBE_FAILED
TRANSACTION_RECOVERY_REQUIRED = ReasonCode.TRANSACTION_RECOVERY_REQUIRED
NETWORK_CHECK_FAILED = "NETWORK_CHECK_FAILED"
METADATA_EXPIRED = "METADATA_EXPIRED"
TARGET_REVOKED = "TARGET_REVOKED"
REVOCATION_CACHE_CORRUPT = "REVOCATION_CACHE_CORRUPT"
DOWNLOAD_CANCELLED = "DOWNLOAD_CANCELLED"
COMPONENT_CHANGE_KIND = "component_change"
INSTALLER_UPDATE_KIND = "installer_update"

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
    package_json_target: str
    package_json_sha256: str
    package_json_length: int


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
    snapshot: RepositorySnapshot | None = None


@dataclass(frozen=True)
class RepositorySnapshot:
    """One verified refresh: display fields stay readable after later failure.

    ``change_authorized`` is component install/upgrade/uninstall eligibility for
    *this* snapshot. Last-success catalog/status remain for display even when
    this flag is False. ``installer_update_authorized`` is the separate recovery
    path that may stay true for a freshly verified manager-status when the
    manager is too old or the catalog cannot be read.
    """

    snapshot_id: str
    manager_status: TrustedManagerStatus
    catalog: ComponentCatalogV1 | None
    catalog_schema: str | None
    installer_target: str
    installer_sha256: str
    change_authorized: bool = False
    installer_update_authorized: bool = False
    qualification_reason: str | None = None
    metadata_expires: datetime | None = None
    repository_generation: int | None = None


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


def _status_mapping(parsed: TrustedManagerStatus) -> ManagerStatusV1:
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


def _target_sha256(info: TargetFile) -> str:
    digest = info.hashes.get("sha256")
    if not digest:
        raise ExtensionRepositoryError(
            "trusted target is missing sha256",
            VERIFICATION_FAILED,
        )
    return str(digest).lower()


class ExtensionRepositoryError(Exception):
    def __init__(self, message: str, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def compare_semver(left: str, right: str) -> int:
    """Strict SemVer compare: negative if left < right. Not string lexicographic."""

    return int(contract_compare_semver(left, right))


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


def _revocation_cache_corrupt(message: str, cause: BaseException | None = None) -> ExtensionRepositoryError:
    error = ExtensionRepositoryError(message, REVOCATION_CACHE_CORRUPT)
    if cause is not None:
        error.__cause__ = cause
    return error


def load_observed_revocations(path: Path) -> ObservedRevocations:
    """Load persisted revocations. A missing file means none were observed.

    Corrupt JSON/schema is a diagnostic failure, not an empty store. Callers
    must not treat this as "never learned any revocations".
    """

    if not path.is_file():
        return ObservedRevocations()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _revocation_cache_corrupt(
            "observed revocation cache is unreadable",
            exc,
        ) from exc
    if not isinstance(payload, dict):
        raise _revocation_cache_corrupt("observed revocation cache is not an object")
    schema = payload.get("schema")
    items = payload.get("items")
    if schema is not None and schema != "observed-revocations-v1":
        raise _revocation_cache_corrupt(
            f"unsupported observed revocation schema {schema!r}",
        )
    if not isinstance(items, list):
        raise _revocation_cache_corrupt("observed revocation cache is missing an items array")
    records: list[RevocationRecord] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("sha256"):
            raise _revocation_cache_corrupt("observed revocation cache contains an invalid item")
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

    try:
        store = load_observed_revocations(revocation_store)
    except ExtensionRepositoryError as exc:
        return InstalledTrust(may_run=False, reason_code=exc.reason_code)
    if is_hash_revoked(package_sha256, store):
        return InstalledTrust(may_run=False, reason_code=TARGET_REVOKED)
    return InstalledTrust(may_run=True, required_fresh_metadata=False)


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
    chain: list[BaseException] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    for item in chain:
        if isinstance(item, ExpiredMetadataError):
            return ExtensionRepositoryError(str(item), METADATA_EXPIRED)
        if isinstance(item, DownloadCancelled):
            return ExtensionRepositoryError(str(item), DOWNLOAD_CANCELLED)
    for item in chain:
        if isinstance(item, DownloadPolicyError):
            return ExtensionRepositoryError(str(item), item.reason_code)
        if isinstance(
            item,
            (
                UnsignedMetadataError,
                LengthOrHashMismatchError,
                DownloadLengthMismatchError,
                BadVersionNumberError,
            ),
        ):
            return ExtensionRepositoryError(str(item), VERIFICATION_FAILED)
        if isinstance(item, DownloadError):
            return ExtensionRepositoryError(str(item), NETWORK_CHECK_FAILED)
        if isinstance(item, TUFRepositoryError):
            return ExtensionRepositoryError(str(item), VERIFICATION_FAILED)
    raise exc


_KNOWN_REFRESH_ERRORS = (
    ExpiredMetadataError,
    DownloadCancelled,
    DownloadPolicyError,
    UnsignedMetadataError,
    LengthOrHashMismatchError,
    DownloadLengthMismatchError,
    BadVersionNumberError,
    DownloadError,
    TUFRepositoryError,
)


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
        self._trusted_status: TrustedManagerStatus | None = None
        self._snapshot: RepositorySnapshot | None = None
        self._status_payload: bytes | None = None

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
            snapshot = self._snapshot
            authorized = bool(snapshot is not None and snapshot.change_authorized)
            catalog = self._last_catalog
            return RefreshResult(
                ok=authorized,
                reason_code=(
                    None
                    if authorized
                    else (snapshot.qualification_reason if snapshot else NETWORK_CHECK_FAILED)
                ),
                manager_status=self._last_status,
                catalog=catalog,
                catalog_schema=(catalog or {}).get("schema") if catalog else None,
                snapshot=snapshot,
            )
        try:
            updater = self._new_updater()
            updater.refresh()
            status = self._load_status(updater)
            self._last_status = status
            catalog, catalog_reason = self._load_catalog(updater, status)
            self._last_catalog = catalog
            self._updater = updater
            reason = catalog_reason
            if reason is None and not manager_meets_minimum(
                self.manager_version,
                _status_minimum(status),
            ):
                reason = MANAGER_TOO_OLD
            if catalog is not None:
                try:
                    merged = merge_revocations(
                        load_observed_revocations(self.revocation_store),
                        catalog,
                    )
                    save_observed_revocations(self.revocation_store, merged)
                except ExtensionRepositoryError as exc:
                    if exc.reason_code != REVOCATION_CACHE_CORRUPT:
                        raise
                    reason = REVOCATION_CACHE_CORRUPT
            snapshot = self._bind_verified_snapshot(
                updater,
                status,
                catalog,
                qualification_reason=reason,
            )
            return RefreshResult(
                ok=reason is None,
                reason_code=reason,
                manager_status=status,
                catalog=catalog,
                catalog_schema=(catalog or {}).get("schema") if catalog else str(
                    status.get("schema") or MANAGER_STATUS_SCHEMA
                ),
                snapshot=snapshot,
            )
        except ExtensionRepositoryError as exc:
            return self._refresh_failure(exc.reason_code)
        except _KNOWN_REFRESH_ERRORS as exc:
            mapped = _map_tuf_error(exc)
            return self._refresh_failure(mapped.reason_code)

    def _refresh_failure(self, reason_code: str) -> RefreshResult:
        snapshot = self._revoke_live_authorization(reason_code)
        catalog = self._last_catalog
        return RefreshResult(
            ok=False,
            reason_code=reason_code,
            manager_status=self._last_status,
            catalog=catalog,
            catalog_schema=(catalog or {}).get("schema") if catalog else None,
            snapshot=snapshot,
        )

    def _revoke_live_authorization(self, reason_code: str) -> RepositorySnapshot | None:
        """Keep last-success data for display; drop current change eligibility."""

        snapshot = self._snapshot
        if snapshot is None:
            return None
        revoked = replace(
            snapshot,
            change_authorized=False,
            installer_update_authorized=False,
            qualification_reason=reason_code,
        )
        self._snapshot = revoked
        return revoked

    def _bind_verified_snapshot(
        self,
        updater: Updater,
        status: ManagerStatusV1,
        catalog: ComponentCatalogV1 | None,
        *,
        qualification_reason: str | None,
    ) -> RepositorySnapshot | None:
        trusted = self._trusted_status
        if trusted is None or self._status_payload is None:
            return None
        catalog_identity = b""
        if catalog is not None:
            catalog_identity = json.dumps(
                catalog,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        component_ok = qualification_reason is None
        snapshot = RepositorySnapshot(
            snapshot_id=sha256_hex(self._status_payload + b"\0" + catalog_identity),
            manager_status=trusted,
            catalog=catalog,
            catalog_schema=(catalog or {}).get("schema") if catalog else str(
                status.get("schema") or MANAGER_STATUS_SCHEMA
            ),
            installer_target=trusted.installer_filename,
            installer_sha256=trusted.installer_sha256,
            change_authorized=component_ok,
            installer_update_authorized=True,
            qualification_reason=qualification_reason,
            metadata_expires=_trusted_metadata_expires(updater),
            repository_generation=_trusted_generation(updater),
        )
        self._snapshot = snapshot
        return snapshot

    def _load_revocations(self) -> ObservedRevocations:
        return load_observed_revocations(self.revocation_store)

    def _assert_snapshot_preconditions(self, snapshot: RepositorySnapshot) -> None:
        expires = snapshot.metadata_expires
        if expires is not None and utcnow() >= expires:
            self._revoke_live_authorization(METADATA_EXPIRED)
            raise ExtensionRepositoryError("trusted metadata has expired", METADATA_EXPIRED)
        updater = self._updater
        if (
            updater is not None
            and snapshot.repository_generation is not None
        ):
            live_generation = _trusted_generation(updater)
            if live_generation is not None and live_generation != snapshot.repository_generation:
                self._revoke_live_authorization(VERIFICATION_FAILED)
                raise ExtensionRepositoryError(
                    "repository generation changed since this snapshot was verified",
                    VERIFICATION_FAILED,
                )

    def _require_snapshot(self, *, kind: str) -> RepositorySnapshot:
        snapshot = self._snapshot
        if snapshot is None:
            raise ExtensionRepositoryError(
                "no verified repository snapshot is bound",
                VERIFICATION_FAILED,
            )
        self._assert_snapshot_preconditions(snapshot)
        snapshot = self._snapshot
        if snapshot is None:
            raise ExtensionRepositoryError(
                "no verified repository snapshot is bound",
                VERIFICATION_FAILED,
            )
        if kind == COMPONENT_CHANGE_KIND:
            if not snapshot.change_authorized:
                raise ExtensionRepositoryError(
                    "repository snapshot is not authorized for component changes",
                    snapshot.qualification_reason or VERIFICATION_FAILED,
                )
            self._load_revocations()
        elif kind == INSTALLER_UPDATE_KIND:
            if not snapshot.installer_update_authorized:
                raise ExtensionRepositoryError(
                    "repository snapshot is not authorized for installer updates",
                    snapshot.qualification_reason or VERIFICATION_FAILED,
                )
        else:
            raise ExtensionRepositoryError(
                f"unknown qualification kind {kind!r}",
                VERIFICATION_FAILED,
            )
        return snapshot

    def requalify_after_lock_wait(self, *, kind: str = COMPONENT_CHANGE_KIND) -> RepositorySnapshot:
        """Re-run snapshot preconditions after a future W5 lock wait.

        W3 does not implement transaction locking and this method does not wait.
        W5 must call it after a lock is acquired and before commit.
        """

        return self._require_snapshot(kind=kind)

    def _load_status(self, updater: Updater) -> ManagerStatusV1:
        info = updater.get_targetinfo(MANAGER_STATUS_TARGET)
        if info is None:
            raise ExtensionRepositoryError(
                "trusted repository is missing manager-status-v1.json",
                VERIFICATION_FAILED,
            )
        payload = self._read_target(updater, info)
        try:
            parsed = parse_manager_status_v1(payload)
        except ExtensionError as exc:
            raise ExtensionRepositoryError(str(exc), exc.reason_code) from exc
        installer_info = updater.get_targetinfo(parsed.installer_filename)
        if installer_info is None:
            raise ExtensionRepositoryError(
                f"unknown installer target {parsed.installer_filename}",
                VERIFICATION_FAILED,
            )
        target_hash = _target_sha256(installer_info)
        if parsed.installer_sha256 != target_hash:
            raise ExtensionRepositoryError(
                "manager-status installer sha256 does not match the trusted installer target",
                VERIFICATION_FAILED,
            )
        self._trusted_status = parsed
        self._status_payload = payload
        return _status_mapping(parsed)

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
        try:
            snapshot = self._require_snapshot(kind=COMPONENT_CHANGE_KIND)
            store = self._load_revocations()
        except ExtensionRepositoryError as exc:
            return PackageSelection(False, exc.reason_code)
        capabilities = core.get("capabilities") or {}
        extra = str(component)
        if extra not in capabilities:
            return PackageSelection(False, NO_COMPATIBLE_PACKAGE)
        trusted_catalog = catalog if catalog is not None else snapshot.catalog
        return select_compatible_package(
            trusted_catalog,
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
        snapshot = self._require_snapshot(kind=COMPONENT_CHANGE_KIND)
        store = self._load_revocations()
        digest = str(package.get("sha256") or "").lower()
        length = int(package.get("length") or -1)
        target = str(package.get("target") or "")
        if not digest or length < 0 or not target:
            raise ExtensionRepositoryError("package record is incomplete", VERIFICATION_FAILED)
        if is_hash_revoked(digest, store):
            raise ExtensionRepositoryError("package hash is revoked", TARGET_REVOKED)
        catalog_revoked = {
            str(item.get("sha256") or "").lower()
            for item in (snapshot.catalog or {}).get("revoked") or []
            if item.get("sha256")
        }
        if digest in catalog_revoked:
            raise ExtensionRepositoryError("package hash is revoked", TARGET_REVOKED)
        if snapshot.catalog is not None:
            known = {
                str(item.get("sha256") or "").lower()
                for item in snapshot.catalog.get("packages") or []
                if item.get("sha256")
            }
            if digest not in known:
                raise ExtensionRepositoryError(
                    "package is not in the authorized catalog",
                    NO_COMPATIBLE_PACKAGE,
                )
        minimum = str(package.get("min_manager_version") or "")
        if minimum and not manager_meets_minimum(self.manager_version, minimum):
            raise ExtensionRepositoryError(
                "package requires a newer extension manager",
                MANAGER_TOO_OLD,
            )
        dest = cache_download_path(app_root, digest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        updater = self._updater
        if updater is None:
            raise ExtensionRepositoryError(
                "no verified repository snapshot is bound",
                VERIFICATION_FAILED,
            )
        info = updater.get_targetinfo(target)
        if info is None:
            raise ExtensionRepositoryError(f"unknown TUF target {target}", VERIFICATION_FAILED)
        expected = info.hashes.get("sha256", digest).lower()
        if expected != digest:
            raise ExtensionRepositoryError(
                "package sha256 does not match trusted target metadata",
                VERIFICATION_FAILED,
            )
        try:
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
        except DownloadCancelled:
            raise
        except DownloadPolicyError as exc:
            raise ExtensionRepositoryError(str(exc), exc.reason_code) from exc
        payload = dest.read_bytes()
        info.verify_length_and_hashes(payload)
        if hashlib.sha256(payload).hexdigest() != digest:
            dest.unlink(missing_ok=True)
            raise ExtensionRepositoryError("package SHA-256 mismatch", VERIFICATION_FAILED)
        return dest

    def download_verified_package(
        self,
        package: PackageRecord,
        app_root: Path,
        *,
        cancel_event: Any | None = None,
    ) -> tuple[Path, VerifiedPackage]:
        """Download ZIP + independent package.json and bind one VerifiedPackage."""

        snapshot = self._require_snapshot(kind=COMPONENT_CHANGE_KIND)
        zip_path = self.download_package(package, app_root, cancel_event=cancel_event)
        manifest_target = str(package.get("package_json_target") or "")
        manifest_sha256 = str(package.get("package_json_sha256") or "").lower()
        try:
            manifest_length = int(package.get("package_json_length") or -1)
        except (TypeError, ValueError) as exc:
            raise ExtensionRepositoryError(
                "independent package.json length is missing",
                VERIFICATION_FAILED,
            ) from exc
        if not manifest_target or not manifest_sha256 or manifest_length < 0:
            raise ExtensionRepositoryError(
                "independent package.json target is missing",
                VERIFICATION_FAILED,
            )
        updater = self._updater
        if updater is None:
            raise ExtensionRepositoryError(
                "no verified repository snapshot is bound",
                VERIFICATION_FAILED,
            )
        info = updater.get_targetinfo(manifest_target)
        if info is None:
            raise ExtensionRepositoryError(
                f"unknown TUF target {manifest_target}",
                VERIFICATION_FAILED,
            )
        expected = _target_sha256(info)
        if expected != manifest_sha256:
            raise ExtensionRepositoryError(
                "package.json sha256 does not match trusted target metadata",
                VERIFICATION_FAILED,
            )
        dest = cache_download_path(app_root, manifest_sha256).with_name(
            f"{manifest_sha256}.package.json"
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
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
        if sha256_hex(payload) != manifest_sha256 or len(payload) != manifest_length:
            dest.unlink(missing_ok=True)
            raise ExtensionRepositoryError("package.json SHA-256 mismatch", VERIFICATION_FAILED)
        try:
            verified = bind_verified_package(
                snapshot_id=snapshot.snapshot_id,
                component=str(package.get("component") or ""),
                runtime_id=str(package.get("runtime_id") or ""),
                package_revision=int(package.get("package_revision") or 0),
                component_api=str(package.get("component_api") or ""),
                min_manager_version=str(package.get("min_manager_version") or "0.0.0"),
                zip_target=str(package.get("target") or ""),
                zip_sha256=str(package.get("sha256") or ""),
                zip_length=int(package.get("length") or -1),
                manifest_target=manifest_target,
                manifest_sha256=manifest_sha256,
                manifest_length=manifest_length,
                package_json_bytes=payload,
            )
        except ExtensionError as exc:
            raise ExtensionRepositoryError(str(exc), exc.reason_code) from exc
        if sha256_hex(zip_path.read_bytes()) != verified.zip.sha256:
            raise ExtensionRepositoryError(
                "ZIP hash does not match the verified package binding",
                VERIFICATION_FAILED,
            )
        return zip_path, verified

    def download_manager_installer(
        self,
        app_root: Path,
        *,
        status: ManagerStatusV1 | None = None,
        cancel_event: Any | None = None,
    ) -> Path:
        """Download a verified installer next to cache/manager-updates/.

        Display version and installer hash come from the verified snapshot.
        Callers cannot inject a different manager-status document.
        Does not overwrite ``installer.exe`` in the application root.
        """

        snapshot = self._require_snapshot(kind=INSTALLER_UPDATE_KIND)
        trusted = snapshot.manager_status
        if status is not None:
            injected_hash = str(status.get("installer_sha256") or "").lower()
            injected_name = str(
                status.get("installer_filename") or status.get("installer_target") or ""
            )
            injected_version = str(status.get("latest_manager_version") or "")
            if (
                injected_hash != trusted.installer_sha256
                or injected_name != trusted.installer_filename
                or injected_version != trusted.latest_manager_version
            ):
                raise ExtensionRepositoryError(
                    "caller cannot inject a manager-status other than the verified snapshot",
                    VERIFICATION_FAILED,
                )
        target = trusted.installer_filename
        version = trusted.latest_manager_version
        dest = manager_update_path(app_root, version)
        if dest.resolve() == (Path(app_root) / "installer.exe").resolve():
            raise ExtensionRepositoryError(
                "refusing in-place overwrite of installer.exe",
                VERIFICATION_FAILED,
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        updater = self._updater
        if updater is None:
            raise ExtensionRepositoryError(
                "no verified repository snapshot is bound",
                VERIFICATION_FAILED,
            )
        info = updater.get_targetinfo(target)
        if info is None:
            raise ExtensionRepositoryError(f"unknown installer target {target}", VERIFICATION_FAILED)
        target_hash = _target_sha256(info)
        if target_hash != trusted.installer_sha256:
            raise ExtensionRepositoryError(
                "manager-status installer sha256 does not match the trusted installer target",
                VERIFICATION_FAILED,
            )
        try:
            if self._http_download:
                url = urllib.parse.urljoin(self.target_base_url, info.path)
                download_verified_file(
                    url,
                    dest,
                    expected_sha256=trusted.installer_sha256,
                    expected_length=int(info.length),
                    policy=self.policy,
                    cancel_event=cancel_event or self.cancel_event,
                    urlopen=self._urlopen,
                )
            else:
                updater.download_target(info, filepath=str(dest))
        except DownloadCancelled:
            raise
        except DownloadPolicyError as exc:
            raise ExtensionRepositoryError(str(exc), exc.reason_code) from exc
        payload = dest.read_bytes()
        info.verify_length_and_hashes(payload)
        if sha256_hex(payload) != trusted.installer_sha256:
            dest.unlink(missing_ok=True)
            raise ExtensionRepositoryError("installer SHA-256 mismatch", VERIFICATION_FAILED)
        root_installer = Path(app_root) / "installer.exe"
        if dest.resolve() == root_installer.resolve():
            raise ExtensionRepositoryError(
                "refusing in-place overwrite of installer.exe",
                VERIFICATION_FAILED,
            )
        return dest

    def observed_revocation_hashes(self) -> frozenset[str]:
        return self._load_revocations().hashes()

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


def _trusted_metadata_expires(updater: Updater) -> datetime | None:
    times: list[datetime] = []
    stored = getattr(updater._trusted_set, "_trusted_set", {})
    if isinstance(stored, dict):
        values = stored.values()
    else:
        values = ()
    for signed in values:
        expires = getattr(signed, "expires", None)
        if isinstance(expires, datetime):
            times.append(expires)
    return min(times) if times else None


def _trusted_generation(updater: Updater) -> int | None:
    stored = getattr(updater._trusted_set, "_trusted_set", {})
    if not isinstance(stored, dict):
        return None
    timestamp = stored.get("timestamp")
    version = getattr(timestamp, "version", None)
    return int(version) if version is not None else None
