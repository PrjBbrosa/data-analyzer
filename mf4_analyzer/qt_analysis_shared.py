"""Pure analysis maths and image helpers with no Analyzer UI dependency.

The absolute-dB colour window, the slice amplitude bounds and the smoothed
image item are needed identically by the interactive canvases
(``ui/pg_canvas/``) and by the headless batch Qt renderer
(``batch_render_qt/``), which used to carry its own copies marked
"Copied — not imported". This module is the neutral landing site both sides
import without dragging in ``mf4_analyzer.ui``, following the
``qt_plot_helpers.py`` precedent.

Importing this module must never pull in ``mf4_analyzer.ui`` — that is the
whole point of it existing, and
``tests/test_batch_render_import_boundary.py`` asserts it in a subprocess.
So keep the imports below limited to numpy/pyqtgraph/PyQt5.

Moved verbatim out of ``ui/pg_canvas/analysis_axes.py``, which now re-exports
every name here so existing import paths keep resolving. ``batch_render_qt``
has since dropped its duplicates of ``_SLICE_MAX_SPAN_DB``,
``_slice_amp_bounds`` and ``_SmoothImageItem`` and imports them from here, so
a change to those three lands on both sides at once — the render-parity
matrix (``tools/verify_batch_qt_render_parity.py``) is what proves it stays
safe. The diff audit that cleared the switch is
``docs/analyzer/verify/batch-analysis-maths-dedup.md``.

One family is deliberately still forked: the batch renderer keeps its own
``_auto_db_color_limits`` rather than using ``_auto_db_window`` here. They
agree on real data but not on empty/all-NaN input, where batch falls back to
its ``_EMPTY_DB_LEVEL`` (-200 dB) baseline and this module falls back to
``_finite_data_bounds``. Unifying them means picking one empty-state
semantics, which is its own piece of work.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt5.QtGui import QPainter


# 热力图默认色图。交互画布和批处理渲染器必须用同一个值，否则同一份数据在
# 单文件里是一种配色、导出的 PNG 里是另一种——用户看到的是「色阶不一致」。
# 批处理侧以前硬编码 "turbo"，而画布侧是 "gnuplot2"；常量放在这个中立模块里，
# 两边各自 import，谁也不能再单方面漂移（``batch_render_qt`` 不允许 import
# ``mf4_analyzer.ui``，所以不能直接引画布里的常量）。
DEFAULT_HEATMAP_CMAP = "gnuplot2"
SUPPORTED_HEATMAP_COLORMAPS = (
    DEFAULT_HEATMAP_CMAP,
    "turbo",
    "viridis",
    "plasma",
    "inferno",
    "magma",
    "cividis",
)


def _gnuplot2_lut() -> np.ndarray:
    """Return Matplotlib gnuplot2's documented 256-entry RGBA LUT.

    The channel transfer functions are ported locally so the desktop runtime
    remains independent of Matplotlib.  Values are clipped after evaluating
    the original piecewise functions, then quantised exactly as a byte LUT.
    """
    x = np.linspace(0.0, 1.0, 256)
    red = np.clip(x / 0.32 - 0.78125, 0.0, 1.0)
    green = np.clip(2.0 * x - 0.84, 0.0, 1.0)
    blue = np.where(
        x < 0.25,
        4.0 * x,
        np.where(x < 0.92, -2.0 * x + 1.84, x / 0.08 - 11.5),
    )
    blue = np.clip(blue, 0.0, 1.0)
    rgba = np.column_stack((red, green, blue, np.ones_like(x)))
    return np.rint(rgba * 255.0).astype(np.ubyte)


_GNUPLOT2_COLORMAP = pg.ColorMap(
    np.linspace(0.0, 1.0, 256), _gnuplot2_lut(), name=DEFAULT_HEATMAP_CMAP,
)


def _normalise_colormap_name(name: str | None) -> str:
    requested = str(name or DEFAULT_HEATMAP_CMAP)
    return requested if requested in SUPPORTED_HEATMAP_COLORMAPS else DEFAULT_HEATMAP_CMAP


def _resolve_colormap(name: str) -> pg.ColorMap:
    """Resolve a supported heatmap map without a Matplotlib dependency."""
    requested = _normalise_colormap_name(name)
    if requested == DEFAULT_HEATMAP_CMAP:
        return _GNUPLOT2_COLORMAP
    try:
        cm = pg.colormap.get(requested)
        if cm is not None:
            return cm
    except Exception:
        pass
    return _GNUPLOT2_COLORMAP


def _finite_data_bounds(matrix):
    arr = np.asarray(matrix, dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return 0.0, 1.0
    lo = float(np.nanmin(finite))
    hi = float(np.nanmax(finite))
    if hi <= lo:
        hi = lo + 1.0
    return lo, hi


# Default dynamic range span used by the *absolute-dB* auto color window
# (plot_result path, FFT-vs-Time and Order).  The canvas normalises to
# [ceiling - _AUTO_SPAN_DB, ceiling] (ceiling = _robust_db_ceiling, below)
# so the "auto" and "manual-after-write-back" windows are identical —
# eliminating the 30+ dB jump that occurred when the old code treated
# z_floor/z_ceiling as *peak offsets* while the manual path used them as
# *absolute* dB values.
#
# Deliberately NOT read from the inspector's z_floor/z_ceiling: reading
# from those fields would make the auto window depend on spin state and
# re-introduce a feedback loop.  A fixed span is predictable and safe.
# Default 30 dB — the window most noise analysis uses; high-dynamic-range data
# may later auto-widen toward 40 dB (Phase A2 of the auto-color-span plan).
_AUTO_SPAN_DB: float = 30.0

# Percentile used to anchor the *ceiling* of the absolute-dB auto window
# (plot_result path, FFT-vs-Time and Order).  Real measurement spectra have
# sharp transient peaks 30-40 dB above the informative bulk; anchoring the
# auto ceiling at the literal data MAX (np.nanmax) put the whole field below
# the floor → an all-dark image the user had to drag down ~38 dB to read.
# Using a high percentile makes the ceiling track the top of the *bulk*
# instead of a lone outlier, so "自动" lands where the user actually wants it.
# For well-behaved data with no outliers, the 99th percentile ≈ max, so this
# is a no-op there and only kicks in when there is a heavy upper tail.
_AUTO_CEILING_PCT: float = 99.0


def _robust_db_ceiling(matrix, pct=_AUTO_CEILING_PCT):
    """Return a high-percentile ceiling for the absolute-dB auto window.

    Robust to the outlier transient peaks common in real measurement data:
    unlike ``np.nanmax`` it ignores the top ``(100 - pct)``% of cells, so a
    handful of bright spikes no longer drag the whole colour window up and
    bury the informative bulk below the floor.  NaN/inf-safe (matches
    ``_finite_data_bounds``); falls back to that bound when the matrix has
    no finite values.
    """
    arr = np.asarray(matrix, dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return _finite_data_bounds(matrix)[1]
    return float(np.percentile(finite, pct))


def _auto_db_window(matrix):
    """Single source for the absolute-dB auto colour window → ``(vmin, vmax)``.

    ceiling = robust high-percentile (``_robust_db_ceiling``, anti-transient);
    span = ``_AUTO_SPAN_DB`` below it. Both the heatmap ``z_auto`` path and the
    Order render override resolve the window here, so the two can never drift
    apart (the recurring compute-vs-display split). Display-only: callers clamp
    COLOURS to this window, never the stored matrix.
    """
    ceiling = _robust_db_ceiling(matrix, _AUTO_CEILING_PCT)
    return ceiling - _AUTO_SPAN_DB, ceiling


# Widest dynamic range a real measurement slice can plausibly span. Bins more
# than this far below the slice's top are numerically-dead artifacts: the 0 Hz
# DC bin, zeroed by de-mean and/or A-weighting (gain == 0 at f == 0), then
# floored by ``amplitude_to_db`` to ``20*log10(np.finfo(float).tiny)`` ≈
# -6153 dB. A 24-bit acquisition has only ~144 dB of range, so 200 dB only ever
# catches such dead bins, never real signal (e.g. a deep anti-resonance notch).
_SLICE_MAX_SPAN_DB: float = 200.0


def _slice_amp_bounds(values):
    """Robust ``(lo, hi)`` for the slice amplitude *view* axis, or ``None``.

    Display-only: the slice curve is always drawn in full (``setData`` is
    untouched); this only picks the Y *view* range. The top is the literal max
    (a line plot should show real peaks, unlike the colour window). The bottom
    ignores numerically-dead bins sitting more than ``_SLICE_MAX_SPAN_DB`` below
    the top, so a single DC bin floored to ≈ -6153 dB can no longer crush the
    real -40..-60 dB signal into a thin band at the top of the panel. NaN/inf
    -safe. Returns ``None`` when there is no finite spread to fit (the caller
    then falls back to pyqtgraph auto-range)."""
    arr = np.asarray(values, dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return None
    hi = float(np.max(finite))
    real = finite[finite >= hi - _SLICE_MAX_SPAN_DB]
    lo = float(np.min(real)) if real.size else hi
    if hi <= lo:
        return None
    return lo, hi


class _SmoothImageItem(pg.ImageItem):
    """ImageItem that honors mpl-style interpolation hints via QPainter."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._smooth_transform = False

    def set_smooth_transform(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._smooth_transform == enabled:
            return
        self._smooth_transform = enabled
        self.update()

    def smooth_transform_enabled(self) -> bool:
        return self._smooth_transform

    def paint(self, painter, *args):
        previous = painter.testRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, self._smooth_transform)
        try:
            return super().paint(painter, *args)
        finally:
            painter.setRenderHint(QPainter.SmoothPixmapTransform, previous)
