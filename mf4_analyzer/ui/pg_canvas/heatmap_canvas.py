"""PgHeatmapCanvas: pyqtgraph heatmap canvas for the Order and
FFT-vs-Time sections.

Replaces ``PlotCanvas.plot_or_update_heatmap`` (canvases.py:2178) and —
with ``with_slice=True`` — ``SpectrogramCanvas`` (canvases.py:1602).
API names/kwargs mirror the matplotlib originals so MainWindow render
paths keep their call sites.

dB semantics are a line-for-line port of canvases.py:2221-2244.
NO OpenGL anywhere here: OpenGL breaks grab_pixmap exports (all-white,
verified on the time-domain canvas history).
"""
from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFontMetrics, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui._axis_handle import (
    PG_AXIS_NEUTRAL_COLOR,
    PG_AXIS_NEUTRAL_WIDTH,
)
from mf4_analyzer.ui.pg_canvas.context_menu import redesign_pg_context_menu
from mf4_analyzer.ui.pg_canvas._shared import (
    _hide_native_auto_button,
    show_major_grid_left_bottom_only,
)
from mf4_analyzer.ui.pg_canvas._split_mixin import (
    _CollapsedRail,
    _SPLIT_COLLAPSE_AT,
    _SPLIT_MIN_BOTTOM,
    _SPLIT_MIN_TOP,
    _SPLIT_ROW_SPACING,
    _SplitDivider,
    _StackedSplitMixin,
)
from mf4_analyzer.ui.pg_canvas.fonts import _apply_pg_axis_font, _pg_chart_font
from mf4_analyzer.ui.pg_canvas.viewbox import _ModifierWheelViewBox


class _SliceDirToggle(QWidget):
    """Two-segment X/Y slice-direction switch overlaid on the slice view's
    top-right corner. ``direction_changed`` emits 'x' or 'y'.

    'x' = fix a position on the X axis (a time) → slice shows amplitude vs the
    Y axis (frequency / order). 'y' = fix a position on the Y axis → slice
    shows amplitude vs time. The two button labels are supplied by the owner so
    FFT-vs-Time reads 「按时间 / 按频率」 and Order reads 「按时间 / 按阶次」.
    """

    direction_changed = pyqtSignal(str)

    def __init__(self, x_label, y_label, parent=None):
        super().__init__(parent)
        self.setObjectName("sliceDirToggle")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        self._btn_x = QPushButton(x_label, self)
        self._btn_y = QPushButton(y_label, self)
        for b, d in ((self._btn_x, 'x'), (self._btn_y, 'y')):
            b.setCheckable(True)
            b.setProperty("role", "slice-seg")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, _d=d: self.set_direction(_d))
            box.addWidget(b, 1)  # split the panel width evenly
        self._dir = 'x'
        self._sync_buttons()

    def direction(self):
        return self._dir

    def set_direction(self, d, *, emit=True):
        d = 'y' if d == 'y' else 'x'
        if d == self._dir:
            self._sync_buttons()
            return
        self._dir = d
        self._sync_buttons()
        if emit:
            self.direction_changed.emit(d)

    def _sync_buttons(self):
        self._btn_x.setChecked(self._dir == 'x')
        self._btn_y.setChecked(self._dir == 'y')


def _resolve_colormap(name: str) -> pg.ColorMap:
    """Map the inspector's matplotlib cmap names to pg ColorMaps.

    matplotlib stays a dependency (batch.py), so getFromMatplotlib gives
    exact color parity with the old canvases.
    """
    try:
        return pg.colormap.getFromMatplotlib(name)
    except Exception:
        return pg.colormap.get('viridis')


class _AxisShim:
    """Minimal axis handle exposing ``view_box`` for ``PgNavigationToolbar``.

    The toolbar's ``_view_boxes`` walks ``canvas.axes_list`` and reads
    ``ax.view_box`` to apply pan/box-zoom modes (``_set_all_mouse_modes``)
    and to resolve the primary ViewBox (``_primary_view_box``). The heatmap
    has one fixed PlotItem ViewBox, so one static shim is enough — it never
    rebuilds, so no replot re-binding is needed.

    Same-source as ``line_canvas._AxisShim`` (M11): kept a private copy here
    rather than cross-importing, since ``line_canvas`` already imports
    ``_tick_counts_to_density`` from this module and a reverse import would
    cycle. Future cleanup may hoist both to a shared ``_shared`` helper.
    """

    __slots__ = ("view_box",)

    def __init__(self, view_box):
        self.view_box = view_box


def _tick_counts_to_density(x_n: int, y_n: int) -> tuple:
    """Convert inspector tick COUNTS to pg tick-density factors.

    Replicates the count->density convention of the time-domain canvas
    (pg_canvas/tick_density.py: x_n/10.0 adaptive fallback at :123,
    y_n/6.0 at :69, both clamped to [0.35, 3.0]) so every pg canvas
    responds identically to the PersistentTop spinboxes (x 3-30 default
    10, y 3-20 default 8). tick_density.py keeps these formulas inline
    in `TickDensityController` (backref-bound to the time-domain
    canvas), so they cannot be imported directly; keep both in sync.
    """
    x_d = max(0.35, min(3.0, float(x_n) / 10.0))
    y_d = max(0.35, min(3.0, float(y_n) / 6.0))
    return x_d, y_d


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

    metrics = QFontMetrics(_pg_chart_font(9))
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
                    continue
                fitted.append((float(tick_value), text))
                previous_right = right
            if len(fitted) < _TARGET_BOTTOM_TICK_MIN_COUNT:
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

# Empty-state axis range for the main heatmap (no result loaded / after
# file-close). Time, frequency, and order are all non-negative quantities, so
# the empty map must NOT inherit pyqtgraph's default [-0.5, 0.5] symmetric
# range (which puts the origin in the middle and shows negative tick labels on
# an axis that can never hold negative values). A fixed, simple, non-negative
# default reads as a sensible "blank chart" until real extents arrive. The
# numbers are deliberately NOT derived from loaded-channel extents (product
# decision: keep it simple). Applied identically in __init__ and full_reset via
# _apply_empty_state_range so the two paths can never drift.
_EMPTY_X_RANGE = (0.0, 30.0)
_EMPTY_Y_RANGE = (0.0, 1000.0)


