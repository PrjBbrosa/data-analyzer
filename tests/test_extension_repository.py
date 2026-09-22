"""Trusted metadata + download tests for the optional-extension manager."""

from __future__ import annotations

import ast
import hashlib
import http.server
import json
import socketserver
import sys
import threading
import time
import urllib.parse
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TUF_ROOT = _REPO_ROOT / ".state" / "extension-manager-tuf"
for _site in list(_TUF_ROOT.glob("lib/python*/site-packages")):
    _text = str(_site)
    if _text not in sys.path:
        sys.path.insert(0, _text)
_win_site = _TUF_ROOT / "Lib" / "site-packages"
if _win_site.is_dir() and str(_win_site) not in sys.path:
    sys.path.insert(0, str(_win_site))

try:
    import tuf  # noqa: F401
    import securesystemslib  # noqa: F401
    import cryptography  # noqa: F401
except ImportError:
    pytest.fail(
        "tuf/securesystemslib/cryptography are required for "
        "tests/test_extension_repository.py. Install "
        "tools/extension_manager/requirements.txt into "
        ".state/extension-manager-tuf (do not install into the app .venv)."
    )

from securesystemslib.signer import CryptoSigner
from tuf.api.exceptions import DownloadHTTPError
from tuf.api.metadata import (
    TOP_LEVEL_ROLE_NAMES,
    Metadata,
    MetaFile,
    Root,
    Snapshot,
    TargetFile,
    Targets,
    Timestamp,
)
from tuf.ngclient.fetcher import FetcherInterface

from tools.extension_manager.download import (
    DownloadCancelled,
    DownloadPolicy,
    DownloadPolicyError,
    assert_https_trusted_url,
    download_verified_file,
    resolve_redirect_url,
)
from tools.extension_manager.repository import (
    COMPONENT_CATALOG_V1_SCHEMA,
    DOWNLOAD_CANCELLED,
    MANAGER_TOO_OLD,
    METADATA_EXPIRED,
    NETWORK_CHECK_FAILED,
    NO_COMPATIBLE_PACKAGE,
    PROTOCOL_UNSUPPORTED,
    REVOCATION_CACHE_CORRUPT,
    TARGET_REVOKED,
    VERIFICATION_FAILED,
    CoreIdentity,
    ExtensionRepositoryError,
    LocalPathFetcher,
    RepositoryClient,
    compare_semver,
    installed_component_may_run,
    load_observed_revocations,
    manager_update_path,
    select_compatible_package,
)
from mf4_analyzer.extensions.contract import generate_package_manifest
from tools.extension_manager.unpack import extract_verified_package

FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "extension_repository"
RUNTIME_ID = "cpython-3.12-win-amd64-numpy-2"
MEDIA_API = "media-api-1"
MATLAB_API = "matlab-api-1"
PLATFORM = "win-amd64"
CORE: CoreIdentity = {
    "runtime_id": RUNTIME_ID,
    "capabilities": {"media": MEDIA_API, "matlab": MATLAB_API},
    "python_tag": "cp312",
    "platform_tag": PLATFORM,
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _status_bytes(**overrides: Any) -> bytes:
    installer = b"installer-exe-bytes"
    payload = {
        "schema": 1,
        "latest_manager_version": "1.2.0",
        "minimum_supported_manager_version": "1.0.0",
        "reason_code": None,
        "installer_artifact": {
            "filename": "installer-1.2.0.exe",
            "sha256": _sha256(installer),
            "size": len(installer),
        },
        "help_page": "https://example.test/help/extensions",
    }
    artifact = overrides.pop("installer_artifact", None)
    payload.update(overrides)
    if artifact:
        merged = dict(payload["installer_artifact"])
        merged.update(artifact)
        payload["installer_artifact"] = merged
    return json.dumps(payload).encode("utf-8")


def _catalog_bytes(packages: list[dict[str, Any]], **overrides: Any) -> bytes:
    payload = {
        "schema": COMPONENT_CATALOG_V1_SCHEMA,
        "protocol_major": 1,
        "protocol_minor": 0,
        "min_manager_version": "1.0.0",
        "packages": packages,
        "revoked": [],
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


def _media_package(blob: bytes, **overrides: Any) -> dict[str, Any]:
    record = {
        "component": "media",
        "package_revision": 3,
        "runtime_id": RUNTIME_ID,
        "component_api": MEDIA_API,
        "min_manager_version": "1.0.0",
        "python_tag": "cp312",
        "platform_tag": PLATFORM,
        "target": "packages/media-3.bin",
        "sha256": _sha256(blob),
        "length": len(blob),
    }
    record.update(overrides)
    return record


class LocalTUFRepo:
    """In-memory TUF repository. Keys exist only for this process/tmp test."""

    def __init__(self, expires: datetime | None = None) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        self.expires = expires or (now + timedelta(days=14))
        self.signers = {role: CryptoSigner.generate_ed25519() for role in TOP_LEVEL_ROLE_NAMES}
        self.md_root = Metadata(Root(version=1, expires=self.expires, consistent_snapshot=False))
        for role, signer in self.signers.items():
            self.md_root.signed.add_key(signer.public_key, role)
        self._sign(self.md_root, "root")
        self.signed_roots = {1: self.md_root.to_bytes()}
        self.md_targets = Metadata(Targets(version=1, expires=self.expires, targets={}))
        self.md_snapshot = Metadata(
            Snapshot(version=1, expires=self.expires, meta={"targets.json": MetaFile(1)})
        )
        self.md_timestamp = Metadata(
            Timestamp(version=1, expires=self.expires, snapshot_meta=MetaFile(1))
        )
        self.target_bytes: dict[str, bytes] = {}
        self.publish(bump=False)

    def _sign(self, metadata: Metadata[Any], role: str) -> None:
        metadata.signatures.clear()
        metadata.sign(self.signers[role])

    def publish(self, *, bump: bool = True) -> None:
        if bump:
            self.md_targets.signed.version += 1
            self.md_snapshot.signed.version += 1
            self.md_timestamp.signed.version += 1
        self.md_targets.signed.expires = self.expires
        self.md_snapshot.signed.expires = self.expires
        self.md_timestamp.signed.expires = self.expires
        self.md_targets.signed.targets = {
            name: TargetFile.from_data(name, data) for name, data in self.target_bytes.items()
        }
        self._sign(self.md_targets, "targets")
        self.md_snapshot.signed.meta["targets.json"] = MetaFile(self.md_targets.signed.version)
        self._sign(self.md_snapshot, "snapshot")
        self.md_timestamp.signed.snapshot_meta = MetaFile(self.md_snapshot.signed.version)
        self._sign(self.md_timestamp, "timestamp")
        self.signed_roots[self.md_root.signed.version] = self.md_root.to_bytes()

    def set_standard_targets(
        self,
        *,
        blob: bytes | None = None,
        status: bytes | None = None,
        catalog: bytes | None = None,
        installer: bytes | None = None,
        extra_packages: list[dict[str, Any]] | None = None,
        catalog_overrides: dict[str, Any] | None = None,
        status_overrides: dict[str, Any] | None = None,
        extra_targets: dict[str, bytes] | None = None,
        bump: bool = False,
    ) -> bytes:
        package_blob = blob if blob is not None else b"media-package-bytes"
        installer_blob = installer if installer is not None else b"installer-exe-bytes"
        packages = [_media_package(package_blob)]
        if extra_packages:
            packages.extend(extra_packages)
        status_payload = status if status is not None else _status_bytes(**(status_overrides or {}))
        catalog_payload = catalog if catalog is not None else _catalog_bytes(
            packages, **(catalog_overrides or {})
        )
        self.target_bytes = {
            "manager-status-v1.json": status_payload,
            "component-catalog-v1.json": catalog_payload,
            "packages/media-3.bin": package_blob,
            "installer-1.2.0.exe": installer_blob,
        }
        if extra_targets:
            self.target_bytes.update(extra_targets)
        self.publish(bump=bump)
        return package_blob

    def export_files(self) -> dict[str, bytes]:
        files = {
            "root.json": self.md_root.to_bytes(),
            "timestamp.json": self.md_timestamp.to_bytes(),
            "snapshot.json": self.md_snapshot.to_bytes(),
            "targets.json": self.md_targets.to_bytes(),
        }
        for version, payload in self.signed_roots.items():
            files[f"{version}.root.json"] = payload
        files.update(self.target_bytes)
        return files

    def write_offline_bundle(self, dest: Path) -> None:
        (dest / "metadata").mkdir(parents=True, exist_ok=True)
        (dest / "targets").mkdir(parents=True, exist_ok=True)
        files = self.export_files()
        for name in ("root.json", "timestamp.json", "snapshot.json", "targets.json"):
            (dest / "metadata" / name).write_bytes(files[name])
        for version, payload in self.signed_roots.items():
            (dest / "metadata" / f"{version}.root.json").write_bytes(payload)
        for name, payload in self.target_bytes.items():
            path = dest / "targets" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)

    def rotate_root(self) -> None:
        old = self.signers["root"]
        new = CryptoSigner.generate_ed25519()
        self.md_root.signed.version += 1
        self.md_root.signed.expires = self.expires
        self.md_root.signed.revoke_key(old.public_key.keyid, "root")
        self.md_root.signed.add_key(new.public_key, "root")
        self.md_root.signatures.clear()
        self.md_root.sign(old)
        self.md_root.sign(new, append=True)
        self.signers["root"] = new
        self.signed_roots[self.md_root.signed.version] = self.md_root.to_bytes()


class RepoFetcher(FetcherInterface):
    def __init__(self, repo: LocalTUFRepo) -> None:
        self.repo = repo
        self.fail_names: set[str] = set()

    def _fetch(self, url: str):  # type: ignore[override]
        name = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]
        if name in self.fail_names:
            raise DownloadHTTPError("injected disconnect", 503)
        files = self.repo.export_files()
        key = name
        if name not in files:
            # Hash-less target paths keep directory prefixes; try full tail.
            path = urllib.parse.urlparse(url).path.lstrip("/")
            if path.startswith("targets/"):
                key = path.split("targets/", 1)[-1]
            elif path.startswith("metadata/"):
                key = path.split("metadata/", 1)[-1]
        if key not in files:
            raise DownloadHTTPError(f"missing {url}", 404)
        yield files[key]


