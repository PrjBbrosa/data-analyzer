"""The heatmap canvas's 1D slice strip and its X/Y direction toggle.

Split out of ``heatmap_canvas.py``, where roughly 400 lines of slice behaviour
sat interleaved with the 2D map's own render, colorbar and remark paths, each
consumer guarded on ``self._slice_curve is not None``. Every "slice" change
landed in the canvas's largest file.

``PgHeatmapCanvas`` still owns the state and still exposes every slice method
it always did -- those are one-line delegates to ``self._slice`` now. What
lives here is the behaviour:

* ``_SliceDirToggle`` -- the two-segment 按X/按Y switch in the info panel;
* ``_SliceStrip`` -- seeding, direction, index clamping, curve + marker
  rendering, drag-to-reslice, the readout text, and the geometry that keeps
  the strip's right edge aligned with the map above it.

``_SliceStrip`` is a ``_CanvasBackref``, so ``self._slice_x_idx``,
``self._matrix_disp``, ``self._time_index_for(...)`` and ``self.slice_picked``
all still mean the CANVAS's -- reads and writes forward. That is deliberate:
tests and ``ui/main_window/_order_mixin.py`` read ``canvas._slice_*`` directly,
and keeping the fields there let this code move without a single body edit.

dB-domain amplitude bounds are NOT re-implemented here: ``_slice_amp_bounds``
and ``_SLICE_MAX_SPAN_DB`` live in the neutral ``qt_analysis_shared`` layer and
reach this module via ``analysis_axes``.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QPushButton, QWidget

from mf4_analyzer.ui._axis_handle import (
    PG_AXIS_NEUTRAL_COLOR,
    PG_AXIS_NEUTRAL_WIDTH,
)
from mf4_analyzer.ui.pg_canvas._backref import _CanvasBackref
from mf4_analyzer.ui.pg_canvas.analysis_axes import (
    _hide_plot_title,
    _slice_amp_bounds,
)


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


class _SliceStrip(_CanvasBackref):
    """The heatmap's 1D slice strip: direction, index, curve, marker,
    info panel and the geometry that keeps it aligned to the map above.

    Every ``_slice_*`` field stays on the CANVAS -- ``_CanvasBackref``
    forwards reads and writes -- because tests and ``ui/main_window`` read
    ``canvas._slice_plot`` / ``._slice_dir`` / ``._slice_x_idx`` directly.
    The same forwarding is what lets these method bodies stay byte-for-byte
    what they were on ``PgHeatmapCanvas``: ``self._matrix_disp``,
    ``self._time_index_for(...)``, ``self.slice_picked`` and the rest still
    resolve to the canvas.
    """

    def _apply_slice_curve_aa_state(self) -> None:
        if self._slice_curve is None:
            return
        self._set_curve_aa(self._slice_curve, self._slice_aa_on)
        try:
            self._glw.update()
        except Exception:
            pass

    def _reset_slice_quality_for_rebuild(self) -> None:
        try:
            self._slice_aa_idle_timer.stop()
        except Exception:
            pass
        self._slice_aa_on = True
        self._apply_slice_curve_aa_state()

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
        """Position the slice and render it.

        On the FIRST render (no prior position) the slice lands at the matrix
        centre. On a RE-render it maps the previous cursor position back by
        COORDINATE value (time / frequency) to the nearest index, so changing
        an inspector knob and re-rendering does not snap the slice to the
        middle — it stays where the user put it (parity with a colorbar drag
        leaving the matrix intact)."""
        m = self._matrix_disp
        if m is None or self._slice_curve is None:
            return
        nrows, ncols = m.shape[0], m.shape[1]
        xc, yc = self._slice_coords()
        if self._slice_x_val is not None and xc is not None and len(xc):
            self._slice_x_idx = int(np.argmin(np.abs(np.asarray(xc) - self._slice_x_val)))
        else:
            self._slice_x_idx = ncols // 2
        if self._slice_y_val is not None and yc is not None and len(yc):
            self._slice_y_idx = int(np.argmin(np.abs(np.asarray(yc) - self._slice_y_val)))
        else:
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

    @staticmethod
    def _slice_visible_mask(coords, lo: float, hi: float):
        """Mask coordinate centers inside a visible range, with nearest fallback."""
        arr = np.asarray(coords, dtype=float)
        finite = np.isfinite(arr)
        if arr.size == 0:
            return finite
        lo, hi = sorted((float(lo), float(hi)))
        mask = finite & (arr >= lo) & (arr <= hi)
        if np.any(mask):
            return mask
        valid = np.flatnonzero(finite)
        if valid.size == 0:
            return mask
        target = (lo + hi) / 2.0
        nearest = valid[int(np.argmin(np.abs(arr[valid] - target)))]
        mask = np.zeros(arr.shape, dtype=bool)
        mask[nearest] = True
        return mask

    def _set_slice_x_range(self, lo: float, hi: float, values) -> None:
        if self._slice_plot is None:
            return
        lo, hi = sorted((float(lo), float(hi)))
        if hi > lo:
            self._slice_plot.setXRange(lo, hi, padding=0)
            return
        arr = np.asarray(values, dtype=float)
        finite = arr[np.isfinite(arr)]
        if finite.size:
            center = float(finite[0])
            pad = max(abs(center) * 0.01, 0.5)
            self._slice_plot.setXRange(center - pad, center + pad, padding=0)

    def _slice_axis_range(self, panel_range, view_axis: str, coords):
        """Range for the slice's horizontal axis.

        Prefer the inspector-driven ``panel_range`` (manual min/max) so the
        slice axis tracks the panel rather than the live heatmap pan/zoom.
        When the panel axis is auto (``panel_range is None``) fall back to the
        live heatmap view range, then to the data extent."""
        if panel_range is not None:
            lo, hi = float(panel_range[0]), float(panel_range[1])
            if hi != lo:
                return sorted((lo, hi))
        vr = self._main_view_range(view_axis)
        if vr is None:
            arr = np.asarray(coords, dtype=float)
            return float(arr[0]), float(arr[-1])
        return vr

    def _apply_slice_amp_range(self, values) -> None:
        """Set the slice's amplitude (vertical) axis.

        Manual z (``_panel_amp_range`` set) clamps the amplitude axis to
        ``[z_floor, z_ceiling]`` — the same window as the colorbar so the
        slice and image share one amplitude caliber. Auto z
        (``_panel_amp_range is None``) enables pyqtgraph auto-fit on the
        already freq/time-range-clipped curve data."""
        if self._slice_plot is None:
            return
        vb = self._slice_plot.vb
        rng = self._panel_amp_range
        if rng is not None:
            lo, hi = sorted((float(rng[0]), float(rng[1])))
            if hi > lo:
                vb.enableAutoRange(axis=vb.YAxis, enable=False)
                self._slice_plot.setYRange(lo, hi, padding=0)
                return
        # Auto: fit the visible curve data, ignoring numerically-dead dB-floor
        # bins (the 0 Hz DC artifact) so they can't crush the real signal
        # against the top (fall back to pg auto-range when there is no spread).
        bounds = _slice_amp_bounds(values)
        if bounds is not None:
            lo, hi = bounds
            pad = (hi - lo) * 0.05
            vb.enableAutoRange(axis=vb.YAxis, enable=False)
            self._slice_plot.setYRange(lo - pad, hi + pad, padding=0)
            return
        vb.enableAutoRange(axis=vb.YAxis, enable=True)

    def _apply_slice(self) -> None:
        """Render the slice curve + marker for the current direction/index."""
        m = self._matrix_disp
        if m is None or self._slice_curve is None:
            return
        xc, yc = self._slice_coords()
        if xc is None:
            return
        nrows, ncols = m.shape[0], m.shape[1]
        amp_label = self._current_amplitude_axis_label()
        if self._slice_dir == 'y':
            # Fix a Y position (frequency / order) → curve = amplitude vs time.
            # Horizontal axis is TIME → panel x_* range (when manual).
            idx = int(np.clip(self._slice_y_idx, 0, max(0, nrows - 1)))
            self._slice_y_idx = idx
            self._slice_y_val = float(yc[idx])
            lo, hi = self._slice_axis_range(self._panel_time_range, 'x', xc)
            mask = self._slice_visible_mask(xc, lo, hi)
            self._slice_curve.setData(xc[mask], m[idx, :][mask])
            self._set_slice_x_range(lo, hi, xc[mask])
            self._slice_plot.setLabel('bottom', self._x_label or 'Time (s)')
            self._apply_slice_amp_range(m[idx, :][mask])
            self._slice_marker_updating = True
            try:
                self._slice_marker.setAngle(0)
                self._slice_marker.setValue(float(yc[idx]))
            finally:
                self._slice_marker_updating = False
            fixed_val, fixed_lbl = float(yc[idx]), self._y_label
        else:
            # Fix a time → curve = amplitude vs Y (frequency / order).
            # Horizontal axis is FREQUENCY/ORDER → panel freq_range (when manual).
            idx = int(np.clip(self._slice_x_idx, 0, max(0, ncols - 1)))
            self._slice_x_idx = idx
            self._slice_x_val = float(xc[idx])
            lo, hi = self._slice_axis_range(self._panel_freq_range, 'y', yc)
            mask = self._slice_visible_mask(yc, lo, hi)
            self._slice_curve.setData(yc[mask], m[:, idx][mask])
            self._set_slice_x_range(lo, hi, yc[mask])
            self._slice_plot.setLabel('bottom', self._y_label or 'Frequency (Hz)')
            self._apply_slice_amp_range(m[:, idx][mask])
            self._slice_marker_updating = True
            try:
                self._slice_marker.setAngle(90)
                self._slice_marker.setValue(float(xc[idx]))
            finally:
                self._slice_marker_updating = False
            fixed_val, fixed_lbl = float(xc[idx]), self._x_label
        self._apply_slice_curve_aa_state()
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
        if self._slice_marker_updating:
            return
        if self._matrix_disp is None or self._slice_curve is None:
            return
        xc, yc = self._slice_coords()
        if xc is None:
            return
        try:
            pos = float(self._slice_marker.value())
        except Exception:
            return
        self.disable_interactive_quality()
        if self._slice_dir == 'y':
            self._slice_y_idx = int(np.argmin(np.abs(yc - pos)))
        else:
            self._slice_x_idx = int(np.argmin(np.abs(xc - pos)))
        self._apply_slice()
        self.schedule_idle_quality()

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
            self.slice_hint_requested.emit("先点计算生成谱图")
            return
        x0, x1, y0, y1 = self._extents
        if self._slice_dir == 'y':
            if not (y0 <= y <= y1):
                self.slice_hint_requested.emit("点击位置超出谱图范围")
                return
            self._slice_y_idx = self._freq_index_for(y)
            self._apply_slice()
            self.slice_picked.emit()
        else:
            if not (x0 <= x <= x1):
                self.slice_hint_requested.emit("点击位置超出谱图范围")
                return
            self._slice_x_idx = self._time_index_for(x)
            self._apply_slice()
            self.slice_picked.emit()

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


__all__ = ["_SliceDirToggle", "_SliceStrip"]
