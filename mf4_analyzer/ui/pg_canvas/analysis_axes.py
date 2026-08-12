"""Axis, tick and dB-display helpers shared by the analysis canvases.

The FFT line canvas (``line_canvas.py``) and the FFT-vs-Time / Order
heatmap canvases (``heatmap_canvas.py``) draw the same kind of chart: a
neutral four-sided frame, major-only grid, target-count bottom ticks, and
— for the heatmaps — an absolute-dB colour window. This module owns that
shared layer. The time-domain canvas (``canvas.py``) does NOT use it; it
keeps its own tick pipeline in ``tick_density.py``.

Extracted verbatim from ``heatmap_canvas.py``, where this layer had grown
into a de-facto shared library that ``line_canvas.py`` imported backwards
— every axis fix had to land inside a 3000-line heatmap file. Behaviour is
unchanged by the move; ``heatmap_canvas`` re-exports every name here so
the old import paths keep resolving.

The Qt-free subset of the maths (the absolute-dB window, the slice
amplitude bounds and ``_SmoothImageItem``) has since sunk one level
further, into ``mf4_analyzer.qt_analysis_shared``, so the headless batch
renderer can share it without importing ``mf4_analyzer.ui``. It is
re-exported below and is still reachable under its original name here.
"""
from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PyQt5.QtGui import QFontMetrics
from PyQt5.QtWidgets import QWidget

# The pure dB/amplitude maths and the smoothed image item now live in a
# UI-free module so the headless batch renderer can share them (it currently
# keeps its own copies). They are re-exported here — unqualified, exactly as
# before — so every existing path keeps working: line_canvas imports
# _AUTO_SPAN_DB/_AUTO_CEILING_PCT from here, heatmap_canvas re-exports the
# whole set onward, and `hc._auto_db_window`-style module-attribute access in
# the tests still resolves.
from mf4_analyzer.qt_analysis_shared import (  # noqa: F401
    _AUTO_CEILING_PCT,
    _AUTO_SPAN_DB,
    _SLICE_MAX_SPAN_DB,
    _SmoothImageItem,
    _auto_db_window,
    _finite_data_bounds,
    _robust_db_ceiling,
    _slice_amp_bounds,
)
from mf4_analyzer.qt_chart_fonts import CHART_FONT_PT
from mf4_analyzer.ui._axis_handle import (
    PG_AXIS_NEUTRAL_COLOR,
    PG_AXIS_NEUTRAL_WIDTH,
)
from mf4_analyzer.ui.pg_canvas._shared import (
    GridLabelSlackAxisItem,
    _hide_native_auto_button,
)
from mf4_analyzer.ui.pg_canvas.fonts import _apply_pg_axis_font, _pg_chart_font


def _tick_counts_to_density(x_n: int, y_n: int) -> tuple:
    """Convert inspector tick COUNTS to pg tick-density factors.

    Replicates the count->density convention of the time-domain canvas
    (pg_canvas/tick_density.py: x_n/10.0 adaptive fallback at :123,
    y_n/6.0 at :69, both clamped to [0.35, 3.0]) so every pg canvas
    responds identically to the PersistentTop spinboxes (x 3-30 default
    10, y 3-20 default 10). tick_density.py keeps these formulas inline
    in `TickDensityController` (backref-bound to the time-domain
    canvas), so they cannot be imported directly; keep both in sync.
    """
    x_d = max(0.35, min(3.0, float(x_n) / 10.0))
    y_d = max(0.35, min(3.0, float(y_n) / 6.0))
    return x_d, y_d