def _client(repo: LocalTUFRepo, tmp_path: Path, manager_version: str = "1.0.0") -> RepositoryClient:
    cache = tmp_path / "metadata-cache"
    return RepositoryClient(
        metadata_cache_dir=cache,
        bootstrap_root=repo.signed_roots[1],
        metadata_base_url="https://example.test/metadata/",
        target_base_url="https://example.test/targets/",
        trusted_origins=("example.test",),
        manager_version=manager_version,
        fetcher=RepoFetcher(repo),
        revocation_store=tmp_path / "observed-revocations.json",
    )


def test_fixture_examples_use_spec_field_names() -> None:
    status = json.loads((FIXTURES / "manager-status-v1.example.json").read_text(encoding="utf-8"))
    catalog = json.loads((FIXTURES / "component-catalog-v1.example.json").read_text(encoding="utf-8"))
    assert status["schema"] == 1
    for key in (
        "latest_manager_version",
        "minimum_supported_manager_version",
        "reason_code",
        "installer_artifact",
        "help_page",
    ):
        assert key in status
    assert "filename" in status["installer_artifact"]
    assert "sha256" in status["installer_artifact"]
    assert catalog["schema"] == COMPONENT_CATALOG_V1_SCHEMA
    pkg = catalog["packages"][0]
    for key in (
        "component",
        "package_revision",
        "runtime_id",
        "component_api",
        "min_manager_version",
        "platform_tag",
        "target",
        "sha256",
        "length",
    ):
        assert key in pkg


