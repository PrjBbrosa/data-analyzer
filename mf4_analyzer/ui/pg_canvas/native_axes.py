"""Native WinWert tick facts and millimetre-to-logical-pixel width helpers."""
from __future__ import annotations

import math
from dataclasses import dataclass

_GRID_CAP = 2000
_EDGE_EPS = 1e-12


@dataclass(frozen=True)
class NativeTickLevels:
    major: tuple[tuple[float, str], ...]
    grid: tuple[tuple[float, str], ...]
    adaptive: bool = False
    warning: str | None = None


def line_width_px(line_width_mm: float, logical_dpi: float) -> float:
    """Convert a physical millimetre width to a logical-pixel QPen width."""
    dpi = float(logical_dpi)
    mm = float(line_width_mm)
    if not math.isfinite(dpi) or dpi <= 0.0 or not math.isfinite(mm) or mm <= 0.0:
        return 1.0
    return max(1.0, mm * dpi / 25.4)


def _format_tick(value: float) -> str:
    if value == 0.0:
        return "0"
    text = f"{value:.12g}"
    if text.endswith(".0"):
        return text[:-2]
    return text


def _bounded_index_range(
    lo: float, hi: float, step: float, max_count: int
) -> tuple[int, int] | None:
    """Inclusive index bounds when the candidate count is within max_count.

    Count is proven from finite lo/step and hi/step quotients without
    allocating a tick list. math.ceil/floor convert inf to int and raise
    OverflowError, so non-finite quotients are rejected first. Returns
    None when the count exceeds max_count or cannot be proven bounded.
    An empty but safe range is (0, -1).
    """
    if not math.isfinite(lo) or not math.isfinite(hi) or not math.isfinite(step):
        return None
    if step <= 0.0 or hi <= lo or max_count < 0:
        return None
    ratio_lo = lo / step
    ratio_hi = hi / step
    if not math.isfinite(ratio_lo) or not math.isfinite(ratio_hi):
        return None
    start = math.ceil(ratio_lo - _EDGE_EPS)
    end = math.floor(ratio_hi + _EDGE_EPS)
    if start > end:
        return (0, -1)
    if end - start + 1 > max_count:
        return None
    return (start, end)


def _values_for_step(
    lo: float, hi: float, step: float, *, max_count: int = _GRID_CAP
) -> list[float]:
    bounds = _bounded_index_range(lo, hi, step, max_count)
    if bounds is None:
        return []
    start, end = bounds
    out: list[float] = []
    for index in range(start, end + 1):
        value = index * step
        if lo - _EDGE_EPS <= value <= hi + _EDGE_EPS:
            out.append(float(value))
    return out


def _adaptive_cap() -> NativeTickLevels:
    return NativeTickLevels((), (), adaptive=True, warning="tick_cap")


def native_tick_levels(
    lo: float,
    hi: float,
    major: float | None,
    grid: float | None,
    *,
    max_grid: int = _GRID_CAP,
) -> NativeTickLevels:
    """Major labels plus unlabeled grid facts. Adaptive fallback on overflow."""
    if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
        return NativeTickLevels((), (), adaptive=True, warning="invalid_range")
    major_ok = major is not None and math.isfinite(major) and major > 0.0
    grid_ok = grid is not None and math.isfinite(grid) and grid > 0.0
    if not major_ok and not grid_ok:
        return NativeTickLevels((), (), adaptive=True, warning=None)

    cap = int(max_grid)
    major_step = float(major) if major_ok else None
    grid_step = float(grid) if grid_ok else None
    # Preflight every requested level before enumerating any. A native
    # axis is all-or-nothing: unsafe major or grid falls back together.
    if major_step is not None and _bounded_index_range(lo, hi, major_step, cap) is None:
        return _adaptive_cap()
    if grid_step is not None and _bounded_index_range(lo, hi, grid_step, cap) is None:
        return _adaptive_cap()

    majors: list[tuple[float, str]] = []
    if major_step is not None:
        majors = [
            (value, _format_tick(value))
            for value in _values_for_step(lo, hi, major_step, max_count=cap)
        ]

    grids: list[tuple[float, str]] = []
    if grid_step is not None:
        major_set = {round(value, 12) for value, _ in majors}
        for value in _values_for_step(lo, hi, grid_step, max_count=cap):
            if round(value, 12) in major_set:
                continue
            grids.append((value, ""))

    return NativeTickLevels(tuple(majors), tuple(grids), adaptive=False)


def apply_native_ticks(axis, levels: NativeTickLevels) -> None:
    """Label only the major level; grid labels stay empty strings."""
    if levels.adaptive or axis is None:
        return
    axis.setStyle(maxTickLevel=1)
    axis.setTicks([list(levels.major), list(levels.grid)])
