"""Install / uninstall transaction state machine.

Stages: prepared → verified → probed → committed → cleanup.
``active.json`` is the only commit point.  Staging directory names are not
verification.  Neutral tools layer: no Qt/UI; TUF stays out of this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import shutil
import time
import uuid
from typing import Any, Callable, Mapping, Sequence

from mf4_analyzer.extensions.contract import (
    TRANSACTION_SCHEMA_V1,
    TRANSACTION_STAGES,
    ExtensionError,
    ReasonCode,
    VerifiedPackage,
    evaluate_install_compatibility,
    generate_active_state,
    generate_receipt,
    parse_active_state,
    parse_receipt,
    parse_transaction_log,
    store_package_relpath,
)
from mf4_analyzer.extensions.locking import (
    Lease,
    LockBackend,
    acquire_exclusive_lock,
    extensions_root,
    refuse_unsupported_filesystem,
    verify_staging_auth,
    write_staging_auth,
)
from mf4_analyzer.extensions.probe import (
    ProbeError,
    ProbeTimeout,
    build_probe_request,
    probe_command,
    run_authorized_probe,
    write_result_json,
)
from mf4_analyzer.extensions.runtime import (
    WINDOWS_FROZEN_MEDIA_READ,
    active_path,
    content_identity_bytes,
    empty_active,
    ensure_install_id,
    identify_core,
    verify_core_files,
    verify_package_tree,
    load_optional_active,
    read_json,
    require_same_volume_staging,
    rollback_path,
    selections_equal,
    staging_root,
    store_root,
    transaction_log_path,
    write_json_atomic,
)
from mf4_analyzer.extensions.state import CoreIdentity, resolve_inside, verify_receipt
from .unpack import UnpackError, extract_verified_package, require_disk_space


CANCELABLE_STAGES = frozenset({"prepared", "verified", "probed"})
REQUALIFY_KIND = "component_change"


class TransactionCancelled(Exception):
    """User cancel before the active.json critical section."""


@dataclass
class TransactionHooks:
    """Fault-injection and collaborator seams.  Unexpected exceptions propagate."""

    requalify: Callable[..., Any] | None = None
    before_verify: Callable[["InstallTransaction"], None] | None = None
    before_probe: Callable[["InstallTransaction"], None] | None = None
    before_store_publish: Callable[["InstallTransaction"], None] | None = None
    after_store_publish: Callable[["InstallTransaction"], None] | None = None
    before_active_replace: Callable[["InstallTransaction"], None] | None = None
    after_active_replace: Callable[["InstallTransaction"], None] | None = None
    before_log_close: Callable[["InstallTransaction"], None] | None = None
    on_cleanup_unlink: Callable[[Path], None] | None = None
    on_phase: Callable[[str], None] | None = None
    probe_runner: Callable[..., dict[str, Any]] | None = None
    cancel_requested: Callable[[], bool] | None = None


@dataclass(frozen=True)
class PackageSource:
    verified: VerifiedPackage
    zip_path: Path


@dataclass
class TransactionResult:
    stage: str
    transaction_id: str
    outcome: str
    reason_code: str | None = None
    active: dict[str, Any] | None = None
    cleanup_pending: tuple[str, ...] = ()
    repair_required: bool = False
    windows_frozen_media_read: str = WINDOWS_FROZEN_MEDIA_READ


def _call_hook(hook: Callable[..., Any] | None, *args: Any) -> None:
    if hook is not None:
        hook(*args)


class InstallTransaction:
    def __init__(
        self,
        app_root: str | Path,
        packages: Sequence[PackageSource],
        *,
        lock_backend: LockBackend | None = None,
        probe_executable: Sequence[str] | None = None,
        hooks: TransactionHooks | None = None,
        manager_version: str = "1.0.0",
        probe_timeout_seconds: float = 30.0,
        disk_margin_bytes: int = 1024 * 1024,
        transaction_id: str | None = None,
    ) -> None:
        if not packages:
            raise ExtensionError(ReasonCode.NO_COMPATIBLE_PACKAGE, "no packages in the transaction")
        self.app_root = Path(app_root).expanduser().resolve()
        self.packages = tuple(packages)
        self.lock_backend = lock_backend
        self.probe_executable = (list(probe_executable) if probe_executable is not None
                                 else [str(self.app_root / identify_core(self.app_root).exe_relpath)])
        self.hooks = hooks or TransactionHooks()
        self.manager_version = manager_version
        self.probe_timeout_seconds = probe_timeout_seconds
        self.disk_margin_bytes = disk_margin_bytes
        self.transaction_id = transaction_id or uuid.uuid4().hex
        self.core: CoreIdentity | None = None
        self.old_active: dict[str, Any] = empty_active()
        self.expected_new_active: dict[str, Any] = empty_active()
        self.stage = "prepared"
        self.lease: Lease | None = None
        self._in_commit_critical = False
        self.cleanup_pending: list[str] = []
        self.staging_nonce = uuid.uuid4().hex
        self.repair_required = False

    @property
    def extensions(self) -> Path:
        return extensions_root(self.app_root)

    @property
    def staging_dir(self) -> Path:
        return staging_root(self.app_root) / self.transaction_id

    def component_staging(self, component: str) -> Path:
        return self.staging_dir / component

    def _log_path(self) -> Path:
        return transaction_log_path(self.app_root)

    def _affected_components(self) -> tuple[str, ...]:
        return tuple(item.verified.component for item in self.packages)

    def _package_hashes(self) -> tuple[str, ...]:
        return tuple(item.verified.zip.sha256 for item in self.packages)

    def _raise_if_cancelled(self) -> None:
        if self._in_commit_critical:
            return
        requested = self.hooks.cancel_requested
        if requested is not None and requested():
            raise TransactionCancelled("cancel requested before active commit")

    def _write_log(self, stage: str, **extra: Any) -> None:
        if stage not in TRANSACTION_STAGES:
            raise ExtensionError(ReasonCode.PROTOCOL_UNSUPPORTED, f"unknown stage {stage}")
        self.stage = stage
        _call_hook(self.hooks.on_phase, stage)
        payload: dict[str, Any] = {
            "schema": TRANSACTION_SCHEMA_V1,
            "transaction_id": self.transaction_id,
            "stage": stage,
            "core_build_id": self.core.core_build_id if self.core is not None else "",
            "runtime_id": self.core.runtime_id if self.core is not None else "",
            "old_active_generation": int(self.old_active.get("generation") or 0),
            "old_active_sha256": content_identity_bytes(self.old_active),
            "new_active_generation": int(self.expected_new_active.get("generation") or 0),
            "package_hashes": list(self._package_hashes()),
            "cleanup_pending": list(self.cleanup_pending),
            "old_active": self.old_active,
            "expected_new_active": self.expected_new_active,
            "affected_components": list(self._affected_components()),
            "staging_nonce": self.staging_nonce,
            "repair_required": self.repair_required,
        }
        payload.update(extra)
        parse_transaction_log(payload)
        write_json_atomic(self._log_path(), payload)

    def _expected_selection_map(self) -> dict[str, dict[str, dict[str, str]]]:
        assert self.core is not None
        current = {
            runtime: {
                component: dict(spec)
                for component, spec in mapping.items()
            }
            for runtime, mapping in (self.old_active.get("by_runtime") or {}).items()
        }
        runtime_map = dict(current.get(self.core.runtime_id) or {})
        for source in self.packages:
            relpath = store_package_relpath(
                source.verified.runtime_id,
                source.verified.component,
                source.verified.zip.sha256,
            )
            runtime_map[source.verified.component] = {
                "package_relpath": relpath,
                "package_sha256": source.verified.zip.sha256,
            }
        current[self.core.runtime_id] = runtime_map
        return current

    def prepare(self) -> None:
        refuse_unsupported_filesystem(self.app_root)
        self.core = identify_core(self.app_root)
        existing = load_optional_active(self.app_root)
        if existing is None:
            self.old_active = empty_active(generation=0)
        else:
            self.old_active = generate_active_state(
                generation=existing.generation,
                by_runtime={
                    runtime_id: {
                        component: {
                            "package_relpath": selection.package_relpath,
                            "package_sha256": selection.package_sha256,
                        }
                        for component, selection in mapping.items()
                    }
                    for runtime_id, mapping in existing.by_runtime.items()
                },
            )
        for source in self.packages:
            if source.verified.runtime_id != self.core.runtime_id:
                raise ExtensionError(
                    ReasonCode.COMPONENT_INCOMPATIBLE,
                    "package runtime_id does not match the identified core",
                )
            decision = evaluate_install_compatibility(
                core=self.core.envelope,
                package=source.verified.package,
                manager_version=self.manager_version,
            )
            if not decision.allowed:
                raise ExtensionError(decision.reason_code, "package is not installable on this core")
        new_generation = int(self.old_active.get("generation") or 0) + 1
        self.expected_new_active = generate_active_state(
            generation=new_generation,
            by_runtime=self._expected_selection_map(),
        )
    def prepare_staging(self) -> None:
        # Only the exclusive holder may mutate the shared journal or store.
        ensure_install_id(self.app_root)
        path = self._log_path()
        if path.is_file():
            previous = read_json(path)
            if previous.get("stage") not in {"committed", "cleanup"} or previous.get("repair_required"):
                raise ExtensionError(ReasonCode.TRANSACTION_RECOVERY_REQUIRED, "recover previous transaction first")
        store = store_root(self.app_root)
        store.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        require_same_volume_staging(self.staging_dir, store)
        required = sum(source.verified.zip.length + source.verified.package.max_extract_bytes for source in self.packages)
        require_disk_space(self.staging_dir, required, self.disk_margin_bytes)
        write_staging_auth(self.staging_dir, self.staging_nonce)
        self._write_log("prepared")

    def acquire_lock(self) -> Lease:
        self._raise_if_cancelled()
        self.lease = acquire_exclusive_lock(self.app_root, backend=self.lock_backend)
        return self.lease

    def requalify_after_lock(self) -> None:
        """Call the existing repository seam after lock, before commit."""

        assert self.core is not None
        requalify = self.hooks.requalify
        if requalify is not None:
            requalify(kind=REQUALIFY_KIND)
        current = identify_core(self.app_root)
        verify_core_files(self.app_root, current)
        if current.core_build_id != self.core.core_build_id or current.runtime_id != self.core.runtime_id:
            raise ExtensionError(
                ReasonCode.CORE_INCONSISTENT,
                "core identity changed while waiting for the exclusive lock",
            )
        active = load_optional_active(self.app_root)
        observed_generation = 0 if active is None else active.generation
        if observed_generation != int(self.old_active.get("generation") or 0):
            raise ExtensionError(
                ReasonCode.CORE_INCONSISTENT,
                "active generation changed while waiting for the exclusive lock",
            )

    def verify(self) -> None:
        self._raise_if_cancelled()
        _call_hook(self.hooks.before_verify, self)
        assert self.core is not None
        for source in self.packages:
            dest = self.component_staging(source.verified.component)
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True, exist_ok=True)
            try:
                extract_verified_package(
                    source.zip_path,
                    dest,
                    extensions_root=self.extensions,
                    verified=source.verified,
                    app_root=self.app_root,
                )
            except UnpackError as exc:
                if dest.exists():
                    shutil.rmtree(dest, ignore_errors=True)
                raise ExtensionError(
                    exc.reason_code or ReasonCode.VERIFICATION_FAILED,
                    str(exc),
                ) from exc
        self._write_log("verified")

    def probe(self) -> dict[str, Any]:
        self._raise_if_cancelled()
        _call_hook(self.hooks.before_probe, self)
        assert self.core is not None
        selection = self.expected_new_active["by_runtime"][self.core.runtime_id]
        names = sorted(selection)
        request = build_probe_request(
            core_build_id=self.core.core_build_id,
            runtime_id=self.core.runtime_id,
            transaction_id=self.transaction_id,
            components=names,
            package_hashes=[selection[name]["package_sha256"] for name in names],
            staging_relpath=f".staging/{self.transaction_id}",
            staging_nonce=self.staging_nonce,
        )
        request["app_root"] = str(self.app_root)
        request["package_roots"] = {
            name: (f".staging/{self.transaction_id}/{name}" if name in self._affected_components()
                   else selection[name]["package_relpath"])
            for name in names
        }
        request_path = self.staging_dir / "probe-request.json"
        result_path = self.staging_dir / "probe-result.json"
        write_json_atomic(request_path, request)
        verify_staging_auth(
            self.staging_dir,
            self.staging_nonce,
            extensions_root_path=self.extensions,
            transaction_id=self.transaction_id,
        )
        command = probe_command(
            self.probe_executable,
            request_path=request_path,
            result_path=result_path,
            staging_dir=self.staging_dir,
            staging_nonce=self.staging_nonce,
        )
        runner = self.hooks.probe_runner or run_authorized_probe
        try:
            payload = runner(
                command,
                timeout_seconds=self.probe_timeout_seconds,
                result_path=result_path,
                app_root=self.app_root,
            )
        except ProbeTimeout as exc:
            raise ExtensionError(ReasonCode.PROBE_FAILED, str(exc)) from exc
        except ProbeError as exc:
            raise ExtensionError(exc.reason_code, str(exc)) from exc
        if not payload.get("ok"):
            raise ExtensionError(ReasonCode.PROBE_FAILED, "authorized probe reported failure")
        self._write_log("probed", probe=payload)
        return payload

    def _retry_store_operation(self, operation: Callable, *paths: Path) -> None:
        # Windows native-image consumers (observed: ARM XtaCache) can retain a
        # probed DLL briefly after the child has exited. Keep the lease held,
        # preserve cancellation, and never turn permanent failures into success.
        for attempt in range(31):
            self._raise_if_cancelled()
            try:
                operation(*paths)
                return
            except OSError as exc:
                if getattr(exc, "winerror", None) not in {5, 32} or attempt == 30:
                    raise
                if attempt == 0:
                    logging.getLogger(__name__).warning(
                        "Windows store operation blocked (%s); retrying for up to 3s: %s",
                        exc.winerror, paths,
                    )
                time.sleep(0.1)

    def publish_store(self) -> None:
        self._raise_if_cancelled()
        _call_hook(self.hooks.on_phase, "publish")
        _call_hook(self.hooks.before_store_publish, self)
        assert self.core is not None
        for source in self.packages:
            relpath = store_package_relpath(
                source.verified.runtime_id,
                source.verified.component,
                source.verified.zip.sha256,
            )
            dest = resolve_inside(self.extensions, relpath)
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = self.component_staging(source.verified.component)
            if dest.exists():
                try:
                    verify_package_tree(dest, source.verified.package.files, extensions=self.extensions)
                    verify_receipt(parse_receipt((dest / "receipt.json").read_bytes()),
                                   package_json_bytes=(dest / "package.json").read_bytes(),
                                   package=source.verified.package,
                                   package_sha256=source.verified.zip.sha256,
                                   trusted_target_id=source.verified.manifest.sha256)
                except (ExtensionError, OSError, ValueError):
                    # Preserve damaged bytes for diagnosis/recovery under the held lock.
                    quarantine = self.extensions / ".quarantine" / self.transaction_id / source.verified.component
                    quarantine.parent.mkdir(parents=True, exist_ok=True)
                    self._retry_store_operation(os.replace, dest, quarantine)
                    self.cleanup_pending.append(quarantine.relative_to(self.extensions).as_posix())
                else:
                    self._retry_store_operation(shutil.rmtree, src)
                    continue
            self._retry_store_operation(os.replace, src, dest)
            receipt = generate_receipt(
                core_build_id=self.core.core_build_id,
                package=source.verified.package,
                package_sha256=source.verified.zip.sha256,
                package_json_sha256=source.verified.manifest.sha256,
                probe_ok=True,
            )
            write_json_atomic(dest / "receipt.json", receipt)
            verify_receipt(
                parse_receipt(receipt),
                package_json_bytes=source.verified.package_json_bytes,
                package=source.verified.package,
                package_sha256=source.verified.zip.sha256,
                trusted_target_id=source.verified.manifest.sha256,
            )
        _call_hook(self.hooks.after_store_publish, self)

    def commit_active(self) -> None:
        self._raise_if_cancelled()
        self._in_commit_critical = True
        _call_hook(self.hooks.on_phase, "commit")
        try:
            _call_hook(self.hooks.before_active_replace, self)
            write_json_atomic(active_path(self.app_root), self.expected_new_active)
            parse_active_state(active_path(self.app_root).read_bytes())
            _call_hook(self.hooks.after_active_replace, self)
        finally:
            self._in_commit_critical = False

    def mark_committed(self) -> None:
        _call_hook(self.hooks.before_log_close, self)
        previous = rollback_path(self.app_root)
        write_json_atomic(previous, self.old_active)
        self._write_log("committed")

    def cleanup(self) -> None:
        if self.staging_dir.exists():
            shutil.rmtree(self.staging_dir, ignore_errors=True)
        referenced = _referenced_store_relpaths(self.app_root, include_rollback=True)
        self._recycle_unreferenced(referenced)
        self._write_log("cleanup")

    def _recycle_unreferenced(self, referenced: set[str]) -> None:
        store = store_root(self.app_root)
        if not store.is_dir() or self.core is None:
            return
        runtime_dir = store / self.core.runtime_id
        if not runtime_dir.is_dir():
            return
        for component_dir in runtime_dir.iterdir():
            if not component_dir.is_dir():
                continue
            for digest_dir in component_dir.iterdir():
                relpath = f"store/{self.core.runtime_id}/{component_dir.name}/{digest_dir.name}"
                if relpath in referenced:
                    continue
                self._try_unlink_store(relpath)

    def _try_unlink_store(self, relpath: str) -> None:
        try:
            path = resolve_inside(self.extensions, relpath)
        except ExtensionError:
            return
        hook = self.hooks.on_cleanup_unlink
        try:
            if hook is not None:
                hook(path)
            if path.exists():
                shutil.rmtree(path)
        except OSError:
            self.cleanup_pending.append(relpath)

    def release_lock(self) -> None:
        if self.lease is not None:
            self.lease.release()
            self.lease = None

    def cancel(self) -> TransactionResult:
        if self.stage not in CANCELABLE_STAGES:
            return TransactionResult(
                stage=self.stage,
                transaction_id=self.transaction_id,
                outcome="already_committed",
                active=_load_active_payload(self.app_root),
                cleanup_pending=tuple(self.cleanup_pending),
            )
        if self.lease is None:
            return TransactionResult("prepared", self.transaction_id, "cancelled", active=self.old_active)
        if self.staging_dir.exists():
            shutil.rmtree(self.staging_dir, ignore_errors=True)
        if self._log_path().exists() and read_json(self._log_path()).get("transaction_id") == self.transaction_id:
            self._log_path().unlink()
        return TransactionResult(
            stage="prepared",
            transaction_id=self.transaction_id,
            outcome="cancelled",
            active=self.old_active,
        )

    def run(self) -> TransactionResult:
        self.prepare()
        try:
            self.acquire_lock()
            self.requalify_after_lock()
            self.prepare_staging()
            self.verify()
            self.probe()
            self.publish_store()
            self.commit_active()
            self.mark_committed()
            self.cleanup()
        except TransactionCancelled:
            result = self.cancel()
            return result
        finally:
            self.release_lock()
        return TransactionResult(
            stage=self.stage,
            transaction_id=self.transaction_id,
            outcome="installed",
            active=self.expected_new_active,
            cleanup_pending=tuple(self.cleanup_pending),
        )


def _load_active_payload(app_root: Path) -> dict[str, Any] | None:
    path = active_path(app_root)
    if not path.is_file():
        return None
    return read_json(path)


def _referenced_store_relpaths(app_root: Path, *, include_rollback: bool) -> set[str]:
    found: set[str] = set()
    for path in (active_path(app_root), rollback_path(app_root) if include_rollback else None):
        if path is None or not path.is_file():
            continue
        try:
            payload = read_json(path)
            parsed = parse_active_state(payload)
        except (ExtensionError, OSError, ValueError):
            continue
        for selection in parsed.iter_selections():
            found.add(selection.package_relpath)
    return found


def recover_transaction(
    app_root: str | Path,
    *,
    lock_backend: LockBackend | None = None,
    requalify: Callable[..., Any] | None = None,
) -> TransactionResult:
    """Crash recovery: complete old, complete new, or repair_required.

    Never guesses the newest directory under store/.
    """

    root = Path(app_root).expanduser().resolve()
    log_path = transaction_log_path(root)
    lease = acquire_exclusive_lock(root, backend=lock_backend)
    try:
        if requalify is not None:
            requalify(kind=REQUALIFY_KIND)
        if not log_path.is_file():
            return TransactionResult(stage="cleanup", transaction_id="", outcome="idle")
        raw = read_json(log_path)
        log = parse_transaction_log(raw)
        old_active = raw.get("old_active") or empty_active()
        expected_new = raw.get("expected_new_active")
        observed = _load_active_payload(root)
        if observed is None and not (old_active.get("by_runtime") or {}):
            observed = old_active
        staging = staging_root(root) / log.transaction_id
        if selections_equal(observed, old_active):
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            _cleanup_unreferenced_candidates(root, raw, keep=old_active)
            log_path.unlink()
            return TransactionResult(
                stage="cleanup",
                transaction_id=log.transaction_id,
                outcome="kept_old",
                active=old_active,
            )
        if expected_new is not None and selections_equal(observed, expected_new) and _new_packages_verify(root, raw):
            write_json_atomic(log_path, {**raw, "stage": "committed", "repair_required": False})
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            return TransactionResult(
                stage="committed",
                transaction_id=log.transaction_id,
                outcome="completed_new",
                active=expected_new,
            )
        deactivated = _deactivate_affected(old_active, raw)
        write_json_atomic(active_path(root), deactivated)
        write_json_atomic(
            log_path,
            {
                **raw,
                "repair_required": True,
                "stage": log.stage if log.stage in TRANSACTION_STAGES else "verified",
            },
        )
        return TransactionResult(
            stage=log.stage,
            transaction_id=log.transaction_id,
            outcome="repair_required",
            reason_code=ReasonCode.TRANSACTION_RECOVERY_REQUIRED,
            active=deactivated,
            repair_required=True,
        )
    finally:
        lease.release()


def _new_packages_verify(app_root: Path, raw: Mapping[str, Any]) -> bool:
    expected = raw.get("expected_new_active")
    if not isinstance(expected, dict):
        return False
    try:
        parsed = parse_active_state(expected)
        for selection in parsed.iter_selections():
            package_root = resolve_inside(extensions_root(app_root), selection.package_relpath)
            manifest = package_root / "package.json"
            from mf4_analyzer.extensions.contract import parse_package_manifest
            package = parse_package_manifest(manifest.read_bytes())
            receipt = parse_receipt((package_root / "receipt.json").read_bytes())
            verify_receipt(receipt, package_json_bytes=manifest.read_bytes(), package=package,
                           package_sha256=selection.package_sha256)
            if not receipt.probe_ok:
                return False
            verify_package_tree(package_root, package.files, extensions=extensions_root(app_root))
        return True
    except (ExtensionError, OSError, ValueError):
        return False


def _deactivate_affected(old_active: Mapping[str, Any], raw: Mapping[str, Any]) -> dict[str, Any]:
    affected = set(str(item) for item in raw.get("affected_components") or ())
    runtime_id = str(raw.get("runtime_id") or "")
    by_runtime = {
        runtime: {
            component: dict(spec)
            for component, spec in mapping.items()
            if not (runtime == runtime_id and component in affected)
        }
        for runtime, mapping in (old_active.get("by_runtime") or {}).items()
    }
    generation = int(old_active.get("generation") or 0) + 1
    return generate_active_state(generation=generation, by_runtime=by_runtime)


def _cleanup_unreferenced_candidates(app_root: Path, raw: Mapping[str, Any], *, keep: Mapping[str, Any]) -> None:
    keep_relpaths = set()
    try:
        parsed = parse_active_state(keep)
        keep_relpaths = {selection.package_relpath for selection in parsed.iter_selections()}
    except ExtensionError:
        keep_relpaths = set()
    expected = raw.get("expected_new_active") or {}
    try:
        new_parsed = parse_active_state(expected)
    except ExtensionError:
        return
    for selection in new_parsed.iter_selections():
        if selection.package_relpath in keep_relpaths:
            continue
        try:
            path = resolve_inside(extensions_root(app_root), selection.package_relpath)
        except ExtensionError:
            continue
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)


def uninstall_components(
    app_root: str | Path,
    components: Sequence[str],
    *,
    lock_backend: LockBackend | None = None,
    requalify: Callable[..., Any] | None = None,
    hooks: TransactionHooks | None = None,
) -> TransactionResult:
    """Deactivate first, then attempt unreferenced store cleanup."""

    root = Path(app_root).expanduser().resolve()
    hooks = hooks or TransactionHooks()
    names = tuple(str(item) for item in components)
    lease = acquire_exclusive_lock(root, backend=lock_backend)
    try:
        core = identify_core(root)
        verify_core_files(root, core)
        if requalify is not None:
            requalify(kind=REQUALIFY_KIND)
        elif hooks.requalify is not None:
            hooks.requalify(kind=REQUALIFY_KIND)
        existing = load_optional_active(root)
        old = empty_active() if existing is None else generate_active_state(
            generation=existing.generation,
            by_runtime={
                runtime_id: {
                    component: {
                        "package_relpath": selection.package_relpath,
                        "package_sha256": selection.package_sha256,
                    }
                    for component, selection in mapping.items()
                }
                for runtime_id, mapping in existing.by_runtime.items()
            },
        )
        by_runtime = {
            runtime: {
                component: dict(spec)
                for component, spec in mapping.items()
                if not (runtime == core.runtime_id and component in names)
            }
            for runtime, mapping in (old.get("by_runtime") or {}).items()
        }
        new = generate_active_state(generation=int(old.get("generation") or 0) + 1, by_runtime=by_runtime)
        txn_id = uuid.uuid4().hex
        write_json_atomic(
            transaction_log_path(root),
            {
                "schema": TRANSACTION_SCHEMA_V1,
                "transaction_id": txn_id,
                "stage": "prepared",
                "core_build_id": core.core_build_id,
                "runtime_id": core.runtime_id,
                "old_active_generation": int(old.get("generation") or 0),
                "old_active_sha256": content_identity_bytes(old),
                "new_active_generation": int(new.get("generation") or 0),
                "package_hashes": [],
                "cleanup_pending": [],
                "old_active": old,
                "expected_new_active": new,
                "affected_components": list(names),
            },
        )
        write_json_atomic(rollback_path(root), old)
        write_json_atomic(active_path(root), new)
        pending: list[str] = []
        referenced = _referenced_store_relpaths(root, include_rollback=True)
        store = store_root(root)
        runtime_dir = store / core.runtime_id
        if runtime_dir.is_dir():
            for component_dir in runtime_dir.iterdir():
                if not component_dir.is_dir():
                    continue
                if names and component_dir.name not in names:
                    continue
                for digest_dir in component_dir.iterdir():
                    relpath = f"store/{core.runtime_id}/{component_dir.name}/{digest_dir.name}"
                    if relpath in referenced:
                        continue
                    try:
                        path = resolve_inside(extensions_root(root), relpath)
                        if hooks.on_cleanup_unlink is not None:
                            hooks.on_cleanup_unlink(path)
                        if path.exists():
                            shutil.rmtree(path)
                    except OSError:
                        pending.append(relpath)
        write_json_atomic(
            transaction_log_path(root),
            {
                "schema": TRANSACTION_SCHEMA_V1,
                "transaction_id": txn_id,
                "stage": "cleanup",
                "core_build_id": core.core_build_id,
                "runtime_id": core.runtime_id,
                "old_active_generation": int(old.get("generation") or 0),
                "old_active_sha256": content_identity_bytes(old),
                "new_active_generation": int(new.get("generation") or 0),
                "package_hashes": [],
                "cleanup_pending": pending,
                "old_active": old,
                "expected_new_active": new,
                "affected_components": list(names),
            },
        )
        return TransactionResult(
            stage="cleanup",
            transaction_id=txn_id,
            outcome="uninstalled",
            active=new,
            cleanup_pending=tuple(pending),
        )
    finally:
        lease.release()
