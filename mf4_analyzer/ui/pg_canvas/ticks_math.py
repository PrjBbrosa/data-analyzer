"""Pure tick and range math helpers for the pyqtgraph canvas.

The nice-number graticule helpers now live in the shared low-level module
``mf4_analyzer.ui_kit.ticks_math`` so the Cockpit live-card sparklines can
reuse them without importing ``ui.*``. They are re-exported here to preserve
every existing ``pg_canvas.ticks_math`` / ``pg_canvases`` import path. The
viewport-cache key helper ``_quantize_range_key`` stays private to the
pyqtgraph canvas and remains defined below.
"""

from __future__ import annotations

from typing import Tuple

from mf4_analyzer.ui_kit.ticks_math import (  # noqa: F401 re-export
    _NICE_STEP_MANTISSAS,
    _snap_y_to_divisions,
    _nice_per_div,
    _adjacent_nice_step,
    _fmt_tick,
    _frame_to_nice,
    bounded_tick_strings,
    pad_y_extent,
)


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
    "bounded_tick_strings",
    "pad_y_extent",
]
