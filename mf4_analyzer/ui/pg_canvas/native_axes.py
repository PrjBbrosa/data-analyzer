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


def _values_for_step(lo: float, hi: float, step: float) -> list[float]:
    start = math.ceil(lo / step - _EDGE_EPS)
    end = math.floor(hi / step + _EDGE_EPS)
    out: list[float] = []
    for index in range(int(start), int(end) + 1):
        value = index * step
        if lo - _EDGE_EPS <= value <= hi + _EDGE_EPS:
            out.append(float(value))
    return out


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

    majors: list[tuple[float, str]] = []
    if major_ok:
        majors = [
            (value, _format_tick(value))
            for value in _values_for_step(lo, hi, float(major))
        ]

    grids: list[tuple[float, str]] = []
    if grid_ok:
        raw = _values_for_step(lo, hi, float(grid))
        if len(raw) > max_grid:
            return NativeTickLevels(
                (), (), adaptive=True, warning="grid_cap"
            )
        major_set = {round(value, 12) for value, _ in majors}
        for value in raw:
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
