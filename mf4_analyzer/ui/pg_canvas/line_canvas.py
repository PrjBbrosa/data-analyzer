"""PgLineCanvas: FFT amplitude overlay plus selected-source time preview.

Replaces the inline matplotlib plotting in MainWindow.do_fft. The top row
draws N overlaid FFT amplitude curves; the bottom row shows the original
time-domain trace for the selected spectrum source. NO OpenGL: it breaks
grab_pixmap exports on this project.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QVBoxLayout, QWidget

from .heatmap_canvas import _apply_neutral_axis_frame, _tick_counts_to_density


class _AxisShim:
    """Minimal axis handle exposing ``view_box`` for ``PgNavigationToolbar``."""

    __slots__ = ("view_box",)

    def __init__(self, view_box):
        self.view_box = view_box


class PgLineCanvas(QWidget):
    cursor_info = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._glw = pg.GraphicsLayoutWidget(self)
        self._glw.setBackground("#ffffff")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._glw)

        self._plot_amp = self._glw.addPlot(row=0, col=0)
        self._plot_time = self._glw.addPlot(row=1, col=0)
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

        self._cursor_amp = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen('#94a3b8', width=1))
        self._cursor_amp.setVisible(False)
        self._plot_amp.addItem(self._cursor_amp)

        self._glw.scene().sigMouseMoved.connect(self._on_hover)
        self._glw.scene().sigMouseClicked.connect(self._on_click)

    # ------------------------------------------------------------------
    def plot_spectra(self, entries, *, xlim, amp_label, title,
                     y_auto=True, y_min=0.0, y_max=0.0):
        """Plot FFT curves and seed the lower time preview.

        ``entries`` are dictionaries with display-space ``freq``/``amp`` and
        optional raw ``time``/``signal`` arrays for the preview row.
        """
        for p, curves in ((self._plot_amp, self._amp_curves),
                          (self._plot_time, self._time_curves)):
            for c in curves:
                p.removeItem(c)
            curves.clear()
        self.clear_remarks()
        self._entries = list(entries)

        for e in self._entries:
            pen = pg.mkPen(e.get('color', '#2563eb'), width=1.2)
            self._amp_curves.append(
                self._plot_amp.plot(
                    e['freq'], e['amp'], pen=pen, name=e['label'],
                    antialias=True))

        self._plot_amp.setTitle(title)
        self._plot_amp.setLabel('left', amp_label)
        self._plot_amp.setLabel('bottom', 'Frequency (Hz)')
        self._plot_time.setLabel('left', 'Amplitude')
        self._plot_time.setLabel('bottom', 'Time (s)')
        self._last_xlim = (float(xlim[0]), float(xlim[1]))
        manual_y = (not y_auto) and y_max > y_min
        self._last_yrange = (float(y_min), float(y_max)) if manual_y else None

        self._plot_amp.setXRange(float(xlim[0]), float(xlim[1]), padding=0)
        if manual_y:
            self._plot_amp.setYRange(float(y_min), float(y_max), padding=0)
        else:
            self._plot_amp.enableAutoRange(axis='y')

        self.select_time_entry(0 if self._entries else None)

    def reset_view_to_data_extents(self) -> None:
        if self._last_xlim is None:
            for p in (self._plot_amp, self._plot_time):
                p.vb.autoRange()
            return
        self._plot_amp.setXRange(self._last_xlim[0], self._last_xlim[1], padding=0)
        if self._last_yrange is not None:
            self._plot_amp.setYRange(
                self._last_yrange[0], self._last_yrange[1], padding=0)
        else:
            self._plot_amp.enableAutoRange(axis='y')
        self.select_time_entry(self._selected_time_entry_idx)

    def full_reset(self) -> None:
        for p, curves in ((self._plot_amp, self._amp_curves),
                          (self._plot_time, self._time_curves)):
            for c in curves:
                p.removeItem(c)
            curves.clear()
        self.clear_remarks()
        self._entries = []
        self._selected_time_entry_idx = None
        self._last_xlim = None
        self._last_yrange = None
        self._cursor_amp.setVisible(False)
        self._plot_amp.setTitle(None)
        self._plot_time.setTitle(None)
        for p in (self._plot_amp, self._plot_time):
            p.setLabel('left', '')
            p.setLabel('bottom', '')
            p.enableAutoRange(axis='y')
        self.cursor_info.emit("")

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

    # ------------------------------------------------------------------
    def select_time_entry(self, idx) -> None:
        for c in self._time_curves:
            self._plot_time.removeItem(c)
        self._time_curves.clear()
        if idx is None or not self._entries:
            self._selected_time_entry_idx = None
            self._plot_time.setTitle("时域")
            return
        idx = int(np.clip(int(idx), 0, len(self._entries) - 1))
        e = self._entries[idx]
        t = np.asarray(e.get('time', []), dtype=float)
        sig = np.asarray(e.get('signal', []), dtype=float)
        self._selected_time_entry_idx = idx
        self._plot_time.setTitle(f"时域 - {e['label']}")
        if t.size == 0 or sig.size == 0:
            self._plot_time.enableAutoRange()
            return
        n = min(t.size, sig.size)
        pen = pg.mkPen(e.get('color', '#2563eb'), width=1.1)
        self._time_curves.append(
            self._plot_time.plot(t[:n], sig[:n], pen=pen, antialias=True))
        if n == 1:
            self._plot_time.setXRange(float(t[0]) - 0.5, float(t[0]) + 0.5,
                                      padding=0)
        else:
            self._plot_time.setXRange(float(t[0]), float(t[n - 1]), padding=0)
        self._plot_time.enableAutoRange(axis='y')

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
            self._cursor_amp.setVisible(False)
            self.cursor_info.emit("")
            return
        x = self._plot_amp.vb.mapSceneToView(pos).x()
        self._cursor_amp.setPos(x)
        self._cursor_amp.setVisible(True)
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
