"""Pure tick and range math helpers for the pyqtgraph canvas."""

from __future__ import annotations

import math
from typing import Tuple


def _snap_y_to_divisions(y: float, n: int) -> float:
    """Round ``y`` to the nearest k/n grid boundary."""
    return round(y * n) / n


_NICE_STEP_MANTISSAS = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8]


def _nice_per_div(raw):
    """Return the smallest nice step that is >= ``raw``."""
    try:
        value = float(raw)
    except Exception:
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    exp = math.floor(math.log10(value))
    base = 10.0 ** exp
    mantissa = value / base
    for step in _NICE_STEP_MANTISSAS:
        if step >= mantissa - 1e-9:
            return step * base
    return 10.0 * base


def _adjacent_nice_step(step, direction):
    """Return the neighboring nice step below/above ``step``."""
    current = _nice_per_div(step)
    if current is None:
        return None
    exponent = math.floor(math.log10(current))
    candidates = []
    for exp in range(exponent - 2, exponent + 3):
        base = 10.0 ** exp
        for mantissa in _NICE_STEP_MANTISSAS:
            candidates.append(mantissa * base)
    candidates = sorted(set(candidates))
    tol = max(abs(current) * 1e-9, 1e-12)
    if direction < 0:
        lower = [value for value in candidates if value < current - tol]
        return lower[-1] if lower else current / 10.0
    higher = [value for value in candidates if value > current + tol]
    return higher[0] if higher else current * 10.0


def _fmt_tick(value):
    """Format a graticule tick compactly enough for narrow overlay axes."""
    try:
        value = float(value)
    except Exception:
        return ""
    if not math.isfinite(value):
        return ""
    if value != 0.0 and (abs(value) >= 1e6 or abs(value) < 1e-4):
        return f"{value:.2e}"
    rounded = round(value)
    if abs(value - rounded) < 1e-9:
        return f"{int(rounded)}"
    return f"{value:g}"


def _frame_to_nice(lo, hi, n):
    """Expand ``[lo, hi]`` into ``n`` nice, equal graticule divisions."""
    try:
        lo = float(lo)
        hi = float(hi)
    except Exception:
        lo, hi = 0.0, 0.0
    if hi < lo:
        lo, hi = hi, lo
    n = max(1, int(n))
    span = hi - lo
    if not math.isfinite(span) or span <= 0:
        center = (lo + hi) / 2.0
        if not math.isfinite(center):
            center = 0.0
        span = max(abs(center), 1.0)
        lo = center - span / 2.0
        hi = center + span / 2.0
    per_div = _nice_per_div(span / n) or (span / n)
    bottom = math.floor(lo / per_div) * per_div
    top = bottom + n * per_div
    guard = 0
    while top < hi - max(abs(per_div) * 1e-9, 1e-12) and guard < 64:
        per_div = _nice_per_div(per_div * 1.000001) or (per_div * 2.0)
        bottom = math.floor(lo / per_div) * per_div
        top = bottom + n * per_div
        guard += 1
    ticks = [bottom + k * per_div for k in range(n + 1)]
    return bottom, top, ticks


def _quantize_range_key(
    channel: str,
    xlim: Tuple[float, float],
    pixel_width: int,
) -> Tuple[str, int, int, int]:
    """Return the bucket-quantized cache key for one curve frame."""
    if pixel_width is None or pixel_width < 1:
        pixel_width = 1
    x0, x1 = float(xlim[0]), float(xlim[1])
    if x1 < x0:
        x0, x1 = x1, x0
    span = x1 - x0
    quantum = (span / pixel_width) if span > 0 else 1.0
    if quantum <= 0:
        quantum = 1.0
    qx0 = int(round(x0 / quantum))
    qx1 = int(round(x1 / quantum))
    return (channel, qx0, qx1, int(pixel_width))


__all__ = [
    "_NICE_STEP_MANTISSAS",
    "_snap_y_to_divisions",
    "_nice_per_div",
    "_adjacent_nice_step",
    "_fmt_tick",
    "_frame_to_nice",
    "_quantize_range_key",
]
