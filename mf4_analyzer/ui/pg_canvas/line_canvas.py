"""PgLineCanvas: FFT amplitude overlay plus FFT-source time preview.

The top row draws overlaid FFT amplitude curves after computation. The lower
row shows the time-domain input sources immediately when they are selected,
and remains an overlay when multiple FFT sources are active. NO OpenGL: it
breaks grab_pixmap exports on this project.
"""
from __future__ import annotations

from html import escape
import logging
import math

import numpy as np
from PyQt5.QtCore import QEvent, QPointF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget
import pyqtgraph as pg

from mf4_analyzer.ui._axis_handle import (
    PG_AXIS_NEUTRAL_COLOR,
    PG_AXIS_NEUTRAL_WIDTH,
    PgAxisHandle,
)
from mf4_analyzer.signal.envelope import build_envelope

# Overlay AA point-density budget, shared with TimeDomainCanvasPG (canvas.py:
# 145-146): ON=5000 / OFF=7000 with hysteresis. Imported (not re-defined) so
# the two renderers cannot drift — the time preview's AA must gate on the same
# per-frame drawn-point SUM economics as the main time-domain overlay.
from .canvas import (
    _AA_OVERLAY_SEGMENT_OFF,
    _AA_OVERLAY_SEGMENT_ON,
    _OVERLAY_GRID_ALPHA,
)

from .analysis_axes import (
    _AUTO_CEILING_PCT,
    _AUTO_SPAN_DB,
    _apply_axis_tick_density,
    _apply_neutral_axis_frame,
    _apply_target_bottom_ticks,
    _make_analysis_plot,
    _tick_counts_to_density,
    _visual_padded_bounds,
)
from .context_menu import redesign_pg_context_menu
from .empty_hint import EmptyHintOverlay
from .fonts import _apply_pg_axis_font
from .remarks import (
    RemarkArtist,
    RemarkInteraction,
    RemarkPoint,
    remark_at_viewport_pos,
    viewport_pos_to_scene,
)
from ._shared import show_major_grid_left_bottom_only
from ._split_mixin import (
    _CollapsedRail,
    _SPLIT_ROW_SPACING,
    _SplitDivider,
    _StackedSplitMixin,
)
from .ticks_math import (
    _adjacent_nice_step,
    _fmt_tick,
    _frame_to_nice,
    _nice_per_div,
)
from mf4_analyzer.ui.plot_helpers import _middle_ellipsis
from .viewbox import _ModifierWheelViewBox, _WheelDeltaGraphicsLayoutWidget
from mf4_analyzer.ui_kit.axis_metrics import (
    activate_item_layouts,
    left_axis_width_for_ticks,
)


logger = logging.getLogger(__name__)


_DUAL_CURSOR_DELTA_STYLE = (
    "color:#0b7af3; background-color:#e8f1ff; font-weight:700;"
)


# Fallback envelope bucket count used when the time-preview plot area has no
# realized geometry yet (canvas not shown / mid-build). Generous so a trace
# of up to ~2x this many points still renders untouched (build_envelope's
# small-visible shortcut returns the input when n <= 2*pixel_width); the win
# only matters for multi-million-point sources, which always exceed it.
_PREVIEW_FALLBACK_PIXEL_WIDTH = 2000

# Minimum believable realized plot-area width (px). Below this the
# GraphicsLayout has not been laid out yet (an un-shown / collapsed canvas
# reports ~45 px), so a measured width under the floor is treated as
# unrealized and routed to the generous fallback — otherwise a small source
# would be needlessly decimated against a phantom 46-px viewport.
_PREVIEW_MIN_REALIZED_PIXEL_WIDTH = 200
_SPECTRUM_FALLBACK_PIXEL_WIDTH = 2400
_SPECTRUM_MIN_REALIZED_PIXEL_WIDTH = 200

# Minimum vertical room per Y tick label on the short time-preview strip.
# Inspector Y-density still *requests* up to 20 divisions, but labelling every
# division in ~170 px stacks the text; nicestep itself is fine (e.g. 0.25) —
# the failure mode is uncapped label count, not a broken nice-step picker.
_TIME_PREVIEW_MIN_TICK_LABEL_PX = 16.0
_TIME_EMPHASIS_LW = 1.9
_TIME_DEEMPHASIS_LW = 1.35
_TIME_DEEMPHASIS_ALPHA = 0.42
_TIME_AXIS_LABEL_MAX_CHARS = 14

# Stale-state chrome for the already-computed spectrum when the source
# selection changed but the user has not re-clicked 计算. Deliberately a
# desaturated neutral so it can NEVER be mistaken for a data-series line
# (file palette: blues/greens/reds/oranges/cyans/purples/slate) nor for the
# red remark dot (#dc2626). The marker text is fixed by product copy.
_STALE_MARKER_TEXT = "结果已过期，请重新计算"
_STALE_MARKER_TEXT_COLOR = "#6b7280"      # neutral slate-500, UI chrome
_STALE_MARKER_FILL = (243, 244, 246, 235)  # gray-100 translucent banner
_STALE_MARKER_BORDER = "#9ca3af"          # gray-400 hairline
# Opacity applied to the amp curves while stale (dim, not hidden).
_STALE_CURVE_OPACITY = 0.28

# Default axis titles. Both plots carry titles AT ALL TIMES (incl. the empty
# pre-compute state) so the FFT panel never shows one labelled plot beside one
# bare plot. plot_spectra overrides the amp-left title with the chosen
# amplitude label (Amplitude / dB); everything else falls back to these.
_AMP_LEFT_LABEL = 'Amplitude'
_AMP_BOTTOM_LABEL = 'Frequency (Hz)'
_TIME_LEFT_LABEL = 'Amplitude'
_TIME_BOTTOM_LABEL = 'Time (s)'


class _AxisShim:
    """Minimal axis handle exposing ``view_box`` for ``PgNavigationToolbar``."""

    __slots__ = ("view_box",)

    def __init__(self, view_box):
        self.view_box = view_box


class _HistoryHandle:
    """Lightweight view-history handle for ``PgNavigationToolbar``.

    ``_snapshot_view``/``_restore_view`` (chart_stack) iterate the canvas's
    ``_channel_lines`` and call ``pair[0].get_xlim()/get_ylim()`` to snapshot
    and ``set_xlim()/set_ylim()`` to restore. This shell reads/writes the
    wrapped ViewBox's ``viewRange()``/``setRange`` directly.

    Both amp and time-preview handles restore X and Y: the preview Y is
    user-draggable (and Shift-wheel zoomable), so history must rewind it too.
    """

    __slots__ = ("_vb", "_y")

    def __init__(self, view_box, with_y=True):
        self._vb = view_box
        self._y = bool(with_y)

    def get_xlim(self):
        (lo, hi), _ = self._vb.viewRange()
        return (lo, hi)

    def set_xlim(self, lo, hi):
        self._vb.setXRange(lo, hi, padding=0)

    def get_ylim(self):
        _, (lo, hi) = self._vb.viewRange()
        return (lo, hi)

    def set_ylim(self, lo, hi):
        if self._y:
            self._vb.setYRange(lo, hi, padding=0)


