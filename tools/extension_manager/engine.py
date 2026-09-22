"""Orchestrate verified-package install transactions.

TUF download stays optional and is imported lazily so application-layer tests
do not need ``tuf`` in the app ``.venv``.  Programming errors are not mapped
to network failures.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence

from mf4_analyzer.extensions.contract import ExtensionError, REASON_CODES, ReasonCode, VerifiedPackage
from mf4_analyzer.extensions.locking import LockBackend
from mf4_analyzer.extensions.runtime import identify_core

from .transaction import (
    InstallTransaction,
    PackageSource,
    TransactionHooks,
    TransactionResult,
    recover_transaction,
    uninstall_components,
)


class InstallEngine:
    """Identify core → lock → requalify → probe → immutable store → active.json."""

    def __init__(
        self,
        app_root: str | Path,
        *,
        lock_backend: LockBackend | None = None,
        probe_executable: Sequence[str] | None = None,
        requalify: Callable[..., Any] | None = None,
        manager_version: str = "1.0.0",
        probe_timeout_seconds: float = 30.0,
    ) -> None:
        self.app_root = Path(app_root).expanduser().resolve()
        self.lock_backend = lock_backend
        self.probe_executable = list(probe_executable) if probe_executable is not None else None
        self.requalify = requalify
        self.manager_version = manager_version
        self.probe_timeout_seconds = probe_timeout_seconds

    def _hooks(self, extra: TransactionHooks | None) -> TransactionHooks:
        hooks = extra or TransactionHooks()
        if hooks.requalify is None:
            hooks.requalify = self.requalify
        return hooks

    def install(
        self,
        packages: Sequence[PackageSource | tuple[VerifiedPackage, Path]],
        *,
        hooks: TransactionHooks | None = None,
    ) -> TransactionResult:
        sources: list[PackageSource] = []
        for item in packages:
            if isinstance(item, PackageSource):
                sources.append(item)
            else:
                verified, zip_path = item
                sources.append(PackageSource(verified=verified, zip_path=Path(zip_path)))
        txn = InstallTransaction(
            self.app_root,
            sources,
            lock_backend=self.lock_backend,
            probe_executable=self.probe_executable,
            hooks=self._hooks(hooks),
            manager_version=self.manager_version,
            probe_timeout_seconds=self.probe_timeout_seconds,
        )
        return txn.run()

    def uninstall(
        self,
        components: Sequence[str],
        *,
        hooks: TransactionHooks | None = None,
    ) -> TransactionResult:
        extra = self._hooks(hooks)
        return uninstall_components(
            self.app_root,
            components,
            lock_backend=self.lock_backend,
            requalify=extra.requalify,
            hooks=extra,
        )

    def recover(self) -> TransactionResult:
        return recover_transaction(
            self.app_root,
            lock_backend=self.lock_backend,
            requalify=self.requalify,
        )

    def install_from_repository(
        self,
        repository: Any,
        components: Sequence[str],
        *,
        hooks: TransactionHooks | None = None,
    ) -> TransactionResult:
        """Select against the target core, then consume the real verified API."""

        core = identify_core(self.app_root)
        target = {
            "runtime_id": core.runtime_id,
            "capabilities": {
                name: capability.component_api
                for name, capability in core.envelope.component_capabilities.items()
                if capability.available
            },
        }
        sources: list[PackageSource] = []
        for component in components:
            if hooks is not None and hooks.cancel_requested is not None and hooks.cancel_requested():
                from .transaction import TransactionCancelled
                raise TransactionCancelled("download cancelled")
            selection = repository.select_package(component, target, platform_tag="win_amd64")
            if not selection.ok or selection.package is None:
                reason = selection.reason_code or ReasonCode.NO_COMPATIBLE_PACKAGE
                message = f"Package selection failed for {component}: {reason}"
                if reason in REASON_CODES:
                    raise ExtensionError(reason, message)
                from .repository import ExtensionRepositoryError
                raise ExtensionRepositoryError(message, reason)
            zip_path, verified = repository.download_verified_package(
                selection.package, self.app_root, cancel_event=repository.cancel_event,
            )
            sources.append(PackageSource(verified=verified, zip_path=Path(zip_path)))
        extra = self._hooks(hooks)
        if extra.requalify is None:
            extra.requalify = getattr(repository, "requalify_after_lock_wait", None)
        return self.install(sources, hooks=extra)


def install_verified_packages(
    app_root: str | Path,
    packages: Sequence[PackageSource | tuple[VerifiedPackage, Path]],
    **kwargs: Any,
) -> TransactionResult:
    return InstallEngine(app_root, **kwargs).install(packages)
