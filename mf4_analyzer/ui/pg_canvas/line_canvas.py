"""PgLineCanvas: FFT amplitude overlay plus FFT-source time preview.

The top row draws overlaid FFT amplitude curves after computation. The lower
row shows the time-domain input sources immediately when they are selected,
and remains an overlay when multiple FFT sources are active. NO OpenGL: it
breaks grab_pixmap exports on this project.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QPointF, Qt, pyqtSignal
from PyQt5.QtGui import QFontMetricsF, QPixmap
from PyQt5.QtWidgets import QVBoxLayout, QWidget

from mf4_analyzer.ui.canvases import build_envelope

from .heatmap_canvas import (
    _apply_neutral_axis_frame,
    _tick_counts_to_density,
    _visual_padded_bounds,
)
from .context_menu import redesign_pg_context_menu
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


class _AxisShim:
    """Minimal axis handle exposing ``view_box`` for ``PgNavigationToolbar``."""

    __slots__ = ("view_box",)

    def __init__(self, view_box):
        self.view_box = view_box


class PgLineCanvas(QWidget):
    cursor_info = pyqtSignal(str)
    context_menu_requested = pyqtSignal()
    layout_geometry_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._glw = pg.GraphicsLayoutWidget(self)
        self._glw.setBackground("#ffffff")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._glw)

        self._plot_amp = self._glw.addPlot(
            row=0, col=0,
            viewBox=_ModifierWheelViewBox(owner_canvas=self),
        )
        self._plot_time = self._glw.addPlot(
            row=1, col=0,
            viewBox=_ModifierWheelViewBox(owner_canvas=self),
        )
        for p in (self._plot_amp, self._plot_time):
            _apply_neutral_axis_frame(p)
            p.showGrid(x=True, y=True, alpha=0.25)
        self._plot_amp.addLegend(offset=(8, 8))
        self._plot_time.setMaximumHeight(170)

        self.axes_list = [
            _AxisShim(self._plot_amp.vb),
            _AxisShim(self._plot_time.vb),
        ]

        self._amp_curves = []
        self._time_curves = []
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

        self._glw.scene().sigMouseMoved.connect(self._on_hover)
        self._glw.scene().sigMouseClicked.connect(self._on_click)

    def register_mouse_mode_controller(self, controller) -> None:
        self._mouse_mode_controller = controller

    def _plot_item_for_view_box(self, view_box):
        for plot in (self._plot_amp, self._plot_time):
            if plot.vb is view_box:
                return plot
        return self._plot_amp

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
            pen = pg.mkPen(e.get('color', '#2563eb'), width=1.2)
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
            self._plot_amp.setLabel('left', '')
            self._plot_amp.setLabel('bottom', '')
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

    def _reset_time_preview_to_extents(self) -> None:
        bounds = self._combined_time_bounds()
        if bounds is None:
            return
        tx0, tx1 = _visual_padded_bounds(bounds[0], bounds[1])
        self._plot_time.setXRange(tx0, tx1, padding=0)
        self._plot_time.enableAutoRange(axis='y')

    def full_reset(self) -> None:
        for p, curves in ((self._plot_amp, self._amp_curves),
                          (self._plot_time, self._time_curves)):
            for c in curves:
                p.removeItem(c)
            curves.clear()
        self.clear_remarks()
        self._clear_spectrum_stale()
        self._entries = []
        self._selected_time_entry_idx = None
        self._last_xlim = None
        self._last_yrange = None
        self._raw_amp_title = ''
        self._raw_time_title = ''
        self._apply_title_texts()
        for p in (self._plot_amp, self._plot_time):
            p.setLabel('left', '')
            p.setLabel('bottom', '')
            p.enableAutoRange(axis='y')
        self.cursor_info.emit("")
        self.layout_geometry_changed.emit()

    def has_result(self) -> bool:
        return bool(self._entries)

    def set_tick_density(self, x, y) -> None:
        try:
            x_n = max(3, int(x))
            y_n = max(3, int(y))
        except (TypeError, ValueError):
            return
        x_d, y_d = _tick_counts_to_density(x_n, y_n)
        for plot in (self._plot_amp, self._plot_time):
            for axis, density in ((plot.getAxis('bottom'), x_d),
                                  (plot.getAxis('left'), y_d)):
                axis.setStyle(maxTickLevel=0)
                axis.setTickDensity(density)
        self.layout_geometry_changed.emit()

    # ------------------------------------------------------------------
    def select_time_entry(self, idx) -> None:
        self._plot_time_preview_entries(self._entries, selected_idx=idx,
                                        title="时域预览")

    def _plot_time_preview_entries(self, entries, selected_idx=None,
                                   title="时域预览") -> None:
        for c in self._time_curves:
            self._plot_time.removeItem(c)
        self._time_curves.clear()
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
            width = 1.7 if i == self._selected_time_entry_idx else 1.1
            pen = pg.mkPen(e.get('color', '#2563eb'), width=width)
            self._time_curves.append(
                self._plot_time.plot(t_env, sig_env, pen=pen,
                                     antialias=antialias))
            x_bounds.append((float(t[0]), float(t[-1])))
        if x_bounds:
            lo = min(a for a, _b in x_bounds)
            hi = max(b for _a, b in x_bounds)
            if hi > lo:
                self._plot_time.setXRange(lo, hi, padding=0)
            else:
                self._plot_time.setXRange(lo - 0.5, hi + 0.5, padding=0)
        self._plot_time.enableAutoRange(axis='y')
        self.layout_geometry_changed.emit()

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
            try:
                plot.showAxis('right', False)
                axis.setWidth(None)
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
        title = title or ''
        width = self._split_title_width
        label = plot.titleLabel
        if width is None or not title:
            try:
                label.setMinimumWidth(0)
                label.setMaximumWidth(1000000)
            except Exception:
                pass
            plot.setTitle(title)
            return
        try:
            fm = QFontMetricsF(label.item.font())
            title = fm.elidedText(title, Qt.ElideMiddle, int(round(width)))
        except Exception:
            pass
        plot.setTitle(title)
        try:
            label.setMinimumWidth(0)
            label.setMaximumWidth(float(width))
            label.setPreferredWidth(float(width))
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
        self._plot_amp.vb.setMenuEnabled(not self._remark_enabled)
        self._plot_time.vb.setMenuEnabled(True)

    def clear_remarks(self) -> None:
        for r in self._remarks:
            r['plot'].removeItem(r['label'])
            r['plot'].removeItem(r['dot'])
        self._remarks = []

    def add_remark_at(self, which: str, x: float, y: float) -> None:
        if which != 'amp' or not self._remark_enabled or not self._entries:
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

    def remove_remark_near(self, which: str, x: float) -> None:
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
        if not self._plot_amp.vb.sceneBoundingRect().contains(ev.scenePos()):
            return
        v = self._plot_amp.vb.mapSceneToView(ev.scenePos())
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
