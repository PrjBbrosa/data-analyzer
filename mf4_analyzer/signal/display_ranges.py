"""UI-neutral line amplitude ranges from original samples and visible segments."""
from __future__ import annotations

import numpy as np


def _values_and_valid(values, valid_mask):
    values = np.asarray(values, dtype=float)
    if values.ndim != 1:
        raise ValueError('line values must be one-dimensional')
    valid = np.isfinite(values)
    if valid_mask is not None:
        mask = np.asarray(valid_mask, dtype=bool)
        if mask.shape != values.shape:
            raise ValueError('valid_mask must match line values shape')
        valid &= mask
    return values, valid


def line_amplitude_limits(values, *, amplitude_mode, valid_mask=None):
    """Return padded finite limits or None; validate 1D/equal shapes.

    Masks come from original linear amplitudes; finite deep dB valleys are
    never inferred to be invalid from their distance below a peak.
    """
    values, valid = _values_and_valid(values, valid_mask)
    finite = values[valid]
    if not finite.size:
        return None
    lo, hi = float(np.min(finite)), float(np.max(finite))
    if hi > lo:
        span = hi - lo
        # Scale first only when the subtraction overflows; preserve ordinary
        # range arithmetic and its rounding for engineering-scale values.
        pad = span * 0.05 if np.isfinite(span) else hi * 0.05 - lo * 0.05
    elif 'db' in str(amplitude_mode).lower():
        pad = 1.0
    else:
        pad = abs(lo) * 0.05 if lo else 1.0
    # At float64 limits padding saturates at the representable boundary.
    # Every original finite sample stays covered without emitting infinities.
    largest = float(np.finfo(float).max)
    return max(-largest, lo - pad), min(largest, hi + pad)


def visible_line_values(x, y, xlim, *, valid_mask=None):
    """Return valid in-window values plus finite boundary intersections.

    Only adjacent valid points may form a segment, so NaNs and invalid source
    amplitudes remain gaps. The original arrays are never changed.
    """
    y, valid = _values_and_valid(y, valid_mask)
    x = np.asarray(x, dtype=float)
    if x.ndim != 1 or x.shape != y.shape:
        raise ValueError('x and y must be one-dimensional with equal shapes')
    limits = np.asarray(xlim, dtype=float)
    if limits.shape != (2,) or not np.all(np.isfinite(limits)) or limits[1] < limits[0]:
        raise ValueError('xlim must be a finite ascending pair')
    lo, hi = limits
    valid &= np.isfinite(x)
    result = [y[valid & (x >= lo) & (x <= hi)]]
    adjacent = valid[:-1] & valid[1:]
    for boundary in (lo, hi):
        crossing = adjacent & (((x[:-1] < boundary) & (x[1:] > boundary)) | ((x[:-1] > boundary) & (x[1:] < boundary)))
        indices = np.flatnonzero(crossing)
        fraction = (boundary - x[indices]) / (x[indices + 1] - x[indices])
        result.append(y[indices] * (1.0 - fraction) + y[indices + 1] * fraction)
    return np.concatenate(result)
