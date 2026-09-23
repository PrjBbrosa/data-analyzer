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

Finite colour windows are ``_auto_db_window``, including the batch
helper's real-data branch. Empty / all-non-finite input is still forked:
batch falls back to its ``_EMPTY_DB_LEVEL`` (-200 dB) baseline, and this
module returns ``None`` so interactive callers take an explicit no-data
branch (B5). The span, percentile and ceiling-headroom constants
(``_AUTO_SPAN_DB`` / ``_AUTO_CEILING_PCT`` /
``_AUTO_CEILING_HEADROOM_DB``) live here.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt5.QtGui import QPainter

from mf4_analyzer.ui_kit.ticks_math import _DEGENERATE_SPAN_RATIO


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

# Heatmap interpolation default + the set that enables SmoothPixmapTransform.
# Interactive canvas (``heatmap_canvas``) and the batch Qt renderer must share
# these — batch has no interp control, so a silent default fork would paint
# different ink for the same matrix (the pre-cmap-bug failure mode).
DEFAULT_HEATMAP_INTERP = "bilinear"
HEATMAP_SMOOTH_INTERP_MODES = frozenset({"bilinear", "bicubic", "hanning"})


def heatmap_interp_is_smooth(interp) -> bool:
    """Return whether ``interp`` should enable smooth pixmap transforms."""
    mode = (
        DEFAULT_HEATMAP_INTERP
        if interp is None
        else str(interp).strip().lower()
    )
    return mode in HEATMAP_SMOOTH_INTERP_MODES


def default_amplitude_mode_for_kind(kind: str) -> str:
    """Product default when a recipe omits ``amplitude_mode``.

    FFT-vs-Time and Order match the GUI inspector default (dB). Plain FFT
    stays linear. This is the parity fix for Order batch vs single-file.
    """
    if str(kind) in {"fft_time", "order_time"}:
        return "amplitude_db"
    return "amplitude"


def amplitude_mode_is_db(mode) -> bool:
    """True when an amplitude-mode token requests a dB axis.

    Covers the three historical dialects in one place: substring ``'db'``
    (batch ``_render_in_db`` / ``batch_output_scale``), exact
    ``'amplitude_db'`` (heatmap token), and ``'Amplitude dB'`` (Order
    inspector label).
    """
    return "db" in str(mode or "").lower()


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
    """Return ``(lo, hi)`` over finite cells, or ``None`` when there are none.

    Degenerate / residue-only spans (relative to
    ``ui_kit.ticks_math._DEGENERATE_SPAN_RATIO``) are widened by 1.0 so a
    float64 channel-math constant does not become a 1e-16-wide colour
    window (B5). All-non-finite input returns ``None`` — callers take the
    no-data branch; this helper does not invent ``0..1``.
    """
    arr = np.asarray(matrix, dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return None
    lo = float(np.nanmin(finite))
    hi = float(np.nanmax(finite))
    span = hi - lo
    magnitude = max(abs(lo), abs(hi))
    if not (span > magnitude * _DEGENERATE_SPAN_RATIO and span > 0.0):
        hi = lo + 1.0
    return lo, hi


# Floor offset of the absolute-dB auto colour window (FFT-vs-Time and Order,
# interactive and batch). The floor is ``percentile - _AUTO_SPAN_DB``. It is
# not read from the inspector spins: that would couple the auto window to
# spin state and re-introduce the old auto/manual feedback loop.
# 30 dB is the window most noise analysis uses.
_AUTO_SPAN_DB: float = 30.0

# Percentile that anchors the floor, and the reference for the ceiling
# headroom. Real spectra have transient peaks 30-40 dB above the bulk;
# anchoring the ceiling on the literal maximum buried that bulk below the
# floor. The 99th percentile tracks the top of the bulk. It is not itself
# the colour-scale maximum — see ``_AUTO_CEILING_HEADROOM_DB``.
_AUTO_CEILING_PCT: float = 99.0

# How far above the percentile the colour scale may extend, before it is
# capped at the finite maximum. A bright ridge within this headroom stays
# on the scale instead of pinning to the top colour. The floor does not
# move with this offset. 5 dB is enough to show that near-percentile energy
# has not run off the top, without giving a lone transient the scale.
_AUTO_CEILING_HEADROOM_DB: float = 5.0


def _robust_db_ceiling(matrix, pct=_AUTO_CEILING_PCT):
    """Return a high-percentile ceiling for the absolute-dB auto window.

    Robust to the outlier transient peaks common in real measurement data:
    unlike ``np.nanmax`` it ignores the top ``(100 - pct)``% of cells, so a
    handful of bright spikes no longer drag the whole colour window up and
    bury the informative bulk below the floor.  NaN/inf-safe (matches
    ``_finite_data_bounds``); returns ``None`` when the matrix has no finite
    values (callers take the no-data branch — B5).
    """
    arr = np.asarray(matrix, dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return None
    return float(np.percentile(finite, pct))


def _auto_db_window(matrix):
    """Single source for the absolute-dB auto colour window → ``(vmin, vmax)``.

    Floor = robust percentile − ``_AUTO_SPAN_DB``. Ceiling = that percentile
    + ``_AUTO_CEILING_HEADROOM_DB``, capped at the finite maximum so the
    scale never extends past data that exists. A transient far above the
    percentile still saturates; energy within the headroom does not pin to
    the top colour, and the floor stays put. The heatmap ``z_auto`` path,
    the Order render override and the batch renderer's finite-data branch
    all resolve the window here. Display-only: callers clamp colours, never
    the stored matrix. Returns ``None`` when nothing is finite (B5).
    """
    anchor = _robust_db_ceiling(matrix, _AUTO_CEILING_PCT)
    if anchor is None:
        return None
    finite = np.asarray(matrix, dtype=float)
    finite = finite[np.isfinite(finite)]
    peak = float(np.max(finite))
    return (
        anchor - _AUTO_SPAN_DB,
        min(peak, anchor + _AUTO_CEILING_HEADROOM_DB),
    )


# Retained for compatibility only; never used to identify invalid line values.
_SLICE_MAX_SPAN_DB: float = 200.0


def _slice_amp_bounds(values, *, amplitude_mode="amplitude_db", valid_mask=None):
    """Compatibility entry returning padded line limits with explicit mode."""
    from mf4_analyzer.signal.display_ranges import line_amplitude_limits

    return line_amplitude_limits(
        values, amplitude_mode=amplitude_mode, valid_mask=valid_mask
    )


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