class PgLineCanvas(_StackedSplitMixin, QWidget):
    cursor_info = pyqtSignal(str)
    dual_cursor_info = pyqtSignal(str)
    context_menu_requested = pyqtSignal()
    layout_geometry_changed = pyqtSignal()
    time_preview_range_changed = pyqtSignal(float, float)
    manual_zoom_changed = pyqtSignal(bool)
    # Hidden-gesture discovery: emitted when the user clicks a spectrum curve to
    # pick the time-preview source. The chart card retires the "click a curve to
    # choose the source" tip once this fires.
    time_source_selected = pyqtSignal()
    # AA status traffic-light (mirrors TimeDomainCanvasPG). _ChartCard wires
    # this signal + quality_status() into the bottom-right quality dot, so the
    # FFT card shows the same red/yellow/green antialiasing indicator the
    # time-domain card does.
    quality_status_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._glw = _WheelDeltaGraphicsLayoutWidget(self, owner_canvas=self)
        self._glw.setBackground("#ffffff")
        self._glw.ci.setContentsMargins(2, 2, 2, 2)
        self._glw.ci.setSpacing(2)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._glw)

        self._plot_amp = _make_analysis_plot(
            self._glw, 0, 0, _ModifierWheelViewBox(owner_canvas=self))
        self._plot_time = _make_analysis_plot(
            self._glw, 1, 0, _ModifierWheelViewBox(owner_canvas=self))
        for p in (self._plot_amp, self._plot_time):
            _apply_neutral_axis_frame(p)
            show_major_grid_left_bottom_only(p, alpha=0.25)
            for _ax in ('left', 'bottom', 'top', 'right'):
                try:
                    p.getAxis(_ax).setStyle(maxTickLevel=0)
                except Exception:
                    pass
        # Time-preview mirrors TimeDomain overlay: native left-axis Y grid is
        # OFF because each overlay curve has its own Y scale — a shared
        # fractional graticule (_build_time_y_grid) is the only horizontal
        # anchor. Keeping both native + custom grids stacks lines and desyncs
        # labels after a Y pan (lesson: overlay_graticule_wheel_contract).
        show_major_grid_left_bottom_only(self._plot_time, x=True, y=False, alpha=0.25)
        self._plot_amp.addLegend(offset=(8, 8))
        # Open up the gap between the two stacked plots so the draggable divider
        # line sits in clear whitespace instead of merging with the plot frames.
        try:
            self._glw.ci.layout.setVerticalSpacing(_SPLIT_ROW_SPACING)
        except Exception:
            pass
        # Bottom (time-preview) plot height when expanded. Stateful so the
        # divider drag can resize it and fold/restore can remember the size.
        self._bottom_split_default = 170.0
        self._bottom_split_h = self._bottom_split_default
        self._drag_start_bottom_h = self._bottom_split_h
        self._plot_time.setMaximumHeight(int(self._bottom_split_h))
        self._apply_default_axis_labels()

        self.axes_list = [
            _AxisShim(self._plot_amp.vb),
            _AxisShim(self._plot_time.vb),
        ]

        self._amp_curves = []
        self._time_curves = []
        self._cursor_lines = self._make_frequency_cursor_lines("#64748b")
        self._cursor_a_lines = self._make_frequency_cursor_lines("#1769e0")
        self._cursor_b_lines = self._make_frequency_cursor_lines("#d97706")
        self._cursor_mode = "off"
        self._cursor_a_frequency = None
        self._cursor_b_frequency = None
        self._next_dual_cursor = "a"
        # Multi-Y overlay for the time preview: when >1 source is overlaid each
        # extra curve gets its own auto-scaled aux ViewBox + a colour-coded
        # right axis (mirrors TimeDomainCanvasPG overlay). The first curve stays
        # on _plot_time's own left axis.
        self._time_overlay_vbs = []
        self._time_overlay_axes = []
        # Shared horizontal grid for the time-preview overlay. Each aux right
        # axis lives in its own ViewBox with its own Y range, so the built-in
        # left-axis Y grid alone cannot be a common visual anchor (and it is
        # cleared whenever a refresh path pushes plain density onto the left
        # axis). A dedicated grid ViewBox locked to Y=[0,1] and X-linked to the
        # main vb draws n-1 InfiniteLines at i/n — the single graticule every
        # axis's k/n ticks must coincide with (mirrors TimeDomainCanvasPG's
        # _build_overlay_y_grid). Created lazily on first frame.
        self._time_grid_vb = None
        self._time_grid_lines = []
        # Time-preview Y graticule division count (mirrors the time-domain
        # overlay's divisions). Driven by the Y tick density; the left axis and
        # every aux right axis are framed to this many equal nice divisions so
        # all their ticks land on the SAME set of horizontal grid lines.
        # Default 10 matches the standard global Y tick count.
        self._time_divisions = 10
        # Set when the user pans/zooms the time preview; cleared after idle
        # repin so tick labels realign to the shared graticule (overlay snap).
        self._time_y_needs_repin = False
        self._entries = []
        self._selected_time_entry_idx = None
        self._remarks = []
        self._remark_enabled = False
        self._remark_artist = RemarkArtist()
        self._remark_interaction = RemarkInteraction(
            add_at_viewport_pos=lambda pos: self._add_remark_at_viewport_pos(pos),
            remove_at_viewport_pos=lambda pos: self._remove_remark_at_viewport_pos(pos),
            remark_at_viewport_pos=lambda pos: self._remark_item_at_viewport_pos(pos),
        )
        self._last_xlim = None
        self._last_yrange = None
        self._mouse_mode_controller = None
        self._copy_image_handler = None
        # Replot callbacks: the card registers the toolbar's
        # apply_current_mouse_mode + rebind_history_capture here (chart_stack
        # gates registration on register_replot_callback being present), and
        # they fire at the end of every plot_spectra/plot_time_preview/full_reset
        # so the view-history capture re-binds to the live ViewBoxes and seeds a
        # baseline after each rebuild (Task C).
        self._replot_callbacks = []
        self._raw_amp_title = ''
        self._raw_time_title = ''
        self._split_title_width = None
        self._spectrum_stale = False
        self._stale_banner = None
        self._empty_hint_text = ''
        self._empty_hint_item = None
        # The overlay owns the behaviour; the two attributes above stay the
        # public read surface (main_window and several tests read them).
        self._empty_hint = EmptyHintOverlay(
            viewbox_getter=lambda: self._plot_amp.vb,
            reposition_slot=self._reposition_empty_hint,
            on_state=self._store_empty_hint_state,
        )
        self._bottom_tick_target = None
        self._bottom_tick_density = None

        # Interactive curve-AA policy (mirrors the time-domain canvas): drop
        # antialiasing while the user pans/zooms so each frame is a cheap
        # non-AA raster, then restore crisp AA after a short hands-off idle.
        self._aa_on = True
        # Time-preview AA density-budget hysteresis (mirrors QualityManager's
        # density_seeded/density_allowed for the overlay branch). Re-seeded
        # against the OFF budget whenever the curve set is rebuilt; thereafter
        # metric<=ON→on, metric>OFF→off, dead band holds last.
        self._time_aa_density_allowed = False
        self._time_aa_density_seeded = False
        self._last_quality_status = None
        self._aa_idle_timer = QTimer(self)
        self._aa_idle_timer.setSingleShot(True)
        self._aa_idle_timer.setInterval(150)
        self._aa_idle_timer.timeout.connect(self._enable_idle_quality)
        for _p in (self._plot_amp, self._plot_time):
            # Pan / box-zoom / plain wheel emit sigRangeChangedManually (a
            # programmatic setRange, e.g. plot_spectra, does NOT — so a fresh
            # plot stays crisp). The custom ctrl/shift wheel zoom is hooked
            # separately in _handle_wheel_dispatch.
            _p.vb.sigRangeChangedManually.connect(
                lambda *_args, _plot=_p: self._on_interactive_range_changed(
                    _plot))

        self._glw.scene().sigMouseMoved.connect(self._on_hover)
        self._glw.scene().sigMouseClicked.connect(self._on_click)
        try:
            viewport = self._glw.viewport()
            if viewport is not None:
                viewport.setMouseTracking(True)
                viewport.installEventFilter(self)
        except Exception:
            pass
        # Keep the overlay aux ViewBoxes glued to the time plot's main ViewBox
        # (geometry on resize, X range on pan/zoom) so the extra Y axes track.
        self._plot_time.vb.sigResized.connect(self._sync_time_overlay_vbs)
        self._plot_time.vb.sigXRangeChanged.connect(self._sync_time_overlay_vbs)
        for _p in (self._plot_amp, self._plot_time):
            _p.vb.sigXRangeChanged.connect(self._refresh_bottom_x_ticks)
            _p.vb.sigResized.connect(self._refresh_bottom_x_ticks)

        # Draggable split divider (resize) + drawer-style collapsed rail.
        # Drag the divider near the bottom to collapse the time preview; click
        # the rail's ▴ to bring it back. (Replaces the old gutter triangle.)
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
        self._plot_amp.vb.sigResized.connect(self._position_collapse_ctrl)

        # Preview pan/zoom emits `_emit_time_preview_range` (via
        # sigRangeChangedManually) so the inspector start/end spinboxes track
        # the visible X as a draft. The analysis window is gated by the
        # shared「使用选定时间范围」checkbox (manual, same as Time-Domain) —
        # zoom alone does not arm it. There is no separate left-drag region
        # selector anymore — it collided with pan.

        # View-history contract for PgNavigationToolbar (Task C). The toolbar's
        # _snapshot_view/_restore_view walk this map and call pair[0]'s
        # get/set_xlim/ylim. Both rows restore X and Y: the time preview is
        # user-draggable on Y (and Shift-wheel zoomable). The two PlotItems are
        # fixed (never rebuilt), so these handles are built once here.
        self._channel_lines = {
            '__amp__': (_HistoryHandle(self._plot_amp.vb, with_y=True), None),
            '__time__': (_HistoryHandle(self._plot_time.vb, with_y=True), None),
        }

    # ------------------------------------------------------------------
    # Interactive vs idle curve antialiasing
    # ------------------------------------------------------------------
    # FFT curves are few but can be dense (nfft/2 bins × overlaid sources), and
    # overlaying multiple antialiased curves is CPU-raster bound (project
    # lesson: TimeDomain 卡顿=CPU 光栅, 随 overlay 通道数超线性). Re-rasterizing
    # AA on every drag frame is the dominant pan/zoom cost, so AA is dropped for
    # the interactive path and restored once the view settles.
    def _interactive_curves(self):
        return [*self._amp_curves, *self._time_curves]

    @staticmethod
    def _set_curve_aa(curve, on):
        on = bool(on)
        try:
            curve.opts["antialias"] = on
        except Exception:
            pass
        # pyqtgraph 0.14: PlotDataItem 的 antialias 只在 updateItems() 经
        # curve.setData(...) 流到子 PlotCurveItem；FFT 预览平移不重新 setData，
        # 故直接落到被渲染的子 curve 并触发重绘（不重新 setData，便宜）。
        child = getattr(curve, "curve", None)
        if child is not None:
            try:
                child.opts["antialias"] = on
                child.update()
            except Exception:
                pass

    def _time_preview_aa_allowed(self) -> bool:
        """Hysteresis AA gate for the time preview, keyed to drawn-point SUM.

        Replaces the old ``len(entries) <= 1`` one-cut kill: the overlaid
        time traces share one full-plot raster region (like TimeDomainCanvasPG
        overlay), so AA cost is linear in the SUM of points across all
        ``_time_curves``. Gate on the same ON=5000 / OFF=7000 budget with
        hysteresis: an empty/single curve set is always AA-on; otherwise seed
        against OFF, then metric<=ON→on, metric>OFF→off, dead band holds. The
        result is cached on ``_time_aa_density_allowed`` and reused as the
        conservative fallback if ``getData()`` is unavailable / raises."""
        curves = list(self._time_curves)
        if len(curves) <= 1:
            # A single trace (or none) is one cheap region — always crisp.
            self._time_aa_density_allowed = True
            return True
        try:
            total = 0
            for c in curves:
                xd, _yd = c.getData()
                total += 0 if xd is None else len(xd)
        except Exception:
            # Defensive: keep the last settled allowance rather than crash.
            return bool(self._time_aa_density_allowed)
        if not self._time_aa_density_seeded:
            self._time_aa_density_allowed = total <= int(_AA_OVERLAY_SEGMENT_OFF)
            self._time_aa_density_seeded = True
        elif total <= int(_AA_OVERLAY_SEGMENT_ON):
            self._time_aa_density_allowed = True
        elif total > int(_AA_OVERLAY_SEGMENT_OFF):
            self._time_aa_density_allowed = False
        return bool(self._time_aa_density_allowed)

    def _apply_idle_curve_aa(self):
        """Restore each curve's settled-state AA: the amplitude overlay is
        always crisp; the time preview's AA follows the drawn-point density
        budget (``_time_preview_aa_allowed``), so light multi-source overlays
        stay crisp while dense ones drop AA — matching TimeDomainCanvasPG."""
        time_idle_aa = self._time_preview_aa_allowed()
        for c in self._amp_curves:
            self._set_curve_aa(c, True)
        for c in self._time_curves:
            self._set_curve_aa(c, time_idle_aa)

    def disable_interactive_quality(self):
        """Drop curve AA for the interactive (pan/zoom) path and cancel any
        pending idle upgrade. Also invoked by the ViewBox drag hook
        (``_ModifierWheelViewBox.mouseDragEvent``)."""
        try:
            self._aa_idle_timer.stop()
        except Exception:
            pass
        if not self._aa_on:
            return
        for c in self._interactive_curves():
            self._set_curve_aa(c, False)
        self._aa_on = False
        try:
            self._glw.update()
        except Exception:
            pass
        self._emit_quality_status()

    def schedule_idle_quality(self):
        """Re-arm the idle-AA timer after a settled interaction."""
        try:
            self._aa_idle_timer.start()
        except Exception:
            pass
        self._emit_quality_status()

    def _enable_idle_quality(self):
        """Idle-timer slot: restore crisp AA once the user is hands-off. If a
        mouse button is still down the gesture is ongoing, so re-arm instead."""
        if self._aa_on:
            return
        try:
            if QApplication.mouseButtons() != Qt.NoButton:
                self._aa_idle_timer.start()
                return
        except Exception:
            pass
        if self._time_y_needs_repin:
            self._time_y_needs_repin = False
            try:
                self._snap_time_axes_to_grid()
            except Exception:
                pass
        self._apply_idle_curve_aa()
        self._aa_on = True
        try:
            self._glw.update()
        except Exception:
            pass
        self._emit_quality_status()

    # ------------------------------------------------------------------
    # AA status (reader-facing traffic light) — mirrors QualityManager on the
    # time-domain canvas but scoped to this canvas's own AA hysteresis state.
    # ------------------------------------------------------------------
    def quality_status(self):
        """Return the {state, tooltip} dict consumed by the chart quality dot.

        Judged on the amplitude spectrum curves (the primary FFT trace); the
        time-preview curves gate their AA on a drawn-point density budget
        (light overlays stay crisp, dense ones drop AA), so they are not a
        reliable signal for the green/red readiness state and are excluded.
        """
        judged = self._amp_curves or self._time_curves
        if not judged:
            return {"state": "red", "tooltip": "抗锯齿未激活：无曲线"}

        def _aa(curve):
            try:
                return bool(curve.opts.get("antialias", False))
            except Exception:
                return False

        actual_on = all(_aa(c) for c in judged)
        if self._aa_on and actual_on:
            return {"state": "green", "tooltip": "抗锯齿已完成"}
        try:
            timer_active = self._aa_idle_timer.isActive()
        except Exception:
            timer_active = False
        if timer_active:
            return {"state": "yellow", "tooltip": "抗锯齿等待空闲刷新"}
        return {"state": "red", "tooltip": "抗锯齿未激活"}

    def _emit_quality_status(self):
        """Emit quality_status_changed only when the status actually changes."""
        try:
            status = self.quality_status()
            if status == self._last_quality_status:
                return
            self._last_quality_status = status
            self.quality_status_changed.emit(status)
        except Exception:
            pass

    def _on_interactive_range_changed(self, plot=None, *_args):
        self.disable_interactive_quality()
        self.schedule_idle_quality()
        if plot is self._plot_time:
            self._time_y_needs_repin = True
            self._emit_time_preview_range()
        elif plot is self._plot_amp:
            self.manual_zoom_changed.emit(True)

    def get_time_preview_xlim(self):
        """Return the time-preview ViewBox visible X as ``(lo, hi)`` or None."""
        try:
            (lo, hi), _yr = self._plot_time.vb.viewRange()
            lo = float(lo)
            hi = float(hi)
        except Exception:
            return None
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            return None
        return (lo, hi)

    def _emit_time_preview_range(self) -> bool:
        xlim = self.get_time_preview_xlim()
        if xlim is None:
            return False
        lo, hi = xlim
        self.time_preview_range_changed.emit(lo, hi)
        return True

    def register_mouse_mode_controller(self, controller) -> None:
        self._mouse_mode_controller = controller

    def register_copy_image_handler(self, handler) -> None:
        self._copy_image_handler = handler

    def register_replot_callback(self, cb) -> None:
        """Register a callback fired after every chart rebuild.

        The card registers the toolbar's ``apply_current_mouse_mode`` and
        ``rebind_history_capture`` (chart_stack only does so when this method
        exists), so back/forward history works on the FFT canvas (Task C)."""
        if callable(cb):
            self._replot_callbacks.append(cb)

    def _run_replot_callbacks(self) -> None:
        for cb in list(self._replot_callbacks):
            try:
                cb()
            except Exception:
                logger.debug("replot callback %r failed", cb, exc_info=True)

    def _plot_item_for_view_box(self, view_box):
        if view_box is self._plot_amp.vb:
            return self._plot_amp
        if view_box is self._plot_time.vb or view_box in self._time_overlay_vbs:
            return self._plot_time
        return self._plot_amp

    def _fit_y_to_visible_x(self, plot) -> None:
        """Right-click 「Y 轴自适应」: keep the CURRENT X window fixed and
        autoscale Y to just the curve samples inside it.

        Mirrors ``TimeDomainCanvasPG.fit_y_to_visible_x`` but for the FFT line
        plots. Distinct from ``reset_view_to_data_extents`` (查看全部), which
        restores BOTH axes to the full data extent. Unlike the time-domain hot
        path the line curves hold their full (non-decimated) samples, so we can
        fit directly on ``getData()`` rather than re-slicing a raw signal.
        """
        if plot is self._plot_time:
            curves = self._time_curves
        else:
            plot = self._plot_amp
            curves = self._amp_curves
        try:
            (x0, x1), _ = plot.vb.viewRange()
        except Exception:
            return
        lo, hi = np.inf, -np.inf
        for c in curves:
            try:
                xs, ys = c.getData()
            except Exception:
                continue
            if xs is None or ys is None or len(xs) == 0:
                continue
            xs = np.asarray(xs)
            ys = np.asarray(ys)
            mask = (xs >= x0) & (xs <= x1) & np.isfinite(ys)
            if not np.any(mask):
                continue
            yv = ys[mask]
            lo = min(lo, float(np.min(yv)))
            hi = max(hi, float(np.max(yv)))
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi < lo:
            return
        pad = (hi - lo) * 0.05 if hi > lo else (abs(hi) * 0.05 or 1.0)
        self.disable_interactive_quality()
        plot.setYRange(lo - pad, hi + pad, padding=0)
        # Time preview: repin the *fitted* window onto the shared graticule
        # (TimeDomain overlay contract). Do NOT full-data reframe — that undoes
        # the visible-X fit. Spectrum row has no graticule.
        if plot is self._plot_time:
            self._repin_time_y_to_grid()
        self.schedule_idle_quality()

    def _redesign_context_menu_for_viewbox(self, view_box, menu) -> None:
        plot = self._plot_item_for_view_box(view_box)
        redesign_pg_context_menu(
            menu,
            plot,
            self._mouse_mode_controller,
            view_all_handler=self.reset_view_to_data_extents,
            # Per-viewbox: fit Y on whichever plot (amp / time preview) was
            # right-clicked — matches the time-domain 「Y 轴自适应」 entry.
            y_autofit_handler=lambda: self._fit_y_to_visible_x(plot),
            copy_image_handler=self._copy_image_handler,
            allow_y_grid=True,
            # Plot Options hidden for now in the fft section (per request).
            # Default is already False; set explicitly so the intentional
            # "off for now" reads clearly and is easy to flip back.
            keep_plot_options=False,
            view_box=view_box,
        )
        self._maybe_add_time_preview_left_axis_action(view_box, menu)

    def _maybe_add_time_preview_left_axis_action(self, view_box, menu) -> None:
        """Overlay-style 「设为左轴」 for multi-source time preview.

        TimeDomain's channel-tree action only rewrites the TD overlay primary;
        it does not reorder FFT preview sources. When the user right-clicks a
        non-left preview curve (or its right axis ViewBox), offer the same
        label and promote that entry to the left axis.
        """
        time_vbs = {self._plot_time.vb, *self._time_overlay_vbs}
        if view_box not in time_vbs or len(self._entries) < 2:
            return
        idx = 0
        if view_box is not self._plot_time.vb:
            try:
                idx = 1 + self._time_overlay_vbs.index(view_box)
            except ValueError:
                idx = self._nearest_time_entry_for_menu()
        else:
            idx = self._nearest_time_entry_for_menu()
        if idx is None or idx <= 0 or idx >= len(self._entries):
            return
        from PyQt5.QtWidgets import QAction

        action = QAction("设为左轴", menu)
        action.triggered.connect(lambda *_a, i=idx: self.promote_time_entry_to_left(i))
        try:
            menu.insertAction(menu.actions()[0] if menu.actions() else None, action)
        except Exception:
            menu.addAction(action)

    def _nearest_time_entry_for_menu(self):
        """Best-effort curve index under the last right-click, else selection."""
        scene_pos = getattr(self, "_last_rclick_scene_pos", None)
        if scene_pos is not None:
            try:
                if self._plot_time.vb.sceneBoundingRect().contains(scene_pos):
                    v = self._plot_time.vb.mapSceneToView(scene_pos)
                    idx = self._nearest_time_entry_index(float(v.x()), float(v.y()))
                    if idx is not None:
                        return idx
            except Exception:
                pass
        sel = self._selected_time_entry_idx
        if sel is not None and int(sel) > 0:
            return int(sel)
        return None

    def _nearest_time_entry_index(self, x, y):
        """Nearest overlay curve to ``(x, y)`` in the main time ViewBox."""
        best_i = None
        best_d = None
        for i, (_curve, vb, _plot) in enumerate(self._time_curve_owners()):
            try:
                xs, ys = _curve.getData()
            except Exception:
                continue
            if xs is None or ys is None or len(xs) == 0:
                continue
            xs = np.asarray(xs, dtype=float)
            ys = np.asarray(ys, dtype=float)
            if vb is not self._plot_time.vb:
                # Map aux data Y into the main view's scene, then to main data
                # so distance is screen-comparable.
                try:
                    # Compare in scene pixels via each vb.
                    scene_pts = []
                    for xi, yi in zip(xs[::max(1, len(xs)//200)], ys[::max(1, len(ys)//200)]):
                        if not (np.isfinite(xi) and np.isfinite(yi)):
                            continue
                        sp = vb.mapViewToScene(QPointF(float(xi), float(yi)))
                        mp = self._plot_time.vb.mapSceneToView(sp)
                        scene_pts.append((float(mp.x()), float(mp.y())))
                    if not scene_pts:
                        continue
                    arr = np.asarray(scene_pts, dtype=float)
                    d = float(np.min((arr[:, 0] - x) ** 2 + (arr[:, 1] - y) ** 2))
                except Exception:
                    continue
            else:
                mask = np.isfinite(xs) & np.isfinite(ys)
                if not np.any(mask):
                    continue
                d = float(np.min((xs[mask] - x) ** 2 + (ys[mask] - y) ** 2))
            if best_d is None or d < best_d:
                best_d = d
                best_i = i
        return best_i

    def promote_time_entry_to_left(self, idx: int) -> None:
        """Move ``entries[idx]`` to the left axis (index 0) and rebuild preview."""
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            return
        if idx <= 0 or idx >= len(self._entries):
            return
        entries = list(self._entries)
        entry = entries.pop(idx)
        entries.insert(0, entry)
        self._entries = entries
        try:
            (x0, x1), _ = self._plot_time.vb.viewRange()
        except Exception:
            x0 = x1 = None
        title = "时域预览"
        self._plot_time_preview_entries(entries, selected_idx=0, title=title)
        if x0 is not None and x1 is not None and np.isfinite(x0) and np.isfinite(x1) and x1 > x0:
            try:
                self._plot_time.setXRange(x0, x1, padding=0)
            except Exception:
                pass
        self._selected_time_entry_idx = 0
        self.time_source_selected.emit()
        self.layout_geometry_changed.emit()

    def _handle_wheel_dispatch(self, *, delta, modifiers, x_pos, y_pos,
                               view_box=None, scene_pos=None, axis=None):
        """Wheel contract aligned with TimeDomain overlay + analysis footer.

        * Ctrl → X zoom (any plot)
        * Time preview, no Ctrl:
          - plain wheel → Y pan by one division (overlay sign)
          - Shift → nice-step Y zoom
          - ``axis == 1`` (Y gutter) → only that ViewBox; else all time VBs
        * Spectrum row: Shift → Y zoom; plain wheel consumed (no native zoom)
        """
        step = 1 if delta > 0 else -1 if delta < 0 else 0
        if step == 0 or view_box is None:
            return False
        ctrl = bool(modifiers & Qt.ControlModifier)
        shift = bool(modifiers & Qt.ShiftModifier)
        time_vbs = [self._plot_time.vb, *self._time_overlay_vbs]
        on_time = view_box in time_vbs and bool(self._time_curves)

        if not ctrl and not on_time and not shift:
            return True  # spectrum plain wheel: consume, no zoom

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
                if on_time:
                    self._emit_time_preview_range()
                elif view_box is self._plot_amp.vb:
                    self.manual_zoom_changed.emit(True)
            elif on_time:
                pairs = self._time_axis_pairs()
                if axis == 1:
                    targets = [(vb, ax) for vb, ax in pairs if vb is view_box]
                    if not targets:
                        targets = pairs
                else:
                    targets = pairs
                n = self._effective_time_divisions()
                lo, hi = y_range
                span = hi - lo
                if not (np.isfinite(span) and span > 0):
                    return True
                if np.isfinite(y_pos):
                    cursor_fraction = (float(y_pos) - lo) / span
                    cursor_fraction = max(0.0, min(1.0, cursor_fraction))
                else:
                    cursor_fraction = 0.5
                for target_vb, target_axis in targets:
                    try:
                        target_lo, target_hi = target_vb.viewRange()[1]
                        target_span = target_hi - target_lo
                        if not (np.isfinite(target_span) and target_span > 0):
                            continue
                        current_per_div = target_span / n
                        if shift:
                            next_per_div = _adjacent_nice_step(
                                current_per_div, -1 if step > 0 else 1
                            )
                            if next_per_div is None:
                                next_per_div = current_per_div * factor
                            anchor = target_lo + cursor_fraction * target_span
                            next_span = n * next_per_div
                            raw_bottom = anchor - cursor_fraction * next_span
                            bottom = round(raw_bottom / next_per_div) * next_per_div
                            top = bottom + next_span
                            tick_per_div = next_per_div
                        else:
                            # Plain-wheel vertical pan (Windows-traditional sign).
                            bottom = target_lo - step * current_per_div
                            top = target_hi - step * current_per_div
                            tick_per_div = current_per_div
                        ticks = [
                            bottom + k * tick_per_div for k in range(n + 1)
                        ]
                        target_vb.enableAutoRange(axis='y', enable=False)
                        target_vb.setYRange(bottom, top, padding=0)
                        target_axis.setStyle(maxTickLevel=0)
                        target_axis.setTickDensity(1.0)
                        target_axis.setTicks([[
                            (value, _fmt_tick(value, tick_per_div))
                            for value in ticks
                        ], []])
                    except Exception:
                        continue
                self._build_time_y_grid(n)
            elif shift:
                lo, hi = y_range
                center = float(y_pos) if np.isfinite(y_pos) else (lo + hi) / 2.0
                view_box.setYRange(
                    center - (center - lo) * factor,
                    center + (hi - center) * factor,
                    padding=0,
                )
                if view_box is self._plot_amp.vb:
                    self.manual_zoom_changed.emit(True)
            else:
                return True
        except Exception:
            return False
        self.disable_interactive_quality()
        self.schedule_idle_quality()
        self.layout_geometry_changed.emit()
        return True

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

    # ------------------------------------------------------------------
    def plot_spectra(self, entries, *, xlim, amp_label, title,
                     y_auto=True, y_min=0.0, y_max=0.0):
        """Plot FFT curves and show all source time traces below."""
        self.clear_empty_hint()
        self._clear_frequency_cursor_readout()
        for p, curves in ((self._plot_amp, self._amp_curves),
                          (self._plot_time, self._time_curves)):
            for c in curves:
                p.removeItem(c)
            curves.clear()
        self.clear_remarks()
        # A fresh compute supersedes any stale marker; restore the NORMAL
        # visual state (full-opacity curves rebuilt below + marker removed).
        self._clear_spectrum_stale()
        self._entries = list(entries)

        for e in self._entries:
            pen = pg.mkPen(e.get('color', '#2563eb'), width=1.5)
            pen.setJoinStyle(Qt.RoundJoin)
            pen.setCapStyle(Qt.RoundCap)
            freq, amp = self._spectrum_plot_arrays(e['freq'], e['amp'])
            # dB-reference-defaults Task 6 (spec §15 C1): a mixed-reference
            # FFT overlay attaches a per-curve 'legend_label' (base label +
            # a compact 'dB[A] re ...' disclosure) distinct from the base
            # 'label' -- fall back to 'label' for entries that never went
            # through the per-entry resolver (single/exact-reference axis,
            # or a legacy hand-built entry).
            curve = self._plot_amp.plot(
                freq, amp, pen=pen, name=e.get('legend_label', e['label']),
                antialias=True)
            curve.setOpacity(1.0)
            self._amp_curves.append(curve)

        self._raw_amp_title = title or ''
        self._apply_title_texts()
        self._plot_amp.setLabel('left', amp_label)
        self._plot_amp.setLabel('bottom', 'Frequency (Hz)')
        self._last_xlim = (float(xlim[0]), float(xlim[1]))
        manual_y = (not y_auto) and y_max > y_min
        self._last_yrange = (float(y_min), float(y_max)) if manual_y else None

        self._plot_amp.setXRange(float(xlim[0]), float(xlim[1]), padding=0)
        if manual_y:
            self._plot_amp.setYRange(float(y_min), float(y_max), padding=0)
        elif self._is_db_amp_label(amp_label):
            yrange = self._auto_db_y_range(self._entries, xlim)
            if yrange is not None:
                self._plot_amp.setYRange(yrange[0], yrange[1], padding=0)
            else:
                self._plot_amp.enableAutoRange(axis='y')
        else:
            self._plot_amp.enableAutoRange(axis='y')
        self.manual_zoom_changed.emit(False)

        self._plot_time_preview_entries(
            self._entries, selected_idx=0 if self._entries else None,
            title="时域预览",
        )
        # Fresh curves are rebuilt AA-on; surface the resulting (green) state
        # on the quality dot immediately.
        self._emit_quality_status()
        # Re-bind history capture + re-apply mouse mode on the rebuilt view
        # (Task C: lets the toolbar's back/forward seed a baseline).
        self._run_replot_callbacks()

    def plot_time_preview(self, entries, *, title="时域预览",
                          clear_spectrum=True) -> None:
        """Show selected FFT input sources before spectrum computation.

        ``clear_spectrum=True`` (genuine reset: mode entry / file close) wipes
        the upper amplitude row. ``clear_spectrum=False`` (selection change on
        an already-computed spectrum) KEEPS the amplitude curves visible but
        DIMS them and overlays a "结果已过期" marker, while the lower time row
        still updates live to the new selection. The next ``plot_spectra``
        restores the normal visual state."""
        self.clear_empty_hint()
        if clear_spectrum:
            for c in self._amp_curves:
                self._plot_amp.removeItem(c)
            self._amp_curves.clear()
            self.clear_remarks()
            self._clear_spectrum_stale()
            self._entries = []
            self._selected_time_entry_idx = None
            self._last_xlim = None
            self._last_yrange = None
            self._raw_amp_title = ''
            self._apply_title_texts()
            # Keep the amp plot labelled (default titles) so it never goes bare
            # while the time-preview row below stays labelled.
            self._plot_amp.setLabel('left', _AMP_LEFT_LABEL)
            self._plot_amp.setLabel('bottom', _AMP_BOTTOM_LABEL)
        elif self._amp_curves:
            # Keep the computed spectrum but flag it stale. Nothing to flag
            # when no spectrum exists yet (behaves like a plain preview).
            self.mark_spectrum_stale()
        self._plot_time_preview_entries(list(entries or []), title=title)
        # Task C: re-bind history capture + re-apply mouse mode after rebuild.
        self._run_replot_callbacks()

    # ------------------------------------------------------------------
    # stale spectrum state (selection changed, awaiting re-compute)
    # ------------------------------------------------------------------
    def mark_spectrum_stale(self) -> None:
        """Dim the computed amplitude curves and show the over-stale marker.

        Idempotent and a no-op when there is no computed spectrum."""
        if not self._amp_curves:
            return
        self._spectrum_stale = True
        for c in self._amp_curves:
            try:
                c.setOpacity(_STALE_CURVE_OPACITY)
            except Exception:
                pass
        self._show_stale_banner()

    def _clear_spectrum_stale(self) -> None:
        """Restore full-opacity curves and remove the stale marker."""
        self._spectrum_stale = False
        for c in self._amp_curves:
            try:
                c.setOpacity(1.0)
            except Exception:
                pass
        self._remove_stale_banner()

    def is_spectrum_stale(self) -> bool:
        return bool(self._spectrum_stale)

    def _show_stale_banner(self) -> None:
        if self._stale_banner is None:
            # pg.TextItem already renders at a constant on-screen size
            # (it does not scale with the view transform), so only its
            # data-space POSITION must be re-pinned on range/resize changes.
            banner = pg.TextItem(
                _STALE_MARKER_TEXT,
                color=_STALE_MARKER_TEXT_COLOR,
                fill=pg.mkBrush(*_STALE_MARKER_FILL),
                border=pg.mkPen(_STALE_MARKER_BORDER, width=1),
                anchor=(0.5, 0.0),
            )
            banner.setZValue(1000)
            self._stale_banner = banner
        if self._stale_banner.scene() is None:
            self._plot_amp.vb.addItem(self._stale_banner, ignoreBounds=True)
        self._stale_banner.setVisible(True)
        # Keep the banner pinned to the top-center of the ViewBox through
        # resize AND pan/zoom (range changes remap scene→view coords).
        # Disconnect-before-connect avoids stacking duplicate handlers when
        # mark_spectrum_stale is called repeatedly across selection changes.
        for sig in (self._plot_amp.vb.sigResized,
                    self._plot_amp.vb.sigRangeChanged):
            try:
                sig.disconnect(self._reposition_stale_banner)
            except (TypeError, RuntimeError):
                pass
            try:
                sig.connect(self._reposition_stale_banner)
            except Exception:
                pass
        self._reposition_stale_banner()

    def _reposition_stale_banner(self, *_args) -> None:
        if self._stale_banner is None or not self._spectrum_stale:
            return
        try:
            rect = self._plot_amp.vb.sceneBoundingRect()
            top_center_scene = QPointF(rect.center().x(), rect.top() + 8.0)
            self._stale_banner.setPos(
                self._plot_amp.vb.mapSceneToView(top_center_scene))
        except Exception:
            pass

    def _remove_stale_banner(self) -> None:
        if self._stale_banner is None:
            return
        for sig in (self._plot_amp.vb.sigResized,
                    self._plot_amp.vb.sigRangeChanged):
            try:
                sig.disconnect(self._reposition_stale_banner)
            except (TypeError, RuntimeError):
                pass
        try:
            self._plot_amp.vb.removeItem(self._stale_banner)
        except Exception:
            pass
        self._stale_banner = None

    def reset_view_to_data_extents(self) -> None:
        if self._last_xlim is None:
            self._reset_time_preview_to_extents()
            self.manual_zoom_changed.emit(False)
            return
        x0, x1 = _visual_padded_bounds(self._last_xlim[0], self._last_xlim[1])
        self._plot_amp.setXRange(x0, x1, padding=0)
        if self._last_yrange is not None:
            y0, y1 = _visual_padded_bounds(self._last_yrange[0], self._last_yrange[1])
            self._plot_amp.setYRange(
                y0, y1, padding=0)
        else:
            self._plot_amp.enableAutoRange(axis='y')
        self.select_time_entry(self._selected_time_entry_idx)
        bounds = self._combined_time_bounds()
        if bounds is not None:
            tx0, tx1 = _visual_padded_bounds(bounds[0], bounds[1])
            self._plot_time.setXRange(tx0, tx1, padding=0)
        # Re-frame Y to the shared graticule after the X reset so the left +
        # aux right axes stay aligned on the same horizontal grid lines.
        self._reframe_time_y_to_grid()
        self.manual_zoom_changed.emit(False)

    def _reset_time_preview_to_extents(self) -> None:
        bounds = self._combined_time_bounds()
        if bounds is None:
            return
        tx0, tx1 = _visual_padded_bounds(bounds[0], bounds[1])
        self._plot_time.setXRange(tx0, tx1, padding=0)
        # Re-frame Y to the shared graticule (was per-axis autoRange).
        self._reframe_time_y_to_grid()

    def full_reset(self) -> None:
        self.clear_empty_hint()
        self._clear_frequency_cursor_readout()
        for p, curves in ((self._plot_amp, self._amp_curves),
                          (self._plot_time, self._time_curves)):
            for c in curves:
                try:
                    p.removeItem(c)
                except Exception:
                    pass
            curves.clear()
        # Aux overlay curves live in their own ViewBoxes, not in _plot_time —
        # tear those down too so no orphan axes/curves linger.
        self._clear_time_overlay_axes()
        self.clear_remarks()
        self._clear_spectrum_stale()
        self._entries = []
        self._selected_time_entry_idx = None
        self._last_xlim = None
        self._last_yrange = None
        self._raw_amp_title = ''
        self._raw_time_title = ''
        self._apply_title_texts()
        # Keep both plots labelled in the empty state (consistency fix).
        self._apply_default_axis_labels()
        # 空状态：显式留白，避免最高刻度网格线贴顶边框（spec R2）。有数据时
        # 后续 plot_*/reset 会重新设范围，这里只管空态观感。
        for p in (self._plot_amp, self._plot_time):
            p.setYRange(0.0, 1.0, padding=0.08)
        self.layout_geometry_changed.emit()
        # Curves are gone → the AA dot must fall back to red ("no curves")
        # instead of showing the previous render's stale green.
        self._emit_quality_status()
        # Task C: re-bind history capture after the reset rebuild.
        self._run_replot_callbacks()

    def _apply_default_axis_labels(self) -> None:
        """Pin both plots' axis titles to their defaults so neither row ever
        renders bare. Called at construction and on full_reset; plot_spectra
        later overrides the amp-left title with the chosen amplitude label."""
        self._plot_amp.setLabel('left', _AMP_LEFT_LABEL)
        self._plot_amp.setLabel('bottom', _AMP_BOTTOM_LABEL)
        self._plot_time.setLabel('left', _TIME_LEFT_LABEL)
        self._plot_time.setLabel('bottom', _TIME_BOTTOM_LABEL)

    # ------------------------------------------------------------------
    # collapse divider (spectrum vs time-preview)
    # ------------------------------------------------------------------
    def _split_top_plot(self):
        return self._plot_amp

    def _split_bottom_plot(self):
        return self._plot_time

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_collapse_ctrl()
        self._refresh_bottom_x_ticks()

    def showEvent(self, event):
        super().showEvent(event)
        self._position_collapse_ctrl()
        self._refresh_bottom_x_ticks()

    def has_result(self) -> bool:
        return bool(self._entries)

    def set_tick_density(self, x, y) -> None:
        try:
            x_n = max(3, int(x))
            y_n = max(3, int(y))
        except (TypeError, ValueError):
            return
        x_d, y_d = _tick_counts_to_density(x_n, y_n)
        self._bottom_tick_target = x_n
        self._bottom_tick_density = x_d
        self._refresh_bottom_x_ticks()
        # Spectrum Y keeps plain density. Time-preview Y drives the shared
        # graticule divisions so the left axis AND every aux right axis re-tick
        # together (fixes "Y tick density had no effect on the right axes").
        _apply_axis_tick_density(self._plot_amp.getAxis('left'), y_d)
        self._time_divisions = max(3, min(20, y_n))
        # Density only changes division count / tick pin — keep the current Y
        # window (TimeDomain overlay: set_tick_density → _repin, not full reframe).
        self._repin_time_y_to_grid()
        self.layout_geometry_changed.emit()

    def open_chart_options_dialog(self, parent=None):
        """Open chart options for the main FFT axis."""
        from mf4_analyzer.ui import _axis_interaction

        handle = PgAxisHandle(self._plot_amp, owner_canvas=self)
        target_parent = parent if parent is not None else self.window()
        return bool(_axis_interaction.edit_chart_options_dialog(
            target_parent, handle))

    def _refresh_bottom_x_ticks(self, *_args) -> None:
        if self._bottom_tick_target is None or self._bottom_tick_density is None:
            return
        # Bottom X axes use TimeDomain-style target-count ticks once the plot
        # geometry is realized; before layout, fall back to native density.
        for plot in (self._plot_amp, self._plot_time):
            bottom = plot.getAxis('bottom')
            if not _apply_target_bottom_ticks(
                bottom, plot.vb, self._bottom_tick_target, self
            ):
                _apply_axis_tick_density(bottom, self._bottom_tick_density)

    # ------------------------------------------------------------------
    def select_time_entry(self, idx) -> None:
        self._plot_time_preview_entries(self._entries, selected_idx=idx,
                                        title="时域预览")
        self._apply_time_preview_emphasis()

    def _apply_time_preview_emphasis(self) -> None:
        """Dim non-selected preview curves (TimeDomain overlay emphasis)."""
        sel = self._selected_time_entry_idx
        for i, curve in enumerate(self._time_curves):
            try:
                pen = curve.opts.get("pen")
                if pen is None:
                    continue
                if sel is None or i == int(sel):
                    pen.setWidthF(_TIME_EMPHASIS_LW if sel is not None else 1.5)
                    curve.setPen(pen)
                    curve.setOpacity(1.0)
                else:
                    pen.setWidthF(_TIME_DEEMPHASIS_LW)
                    curve.setPen(pen)
                    curve.setOpacity(_TIME_DEEMPHASIS_ALPHA)
            except Exception:
                continue

    def promote_time_entry_to_left_by_channel(self, fid, channel) -> bool:
        """Promote preview entry matching ``(fid, channel)`` to the left axis.

        Used when the navigator 「设为左轴」 fires while FFT mode is active.
        Matching is by channel name against entry ``label`` / ``channel`` /
        trailing segment after ``] `` (file-prefixed display names).
        """
        ch = str(channel or "").strip()
        if not ch or len(self._entries) < 2:
            return False
        fid_s = None if fid is None else str(fid)

        def _matches(entry) -> bool:
            if fid_s is not None:
                ef = entry.get("file_id", entry.get("fid", entry.get("data_id")))
                if ef is not None and str(ef) != fid_s:
                    return False
            for key in ("channel", "name", "label"):
                val = entry.get(key)
                if val is None:
                    continue
                text = str(val)
                if text == ch or text.endswith(ch) or text.endswith(f"] {ch}"):
                    return True
                if "]" in text and text.rsplit("]", 1)[-1].strip() == ch:
                    return True
            return False

        for i, entry in enumerate(self._entries):
            if i > 0 and _matches(entry):
                self.promote_time_entry_to_left(i)
                return True
        return False

    # ------------------------------------------------------------------
    # Time-preview multi-Y overlay (one colour-coded right axis per extra curve)
    # ------------------------------------------------------------------
    def _clear_time_overlay_axes(self) -> None:
        """Tear down every aux overlay ViewBox + right axis on the time plot."""
        for vb in self._time_overlay_vbs:
            try:
                vb.clear()
            except Exception:
                pass
            try:
                sc = vb.scene()
                if sc is not None:
                    sc.removeItem(vb)
            except Exception:
                pass
        for ax in self._time_overlay_axes:
            try:
                self._plot_time.layout.removeItem(ax)
            except Exception:
                pass
            try:
                sc = ax.scene()
                if sc is not None:
                    sc.removeItem(ax)
            except Exception:
                pass
        self._time_overlay_vbs = []
        self._time_overlay_axes = []
        # Also tear down the shared horizontal graticule lines so an empty or
        # rebuilt preview leaves no orphaned InfiniteLines in the scene. The
        # grid ViewBox itself is reused (lazily created once); only its lines
        # are rebuilt per division-count by _build_time_y_grid.
        for line in list(self._time_grid_lines):
            try:
                if self._time_grid_vb is not None:
                    self._time_grid_vb.removeItem(line)
            except Exception:
                pass
        self._time_grid_lines = []

    def _add_time_overlay_axis(self, color, position, *, label=""):
        """Create one aux ViewBox + colour-coded right axis for an overlay
        curve. ``position`` is the 1-based overlay slot (2nd curve → 1, …)."""
        # AxisItem forwards gutter wheel events to its linked ViewBox. Use the
        # modifier-aware subclass so aux gutters share the main preview's
        # synchronized Shift-wheel behavior instead of native single-axis zoom.
        aux_vb = _ModifierWheelViewBox(owner_canvas=self)
        axis = pg.AxisItem('right')
        # Keep auto SI prefix OFF so a large-range right axis never renders
        # '1k'/'1m', which would clash with the left axis's _fmt_tick style
        # (mirrors _add_overlay_axis_handle in overlay_axes.py).
        try:
            axis.enableAutoSIPrefix(False)
        except Exception:
            pass
        _apply_pg_axis_font(axis)
        # Frame line stays neutral; the tick TEXT follows the curve colour so a
        # glance maps each right axis to its trace (no channel-name clutter).
        axis.setPen(pg.mkPen(color=PG_AXIS_NEUTRAL_COLOR, width=PG_AXIS_NEUTRAL_WIDTH))
        axis.setTextPen(pg.mkPen(color=color))
        text = _middle_ellipsis(str(label or "").strip(), max_chars=_TIME_AXIS_LABEL_MAX_CHARS)
        if text:
            try:
                axis.setLabel(text)
            except Exception:
                pass
        self._plot_time.layout.addItem(axis, 2, 2 + position)
        self._plot_time.layout.setHorizontalSpacing(8)
        self._plot_time.scene().addItem(aux_vb)
        axis.linkToView(aux_vb)
        aux_vb.setXLink(self._plot_time.vb)
        # Y-only on the aux ViewBox so the colour-coded RIGHT axis gutter can
        # pan/zoom that channel (TimeDomain overlay: gutter owns per-channel Y;
        # plot body stays on the main vb). X stays linked / non-interactive.
        aux_vb.setMouseEnabled(x=False, y=True)
        aux_vb.setZValue(-10000)
        aux_vb.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
        try:
            aux_vb.sigRangeChangedManually.connect(
                lambda *_args: self._on_interactive_range_changed(
                    self._plot_time))
        except Exception:
            pass
        self._time_overlay_vbs.append(aux_vb)
        self._time_overlay_axes.append(axis)
        return aux_vb

    def _ensure_time_grid_vb(self):
        """Lazily create the dedicated grid ViewBox (Y locked to [0,1], X-linked
        to the main time vb) that hosts the shared horizontal graticule lines.

        Sits BELOW every aux ViewBox (z = -20000 vs the aux -10000) so the grid
        lines never paint over the curves, and is read-only/non-interactive —
        it only supplies a common visual anchor while the main preview ViewBox
        remains the pan/zoom surface."""
        if self._time_grid_vb is not None:
            return self._time_grid_vb
        grid_vb = pg.ViewBox()
        try:
            self._plot_time.scene().addItem(grid_vb)
            grid_vb.setXLink(self._plot_time.vb)
            grid_vb.enableAutoRange(axis=pg.ViewBox.YAxis, enable=False)
            grid_vb.setYRange(0.0, 1.0, padding=0)
            grid_vb.setMouseEnabled(x=False, y=False)
            grid_vb.setZValue(-20000)
        except Exception:
            pass
        self._time_grid_vb = grid_vb
        return grid_vb

    def _build_time_y_grid(self, n: int) -> None:
        """(Re)build the n-1 shared horizontal grid lines at i/n (i = 1..n-1).

        Rebuilt whenever the division count changes; old lines are removed from
        the grid ViewBox first so scene items never accumulate across rebuilds
        (mirrors _clear_time_overlay_axes' detach discipline)."""
        grid_vb = self._ensure_time_grid_vb()
        for line in list(self._time_grid_lines):
            try:
                grid_vb.removeItem(line)
            except Exception:
                pass
        self._time_grid_lines = []
        if not self._time_curves:
            return
        alpha_int = max(1, min(255, int(round(_OVERLAY_GRID_ALPHA * 255))))
        pen = pg.mkPen(color=(180, 180, 180, alpha_int), width=1)
        lines = []
        for i in range(1, n):
            line = pg.InfiniteLine(pos=i / n, angle=0, movable=False, pen=pen)
            try:
                grid_vb.addItem(line)
                lines.append(line)
            except Exception:
                pass
        self._time_grid_lines = lines
        self._sync_time_grid_vb()

    def _sync_time_grid_vb(self, *_args) -> None:
        """Glue the grid ViewBox geometry to the main time ViewBox so the shared
        graticule tracks resize/pan exactly like the aux overlay ViewBoxes."""
        if self._time_grid_vb is None:
            return
        try:
            self._time_grid_vb.setGeometry(
                self._plot_time.vb.sceneBoundingRect())
        except Exception:
            pass

    def _effective_time_divisions(self) -> int:
        """Return the graticule division count that still fits the preview height.

        ``_time_divisions`` is the inspector request (3..20). On the short
        time-preview strip, labelling every requested division stacks tick
        text even when ``_frame_to_nice`` picks a clean step — so cap by the
        realized ViewBox height (fallback: current bottom-split height).
        """
        requested = max(3, min(20, int(self._time_divisions)))
        height = 0.0
        try:
            height = float(self._plot_time.vb.sceneBoundingRect().height())
        except Exception:
            height = 0.0
        if height <= 1.0:
            try:
                height = float(self._bottom_split_h or 0.0)
            except Exception:
                height = 0.0
        if height <= 1.0:
            return requested
        max_labels = max(4, int(height // _TIME_PREVIEW_MIN_TICK_LABEL_PX))
        max_divs = max(3, max_labels - 1)
        return max(3, min(requested, max_divs))

    def _time_axis_triples(self):
        """(vb, axis, curve) for main left + every aux right overlay axis."""
        if not self._time_curves:
            return []
        triples = [(self._plot_time.vb,
                    self._plot_time.getAxis('left'),
                    self._time_curves[0])]
        triples.extend(zip(self._time_overlay_vbs,
                           self._time_overlay_axes,
                           self._time_curves[1:]))
        return triples

    def _pin_time_axis_y(self, vb, axis, bottom, top, ticks, per_div) -> None:
        """Write one preview axis to an explicit nice Y window + pinned ticks."""
        try:
            vb.enableAutoRange(axis='y', enable=False)
            vb.setYRange(bottom, top, padding=0)
            try:
                axis.enableAutoSIPrefix(False)
            except Exception:
                pass
            axis.setStyle(maxTickLevel=0)
            axis.setTickDensity(1.0)
            axis.setTicks([[
                (value, _fmt_tick(value, per_div)) for value in ticks
            ], []])
        except Exception:
            pass

    def _enable_time_preview_mouse(self) -> None:
        # Main vb keeps y=True so the LEFT axis gutter can pan/zoom Y (AxisItem
        # forwards with axis=1 and ViewBox still gates on mouseEnabled[y]).
        # Plot-body 2D drags are forced X-only in ``_ModifierWheelViewBox`` —
        # same end state as TimeDomain X-master y=False + per-channel gutters.
        try:
            self._plot_time.vb.setMouseEnabled(x=True, y=True)
        except Exception:
            pass
        for vb in self._time_overlay_vbs:
            try:
                vb.setMouseEnabled(x=False, y=True)
            except Exception:
                pass

    def _time_axis_pairs(self):
        """``(vb, axis)`` for left + every aux right axis."""
        return [
            (self._plot_time.vb, self._plot_time.getAxis('left')),
            *zip(self._time_overlay_vbs, self._time_overlay_axes),
        ]

    def _begin_view_interaction(self) -> None:
        self.disable_interactive_quality()
        baselines = {}
        for vb, _axis in self._time_axis_pairs():
            try:
                baselines[id(vb)] = tuple(vb.viewRange()[1])
            except Exception:
                continue
        self._box_zoom_y_baselines = baselines

    def _end_view_interaction(self) -> None:
        self._time_y_needs_repin = True
        self.schedule_idle_quality()

    def _snap_time_axes_to_grid(self) -> None:
        """Phase-snap every preview Y window onto the current graticule span."""
        n = self._effective_time_divisions()
        triples = self._time_axis_triples()
        if not triples:
            return
        for vb, axis, _curve in triples:
            try:
                lo, hi = vb.viewRange()[1]
                lo, hi = float(lo), float(hi)
            except Exception:
                continue
            span = hi - lo
            if not (math.isfinite(span) and span > 0):
                continue
            per_div = span / n
            if not (math.isfinite(per_div) and per_div > 0):
                continue
            bottom = round(lo / per_div) * per_div
            if abs(bottom) < per_div * 1e-10:
                bottom = 0.0
            top = bottom + span
            ticks = [bottom + k * per_div for k in range(n + 1)]
            self._pin_time_axis_y(vb, axis, bottom, top, ticks, per_div)
        self._build_time_y_grid(n)
        self._enable_time_preview_mouse()

    def _apply_time_preview_box_zoom_y(self) -> None:
        """After RectMode on the time preview, map the box Y fraction onto every channel."""
        baselines = getattr(self, "_box_zoom_y_baselines", None) or {}
        main = self._plot_time.vb
        base = baselines.get(id(main))
        n = self._effective_time_divisions()
        if base is None:
            self._repin_time_y_to_grid()
            return
        try:
            new_lo, new_hi = main.viewRange()[1]
            new_lo, new_hi = float(new_lo), float(new_hi)
        except Exception:
            return
        blo, bhi = float(base[0]), float(base[1])
        bspan = bhi - blo
        if not (math.isfinite(bspan) and bspan > 0):
            return
        f0 = (new_lo - blo) / bspan
        f1 = (new_hi - blo) / bspan
        if abs(f1 - f0) < 1e-6:
            # X-only box — restore main Y to baseline then repin.
            try:
                main.setYRange(blo, bhi, padding=0)
            except Exception:
                pass
            self._repin_time_y_to_grid()
            return
        for vb, axis in self._time_axis_pairs():
            try:
                if vb is main:
                    lo, hi = new_lo, new_hi
                else:
                    clo, chi = baselines.get(id(vb), vb.viewRange()[1])
                    clo, chi = float(clo), float(chi)
                    cspan = chi - clo
                    if not (math.isfinite(cspan) and cspan > 0):
                        continue
                    lo = clo + f0 * cspan
                    hi = clo + f1 * cspan
                bottom, top, ticks = _frame_to_nice(lo, hi, n)
                per_div = (top - bottom) / n
                self._pin_time_axis_y(vb, axis, bottom, top, ticks, per_div)
            except Exception:
                continue
        self._build_time_y_grid(n)
        self._enable_time_preview_mouse()
        self._box_zoom_y_baselines = {}
        self.layout_geometry_changed.emit()

    def _reframe_time_y_to_grid(self) -> None:
        """Frame every time-preview axis from **full curve Y** to ``n`` nice divisions.

        Used for new data / view-all / explicit reset — the TimeDomain analogue
        of fitting to the full signal then pinning the overlay graticule.
        Density changes and Y-adapt must NOT call this; they use
        ``_repin_time_y_to_grid`` so the current window survives.
        """
        n = self._effective_time_divisions()
        triples = self._time_axis_triples()
        if not triples:
            return
        for vb, axis, curve in triples:
            try:
                _xs, ys = curve.getData()
                ys = np.asarray(ys, dtype=float)
                ys = ys[np.isfinite(ys)]
                if ys.size == 0:
                    continue
                lo, hi = float(ys.min()), float(ys.max())
            except Exception:
                continue
            bottom, top, ticks = _frame_to_nice(lo, hi, n)
            per_div = (top - bottom) / n
            self._pin_time_axis_y(vb, axis, bottom, top, ticks, per_div)
        self._build_time_y_grid(n)
        self._enable_time_preview_mouse()

    def _repin_time_y_to_grid(self) -> None:
        """Repin ticks/graticule from each axis's **current** Y range.

        Mirrors ``OverlayAxisManager._repin_overlay_channel_ticks``: keep the
        live window when it already sits on a nice per-division; otherwise
        expand slightly via ``_frame_to_nice`` without rebuilding from full
        curve extents.
        """
        n = self._effective_time_divisions()
        triples = self._time_axis_triples()
        if not triples:
            return
        for vb, axis, _curve in triples:
            try:
                lo, hi = vb.viewRange()[1]
                lo, hi = float(lo), float(hi)
            except Exception:
                continue
            span = hi - lo
            if not (math.isfinite(span) and span > 0):
                continue
            current_per_div = span / n
            nice_per_div = _nice_per_div(current_per_div)
            lower_nice_per_div = (
                _adjacent_nice_step(nice_per_div, -1)
                if nice_per_div is not None
                else None
            )
            if any(
                candidate is not None
                and math.isclose(
                    current_per_div,
                    candidate,
                    rel_tol=1e-9,
                    abs_tol=0.0,
                )
                for candidate in (nice_per_div, lower_nice_per_div)
            ):
                bottom, top, per_div = lo, hi, current_per_div
                ticks = [bottom + k * per_div for k in range(n + 1)]
            else:
                bottom, top, ticks = _frame_to_nice(lo, hi, n)
                per_div = (top - bottom) / n
            self._pin_time_axis_y(vb, axis, bottom, top, ticks, per_div)
        self._build_time_y_grid(n)
        self._enable_time_preview_mouse()

    def _sync_time_overlay_vbs(self, *_args) -> None:
        """Glue every aux ViewBox + the shared grid ViewBox geometry to the time
        plot's main ViewBox so the right axes and graticule track resize/pan."""
        # The grid ViewBox is independent of the aux axes (it exists even for a
        # single source), so sync it unconditionally before the early return.
        self._sync_time_grid_vb()
        if not self._time_overlay_vbs:
            return
        try:
            rect = self._plot_time.vb.sceneBoundingRect()
        except Exception:
            return
        for vb in self._time_overlay_vbs:
            try:
                vb.setGeometry(rect)
            except Exception:
                pass

    def _plot_time_preview_entries(self, entries, selected_idx=None,
                                   title="时域预览") -> None:
        for c in self._time_curves:
            try:
                self._plot_time.removeItem(c)
            except Exception:
                pass
        self._time_curves.clear()
        # New curve set → re-seed the AA density hysteresis against the OFF
        # budget so a fresh overlay is judged on its own drawn-point sum.
        self._time_aa_density_seeded = False
        self._clear_time_overlay_axes()
        entries = list(entries or [])
        if not entries:
            self._selected_time_entry_idx = None
            self._raw_time_title = title or ''
            self._apply_title_texts()
            self._plot_time.setLabel('left', 'Amplitude')
            self._plot_time.setLabel('bottom', 'Time (s)')
            self.layout_geometry_changed.emit()
            return
        if selected_idx is None:
            self._selected_time_entry_idx = None
        else:
            self._selected_time_entry_idx = int(
                np.clip(int(selected_idx), 0, len(entries) - 1))
        if len(entries) > 1:
            self._raw_time_title = f"{title} · {len(entries)} 条曲线"
        else:
            self._raw_time_title = f"{title} - {entries[0].get('label', '')}"
        self._apply_title_texts()
        self._plot_time.setLabel('left', 'Amplitude')
        self._plot_time.setLabel('bottom', 'Time (s)')
        # Overlaying multiple full-resolution antialiased traces is CPU-raster
        # bound (project lesson: TimeDomain 卡顿=CPU 光栅,随 overlay 通道数超
        # 线性). The win comes from cutting points-rasterized × channels, so we
        # (1) decimate each source to a viewport-pixel-width min/max envelope
        # via the same build_envelope used by TimeDomainCanvasPG, and (2) gate
        # antialias on the overlay drawn-point density budget (ON=5000/OFF=7000,
        # imported from canvas.py). The curves are built AA-off provisionally —
        # their real point counts are only known once every curve is appended —
        # then ``_apply_idle_curve_aa`` lands the budgeted AA below.
        pixel_width = self._preview_pixel_width()
        antialias = False
        x_bounds = []
        for i, e in enumerate(entries):
            t = np.asarray(e.get('time', []), dtype=float)
            sig = np.asarray(e.get('signal', []), dtype=float)
            if t.size == 0 or sig.size == 0:
                continue
            n = min(t.size, sig.size)
            t = t[:n]
            sig = sig[:n]
            # Full-range envelope: the preview always shows the whole trace
            # (the view is reset to data extents below), so xlim=None is the
            # correct viewport. build_envelope preserves peaks (min/max per
            # bucket), passes small/single-point traces through untouched, and
            # emits NaN breaks for gaps.
            t_env, sig_env = build_envelope(
                t, sig, xlim=None, pixel_width=pixel_width)
            width = 1.9 if i == self._selected_time_entry_idx else 1.5
            color = e.get('color', '#2563eb')
            pen = pg.mkPen(color, width=width)
            if i == 0:
                # First source keeps the plot's own left axis.
                curve = self._plot_time.plot(t_env, sig_env, pen=pen,
                                             antialias=antialias)
            else:
                # Each extra source gets its own auto-scaled aux ViewBox + a
                # colour-coded right axis so traces with different amplitude
                # ranges are not squashed onto one shared scale.
                aux_vb = self._add_time_overlay_axis(
                    color, i, label=e.get('label', ''))
                curve = pg.PlotDataItem(t_env, sig_env, pen=pen,
                                        antialias=antialias)
                aux_vb.addItem(curve)
            curve._channel_name = e.get('label', '')
            self._time_curves.append(curve)
            x_bounds.append((float(t[0]), float(t[-1])))
        if x_bounds:
            lo = min(a for a, _b in x_bounds)
            hi = max(b for _a, b in x_bounds)
            if hi > lo:
                self._plot_time.setXRange(lo, hi, padding=0)
            else:
                self._plot_time.setXRange(lo - 0.5, hi + 0.5, padding=0)
        # Frame the left + each aux right Y axis to a shared nice graticule so
        # every axis's ticks land on the same horizontal grid lines (replaces
        # per-axis autoRange, which let each right axis pick its own scale).
        self._reframe_time_y_to_grid()
        # Position any aux overlay ViewBoxes now, and again on the next resize
        # (sigResized) once the layout with the new right axes is realized.
        self._sync_time_overlay_vbs()
        self.layout_geometry_changed.emit()
        # Curves were built AA-off provisionally; now that every curve is in
        # _time_curves their real drawn-point sum is known, so land the budgeted
        # AA. Only in the settled (_aa_on) state — a rebuild mid pan/zoom keeps
        # AA off, and the idle timer's _apply_idle_curve_aa lands it on restore.
        if self._aa_on:
            self._apply_idle_curve_aa()
        self._apply_time_preview_emphasis()
        # Time-preview-only updates (source selection before 计算) rebuild the
        # curve set, so refresh the AA dot here too — otherwise it keeps the
        # previous render's state until the next pan/zoom.
        self._emit_quality_status()

    def _preview_pixel_width(self) -> int:
        """Bucket count for the time-preview envelope: the pixel width of the
        time plot's ViewBox (≈ one bucket per pixel, like TimeDomainCanvasPG),
        with a generous fallback when geometry is not yet realized."""
        try:
            rect = self._plot_time.vb.sceneBoundingRect()
            w = int(round(rect.width()))
            if w >= _PREVIEW_MIN_REALIZED_PIXEL_WIDTH:
                return w
        except Exception:
            pass
        return _PREVIEW_FALLBACK_PIXEL_WIDTH

    def _spectrum_pixel_width(self) -> int:
        try:
            rect = self._plot_amp.vb.sceneBoundingRect()
            w = int(round(rect.width()))
            if w >= _SPECTRUM_MIN_REALIZED_PIXEL_WIDTH:
                return w
        except Exception:
            pass
        return _SPECTRUM_FALLBACK_PIXEL_WIDTH

    def _spectrum_plot_arrays(self, freq, amp):
        freq_arr = np.asarray(freq, dtype=float)
        amp_arr = np.asarray(amp, dtype=float)
        n = min(freq_arr.size, amp_arr.size)
        if n == 0:
            return freq_arr[:0], amp_arr[:0]
        freq_arr = freq_arr[:n]
        amp_arr = amp_arr[:n]
        pixel_width = self._spectrum_pixel_width()
        if n <= max(1, pixel_width * 2):
            return freq_arr, amp_arr
        return build_envelope(freq_arr, amp_arr, xlim=None, pixel_width=pixel_width)

    @staticmethod
    def _is_db_amp_label(label: str) -> bool:
        return 'db' in str(label or '').lower()

    @staticmethod
    def _visible_entry_values(entry, xlim):
        freq_arr = np.asarray(entry.get('freq', []), dtype=float)
        amp_arr = np.asarray(entry.get('amp', []), dtype=float)
        n = min(freq_arr.size, amp_arr.size)
        if n == 0:
            return np.asarray([], dtype=float)
        freq_arr = freq_arr[:n]
        amp_arr = amp_arr[:n]
        lo, hi = sorted((float(xlim[0]), float(xlim[1])))
        mask = (
            np.isfinite(freq_arr)
            & np.isfinite(amp_arr)
            & (freq_arr >= lo)
            & (freq_arr <= hi)
        )
        return amp_arr[mask]

    def _auto_db_y_range(self, entries, xlim):
        values = [
            self._visible_entry_values(entry, xlim)
            for entry in entries
        ]
        values = [v for v in values if v.size]
        if not values:
            return None
        arr = np.concatenate(values)
        if arr.size == 0:
            return None
        ceiling = float(np.percentile(arr, _AUTO_CEILING_PCT))
        literal_hi = float(np.nanmax(arr))
        top = max(ceiling, literal_hi)
        bottom = ceiling - _AUTO_SPAN_DB
        if top <= bottom:
            center = (top + bottom) / 2.0
            bottom, top = center - 0.5, center + 0.5
        return bottom, top

    def _combined_time_bounds(self):
        bounds = []
        for e in self._entries:
            t = np.asarray(e.get('time', []), dtype=float)
            if t.size == 0:
                continue
            finite = t[np.isfinite(t)]
            if finite.size:
                bounds.append((float(finite.min()), float(finite.max())))
        if not bounds:
            for curve in self._time_curves:
                try:
                    t, _sig = curve.getData()
                except Exception:
                    continue
                t = np.asarray(t, dtype=float)
                finite = t[np.isfinite(t)]
                if finite.size:
                    bounds.append((float(finite.min()), float(finite.max())))
        if not bounds:
            return None
        return min(lo for lo, _hi in bounds), max(hi for _lo, hi in bounds)

    # ------------------------------------------------------------------
    # split-pane layout alignment
    # ------------------------------------------------------------------
    def recommended_split_title_width(self) -> float:
        viewport_w = 0.0
        try:
            viewport_w = float(self._glw.viewport().width())
        except Exception:
            viewport_w = float(self._glw.width())
        return max(120.0, viewport_w - 140.0)

    def _release_split_right_spacers(self) -> None:
        self._set_right_spacer(self._plot_amp, None)
        self._set_right_spacer(self._plot_time, None)

    def _release_split_titles(self) -> None:
        self._apply_title_texts()

    def _layout_owners(self):
        """Graphics items whose own ``QGraphicsLayout`` assigns axis geometry.

        Each ``AxisItem``'s cell is sized by its owning PlotItem's layout, NOT
        by the enclosing ``GraphicsLayout`` grid, so both have to be activated
        or a width change never reaches realized geometry.
        """
        return [self._glw.ci, self._plot_amp, self._plot_time]

    def line_layout_metrics(self) -> dict:
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
        return {
            'left_axis_width': max(left_widths) if left_widths else 0.0,
            'amp_bottom_axis_height': (
                bottom_heights[0] if bottom_heights else 0.0
            ),
            'time_bottom_axis_height': (
                bottom_heights[1] if len(bottom_heights) > 1 else 0.0
            ),
            'amp_right_reserve': self._right_reserve(self._plot_amp),
            'time_right_reserve': self._right_reserve(self._plot_time),
        }

    def apply_split_layout_alignment(
        self,
        *,
        left_axis_width: float,
        amp_bottom_axis_height: float | None = None,
        time_bottom_axis_height: float | None = None,
        amp_right_reserve: float | None = None,
        time_right_reserve: float | None = None,
    ) -> None:
        self._pin_split_left_axes(left_axis_width)
        self._pin_split_bottom_heights((
            (self._plot_amp, amp_bottom_axis_height),
            (self._plot_time, time_bottom_axis_height),
        ))
        if amp_right_reserve is not None:
            self._set_right_spacer(self._plot_amp, float(amp_right_reserve))
        if time_right_reserve is not None:
            self._set_right_spacer(self._plot_time, float(time_right_reserve))
        self._activate_graphics_layout()

    def _alignment_left_axes(self):
        return [self._plot_amp.getAxis('left'), self._plot_time.getAxis('left')]

    def _alignment_bottom_axes(self):
        return [
            self._plot_amp.getAxis('bottom'),
            self._plot_time.getAxis('bottom'),
        ]

    def _right_reserve(self, plot) -> float:
        try:
            return max(
                0.0,
                float(plot.sceneBoundingRect().right()
                      - plot.vb.sceneBoundingRect().right()),
            )
        except Exception:
            return 0.0

    def _set_right_spacer(self, plot, width: float | None) -> None:
        axis = plot.getAxis('right')
        if width is None or width <= 0:
            # No split reserve (single-pane): keep a thin VISIBLE right frame so
            # the plot reads as a closed rectangle, matching the top/left/bottom
            # frame from _apply_neutral_axis_frame. Previously this hid the right
            # axis entirely, leaving the time-preview plot's right edge open
            # (user-reported missing border).
            try:
                plot.showAxis('right', True)
                frame_pen = pg.mkPen(
                    color=PG_AXIS_NEUTRAL_COLOR, width=PG_AXIS_NEUTRAL_WIDTH)
                axis.setPen(frame_pen)
                axis.setStyle(showValues=False, tickLength=0)
                axis.setWidth(1)
            except Exception:
                pass
            return
        try:
            plot.showAxis('right', True)
            transparent = pg.mkPen((0, 0, 0, 0))
            axis.setPen(transparent)
            axis.setTextPen(transparent)
            axis.setStyle(showValues=False, tickLength=0)
            axis.setWidth(float(width))
        except Exception:
            pass

    def _apply_title_texts(self) -> None:
        self._apply_title_text(self._plot_amp, self._raw_amp_title)
        self._apply_title_text(self._plot_time, self._raw_time_title)

    def _apply_title_text(self, plot, title: str) -> None:
        try:
            plot.setTitle(None)
        except Exception:
            try:
                plot.setTitle("")
            except Exception:
                pass
        label = plot.titleLabel
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
        try:
            label.updateMin()
            label.updateGeometry()
        except Exception:
            pass

    def _activate_graphics_layout(self) -> None:
        """Realize pending geometry for the outer grid AND both PlotItems.

        Activating only ``self._glw.ci.layout`` re-flows the rows without ever
        re-sizing the ``AxisItem`` cells inside them, because those cells belong
        to each PlotItem's own layout. That is why releasing a left-axis pin
        here used to have no observable effect at all. Mirrors the traversal
        ``heatmap_canvas._activate_graphics_layout`` already did.
        """
        activate_item_layouts(self._layout_owners())

    def readout_at(self, freq: float):
        rows = []
        for e in self._entries:
            freq_arr = np.asarray(e['freq'])
            amp_arr = np.asarray(e['amp'])
            if freq_arr.size == 0 or amp_arr.size == 0:
                continue
            idx = int(np.argmin(np.abs(freq_arr - freq)))
            # Same 'legend_label'-over-'label' preference as the curve name
            # in plot_spectra (Task 6): a mixed-reference axis discloses each
            # curve's own dB[A] re ... in the hover readout too.
            rows.append((
                e.get('legend_label', e['label']),
                float(freq_arr[idx]), float(amp_arr[idx]),
            ))
        return rows

    def _make_frequency_cursor_lines(self, color):
        line = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen(color, width=1.2)
        )
        line.setZValue(50)
        line.hide()
        self._plot_amp.addItem(line, ignoreBounds=True)
        return [line]

    @staticmethod
    def _hide_frequency_cursor_lines(lines) -> None:
        for line in lines:
            line.hide()

    @staticmethod
    def _show_frequency_cursor_lines(lines, frequency) -> None:
        for line in lines:
            line.setValue(float(frequency))
            line.show()

    def _clear_frequency_cursor_readout(self) -> None:
        """Clear samples/lines without changing the pane's selected mode."""
        for lines in (
            self._cursor_lines, self._cursor_a_lines, self._cursor_b_lines,
        ):
            self._hide_frequency_cursor_lines(lines)
        self._cursor_a_frequency = None
        self._cursor_b_frequency = None
        self._next_dual_cursor = "a"
        self.cursor_info.emit("")
        self.dual_cursor_info.emit("")

    def cursor_mode(self) -> str:
        return self._cursor_mode

    def set_cursor_mode(self, mode: str) -> None:
        if mode not in {"off", "single", "dual"}:
            return
        self._cursor_mode = mode
        self._clear_frequency_cursor_readout()

    def _nearest_frequency(self, frequency):
        rows = self.readout_at(float(frequency))
        return float(rows[0][1]) if rows else None

    def set_cursor_frequency(self, frequency) -> str:
        snapped = self._nearest_frequency(frequency)
        if snapped is None:
            self.cursor_info.emit("")
            return ""
        self._show_frequency_cursor_lines(self._cursor_lines, snapped)
        text = self.format_readout(snapped)
        self.cursor_info.emit(text)
        return text

    def set_dual_cursor_frequencies(self, a_frequency, b_frequency) -> str:
        a_value = self._nearest_frequency(a_frequency)
        if a_value is None:
            self.cursor_info.emit("")
            self.dual_cursor_info.emit("")
            return ""
        self._cursor_a_frequency = a_value
        self._show_frequency_cursor_lines(self._cursor_a_lines, a_value)
        self._cursor_b_frequency = None
        self._hide_frequency_cursor_lines(self._cursor_b_lines)
        if b_frequency is None:
            primary = f"A: f={a_value:g} Hz | 点击 B 选择第二点"
            self.cursor_info.emit(primary)
            self.dual_cursor_info.emit("")
            return primary
        b_value = self._nearest_frequency(b_frequency)
        if b_value is None:
            return ""
        self._cursor_b_frequency = b_value
        self._show_frequency_cursor_lines(self._cursor_b_lines, b_value)
        primary = (
            f"A={a_value:g} Hz | B={b_value:g} Hz | "
            f'<span style="{_DUAL_CURSOR_DELTA_STYLE}">'
            f"Δf={b_value - a_value:+g} Hz</span>"
        )
        self.cursor_info.emit(primary)
        self.dual_cursor_info.emit(self._format_dual_cursor_detail(a_value, b_value))
        return primary

    def _format_dual_cursor_detail(self, a_value: float, b_value: float) -> str:
        """Keep A/B values while surfacing every B-minus-A spectrum delta."""
        a_rows = self.readout_at(a_value)
        b_rows = self.readout_at(b_value)
        deltas = []
        for a_row, b_row in zip(a_rows, b_rows):
            label = str(b_row[0])
            delta = float(b_row[2]) - float(a_row[2])
            deltas.append(f"{escape(label)}={delta:+.4g}")
        delta_html = " · ".join(deltas) or "—"
        return (
            f"A：{escape(self.format_readout(a_value))}<br>"
            f"B：{escape(self.format_readout(b_value))}<br>"
            f'<span style="{_DUAL_CURSOR_DELTA_STYLE}">'
            f"ΔY：{delta_html}</span>"
        )

    def format_readout(self, freq: float) -> str:
        rows = self.readout_at(freq)
        if not rows:
            return ""
        parts = []
        base_amp = rows[0][2]
        for i, (label, _f, amp) in enumerate(rows):
            seg = f"{label}: {amp:.4g}"
            if i > 0:
                seg += f"  Δ{amp - base_amp:+.4g}"
            parts.append(seg)
        return f"f={rows[0][1]:.2f} Hz  " + "  |  ".join(parts)

    def _on_hover(self, pos) -> None:
        if self._cursor_mode != "single":
            return
        if not self._plot_amp.vb.sceneBoundingRect().contains(pos) or not self._entries:
            self.cursor_info.emit("")
            return
        x = self._plot_amp.vb.mapSceneToView(pos).x()
        self.set_cursor_frequency(x)

    def _nearest_entry_index(self, freq: float, amp_y: float) -> int | None:
        if not self._entries:
            return None
        best = None
        for i, e in enumerate(self._entries):
            freq_arr = np.asarray(e['freq'])
            amp_arr = np.asarray(e['amp'])
            if freq_arr.size == 0 or amp_arr.size == 0:
                continue
            idx = int(np.argmin(np.abs(freq_arr - freq)))
            dy = abs(float(amp_arr[idx]) - float(amp_y))
            if best is None or dy < best[0]:
                best = (dy, i)
        return None if best is None else best[1]

    # ------------------------------------------------------------------
    def _axis_label_unit(self, label: str) -> str:
        text = str(label or "")
        if "dB" in text:
            return "dB"
        if "(Hz)" in text:
            return "Hz"
        if "(s)" in text:
            return "s"
        return ""

    def _amp_y_unit(self) -> str:
        try:
            axis = self._plot_amp.getAxis('left')
            return self._axis_label_unit(getattr(axis, 'labelText', ''))
        except Exception:
            return ""

    @staticmethod
    def _curve_color(curve, fallback="#1769e0") -> str:
        try:
            pen = curve.opts.get('pen')
            color = pen.color()
            if color.isValid():
                return color.name()
        except Exception:
            pass
        return fallback

    def set_remark_enabled(self, enabled: bool) -> None:
        self._remark_enabled = bool(enabled)
        # Suppress BOTH plots' default right-click ViewBox menu while annotating
        # so a right-click reaches the delete-nearest slot. ev.accept() in the
        # click slot is structurally too late to block the menu (the menu is
        # raised during item dispatch, before sigMouseClicked fires) — the menu's
        # real gate is menuEnabled(). Lesson: sigmouseclicked-fires-after-viewbox-menu.
        self._remark_interaction.set_enabled(
            self._remark_enabled,
            viewport=self._glw.viewport(),
            menu_viewboxes=(self._plot_amp.vb, self._plot_time.vb),
        )

    def clear_remarks(self) -> None:
        self._remark_artist.clear(self._remarks)

    def remark_count(self) -> int:
        return len(self._remarks)

    def _append_remark(
        self, *, vb, x: float, y: float, color: str, unit_x: str,
        unit_y: str = "", plot=None,
    ) -> None:
        point = RemarkPoint(
            vb=vb,
            x=float(x),
            y=float(y),
            color=color or "#dc2626",
            unit_x=unit_x,
            unit_y=unit_y,
        )
        remark = self._remark_artist.add(point)
        remark['plot'] = plot
        self._remarks.append(remark)

    def _remove_remark(self, remark) -> None:
        self._remark_artist.remove(remark)
        try:
            self._remarks.remove(remark)
        except ValueError:
            pass

    def add_remark_at(self, which: str, x: float, y: float) -> None:
        if not self._remark_enabled:
            return
        if which == 'time':
            self._add_time_remark_at(x, y)
            return
        if which != 'amp' or not self._entries:
            return
        best = None
        for e in self._entries:
            freq_arr = np.asarray(e['freq'])
            amp_arr = np.asarray(e['amp'])
            if freq_arr.size == 0 or amp_arr.size == 0:
                continue
            idx = int(np.argmin(np.abs(freq_arr - x)))
            sx, sy = float(freq_arr[idx]), float(amp_arr[idx])
            dy = abs(sy - y)
            if best is None or dy < best[0]:
                best = (dy, sx, sy, e.get('color', '#2563eb'))
        if best is None:
            return
        _dy, sx, sy, color = best
        self._append_remark(
            vb=self._plot_amp.vb,
            x=sx,
            y=sy,
            color=color,
            unit_x="Hz",
            unit_y=self._amp_y_unit(),
            plot=self._plot_amp,
        )

    def _nearest_amp_remark_candidate(self, scene_pos):
        if scene_pos is None or not self._entries:
            return None
        try:
            click_data = self._plot_amp.vb.mapSceneToView(scene_pos)
            x_data = float(click_data.x())
        except Exception:
            return None
        try:
            x_range, _y_range = self._plot_amp.vb.viewRange()
            rect = self._plot_amp.vb.sceneBoundingRect()
            span = abs(float(x_range[1]) - float(x_range[0]))
            width = max(float(rect.width()), 1.0)
            half_window = max((span / width) * 48.0, 1e-12)
        except Exception:
            half_window = 0.0
        best = None
        for e in self._entries:
            freq_arr = np.asarray(e['freq'], dtype=float)
            amp_arr = np.asarray(e['amp'], dtype=float)
            n = min(freq_arr.size, amp_arr.size)
            if n == 0:
                continue
            freq_arr = freq_arr[:n]
            amp_arr = amp_arr[:n]
            finite = np.isfinite(freq_arr) & np.isfinite(amp_arr)
            if not finite.any():
                continue
            freq_arr = freq_arr[finite]
            amp_arr = amp_arr[finite]
            nearest_idx = int(np.argmin(np.abs(freq_arr - x_data)))
            lo = max(0, nearest_idx - 32)
            hi = min(freq_arr.size, nearest_idx + 33)
            idxs = np.arange(lo, hi, dtype=int)
            if half_window > 0.0:
                near_x = np.flatnonzero(np.abs(freq_arr - x_data) <= half_window)
                if near_x.size:
                    idxs = np.union1d(idxs, near_x)
            for idx in idxs:
                sx, sy = float(freq_arr[idx]), float(amp_arr[idx])
                try:
                    pt = self._plot_amp.vb.mapViewToScene(QPointF(sx, sy))
                except Exception:
                    continue
                dx = pt.x() - scene_pos.x()
                dy = pt.y() - scene_pos.y()
                d2 = dx * dx + dy * dy
                if best is None or d2 < best[0]:
                    best = (d2, sx, sy, e.get('color', '#2563eb'))
        return best

    def _add_amp_remark_at_scene(self, scene_pos) -> None:
        best = self._nearest_amp_remark_candidate(scene_pos)
        if best is None:
            return
        _d2, sx, sy, color = best
        self._append_remark(
            vb=self._plot_amp.vb,
            x=sx,
            y=sy,
            color=color,
            unit_x="Hz",
            unit_y=self._amp_y_unit(),
            plot=self._plot_amp,
        )

    def _time_curve_owners(self):
        """Yield ``(curve, vb, plot_or_none)`` for each time-preview curve.

        Curve 0 lives on the main ViewBox (``_plot_time.vb`` / its left axis);
        each extra curve lives on its own aux ViewBox (``_time_overlay_vbs[i-1]``)
        with a colour-coded right axis. ``plot_or_none`` is ``_plot_time`` only
        for curve 0 (annotation items go onto the plot so they share the left
        axis); aux annotations go straight onto the aux ViewBox."""
        if not self._time_curves:
            return
        yield (self._time_curves[0], self._plot_time.vb, self._plot_time)
        for curve, vb in zip(self._time_curves[1:], self._time_overlay_vbs):
            yield (curve, vb, None)

    def _add_time_remark_at(self, x: float, y: float) -> None:
        if not self._time_curves:
            return
        # Each overlay curve sits on a different Y scale (own aux ViewBox), so a
        # data-space nearest search would always favour the largest-scale curve.
        # Compare in SCREEN (scene) space: project the clicked point and every
        # candidate sample through each curve's OWN ViewBox, then pick the
        # globally nearest sample. The clicked (x, y) is in the MAIN ViewBox's
        # data space (the click handler maps via _plot_time.vb), so anchor the
        # scene reference there. Lesson: overlay nearest-point must be screen-space.
        try:
            click_scene = self._plot_time.vb.mapViewToScene(QPointF(x, y))
        except Exception:
            return
        best = None  # (dist2, sx, sy, vb, plot_or_none, color)
        for curve, vb, plot in self._time_curve_owners():
            try:
                xs, ys = curve.getData()
            except Exception:
                continue
            if xs is None or ys is None:
                continue
            xs = np.asarray(xs, dtype=float)
            ys = np.asarray(ys, dtype=float)
            mask = np.isfinite(xs) & np.isfinite(ys)
            if not mask.any():
                continue
            xs, ys = xs[mask], ys[mask]
            # Narrow to the few samples nearest in X first (cheap), then compare
            # the handful in screen space — projecting every sample is wasteful.
            xi = int(np.argmin(np.abs(xs - x)))
            lo = max(0, xi - 2)
            hi = min(xs.size, xi + 3)
            for j in range(lo, hi):
                sx, sy = float(xs[j]), float(ys[j])
                try:
                    pt = vb.mapViewToScene(QPointF(sx, sy))
                except Exception:
                    continue
                dx = pt.x() - click_scene.x()
                dy = pt.y() - click_scene.y()
                d2 = dx * dx + dy * dy
                if best is None or d2 < best[0]:
                    best = (d2, sx, sy, vb, plot, self._curve_color(curve))
        if best is None:
            return
        _d2, sx, sy, vb, plot, color = best
        self._append_remark(
            vb=vb,
            x=sx,
            y=sy,
            color=color,
            unit_x="s",
            unit_y="",
            plot=plot,
        )

    def remove_remark_near(self, which: str, x: float) -> None:
        if which == 'time':
            time_vbs = {self._plot_time.vb, *self._time_overlay_vbs}
            cands = [r for r in self._remarks if r.get('vb') in time_vbs]
            if not cands:
                return
            nearest = min(cands, key=lambda r: abs(r['dot'].getData()[0][0] - x))
            self._remove_remark(nearest)
            return
        if which != 'amp':
            return
        cands = [
            r for r in self._remarks
            if r.get('plot') is self._plot_amp or r.get('vb') is self._plot_amp.vb
        ]
        if not cands:
            return
        nearest = min(cands, key=lambda r: abs(r['dot'].getData()[0][0] - x))
        self._remove_remark(nearest)

    def _remove_amp_remark_at_scene(self, scene_pos) -> None:
        cands = [
            r for r in self._remarks
            if r.get('plot') is self._plot_amp or r.get('vb') is self._plot_amp.vb
        ]
        if not cands or scene_pos is None:
            return
        best = None
        for remark in cands:
            try:
                xs, ys = remark['dot'].getData()
                pt = self._plot_amp.vb.mapViewToScene(
                    QPointF(float(xs[0]), float(ys[0])))
            except Exception:
                continue
            dx = pt.x() - scene_pos.x()
            dy = pt.y() - scene_pos.y()
            d2 = dx * dx + dy * dy
            if best is None or d2 < best[0]:
                best = (d2, remark)
        if best is not None:
            self._remove_remark(best[1])

    def _viewport_pos_to_scene(self, viewport_pos):
        return viewport_pos_to_scene(self._glw, viewport_pos)

    def _add_remark_at_viewport_pos(self, viewport_pos) -> None:
        scene_pos = self._viewport_pos_to_scene(viewport_pos)
        if scene_pos is None:
            return
        if self._plot_amp.vb.sceneBoundingRect().contains(scene_pos):
            self._add_amp_remark_at_scene(scene_pos)
            return
        if self._plot_time.vb.sceneBoundingRect().contains(scene_pos):
            v = self._plot_time.vb.mapSceneToView(scene_pos)
            self.add_remark_at('time', v.x(), v.y())

    def _remove_remark_at_viewport_pos(self, viewport_pos) -> None:
        scene_pos = self._viewport_pos_to_scene(viewport_pos)
        if scene_pos is None:
            return
        if self._plot_amp.vb.sceneBoundingRect().contains(scene_pos):
            self._remove_amp_remark_at_scene(scene_pos)
            return
        if self._plot_time.vb.sceneBoundingRect().contains(scene_pos):
            v = self._plot_time.vb.mapSceneToView(scene_pos)
            self.remove_remark_near('time', v.x())

    def _remark_item_at_viewport_pos(self, viewport_pos):
        return remark_at_viewport_pos(self._remarks, self._glw, viewport_pos)

    def eventFilter(self, obj, event):
        try:
            viewport = self._glw.viewport()
        except Exception:
            viewport = None
        try:
            if obj is viewport and event.type() == QEvent.MouseButtonDblClick:
                if event.button() == Qt.LeftButton and not self._remark_enabled:
                    self._handle_time_or_amp_double_click(event.pos())
                    return True
            if obj is viewport and self._remark_enabled:
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

    def _handle_time_or_amp_double_click(self, viewport_pos) -> None:
        """Double-click → chart options (amp) or curve color / time options."""
        try:
            scene_pos = self._glw.mapToScene(viewport_pos)
        except Exception:
            return
        # Spectrum row → existing amp chart-options dialog.
        try:
            if self._plot_amp.vb.sceneBoundingRect().contains(scene_pos):
                self.open_chart_options_dialog(parent=self.window())
                return
        except Exception:
            pass
        # Time-preview row → emphasise nearest curve; left opens full options,
        # aux opens a colour picker (aux curves are not on the main PlotItem).
        try:
            in_time = self._plot_time.vb.sceneBoundingRect().contains(scene_pos)
        except Exception:
            in_time = False
        if not in_time:
            # Right-axis gutters sit outside the main vb rect.
            for i, ax in enumerate(self._time_overlay_axes):
                try:
                    if ax.sceneBoundingRect().contains(scene_pos):
                        self._edit_time_curve_appearance(i + 1)
                        return
                except Exception:
                    continue
            return
        try:
            v = self._plot_time.vb.mapSceneToView(scene_pos)
            idx = self._nearest_time_entry_index(float(v.x()), float(v.y()))
        except Exception:
            idx = 0
        if idx is None:
            idx = 0
        self._edit_time_curve_appearance(int(idx))

    def _edit_time_curve_appearance(self, idx: int) -> None:
        if not self._time_curves:
            return
        idx = max(0, min(int(idx), len(self._time_curves) - 1))
        self._selected_time_entry_idx = idx
        self._apply_time_preview_emphasis()
        if idx == 0:
            from mf4_analyzer.ui import _axis_interaction
            handle = PgAxisHandle(self._plot_time, owner_canvas=self)
            _axis_interaction.edit_chart_options_dialog(
                self.window() if self.window() is not None else self, handle)
            self._apply_time_preview_emphasis()
            return
        from PyQt5.QtGui import QColor
        from PyQt5.QtWidgets import QColorDialog

        curve = self._time_curves[idx]
        current = QColor(self._curve_color(curve))
        color = QColorDialog.getColor(
            current, self.window() if self.window() is not None else self,
            "曲线颜色")
        if not color.isValid():
            return
        try:
            pen = curve.opts.get("pen")
            if pen is not None:
                pen.setColor(color)
                curve.setPen(pen)
            axis = self._time_overlay_axes[idx - 1]
            axis.setTextPen(pg.mkPen(color=color))
        except Exception:
            pass
        if idx < len(self._entries):
            self._entries[idx]['color'] = color.name()
        self.layout_geometry_changed.emit()

    def _on_click(self, ev) -> None:
        if self._remark_enabled:
            return
        scene_pos = ev.scenePos()
        # Spectrum (amp) row.
        if self._plot_amp.vb.sceneBoundingRect().contains(scene_pos):
            v = self._plot_amp.vb.mapSceneToView(scene_pos)
            if ev.button() == Qt.LeftButton:
                if self._cursor_mode == "dual":
                    if self._next_dual_cursor == "a":
                        self.set_dual_cursor_frequencies(v.x(), None)
                        self._next_dual_cursor = "b"
                    else:
                        self.set_dual_cursor_frequencies(
                            self._cursor_a_frequency, v.x()
                        )
                        self._next_dual_cursor = "a"
                    ev.accept()
                    return
                if self._remark_enabled:
                    self.add_remark_at('amp', v.x(), v.y())
                else:
                    idx = self._nearest_entry_index(v.x(), v.y())
                    if idx is not None:
                        self.select_time_entry(idx)
                        # User picked the preview source by clicking the curve.
                        self.time_source_selected.emit()
                return
            if ev.button() == Qt.RightButton and self._remark_enabled:
                self.remove_remark_near('amp', v.x())
                ev.accept()
            return
        # Time-preview row: annotations only (no entry-selection here). Coordinates
        # come from the MAIN ViewBox (curve 0 / left axis); the aux overlay curves
        # are X-linked to it, and _add_time_remark_at projects each curve through
        # its own ViewBox to pick the screen-nearest sample.
        if (self._remark_enabled
                and self._plot_time.vb.sceneBoundingRect().contains(scene_pos)):
            v = self._plot_time.vb.mapSceneToView(scene_pos)
            if ev.button() == Qt.LeftButton:
                self.add_remark_at('time', v.x(), v.y())
            elif ev.button() == Qt.RightButton:
                self.remove_remark_near('time', v.x())
                ev.accept()

    # ------------------------------------------------------------------
    def grab_pixmap(self, scale: float = 2.0) -> QPixmap:
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
