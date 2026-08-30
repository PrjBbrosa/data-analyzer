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
    """Label only the major level; grid labels stay empty strings.

    Adaptive/invalid/overflow must clear any previous explicit ``_tickLevels``
    so a later WWT View cannot leak cadence onto the next axis.
    """
    if axis is None:
        return
    if levels.adaptive:
        axis.setTicks(None)
        return
    axis.setStyle(maxTickLevel=1)
    axis.setTicks([list(levels.major), list(levels.grid)])


def tag_axis_group(handle, axis_id) -> None:
    """Stamp ``axis_id`` on a handle and its Y AxisItem for restore lookup."""
    handle.axis_group = axis_id
    getter = getattr(handle, "y_axis_item", None)
    axis = getter() if callable(getter) else None
    if axis is not None:
        axis.axis_group = axis_id


def y_axis_items_by_id(canvas) -> dict:
    """Map axis_id → AxisItem from ``axes_list`` handles and overlay aux axes.

    Overlay slots already carry ``axis_group`` as the WWT axis_id. A missing
    id on either the canvas or the native_y table stays adaptive.
    """
    by_id: dict = {}
    for handle in getattr(canvas, "axes_list", None) or ():
        axis_id = getattr(handle, "axis_group", None)
        if axis_id is None:
            continue
        getter = getattr(handle, "y_axis_item", None)
        axis = getter() if callable(getter) else None
        if axis is not None:
            by_id[axis_id] = axis
    overlay = getattr(canvas, "_overlay_axes", None)
    aux_axes = ()
    if overlay is not None:
        aux_axes = (
            getattr(overlay, "aux_axes", None)
            or getattr(overlay, "_overlay_aux_axes", None)
            or ()
        )
    if not aux_axes:
        aux_axes = getattr(canvas, "_overlay_aux_axes", None) or ()
    for aux in aux_axes:
        axis_id = getattr(aux, "axis_group", None)
        if axis_id is None or axis_id in by_id:
            continue
        by_id[axis_id] = aux
    return by_id


def _finite_span(lo, hi) -> tuple[float, float] | None:
    try:
        lo_f, hi_f = float(lo), float(hi)
    except (TypeError, ValueError):
        return None
    if math.isfinite(lo_f) and math.isfinite(hi_f) and hi_f > lo_f:
        return lo_f, hi_f
    return None


def _effective_y_range(handle, axis, spec) -> tuple[object, object]:
    """Prefer the live handle/AxisItem range; spec lo/hi is first-range fallback."""
    if handle is not None:
        getter = getattr(handle, "get_ylim", None)
        if callable(getter):
            try:
                span = _finite_span(*getter())
            except Exception:
                span = None
            if span is not None:
                return span
    rng = getattr(axis, "range", None)
    if rng is not None and len(rng) >= 2:
        span = _finite_span(rng[0], rng[1])
        if span is not None:
            return span
    return spec.get("lo"), spec.get("hi")


def apply_native_y_ticks(canvas, native_y) -> None:
    """Apply owner cadence by axis_id over the current effective range.

    Spec ``lo``/``hi`` are not a permanent clip; they only fill in when the
    handle has no finite viewport yet. Unmatched axes stay adaptive.
    """
    axes_by_id = y_axis_items_by_id(canvas)
    handles_by_id = {}
    for handle in getattr(canvas, "axes_list", None) or ():
        axis_id = getattr(handle, "axis_group", None)
        if axis_id is not None:
            handles_by_id[axis_id] = handle
    for axis_id, spec in (native_y or {}).items():
        axis = axes_by_id.get(axis_id)
        if axis is None or not isinstance(spec, dict):
            continue
        lo, hi = _effective_y_range(handles_by_id.get(axis_id), axis, spec)
        apply_native_ticks(
            axis,
            native_tick_levels(lo, hi, spec.get("major"), spec.get("grid")),
        )
