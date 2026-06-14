"""PgLineCanvas: FFT amplitude overlay plus FFT-source time preview.

The top row draws overlaid FFT amplitude curves after computation. The lower
row shows the time-domain input sources immediately when they are selected,
and remains an overlay when multiple FFT sources are active. NO OpenGL: it
breaks grab_pixmap exports on this project.
"""
from __future__ import annotations

import numpy as np
from PyQt5.QtCore import QPointF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget
import pyqtgraph as pg

from mf4_analyzer.ui._axis_handle import (
    PG_AXIS_NEUTRAL_COLOR,
    PG_AXIS_NEUTRAL_WIDTH,
)
from mf4_analyzer.ui.canvases import build_envelope

from .heatmap_canvas import (
    _apply_neutral_axis_frame,
    _apply_plot_collapse,
    _available_split_height,
    _clamp_bottom_split,
    _CollapsedRail,
    _make_analysis_plot,
    _position_collapse_layout,
    _SPLIT_COLLAPSE_AT,
    _SPLIT_ROW_SPACING,
    _SplitDivider,
    _tick_counts_to_density,
    _visual_padded_bounds,
)
from .context_menu import redesign_pg_context_menu
from .ticks_math import _frame_to_nice, _fmt_tick
from .viewbox import _ModifierWheelViewBox


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


