"""Standalone TraceLab extension manager package.

Keep this tree free of PyQt, NumPy, PyAV, SciPy, and h5py imports.
"""

from .unpack import extract_verified_package, extract_verified_zip, validate_zip

__all__ = (
    "extract_verified_package",
    "extract_verified_zip",
    "validate_zip",
)