def test_modules_do_not_import_gui_toolkits() -> None:
    for rel in (
        "tools/extension_manager/download.py",
        "tools/extension_manager/repository.py",
    ):
        tree = ast.parse((_REPO_ROOT / rel).read_text(encoding="utf-8"), filename=rel)
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module.split(".")[0])
        forbidden = {"tkinter", "Tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "qtpy"}
        assert not (set(names) & forbidden), rel


def test_semver_is_numeric_not_lexicographic() -> None:
    assert compare_semver("1.10.0", "1.9.0") > 0
    assert compare_semver("1.0.0-alpha", "1.0.0") < 0


def test_trusted_happy_path(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    blob = repo.set_standard_targets()
    client = _client(repo, tmp_path)
    result = client.refresh()
    assert result.ok
    assert result.reason_code is None
    assert result.snapshot is not None
    assert result.snapshot.change_authorized is True
    assert result.snapshot.installer_update_authorized is True
    assert result.component_install_state is None
    assert result.uninstalled is False
    assert result.manager_status is not None
    assert result.manager_status["schema"] == 1
    assert result.catalog is not None
    selected = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert selected.ok
    assert selected.package is not None
    dest = client.download_package(selected.package, tmp_path)
    assert dest.read_bytes() == blob
    assert "cache" in dest.parts
    assert "downloads" in dest.parts
    assert "site-packages" not in dest.parts
    installer = client.download_manager_installer(tmp_path)
    assert installer == manager_update_path(tmp_path, "1.2.0")
    assert installer.name == "installer-1.2.0.exe"
    root_installer = tmp_path / "installer.exe"
    assert not root_installer.exists()


def test_signature_error(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    repo.set_standard_targets()
    repo.md_timestamp.signatures.clear()
    repo.md_timestamp.sign(repo.signers["snapshot"])
    result = _client(repo, tmp_path).refresh()
    assert not result.ok
    assert result.reason_code == VERIFICATION_FAILED
    assert result.component_install_state is None
    assert result.uninstalled is False


def test_hash_error(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    repo.set_standard_targets()
    repo.target_bytes["manager-status-v1.json"] = b'{"schema":"manager-status-v1","tampered":true}'
    result = _client(repo, tmp_path).refresh()
    assert not result.ok
    assert result.reason_code == VERIFICATION_FAILED


def test_length_error(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    repo.set_standard_targets()
    original = repo.target_bytes["manager-status-v1.json"]
    repo.target_bytes["manager-status-v1.json"] = original + b"\nextra"
    result = _client(repo, tmp_path).refresh()
    assert not result.ok
    assert result.reason_code == VERIFICATION_FAILED


def test_expiry(tmp_path: Path) -> None:
    past = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=2)
    repo = LocalTUFRepo(expires=past)
    repo.set_standard_targets()
    result = _client(repo, tmp_path).refresh()
    assert not result.ok
    assert result.reason_code in {"METADATA_EXPIRED", VERIFICATION_FAILED}


def test_rollback(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    repo.set_standard_targets()
    client_dir = tmp_path
    first = _client(repo, client_dir)
    assert first.refresh().ok
    repo.target_bytes["manager-status-v1.json"] = _status_bytes(latest_manager_version="1.3.0")
    repo.publish(bump=True)
    second = _client(repo, client_dir)
    assert second.refresh().ok
    repo.md_timestamp.signed.version = 1
    repo._sign(repo.md_timestamp, "timestamp")
    third = _client(repo, client_dir)
    result = third.refresh()
    assert not result.ok
    assert result.reason_code == VERIFICATION_FAILED
    assert result.uninstalled is False


def test_revocation_persisted_and_unknown_offline(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    blob = repo.set_standard_targets()
    digest = _sha256(blob)
    online_dir = tmp_path / "online"
    online_dir.mkdir()
    client = _client(repo, online_dir)
    assert client.refresh().ok
    assert digest not in client.observed_revocation_hashes()
    trust = installed_component_may_run(digest, revocation_store=client.revocation_store)
    assert trust.may_run

    repo.set_standard_targets(
        blob=blob,
        catalog_overrides={"revoked": [{"sha256": digest, "component": "media"}]},
        bump=True,
    )
    later = _client(repo, online_dir)
    assert later.refresh().ok
    assert digest in later.observed_revocation_hashes()
    selected = later.select_package("media", CORE, platform_tag=PLATFORM)
    assert not selected.ok
    assert selected.reason_code == NO_COMPATIBLE_PACKAGE
    trust_after = installed_component_may_run(digest, revocation_store=later.revocation_store)
    assert not trust_after.may_run
    assert trust_after.reason_code == TARGET_REVOKED

    fresh_offline = tmp_path / "never-saw-revocation"
    fresh_offline.mkdir()
    unseen = installed_component_may_run(
        digest,
        revocation_store=fresh_offline / "observed-revocations.json",
    )
    assert unseen.may_run, "offline must not invent unknown revocations"


def test_root_rotation(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    repo.set_standard_targets()
    client_dir = tmp_path
    assert _client(repo, client_dir).refresh().ok
    repo.rotate_root()
    result = _client(repo, client_dir).refresh()
    assert result.ok
    assert result.manager_status is not None


def test_clock_skew(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    repo = LocalTUFRepo(expires=now + timedelta(minutes=20))
    repo.set_standard_targets()
    import tuf.ngclient._internal.trusted_metadata_set as trusted_set

    class _Clock:
        timezone = timezone

        class datetime(datetime):
            @classmethod
            def now(cls, tz: Any = None) -> datetime:
                value = now + timedelta(hours=2)
                return value if tz is None else value.astimezone(tz)

    monkeypatch.setattr(trusted_set, "datetime", _Clock)
    result = _client(repo, tmp_path).refresh()
    assert not result.ok
    assert result.reason_code in {"METADATA_EXPIRED", VERIFICATION_FAILED}

    class _InsideWindow:
        timezone = timezone

        class datetime(datetime):
            @classmethod
            def now(cls, tz: Any = None) -> datetime:
                value = now + timedelta(minutes=5)
                return value if tz is None else value.astimezone(tz)

    monkeypatch.setattr(trusted_set, "datetime", _InsideWindow)
    ok = _client(repo, tmp_path / "inside").refresh()
    assert ok.ok


def test_wrong_arch(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    blob = b"arm-only"
    repo.set_standard_targets(
        blob=blob,
        extra_packages=[],
        catalog=_catalog_bytes([_media_package(blob, platform_tag="win-arm64", target="packages/media-3.bin")]),
    )
    client = _client(repo, tmp_path)
    assert client.refresh().ok
    selected = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert not selected.ok
    assert selected.reason_code == NO_COMPATIBLE_PACKAGE


def test_no_matching_package(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    blob = b"other-runtime"
    repo.set_standard_targets(
        blob=blob,
        catalog=_catalog_bytes(
            [_media_package(blob, runtime_id="cpython-3.11-win-amd64-numpy-1")]
        ),
    )
    client = _client(repo, tmp_path)
    assert client.refresh().ok
    selected = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert not selected.ok
    assert selected.reason_code == NO_COMPATIBLE_PACKAGE


def test_catalog_cannot_add_undeclared_capability() -> None:
    blob = b"ghost"
    catalog = json.loads(
        _catalog_bytes(
            [
                _media_package(blob),
                _media_package(
                    blob,
                    component="ghost",
                    component_api="ghost-api-1",
                    target="packages/ghost.bin",
                ),
            ]
        )
    )
    selected = select_compatible_package(
        catalog,
        component="ghost",
        runtime_id=RUNTIME_ID,
        component_api="ghost-api-1",
        manager_version="1.0.0",
        platform_tag=PLATFORM,
        core_capabilities={"media": MEDIA_API},
    )
    assert not selected.ok
    assert selected.reason_code == NO_COMPATIBLE_PACKAGE


def test_old_catalog_vs_new_catalog(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    repo.set_standard_targets()
    old = _client(repo, tmp_path / "old")
    result = old.refresh()
    assert result.ok
    assert result.catalog is not None
    assert result.catalog["schema"] == COMPONENT_CATALOG_V1_SCHEMA

    repo.set_standard_targets(
        catalog=_catalog_bytes([], schema="component-catalog-v2", protocol_major=2),
        status_overrides={
            "minimum_supported_manager_version": "2.0.0",
            "latest_manager_version": "2.0.0",
        },
        bump=True,
    )
    newer = _client(repo, tmp_path / "new-schema", manager_version="1.0.0")
    blocked = newer.refresh()
    assert not blocked.ok
    assert blocked.manager_status is not None
    assert blocked.manager_status["schema"] == 1
    assert blocked.manager_status["minimum_supported_manager_version"] == "2.0.0"
    assert blocked.reason_code == MANAGER_TOO_OLD
    assert blocked.catalog is None


def test_discover_min_manager_then_reject_new_schema(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    repo.set_standard_targets(
        status_overrides={
            "minimum_supported_manager_version": "3.1.0",
            "latest_manager_version": "3.1.0",
            "help_page": "https://example.test/help/manager-update",
        },
        catalog=_catalog_bytes([], schema="component-catalog-v2", protocol_major=2),
    )
    result = _client(repo, tmp_path, manager_version="1.4.0").refresh()
    assert result.manager_status is not None
    assert result.manager_status["help_page"]
    assert result.manager_status["minimum_supported_manager_version"] == "3.1.0"
    assert result.reason_code == MANAGER_TOO_OLD
    assert result.catalog is None


def test_manager_too_old_for_matching_package() -> None:
    blob = b"needs-manager-2"
    catalog = json.loads(
        _catalog_bytes([_media_package(blob, min_manager_version="2.0.0")])
    )
    selected = select_compatible_package(
        catalog,
        component="media",
        runtime_id=RUNTIME_ID,
        component_api=MEDIA_API,
        manager_version="1.0.0",
        platform_tag=PLATFORM,
        core_capabilities=CORE["capabilities"],
    )
    assert not selected.ok
    assert selected.reason_code == MANAGER_TOO_OLD


def test_protocol_unsupported_catalog(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    repo.set_standard_targets(
        catalog=_catalog_bytes([], schema="component-catalog-v2", protocol_major=2),
        status_overrides={"minimum_supported_manager_version": "1.0.0"},
    )
    result = _client(repo, tmp_path).refresh()
    assert result.manager_status is not None
    assert result.reason_code == PROTOCOL_UNSUPPORTED
    assert result.catalog is None


def test_offline_bundle_same_trust_chain(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    blob = repo.set_standard_targets()
    bundle = tmp_path / "bundle"
    repo.write_offline_bundle(bundle)
    client = RepositoryClient.from_offline_bundle(
        bundle,
        metadata_cache_dir=tmp_path / "offline-cache",
        bootstrap_root=repo.signed_roots[1],
        manager_version="1.0.0",
        revocation_store=tmp_path / "offline-revocations.json",
    )
    result = client.refresh()
    assert result.ok
    selected = client.select_package("media", CORE, platform_tag=PLATFORM)
    dest = client.download_package(selected.package, tmp_path / "app")  # type: ignore[arg-type]
    assert dest.read_bytes() == blob


def test_expired_offline_bundle_blocks_new_install_not_installed_runtime(tmp_path: Path) -> None:
    past = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=1)
    repo = LocalTUFRepo(expires=past)
    blob = repo.set_standard_targets()
    bundle = tmp_path / "expired-bundle"
    repo.write_offline_bundle(bundle)
    client = RepositoryClient.from_offline_bundle(
        bundle,
        metadata_cache_dir=tmp_path / "expired-cache",
        bootstrap_root=repo.signed_roots[1],
        manager_version="1.0.0",
        revocation_store=tmp_path / "expired-revocations.json",
    )
    result = client.refresh()
    assert not result.ok
    assert result.reason_code in {METADATA_EXPIRED, VERIFICATION_FAILED}
    selected = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert not selected.ok
    assert selected.reason_code in {METADATA_EXPIRED, VERIFICATION_FAILED}
    with pytest.raises(ExtensionRepositoryError) as caught:
        client.download_package(_media_package(blob), tmp_path / "app")
    assert caught.value.reason_code in {METADATA_EXPIRED, VERIFICATION_FAILED}
    already = installed_component_may_run(
        _sha256(blob),
        revocation_store=tmp_path / "expired-revocations.json",
    )
    assert already.may_run
    assert already.required_fresh_metadata is False


def test_network_failure_is_not_not_installed(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    repo.set_standard_targets()
    sentinel = tmp_path / "extensions" / "store" / "keep-me.txt"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("installed", encoding="utf-8")
    client = _client(repo, tmp_path)
    assert isinstance(client.fetcher, RepoFetcher)
    client.fetcher.fail_names.add("timestamp.json")
    result = client.refresh()
    assert not result.ok
    assert result.reason_code == NETWORK_CHECK_FAILED
    assert result.component_install_state != "not_installed"
    assert result.component_install_state is None
    assert result.uninstalled is False
    assert sentinel.read_text(encoding="utf-8") == "installed"


def test_redirect_policy_rejects_http_and_foreign_hosts() -> None:
    policy = DownloadPolicy(trusted_origins=("example.test",), require_https=True)
    with pytest.raises(DownloadPolicyError):
        assert_https_trusted_url("http://example.test/file.bin", policy.trusted_origins)
    with pytest.raises(DownloadPolicyError):
        resolve_redirect_url(
            "https://example.test/a",
            "http://example.test/b",
            policy,
            hop=1,
        )
    with pytest.raises(DownloadPolicyError):
        resolve_redirect_url(
            "https://example.test/a",
            "https://evil.test/b",
            policy,
            hop=1,
        )
    allowed = resolve_redirect_url(
        "https://example.test/a",
        "https://example.test/cache/b.bin",
        policy,
        hop=1,
    )
    assert allowed == "https://example.test/cache/b.bin"


class _ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _serve(handler_cls: type[http.server.BaseHTTPRequestHandler]) -> tuple[_ThreadedServer, str]:
    server = _ThreadedServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}"


def test_disconnect_cancel_and_part_reuse(tmp_path: Path) -> None:
    body = b"ABCDEFGH" * 2048
    digest = _sha256(body)
    state = {"requests": 0, "gate": threading.Event()}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            state["requests"] += 1
            if self.path.endswith("/cancel"):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body[:64])
                state["gate"].wait(2.0)
                return
            range_header = self.headers.get("Range")
            if range_header:
                start = int(range_header.split("=")[1].split("-")[0])
                chunk = body[start:]
                self.send_response(206)
                self.send_header("Content-Length", str(len(chunk)))
                self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
                self.end_headers()
                self.wfile.write(chunk)
                return
            if state["requests"] == 1:
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body[:100])
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server, base = _serve(Handler)
    policy = DownloadPolicy(
        trusted_origins=("127.0.0.1",),
        require_https=False,
        max_retries=3,
        retry_backoff_s=0.01,
        connect_timeout_s=2,
        read_timeout_s=2,
    )
    dest = tmp_path / "extensions" / "cache" / "downloads" / f"{digest}.bin"
    try:
        download_verified_file(
            f"{base}/pkg.bin",
            dest,
            expected_sha256=digest,
            expected_length=len(body),
            policy=policy,
            sleeper=lambda _s: None,
        )
        assert dest.read_bytes() == body
        assert not dest.with_name(dest.name + ".part").exists()

        cancel_dest = tmp_path / "extensions" / "cache" / "downloads" / "cancel.bin"
        cancel_event = threading.Event()

        class _Headers(dict):
            def get(self, name: str, default: Any = None) -> Any:
                return super().get(name, default)

        class _Response:
            status = 200

            def __init__(self) -> None:
                self._sent = False
                self.headers = _Headers({"Content-Length": str(len(body))})

            def getcode(self) -> int:
                return 200

            def info(self) -> _Headers:
                return self.headers

            def read(self, n: int = -1) -> bytes:
                if not self._sent:
                    self._sent = True
                    cancel_event.set()
                    return body[:64]
                return b""

            def close(self) -> None:
                return None

            def __enter__(self) -> _Response:
                return self

            def __exit__(self, *args: Any) -> None:
                self.close()

        with pytest.raises(DownloadCancelled):
            download_verified_file(
                "https://example.test/cancel.bin",
                cancel_dest,
                expected_sha256=digest,
                expected_length=len(body),
                policy=DownloadPolicy(trusted_origins=("example.test",), require_https=True),
                cancel_event=cancel_event,
                urlopen=lambda *args, **kwargs: _Response(),
                sleeper=lambda _s: None,
            )
        assert not cancel_dest.exists()
        assert "site-packages" not in cancel_dest.parts
        assert "store" not in cancel_dest.parts
    finally:
        server.shutdown()
        server.server_close()


def test_https_required_blocks_local_http_even_if_server_exists(tmp_path: Path) -> None:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"nope")

    server, base = _serve(Handler)
    try:
        with pytest.raises(DownloadPolicyError) as excinfo:
            download_verified_file(
                f"{base}/x.bin",
                tmp_path / "extensions" / "cache" / "downloads" / "x.bin",
                expected_sha256=_sha256(b"nope"),
                expected_length=4,
                policy=DownloadPolicy(trusted_origins=("127.0.0.1",), require_https=True),
            )
        assert excinfo.value.reason_code == VERIFICATION_FAILED
    finally:
        server.shutdown()
        server.server_close()


def test_local_path_fetcher_is_used_by_offline_helper() -> None:
    assert LocalPathFetcher.__mro__[1] is FetcherInterface


def test_repository_imports_neutral_contract_explicitly() -> None:
    source = (_REPO_ROOT / "tools" / "extension_manager" / "repository.py").read_text(
        encoding="utf-8"
    )
    assert "_load_contract" not in source
    assert "from mf4_analyzer.extensions.contract import" in source
    unpack_source = (_REPO_ROOT / "tools" / "extension_manager" / "unpack.py").read_text(
        encoding="utf-8"
    )
    assert "_verification_failed_code" not in unpack_source
    assert "from mf4_analyzer.extensions.contract import" in unpack_source


def _real_media_package() -> tuple[bytes, bytes, dict[str, Any]]:
    payload_files = {
        "site-packages/av/__init__.py": b"__version__ = '1'\n",
        "native/av/lib.bin": b"dll-bytes",
    }
    manifest = generate_package_manifest(
        component="media",
        package_revision=3,
        runtime_id=RUNTIME_ID,
        component_api=MEDIA_API,
        min_manager_version="1.0.0",
        python_tag="cp312",
        platform_tag=PLATFORM,
        module_roots=["site-packages/av"],
        dll_directories=["native/av"],
        dependency_ownership={"av": "media"},
        files=[
            {"relpath": name, "size": len(data), "sha256": _sha256(data)}
            for name, data in payload_files.items()
        ],
        max_extract_bytes=10_000,
        probe_type="media_wav_mp4_v1",
        required_features=["store_layout_v1", "native_probe_v1", "file_manifest_sha256"],
    )
    json_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("package.json", json_bytes)
        for name, data in payload_files.items():
            archive.writestr(name, data)
    zip_bytes = buf.getvalue()
    record = _media_package(
        zip_bytes,
        target="packages/media-3.zip",
        package_json_target="packages/media-3.package.json",
        package_json_sha256=_sha256(json_bytes),
        package_json_length=len(json_bytes),
    )
    return zip_bytes, json_bytes, record


def test_installer_declared_hash_must_match_tuf_target(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    repo.set_standard_targets(
        status_overrides={"installer_artifact": {"sha256": "0" * 64}},
    )
    client = _client(repo, tmp_path)
    result = client.refresh()
    assert not result.ok
    assert result.reason_code == VERIFICATION_FAILED
    with pytest.raises(ExtensionRepositoryError) as caught:
        client.download_manager_installer(tmp_path)
    assert caught.value.reason_code == VERIFICATION_FAILED


def test_download_manager_installer_rejects_injected_status(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    repo.set_standard_targets()
    client = _client(repo, tmp_path)
    assert client.refresh().ok
    bogus = dict(client._last_status or {})
    bogus["installer_sha256"] = "0" * 64
    bogus["latest_manager_version"] = "9.9.9"
    with pytest.raises(ExtensionRepositoryError) as caught:
        client.download_manager_installer(tmp_path, status=bogus)
    assert caught.value.reason_code == VERIFICATION_FAILED
    installer = client.download_manager_installer(tmp_path)
    assert installer == manager_update_path(tmp_path, "1.2.0")


def test_verified_package_chain_unpacks_real_zip(tmp_path: Path) -> None:
    zip_bytes, json_bytes, record = _real_media_package()
    repo = LocalTUFRepo()
    repo.set_standard_targets(
        blob=zip_bytes,
        catalog=_catalog_bytes([record]),
        extra_targets={
            record["target"]: zip_bytes,
            record["package_json_target"]: json_bytes,
        },
    )
    client = _client(repo, tmp_path)
    result = client.refresh()
    assert result.ok
    assert result.snapshot is not None
    assert result.snapshot.installer_sha256 == result.manager_status["installer_sha256"]
    selected = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert selected.ok and selected.package is not None
    zip_path, verified = client.download_verified_package(selected.package, tmp_path)
    assert zip_path.read_bytes() == zip_bytes
    assert verified.snapshot_id == result.snapshot.snapshot_id
    assert verified.component == "media"
    assert verified.runtime_id == RUNTIME_ID
    assert verified.package_revision == 3
    assert verified.component_api == MEDIA_API
    assert verified.zip.sha256 == _sha256(zip_bytes)
    assert verified.manifest.sha256 == _sha256(json_bytes)
    assert verified.package_json_bytes == json_bytes

    app_root, extensions = tmp_path / "app", tmp_path / "app" / "extensions"
    staging = extensions / ".staging" / "txn-verified"
    extensions.mkdir(parents=True)
    unpacked = extract_verified_package(
        zip_path,
        staging,
        extensions_root=extensions,
        verified=verified,
        app_root=app_root,
    )
    assert (unpacked.staging_dir / "package.json").read_bytes() == json_bytes
    assert (unpacked.staging_dir / "site-packages/av/__init__.py").read_bytes() == (
        b"__version__ = '1'\n"
    )


def test_independent_manifest_missing_is_rejected(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    blob = repo.set_standard_targets()
    client = _client(repo, tmp_path)
    assert client.refresh().ok
    selected = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert selected.ok and selected.package is not None
    with pytest.raises(ExtensionRepositoryError) as caught:
        client.download_verified_package(selected.package, tmp_path)
    assert caught.value.reason_code == VERIFICATION_FAILED
    assert "package.json" in str(caught.value)
    dest = client.download_package(selected.package, tmp_path)
    assert dest.read_bytes() == blob


def test_independent_manifest_mismatch_is_rejected(tmp_path: Path) -> None:
    zip_bytes, json_bytes, record = _real_media_package()
    other_json = json_bytes + b"\n"
    record = dict(record)
    record["package_json_sha256"] = _sha256(other_json)
    record["package_json_length"] = len(other_json)
    repo = LocalTUFRepo()
    repo.set_standard_targets(
        blob=zip_bytes,
        catalog=_catalog_bytes([record]),
        extra_targets={
            record["target"]: zip_bytes,
            record["package_json_target"]: json_bytes,
        },
    )
    client = _client(repo, tmp_path)
    result = client.refresh()
    assert result.ok
    selected = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert selected.ok and selected.package is not None
    with pytest.raises(ExtensionRepositoryError) as caught:
        client.download_verified_package(selected.package, tmp_path)
    assert caught.value.reason_code == VERIFICATION_FAILED


def _advance_tuf_clock(monkeypatch: pytest.MonkeyPatch, now: datetime, delta: timedelta) -> None:
    import tuf.ngclient._internal.trusted_metadata_set as trusted_set

    class _Clock:
        timezone = timezone

        class datetime(datetime):
            @classmethod
            def now(cls, tz: Any = None) -> datetime:
                value = now + delta
                return value if tz is None else value.astimezone(tz)

    monkeypatch.setattr(trusted_set, "datetime", _Clock)


def test_failed_refresh_revokes_select_and_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    repo = LocalTUFRepo(expires=now + timedelta(minutes=20))
    blob = repo.set_standard_targets()
    client = _client(repo, tmp_path)
    first = client.refresh()
    assert first.ok
    assert first.snapshot is not None
    assert first.snapshot.change_authorized is True
    selected = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert selected.ok and selected.package is not None
    assert client.download_package(selected.package, tmp_path / "before").read_bytes() == blob

    _advance_tuf_clock(monkeypatch, now, timedelta(hours=2))
    second = client.refresh()
    assert not second.ok
    assert second.reason_code == METADATA_EXPIRED
    assert second.manager_status is not None
    assert second.snapshot is not None
    assert second.snapshot.change_authorized is False
    assert second.snapshot.installer_update_authorized is False
    assert second.catalog is not None

    later = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert not later.ok
    assert later.reason_code == METADATA_EXPIRED
    with pytest.raises(ExtensionRepositoryError) as caught:
        client.download_package(selected.package, tmp_path / "after")
    assert caught.value.reason_code == METADATA_EXPIRED
    with pytest.raises(ExtensionRepositoryError) as installer_caught:
        client.download_manager_installer(tmp_path / "after")
    assert installer_caught.value.reason_code == METADATA_EXPIRED


def test_refresh_revocation_rejects_old_selection(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    blob = repo.set_standard_targets()
    client = _client(repo, tmp_path)
    first = client.refresh()
    assert first.ok
    selected = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert selected.ok and selected.package is not None
    old_package = dict(selected.package)
    assert client.download_package(old_package, tmp_path / "before").read_bytes() == blob

    repo.set_standard_targets(
        blob=blob,
        catalog_overrides={"revoked": [{"sha256": _sha256(blob), "component": "media"}]},
        bump=True,
    )
    later = client.refresh()
    assert later.ok
    assert later.snapshot is not None
    assert later.snapshot.change_authorized is True
    blocked = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert not blocked.ok
    with pytest.raises(ExtensionRepositoryError) as caught:
        client.download_package(old_package, tmp_path / "after")
    assert caught.value.reason_code == TARGET_REVOKED


def test_manager_minimum_bump_blocks_component_changes(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    blob = repo.set_standard_targets()
    client = _client(repo, tmp_path, manager_version="1.0.0")
    first = client.refresh()
    assert first.ok
    selected = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert selected.ok and selected.package is not None

    repo.set_standard_targets(
        blob=blob,
        status_overrides={
            "minimum_supported_manager_version": "9.0.0",
            "latest_manager_version": "9.0.0",
        },
        bump=True,
    )
    later = client.refresh()
    assert not later.ok
    assert later.reason_code == MANAGER_TOO_OLD
    assert later.manager_status is not None
    assert later.snapshot is not None
    assert later.snapshot.change_authorized is False
    blocked = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert not blocked.ok
    assert blocked.reason_code == MANAGER_TOO_OLD
    with pytest.raises(ExtensionRepositoryError) as caught:
        client.download_package(selected.package, tmp_path / "after")
    assert caught.value.reason_code == MANAGER_TOO_OLD


def test_unknown_catalog_still_shows_verified_update_status(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    repo.set_standard_targets(
        catalog=_catalog_bytes([], schema="component-catalog-v2", protocol_major=2),
        status_overrides={
            "minimum_supported_manager_version": "9.0.0",
            "latest_manager_version": "9.0.0",
            "help_page": "https://example.test/help/manager-update",
        },
    )
    client = _client(repo, tmp_path, manager_version="1.0.0")
    result = client.refresh()
    assert not result.ok
    assert result.reason_code == MANAGER_TOO_OLD
    assert result.catalog is None
    assert result.manager_status is not None
    assert result.manager_status["help_page"]
    assert result.manager_status["minimum_supported_manager_version"] == "9.0.0"
    assert result.snapshot is not None
    assert result.snapshot.change_authorized is False
    selected = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert not selected.ok
    assert selected.reason_code == MANAGER_TOO_OLD


def test_old_manager_can_download_installer_not_components(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    blob = repo.set_standard_targets(
        status_overrides={
            "minimum_supported_manager_version": "9.0.0",
            "latest_manager_version": "1.2.0",
            "help_page": "https://example.test/help/manager-update",
        },
    )
    client = _client(repo, tmp_path, manager_version="1.0.0")
    result = client.refresh()
    assert not result.ok
    assert result.reason_code == MANAGER_TOO_OLD
    assert result.snapshot is not None
    assert result.snapshot.change_authorized is False
    assert result.snapshot.installer_update_authorized is True
    selected = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert not selected.ok
    assert selected.reason_code == MANAGER_TOO_OLD
    with pytest.raises(ExtensionRepositoryError) as caught:
        client.download_package(_media_package(blob), tmp_path)
    assert caught.value.reason_code == MANAGER_TOO_OLD
    installer = client.download_manager_installer(tmp_path)
    assert installer == manager_update_path(tmp_path, "1.2.0")
    assert installer.is_file()


def test_metadata_expiry_during_download_rejects_without_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    expires = now + timedelta(minutes=20)
    repo = LocalTUFRepo(expires=expires)
    blob = repo.set_standard_targets()
    client = _client(repo, tmp_path)
    result = client.refresh()
    assert result.ok
    selected = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert selected.ok and selected.package is not None
    monkeypatch.setattr(
        "tools.extension_manager.repository.utcnow",
        lambda: expires + timedelta(seconds=1),
    )
    with pytest.raises(ExtensionRepositoryError) as requalify:
        client.requalify_after_lock_wait()
    assert requalify.value.reason_code == METADATA_EXPIRED
    with pytest.raises(ExtensionRepositoryError) as caught:
        client.download_package(selected.package, tmp_path)
    assert caught.value.reason_code == METADATA_EXPIRED
    assert client._snapshot is not None
    assert client._snapshot.change_authorized is False
    later = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert not later.ok
    assert later.reason_code == METADATA_EXPIRED
    assert blob


def test_valid_offline_bundle_authorizes_component_download(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    blob = repo.set_standard_targets()
    bundle = tmp_path / "valid-bundle"
    repo.write_offline_bundle(bundle)
    client = RepositoryClient.from_offline_bundle(
        bundle,
        metadata_cache_dir=tmp_path / "valid-offline-cache",
        bootstrap_root=repo.signed_roots[1],
        manager_version="1.0.0",
        revocation_store=tmp_path / "valid-offline-revocations.json",
    )
    result = client.refresh()
    assert result.ok
    assert result.snapshot is not None
    assert result.snapshot.change_authorized is True
    selected = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert selected.ok and selected.package is not None
    dest = client.download_package(selected.package, tmp_path / "app")
    assert dest.read_bytes() == blob


def test_installed_component_runs_offline_without_fresh_metadata(tmp_path: Path) -> None:
    digest = _sha256(b"already-installed-media")
    store = tmp_path / "never-refreshed" / "observed-revocations.json"
    trust = installed_component_may_run(digest, revocation_store=store)
    assert trust.may_run
    assert trust.required_fresh_metadata is False
    assert trust.reason_code is None


def test_corrupt_revocation_cache_is_diagnostic_not_empty(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    blob = repo.set_standard_targets()
    client = _client(repo, tmp_path)
    first = client.refresh()
    assert first.ok
    selected = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert selected.ok and selected.package is not None

    client.revocation_store.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ExtensionRepositoryError) as loaded:
        load_observed_revocations(client.revocation_store)
    assert loaded.value.reason_code == REVOCATION_CACHE_CORRUPT
    trust = installed_component_may_run(_sha256(blob), revocation_store=client.revocation_store)
    assert not trust.may_run
    assert trust.reason_code == REVOCATION_CACHE_CORRUPT
    blocked = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert not blocked.ok
    assert blocked.reason_code == REVOCATION_CACHE_CORRUPT
    with pytest.raises(ExtensionRepositoryError) as caught:
        client.download_package(selected.package, tmp_path)
    assert caught.value.reason_code == REVOCATION_CACHE_CORRUPT


def test_download_does_not_reclassify_programming_errors(tmp_path: Path) -> None:
    dest = tmp_path / "extensions" / "cache" / "downloads" / "x.bin"

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise TypeError("urlopen signature is wrong")

    with pytest.raises(TypeError, match="urlopen signature is wrong"):
        download_verified_file(
            "https://example.test/x.bin",
            dest,
            expected_sha256=_sha256(b"x"),
            expected_length=1,
            policy=DownloadPolicy(trusted_origins=("example.test",), require_https=True),
            urlopen=boom,
            sleeper=lambda _s: None,
        )


def test_resume_uses_etag_if_range_and_content_range(tmp_path: Path) -> None:
    body = b"ABCDEFGH" * 1024
    digest = _sha256(body)
    etag = '"pkg-v1"'
    state: dict[str, Any] = {"requests": 0, "if_range": [], "ranges": []}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            state["requests"] += 1
            state["if_range"].append(self.headers.get("If-Range"))
            range_header = self.headers.get("Range")
            state["ranges"].append(range_header)
            if range_header:
                start = int(range_header.split("=")[1].split("-")[0])
                chunk = body[start:]
                self.send_response(206)
                self.send_header("Content-Length", str(len(chunk)))
                self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
                self.send_header("ETag", etag)
                self.end_headers()
                self.wfile.write(chunk)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("ETag", etag)
            self.end_headers()
            self.wfile.write(body[:120])

    server, base = _serve(Handler)
    policy = DownloadPolicy(
        trusted_origins=("127.0.0.1",),
        require_https=False,
        max_retries=3,
        retry_backoff_s=0.01,
        connect_timeout_s=2,
        read_timeout_s=2,
    )
    dest = tmp_path / "extensions" / "cache" / "downloads" / f"{digest}.bin"
    try:
        download_verified_file(
            f"{base}/pkg.bin",
            dest,
            expected_sha256=digest,
            expected_length=len(body),
            policy=policy,
            sleeper=lambda _s: None,
        )
        assert dest.read_bytes() == body
        assert state["requests"] >= 2
        assert etag in {item for item in state["if_range"] if item}
        assert any(item and item.startswith("bytes=") for item in state["ranges"])
    finally:
        server.shutdown()
        server.server_close()


def test_wrong_content_range_discards_part_and_redownloads(tmp_path: Path) -> None:
    body = b"ABCDEFGH" * 256
    digest = _sha256(body)
    state = {"requests": 0}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            state["requests"] += 1
            range_header = self.headers.get("Range")
            if range_header and state["requests"] == 2:
                self.send_response(206)
                self.send_header("Content-Length", "11")
                self.send_header("Content-Range", "bytes 0-10/11")
                self.send_header("ETag", '"other"')
                self.end_headers()
                self.wfile.write(b"wrong-range")
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("ETag", '"pkg-v1"')
            self.end_headers()
            if state["requests"] == 1:
                self.wfile.write(body[:80])
                return
            self.wfile.write(body)

    server, base = _serve(Handler)
    policy = DownloadPolicy(
        trusted_origins=("127.0.0.1",),
        require_https=False,
        max_retries=3,
        retry_backoff_s=0.01,
        connect_timeout_s=2,
        read_timeout_s=2,
    )
    dest = tmp_path / "extensions" / "cache" / "downloads" / f"{digest}.bin"
    try:
        download_verified_file(
            f"{base}/pkg.bin",
            dest,
            expected_sha256=digest,
            expected_length=len(body),
            policy=policy,
            sleeper=lambda _s: None,
        )
        assert dest.read_bytes() == body
        assert not dest.with_name(dest.name + ".part").exists()
        assert state["requests"] >= 3
    finally:
        server.shutdown()
        server.server_close()


def test_refresh_cancel_is_not_a_network_failure(tmp_path: Path) -> None:
    repo = LocalTUFRepo()
    repo.set_standard_targets()
    client = _client(repo, tmp_path)
    first = client.refresh()
    assert first.ok
    selected = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert selected.ok

    class _CancelFetcher(FetcherInterface):
        def _fetch(self, url: str):  # type: ignore[override]
            raise DownloadCancelled("metadata fetch cancelled")

    client.fetcher = _CancelFetcher()
    result = client.refresh()
    assert not result.ok
    assert result.reason_code == DOWNLOAD_CANCELLED
    assert result.snapshot is not None
    assert result.snapshot.change_authorized is False
    blocked = client.select_package("media", CORE, platform_tag=PLATFORM)
    assert not blocked.ok
    assert blocked.reason_code == DOWNLOAD_CANCELLED


def test_real_repository_engine_boundary_selects_verified_package(tmp_path):
    from tests.test_extension_transaction import _write_core, _make_verified_zip
    from mf4_analyzer.extensions.locking import MemoryLockBackend
    from tools.extension_manager.engine import InstallEngine
    from tools.extension_manager.transaction import TransactionHooks

    root = tmp_path / 'TraceLab'
    _write_core(root)
    source = _make_verified_zip(tmp_path, 'media')
    package = source.verified
    record = _media_package(source.zip_path.read_bytes(),
        target=package.zip.target, sha256=package.zip.sha256, length=package.zip.length,
        runtime_id=package.runtime_id, component_api=package.component_api,
        python_tag=package.package.python_tag, platform_tag=package.package.platform_tag,
        package_json_target=package.manifest.target,
        package_json_sha256=package.manifest.sha256,
        package_json_length=package.manifest.length)
    repo = LocalTUFRepo()
    repo.set_standard_targets(catalog=_catalog_bytes([record]), extra_targets={
        package.zip.target: source.zip_path.read_bytes(),
        package.manifest.target: package.package_json_bytes,
    })
    client = _client(repo, tmp_path)
    assert client.refresh().ok
    engine = InstallEngine(root, lock_backend=MemoryLockBackend())
    # This test proves the real trust/download/transaction boundary. Native
    # decoding is covered separately; only the child runner is substituted.
    hooks = TransactionHooks(probe_runner=lambda *args, **kwargs: {'ok': True})
    result = engine.install_from_repository(client, ['media'], hooks=hooks)
    assert result.outcome == 'installed'
    assert result.active['by_runtime'][package.runtime_id]['media']['package_sha256'] == package.zip.sha256


def test_manager_offline_entry_uses_bundled_trust_and_real_repository(tmp_path):
    from tools.extension_manager.app import ManagerPresenter
    from tools.extension_manager.engine import InstallEngine
    from tools.extension_manager.transaction import TransactionHooks
    from mf4_analyzer.extensions.locking import MemoryLockBackend
    from tests.test_extension_transaction import _write_core, _make_verified_zip

    root = tmp_path / 'TraceLab'
    _write_core(root)
    source = _make_verified_zip(tmp_path, 'media')
    pkg = source.verified
    record = _media_package(source.zip_path.read_bytes(), target=pkg.zip.target,
        runtime_id=pkg.runtime_id, component_api=pkg.component_api,
        python_tag=pkg.package.python_tag, platform_tag=pkg.package.platform_tag,
        package_json_target=pkg.manifest.target,
        package_json_sha256=pkg.manifest.sha256, package_json_length=pkg.manifest.length)
    repo = LocalTUFRepo()
    repo.set_standard_targets(catalog=_catalog_bytes([record]), extra_targets={
        pkg.zip.target: source.zip_path.read_bytes(), pkg.manifest.target: pkg.package_json_bytes})
    bundle = tmp_path / 'offline'
    repo.write_offline_bundle(bundle)
    config = tmp_path / 'repository.json'
    (tmp_path / 'root.json').write_bytes(repo.md_root.to_bytes())
    config.write_text(json.dumps({'schema': 1, 'bootstrap_root': 'root.json',
        'metadata_base_url': 'https://example.test/metadata/',
        'target_base_url': 'https://example.test/targets/', 'trusted_origins': ['example.test']}))
    engine = InstallEngine(root, lock_backend=MemoryLockBackend())
    presenter = ManagerPresenter(root, engine=engine, repository_config=config)
    online = presenter._try_make_repository()
    assert isinstance(online, RepositoryClient)
    assert online.cancel_event is presenter._cancel
    from mf4_analyzer.extensions.revocations import revocation_store_path
    assert online.revocation_store == revocation_store_path(root)
    hooks = TransactionHooks(probe_runner=lambda *args, **kwargs: {'ok': True})
    result = presenter.run_local_install(str(bundle), components=['media'], hooks=hooks)
    assert result.outcome == 'installed'
    assert presenter.repository is None  # offline authorization does not bless online state


def test_engine_preserves_repository_specific_failure_reason(tmp_path):
    from tools.extension_manager.engine import InstallEngine
    from tests.test_extension_transaction import _write_core

    root = tmp_path / "TraceLab"
    _write_core(root)
    repo = LocalTUFRepo()
    repo.set_standard_targets()
    client = _client(repo, tmp_path)
    assert client.refresh().ok
    client.revocation_store.write_text("{bad-json", encoding="utf-8")
    with pytest.raises(ExtensionRepositoryError) as caught:
        InstallEngine(root).install_from_repository(client, ["media"])
    assert caught.value.reason_code == REVOCATION_CACHE_CORRUPT