class PgLineCanvas(QWidget):
    cursor_info = pyqtSignal(str)
    context_menu_requested = pyqtSignal()
    layout_geometry_changed = pyqtSignal()
    time_preview_range_changed = pyqtSignal(float, float)
    # AA status traffic-light (mirrors TimeDomainCanvasPG). _ChartCard wires
    # this signal + quality_status() into the bottom-right quality dot, so the
    # FFT card shows the same red/yellow/green antialiasing indicator the
    # time-domain card does.
    quality_status_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._glw = pg.GraphicsLayoutWidget(self)
        self._glw.setBackground("#ffffff")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._glw)

        self._plot_amp = _make_analysis_plot(
            self._glw, 0, 0, _ModifierWheelViewBox(owner_canvas=self))
        self._plot_time = _make_analysis_plot(
            self._glw, 1, 0, _ModifierWheelViewBox(owner_canvas=self))
        for p in (self._plot_amp, self._plot_time):
            _apply_neutral_axis_frame(p)
            p.showGrid(x=True, y=True, alpha=0.25)
            for _ax in ('left', 'bottom', 'top', 'right'):
                try:
                    p.getAxis(_ax).setStyle(maxTickLevel=0)
                except Exception:
                    pass
            # major grid 只画在 left+bottom；top/right 关掉，避免横向网格被
            # 左右两轴重复过绘、且顶部网格线与边框叠成"双线"（spec R2）。
            p.getAxis('top').setGrid(False)
            p.getAxis('right').setGrid(False)
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
        # Multi-Y overlay for the time preview: when >1 source is overlaid each
        # extra curve gets its own auto-scaled aux ViewBox + a colour-coded
        # right axis (mirrors TimeDomainCanvasPG overlay). The first curve stays
        # on _plot_time's own left axis.
        self._time_overlay_vbs = []
        self._time_overlay_axes = []
        # Time-preview Y graticule division count (mirrors the time-domain
        # overlay's divisions). Driven by the Y tick density; the left axis and
        # every aux right axis are framed to this many equal nice divisions so
        # all their ticks land on the SAME set of horizontal grid lines. Default
        # 8 matches the FFT card's default Y tick count.
        self._time_divisions = 8
        self._entries = []
        self._selected_time_entry_idx = None
        self._remarks = []
        self._remark_enabled = False
        self._last_xlim = None
        self._last_yrange = None
        self._mouse_mode_controller = None
        self._raw_amp_title = ''
        self._raw_time_title = ''
        self._split_title_width = None
        self._spectrum_stale = False
        self._stale_banner = None

        # Interactive curve-AA policy (mirrors the time-domain canvas): drop
        # antialiasing while the user pans/zooms so each frame is a cheap
        # non-AA raster, then restore crisp AA after a short hands-off idle.
        self._aa_on = True
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
        # Keep the overlay aux ViewBoxes glued to the time plot's main ViewBox
        # (geometry on resize, X range on pan/zoom) so the extra Y axes track.
        self._plot_time.vb.sigResized.connect(self._sync_time_overlay_vbs)
        self._plot_time.vb.sigXRangeChanged.connect(self._sync_time_overlay_vbs)

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

        # The FFT time window is taken from the preview's VISIBLE x-range:
        # pan/zoom the preview and `_emit_time_preview_range` (driven by
        # sigRangeChangedManually) pushes it to the inspector. There is no
        # separate left-drag region selector anymore — it collided with pan.

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

    def _apply_idle_curve_aa(self):
        """Restore each curve's settled-state AA: the amplitude overlay is
        always crisp; the time preview keeps AA off whenever more than one
        source is overlaid (its creation policy in
        ``_plot_time_preview_entries``)."""
        time_idle_aa = len(self._time_curves) <= 1
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
        time-preview curves intentionally drop AA when >1 source is overlaid,
        so they are not used to decide the green/red readiness state.
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
            self._emit_time_preview_range()

    def _emit_time_preview_range(self) -> bool:
        try:
            (lo, hi), _yr = self._plot_time.vb.viewRange()
            lo = float(lo)
            hi = float(hi)
        except Exception:
            return False
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            return False
        self.time_preview_range_changed.emit(lo, hi)
        return True

    def register_mouse_mode_controller(self, controller) -> None:
        self._mouse_mode_controller = controller

    def _plot_item_for_view_box(self, view_box):
        for plot in (self._plot_amp, self._plot_time):
            if plot.vb is view_box:
                return plot
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
        # Re-snap the time preview's fitted Y back onto the shared graticule so
        # the right axes stay aligned (mirrors the time-domain fit path); the
        # spectrum row has no graticule and keeps the raw fitted range.
        if plot is self._plot_time:
            self._reframe_time_y_to_grid()
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
            allow_y_grid=True,
            keep_plot_options=True,
        )

    def _handle_wheel_dispatch(self, *, delta, modifiers, x_pos, y_pos,
                               view_box=None):
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
        # This zoom sets the range programmatically (no sigRangeChangedManually),
        # so drop AA for the interactive raster and re-arm the idle restore here.
        self.disable_interactive_quality()
        self.schedule_idle_quality()
        if view_box is self._plot_time.vb:
            self._emit_time_preview_range()
        self.layout_geometry_changed.emit()
        return True

    # ------------------------------------------------------------------
    def plot_spectra(self, entries, *, xlim, amp_label, title,
                     y_auto=True, y_min=0.0, y_max=0.0):
        """Plot FFT curves and show all source time traces below."""
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
            curve = self._plot_amp.plot(
                e['freq'], e['amp'], pen=pen, name=e['label'],
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
        else:
            self._plot_amp.enableAutoRange(axis='y')

        self._plot_time_preview_entries(
            self._entries, selected_idx=0 if self._entries else None,
            title="时域预览",
        )
        # Fresh curves are rebuilt AA-on; surface the resulting (green) state
        # on the quality dot immediately.
        self._emit_quality_status()

    def plot_time_preview(self, entries, *, title="时域预览",
                          clear_spectrum=True) -> None:
        """Show selected FFT input sources before spectrum computation.

        ``clear_spectrum=True`` (genuine reset: mode entry / file close) wipes
        the upper amplitude row. ``clear_spectrum=False`` (selection change on
        an already-computed spectrum) KEEPS the amplitude curves visible but
        DIMS them and overlays a "结果已过期" marker, while the lower time row
        still updates live to the new selection. The next ``plot_spectra``
        restores the normal visual state."""
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

    def _reset_time_preview_to_extents(self) -> None:
        bounds = self._combined_time_bounds()
        if bounds is None:
            return
        tx0, tx1 = _visual_padded_bounds(bounds[0], bounds[1])
        self._plot_time.setXRange(tx0, tx1, padding=0)
        # Re-frame Y to the shared graticule (was per-axis autoRange).
        self._reframe_time_y_to_grid()

    def full_reset(self) -> None:
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
        self.cursor_info.emit("")
        self.layout_geometry_changed.emit()
        # Curves are gone → the AA dot must fall back to red ("no curves")
        # instead of showing the previous render's stale green.
        self._emit_quality_status()

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
    def _set_bottom_collapsed(self, collapsed: bool) -> None:
        self._bottom_collapsed = bool(collapsed)
        if not self._bottom_collapsed:
            # Expand always returns to the DEFAULT height (confirmed product
            # decision). A near-collapse drag floor-clamps _bottom_split_h to
            # _SPLIT_MIN_BOTTOM in its last pre-fold steps, so reading the
            # remembered value here would restore the time preview at half
            # height; reset to the default before applying so the row comes
            # back full size. Double-click reset (_on_split_reset) already
            # restores the default by its own path.
            self._bottom_split_h = float(self._bottom_split_default)
        state = 'bottom' if self._bottom_collapsed else 'none'
        _apply_plot_collapse(self._plot_amp, self._plot_time, state,
                             self._bottom_split_h)
        self._position_collapse_ctrl()
        self.layout_geometry_changed.emit()

    def _on_collapse_changed(self, state) -> None:
        # Compat entry (programmatic / tests): 'bottom' collapses, else expands.
        self._set_bottom_collapsed(state == 'bottom')

    def _position_collapse_ctrl(self, *_args) -> None:
        _position_collapse_layout(
            getattr(self, '_collapsed_rail', None),
            getattr(self, '_split_divider', None),
            self._plot_amp, self._plot_time,
            getattr(self, '_bottom_collapsed', False))

    def _position_split_divider(self, *_args) -> None:
        self._position_collapse_ctrl()

    # ---- split-divider drag (resize) / double-click (reset) --------------
    def _available_split_height(self) -> float:
        return _available_split_height(self)

    def _on_split_drag_started(self) -> None:
        self._drag_start_bottom_h = float(self._bottom_split_h)

    def _on_split_drag_delta(self, delta) -> None:
        raw = self._drag_start_bottom_h + delta
        if raw <= _SPLIT_COLLAPSE_AT:
            self._set_bottom_collapsed(True)
            return
        self._bottom_split_h = _clamp_bottom_split(
            raw, self._available_split_height())
        self._plot_time.setMaximumHeight(int(self._bottom_split_h))
        self._position_collapse_ctrl()
        self._position_split_divider()
        self.layout_geometry_changed.emit()

    def _on_split_drag_finished(self) -> None:
        self._position_split_divider()

    def _on_split_reset(self) -> None:
        self._bottom_split_h = float(self._bottom_split_default)
        if not self._bottom_collapsed:
            self._plot_time.setMaximumHeight(int(self._bottom_split_h))
        self._position_collapse_ctrl()
        self._position_split_divider()
        self.layout_geometry_changed.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_collapse_ctrl()
        self._position_split_divider()

    def showEvent(self, event):
        super().showEvent(event)
        self._position_collapse_ctrl()
        self._position_split_divider()

    def has_result(self) -> bool:
        return bool(self._entries)

    def set_tick_density(self, x, y) -> None:
        try:
            x_n = max(3, int(x))
            y_n = max(3, int(y))
        except (TypeError, ValueError):
            return
        x_d, y_d = _tick_counts_to_density(x_n, y_n)
        # Spectrum (top): no aux right axes, no graticule — keep the plain
        # density-driven ticks on both axes.
        for axis, density in ((self._plot_amp.getAxis('bottom'), x_d),
                              (self._plot_amp.getAxis('left'), y_d)):
            axis.setStyle(maxTickLevel=0)
            axis.setTickDensity(density)
        # Time preview: X still uses density; Y drives the shared graticule
        # divisions so the left axis AND every aux right axis re-tick together
        # (fixes "Y tick density had no effect on the right axes").
        tb = self._plot_time.getAxis('bottom')
        tb.setStyle(maxTickLevel=0)
        tb.setTickDensity(x_d)
        self._time_divisions = max(3, min(20, y_n))
        self._reframe_time_y_to_grid()
        self.layout_geometry_changed.emit()

    # ------------------------------------------------------------------
    def select_time_entry(self, idx) -> None:
        self._plot_time_preview_entries(self._entries, selected_idx=idx,
                                        title="时域预览")

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

    def _add_time_overlay_axis(self, color, position):
        """Create one aux ViewBox + colour-coded right axis for an overlay
        curve. ``position`` is the 1-based overlay slot (2nd curve → 1, …)."""
        aux_vb = pg.ViewBox()
        axis = pg.AxisItem('right')
        # Frame line stays neutral; the tick TEXT follows the curve colour so a
        # glance maps each right axis to its trace (no channel-name clutter).
        axis.setPen(pg.mkPen(color=PG_AXIS_NEUTRAL_COLOR, width=PG_AXIS_NEUTRAL_WIDTH))
        axis.setTextPen(pg.mkPen(color=color))
        self._plot_time.layout.addItem(axis, 2, 2 + position)
        self._plot_time.layout.setHorizontalSpacing(8)
        self._plot_time.scene().addItem(aux_vb)
        axis.linkToView(aux_vb)
        aux_vb.setXLink(self._plot_time.vb)
        aux_vb.setMouseEnabled(x=False, y=False)
        aux_vb.setZValue(-10000)
        aux_vb.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
        self._time_overlay_vbs.append(aux_vb)
        self._time_overlay_axes.append(axis)
        return aux_vb

    def _reframe_time_y_to_grid(self) -> None:
        """Frame the time-preview's main axis (curve 0 / left / ``_plot_time.vb``)
        and every aux right axis to ``_time_divisions`` equal nice divisions and
        pin their ticks, so all axes land on the SAME k/n horizontal grid lines
        (mirrors the time-domain overlay graticule).

        Curve 0 lives on the main ViewBox (its left axis grid IS the k/n
        graticule); each extra curve lives on its own aux ViewBox + right axis,
        so framing every axis to the same n divisions makes the right-axis ticks
        coincide with the left-axis grid. Empty / constant-signal curves are
        skipped (``_frame_to_nice`` already guards a zero span)."""
        n = max(3, min(20, int(self._time_divisions)))
        if not self._time_curves:
            return
        # Single unified pairing: (main vb, left axis, curve0), then each aux.
        triples = [(self._plot_time.vb,
                    self._plot_time.getAxis('left'),
                    self._time_curves[0])]
        triples.extend(zip(self._time_overlay_vbs,
                           self._time_overlay_axes,
                           self._time_curves[1:]))
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
            try:
                vb.enableAutoRange(axis='y', enable=False)
                vb.setYRange(bottom, top, padding=0)
                axis.setStyle(maxTickLevel=0)
                axis.setTicks([[(v, _fmt_tick(v)) for v in ticks], []])
            except Exception:
                pass
        # Preview Y is pinned to the graticule: left-drag pans X only (= picks
        # the FFT window). Confirmed product decision to lock Y.
        try:
            self._plot_time.vb.setMouseEnabled(x=True, y=False)
        except Exception:
            pass

    def _sync_time_overlay_vbs(self, *_args) -> None:
        """Glue every aux ViewBox geometry to the time plot's main ViewBox."""
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
        # via the same build_envelope used by TimeDomainCanvasPG, and (2) drop
        # antialias once more than one channel is overlaid.
        pixel_width = self._preview_pixel_width()
        antialias = len(entries) <= 1
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
                aux_vb = self._add_time_overlay_axis(color, i)
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

    def prepare_split_layout_alignment(self, title_width: float | None) -> None:
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
        self._set_right_spacer(self._plot_amp, None)
        self._set_right_spacer(self._plot_time, None)
        self._apply_title_texts()
        self._activate_graphics_layout()

    def reset_split_layout_alignment(self) -> None:
        self.prepare_split_layout_alignment(None)
        # Single-pane: unify the amp and time-preview left axes to a common
        # width so both rows share a left edge. prepare_* just released the
        # widths to their natural sizes, which differ when the two plots' y
        # tick labels differ (e.g. spectrum amplitude vs time-domain
        # amplitude) → misaligned left edges. Split mode (≥2 panes) is handled
        # by the page via apply_split_layout_alignment, which already unifies
        # left widths, so do this only on the single-pane reset path.
        self._unify_stacked_left_axes()

    def _unify_stacked_left_axes(self) -> None:
        """Pin the amp and time-preview left axes to the MAX of their natural
        widths so both stacked plots share a left edge in single-pane mode.

        Call only AFTER prepare_split_layout_alignment(None) released the
        widths (setWidth(None)) and realized the layout, so width() reports each
        axis's natural size."""
        axes = self._alignment_left_axes()
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

    def line_layout_metrics(self) -> dict:
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
        for axis in self._alignment_left_axes():
            try:
                axis.setWidth(float(left_axis_width))
            except Exception:
                pass
        if amp_bottom_axis_height is not None:
            try:
                self._plot_amp.getAxis('bottom').setHeight(
                    float(amp_bottom_axis_height))
            except Exception:
                pass
        if time_bottom_axis_height is not None:
            try:
                self._plot_time.getAxis('bottom').setHeight(
                    float(time_bottom_axis_height))
            except Exception:
                pass
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
        try:
            layout = self._glw.ci.layout
            layout.invalidate()
            layout.activate()
        except Exception:
            pass

    def readout_at(self, freq: float):
        rows = []
        for e in self._entries:
            freq_arr = np.asarray(e['freq'])
            amp_arr = np.asarray(e['amp'])
            if freq_arr.size == 0 or amp_arr.size == 0:
                continue
            idx = int(np.argmin(np.abs(freq_arr - freq)))
            rows.append((e['label'], float(freq_arr[idx]), float(amp_arr[idx])))
        return rows

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
        if not self._plot_amp.vb.sceneBoundingRect().contains(pos) or not self._entries:
            self.cursor_info.emit("")
            return
        x = self._plot_amp.vb.mapSceneToView(pos).x()
        self.cursor_info.emit(self.format_readout(x))

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
    def set_remark_enabled(self, enabled: bool) -> None:
        self._remark_enabled = bool(enabled)
        # Suppress BOTH plots' default right-click ViewBox menu while annotating
        # so a right-click reaches the delete-nearest slot. ev.accept() in the
        # click slot is structurally too late to block the menu (the menu is
        # raised during item dispatch, before sigMouseClicked fires) — the menu's
        # real gate is menuEnabled(). Lesson: sigmouseclicked-fires-after-viewbox-menu.
        self._plot_amp.vb.setMenuEnabled(not self._remark_enabled)
        self._plot_time.vb.setMenuEnabled(not self._remark_enabled)

    def clear_remarks(self) -> None:
        for r in self._remarks:
            # Aux overlay annotations live on an aux ViewBox, not on the plot
            # directly, so remove from the stored owner — vb if recorded
            # (aux curves), else the plot (amp row / main time curve).
            owner = r.get('vb') or r.get('plot')
            try:
                owner.removeItem(r['label'])
                owner.removeItem(r['dot'])
            except Exception:
                pass
        self._remarks = []

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
                best = (dy, sx, sy)
        if best is None:
            return
        _dy, sx, sy = best
        label = pg.TextItem(f"({sx:.2f}, {sy:.4g})", color='#111827',
                            fill=pg.mkBrush(255, 255, 255, 200), anchor=(0, 1))
        label.setPos(sx, sy)
        dot = pg.ScatterPlotItem([sx], [sy], size=7,
                                 brush=pg.mkBrush('#dc2626'),
                                 pen=pg.mkPen('w', width=1))
        self._plot_amp.addItem(label)
        self._plot_amp.addItem(dot)
        self._remarks.append({'label': label, 'dot': dot, 'plot': self._plot_amp})

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
        best = None  # (dist2, sx, sy, vb, plot_or_none)
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
                    best = (d2, sx, sy, vb, plot)
        if best is None:
            return
        _d2, sx, sy, vb, plot = best
        label = pg.TextItem(f"({sx:.3g}, {sy:.4g})", color='#111827',
                            fill=pg.mkBrush(255, 255, 255, 200), anchor=(0, 1))
        label.setPos(sx, sy)
        dot = pg.ScatterPlotItem([sx], [sy], size=7,
                                 brush=pg.mkBrush('#dc2626'),
                                 pen=pg.mkPen('w', width=1))
        owner = plot if plot is not None else vb
        owner.addItem(label)
        owner.addItem(dot)
        self._remarks.append({'label': label, 'dot': dot,
                              'plot': plot, 'vb': vb})

    def remove_remark_near(self, which: str, x: float) -> None:
        if which == 'time':
            time_vbs = {self._plot_time.vb, *self._time_overlay_vbs}
            cands = [r for r in self._remarks if r.get('vb') in time_vbs]
            if not cands:
                return
            nearest = min(cands, key=lambda r: abs(r['dot'].getData()[0][0] - x))
            owner = nearest.get('vb') or nearest.get('plot')
            owner.removeItem(nearest['label'])
            owner.removeItem(nearest['dot'])
            self._remarks.remove(nearest)
            return
        if which != 'amp':
            return
        cands = [r for r in self._remarks if r['plot'] is self._plot_amp]
        if not cands:
            return
        nearest = min(cands, key=lambda r: abs(r['dot'].getData()[0][0] - x))
        self._plot_amp.removeItem(nearest['label'])
        self._plot_amp.removeItem(nearest['dot'])
        self._remarks.remove(nearest)

    def _on_click(self, ev) -> None:
        scene_pos = ev.scenePos()
        # Spectrum (amp) row.
        if self._plot_amp.vb.sceneBoundingRect().contains(scene_pos):
            v = self._plot_amp.vb.mapSceneToView(scene_pos)
            if ev.button() == Qt.LeftButton:
                if self._remark_enabled:
                    self.add_remark_at('amp', v.x(), v.y())
                else:
                    idx = self._nearest_entry_index(v.x(), v.y())
                    if idx is not None:
                        self.select_time_entry(idx)
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