def _finite_float(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


# Fraction of cells that must fall inside the visible colour gradient for the
# heatmap to read as "alive". Below this, the colour window has collapsed the
# image to ~one flat colour (all dark / all bright) and the colorbar-reset nudge
# should offer a way out. NOTE: perceptual threshold — tune on-device.
_COLORBAR_DEAD_VISIBLE_FRAC = 0.01


def _colorbar_is_dead(matrix, lo, hi):
    """True if the colour window (lo, hi) leaves the heatmap with ~no contrast.

    A healthy spectrogram keeps a meaningful fraction of cells in the mid
    gradient (features + halos); a window dragged off the data clamps nearly
    every cell to one end → a flat, single-colour image. Display-only: this
    inspects the colour mapping, never the data.
    """
    if matrix is None:
        return False
    if not (hi > lo):
        return True  # degenerate window → no contrast at all
    m = np.asarray(matrix, dtype=float)
    finite = m[np.isfinite(m)]
    if finite.size == 0:
        return False
    norm = (finite - lo) / (hi - lo)
    visible = int(np.count_nonzero((norm > 0.02) & (norm < 0.98)))
    return (visible / finite.size) < _COLORBAR_DEAD_VISIBLE_FRAC


def time_axis_display_extent(times, *, params=None, metadata=None, fallback=None):
    """Return the displayed X extent for time-window heatmaps.

    ``times`` are frame centers. When analyzer metadata carries the real
    window coverage, prefer that so the image spans the analyzed time range
    rather than stopping at the first/last center.
    """
    md = metadata or {}
    lo = _finite_float(md.get('coverage_start'))
    hi = _finite_float(md.get('coverage_end'))
    if lo is not None and hi is not None and hi > lo:
        return lo, hi

    arr = np.asarray(times, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size:
        fs = _finite_float(getattr(params, 'fs', None))
        try:
            nfft = int(getattr(params, 'nfft'))
        except (TypeError, ValueError):
            nfft = 0
        if fs is not None and fs > 0 and nfft > 1:
            half_window = (nfft - 1) / (2.0 * fs)
            lo = float(arr[0] - half_window)
            if arr[0] >= 0.0:
                lo = max(0.0, lo)
            return lo, float(arr[-1] + half_window)
        if arr.size >= 2:
            left_half = (arr[1] - arr[0]) / 2.0
            right_half = (arr[-1] - arr[-2]) / 2.0
            lo = float(arr[0] - left_half)
            if arr[0] >= 0.0:
                lo = max(0.0, lo)
            return lo, float(arr[-1] + right_half)
        return float(arr[0]), float(arr[0])

    if fallback is not None:
        return float(fallback[0]), float(fallback[1])
    return 0.0, 0.0


_TARGET_BOTTOM_TICK_NICE_FACTORS = (1.0, 2.0, 2.5, 5.0, 10.0)
_TARGET_BOTTOM_TICK_MIN_GAP_PX = 10.0
_TARGET_BOTTOM_TICK_MIN_NARROW_GAP_PX = 0.0
_TARGET_BOTTOM_TICK_EDGE_PAD_PX = 2.0
_TARGET_BOTTOM_TICK_MIN_COUNT = 3


def _apply_target_bottom_ticks(
    axis, view_box, target_count: int, owner: QWidget | None = None
) -> bool:
    """Pin bottom-axis ticks to a readable target count when geometry exists."""
    try:
        if owner is not None and not owner.isVisible():
            return False
        (lo, hi), _yr = view_box.viewRange()
        width = float(axis.size().width())
    except Exception:
        return False
    lo = float(lo)
    hi = float(hi)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return False
    if width <= 1.0:
        return False

    target = max(_TARGET_BOTTOM_TICK_MIN_COUNT, int(target_count))
    raw_step = (hi - lo) / max(1, target - 1)
    if not np.isfinite(raw_step) or raw_step <= 0:
        return False

    metrics = QFontMetrics(_pg_chart_font(CHART_FONT_PT))
    extreme_narrow = width < target * 8.0
    min_gap = (
        _TARGET_BOTTOM_TICK_MIN_NARROW_GAP_PX
        if extreme_narrow else
        min(
            _TARGET_BOTTOM_TICK_MIN_GAP_PX,
            max(
                _TARGET_BOTTOM_TICK_MIN_NARROW_GAP_PX,
                width / max(1.0, target * 6.0),
            ),
        )
    )
    edge_pad = 0.0 if extreme_narrow else _TARGET_BOTTOM_TICK_EDGE_PAD_PX
    candidates = []
    exponent = math.floor(math.log10(raw_step))
    for exp in range(exponent - 2, exponent + 4):
        scale = 10.0 ** exp
        for factor in _TARGET_BOTTOM_TICK_NICE_FACTORS:
            step = factor * scale
            if step <= 0:
                continue
            start = math.ceil(lo / step) * step
            values = []
            value = start
            guard = 0
            while value <= hi + step * 1e-9 and guard < 500:
                if value >= lo - step * 1e-9:
                    values.append(
                        0.0 if abs(value) < step * 1e-10 else float(value)
                    )
                value += step
                guard += 1
            if len(values) < _TARGET_BOTTOM_TICK_MIN_COUNT:
                continue
            try:
                labels = axis.tickStrings(
                    values,
                    getattr(axis, "scale", 1.0),
                    step,
                )
            except Exception:
                labels = [f"{value:g}" for value in values]

            previous_right = None
            fitted = []
            too_dense = False
            for tick_value, label in zip(values, labels):
                x_pos = (float(tick_value) - lo) / (hi - lo) * width
                text = str(label)
                try:
                    text_width = float(metrics.horizontalAdvance(text))
                except AttributeError:  # pragma: no cover - older Qt fallback
                    text_width = float(metrics.width(text))
                left = x_pos - text_width / 2.0
                right = x_pos + text_width / 2.0
                if left < edge_pad:
                    continue
                if right > width - edge_pad:
                    continue
                if previous_right is not None and left - previous_right < min_gap:
                    # Interior labels collide → this step is too fine. Reject the
                    # WHOLE candidate rather than thinning it: a thinned over-fine
                    # step (e.g. 0.01) yields non-round, truncated ticks (0.21,
                    # 0.69, …) that can hit the target count exactly and beat the
                    # genuine nice steps, leaving the right edge tickless. This
                    # mirrors tick_density.py:_fit_x_tick_labels, whose `return
                    # None` is why the time-domain axis never had this bug. In
                    # extreme-narrow mode min_gap is 0 and thinning is the only
                    # way to fit any labels, so keep skipping there.
                    if extreme_narrow:
                        continue
                    too_dense = True
                    break
                fitted.append((float(tick_value), text))
                previous_right = right
            if too_dense or len(fitted) < _TARGET_BOTTOM_TICK_MIN_COUNT:
                continue
            candidates.append((
                abs(len(fitted) - target),
                -len(fitted),
                abs(math.log(step / raw_step)) if raw_step > 0 else 0.0,
                fitted,
            ))

    if not candidates:
        return False
    _distance, _neg_count, _nice_distance, ticks = min(candidates)
    try:
        axis.setStyle(maxTickLevel=0)
        axis.setTicks([ticks, []])
    except Exception:
        return False
    return True


def _apply_axis_tick_density(axis, density: float) -> None:
    try:
        axis.setTicks(None)
    except Exception:
        pass
    axis.setStyle(maxTickLevel=0)
    axis.setTickDensity(density)


def _visual_padded_bounds(lo: float, hi: float, *, fraction: float = 0.015) -> tuple:
    """Return a small display margin around full data bounds.

    Home/View-All should include every data point without placing boundary
    tick labels directly on the plot frame. Keep this visual-only margin tiny
    so reset still reads as "full data range" to the user.
    """
    lo = float(lo)
    hi = float(hi)
    if not np.isfinite(lo) or not np.isfinite(hi):
        return lo, hi
    span = hi - lo
    if span <= 0:
        return lo, hi
    pad = span * float(fraction)
    return lo - pad, hi + pad


# Pixel tolerance for "this grid line sits on the view boundary". The
# outermost grid line lands within ~1px of the linked-view rect edge; widen
# slightly so a sub-pixel layout rounding never lets the boundary line slip
# through. Internal grid lines are many px away so they are never touched.
_BOUNDARY_GRID_EPS_PX = 1.5


class _BoundaryGridAxisItem(GridLabelSlackAxisItem):
    """AxisItem that suppresses ONLY the outermost (view-boundary) grid line.

    Base class note: it derives from ``GridLabelSlackAxisItem`` (not plain
    ``pg.AxisItem``) so the LEFT instance also keeps the vertical tick-label
    slack that pyqtgraph's grid branch drops — without it the top/bottom Y
    tick VALUES disappear as soon as the grid is on (D2). The two behaviours
    are orthogonal: this class drops a boundary grid LINE, the base restores
    boundary tick TEXT.

    Analysis plots keep explicit Y/X whitespace (e.g. the empty-state
    ``setYRange(0, 1, padding=0.08)`` and pyqtgraph's autorange margin in the
    data state) so the highest/lowest tick is NOT flush with the frame. With a
    grid enabled, that boundary tick still draws a long grid line right next to
    the neutral frame line → it reads as a "double line" at the top/bottom
    edge (spec R2 side effect). The product decision (confirmed with the user)
    is to KEEP the padding but drop the grid line that is glued to the frame,
    leaving one frame line + interior grid lines.

    Implementation: ``generateDrawSpecs`` returns ``(axisSpec, tickSpecs,
    textSpecs)`` where each tickSpec is ``(pen, p1, p2)`` and — when the grid
    is on — the line spans the linked-view rect. The grid line's position
    along the VALUE axis is ``point[1 - axis]`` (axis=0 for left/right →
    value is Y; axis=1 for top/bottom → value is X). We drop any spec whose
    value-position is within ``_BOUNDARY_GRID_EPS_PX`` of the linked-view rect
    edge. Short ticks (grid off) are unaffected because their spans never
    reach the rect edges the same way; left+bottom carry the grid here.
    """

    def generateDrawSpecs(self, p):
        specs = super().generateDrawSpecs(p)
        # generateDrawSpecs returns None when the axis has no realized
        # geometry; pass that through unchanged (drawPicture handles None).
        if specs is None or self.grid is False:
            return specs
        axis_spec, tick_specs, text_specs = specs
        linked = self.linkedView()
        if linked is None:
            return specs
        try:
            rect = linked.mapRectToItem(self, linked.boundingRect())
        except Exception:
            return specs
        # axis index along which the tick line extends: 0 for left/right
        # (vertical axis → value runs in Y), 1 for top/bottom (value in X).
        axis = 0 if self.orientation in ('left', 'right') else 1
        if axis == 0:
            lo, hi = rect.top(), rect.bottom()
        else:
            lo, hi = rect.left(), rect.right()
        eps = _BOUNDARY_GRID_EPS_PX
        kept = []
        for pen, p1, p2 in tick_specs:
            # The value-position is the coordinate NOT pinned to tickStart/
            # tickStop; both points share it, so read it off p1.
            value_pos = p1[1 - axis]
            if abs(value_pos - lo) <= eps or abs(value_pos - hi) <= eps:
                continue  # boundary grid line glued to the frame — drop it
            kept.append((pen, p1, p2))
        return axis_spec, kept, text_specs


class _FrfBottomAxisItem(_BoundaryGridAxisItem):
    """FRF-only bottom axis: labelled majors plus visible log minor grids."""

    def set_frf_log_ticks(self, major_ticks, minor_values) -> None:
        self._frf_minor_tick_values = tuple(float(value) for value in minor_values)
        self.setTicks([
            list(major_ticks),
            [(float(value), "") for value in self._frf_minor_tick_values],
        ])

def _make_analysis_plot(glw, row, col, view_box, *, frf_bottom_axis=False):
    """Add a PlotItem whose left+bottom axes use ``_BoundaryGridAxisItem`` so the
    outermost grid line never doubles up with the neutral frame.

    Top/right stay default AxisItems (they carry no grid — ``setGrid(False)`` /
    ``_apply_neutral_axis_frame`` keep them as plain frame lines). The custom
    axes inherit every later mutation (``_apply_neutral_axis_frame`` pen/style,
    ``set_tick_density``) because they are ordinary AxisItem subclasses."""
    return glw.addPlot(
        row=row, col=col,
        viewBox=view_box,
        axisItems={
            'left': _BoundaryGridAxisItem(orientation='left'),
            'bottom': (
                _FrfBottomAxisItem(orientation='bottom')
                if frf_bottom_axis else _BoundaryGridAxisItem(orientation='bottom')
            ),
        },
    )


def _apply_neutral_axis_frame(plot) -> None:
    """Draw a full frame with axes, avoiding ViewBox border/axis overlap."""
    _hide_native_auto_button(plot)
    vb = plot.getViewBox()
    # pg 0.14 setBorder(None) stores a NoPen QPen, so ViewBox.paint still
    # enters its border branch. Clear the private value after resetting the
    # auxiliary border item so the visible frame is composed only from axes.
    vb.setBorder(None)
    vb.border = None
    frame_pen = pg.mkPen(
        color=PG_AXIS_NEUTRAL_COLOR,
        width=PG_AXIS_NEUTRAL_WIDTH,
    )
    for side in ('left', 'bottom', 'top', 'right'):
        axis = plot.getAxis(side)
        try:
            axis.enableAutoSIPrefix(False)
        except Exception:
            pass
        _apply_pg_axis_font(axis)
        axis.setPen(frame_pen)
        if side in ('left', 'bottom'):
            # 2026-06-13: major grid only. pyqtgraph's default maxTickLevel
            # (2) draws faint minor (sub-)grid lines at tick levels 1-2; the
            # analysis canvases (FFT line + FFT-vs-Time / Order heatmaps)
            # should match the time-domain grid, which shows major lines only.
            # ``set_tick_density`` re-asserts maxTickLevel=0, but pin it here at
            # construction so the FIRST rendered frame (before any density
            # change) is already major-only instead of flashing the sub-grid.
            try:
                axis.setStyle(maxTickLevel=0)
            except Exception:
                pass
    for side in ('top', 'right'):
        axis = plot.getAxis(side)
        plot.showAxis(side)
        axis.setStyle(showValues=False, tickLength=0, maxTickLevel=0)
        axis.setLabel('')
    plot.getAxis('top').setHeight(1)
    plot.getAxis('right').setWidth(1)


def _hide_plot_title(plot) -> None:
    """Remove pyqtgraph's title row so analysis plots keep maximum height."""
    try:
        plot.setTitle(None)
    except Exception:
        try:
            plot.setTitle("")
        except Exception:
            pass
    label = getattr(plot, "titleLabel", None)
    if label is None:
        return
    for name, value in (
        ("setMinimumHeight", 0),
        ("setMaximumHeight", 0),
        ("setPreferredHeight", 0),
    ):
        setter = getattr(label, name, None)
        if callable(setter):
            try:
                setter(value)
            except Exception:
                pass
    try:
        label.setVisible(False)
    except Exception:
        pass
    for name in ("updateMin", "updateGeometry"):
        updater = getattr(label, name, None)
        if callable(updater):
            try:
                updater()
            except Exception:
                pass
