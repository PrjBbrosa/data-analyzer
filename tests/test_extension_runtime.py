"""Runtime identity, availability, and lease.  Frozen WAV/MP4 remains UNKNOWN."""
from __future__ import annotations

from pathlib import Path

from mf4_analyzer.extensions.locking import MemoryLockBackend
from mf4_analyzer.extensions.runtime import (
    MODE_MODULAR,
    MODE_SOURCE,
    STATUS_NOT_INSTALLED,
    STATUS_REPAIR_REQUIRED,
    WINDOWS_FROZEN_MEDIA_READ,
    detect_runtime_mode,
    identify_core,
    load_runtime,
    transaction_log_path,
    write_json_atomic,
)
from tests.test_extension_transaction import RUNTIME_ID, _write_core


def test_source_mode_does_not_load_extensions_by_default(tmp_path: Path):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    snapshot = load_runtime(app_root, acquire_lease=False, frozen=False)
    assert snapshot.mode == MODE_SOURCE
    assert snapshot.availability("media").status == STATUS_NOT_INSTALLED
    assert snapshot.core is None


def test_identify_core_binds_envelope_and_exe(tmp_path: Path):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    identity = identify_core(app_root)
    assert identity.exe_relpath == "TraceLabAnalyzer.exe"
    assert identity.runtime_id == RUNTIME_ID


def test_modular_mode_requires_install_id(tmp_path: Path):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    (app_root / "extensions" / "install-id").write_text("abc\n", encoding="utf-8")
    assert detect_runtime_mode(frozen=True, app_root=app_root) == MODE_MODULAR


def test_in_progress_transaction_is_repair_required_not_ready(tmp_path: Path):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    write_json_atomic(
        transaction_log_path(app_root),
        {
            "schema": 1,
            "transaction_id": "txn-open",
            "stage": "probed",
            "core_build_id": "cb1-7a5bcf9b9578af84aac82757fffe8d981c5c585e5a46a0401e226587db1e2216",
            "runtime_id": RUNTIME_ID,
            "old_active_generation": 0,
            "old_active_sha256": "ee" * 32,
            "new_active_generation": 1,
            "package_hashes": ["dd" * 32],
            "cleanup_pending": [],
            "affected_components": ["media"],
            "repair_required": False,
        },
    )
    snapshot = load_runtime(
        app_root,
        lock_backend=MemoryLockBackend(),
        frozen=True,
        use_extensions=True,
    )
    assert snapshot.repair_required
    assert snapshot.availability("media").status == STATUS_REPAIR_REQUIRED


def test_frozen_exe_wav_mp4_read_is_unknown():
    assert WINDOWS_FROZEN_MEDIA_READ == "UNKNOWN"
    assert detect_runtime_mode(frozen=True, use_extensions=False) == "bundled"


def test_startup_consumes_persisted_revocation_without_repository_import(tmp_path):
    from tests.test_extension_transaction import _engine, _make_verified_zip

    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    backend = MemoryLockBackend()
    media = _make_verified_zip(tmp_path, "media")
    assert _engine(app_root, backend).install([media]).outcome == "installed"
    write_json_atomic(
        app_root / "extensions/cache/metadata/observed-revocations.json",
        {"schema": "observed-revocations-v1", "items": [
            {"sha256": media.verified.zip.sha256, "component": "media"}
        ]},
    )
    snapshot = load_runtime(app_root, frozen=True, lock_backend=backend)
    try:
        assert snapshot.availability("media").status == "revoked"
        assert not snapshot.planned.module_roots
    finally:
        snapshot.lease.release()


def test_corrupt_revocation_cache_is_not_treated_as_empty(tmp_path):
    import pytest
    from mf4_analyzer.extensions.contract import ExtensionError

    _write_core(tmp_path)
    path = tmp_path / "extensions/cache/metadata/observed-revocations.json"
    path.parent.mkdir(parents=True)
    path.write_text("{bad-json", encoding="utf-8")
    with pytest.raises(ExtensionError, match="revocation cache"):
        load_runtime(tmp_path, frozen=True, acquire_lease=False)
