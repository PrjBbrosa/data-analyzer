"""Standalone TraceLab extension manager package.

Keep this tree free of PyQt, NumPy, PyAV, SciPy, and h5py imports.
"""

from .engine import InstallEngine, install_verified_packages
from .transaction import (
    InstallTransaction,
    PackageSource,
    TransactionHooks,
    TransactionResult,
    recover_transaction,
    uninstall_components,
)
from .unpack import extract_verified_package, extract_verified_zip, validate_zip

__all__ = (
    "InstallEngine",
    "InstallTransaction",
    "PackageSource",
    "TransactionHooks",
    "TransactionResult",
    "extract_verified_package",
    "extract_verified_zip",
    "install_verified_packages",
    "recover_transaction",
    "uninstall_components",
    "validate_zip",
)
