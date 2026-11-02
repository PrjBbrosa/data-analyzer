"""Shared input checks; never repair or shorten measurement arrays."""
from __future__ import annotations

import numpy as np


def require_finite_samples(values, label="signal"):
    """Reject gaps in the selected computation input, leaving data untouched.

    Callers retain their own dtype, shape, empty and short-input contracts.
    The caller must slice the requested time range before this check.
    """
    array = np.asarray(values)
    invalid_count = int(array.size - np.count_nonzero(np.isfinite(array)))
    if invalid_count:
        raise ValueError(
            f"所选区间的 {label} 含 {invalid_count} 个缺失或非有限值"
            "（non-finite samples）；请选择有效区间或修复源数据"
        )
