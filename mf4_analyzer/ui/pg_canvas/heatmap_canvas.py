"""PgHeatmapCanvas: pyqtgraph heatmap canvas for the Order and
FFT-vs-Time sections.

Replaces ``PlotCanvas.plot_or_update_heatmap`` (canvases.py:2178) and —
with ``with_slice=True`` — ``SpectrogramCanvas`` (canvases.py:1602).
API names/kwargs mirror the matplotlib originals so MainWindow render
paths keep their call sites.

dB conversion is done in the CALLER (plot_result / _render_order_on),
not inside plot_or_update_heatmap. The internal amplitude_db branch was
removed; pass amplitude_mode='amplitude' with pre-converted data and
explicit vmin/vmax so the colour scale is purely display-only.
NO OpenGL anywhere here: OpenGL breaks grab_pixmap exports (all-white,
verified on the time-domain canvas history).
"""
from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QEvent, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPainter, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui._axis_handle import PgAxisHandle
from mf4_analyzer.ui_kit.ticks_math import finite_non_degenerate_range

# The shared analysis axis/tick/dB layer used to live in this file. It now
# lives in analysis_axes.py, but every name is re-exported here so the old
# ``heatmap_canvas.<name>`` paths keep resolving — for external importers
# (ui/main_window/_order_mixin.py, several tests) and for
# ``monkeypatch.setattr(heatmap_canvas, ...)``, which still reaches this
# module's own call sites because they resolve the bare names through these
# globals. Do NOT rewrite the internal call sites to qualify the module.
from mf4_analyzer.ui.pg_canvas.analysis_axes import (  # noqa: F401
    _AUTO_CEILING_PCT,
    _AUTO_SPAN_DB,
    _BOUNDARY_GRID_EPS_PX,
    _BoundaryGridAxisItem,
    _COLORBAR_DEAD_VISIBLE_FRAC,
    _SLICE_MAX_SPAN_DB,
    _SmoothImageItem,
    _TARGET_BOTTOM_TICK_EDGE_PAD_PX,
    _TARGET_BOTTOM_TICK_MIN_COUNT,
    _TARGET_BOTTOM_TICK_MIN_GAP_PX,
    _TARGET_BOTTOM_TICK_MIN_NARROW_GAP_PX,
    _TARGET_BOTTOM_TICK_NICE_FACTORS,
    _apply_axis_tick_density,
    _apply_neutral_axis_frame,
    _apply_target_bottom_ticks,
    _auto_db_window,
    _colorbar_is_dead,
    _finite_data_bounds,
    _finite_float,
    _hide_plot_title,
    _make_analysis_plot,
    _robust_db_ceiling,
    _slice_amp_bounds,
    _tick_counts_to_density,
    _visual_padded_bounds,
    time_axis_display_extent,
)
from mf4_analyzer.ui.pg_canvas.context_menu import redesign_pg_context_menu
from mf4_analyzer.ui.pg_canvas.empty_hint import EmptyHintOverlay
from mf4_analyzer.ui.pg_canvas.slice_panel import _SliceDirToggle, _SliceStrip
from mf4_analyzer.ui.pg_canvas._shared import (
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
from mf4_analyzer.ui.pg_canvas.fonts import _apply_pg_axis_font
from mf4_analyzer.ui.pg_canvas.remarks import (
    RemarkArtist,
    RemarkInteraction,
    RemarkPoint,
    remark_at_viewport_pos,
    viewport_pos_to_scene,
)
from mf4_analyzer.ui.pg_canvas.overlay_intent import AnalysisRemarkStore
from mf4_analyzer.ui.ultraview_capture_facts import (
    build_capture_facts,
    iter_axes_rubberband_items,
    widget_visible_and_sized,
)
from mf4_analyzer.ui.pg_canvas.viewbox import (
    _ModifierWheelViewBox,
    _WheelDeltaGraphicsLayoutWidget,
)
from mf4_analyzer.ui_kit.axis_metrics import left_axis_width_for_ticks


# 色图整族的真源在 qt_analysis_shared：批处理渲染器要用同一份解析结果，
# 而它不能 import mf4_analyzer.ui。这里保留同名再导出，既有 import 路径
# （含 tests/ui/test_colormap_parity.py）不受影响。
from mf4_analyzer.qt_analysis_shared import (  # noqa: F401
    DEFAULT_HEATMAP_CMAP,
    DEFAULT_HEATMAP_INTERP,
    HEATMAP_SMOOTH_INTERP_MODES,
    SUPPORTED_HEATMAP_COLORMAPS,
    _GNUPLOT2_COLORMAP,
    _gnuplot2_lut,
    amplitude_mode_is_db,
    _normalise_colormap_name,
    _resolve_colormap,
)


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


class _NamedColorMap:
    __slots__ = ("name",)

    def __init__(self, name: str):
        self.name = _normalise_colormap_name(name)


class _HeatmapMappable:
    """Matplotlib-like color mappable facade for ChartOptionsDialog."""

    def __init__(self, canvas):
        self._canvas = canvas

    def get_cmap(self):
        return _NamedColorMap(
            getattr(self._canvas, "_cmap_name", DEFAULT_HEATMAP_CMAP))

    def set_cmap(self, name):
        name = _normalise_colormap_name(name)
        cm = _resolve_colormap(name)
        canvas = self._canvas
        canvas._cmap_name = name
        canvas._img.setColorMap(cm)
        if canvas._cbar is not None:
            canvas._cbar.setColorMap(cm)
        canvas.layout_geometry_changed.emit()

    def get_clim(self):
        canvas = self._canvas
        if canvas._cbar is not None:
            lo, hi = canvas._cbar.levels()
            return float(lo), float(hi)
        levels = canvas._img.getLevels()
        if levels is not None:
            lo, hi = levels
            return float(lo), float(hi)
        bounds = _finite_data_bounds(canvas._matrix_disp)
        if bounds is None:
            # No finite cells and no installed levels: display empty-state
            # placeholder only (B5 — shared helper no longer invents 0..1).
            return 0.0, 1.0
        return bounds

    def set_clim(self, vmin, vmax):
        lo, hi = float(vmin), float(vmax)
        canvas = self._canvas
        canvas._img.setLevels((lo, hi))
        if canvas._cbar is not None:
            canvas._cbar.blockSignals(True)
            canvas._cbar.setLevels((lo, hi))
            canvas._cbar.blockSignals(False)
        canvas.levels_changed.emit(lo, hi)
        canvas.layout_geometry_changed.emit()

    def get_array(self):
        return self._canvas._matrix_disp


class _HeatmapAxisHandle(PgAxisHandle):
    def __init__(self, canvas):
        super().__init__(canvas._plot, owner_canvas=canvas)
        self._canvas = canvas
        self._mappable = _HeatmapMappable(canvas)

    def get_mappables(self):
        if self._canvas._matrix_disp is None:
            return []
        return [self._mappable]


def colorbar_interaction_active(cbar) -> bool:
    """True while the user is dragging a ColorBarItem handle or the band.

    ``ColorBarItem.setLevels`` writes ``lo_prv`` / ``hi_prv``. Doing that
    while the region handles are still offset from the snap-back positions
    (63, 191) makes the next mouse-move compound the delta and run the
    colour window to the inspector spin limits.
    """
    if cbar is None:
        return False
    region = getattr(cbar, 'region', None)
    if region is None:
        return False
    if bool(getattr(region, 'moving', False)):
        return True
    for line in getattr(region, 'lines', ()) or ():
        if bool(getattr(line, 'moving', False)):
            return True
    return False


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


def _heatmap_xy_from_viewbox(view_box):
    """Finite non-degenerate ``((x0, x1), (y0, y1))`` from a ViewBox, else None."""
    try:
        (x0, x1), (y0, y1) = view_box.viewRange()
    except Exception:
        return None
    xr = finite_non_degenerate_range(x0, x1)
    yr = finite_non_degenerate_range(y0, y1)
    if xr is None or yr is None:
        return None
    return xr, yr


class PgHeatmapCanvas(_StackedSplitMixin, QWidget):
    cursor_info = pyqtSignal(str)
    context_menu_requested = pyqtSignal()
    # Emitted when the user drags the interactive colorbar (lo, hi).
    levels_changed = pyqtSignal(float, float)
    manual_zoom_changed = pyqtSignal(bool)
    # User pan/box/modifier-wheel/View-All on the heatmap (not the slice).
    # plot_or_update_heatmap / empty View-All / full_reset must not emit this.
    viewport_intent_committed = pyqtSignal()
    # Emitted after labels/ticks/title/colorbar changes that can resize the
    # pyqtgraph layout. Analysis split pages coalesce this and align panes.
    layout_geometry_changed = pyqtSignal()
    # Emitted after a render path programmatically resets image/colorbar levels.
    levels_rebased = pyqtSignal()
    # Double-click restore of the last render window. Distinct from
    # ``levels_changed`` (live drag) so locked-level linkage and inspector
    # echo can treat restore as a finished window, not an in-progress drag.
    colorbar_restored = pyqtSignal(float, float)
    # Hidden-gesture discovery signals. The chart card connects these to the
    # hint system (mark_discovered / flash) so the matching rotating-pool tip
    # retires once the user has performed the gesture for the first time.
    slice_picked = pyqtSignal()       # user clicked the map to position a slice
    slice_hint_requested = pyqtSignal(str)  # user clicked where no slice can apply
    divider_adjusted = pyqtSignal()   # user dragged / reset the map↔slice divider
    markup_revision_changed = pyqtSignal()

    def __init__(self, parent=None, with_slice: bool = False):
        super().__init__(parent)
        self._with_slice = bool(with_slice)
        self._glw = _WheelDeltaGraphicsLayoutWidget(self, owner_canvas=self)
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
        # Levels (vmin, vmax) the last render applied. Double-click-on-colorbar
        # resets to these (the colour window is display-only — the matrix is
        # never clipped to it). None until the first render.
        self._rendered_levels = None
        self._has_result = False
        self._matrix_disp = None  # display-space matrix
        self._extents = None      # (x0, x1, y0, y1)
        self._raw_title = ''
        self._split_title_width = None
        self._remarks = []
        self._remark_intent = AnalysisRemarkStore()
        self._overlay_source = None
        self._remark_enabled = False
        self.markup_revision = 0
        self._remark_artist = RemarkArtist(on_moved=self._bump_markup_revision)
        self._remark_interaction = RemarkInteraction(
            add_at_viewport_pos=lambda pos: self._add_remark_at_viewport_pos(pos),
            remove_at_viewport_pos=lambda pos: self._remove_remark_at_viewport_pos(pos),
            remark_at_viewport_pos=lambda pos: self._remark_item_at_viewport_pos(pos),
        )
        self._empty_hint_text = ''
        self._empty_hint_item = None
        # The overlay owns the behaviour; the two attributes above stay the
        # public read surface (main_window and several tests read them).
        self._empty_hint = EmptyHintOverlay(
            viewbox_getter=lambda: self._plot.vb,
            reposition_slot=self._reposition_empty_hint,
            on_state=self._store_empty_hint_state,
        )
        self._mouse_mode_controller = None
        self._copy_image_handler = None
        self._bottom_tick_target = None
        self._bottom_tick_density = None
        self._slice_aa_on = True
        self._slice_aa_idle_timer = QTimer(self)
        self._slice_aa_idle_timer.setSingleShot(True)
        self._slice_aa_idle_timer.setInterval(150)
        self._slice_aa_idle_timer.timeout.connect(self.try_enable_idle_quality)
        # remarks: card contract is set_remark_enabled / clear_remarks
        # (chart_stack.py:1314, 1330-1332).
        self._plot.scene().sigMouseClicked.connect(self._on_scene_click)
        self._plot.scene().sigMouseMoved.connect(self._on_scene_hover)
        try:
            viewport = self._glw.viewport()
            if viewport is not None:
                viewport.setMouseTracking(True)
                viewport.installEventFilter(self)
        except Exception:
            pass
        self._plot.vb.sigXRangeChanged.connect(self._refresh_bottom_x_ticks)
        self._plot.vb.sigResized.connect(self._refresh_bottom_x_ticks)
        self._plot.vb.sigRangeChangedManually.connect(
            self._on_interactive_range_changed)
        self._plot.vb.sigRangeChangedManually.connect(self._on_main_manual_zoom)
        # Wheel / Home / inspector setRange are programmatic and do not emit
        # sigRangeChangedManually. The slice still has to follow the live map
        # when the inspector axis is auto.
        self._plot.vb.sigRangeChanged.connect(self._sync_slice_to_heatmap_view)

        # Slice row (with_slice=True). Every consumer guards on
        # ``self._slice_curve is not None``.
        #
        # The behaviour lives on _SliceStrip; the fields below stay canvas
        # attributes because tests and ui/main_window read them directly, and
        # the strip forwards to them through _CanvasBackref. Every public
        # slice method on this class is a thin delegate to self._slice.
        self._slice = _SliceStrip(self)
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
        # Last slice positions kept in COORDINATE space (time value / frequency
        # value) so a re-render can map the cursor back to the nearest index
        # instead of jumping to the matrix centre. None until the first seed.
        self._slice_x_val: float | None = None
        self._slice_y_val: float | None = None
        self._slice_marker_updating = False
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
        self._cmap_name = DEFAULT_HEATMAP_CMAP
        # Amplitude mode of the last plot_result render (slice mode only).
        # Parity with SpectrogramCanvas._amplitude_mode (canvases.py:1622):
        # annotation/slice labels values 'dB' in dB mode and the
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
        # Set by plot_result when z_auto=True so the caller can read back
        # the absolute vmin/vmax that were actually applied and write them
        # into the inspector spins (blockSignals) — eliminating the jump
        # when the user switches from auto to manual mode.
        self._last_auto_levels: tuple[float, float] | None = None
        # dB-reference-defaults Task 7 (spec §8.3.1): the dB reference the
        # last db-mode render on THIS canvas actually used (None until the
        # first db-mode render). reference_delta_since_last_render() diffs
        # a NEW reference against this so a caller can shift an
        # already-tuned MANUAL colour window by the same delta as the
        # (unclipped) shifted matrix instead of leaving it black/blank.
        self._last_db_reference: float | None = None
        # The (vmin, vmax) plot_result actually applied AFTER shifting a
        # manual window for a reference change this render, or None when no
        # shift happened. _render_fft_time_on reads this to write the
        # shifted numbers back into the inspector spins -- parity with the
        # existing _last_auto_levels write-back for the auto branch.
        self._last_manual_levels_shifted: tuple[float, float] | None = None
        # Latest explicit label context (spec §15 C2/C3): set by
        # plot_result / plot_or_update_heatmap from the caller-supplied
        # amplitude_label / z_unit_suffix kwargs. None means "no override" --
        # the slice axis / readout / remark consumers fall back to the
        # historical 'Amplitude (dB)' / 'dB' literal so legacy callers that
        # never pass the new kwargs see unchanged output.
        self._amplitude_axis_label: str | None = None
        self._z_unit_suffix: str | None = None
        # Panel-driven axis ranges for the FFT-vs-Time slice (display-only).
        # Set by plot_result from the inspector knobs; the slice consults them
        # instead of the live viewbox range so a manual panel min/max governs
        # the slice axes regardless of pan/zoom. None == "auto" → the slice
        # falls back to the live view range (heatmap pan/zoom) for that axis.
        #   _panel_time_range: (lo, hi) for the X/time axis, or None (auto)
        #   _panel_freq_range: (lo, hi) for the Y/frequency-order axis, or None
        #   _panel_amp_range:  (z_floor, z_ceiling) for the amplitude axis, or
        #                      None when z_auto (auto-fit the visible data)
        # These stay None on the Order path (plot_or_update_heatmap clears them),
        # preserving its existing live-view-range slice behaviour.
        self._panel_time_range: tuple[float, float] | None = None
        self._panel_freq_range: tuple[float, float] | None = None
        self._panel_amp_range: tuple[float, float] | None = None
        self._heatmap_range_updating = False
        self._slice_view_syncing = False
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
            self._slice_plot.vb.sigRangeChangedManually.connect(
                self._on_interactive_range_changed)
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
                angle=90,
                movable=True,
                pen=pg.mkPen('#e03131', width=1),
                hoverPen=pg.mkPen('#ff3b30', width=3),
            )
            self._plot.addItem(self._slice_marker)
            self._slice_marker.setVisible(False)
            self._slice_marker.sigPositionChanged.connect(
                self._on_slice_marker_dragged)
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
            # Surface the divider gesture to the hint system (retires the
            # "drag the divider" tip once the user has actually used it).
            self._split_divider.drag_started.connect(self.divider_adjusted)
            self._split_divider.reset_requested.connect(self.divider_adjusted)
            self._collapsed_rail = _CollapsedRail(self)
            self._collapsed_rail.setVisible(False)
            self.layout().addWidget(self._collapsed_rail)
            self._collapsed_rail.expand_requested.connect(
                lambda: self._set_bottom_collapsed(False))
            self._plot.vb.sigResized.connect(self._position_collapse_ctrl)
            self._ensure_colorbar(
                _resolve_colormap(self._cmap_name), 'Amplitude (dB)')
        else:
            self._collapsed_rail = None
            self._split_divider = None
            self._bottom_collapsed = False
            self._bottom_split_default = 140.0
            self._bottom_split_h = self._bottom_split_default
            self._drag_start_bottom_h = self._bottom_split_h
            self._split_aligned = False
        self._apply_default_axis_labels()
        # Empty state on construction: pin a fixed non-negative range so the
        # blank map never inherits pyqtgraph's default symmetric [-0.5, 0.5]
        # (negative time/freq/order ticks). Real extents from the first
        # plot_or_update_heatmap override this via setXRange/setYRange.
        self._apply_empty_state_range()

    @staticmethod
    def _set_curve_aa(curve, on: bool) -> None:
        on = bool(on)
        try:
            curve.opts["antialias"] = on
        except Exception:
            pass
        child = getattr(curve, "curve", None)
        if child is not None:
            try:
                child.opts["antialias"] = on
                child.update()
            except Exception:
                pass

    def _apply_slice_curve_aa_state(self) -> None:
        return self._slice._apply_slice_curve_aa_state()

    def _reset_slice_quality_for_rebuild(self) -> None:
        return self._slice._reset_slice_quality_for_rebuild()

    def disable_interactive_quality(self) -> None:
        """Drop slice-curve AA while the user is actively moving the view."""
        try:
            self._slice_aa_idle_timer.stop()
        except Exception:
            pass
        if self._slice_curve is None or not self._slice_aa_on:
            return
        self._slice_aa_on = False
        self._apply_slice_curve_aa_state()

    def schedule_idle_quality(self) -> None:
        """Restore slice-curve AA after the interaction has settled."""
        if self._slice_curve is None:
            return
        try:
            self._slice_aa_idle_timer.start()
        except Exception:
            pass

    def try_enable_idle_quality(self) -> None:
        if self._slice_curve is None or self._slice_aa_on:
            return
        try:
            if QApplication.mouseButtons() != Qt.NoButton:
                self._slice_aa_idle_timer.start()
                return
        except Exception:
            pass
        self._slice_aa_on = True
        self._apply_slice_curve_aa_state()

    def _on_interactive_range_changed(self, *_args) -> None:
        self.disable_interactive_quality()
        self.schedule_idle_quality()

    def _on_main_manual_zoom(self, *_args) -> None:
        self.manual_zoom_changed.emit(True)
        self._emit_viewport_intent()

    def _emit_viewport_intent(self) -> None:
        if not self._has_result:
            return
        self.viewport_intent_committed.emit()

    def capture_xy_viewport(self):
        """Return the heatmap's finite X/Y window, else ``None``.

        Slice subplot and Z/colorbar levels are not part of this viewport.
        """
        if not self._has_result:
            return None
        return _heatmap_xy_from_viewbox(self._plot.vb)

    def data_xy_extents(self):
        """Raw image extents (flush-edge), independent of the live zoom."""
        if self._extents is None:
            return None
        x0, x1, y0, y1 = self._extents
        xr = finite_non_degenerate_range(x0, x1)
        yr = finite_non_degenerate_range(y0, y1)
        if xr is None or yr is None:
            return None
        return xr, yr

    def restore_xy_viewport(self, xlim, ylim) -> bool:
        """Apply a saved heatmap X/Y window and resync the 1D slice."""
        if not self._has_result:
            return False
        try:
            xr = finite_non_degenerate_range(xlim[0], xlim[1])
            yr = finite_non_degenerate_range(ylim[0], ylim[1])
        except (TypeError, ValueError, IndexError):
            return False
        if xr is None or yr is None:
            return False
        self._heatmap_range_updating = True
        try:
            self._plot.setXRange(xr[0], xr[1], padding=0)
            self._plot.setYRange(yr[0], yr[1], padding=0)
        finally:
            self._heatmap_range_updating = False
        self._sync_slice_to_heatmap_view()
        return True

    def _sync_slice_to_heatmap_view(self, *_args) -> None:
        """Re-clip the 1D slice to the heatmap's current view.

        Inspector-manual panel ranges still win inside ``_slice_axis_range``.
        Skips chrome/layout so pan, wheel and Home can call this every tick.
        """
        if self._heatmap_range_updating or self._slice_view_syncing:
            return
        if self._slice_curve is None or self._matrix_disp is None:
            return
        self._slice_view_syncing = True
        try:
            self._slice._apply_slice(refresh_chrome=False)
        finally:
            self._slice_view_syncing = False

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
    # empty hint (source/params selected, result cache not ready)
    # ------------------------------------------------------------------
    def _store_empty_hint_state(self, item, text: str) -> None:
        self._empty_hint_item = item
        self._empty_hint_text = text

    def show_empty_hint(self, text: str) -> None:
        self._empty_hint.show(text)

    def _reposition_empty_hint(self, *_args) -> None:
        self._empty_hint.reposition()

    def clear_empty_hint(self) -> None:
        self._empty_hint.clear()

    def reference_delta_since_last_render(self, new_reference: float) -> float | None:
        """Spec §8.3.1: dB-reference-change × manual colour levels.

        Returns ``20*log10(old/new)`` if this canvas's dB reference changed
        since ITS OWN last db-mode render, else ``None`` (no prior render on
        this canvas, or the reference did not actually change). Always
        stamps ``new_reference`` as the new tracked value, so a second call
        in the same render (or the next render with the same source) reports
        no further change.

        Callers use the returned delta to shift an already-tuned MANUAL
        z-window (``[floor, ceiling] -> [floor+delta, ceiling+delta]``) so it
        keeps tracking the shifted dB matrix instead of appearing to go
        black/blank; this method itself never touches any matrix or widget --
        it is a pure delta calculator (2026-06-21 clip red line: colour-scale
        state must stay display-only).
        """
        try:
            new_reference = float(new_reference)
        except (TypeError, ValueError):
            return None
        old_reference = self._last_db_reference
        self._last_db_reference = new_reference
        if old_reference is None or old_reference <= 0 or new_reference <= 0:
            return None
        if old_reference == new_reference:
            return None
        delta = 20.0 * math.log10(old_reference / new_reference)
        return delta if np.isfinite(delta) and delta != 0.0 else None

    # ------------------------------------------------------------------
    # main API (signature mirrors canvases.PlotCanvas.plot_or_update_heatmap)
    # ------------------------------------------------------------------
    def plot_or_update_heatmap(
        self, matrix, x_extent, y_extent, *,
        x_label='', y_label='', title='', cmap=DEFAULT_HEATMAP_CMAP, interp=None,
        cbar_label='Amplitude', amplitude_mode='amplitude',
        z_auto=True, z_floor=-30.0, z_ceiling=0.0,
        x_auto=True, x_min=0.0, x_max=0.0,
        y_auto=True, y_min=0.0, y_max=0.0,
        vmin=None, vmax=None,
        x_coords=None, y_coords=None,
        amplitude_label=None, z_unit_suffix=None,
    ):
        self.clear_empty_hint()
        # Reset any panel-driven slice ranges. plot_result re-sets them AFTER
        # this call from the FFT-vs-Time inspector knobs; direct callers (the
        # Order path) leave them None so the slice keeps following the live
        # heatmap view range.
        self._panel_time_range = None
        self._panel_freq_range = None
        self._panel_amp_range = None
        # dB-reference-defaults Task 7 (spec §15 C2/C3): explicit label
        # context from the caller (FFT-time / Order mixins), stored so the
        # slice axis (_apply_slice / _apply_default_axis_labels) and the
        # readout/remark consumers (_readout_unit / _z_unit) can share the
        # SAME formatted string as the colorbar (cbar_label above). None
        # preserves the historical 'Amplitude (dB)' / 'dB' literal for
        # legacy direct callers that never pass these kwargs.
        self._amplitude_axis_label = amplitude_label
        self._z_unit_suffix = z_unit_suffix
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
        interp_mode = (
            DEFAULT_HEATMAP_INTERP if interp is None else str(interp).lower()
        )
        smooth = interp_mode in HEATMAP_SMOOTH_INTERP_MODES
        self._img.set_smooth_transform(smooth)
        if amplitude_mode_is_db(amplitude_mode):
            raise ValueError(
                "amplitude_db is not accepted by plot_or_update_heatmap. "
                "Convert to dB in the caller (plot_result / _render_order_on) "
                "and pass amplitude_mode='amplitude' with explicit vmin/vmax."
            )

        m = np.asarray(matrix, dtype=float)

        bounds = _finite_data_bounds(m)
        if bounds is None:
            # No finite cells: ImageItem still needs a finite window. This is
            # the leaf no-data placeholder (B5); the shared helper returns None.
            auto_vmin, auto_vmax = 0.0, 1.0
        else:
            auto_vmin, auto_vmax = bounds
        if vmin is None:
            vmin = float(z_floor) if not z_auto else auto_vmin
        if vmax is None:
            vmax = float(z_ceiling) if not z_auto else auto_vmax

        x0, x1 = float(x_extent[0]), float(x_extent[1])
        y0, y1 = float(y_extent[0]), float(y_extent[1])

        self._cmap_name = _normalise_colormap_name(cmap)
        cm = _resolve_colormap(self._cmap_name)
        self._img.setImage(m, autoLevels=False)
        self._img.setRect(QRectF(x0, y0, x1 - x0, y1 - y0))
        self._img.setColorMap(cm)

        self._ensure_colorbar(cm, cbar_label)

        # Never rewrite ColorBarItem.lo_prv/hi_prv (or the restore snapshot)
        # while a handle is down — that compounds the next mouse-move.
        applied_levels = False
        if not colorbar_interaction_active(self._cbar):
            self._img.setLevels((vmin, vmax))
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
            # Remember the render window so double-click-on-colorbar can restore it.
            self._rendered_levels = (float(vmin), float(vmax))
            applied_levels = True

        self._plot.setLabel('bottom', self._x_label)
        self._plot.setLabel('left', self._y_label)
        self._raw_title = title or ''
        self._apply_title_text()

        self._heatmap_range_updating = True
        try:
            if x_auto:
                self._plot.setXRange(x0, x1, padding=0)
            elif x_max > x_min:
                self._plot.setXRange(float(x_min), float(x_max), padding=0)
            if y_auto:
                self._plot.setYRange(y0, y1, padding=0)
            elif y_max > y_min:
                self._plot.setYRange(float(y_min), float(y_max), padding=0)
        finally:
            self._heatmap_range_updating = False

        # Remark labels embed the z value, so a replot must re-snap to the
        # new matrix. Intent stays; Qt items are a projection.
        self._drop_remark_projection()
        self._matrix_disp = m
        self._extents = (x0, x1, y0, y1)
        self._has_result = True
        self._reset_slice_quality_for_rebuild()
        # Emit after has_result / _matrix_disp so locked-split re-lock
        # (``_on_canvas_levels_rebased``) can merge both panes.
        if applied_levels:
            self.levels_rebased.emit()
        self.layout_geometry_changed.emit()
        self.manual_zoom_changed.emit(False)
        self._project_remarks()

    def has_result(self) -> bool:
        return self._has_result

    def has_plotted_result(self) -> bool:
        return self.has_result()

    def capture_quality_settled(self) -> bool:
        # Heatmap has no quality_status traffic light; missing is explicit.
        return True

    def capture_interaction_idle(self) -> bool:
        # Coordinator historically did not probe ``_slice_aa_idle_timer``.
        return True

    def capture_cursor_facts(self):
        return False, None

    def capture_markup_revision(self) -> int:
        return int(self.markup_revision or 0)

    def iter_transient_overlay_items(self, *, section: str = "unknown"):
        yield from iter_axes_rubberband_items(self)

    def presentation_capture_facts(self):
        dual, geometry = self.capture_cursor_facts()
        return build_capture_facts(
            host_kind="fft_time" if self._with_slice else "order",
            visible_and_sized=widget_visible_and_sized(self),
            has_real_result=self.has_plotted_result(),
            quality_settled=self.capture_quality_settled(),
            interaction_idle=self.capture_interaction_idle(),
            cursor_dual=dual,
            cursor_geometry=geometry,
            markup_revision=self.capture_markup_revision(),
        )

    def full_reset(self) -> None:
        """Clear the heatmap, colorbar, remarks and result state.

        File-close contract: ``ChartStack.full_reset_all``
        (chart_stack.py:2336) calls ``full_reset()`` on every canvas —
        mirrors ``PlotCanvas.full_reset`` (canvases.py:655), which wiped
        the whole matplotlib figure. The colorbar is detached (not just
        hidden) so a stale color scale never outlives its data; the next
        ``plot_or_update_heatmap`` recreates it.
        """
        self.clear_empty_hint()
        self.clear_remarks()
        self._overlay_source = None
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
        self._last_db_reference = None
        self._last_manual_levels_shifted = None
        self._amplitude_axis_label = None
        self._z_unit_suffix = None
        self._x_coords = None
        self._y_coords = None
        if self._slice_curve is not None:
            self._slice_curve.clear()
            _hide_plot_title(self._slice_plot)
            self._slice_marker.setVisible(False)
            if self._slice_panel is not None:
                self._slice_panel.show()
        if self._with_slice:
            self._ensure_colorbar(
                _resolve_colormap(self._cmap_name), 'Amplitude (dB)')
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

    def _current_amplitude_axis_label(self) -> str:
        """The slice's amplitude (left) axis text: the caller-supplied
        ``amplitude_label`` (spec §15 C2/C3 label context) when set, else the
        historical 'Amplitude (dB)' / 'Amplitude' literal so legacy callers
        that never pass the new kwarg see unchanged output."""
        if self._amplitude_axis_label is not None:
            return self._amplitude_axis_label
        return (
            'Amplitude (dB)'
            if amplitude_mode_is_db(self._amplitude_mode)
            else 'Amplitude'
        )
    def _apply_default_axis_labels(self) -> None:
        self._x_label = self._default_x_label
        self._y_label = self._default_y_label
        self._plot.setLabel('bottom', self._default_x_label)
        self._plot.setLabel('left', self._default_y_label)
        if self._slice_plot is not None:
            bottom = (self._default_x_label if self._slice_dir == 'y'
                      else self._default_y_label)
            self._slice_plot.setLabel('bottom', bottom)
            self._slice_plot.setLabel('left', self._current_amplitude_axis_label())

    def register_mouse_mode_controller(self, controller) -> None:
        self._mouse_mode_controller = controller

    def register_copy_image_handler(self, handler) -> None:
        self._copy_image_handler = handler

    def _plot_item_for_view_box(self, view_box):
        for plot in (self._plot, self._slice_plot):
            if plot is not None and plot.vb is view_box:
                return plot
        return self._plot

    def _redesign_context_menu_for_viewbox(self, view_box, menu) -> None:
        slice_vb = self._slice_plot.vb if self._slice_plot is not None else None
        y_fit = self._fit_slice_y_to_visible_x if view_box is slice_vb else None
        redesign_pg_context_menu(
            menu,
            self._plot_item_for_view_box(view_box),
            self._mouse_mode_controller,
            view_all_handler=self.reset_view_to_data_extents,
            y_autofit_handler=y_fit,
            copy_image_handler=self._copy_image_handler,
            allow_y_grid=True,
            # Plot Options hidden for now in the fft_time / order sections
            # (per request). Default is already False; set explicitly so the
            # intentional "off for now" reads clearly and is easy to flip back.
            keep_plot_options=False,
            view_box=view_box,
        )

    def _handle_wheel_dispatch(self, *, delta, modifiers, x_pos, y_pos,
                               view_box=None, scene_pos=None, axis=None):
        """Lock the wheel to one axis on the spectrogram, matching the line
        canvases and the footer hint (``Ctrl + 滚轮`` → X, ``Shift + 滚轮`` → Y).

        Without this the spectrogram fell back to pyqtgraph's default wheel
        (both axes at once, no Ctrl/Shift lock), so the chart-card footer's
        "Ctrl 缩放 X / Shift 缩放 Y" guidance was literally wrong on Order /
        FFT-vs-Time. Mirrors ``PgLineCanvas._handle_wheel_dispatch``: only the
        modifier-held wheel is consumed; a plain wheel returns False so the
        ViewBox keeps its native both-axis zoom. Applies to whichever viewbox
        was scrolled (the 2D map or, with_slice, the 1D slice subplot)."""
        step = 1 if delta > 0 else -1 if delta < 0 else 0
        if step == 0 or view_box is None:
            return False
        ctrl = bool(modifiers & Qt.ControlModifier)
        shift = bool(modifiers & Qt.ShiftModifier)
        if not (ctrl or shift):
            return False

        factor = 0.85 if step > 0 else 1.0 / 0.85
        try:
            x_range, y_range = view_box.viewRange()
            if ctrl:
                lo, hi = x_range
                center = float(x_pos) if np.isfinite(x_pos) else (lo + hi) / 2.0
                view_box.setXRange(
                    center - (center - lo) * factor,
                    center + (hi - center) * factor,
                    padding=0,
                )
            elif shift:
                lo, hi = y_range
                center = float(y_pos) if np.isfinite(y_pos) else (lo + hi) / 2.0
                view_box.setYRange(
                    center - (center - lo) * factor,
                    center + (hi - center) * factor,
                    padding=0,
                )
        except Exception:
            return False
        self.disable_interactive_quality()
        self.schedule_idle_quality()
        if view_box is self._plot.vb:
            self.manual_zoom_changed.emit(True)
            self._emit_viewport_intent()
        self.layout_geometry_changed.emit()
        return True

    def set_tick_density(self, x, y) -> None:
        """Apply inspector tick density.

        ``x``/``y`` are approximate tick COUNTS from
        ``inspector.top.tick_density()`` (spinboxes: x 3-30 default 10,
        y 3-20 default 10) — the same integers the mpl canvases fed into
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

    def open_chart_options_dialog(self, parent=None):
        """Open coordinate/color-scale options for the main heatmap."""
        from mf4_analyzer.ui import _axis_interaction

        handle = _HeatmapAxisHandle(self)
        target_parent = parent if parent is not None else self.window()
        return bool(_axis_interaction.edit_chart_options_dialog(
            target_parent, handle))

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

    def get_data_x_union(self):
        """Return ``(lo, hi)`` spanning plotted X data, or None when empty.

        Same contract as ``PgTimedomainCanvas.get_data_x_union``: the raw
        extent of what is currently drawn (heatmap ``_extents`` X), with no
        view padding. Used by「全部」/ Home framing helpers.
        """
        if self._extents is None:
            return None
        x0, x1 = float(self._extents[0]), float(self._extents[1])
        if not (np.isfinite(x0) and np.isfinite(x1)) or x1 <= x0:
            return None
        return x0, x1

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
            self.manual_zoom_changed.emit(False)
            return
        x0, x1, y0, y1 = self._extents
        self._heatmap_range_updating = True
        try:
            self._plot.setXRange(x0, x1, padding=0)
            self._plot.setYRange(y0, y1, padding=0)
        finally:
            self._heatmap_range_updating = False
        self._sync_slice_to_heatmap_view()
        self.manual_zoom_changed.emit(False)
        self._emit_viewport_intent()

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
        self, result, *, amplitude_mode='amplitude_db', cmap=DEFAULT_HEATMAP_CMAP,
        z_auto=False, z_floor=-80.0, z_ceiling=0.0, freq_range=None,
        x_auto=True, x_min=0.0, x_max=0.0,
        y_auto=True, y_min=0.0, y_max=0.0,
        interp=DEFAULT_HEATMAP_INTERP, db_reference=1.0,
        amplitude_label=None, colorbar_label=None, z_unit_suffix=None,
    ):
        """Render a ``SpectrogramResult`` as a 2D heatmap + frequency slice.

        Signature mirrors ``SpectrogramCanvas.plot_result``
        (canvases.py:1722) and the ``MainWindow._render_fft_time`` call
        site (main_window.py:2825). ``result.amplitude`` is shape
        ``(freq_bins, frames)`` → rows are frequency (Y), columns are
        time (X).

        ``db_reference`` is a DISPLAY-only kwarg (NOT a field on
        ``result.params``): it is the dB normalisation reference the caller
        reads from the inspector at render time, so changing it re-renders
        without a recompute. dB conversion is done HERE (memoized via
        ``self._db_cache``, keyed ``(self._result_db_token(result),
        db_reference)`` — a monotonic epoch token stamped on each result,
        NOT ``id(result)``, so the memo never returns a stale matrix after an
        ``AnalysisResultCache`` eviction frees + reuses an id()), and the
        already-converted
        display matrix is handed to ``plot_or_update_heatmap`` with
        ``amplitude_mode='amplitude'`` plus explicit ``vmin``/``vmax`` so
        the heatmap's internal dB/auto branch never re-derives the
        levels. The explicit ``vmin``/``vmax`` survive because the linear
        branch of ``plot_or_update_heatmap`` only fills them from
        nanmin/nanmax when they are ``None``.

        ``amplitude_label`` / ``colorbar_label`` / ``z_unit_suffix`` are the
        explicit label context (spec §15 C2, Task 7): when the caller (the
        FFT-vs-Time mixin) supplies them, the colorbar, slice amplitude axis
        and readout/remark ALL show the same formatted ``dB[A] re ...``
        text. Omitting them (``None``) reproduces the historical inline
        ``f"Amplitude{unit} (dB re {db_ref:g})"`` colorbar text and the bare
        ``'Amplitude (dB)'`` slice label, so existing direct callers/tests
        that never pass the new kwargs see unchanged output. A MANUAL
        (``z_auto=False``) z-window is shifted by ``delta =
        20*log10(old_ref/new_ref)`` whenever this canvas's dB reference
        changes between renders (spec §8.3.1) — the shift only ever moves
        the display LEVELS, never the stored matrix.
        """
        self._result = result
        # Pin the amplitude mode so annotation/slice labels read the value as
        # 'dB' (not the channel unit) in dB mode, and the slice y-label
        # switches accordingly — parity with SpectrogramCanvas
        # (canvases.py:1762, 1879, 1942, 2028).
        self._amplitude_mode = amplitude_mode
        unit = f" ({result.unit})" if result.unit else ""
        # db_reference is DISPLAY-only: it arrives as a kwarg (sourced from the
        # inspector at render time), NOT from result.params — SpectrogramParams
        # no longer carries it, so changing it never invalidates the compute
        # cache key.
        db_ref = float(db_reference)
        if amplitude_mode_is_db(amplitude_mode):
            key = (self._result_db_token(result), db_ref)
            if self._db_cache is None or self._db_cache[0] != key:
                from ...signal.spectrogram import SpectrogramAnalyzer
                self._db_cache = (key, SpectrogramAnalyzer.amplitude_to_db(
                    result.amplitude, db_ref))
            m = self._db_cache[1]
            # Do NOT clip the matrix to [z_floor, z_ceiling] in manual mode.
            # The display LEVELS (vmin/vmax below) clamp the COLOURS, while the
            # stored matrix must stay full-range so a colorbar drag — which only
            # changes display levels, not the stored data — can remap it without
            # a recompute.  Clipping baked the colour window into the data:
            # computing at e.g. [27, 67] when the data lived in [-47, 6]
            # flattened the whole matrix to 27, and a later drag to [-33, 6.72]
            # could not recover any detail (the user's all-black → all-red →
            # must-recompute report). Slice and annotation read _matrix_disp too,
            # so an unclipped matrix also makes them show the true dB values.
            #
            # Spec §8.3.1: diff THIS render's reference against the last one
            # this canvas actually used, so a manual window can be shifted by
            # the same delta as the (unclipped) matrix below.
            reference_delta = self.reference_delta_since_last_render(db_ref)
            if z_auto:
                # Use a fixed SPAN anchored at a robust high-percentile
                # ceiling so the auto window is expressed in *absolute* dB —
                # matching the manual-mode semantics of z_floor/z_ceiling.
                # This eliminates the 30-40 dB jump that occurred when the old
                # code used z_floor/z_ceiling as *peak offsets* while the
                # manual path treated them as absolute values.
                #
                # The ceiling is the _AUTO_CEILING_PCT percentile, NOT the
                # literal max: real spectra have transient peaks tens of dB
                # above the bulk, and anchoring on the max buried the whole
                # informative field below the floor (an all-dark image the
                # user had to drag down ~38 dB to read).  _AUTO_SPAN_DB and
                # the percentile are intentionally NOT read from the spin
                # widgets, to prevent a feedback loop. Auto levels simply
                # re-derive from the new matrix — no reference-delta shift
                # needed (spec §8.3.1: "自动色阶不需处理").
                window = _auto_db_window(m)
                if window is None:
                    # All-non-finite matrix: keep a display placeholder and
                    # do not advertise auto levels for spin write-back (B5).
                    vmin, vmax = 0.0, 1.0
                    self._last_auto_levels = None
                else:
                    vmin, vmax = window
                    # Store the computed absolute window so the caller can
                    # write it back to the inspector spins (blockSignals),
                    # making auto→manual a seamless no-jump transition.
                    self._last_auto_levels = (vmin, vmax)
                self._last_manual_levels_shifted = None
            else:
                vmin, vmax = float(z_floor), float(z_ceiling)
                if reference_delta is not None:
                    # An already-tuned MANUAL window must track the SAME
                    # shift as the (unclipped) matrix, else the map goes
                    # black/blank when the effective reference changes.
                    vmin, vmax = vmin + reference_delta, vmax + reference_delta
                    self._last_manual_levels_shifted = (vmin, vmax)
                else:
                    self._last_manual_levels_shifted = None
                self._last_auto_levels = None
            cbar = (
                colorbar_label if colorbar_label is not None
                else f"Amplitude{unit} (dB re {db_ref:g})"
            )
        else:
            m = result.amplitude
            if not z_auto:
                vmin, vmax = float(z_floor), float(z_ceiling)
            else:
                bounds = _finite_data_bounds(m)
                if bounds is None:
                    vmin, vmax = 0.0, 1.0
                else:
                    vmin, vmax = bounds
            self._last_manual_levels_shifted = None
            cbar = colorbar_label if colorbar_label is not None else f"Amplitude{unit}"

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
            x_extent=time_axis_display_extent(
                result.times,
                params=result.params,
                metadata=getattr(result, 'metadata', None),
                fallback=(float(result.times[0]), float(result.times[-1])),
            ),
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
            amplitude_label=amplitude_label, z_unit_suffix=z_unit_suffix,
        )
        # plot_or_update_heatmap stores the matrix it was handed (the
        # display matrix) in self._matrix_disp; re-pin it explicitly so
        # the slice and remarks read the same display-space values.
        self._matrix_disp = m
        # Bind the slice axes to the inspector knobs (display-only). The X axis
        # is TIME (panel x_*), the Y axis is FREQUENCY/ORDER (panel freq_range,
        # carried through y_* after the freq_range block above). A None means
        # "auto" → the slice falls back to the live heatmap view range.
        #   slice dir 'y' (curve vs time)      → horizontal axis = time range
        #   slice dir 'x' (curve vs frequency) → horizontal axis = freq range
        # plot_or_update_heatmap reset these to None just above, so set them
        # only when the corresponding axis is manual.
        self._panel_time_range = (
            None if x_auto else (float(x_min), float(x_max)))
        self._panel_freq_range = (
            None if y_auto else (float(y_min), float(y_max)))
        # Amplitude axis: manual z (z_auto=False) clamps the slice's amplitude
        # axis to [z_floor, z_ceiling] — same window as the colorbar. z_auto
        # leaves it None so the slice auto-fits the (freq-range-clipped) data.
        self._panel_amp_range = (
            None if z_auto else (float(z_floor), float(z_ceiling)))
        if self._slice_curve is not None and len(result.times):
            self._seed_slice()
        self.layout_geometry_changed.emit()

    # ------------------------------------------------------------------
    # slice (X / Y direction)
    # ------------------------------------------------------------------
    def _slice_coords(self):
        return self._slice._slice_coords()

    def _seed_slice(self):
        return self._slice._seed_slice()

    def set_slice_direction(self, direction: str) -> None:
        return self._slice.set_slice_direction(direction)

    def select_time_index(self, idx: int) -> None:
        return self._slice.select_time_index(idx)

    def _main_view_range(self, axis: str):
        """Return the main heatmap's current visible range, clamped to data."""
        if self._extents is None:
            return None
        x0, x1, y0, y1 = self._extents
        try:
            x_range, y_range = self._plot.vb.viewRange()
        except Exception:
            x_range, y_range = (x0, x1), (y0, y1)
        if axis == 'y':
            lo, hi = float(y_range[0]), float(y_range[1])
            data_lo, data_hi = float(y0), float(y1)
        else:
            lo, hi = float(x_range[0]), float(x_range[1])
            data_lo, data_hi = float(x0), float(x1)
        if hi < lo:
            lo, hi = hi, lo
        data_lo, data_hi = sorted((data_lo, data_hi))
        lo = max(lo, data_lo)
        hi = min(hi, data_hi)
        if hi < lo:
            mid = min(max((lo + hi) / 2.0, data_lo), data_hi)
            return mid, mid
        return lo, hi

    @staticmethod
    def _slice_visible_mask(coords, lo: float, hi: float):
        return _SliceStrip._slice_visible_mask(coords, lo, hi)

    def _set_slice_x_range(self, lo: float, hi: float, values) -> None:
        return self._slice._set_slice_x_range(lo, hi, values)

    def _slice_axis_range(self, panel_range, view_axis: str, coords):
        return self._slice._slice_axis_range(panel_range, view_axis, coords)

    def _apply_slice_amp_range(self, values) -> None:
        return self._slice._apply_slice_amp_range(values)

    def _fit_slice_y_to_visible_x(self) -> None:
        return self._slice.fit_y_to_visible_x()

    def _apply_slice(self) -> None:
        return self._slice._apply_slice()

    def _on_slice_marker_dragged(self, *_args) -> None:
        return self._slice._on_slice_marker_dragged(*_args)

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
        return self._slice._update_slice_hint(label, value)

    def _select_slice_at(self, x: float, y: float) -> None:
        return self._slice._select_slice_at(x, y)

    def set_slice_button_labels(self, x_label: str, y_label: str) -> None:
        return self._slice.set_slice_button_labels(x_label, y_label)

    def _align_slice_to_main(self) -> None:
        return self._slice._align_slice_to_main()

    def _position_slice_panel(self) -> None:
        return self._slice._position_slice_panel()

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

    def _release_split_right_spacers(self) -> None:
        self._set_slice_right_spacer(None)

    def _release_split_titles(self) -> None:
        self._apply_title_text()

    def reset_split_layout_alignment(self) -> None:
        """Single-pane path, with the slice's own follow-up geometry.

        Overridden rather than inherited for two reasons. The ``_split_aligned``
        flag is heatmap-only -- it tells the ``_after_split_*`` divider hooks
        that the page owns alignment right now, and the line canvas overrides
        none of them. And order matters here: unify the left axes FIRST (that
        shifts each plot's left edge), then pull the slice's RIGHT edge in to
        the heatmap's, then re-place the info panel in the freed column.

        The ``_bottom_collapsed`` guard is deliberately NOT pushed down into
        the mixin: the line canvas unifies unconditionally today, and whether
        that is a bug or simply harmless there is not decidable from the code
        (``pin_left_axes_to_common_width`` folds realized ``width()`` into its
        max, so a collapsed row's stale width may or may not leak). See the
        C3 audit table in docs/analyzer/verify/pg-slice-dedup-anchors.md.
        """
        self._split_aligned = False
        self.prepare_split_layout_alignment(None)
        if not getattr(self, '_bottom_collapsed', False):
            self._unify_stacked_left_axes()
            self._align_slice_to_main()
            self._position_slice_panel()

    def heatmap_layout_metrics(self) -> dict:
        left_widths = []
        for axis in self._alignment_left_axes():
            try:
                # Same max() as the pin: the font-metric term is the only
                # honest one before the axis has been painted, and the realized
                # term keeps an already-sized axis from being narrowed. Reading
                # width() alone would feed the page-level cross-pane max from
                # the very numbers the pin is meant to correct.
                left_widths.append(max(
                    float(left_axis_width_for_ticks(axis)),
                    float(axis.width()),
                ))
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
        self._pin_split_left_axes(left_axis_width)
        self._pin_split_bottom_heights((
            (self._plot, main_bottom_axis_height),
            (self._slice_plot, slice_bottom_axis_height),
        ))
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
        return self._slice._set_slice_right_spacer(width)

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
        """Unit token for annotation values (slice mode).

        dB mode labels the value with the caller-supplied ``z_unit_suffix``
        (spec §15 C2/C3: a reference-aware ``dB[A] re ...`` phrase) when set,
        else the historical bare ``'dB'`` literal (the matrix is already in
        dB); every other mode uses the channel unit.
        """
        if self._z_unit_suffix:
            return self._z_unit_suffix
        if amplitude_mode_is_db(self._amplitude_mode):
            return 'dB'
        return self._result.unit or ''

    def _on_scene_hover(self, scene_pos) -> None:
        """Heatmap passive XYZ hover readout is retired; clear any stale pill."""
        self.cursor_info.emit('')

    # ------------------------------------------------------------------
    # remarks (annotation parity with the matplotlib canvases)
    # ------------------------------------------------------------------
    @staticmethod
    def _axis_label_unit(label: str) -> str:
        text = str(label or "")
        start = text.rfind("(")
        end = text.rfind(")")
        if start >= 0 and end > start:
            return text[start + 1:end].strip()
        return ""

    def _z_unit(self) -> str:
        """Same reference-aware unit token as :meth:`_readout_unit`, used by
        the shared remark point (spec §15 C2/C3: colorbar/slice/readout/
        remark share ONE label context)."""
        if self._z_unit_suffix:
            return self._z_unit_suffix
        if amplitude_mode_is_db(self._amplitude_mode):
            return 'dB'
        result = self._result
        return str(getattr(result, 'unit', '') or '')

    def set_overlay_source(self, source) -> None:
        if isinstance(source, (list, tuple)) and len(source) == 2:
            self._overlay_source = (str(source[0]), str(source[1]))
            return
        self._overlay_source = None

    def set_remark_enabled(self, enabled: bool) -> None:
        self._remark_enabled = bool(enabled)
        # Right-click priority (measured, pg 0.14.0): ViewBox.mouseClickEvent
        # raises the context menu BEFORE GraphicsScene emits sigMouseClicked
        # (GraphicsScene.sendClickEvent emits at the end), so ev.accept() in
        # _on_scene_click cannot stop the popup. mouseClickEvent is gated on
        # menuEnabled(), so disable the menu while annotating — right-click
        # then reaches _on_scene_click un-consumed and deletes the nearest
        # remark, mirroring the mpl tooltip contract (chart_stack.py:1263).
        self._remark_interaction.set_enabled(
            self._remark_enabled,
            viewport=self._glw.viewport(),
            menu_viewboxes=(self._plot.vb,),
        )

    def clear_remarks(self) -> None:
        self._remark_intent.clear()
        if not self._remarks:
            return
        self._drop_remark_projection()
        self._bump_markup_revision()

    def _drop_remark_projection(self) -> None:
        if not self._remarks:
            return
        self._remark_artist.clear(self._remarks)

    def _project_remarks(self) -> None:
        self._drop_remark_projection()
        for item in list(self._remark_intent.items):
            self._restore_one_remark(item)

    def snapshot_remarks(self):
        return self._remark_intent.snapshot(self._remarks)

    def restore_remarks(self, payload) -> None:
        self._remark_intent.replace(payload)
        self._project_remarks()

    def _restore_one_remark(self, item) -> None:
        if not isinstance(item, dict):
            return
        source = item.get("source")
        if source is not None and self._overlay_source is not None:
            parsed = (str(source[0]), str(source[1])) if (
                isinstance(source, (list, tuple)) and len(source) == 2
            ) else None
            if parsed is not None and parsed != self._overlay_source:
                return
        try:
            x = float(item["x"])
            y = float(item["y"])
        except (KeyError, TypeError, ValueError):
            return
        if self._extents is not None:
            x0, x1, y0, y1 = self._extents
            x = min(max(x, x0), x1)
            y = min(max(y, y0), y1)
        point = self._remark_point_at(
            x, y,
            label_dx=item.get("label_dx"),
            label_dy=item.get("label_dy"),
        )
        if point is None:
            return
        remark = self._remark_artist.add(point)
        remark["panel"] = "heatmap"
        if self._overlay_source is not None:
            remark["source"] = self._overlay_source
        elif source is not None:
            remark["source"] = source
        self._remarks.append(remark)

    def _bump_markup_revision(self) -> None:
        self.markup_revision = int(self.markup_revision) + 1
        self.markup_revision_changed.emit()

    def remark_count(self) -> int:
        return len(self._remarks)

    def _remark_point_at(self, x: float, y: float, *, label_dx=None, label_dy=None):
        if not self._has_result or self._matrix_disp is None:
            return None
        if self._extents is None:
            return None
        x0, x1, y0, y1 = self._extents
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            return None
        rows, cols = self._matrix_disp.shape
        if rows == 0 or cols == 0:
            return None
        t_idx = min(self._time_index_for(x), cols - 1)
        f_idx = min(self._freq_index_for(y), rows - 1)
        xc, yc = self._slice_coords()
        sx = float(xc[t_idx]) if xc is not None and len(xc) > t_idx else float(x)
        sy = float(yc[f_idx]) if yc is not None and len(yc) > f_idx else float(y)
        val = float(self._matrix_disp[f_idx, t_idx])
        return RemarkPoint(
            vb=self._plot.vb,
            x=sx,
            y=sy,
            z=val,
            color="#dc2626",
            unit_x=self._axis_label_unit(self._x_label),
            unit_y=self._axis_label_unit(self._y_label),
            unit_z=self._z_unit(),
            label_dx=label_dx,
            label_dy=label_dy,
        )

    def add_remark_at(self, x: float, y: float) -> None:
        if not self._remark_enabled:
            return
        point = self._remark_point_at(x, y)
        if point is None:
            return
        remark = self._remark_artist.add(point)
        remark["panel"] = "heatmap"
        if self._overlay_source is not None:
            remark["source"] = self._overlay_source
        self._remarks.append(remark)
        self._remark_intent.record(remark, panel="heatmap")
        self._bump_markup_revision()

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
        self._remark_intent.discard(nearest)
        self._remark_artist.remove(nearest)
        self._remarks.remove(nearest)
        self._bump_markup_revision()

    def _viewport_pos_to_scene(self, viewport_pos):
        return viewport_pos_to_scene(self._glw, viewport_pos)

    def _add_remark_at_viewport_pos(self, viewport_pos) -> None:
        scene_pos = self._viewport_pos_to_scene(viewport_pos)
        if scene_pos is None or not self._plot.vb.sceneBoundingRect().contains(scene_pos):
            return
        p = self._plot.vb.mapSceneToView(scene_pos)
        self.add_remark_at(p.x(), p.y())

    def _remove_remark_at_viewport_pos(self, viewport_pos) -> None:
        scene_pos = self._viewport_pos_to_scene(viewport_pos)
        if scene_pos is None or not self._plot.vb.sceneBoundingRect().contains(scene_pos):
            return
        p = self._plot.vb.mapSceneToView(scene_pos)
        if self._extents is None:
            return
        x0, x1, y0, y1 = self._extents
        if not (x0 <= p.x() <= x1 and y0 <= p.y() <= y1):
            return
        self.remove_remark_near(p.x(), p.y())

    def _remark_item_at_viewport_pos(self, viewport_pos):
        return remark_at_viewport_pos(self._remarks, self._glw, viewport_pos)

    def eventFilter(self, obj, event):
        try:
            if obj is self._glw.viewport():
                # Double-click on the colorbar resets the colour window to the
                # render's levels — independent of remark mode. Consumes the
                # event so it does not also fall through to slice/remark clicks.
                if event.type() == QEvent.MouseButtonDblClick:
                    if (self._pos_on_colorbar(event.pos())
                            and self.reset_colorbar_levels()):
                        return True
            if obj is self._glw.viewport() and self._remark_enabled:
                if event.type() == QEvent.MouseButtonPress:
                    result = self._remark_interaction.handle_mouse_press(event)
                    if result is not None:
                        return result
                elif event.type() == QEvent.MouseMove:
                    result = self._remark_interaction.handle_mouse_move(event)
                    if result is not None:
                        return result
                elif event.type() == QEvent.MouseButtonRelease:
                    result = self._remark_interaction.handle_mouse_release(event)
                    if result is not None:
                        return result
        except Exception:
            pass
        return super().eventFilter(obj, event)

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
            # cell by argmin-nearest over those axes. This keeps annotation
            # labels and _value_at in agreement on boundary cells, where
            # floor-fraction and argmin-nearest disagree (caliber unification,
            # 裁决 3). Order mode (self._result is None) keeps the
            # floor-fraction mapping below untouched: it has no
            # times/frequencies axis arrays and its remark tests pin the
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
            elif self._slice_curve is not None:
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
    def colorbar_interaction_active(self) -> bool:
        return colorbar_interaction_active(self._cbar)

    def _on_cbar_levels(self, bar) -> None:
        lo, hi = float(bar.levels()[0]), float(bar.levels()[1])
        # ImageItem levels are already owned by ColorBarItem._update_items.
        # Keep the slice amplitude axis on the same window without a replot.
        if hi > lo:
            self._panel_amp_range = (lo, hi)
            apply_amp = getattr(self._slice, '_apply_slice_amp_range', None)
            if callable(apply_amp):
                apply_amp(())
        self.levels_changed.emit(lo, hi)

    # ------------------------------------------------------------------
    def _pos_on_colorbar(self, viewport_pos) -> bool:
        """True if a viewport-space point falls inside the colorbar item."""
        if self._cbar is None:
            return False
        try:
            scene_pos = self._glw.mapToScene(viewport_pos)
            return self._cbar.sceneBoundingRect().contains(scene_pos)
        except Exception:
            return False

    def reset_colorbar_levels(self) -> bool:
        """Restore image + colorbar levels to the last render's window.

        Wired to a double-click on the colorbar. The colour window is
        display-only (the matrix is never clipped to it), so this re-maps
        colour without touching data. Emits ``levels_rebased`` — the
        programmatic-reset signal — NOT ``levels_changed`` (which the
        analysis-page locked-levels linkage treats as a real user drag).
        Also emits ``colorbar_restored(lo, hi)`` so the inspector and any
        locked sibling can take the restored window without a replot.
        Returns True if levels were restored.
        """
        if self._rendered_levels is None or self._cbar is None:
            return False
        lo, hi = self._rendered_levels
        self._img.setLevels((lo, hi))
        self._cbar.blockSignals(True)
        self._cbar.setLevels((lo, hi))
        self._cbar.blockSignals(False)
        if hi > lo:
            self._panel_amp_range = (lo, hi)
            apply_amp = getattr(self._slice, '_apply_slice_amp_range', None)
            if callable(apply_amp):
                apply_amp(())
        self.colorbar_restored.emit(float(lo), float(hi))
        self.levels_rebased.emit()
        return True

    def colorbar_dead(self) -> bool:
        """True if the current colour window leaves the heatmap ~contrast-free."""
        if self._matrix_disp is None:
            return False
        levels = self._img.getLevels()
        if levels is None:
            return False
        return _colorbar_is_dead(
            self._matrix_disp, float(levels[0]), float(levels[1]))

    def nudge_signals(self) -> dict:
        """Situational signals for the footer nudge surface (see hints.py)."""
        return {"colorbar_dead": self.colorbar_dead()}

    # ------------------------------------------------------------------
    def grab_pixmap(self, scale: float = 2.0) -> QPixmap:
        """Snapshot of the canvas for copy/export.

        Consumed by ``chart_stack._grab_pixmap_hidpi`` (chart_stack.py:30)
        as its first-preference branch. Grabs the whole canvas widget (not just
        ``_glw``) so QWidget overlays such as the lower-right slice info panel
        are included in copy/export. Uses ``QWidget.grab()`` + smooth
        magnification rather than ``QWidget.render(QPainter)`` with a scale
        transform: a scaled render() clips to the widget rect in device pixels,
        exporting only the top-left quadrant at 2x (verified offscreen, Qt
        5.15.14). grab() is also the
        realizability probe (lesson
        2026-04-25-tightbbox-survives-offscreen-qt); pattern mirrors
        PgLineCanvas.grab_pixmap (line_canvas.py:209) and
        Renderer.grab_pixmap / _grab_widget_scaled (renderer.py:283).
        Callers must check ``pix.isNull()`` — the degenerate 1x1
        fallback is never scaled up.
        """
        base = self.grab()
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