class _BoundaryGridAxisItem(pg.AxisItem):
    """AxisItem that suppresses ONLY the outermost (view-boundary) grid line.

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


def _make_analysis_plot(glw, row, col, view_box):
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
            'bottom': _BoundaryGridAxisItem(orientation='bottom'),
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


class PgHeatmapCanvas(_StackedSplitMixin, QWidget):
    cursor_info = pyqtSignal(str)
    context_menu_requested = pyqtSignal()
    # Emitted when the user drags the interactive colorbar (lo, hi).
    levels_changed = pyqtSignal(float, float)
    # Emitted after labels/ticks/title/colorbar changes that can resize the
    # pyqtgraph layout. Analysis split pages coalesce this and align panes.
    layout_geometry_changed = pyqtSignal()

    def __init__(self, parent=None, with_slice: bool = False):
        super().__init__(parent)
        self._with_slice = bool(with_slice)
        self._glw = pg.GraphicsLayoutWidget(self)
        # White chart surface to match the package baseline
        # (TimeDomainCanvasPG, canvas.py:198) and the matplotlib
        # CHART_FACE; full style parity is arbitrated in the P1 visual
        # acceptance task.
        self._glw.setBackground("#ffffff")
        self._glw.ci.setContentsMargins(2, 2, 2, 2)
        self._glw.ci.setSpacing(2)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._glw)

        self._plot = _make_analysis_plot(
            self._glw, 0, 0, _ModifierWheelViewBox(owner_canvas=self))
        _apply_neutral_axis_frame(self._plot)
        self._axis_bottom = self._plot.getAxis('bottom')
        self._axis_left = self._plot.getAxis('left')
        show_major_grid_left_bottom_only(self._plot, alpha=0.25)
        for _ax in ('left', 'bottom', 'top', 'right'):
            try:
                self._plot.getAxis(_ax).setStyle(maxTickLevel=0)
            except Exception:
                pass
        self._img = _SmoothImageItem()
        # row-major: matrix[row, col] -> row = Y (origin at rect bottom,
        # matching imshow origin='lower'), col = X.
        self._img.setOpts(axisOrder='row-major')
        self._plot.addItem(self._img)

        # Toolbar contract (PgNavigationToolbar._view_boxes walks axes_list →
        # ax.view_box to apply pan/box-zoom mode; _primary_view_box reads
        # axes_list[0].view_box; home() prefers reset_view_to_data_extents).
        # Without this the order/FFT-vs-Time toolbar's pan/zoom mode buttons
        # go silently inert on the pg canvas — mouseMode stays PanMode and
        # box-zoom is dead (lesson:
        # 2026-05-28-mpl-event-coupled-tests-survive-renderer-swap M6/M11).
        # The FFT-vs-Time slice row (with_slice=True) is deliberately NOT in
        # axes_list: it is a click-driven auxiliary readout with an
        # INDEPENDENT X axis (Frequency Hz, not XLinked to the heatmap's Time
        # axis — verified at runtime), so a box-zoom rectangle dragged on the
        # main map is meaningless against the slice's freq×amplitude axes, and
        # folding it into the toolbar's view-history would conflate two
        # unrelated coordinate systems. Pan/zoom act on the main heatmap only.
        self.axes_list = [_AxisShim(self._plot.vb)]

        self._cbar = None
        self._has_result = False
        self._matrix_disp = None  # display-space matrix
        self._extents = None      # (x0, x1, y0, y1)
        self._raw_title = ''
        self._split_title_width = None
        self._remarks = []
        self._remark_enabled = False
        self._mouse_mode_controller = None
        self._bottom_tick_target = None
        self._bottom_tick_density = None
        # remarks: card contract is set_remark_enabled / clear_remarks
        # (chart_stack.py:1314, 1330-1332).
        self._plot.scene().sigMouseClicked.connect(self._on_scene_click)
        self._plot.vb.sigXRangeChanged.connect(self._refresh_bottom_x_ticks)
        self._plot.vb.sigResized.connect(self._refresh_bottom_x_ticks)

        # Slice row (with_slice=True). Every consumer guards on
        # ``self._slice_curve is not None``.
        self._slice_curve = None
        self._slice_plot = None
        self._slice_marker = None
        self._slice_toggle = None
        self._slice_hint = None
        self._slice_panel = None
        # Slice direction: 'x' fixes a time (curve = amp vs Y axis); 'y' fixes a
        # Y position — frequency / order — (curve = amp vs time). Indices index
        # into _matrix_disp (shape: rows=Y, cols=X).
        self._slice_dir = 'x'
        self._slice_x_idx = 0
        self._slice_y_idx = 0
        # Axis coordinate arrays + labels for the slice. Set by plot_result /
        # plot_or_update_heatmap; the slice reads these instead of the result
        # object so Order (no SpectrogramResult) slices the same way.
        self._x_coords = None
        self._y_coords = None
        self._x_label = ''
        self._y_label = ''
        self._default_x_label = 'Time (s)'
        self._default_y_label = 'Frequency (Hz)'
        # Button labels for the X/Y toggle, e.g. ('时间', '频率'). The '按'
        # prefix is dropped — the toggle's role is self-evident, every char
        # counts in the narrow colorbar column.
        self._slice_x_btn_label = '时间'
        self._slice_y_btn_label = '频率'
        # Shared centred width for the toggle + readout inside the panel. The
        # toggle is pinned ~5% wider than a typical readout so it reads as the
        # primary control; _position_slice_panel clamps it on a narrow column.
        self._slice_toggle_w = 86
        self._result = None     # SpectrogramResult-like payload
        # Amplitude mode of the last plot_result render (slice mode only).
        # Parity with SpectrogramCanvas._amplitude_mode (canvases.py:1622):
        # the hover/remark readout labels values 'dB' in dB mode and the
        # channel unit otherwise, and the slice y-label switches with it.
        self._amplitude_mode = 'amplitude_db'
        # dB conversion memo. Keyed on a STABLE per-result epoch token (see
        # _result_db_token) + db_ref, NOT id(result): once
        # AnalysisResultCache (V4) LRU-evicts a result, CPython can reuse its
        # id() for a freshly computed result, and an id()-keyed memo would then
        # return the OLD dB matrix for the NEW result (silent stale-image bug).
        # The epoch token is stamped onto each distinct result the first time
        # it is rendered, so it travels with the object and never collides.
        self._db_cache = None   # (token, db_ref) -> ndarray
        self._db_epoch_counter = 0
        if self._with_slice:
            # Second GraphicsLayout row: 1D frequency slice at the
            # selected frame (parity with SpectrogramCanvas._ax_slice,
            # canvases.py:1775). Capped height keeps the 2D map dominant.
            self._slice_plot = _make_analysis_plot(
                self._glw, 1, 0, _ModifierWheelViewBox(owner_canvas=self))
            _apply_neutral_axis_frame(self._slice_plot)
            self._slice_plot.vb.sigXRangeChanged.connect(
                self._refresh_bottom_x_ticks)
            self._slice_plot.vb.sigResized.connect(self._refresh_bottom_x_ticks)
            # Open the gap between map + slice so the divider line reads clearly.
            try:
                self._glw.ci.layout.setVerticalSpacing(_SPLIT_ROW_SPACING)
            except Exception:
                pass
            # Bottom (slice) plot height when expanded. Stateful so the divider
            # drag can resize it and fold/restore can remember the last size.
            self._bottom_split_default = 140.0
            self._bottom_split_h = self._bottom_split_default
            self._drag_start_bottom_h = self._bottom_split_h
            # True while the page (AnalysisSectionPage) is driving split-pane
            # alignment; the divider handlers then skip single-pane self-align.
            self._split_aligned = False
            self._slice_plot.setMaximumHeight(int(self._bottom_split_h))
            show_major_grid_left_bottom_only(self._slice_plot, alpha=0.25)
            for _ax in ('left', 'bottom', 'top', 'right'):
                try:
                    self._slice_plot.getAxis(_ax).setStyle(maxTickLevel=0)
                except Exception:
                    pass
            self._slice_plot.setLabel('bottom', 'Frequency (Hz)')
            # Left (amplitude) axis label. dB vs linear is switched per
            # render in select_time_index, mirroring the mpl original's
            # _plot_slice ylabel (canvases.py:1878-1880); seed the default
            # here so the axis is never unlabeled before the first render.
            self._slice_plot.setLabel('left', 'Amplitude (dB)')
            self._slice_curve = self._slice_plot.plot(
                pen=pg.mkPen('#2563eb', width=1.2))
            # Marker on the 2D map at the slice position. Draggable (live
            # re-slice) AND click-positioned. angle flips with direction:
            # 90 (vertical) for an X slice, 0 (horizontal) for a Y slice.
            self._slice_marker = pg.InfiniteLine(
                angle=90, movable=True, pen=pg.mkPen('#e03131', width=1))
            self._plot.addItem(self._slice_marker)
            self._slice_marker.setVisible(False)
            self._slice_marker.sigPositionChanged.connect(
                self._on_slice_marker_dragged)
            # Hover readout (t / freq / value) parity with
            # SpectrogramCanvas._on_motion (canvases.py:2000). Only wired
            # in slice mode; the Order map has no hover-readout contract.
            self._plot.scene().sigMouseMoved.connect(self._on_scene_hover)
            # Right-side info panel (sits in the colorbar column, below the
            # colorbar, beside the slice). Holds the X/Y direction switch +
            # the current fixed value / meaning. The slice plot's right edge is
            # pulled in (via _align_slice_to_main) so its time axis lines up
            # with the heatmap above, freeing this column.
            self._slice_panel = QWidget(self)
            self._slice_panel.setObjectName("slicePanel")
            self._slice_panel.setAttribute(Qt.WA_StyledBackground, True)
            pl = QVBoxLayout(self._slice_panel)
            pl.setContentsMargins(6, 5, 6, 5)
            pl.setSpacing(9)   # roomier toggle -> readout gap (was 4, too tight)
            # No title row: the toggle already says what this is. The toggle and
            # readout are centred at a shared narrow width (panel fills the whole
            # colorbar column, far wider than the content needs).
            self._slice_toggle = _SliceDirToggle(
                self._slice_x_btn_label, self._slice_y_btn_label,
                self._slice_panel)
            self._slice_toggle.direction_changed.connect(self.set_slice_direction)
            self._slice_toggle.setFixedWidth(self._slice_toggle_w)
            pl.addWidget(self._slice_toggle, 0, Qt.AlignHCenter)
            self._slice_hint = QLabel('点击图中选择切片', self._slice_panel)
            self._slice_hint.setObjectName("sliceHint")
            self._slice_hint.setWordWrap(False)
            self._slice_hint.setTextFormat(Qt.RichText)
            self._slice_hint.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            pl.addWidget(self._slice_hint, 0, Qt.AlignHCenter)
            pl.addStretch(1)
            self._slice_panel.show()
            # Draggable split divider (resize) + drawer-style collapsed rail
            # between the 2D map (top) and the slice (bottom). Drag the divider
            # near the bottom to collapse the slice; click the rail's ▴ to bring
            # it back. (Replaces the old gutter triangle.)
            self._bottom_collapsed = False
            self._split_divider = _SplitDivider(self)
            self._split_divider.drag_started.connect(self._on_split_drag_started)
            self._split_divider.drag_delta.connect(self._on_split_drag_delta)
            self._split_divider.drag_finished.connect(self._on_split_drag_finished)
            self._split_divider.reset_requested.connect(self._on_split_reset)
            self._collapsed_rail = _CollapsedRail(self)
            self._collapsed_rail.setVisible(False)
            self.layout().addWidget(self._collapsed_rail)
            self._collapsed_rail.expand_requested.connect(
                lambda: self._set_bottom_collapsed(False))
            self._plot.vb.sigResized.connect(self._position_collapse_ctrl)
            self._ensure_colorbar(_resolve_colormap('turbo'), 'Amplitude (dB)')
        else:
            self._collapsed_rail = None
            self._split_divider = None
            self._bottom_collapsed = False
            self._bottom_split_default = 140.0
            self._bottom_split_h = self._bottom_split_default
            self._drag_start_bottom_h = self._bottom_split_h
            self._split_aligned = False
        self._x_label = self._default_x_label
        self._y_label = self._default_y_label
        # Empty state on construction: pin a fixed non-negative range so the
        # blank map never inherits pyqtgraph's default symmetric [-0.5, 0.5]
        # (negative time/freq/order ticks). Real extents from the first
        # plot_or_update_heatmap override this via setXRange/setYRange.
        self._apply_empty_state_range()

    def _apply_empty_state_range(self) -> None:
        """Pin the empty-map view to fixed non-negative defaults.

        Time / frequency / order are never negative, so the no-result map must
        not show pyqtgraph's default centred [-0.5, 0.5] range. Applied at
        construction and again on full_reset (file-close) from the SAME module
        constants so the two empty-state paths cannot drift. The slice plot's
        own empty state already defaults non-negative ([0,1]×[0,1]); only the
        main map needs the explicit override."""
        x0, x1 = _EMPTY_X_RANGE
        y0, y1 = _EMPTY_Y_RANGE
        self._plot.setXRange(float(x0), float(x1), padding=0)
        self._plot.setYRange(float(y0), float(y1), padding=0)

    # ------------------------------------------------------------------
    # main API (signature mirrors canvases.PlotCanvas.plot_or_update_heatmap)
    # ------------------------------------------------------------------
    def plot_or_update_heatmap(
        self, matrix, x_extent, y_extent, *,
        x_label='', y_label='', title='', cmap='turbo', interp=None,
        cbar_label='Amplitude', amplitude_mode='amplitude',
        z_auto=True, z_floor=-30.0, z_ceiling=0.0,
        x_auto=True, x_min=0.0, x_max=0.0,
        y_auto=True, y_min=0.0, y_max=0.0,
        vmin=None, vmax=None,
        x_coords=None, y_coords=None,
    ):
        # Remember the axis labels + coordinate arrays so the slice can read
        # them (the slice plots amplitude against the OTHER axis). When coords
        # are not supplied they are derived from the extents + matrix shape in
        # _slice_coords (regular display grid).
        self._x_label = x_label or self._default_x_label
        self._y_label = y_label or self._default_y_label
        self._x_coords = (
            np.asarray(x_coords, dtype=float) if x_coords is not None else None)
        self._y_coords = (
            np.asarray(y_coords, dtype=float) if y_coords is not None else None)
        interp_mode = 'bilinear' if interp is None else str(interp).lower()
        smooth = interp_mode in {'bilinear', 'bicubic', 'hanning'}
        self._img.set_smooth_transform(smooth)
        m = np.asarray(matrix, dtype=float)

        # -- dB conversion: line-for-line port of canvases.py:2221-2244 --
        if amplitude_mode == 'amplitude_db':
            ref = float(np.nanmax(m))
            if ref <= 0:
                m_disp = np.full_like(m, fill_value=-100.0)
            else:
                with np.errstate(divide='ignore'):
                    m_disp = 20.0 * np.log10(np.clip(m, 1e-12, None) / ref)
            if not z_auto:
                m_disp = np.clip(m_disp, float(z_floor), float(z_ceiling))
            m = m_disp
            if vmin is None:
                vmin = float(z_floor) if not z_auto else float(np.nanmin(m))
            if vmax is None:
                vmax = float(z_ceiling) if not z_auto else 0.0
            if 'dB' not in cbar_label:
                cbar_label = f"{cbar_label} (dB)"
        else:
            if vmin is None:
                vmin = float(np.nanmin(m))
            if vmax is None:
                vmax = float(np.nanmax(m))

        x0, x1 = float(x_extent[0]), float(x_extent[1])
        y0, y1 = float(y_extent[0]), float(y_extent[1])

        cm = _resolve_colormap(cmap)
        self._img.setImage(m, autoLevels=False)
        self._img.setRect(QRectF(x0, y0, x1 - x0, y1 - y0))
        self._img.setColorMap(cm)
        self._img.setLevels((vmin, vmax))

        self._ensure_colorbar(cm, cbar_label)

        # Adaptive drag granularity: the default rounding=1 snaps
        # interactive level drags to whole units and enforces a minimum
        # 1-unit span — unusable for linear amplitudes < 1.
        self._cbar.rounding = max((float(vmax) - float(vmin)) / 1000.0, 1e-9)
        # ColorBarItem.setLevels in pg 0.14.0 does not emit
        # sigLevelsChanged (only user drags via _regionChanging do), but
        # block defensively so programmatic updates can never masquerade
        # as user drags if a future pg version changes that.
        self._cbar.blockSignals(True)
        self._cbar.setLevels((vmin, vmax))
        self._cbar.blockSignals(False)

        self._plot.setLabel('bottom', self._x_label)
        self._plot.setLabel('left', self._y_label)
        self._raw_title = title or ''
        self._apply_title_text()

        if x_auto:
            self._plot.setXRange(x0, x1, padding=0)
        elif x_max > x_min:
            self._plot.setXRange(float(x_min), float(x_max), padding=0)
        if y_auto:
            self._plot.setYRange(y0, y1, padding=0)
        elif y_max > y_min:
            self._plot.setYRange(float(y_min), float(y_max), padding=0)

        # Remark labels embed the z value, so letting them survive a
        # replot would display stale data against the new matrix (the
        # mpl rebuild path dropped annotations on every replot anyway).
        self.clear_remarks()
        self._matrix_disp = m
        self._extents = (x0, x1, y0, y1)
        self._has_result = True
        self.layout_geometry_changed.emit()

    def has_result(self) -> bool:
        return self._has_result

    def full_reset(self) -> None:
        """Clear the heatmap, colorbar, remarks and result state.

        File-close contract: ``ChartStack.full_reset_all``
        (chart_stack.py:2336) calls ``full_reset()`` on every canvas —
        mirrors ``PlotCanvas.full_reset`` (canvases.py:655), which wiped
        the whole matplotlib figure. The colorbar is detached (not just
        hidden) so a stale color scale never outlives its data; the next
        ``plot_or_update_heatmap`` recreates it.
        """
        self.clear_remarks()
        self._img.clear()
        if self._cbar is not None:
            # setImageItem(insert_in=...) nested the bar in the host
            # PlotItem's QGraphicsGridLayout; detach from layout AND
            # scene so no orphaned column remains.
            try:
                self._plot.layout.removeItem(self._cbar)
            except Exception:
                pass
            scene = self._cbar.scene()
            if scene is not None:
                scene.removeItem(self._cbar)
            self._cbar = None
        _hide_plot_title(self._plot)
        self._raw_title = ''
        self._matrix_disp = None
        self._extents = None
        self._has_result = False
        # FFT-vs-Time slice state. Keep the persistent slice row / curve /
        # marker widgets (built once in __init__) so the GraphicsLayout
        # row is not orphaned; just blank them and drop the result + dB
        # cache so a stale slice never outlives its data.
        self._result = None
        self._db_cache = None
        self._x_coords = None
        self._y_coords = None
        if self._slice_curve is not None:
            self._slice_curve.clear()
            _hide_plot_title(self._slice_plot)
            self._slice_marker.setVisible(False)
            if self._slice_panel is not None:
                self._slice_panel.show()
        if self._with_slice:
            self._ensure_colorbar(_resolve_colormap('turbo'), 'Amplitude (dB)')
        if self.isVisible():
            self._apply_default_axis_labels()
        else:
            self._x_label = self._default_x_label
            self._y_label = self._default_y_label
        self.reset_split_layout_alignment()
        # File-close empty state: restore the fixed non-negative default range
        # (same constants as __init__) so the blank map never shows negative
        # time/freq/order ticks after the data is cleared.
        self._apply_empty_state_range()
        self.layout_geometry_changed.emit()

    def set_default_axis_labels(self, *, x_label: str | None = None,
                                y_label: str | None = None) -> None:
        """Configure labels used before the first render and after reset."""
        if x_label is not None:
            self._default_x_label = x_label
        if y_label is not None:
            self._default_y_label = y_label
        if not self._has_result and self.isVisible():
            self._apply_default_axis_labels()
        elif not self._has_result:
            self._x_label = self._default_x_label
            self._y_label = self._default_y_label

    def _apply_default_axis_labels(self) -> None:
        self._x_label = self._default_x_label
        self._y_label = self._default_y_label
        self._plot.setLabel('bottom', self._default_x_label)
        self._plot.setLabel('left', self._default_y_label)
        if self._slice_plot is not None:
            bottom = (self._default_x_label if self._slice_dir == 'y'
                      else self._default_y_label)
            amp_label = ('Amplitude (dB)'
                         if self._amplitude_mode == 'amplitude_db'
                         else 'Amplitude')
            self._slice_plot.setLabel('bottom', bottom)
            self._slice_plot.setLabel('left', amp_label)

    def register_mouse_mode_controller(self, controller) -> None:
        self._mouse_mode_controller = controller

    def _plot_item_for_view_box(self, view_box):
        for plot in (self._plot, self._slice_plot):
            if plot is not None and plot.vb is view_box:
                return plot
        return self._plot

    def _redesign_context_menu_for_viewbox(self, view_box, menu) -> None:
        redesign_pg_context_menu(
            menu,
            self._plot_item_for_view_box(view_box),
            self._mouse_mode_controller,
            view_all_handler=self.reset_view_to_data_extents,
            y_autofit_handler=None,
            allow_y_grid=True,
            keep_plot_options=True,
        )

    def _handle_wheel_dispatch(self, **_kwargs):
        return False

    def set_tick_density(self, x, y) -> None:
        """Apply inspector tick density.

        ``x``/``y`` are approximate tick COUNTS from
        ``inspector.top.tick_density()`` (spinboxes: x 3-30 default 10,
        y 3-20 default 8) — the same integers the mpl canvases fed into
        ``MaxNLocator(nbins=...)`` — NOT pg density factors. They are
        converted to native ``AxisItem.setTickDensity`` factors here,
        the same mechanism TimeDomainCanvasPG uses (tick_density.py).
        """
        try:
            x_n = max(3, int(x))
            y_n = max(3, int(y))
        except (TypeError, ValueError):
            return
        x_d, y_d = _tick_counts_to_density(x_n, y_n)
        self._bottom_tick_target = x_n
        self._bottom_tick_density = x_d
        self._refresh_bottom_x_ticks()
        left_axes = [self._axis_left]
        # The FFT-vs-Time frequency/amplitude slice subplot (with_slice=True)
        # carries its own bottom/left axes that the main-plot pair above never
        # touched, so the tick control must reach the slice too. Bottom X axes
        # use target-count ticks when the widget has realized geometry; left/Y
        # axes keep pyqtgraph density behavior.
        if self._with_slice and self._slice_plot is not None:
            left_axes.append(self._slice_plot.getAxis('left'))
        for axis in left_axes:
            _apply_axis_tick_density(axis, y_d)
        self.layout_geometry_changed.emit()

    def _refresh_bottom_x_ticks(self, *_args) -> None:
        if self._bottom_tick_target is None or self._bottom_tick_density is None:
            return
        bottom_pairs = [(self._axis_bottom, self._plot.vb)]
        if self._with_slice and self._slice_plot is not None:
            bottom_pairs.append((
                self._slice_plot.getAxis('bottom'),
                self._slice_plot.vb,
            ))
        for axis, view_box in bottom_pairs:
            if not _apply_target_bottom_ticks(
                axis, view_box, self._bottom_tick_target, self
            ):
                _apply_axis_tick_density(axis, self._bottom_tick_density)

    def reset_view_to_data_extents(self) -> None:
        """Toolbar Home helper: restore the view to the full data extents.

        ``PgNavigationToolbar.home`` (chart_stack.py:719) prefers a canvas
        ``reset_view_to_data_extents`` and otherwise falls back to a
        ``axes_list``/``_channel_lines`` walk that the heatmap canvas has
        no surface for — so without this method the Home button is inert on
        the order map (measured: a zoomed view was unchanged by home()).
        Native pg pan/wheel-zoom and the ViewBox "View All" still work; this
        wires the most discoverable reset affordance (the toolbar Home
        button) to the same full-extent restore. Falls back to pg's
        ``autoRange`` when no result has been plotted yet.

        The image ``setRect`` (plot_or_update_heatmap) spans EXACTLY
        ``[x0,x1]x[y0,y1]``, and the initial render fills the ViewBox with
        ``setXRange(x0,x1,padding=0)`` / ``setYRange(y0,y1,padding=0)`` so
        the image meets the frame flush. Home must reproduce that flush
        edge: the shared ``_visual_padded_bounds`` 1.5%/side breathing room
        (which line-plot resets on a white background need to avoid pressing
        the frame) would over-expand the ViewBox past the image rect and
        expose the white ViewBox background as a margin band on a heatmap.
        So reset to the raw extents here, mirroring the initial render.
        """
        if self._extents is None:
            # No result yet: pg's autoRange() with no image item recenters on
            # the origin → negative range (X=[-15,15], Y=[-500,500]), which both
            # the toolbar Home and the right-click "查看全部" would then show as
            # negative time/freq/order ticks. Restore the SAME non-negative
            # empty default used by __init__/full_reset so the blank map stays
            # consistent on reset.
            self._apply_empty_state_range()
            return
        x0, x1, y0, y1 = self._extents
        self._plot.setXRange(x0, x1, padding=0)
        self._plot.setYRange(y0, y1, padding=0)

    # ------------------------------------------------------------------
    # FFT-vs-Time: spectrogram render + frequency slice (with_slice=True)
    # ------------------------------------------------------------------
    def _result_db_token(self, result):
        """Return a stable hashable token identifying ``result`` for the dB
        memo. Stamps a monotonic ``_pg_db_epoch`` attribute on first sight so
        the token travels with the object across AnalysisResultCache eviction
        and never collides via id() reuse. Falls back to id() for exotic
        results that reject attribute assignment (never in practice)."""
        token = getattr(result, '_pg_db_epoch', None)
        if token is None:
            self._db_epoch_counter += 1
            token = self._db_epoch_counter
            try:
                result._pg_db_epoch = token
            except (AttributeError, TypeError):
                return ('id', id(result))
        return ('epoch', token)

    def plot_result(
        self, result, *, amplitude_mode='amplitude_db', cmap='turbo',
        z_auto=False, z_floor=-80.0, z_ceiling=0.0, freq_range=None,
        x_auto=True, x_min=0.0, x_max=0.0,
        y_auto=True, y_min=0.0, y_max=0.0,
        interp='bilinear',
    ):
        """Render a ``SpectrogramResult`` as a 2D heatmap + frequency slice.

        Signature mirrors ``SpectrogramCanvas.plot_result``
        (canvases.py:1722) and the ``MainWindow._render_fft_time`` call
        site (main_window.py:2825). ``result.amplitude`` is shape
        ``(freq_bins, frames)`` → rows are frequency (Y), columns are
        time (X).

        dB conversion is done HERE (memoized via ``self._db_cache``,
        keyed ``(self._result_db_token(result), db_reference)`` — a
        monotonic epoch token stamped on each result, NOT ``id(result)``,
        so the memo never returns a stale matrix after an
        ``AnalysisResultCache`` eviction frees + reuses an id()), and the
        already-converted
        display matrix is handed to ``plot_or_update_heatmap`` with
        ``amplitude_mode='amplitude'`` plus explicit ``vmin``/``vmax`` so
        the heatmap's internal dB/auto branch never re-derives the
        levels. The explicit ``vmin``/``vmax`` survive because the linear
        branch of ``plot_or_update_heatmap`` only fills them from
        nanmin/nanmax when they are ``None``.
        """
        self._result = result
        # Pin the amplitude mode so hover/remark readouts label the value
        # 'dB' (not the channel unit) in dB mode, and the slice y-label
        # switches accordingly — parity with SpectrogramCanvas
        # (canvases.py:1762, 1879, 1942, 2028).
        self._amplitude_mode = amplitude_mode
        unit = f" ({result.unit})" if result.unit else ""
        db_ref = float(result.params.db_reference)
        if amplitude_mode == 'amplitude_db':
            key = (self._result_db_token(result), db_ref)
            if self._db_cache is None or self._db_cache[0] != key:
                from ...signal.spectrogram import SpectrogramAnalyzer
                self._db_cache = (key, SpectrogramAnalyzer.amplitude_to_db(
                    result.amplitude, db_ref))
            m = self._db_cache[1]
            if not z_auto:
                m = np.clip(m, float(z_floor), float(z_ceiling))
            vmin = float(z_floor) if not z_auto else float(np.nanmin(m))
            vmax = float(z_ceiling) if not z_auto else float(np.nanmax(m))
            cbar = f"Amplitude{unit} (dB re {db_ref:g})"
        else:
            m = result.amplitude
            vmin, vmax = float(np.nanmin(m)), float(np.nanmax(m))
            cbar = f"Amplitude{unit}"

        y_lo = float(result.frequencies[0])
        y_hi = float(result.frequencies[-1])
        if freq_range is not None:
            # freq_range controls the Y axis only; (lo, hi) with hi<=lo or
            # hi<=0 falls back to the Nyquist bin (parity with
            # SpectrogramCanvas.plot_result, canvases.py:1808-1811).
            lo, hi = float(freq_range[0]), float(freq_range[1])
            if hi <= 0 or hi <= lo:
                hi = y_hi
            y_auto, y_min, y_max = False, lo, hi

        # amplitude is (freq_bins, frames) → rows=freq(Y), cols=time(X).
        # amplitude_mode='amplitude' here: dB conversion already done
        # above, so vmin/vmax pass through untouched (the dB branch would
        # re-clip and could re-derive levels).
        self.plot_or_update_heatmap(
            matrix=m,
            x_extent=(float(result.times[0]), float(result.times[-1])),
            y_extent=(y_lo, y_hi),
            x_label='Time (s)', y_label='Frequency (Hz)',
            title=f'FFT vs Time - {result.channel_name}',
            cmap=cmap, cbar_label=cbar,
            amplitude_mode='amplitude',  # conversion already done above
            interp=interp,
            z_auto=True, vmin=vmin, vmax=vmax,
            x_auto=x_auto, x_min=x_min, x_max=x_max,
            y_auto=y_auto, y_min=y_min, y_max=y_max,
            x_coords=result.times, y_coords=result.frequencies,
        )
        # plot_or_update_heatmap stores the matrix it was handed (the
        # display matrix) in self._matrix_disp; re-pin it explicitly so
        # the slice and remarks read the same display-space values.
        self._matrix_disp = m
        if self._slice_curve is not None and len(result.times):
            self._seed_slice()
        self.layout_geometry_changed.emit()

    # ------------------------------------------------------------------
    # slice (X / Y direction)
    # ------------------------------------------------------------------
    def _slice_coords(self):
        """Return (x_coords, y_coords) for the displayed matrix, falling back
        to a regular grid derived from the extents when no explicit arrays were
        supplied (parity with how the image is drawn across the extents)."""
        m = self._matrix_disp
        if m is None or self._extents is None:
            return None, None
        nrows, ncols = m.shape[0], m.shape[1]
        x0, x1, y0, y1 = self._extents
        xc = self._x_coords
        if xc is None or len(xc) != ncols:
            xc = np.linspace(float(x0), float(x1), ncols)
        yc = self._y_coords
        if yc is None or len(yc) != nrows:
            yc = np.linspace(float(y0), float(y1), nrows)
        return xc, yc

    def _seed_slice(self):
        """Place the slice at the middle of the active axis and render it."""
        m = self._matrix_disp
        if m is None or self._slice_curve is None:
            return
        nrows, ncols = m.shape[0], m.shape[1]
        self._slice_x_idx = ncols // 2
        self._slice_y_idx = nrows // 2
        self._apply_slice()

    def set_slice_direction(self, direction: str) -> None:
        """Switch the slice between 'x' (fix time → amp vs Y) and 'y' (fix
        frequency/order → amp vs time). Re-renders the slice + flips the marker."""
        direction = 'y' if direction == 'y' else 'x'
        self._slice_dir = direction
        if self._slice_toggle is not None:
            self._slice_toggle.set_direction(direction, emit=False)
        if self._matrix_disp is None:
            if not self.isVisible():
                return
            self._apply_default_axis_labels()
            return
        self._apply_slice()

    def select_time_index(self, idx: int) -> None:
        """Back-compat entry point: place an X slice (fixed time) at frame
        ``idx``. Preserved for the FFT-vs-Time auto-seed + tests."""
        if self._matrix_disp is None or self._slice_curve is None:
            return
        ncols = self._matrix_disp.shape[1]
        self._slice_dir = 'x'
        self._slice_x_idx = int(np.clip(idx, 0, max(0, ncols - 1)))
        if self._slice_toggle is not None:
            self._slice_toggle.set_direction('x', emit=False)
        self._apply_slice()

    def _apply_slice(self) -> None:
        """Render the slice curve + marker for the current direction/index."""
        m = self._matrix_disp
        if m is None or self._slice_curve is None:
            return
        xc, yc = self._slice_coords()
        if xc is None:
            return
        nrows, ncols = m.shape[0], m.shape[1]
        amp_label = ('Amplitude (dB)'
                     if self._amplitude_mode == 'amplitude_db' else 'Amplitude')
        if self._slice_dir == 'y':
            # Fix a Y position (frequency / order) → curve = amplitude vs time.
            idx = int(np.clip(self._slice_y_idx, 0, max(0, nrows - 1)))
            self._slice_y_idx = idx
            self._slice_curve.setData(xc, m[idx, :])
            # Top/bottom grid-line ALIGNMENT (spec FIX 3, 'y' direction only):
            # the slice X axis is deliberately NOT XLinked to the map X (the
            # 'x' direction plots amplitude-vs-frequency, an unrelated axis), so
            # the slice keeps its own auto X range here. In 'y' mode the slice X
            # IS time — the same quantity as the map's bottom X — but pyqtgraph
            # auto-ranges the curve with its own padding, so the slice's time
            # ticks/grid land at different positions than the map's (which uses
            # setXRange(x0,x1,padding=0)). Pin the slice X to the FULL time
            # extent with padding=0 to match the map exactly so the top/bottom
            # gridlines line up vertically. Only the 'y' branch is touched; the
            # 'x' branch (freq/order on X) is left exactly as before.
            if len(xc) >= 2:
                self._slice_plot.setXRange(
                    float(xc[0]), float(xc[-1]), padding=0)
            self._slice_plot.setLabel('bottom', self._x_label or 'Time (s)')
            self._slice_marker.setAngle(0)
            self._slice_marker.setValue(float(yc[idx]))
            fixed_val, fixed_lbl = float(yc[idx]), self._y_label
        else:
            # Fix a time → curve = amplitude vs Y (frequency / order).
            idx = int(np.clip(self._slice_x_idx, 0, max(0, ncols - 1)))
            self._slice_x_idx = idx
            self._slice_curve.setData(yc, m[:, idx])
            # Re-enable X auto-range so the spectrum re-fits to the
            # frequency/order extent. The 'y' branch above pins the slice X to
            # the TIME extent via setXRange(padding=0), which DISABLES the
            # slice plot's X auto-range (autoRangeX → False); without this
            # re-enable, switching y→x would leave the freq spectrum squished
            # into the stale time extent ([0,30]) instead of re-ranging to the
            # frequency axis. The 'y' branch's time-pin is left exactly as is.
            self._slice_plot.enableAutoRange(axis='x')
            try:
                self._slice_plot.vb.autoRange()
            except Exception:
                pass
            self._slice_plot.enableAutoRange(axis='x')
            self._slice_plot.setLabel('bottom', self._y_label or 'Frequency (Hz)')
            self._slice_marker.setAngle(90)
            self._slice_marker.setValue(float(xc[idx]))
            fixed_val, fixed_lbl = float(xc[idx]), self._x_label
        self._slice_plot.setLabel('left', amp_label)
        _hide_plot_title(self._slice_plot)
        self._slice_marker.setVisible(True)
        self._update_slice_hint(fixed_lbl, fixed_val)
        if self._slice_panel is not None and self._slice_panel.isHidden():
            self._slice_panel.show()
        self._align_slice_to_main()
        self._position_slice_panel()
        self.layout_geometry_changed.emit()

    def _on_slice_marker_dragged(self, *_args) -> None:
        """Marker drag → snap to the nearest index along the active axis and
        re-slice live."""
        if self._matrix_disp is None or self._slice_curve is None:
            return
        xc, yc = self._slice_coords()
        if xc is None:
            return
        try:
            pos = float(self._slice_marker.value())
        except Exception:
            return
        if self._slice_dir == 'y':
            self._slice_y_idx = int(np.argmin(np.abs(yc - pos)))
        else:
            self._slice_x_idx = int(np.argmin(np.abs(xc - pos)))
        self._apply_slice()

    @staticmethod
    def _short_axis_label(label: str):
        """Split an axis label like 'Time (s)' / 'Frequency (Hz)' / 'Order'
        into a short prefix ('Time' / 'Freq' / 'Order') and a unit ('s' / 'Hz'
        / '')."""
        raw = (label or '').strip()
        if '(' in raw:
            name = raw.split('(', 1)[0].strip()
            unit = raw.split('(', 1)[1].split(')', 1)[0].strip()
        else:
            name, unit = raw, ''
        abbr = {
            'Frequency': 'Freq', 'frequency': 'Freq', '频率': 'Freq',
            'Time': 'Time', '时间': 'Time',
            'Order': 'Order', '阶次': 'Order',
        }.get(name, name)
        return (abbr or 'X'), unit

    def _update_slice_hint(self, label: str, value: float) -> None:
        if self._slice_hint is None:
            return
        prefix, unit = self._short_axis_label(label)
        unit_part = f' {unit}' if unit else ''
        # At most 2 decimals, trailing zeros trimmed (3.00 -> 3, 4.0336 -> 4.03).
        vtxt = f'{round(float(value), 2):.2f}'.rstrip('0').rstrip('.')
        if vtxt in ('', '-0'):
            vtxt = '0'
        # Single centred line: 'Prefix = <value> unit', value emphasised.
        self._slice_hint.setText(
            f'<span style="color:#8a94a6;">{prefix} = </span>'
            f'<span style="font-size:14px;font-weight:800;color:#1f3b63;">'
            f'{vtxt}</span>'
            f'<span style="color:#8a94a6;">{unit_part}</span>'
        )

    def _select_slice_at(self, x: float, y: float) -> None:
        """Position the slice at a clicked map point, respecting direction and
        the data extents (a click on the colorbar/padding is ignored)."""
        if (self._matrix_disp is None or self._slice_curve is None
                or self._extents is None):
            return
        x0, x1, y0, y1 = self._extents
        if self._slice_dir == 'y':
            if y0 <= y <= y1:
                self._slice_y_idx = self._freq_index_for(y)
                self._apply_slice()
        else:
            if x0 <= x <= x1:
                self._slice_x_idx = self._time_index_for(x)
                self._apply_slice()

    def set_slice_button_labels(self, x_label: str, y_label: str) -> None:
        """Set the X/Y toggle segment captions (Order uses 按阶次 for Y)."""
        self._slice_x_btn_label = x_label
        self._slice_y_btn_label = y_label
        if self._slice_toggle is not None:
            self._slice_toggle._btn_x.setText(x_label)
            self._slice_toggle._btn_y.setText(y_label)

    def _align_slice_to_main(self) -> None:
        """Pull the slice plot's right edge in to match the heatmap's, so the
        time axis lines up vertically (the heatmap's right edge is inset by the
        colorbar). Single-pane; split alignment handles the multi-pane case."""
        if self._slice_plot is None:
            return
        try:
            self._set_slice_right_spacer(None)
            self._activate_graphics_layout()
            main_r = float(self._plot.vb.sceneBoundingRect().right())
            slice_r = float(self._slice_plot.vb.sceneBoundingRect().right())
        except Exception:
            return
        reserve = slice_r - main_r
        self._set_slice_right_spacer(
            reserve if reserve > 1.0 else PG_AXIS_NEUTRAL_WIDTH)
        self._activate_graphics_layout()

    def _position_slice_panel(self) -> None:
        """Pin the slice info panel into the colorbar column (right of the
        aligned slice plot, below the colorbar)."""
        if getattr(self, '_bottom_collapsed', False):
            if self._slice_panel is not None:
                self._slice_panel.hide()
            return
        if self._slice_panel is None or self._slice_plot is None:
            return
        try:
            srect = self._slice_plot.vb.sceneBoundingRect()
        except Exception:
            return
        cbar_left = None
        if self._cbar is not None:
            try:
                cbar_left = float(self._cbar.sceneBoundingRect().left())
            except Exception:
                cbar_left = None
        if cbar_left is not None and cbar_left > srect.right():
            x = int(cbar_left) - 2
        else:
            x = int(srect.right()) + 6
        margin = 4
        y = int(srect.top())
        w = max(70, int(self.width() - x - margin))
        h = max(40, int(srect.height()))
        self._slice_panel.setGeometry(x, y, w, h)
        # Clamp the centred toggle to the available content width so it never
        # clips on a very narrow column (margins are 6 each side).
        if self._slice_toggle is not None:
            self._slice_toggle.setFixedWidth(
                min(self._slice_toggle_w, max(52, w - 12)))
        self._slice_panel.show()
        self._slice_panel.raise_()

    def _split_top_plot(self):
        return self._plot

    def _split_bottom_plot(self):
        return self._slice_plot

    def _after_split_collapse_changed(self) -> None:
        if self._slice_panel is not None:
            self._slice_panel.setVisible(not self._bottom_collapsed)
        if not self._bottom_collapsed:
            self._align_slice_to_main()
            self._position_slice_panel()

    def _after_split_height_changed(self) -> None:
        self._position_slice_panel()

    def _after_split_drag_finished(self) -> bool:
        # Single pane self-aligns; in split mode the page owns alignment, so
        # the shared layout_geometry_changed signal asks the page to align it.
        if not self._split_aligned:
            self._align_slice_to_main()
            self._position_slice_panel()
        return True

    def _after_split_reset(self) -> None:
        if not self._split_aligned:
            self._align_slice_to_main()
            self._position_slice_panel()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Slice re-alignment on resize is owned by the AnalysisSectionPage
        # layout sync (single → reset_split_layout_alignment; split →
        # apply_split_layout_alignment), so only reposition the overlays here
        # to avoid transiently fighting the shared split reserve.
        self._position_slice_panel()
        self._position_collapse_ctrl()
        self._refresh_bottom_x_ticks()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._has_result:
            self._apply_default_axis_labels()
        self._align_slice_to_main()
        self._position_slice_panel()
        self._position_collapse_ctrl()
        self._refresh_bottom_x_ticks()
        # First-show left-axis unification: on the FIRST entry the eager
        # alignment above runs before the on-screen GraphicsLayout geometry /
        # tick-label widths are realized, so _unify_stacked_left_axes measures
        # stale (equal) widths and no-ops — the wide main Y axis ("0–1000") and
        # the narrow slice Y axis ("0.8") then settle to DIFFERENT natural
        # widths with nothing re-unifying them, leaving the slice's left edge
        # off the map's until a later layout_geometry_changed (collapse/expand)
        # re-runs the page sync against realized geometry. Defer a re-alignment
        # to AFTER the first paint/realize so it measures real widths.
        if self._slice_plot is not None:
            QTimer.singleShot(0, self._deferred_first_show_align)

    def _deferred_first_show_align(self) -> None:
        """Re-run left-axis/slice alignment after the first paint realizes the
        GraphicsLayout geometry (scheduled from showEvent via singleShot(0)).

        Split-pane-safe: it does NOT unconditionally call
        reset_split_layout_alignment (which sets _split_aligned=False and would
        fight the page's apply_split_layout_alignment in compare/split mode).
        Instead it always re-emits layout_geometry_changed so the owning
        AnalysisSectionPage re-runs its single/split-aware sync against the now-
        realized geometry; and ONLY for the page-less single-pane case (not
        already split-aligned, slice not collapsed) does it also self-align
        directly so a standalone canvas still unifies its left edges. Both
        reset_split_layout_alignment and _unify_stacked_left_axes do NOT emit
        layout_geometry_changed, so the emit chain terminates (no loop)."""
        if self._slice_plot is None:
            return
        # Always notify the page (if any) to re-sync against realized geometry.
        self.layout_geometry_changed.emit()
        # Page-less single-pane fallback: self-align so a standalone canvas
        # (no AnalysisSectionPage driving alignment) unifies its left edges.
        if not self._split_aligned and not self._bottom_collapsed:
            self.reset_split_layout_alignment()

    # ------------------------------------------------------------------
    # split-pane layout alignment
    # ------------------------------------------------------------------
    def recommended_split_title_width(self) -> float:
        """Conservative title width that cannot widen a split pane's scene.

        Long per-channel titles otherwise increase the PlotItem's minimum
        width beyond the viewport, making side-by-side panes drift even when
        their outer QSplitter slots are equal.
        """
        viewport_w = 0.0
        try:
            viewport_w = float(self._glw.viewport().width())
        except Exception:
            viewport_w = float(self._glw.width())
        return max(120.0, viewport_w - 160.0)

    def prepare_split_layout_alignment(self, title_width: float | None) -> None:
        """Release stale pins, constrain the title, and realize geometry.

        Called by AnalysisSectionPage before it measures multiple heatmap
        panes. The release step mirrors TimeDomain's axis-width unifier: first
        measure natural current text/tick sizes, then pin all panes to maxima.
        """
        self._split_title_width = (
            max(80.0, float(title_width))
            if title_width is not None else None
        )
        for axis in self._alignment_left_axes():
            try:
                axis.setWidth(None)
            except Exception:
                pass
        for axis in self._alignment_bottom_axes():
            try:
                axis.setHeight(None)
            except Exception:
                pass
        self._set_slice_right_spacer(None)
        self._apply_title_text()
        self._activate_graphics_layout()

    def reset_split_layout_alignment(self) -> None:
        self._split_aligned = False
        self.prepare_split_layout_alignment(None)
        # Single-pane: unify the two stacked left axes to a common width so the
        # map and the slice share a left edge (prepare_* just released them to
        # their natural widths, which differ when the y tick labels differ →
        # misaligned left edges). Order matters: unify the left axes FIRST (it
        # shifts each plot's left edge), then align the slice's RIGHT edge to
        # the heatmap. Split mode (≥2 panes) is handled by the page via
        # apply_split_layout_alignment, which already unifies left widths.
        if not getattr(self, '_bottom_collapsed', False):
            self._unify_stacked_left_axes()
            self._align_slice_to_main()
            self._position_slice_panel()

    def _unify_stacked_left_axes(self) -> None:
        """Pin the map's and the slice's left axes to the MAX of their natural
        widths so both plots share a left edge in single-pane mode.

        Call only AFTER prepare_split_layout_alignment(None) has released the
        widths (setWidth(None)) and realized the layout, so width() reports each
        axis's natural size. No-op without a slice row (single plot, nothing to
        align)."""
        if self._slice_plot is None:
            return
        axes = self._alignment_left_axes()
        if len(axes) < 2:
            return
        widths = []
        for axis in axes:
            try:
                widths.append(float(axis.width()))
            except Exception:
                pass
        if not widths:
            return
        target = max(widths)
        for axis in axes:
            try:
                axis.setWidth(target)
            except Exception:
                pass
        self._activate_graphics_layout()

    def heatmap_layout_metrics(self) -> dict:
        left_widths = []
        for axis in self._alignment_left_axes():
            try:
                left_widths.append(float(axis.width()))
            except Exception:
                pass
        bottom_heights = []
        for axis in self._alignment_bottom_axes():
            try:
                bottom_heights.append(float(axis.height()))
            except Exception:
                pass
        metrics = {
            'left_axis_width': max(left_widths) if left_widths else 0.0,
            'main_bottom_axis_height': (
                bottom_heights[0] if bottom_heights else 0.0
            ),
            'slice_bottom_axis_height': (
                bottom_heights[1] if len(bottom_heights) > 1 else 0.0
            ),
            'slice_right_reserve': 0.0,
        }
        if self._slice_plot is not None:
            try:
                main_rect = self._plot.vb.sceneBoundingRect()
                slice_rect = self._slice_plot.vb.sceneBoundingRect()
                metrics['slice_right_reserve'] = max(
                    0.0, float(slice_rect.right() - main_rect.right())
                )
            except Exception:
                pass
        return metrics

    def _ensure_colorbar(self, cm: pg.ColorMap, cbar_label: str):
        if self._cbar is None:
            self._img.setColorMap(cm)
            self._img.setLevels((-70.0, -20.0))
            self._cbar = pg.ColorBarItem(
                colorMap=cm, interactive=True, label=cbar_label,
                colorMapMenu=False,
            )
            self._cbar.setImageItem(self._img, insert_in=self._plot)
            self._cbar.sigLevelsChanged.connect(self._on_cbar_levels)
            self._cbar.blockSignals(True)
            self._cbar.setLevels((-70.0, -20.0))
            self._cbar.blockSignals(False)
        else:
            self._cbar.setColorMap(cm)
            self._cbar.getAxis('left').setLabel(cbar_label)
        _apply_pg_axis_font(self._cbar.getAxis('left'))
        _apply_pg_axis_font(self._cbar.getAxis('right'))
        return self._cbar

    def apply_split_layout_alignment(
        self, *,
        left_axis_width: float,
        main_bottom_axis_height: float | None = None,
        slice_bottom_axis_height: float | None = None,
        slice_right_reserve: float | None = None,
    ) -> None:
        self._split_aligned = True
        for axis in self._alignment_left_axes():
            try:
                axis.setWidth(float(left_axis_width))
            except Exception:
                pass
        if main_bottom_axis_height is not None:
            try:
                self._plot.getAxis('bottom').setHeight(
                    float(main_bottom_axis_height))
            except Exception:
                pass
        if self._slice_plot is not None and slice_bottom_axis_height is not None:
            try:
                self._slice_plot.getAxis('bottom').setHeight(
                    float(slice_bottom_axis_height))
            except Exception:
                pass
        if slice_right_reserve is not None:
            self._set_slice_right_spacer(float(slice_right_reserve))
        self._activate_graphics_layout()

    def _alignment_left_axes(self):
        axes = [self._plot.getAxis('left')]
        if self._slice_plot is not None:
            axes.append(self._slice_plot.getAxis('left'))
        return axes

    def _alignment_bottom_axes(self):
        axes = [self._plot.getAxis('bottom')]
        if self._slice_plot is not None:
            axes.append(self._slice_plot.getAxis('bottom'))
        return axes

    def _set_slice_right_spacer(self, width: float | None) -> None:
        if self._slice_plot is None:
            return
        axis = self._slice_plot.getAxis('right')
        frame_pen = pg.mkPen(
            color=PG_AXIS_NEUTRAL_COLOR, width=PG_AXIS_NEUTRAL_WIDTH)
        transparent = pg.mkPen((0, 0, 0, 0))
        if width is None:
            # _align_slice_to_main 在测量 colorbar 内缩量之前会先调用本分支做一次
            # 瞬时复位——此时把右轴从测量中移除，保持 reserve 计算干净，不画边框。
            try:
                self._slice_plot.showAxis('right', False)
                axis.setWidth(None)
            except Exception:
                pass
            return
        try:
            self._slice_plot.showAxis('right', True)
            # 在 slice viewbox 的右缘画一条可见边框线，使下方图右侧闭合（与热力图右
            # 边框对齐）。刻度文字保持隐藏；width>0 时仍预留 colorbar 列的间距。
            axis.setPen(frame_pen)
            axis.setTextPen(transparent)
            axis.setStyle(showValues=False, tickLength=0)
            axis.setWidth(float(width) if width > 0 else 1.0)
        except Exception:
            pass

    def _apply_title_text(self) -> None:
        _hide_plot_title(self._plot)

    def _activate_graphics_layout(self) -> None:
        try:
            self._glw.ci.resize(self._glw.width(), self._glw.height())
        except Exception:
            pass
        for item in (self._plot, self._slice_plot, self._cbar, self._glw.ci):
            if item is None:
                continue
            layout = getattr(item, 'layout', None)
            if layout is None:
                continue
            try:
                layout.invalidate()
                layout.activate()
            except Exception:
                pass

    def _time_index_for(self, x: float) -> int:
        """Nearest X (time) column index to a view-space ``x``. Coordinate-
        based so it works for the Order map too (no SpectrogramResult)."""
        xc, _ = self._slice_coords()
        if xc is None or len(xc) == 0:
            return 0
        return int(np.argmin(np.abs(xc - x)))

    def _freq_index_for(self, y: float) -> int:
        """Nearest Y (frequency / order) row index to a view-space ``y``."""
        _, yc = self._slice_coords()
        if yc is None or len(yc) == 0:
            return 0
        return int(np.argmin(np.abs(yc - y)))

    def _readout_unit(self) -> str:
        """Unit token for the hover/remark value (slice mode).

        dB mode labels the value 'dB' (the matrix is already in dB), every
        other mode uses the channel unit. Parity with
        SpectrogramCanvas._on_motion / _format_remark_label
        (canvases.py:2028, 1942).
        """
        if self._amplitude_mode == 'amplitude_db':
            return 'dB'
        return self._result.unit or ''

    def _on_scene_hover(self, scene_pos) -> None:
        """Emit ``cursor_info`` (t / freq / value) on hover over the map.

        Slice-mode only (Order has no hover-readout contract). Parity
        with SpectrogramCanvas._on_motion (canvases.py:2000): clears the
        readout when the pointer leaves the data extents or before a
        result is plotted.
        """
        if self._result is None or self._matrix_disp is None:
            return
        if not self._plot.sceneBoundingRect().contains(scene_pos):
            self.cursor_info.emit('')
            return
        p = self._plot.vb.mapSceneToView(scene_pos)
        x, y = p.x(), p.y()
        if self._extents is None:
            return
        x0, x1, y0, y1 = self._extents
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            # Inside the plot's scene rect but outside the heatmap (e.g.
            # the colorbar column or padding) — clear the pill.
            self.cursor_info.emit('')
            return
        rows, cols = self._matrix_disp.shape
        if rows == 0 or cols == 0:
            return
        # Reuse the same argmin-nearest cell picker the slice selection and
        # remarks use, so hover/remark/slice never disagree on which cell a
        # coordinate maps to (M2 dedupe + caliber unification).
        t_idx = self._time_index_for(x)
        f_idx = self._freq_index_for(y)
        val = float(self._matrix_disp[min(f_idx, rows - 1), min(t_idx, cols - 1)])
        unit = self._readout_unit()
        msg = (
            f"t={float(self._result.times[t_idx]):.4g} s · "
            f"f={float(self._result.frequencies[f_idx]):.4g} Hz · "
            f"{val:.4g} {unit}"
        ).rstrip()
        self.cursor_info.emit(msg)

    # ------------------------------------------------------------------
    # remarks (annotation parity with the matplotlib canvases)
    # ------------------------------------------------------------------
    def set_remark_enabled(self, enabled: bool) -> None:
        self._remark_enabled = bool(enabled)
        # Right-click priority (measured, pg 0.14.0): ViewBox.mouseClickEvent
        # raises the context menu BEFORE GraphicsScene emits sigMouseClicked
        # (GraphicsScene.sendClickEvent emits at the end), so ev.accept() in
        # _on_scene_click cannot stop the popup. mouseClickEvent is gated on
        # menuEnabled(), so disable the menu while annotating — right-click
        # then reaches _on_scene_click un-consumed and deletes the nearest
        # remark, mirroring the mpl tooltip contract (chart_stack.py:1263).
        self._plot.vb.setMenuEnabled(not self._remark_enabled)

    def clear_remarks(self) -> None:
        for r in self._remarks:
            self._plot.removeItem(r['label'])
            self._plot.removeItem(r['dot'])
        self._remarks = []

    def add_remark_at(self, x: float, y: float) -> None:
        if not self._remark_enabled or not self._has_result:
            return
        val = self._value_at(x, y)
        if val is None:
            return
        label = pg.TextItem(
            f"({x:.3g}, {y:.3g}, {val:.3g})", color='#111827',
            fill=pg.mkBrush(255, 255, 255, 200), anchor=(0, 1),
        )
        label.setPos(x, y)
        dot = pg.ScatterPlotItem(
            [x], [y], size=7, brush=pg.mkBrush('#dc2626'),
            pen=pg.mkPen('w', width=1),
        )
        self._plot.addItem(label)
        self._plot.addItem(dot)
        self._remarks.append({'label': label, 'dot': dot})

    def remove_remark_near(self, x: float, y: float) -> None:
        if not self._remarks:
            return
        (x0, x1, y0, y1) = self._extents
        sx = max(x1 - x0, 1e-12)
        sy = max(y1 - y0, 1e-12)

        def dist(r):
            p = r['dot'].getData()
            return ((p[0][0] - x) / sx) ** 2 + ((p[1][0] - y) / sy) ** 2

        nearest = min(self._remarks, key=dist)
        self._plot.removeItem(nearest['label'])
        self._plot.removeItem(nearest['dot'])
        self._remarks.remove(nearest)

    def _value_at(self, x: float, y: float):
        if self._matrix_disp is None or self._extents is None:
            return None
        x0, x1, y0, y1 = self._extents
        rows, cols = self._matrix_disp.shape
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            return None
        if self._result is not None:
            # Slice (FFT-vs-Time) mode: the matrix rows/cols correspond
            # exactly to result.frequencies / result.times, so pick the
            # cell by argmin-nearest over those axes — the SAME picker used
            # by hover (_on_scene_hover) and frame selection. This keeps the
            # hover readout and the placed remark in agreement on boundary
            # cells, where floor-fraction and argmin-nearest disagree
            # (caliber unification, 裁决 3). Order mode (self._result is
            # None) keeps the floor-fraction mapping below untouched: it has
            # no times/frequencies axis arrays and its remark tests pin the
            # floor-fraction cell.
            row = min(self._freq_index_for(y), rows - 1)
            col = min(self._time_index_for(x), cols - 1)
            return float(self._matrix_disp[row, col])
        col = min(int((x - x0) / max(x1 - x0, 1e-12) * cols), cols - 1)
        row = min(int((y - y0) / max(y1 - y0, 1e-12) * rows), rows - 1)
        return float(self._matrix_disp[row, col])

    def _on_scene_click(self, ev) -> None:
        if not self._plot.sceneBoundingRect().contains(ev.scenePos()):
            return
        p = self._plot.vb.mapSceneToView(ev.scenePos())
        if ev.button() == Qt.LeftButton:
            if self._remark_enabled:
                self.add_remark_at(p.x(), p.y())
            elif self._slice_curve is not None and self._matrix_disp is not None:
                # Left-click positions the slice at the nearest cell along the
                # active axis (X slice → snap time; Y slice → snap freq/order).
                # Works for both FFT-vs-Time and Order.
                self._select_slice_at(p.x(), p.y())
        elif ev.button() == Qt.RightButton and self._remark_enabled:
            # ``insert_in`` puts the ColorBarItem inside the PlotItem
            # layout, so _plot.sceneBoundingRect() includes the colorbar
            # column. Guard out-of-extent points (symmetric with the
            # left-click path, where _value_at rejects them) so a
            # right-click on the colorbar never deletes a remark.
            if self._extents is None:
                return
            x0, x1, y0, y1 = self._extents
            if not (x0 <= p.x() <= x1 and y0 <= p.y() <= y1):
                return
            self.remove_remark_near(p.x(), p.y())
            ev.accept()

    # ------------------------------------------------------------------
    def _on_cbar_levels(self, bar) -> None:
        lo, hi = bar.levels()
        self.levels_changed.emit(float(lo), float(hi))

    # ------------------------------------------------------------------
    def grab_pixmap(self, scale: float = 2.0) -> QPixmap:
        """Snapshot of the canvas for copy/export.

        Consumed by ``chart_stack._grab_pixmap_hidpi`` (chart_stack.py:30)
        as its first-preference branch. Uses ``QWidget.grab()`` + smooth
        magnification rather than ``QWidget.render(QPainter)`` with a
        scale transform: a scaled render() clips to the widget rect in
        device pixels, exporting only the top-left quadrant at 2x
        (verified offscreen, Qt 5.15.14). grab() is also the
        realizability probe (lesson
        2026-04-25-tightbbox-survives-offscreen-qt); pattern mirrors
        PgLineCanvas.grab_pixmap (line_canvas.py:209) and
        Renderer.grab_pixmap / _grab_widget_scaled (renderer.py:283).
        Callers must check ``pix.isNull()`` — the degenerate 1x1
        fallback is never scaled up.
        """
        base = self._glw.grab()
        if base.isNull() or base.width() <= 0 or base.height() <= 0:
            fallback = QPixmap(1, 1)
            fallback.fill(Qt.transparent)
            return fallback
        if scale <= 1.0:
            return base
        return base.scaled(
            int(round(base.width() * scale)),
            int(round(base.height() * scale)),
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )

    # ------------------------------------------------------------------
    # full/main export modes (FFT-vs-Time copy command, M9 wires the modes)
    # ------------------------------------------------------------------
    def grab_full_view(self) -> QPixmap:
        """Snapshot of the entire widget (heatmap + slice row).

        Phase-1 export contract consumed by
        ``MainWindow._copy_fft_time_image`` with ``mode='full'`` (M9
        wiring). Mirrors ``SpectrogramCanvas.grab_full_view``
        (canvases.py:2053 → ``self.grab()``); here the grab targets the
        inner GraphicsLayoutWidget via the shared ``grab_pixmap`` so the
        hi-DPI 2× scaling and the un-scaled 1×1 degenerate fallback stay
        identical to the plain copy/export path.
        """
        return self.grab_pixmap(scale=2.0)

    def grab_main_chart(self) -> QPixmap:
        """Heatmap + colorbar only (no slice row).

        Renders the scene region covering row 0 of the GraphicsLayout
        (the heatmap PlotItem plus its nested colorbar), excluding the
        ``with_slice=True`` frequency-slice strip in row 1. Parity with
        ``SpectrogramCanvas.grab_main_chart`` (canvases.py:2064), used by
        ``MainWindow._copy_fft_time_image`` with ``mode='main'``.

        Falls back to :meth:`grab_full_view` when the scene geometry is
        degenerate (no result plotted, layout not yet realized, or the
        scene rects collapse under offscreen Qt) — the documented headless
        fallback the SpectrogramCanvas original also keeps, so the export
        button never returns a null pixmap when ``has_result()`` is True.
        With ``with_slice=False`` (Order map) there is no row 1, so the
        row-0 region already spans the whole map and ``main ≈ full``.
        """
        scale = 2.0
        scene = self._glw.scene()
        rect = self._plot.sceneBoundingRect()
        if self._cbar is not None:
            # The colorbar is nested in the PlotItem layout via
            # ``insert_in=self._plot``, so it is normally already inside
            # the plot's scene rect; union defensively in case a future
            # pg version lays it out beyond that rect.
            rect = rect.united(self._cbar.sceneBoundingRect())
        if rect.width() < 2 or rect.height() < 2:
            return self.grab_full_view()
        target = QPixmap(int(rect.width() * scale), int(rect.height() * scale))
        target.fill(Qt.white)
        painter = QPainter(target)
        painter.setRenderHint(QPainter.Antialiasing)
        # scene.render(painter, target_rect, source_rect): map the row-0
        # scene rect (heatmap + colorbar) onto the scaled pixmap, cropping
        # out the slice row that sits below it in the scene.
        scene.render(
            painter,
            QRectF(0, 0, rect.width() * scale, rect.height() * scale),
            rect,
        )
        painter.end()
        return target
