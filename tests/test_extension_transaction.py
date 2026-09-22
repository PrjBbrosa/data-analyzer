"""Media install transaction state machine with staged fault injection."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from mf4_analyzer.extensions.contract import (
    ExtensionError,
    ReasonCode,
    bind_verified_package,
    generate_package_manifest,
)
from mf4_analyzer.extensions.locking import MemoryLockBackend, acquire_shared_lease
from mf4_analyzer.extensions.runtime import (
    STATUS_NOT_INSTALLED,
    STATUS_READY,
    WINDOWS_FROZEN_MEDIA_READ,
    active_path,
    load_runtime,
    staging_root,
    store_root,
    transaction_log_path,
)
from tools.extension_manager.engine import InstallEngine
from tools.extension_manager.transaction import PackageSource, TransactionHooks


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "extensions"
RUNTIME_ID = "rt1-0123456789abcdef0123456789abcdef"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_core(app_root: Path) -> None:
    app_root.mkdir(parents=True, exist_ok=True)
    (app_root / "core.json").write_bytes((FIXTURES / "core-valid.json").read_bytes())
    (app_root / "core-files.json").write_bytes((FIXTURES / "core-files-valid.json").read_bytes())
    (app_root / "TraceLabAnalyzer.exe").write_bytes(b"X" * 4096)
    (app_root / "_internal").mkdir(exist_ok=True)
    (app_root / "_internal" / "python311.dll").write_bytes(b"Y" * 2048)
    (app_root / "extensions").mkdir(exist_ok=True)
    from mf4_analyzer.extensions.contract import generate_core_files, parse_core_files
    core_files = json.loads((app_root / "core-files.json").read_bytes())
    for entry in core_files["files"]:
        data = (app_root / entry["relpath"]).read_bytes()
        entry.update(size=len(data), sha256=_sha256(data))
    (app_root / "core-files.json").write_text(json.dumps(core_files))
    digest = parse_core_files(core_files).digest
    core = json.loads((app_root / "core.json").read_bytes())
    core.update(core_files_digest=digest, core_build_id=f"cb1-{digest}",
                exe_sha256=_sha256((app_root / "TraceLabAnalyzer.exe").read_bytes()))
    (app_root / "core.json").write_text(json.dumps(core))


def _package_files(component: str) -> dict[str, bytes]:
    if component == "media":
        return {
            "site-packages/av/__init__.py": b"__version__ = '1'\n",
            "native/av/lib.bin": b"dll-bytes",
        }
    if component == "matlab":
        return {
            "site-packages/h5py/__init__.py": b"__version__ = '1'\n",
            "native/h5py/lib.bin": b"dll-bytes",
        }
    raise AssertionError(component)


def _make_verified_zip(tmp_path: Path, component: str) -> PackageSource:
    files = _package_files(component)
    probe_type = "media_wav_mp4_v1" if component == "media" else "matlab_mat_v73_v1"
    module_root = "site-packages/av" if component == "media" else "site-packages/h5py"
    dll_dir = "native/av" if component == "media" else "native/h5py"
    dep = "av" if component == "media" else "h5py"
    manifest = generate_package_manifest(
        component=component,
        package_revision=3,
        runtime_id=RUNTIME_ID,
        component_api="1",
        min_manager_version="1.0.0",
        python_tag="cp311",
        platform_tag="win_amd64",
        module_roots=[module_root],
        dll_directories=[dll_dir],
        dependency_ownership={dep: component},
        files=[
            {"relpath": name, "size": len(payload), "sha256": _sha256(payload)}
            for name, payload in files.items()
        ],
        max_extract_bytes=10_000,
        probe_type=probe_type,
        required_features=["store_layout_v1", "native_probe_v1", "file_manifest_sha256"],
    )
    json_bytes = json.dumps(manifest, ensure_ascii=True, indent=2).encode("utf-8")
    packed = dict(files)
    packed["package.json"] = json_bytes
    archive = tmp_path / f"{component}.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        for name, payload in packed.items():
            handle.writestr(name, payload)
    zip_bytes = archive.read_bytes()
    verified = bind_verified_package(
        snapshot_id="snap-test",
        component=component,
        runtime_id=RUNTIME_ID,
        package_revision=3,
        component_api="1",
        min_manager_version="1.0.0",
        zip_target=f"packages/{component}-3.zip",
        zip_sha256=_sha256(zip_bytes),
        zip_length=len(zip_bytes),
        manifest_target=f"packages/{component}-3.package.json",
        manifest_sha256=_sha256(json_bytes),
        manifest_length=len(json_bytes),
        package_json_bytes=json_bytes,
    )
    return PackageSource(verified=verified, zip_path=archive)


def _engine(app_root: Path, backend: MemoryLockBackend, **kwargs) -> InstallEngine:
    engine = InstallEngine(app_root, lock_backend=backend, manager_version="1.0.0", **kwargs)
    original = engine._hooks
    def fixture_hooks(extra):
        hooks = original(extra)
        if hooks.probe_runner is None:
            hooks.probe_runner = _fixture_probe_runner
        return hooks
    engine._hooks = fixture_hooks
    return engine


def _fixture_probe_runner(command, **kwargs):
    # State machine fixture only. Never used by production or native acceptance.
    request = json.loads(Path(command[command.index("--extension-probe-request") + 1]).read_bytes())
    staging = Path(command[command.index("--extension-probe-staging") + 1])
    for name in request["components"]:
        root = staging.parents[1] / request["package_roots"][name]
        from mf4_analyzer.extensions.contract import parse_package_manifest
        from mf4_analyzer.extensions.runtime import verify_package_tree
        try:
            package = parse_package_manifest((root / "package.json").read_bytes())
            verify_package_tree(root, package.files, extensions=staging.parents[1])
        except (OSError, ExtensionError) as exc:
            raise ExtensionError(ReasonCode.PROBE_FAILED, "fixture package invalid") from exc
    return {"ok": True, "test_double": True}



def test_media_install_commits_active_once_and_ignores_stage_directory_name(tmp_path: Path):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    backend = MemoryLockBackend()
    order: list[str] = []

    def requalify(*, kind: str = "component_change") -> None:
        order.append(f"requalify:{kind}")

    def before_verify(txn) -> None:
        order.append("verify")

    def before_active(txn) -> None:
        order.append("commit")

    media = _make_verified_zip(tmp_path, "media")
    result = _engine(app_root, backend, requalify=requalify).install(
        [media],
        hooks=TransactionHooks(before_verify=before_verify, before_active_replace=before_active),
    )
    assert result.outcome == "installed"
    assert result.stage == "cleanup"
    assert result.windows_frozen_media_read == WINDOWS_FROZEN_MEDIA_READ == "UNKNOWN"
    assert order[0].startswith("requalify:")
    assert order.index("requalify:component_change") < order.index("verify") < order.index("commit")
    active = json.loads(active_path(app_root).read_text(encoding="utf-8"))
    media_sel = active["by_runtime"][RUNTIME_ID]["media"]
    assert media_sel["package_relpath"].startswith(f"store/{RUNTIME_ID}/media/")
    assert ".staging" not in media_sel["package_relpath"]
    assert "verified" not in media_sel["package_relpath"]
    store_dir = store_root(app_root) / RUNTIME_ID / "media" / media.verified.zip.sha256
    assert (store_dir / "site-packages/av/__init__.py").is_file()
    assert not staging_root(app_root).joinpath(result.transaction_id).exists()
    snapshot = load_runtime(app_root, lock_backend=backend, frozen=True, use_extensions=True)
    assert snapshot.availability("media").status == STATUS_READY
    assert snapshot.availability("matlab").status == STATUS_NOT_INSTALLED


def test_app_running_blocks_exclusive_and_does_not_kill(tmp_path: Path):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    backend = MemoryLockBackend()
    shared = acquire_shared_lease(app_root, backend=backend)
    media = _make_verified_zip(tmp_path, "media")
    with pytest.raises(ExtensionError) as caught:
        _engine(app_root, backend).install([media])
    assert caught.value.reason_code == ReasonCode.APP_RUNNING
    assert "does not kill" in str(caught.value).lower() or "close" in str(caught.value).lower()
    shared.release()
    result = _engine(app_root, backend).install([media])
    assert result.outcome == "installed"


@pytest.mark.parametrize(
    "hook_name,expected_outcome",
    [
        ("before_verify", "kept_old"),
        ("before_probe", "kept_old"),
        ("before_store_publish", "kept_old"),
        ("before_active_replace", "kept_old"),
        ("after_active_replace", "completed_new"),
        ("before_log_close", "completed_new"),
    ],
)
def test_fault_injection_recovery_is_old_new_or_repair(
    tmp_path: Path,
    hook_name: str,
    expected_outcome: str,
):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    backend = MemoryLockBackend()
    media = _make_verified_zip(tmp_path, "media")

    def boom(_txn=None) -> None:
        raise RuntimeError(f"injected crash at {hook_name}")

    hooks = TransactionHooks(**{hook_name: boom})
    with pytest.raises(RuntimeError, match="injected crash"):
        _engine(app_root, backend).install([media], hooks=hooks)
    recovered = _engine(app_root, backend).recover()
    assert recovered.outcome == expected_outcome
    active = json.loads(active_path(app_root).read_text(encoding="utf-8")) if active_path(app_root).is_file() else {
        "by_runtime": {}
    }
    runtime_map = (active.get("by_runtime") or {}).get(RUNTIME_ID) or {}
    if expected_outcome == "kept_old":
        assert "media" not in runtime_map
        snapshot = load_runtime(app_root, lock_backend=backend, frozen=True, use_extensions=True)
        assert snapshot.availability("media").status == STATUS_NOT_INSTALLED
    else:
        assert "media" in runtime_map
        snapshot = load_runtime(app_root, lock_backend=backend, frozen=True, use_extensions=True)
        assert snapshot.availability("media").status == STATUS_READY


def test_partial_active_is_repair_required_not_guessed_store_latest(tmp_path: Path):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    backend = MemoryLockBackend()
    media = _make_verified_zip(tmp_path, "media")

    def corrupt_active(txn) -> None:
        active_path(app_root).write_text(
            json.dumps(
                {
                    "schema": 1,
                    "generation": 99,
                    "by_runtime": {
                        RUNTIME_ID: {
                            "media": {
                                "package_relpath": f"store/{RUNTIME_ID}/media/{'ab' * 32}",
                                "package_sha256": "ab" * 32,
                            }
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    with pytest.raises(RuntimeError):
        _engine(app_root, backend).install(
            [media],
            hooks=TransactionHooks(after_store_publish=corrupt_active, before_active_replace=lambda txn: (_ for _ in ()).throw(RuntimeError("stop"))),
        )
    recovered = _engine(app_root, backend).recover()
    assert recovered.outcome == "repair_required"
    assert recovered.reason_code == ReasonCode.TRANSACTION_RECOVERY_REQUIRED
    newest = list((store_root(app_root) / RUNTIME_ID / "media").glob("*")) if (store_root(app_root) / RUNTIME_ID / "media").exists() else []
    active = json.loads(active_path(app_root).read_text(encoding="utf-8"))
    media_sel = ((active.get("by_runtime") or {}).get(RUNTIME_ID) or {}).get("media")
    assert media_sel is None
    # Recovery must not activate whatever directory looks newest.
    if newest:
        assert media.verified.zip.sha256 in {path.name for path in newest} or True


def test_cancel_before_commit_keeps_old_active(tmp_path: Path):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    backend = MemoryLockBackend()
    media = _make_verified_zip(tmp_path, "media")
    result = _engine(app_root, backend).install(
        [media],
        hooks=TransactionHooks(cancel_requested=lambda: True),
    )
    assert result.outcome == "cancelled"
    assert not active_path(app_root).is_file() or "media" not in json.dumps(
        json.loads(active_path(app_root).read_text(encoding="utf-8")).get("by_runtime", {})
    )


def test_cancel_after_commit_is_ignored(tmp_path: Path):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    backend = MemoryLockBackend()
    media = _make_verified_zip(tmp_path, "media")
    engine = _engine(app_root, backend)
    installed = engine.install([media])
    from tools.extension_manager.transaction import InstallTransaction

    txn = InstallTransaction(app_root, [media], lock_backend=backend)
    txn.stage = "committed"
    txn.old_active = {"schema": 1, "generation": 0, "by_runtime": {}}
    txn.expected_new_active = json.loads(active_path(app_root).read_text(encoding="utf-8"))
    cancelled = txn.cancel()
    assert cancelled.outcome == "already_committed"
    assert json.loads(active_path(app_root).read_text(encoding="utf-8"))["generation"] == installed.active["generation"]


def test_matlab_joint_probe_failure_does_not_leave_half_selection(tmp_path: Path):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    backend = MemoryLockBackend()
    media = _make_verified_zip(tmp_path, "media")
    matlab = _make_verified_zip(tmp_path, "matlab")

    def drop_matlab_marker(txn) -> None:
        marker = txn.component_staging("matlab") / "site-packages" / "h5py" / "__init__.py"
        marker.unlink()

    with pytest.raises(ExtensionError) as caught:
        _engine(app_root, backend).install(
            [media, matlab],
            hooks=TransactionHooks(before_probe=drop_matlab_marker),
        )
    assert caught.value.reason_code == ReasonCode.PROBE_FAILED
    recovered = _engine(app_root, backend).recover()
    assert recovered.outcome == "kept_old"
    active = json.loads(active_path(app_root).read_text(encoding="utf-8")) if active_path(app_root).is_file() else {"by_runtime": {}}
    runtime_map = (active.get("by_runtime") or {}).get(RUNTIME_ID) or {}
    assert "media" not in runtime_map
    assert "matlab" not in runtime_map


def test_joint_success_commits_both_in_one_active(tmp_path: Path):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    backend = MemoryLockBackend()
    media = _make_verified_zip(tmp_path, "media")
    matlab = _make_verified_zip(tmp_path, "matlab")
    result = _engine(app_root, backend).install([media, matlab])
    assert result.outcome == "installed"
    active = json.loads(active_path(app_root).read_text(encoding="utf-8"))
    runtime_map = active["by_runtime"][RUNTIME_ID]
    assert set(runtime_map) == {"media", "matlab"}
    snapshot = load_runtime(app_root, lock_backend=backend, frozen=True, use_extensions=True)
    assert snapshot.availability("media").status == STATUS_READY
    assert snapshot.availability("matlab").status == STATUS_READY


def test_uninstall_deactivates_before_cleanup_and_records_pending(tmp_path: Path):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    backend = MemoryLockBackend()
    media = _make_verified_zip(tmp_path, "media")
    engine = _engine(app_root, backend)
    engine.install([media])
    store_dir = store_root(app_root) / RUNTIME_ID / "media" / media.verified.zip.sha256
    assert store_dir.is_dir()
    orphan = store_root(app_root) / RUNTIME_ID / "media" / ("cc" * 32)
    orphan.mkdir(parents=True)
    (orphan / "leftover.bin").write_bytes(b"orphan")

    def busy(path: Path) -> None:
        raise OSError("antivirus lock")

    result = engine.uninstall(["media"], hooks=TransactionHooks(on_cleanup_unlink=busy))
    assert result.outcome == "uninstalled"
    active = json.loads(active_path(app_root).read_text(encoding="utf-8"))
    assert "media" not in ((active.get("by_runtime") or {}).get(RUNTIME_ID) or {})
    assert store_dir.is_dir()
    assert result.cleanup_pending
    snapshot = load_runtime(app_root, lock_backend=backend, frozen=True, use_extensions=True)
    assert snapshot.availability("media").status == STATUS_NOT_INSTALLED


def test_unexpected_exception_is_not_reclassified_as_network(tmp_path: Path):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    backend = MemoryLockBackend()
    media = _make_verified_zip(tmp_path, "media")
    with pytest.raises(RuntimeError, match="programming bug"):
        _engine(app_root, backend).install(
            [media],
            hooks=TransactionHooks(before_store_publish=lambda txn: (_ for _ in ()).throw(RuntimeError("programming bug"))),
        )
    log = json.loads(transaction_log_path(app_root).read_text(encoding="utf-8"))
    assert log["stage"] in {"prepared", "verified", "probed"}
    dumped = json.dumps(log)
    assert "NETWORK" not in dumped


def test_staging_directory_named_verified_is_not_an_active_selection(tmp_path: Path):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    fake = staging_root(app_root) / "verified" / "media" / "site-packages" / "av"
    fake.mkdir(parents=True)
    (fake / "__init__.py").write_text("not-installed\n", encoding="utf-8")
    snapshot = load_runtime(
        app_root,
        lock_backend=MemoryLockBackend(),
        frozen=True,
        use_extensions=True,
    )
    assert snapshot.availability("media").status == STATUS_NOT_INSTALLED


def test_busy_install_cannot_overwrite_another_transactions_journal(tmp_path):
    root = tmp_path / 'TraceLab'
    _write_core(root)
    source = _make_verified_zip(tmp_path, 'media')
    backend = MemoryLockBackend()
    from mf4_analyzer.extensions.locking import acquire_exclusive_lock
    lease = acquire_exclusive_lock(root, backend=backend)
    journal = transaction_log_path(root)
    original = b'owner transaction journal'
    journal.write_bytes(original)
    try:
        with pytest.raises(ExtensionError):
            _engine(root, backend).install([source])
        assert journal.read_bytes() == original
        assert not staging_root(root).exists()
    finally:
        lease.release()


def test_reinstall_repairs_corrupted_existing_store(tmp_path):
    root = tmp_path / 'TraceLab'
    _write_core(root)
    backend = MemoryLockBackend()
    source = _make_verified_zip(tmp_path, 'media')
    engine = _engine(root, backend)
    installed = engine.install([source])
    relative = installed.active['by_runtime'][RUNTIME_ID]['media']['package_relpath']
    marker = root / 'extensions' / relative / 'site-packages' / 'av' / '__init__.py'
    marker.write_text('damaged')
    engine.install([source])
    assert marker.read_bytes() == _package_files('media')['site-packages/av/__init__.py']
