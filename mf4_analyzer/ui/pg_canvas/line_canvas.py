"""PgLineCanvas: dual-row (amplitude + PSD) spectrum canvas.

Replaces the inline matplotlib plotting in MainWindow.do_fft
(main_window.py:2293-2354). One canvas, N overlay curves per row;
legend names follow "file · channel". Cursor + snap-remark parity with
PlotCanvas.store_line_data/_add_remark.
NO OpenGL (breaks grab_pixmap exports, see time-domain history).
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QVBoxLayout, QWidget

from .heatmap_canvas import _tick_counts_to_density


class _AxisShim:
    """Minimal axis handle exposing ``view_box`` for ``PgNavigationToolbar``.

    The toolbar's ``_view_boxes`` walks ``canvas.axes_list`` and reads
    ``ax.view_box`` to apply pan/box-zoom modes. PgLineCanvas has two fixed
    PlotItems (amp + psd) rather than the dynamic per-channel axes a time
    canvas builds, so a lightweight static shim per plot is enough — it never
    rebuilds, so no replot re-binding is needed.
    """

    __slots__ = ("view_box",)

    def __init__(self, view_box):
        self.view_box = view_box


class PgLineCanvas(QWidget):
    cursor_info = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._glw = pg.GraphicsLayoutWidget(self)
        # White chart surface to match the package baseline
        # (PgHeatmapCanvas / TimeDomainCanvasPG) and the matplotlib
        # CHART_FACE.
        self._glw.setBackground("#ffffff")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._glw)

        self._plot_amp = self._glw.addPlot(row=0, col=0)
        self._plot_psd = self._glw.addPlot(row=1, col=0)
        for p in (self._plot_amp, self._plot_psd):
            p.showGrid(x=True, y=True, alpha=0.25)
            p.addLegend(offset=(8, 8))
        self._plot_psd.setXLink(self._plot_amp)

        # Toolbar contract (PgNavigationToolbar._view_boxes walks axes_list →
        # ax.view_box to apply pan/box-zoom mode). Static shims, one per fixed
        # plot. Without this the FFT toolbar's pan/zoom mode buttons go
        # silently inert on the pg canvas (lesson:
        # 2026-05-28-mpl-event-coupled-tests-survive-renderer-swap M6).
        self.axes_list = [
            _AxisShim(self._plot_amp.vb),
            _AxisShim(self._plot_psd.vb),
        ]

        self._amp_curves = []
        self._psd_curves = []
        self._entries = []      # plotted data for readout/snap
        self._remarks = []
        self._remark_enabled = False
        # Last view applied by plot_spectra; the toolbar Home button restores
        # it (reset_view_to_data_extents).
        self._last_xlim = None
        self._last_yrange = None  # (y_min, y_max) when manual, else None

        self._cursor_amp = pg.InfiniteLine(angle=90, movable=False,
                                           pen=pg.mkPen('#94a3b8', width=1))
        self._cursor_psd = pg.InfiniteLine(angle=90, movable=False,
                                           pen=pg.mkPen('#94a3b8', width=1))
        for line in (self._cursor_amp, self._cursor_psd):
            line.setVisible(False)
        self._plot_amp.addItem(self._cursor_amp)
        self._plot_psd.addItem(self._cursor_psd)

        self._glw.scene().sigMouseMoved.connect(self._on_hover)
        self._glw.scene().sigMouseClicked.connect(self._on_click)

    # ------------------------------------------------------------------
    def plot_spectra(self, entries, *, xlim, amp_label, psd_label, title,
                     y_auto=True, y_min=0.0, y_max=0.0):
        """entries: [{label, color, freq, amp, psd}] — display-space values."""
        for p, curves in ((self._plot_amp, self._amp_curves),
                          (self._plot_psd, self._psd_curves)):
            for c in curves:
                p.removeItem(c)
            curves.clear()
        self.clear_remarks()
        self._entries = list(entries)

        for e in self._entries:
            pen = pg.mkPen(e['color'], width=1.2)
            self._amp_curves.append(
                self._plot_amp.plot(e['freq'], e['amp'], pen=pen, name=e['label']))
            self._psd_curves.append(
                self._plot_psd.plot(e['freq'], e['psd'], pen=pen, name=e['label']))

        self._plot_amp.setTitle(title)
        self._plot_amp.setLabel('left', amp_label)
        self._plot_psd.setLabel('left', psd_label)
        self._plot_psd.setLabel('bottom', 'Frequency (Hz)')
        self._last_xlim = (float(xlim[0]), float(xlim[1]))
        manual_y = (not y_auto) and y_max > y_min
        self._last_yrange = (float(y_min), float(y_max)) if manual_y else None
        for p in (self._plot_amp, self._plot_psd):
            p.setXRange(float(xlim[0]), float(xlim[1]), padding=0)
            if manual_y:
                p.setYRange(float(y_min), float(y_max), padding=0)
            else:
                p.enableAutoRange(axis='y')

    def reset_view_to_data_extents(self) -> None:
        """Toolbar Home helper: restore the view applied by plot_spectra.

        ``PgNavigationToolbar.home`` prefers a canvas
        ``reset_view_to_data_extents`` over its ``axes_list`` autoRange
        fallback; without it the Home button would re-derive the X range from
        ``channel_data`` (which this canvas does not populate) and leave the
        manual FFT xlim. Restores the last plot_spectra X range and either the
        manual Y range or per-row Y autorange. Falls back to pg ``autoRange``
        when nothing has been plotted yet.
        """
        if self._last_xlim is None:
            for p in (self._plot_amp, self._plot_psd):
                p.vb.autoRange()
            return
        for p in (self._plot_amp, self._plot_psd):
            p.setXRange(self._last_xlim[0], self._last_xlim[1], padding=0)
            if self._last_yrange is not None:
                p.setYRange(self._last_yrange[0], self._last_yrange[1],
                            padding=0)
            else:
                p.enableAutoRange(axis='y')

    def full_reset(self) -> None:
        """Clear both rows' curves, remarks, result state and labels.

        File-close contract: ``ChartStack.full_reset_all``
        (chart_stack.py) calls ``full_reset()`` on every canvas, mirroring
        the matplotlib ``PlotCanvas.full_reset`` it replaced. Without this
        method the call AttributeErrors and the FFT canvas keeps a stale
        spectrum after the data is unloaded.
        """
        for p, curves in ((self._plot_amp, self._amp_curves),
                          (self._plot_psd, self._psd_curves)):
            for c in curves:
                p.removeItem(c)
            curves.clear()
        self.clear_remarks()
        self._entries = []
        self._last_xlim = None
        self._last_yrange = None
        self._cursor_amp.setVisible(False)
        self._cursor_psd.setVisible(False)
        self._plot_amp.setTitle(None)
        for p in (self._plot_amp, self._plot_psd):
            p.setLabel('left', '')
            p.enableAutoRange(axis='y')
        self._plot_psd.setLabel('bottom', '')
        self.cursor_info.emit("")

    def has_result(self) -> bool:
        return bool(self._entries)

    def set_tick_density(self, x, y) -> None:
        """Apply inspector tick density.

        ``x``/``y`` are approximate tick COUNTS from
        ``inspector.top.tick_density()`` (spinboxes: x 3-30 default 10,
        y 3-20 default 8) — the same integers the mpl canvases fed into
        ``MaxNLocator(nbins=...)`` — NOT pg density factors. They are
        converted via the shared ``_tick_counts_to_density`` and applied
        to both rows' axes with pg-native ``AxisItem.setTickDensity``,
        mirroring PgHeatmapCanvas.set_tick_density.
        """
        try:
            x_n = max(3, int(x))
            y_n = max(3, int(y))
        except (TypeError, ValueError):
            return
        x_d, y_d = _tick_counts_to_density(x_n, y_n)
        for plot in (self._plot_amp, self._plot_psd):
            for axis, density in ((plot.getAxis('bottom'), x_d),
                                  (plot.getAxis('left'), y_d)):
                axis.setStyle(maxTickLevel=0)
                axis.setTickDensity(density)

    # ------------------------------------------------------------------
    def readout_at(self, freq: float):
        """[(label, snapped_freq, amp_value, psd_value)] per curve at ``freq``."""
        rows = []
        for e in self._entries:
            idx = int(np.argmin(np.abs(np.asarray(e['freq']) - freq)))
            rows.append((e['label'], float(e['freq'][idx]),
                         float(e['amp'][idx]), float(e['psd'][idx])))
        return rows

    def _on_hover(self, pos) -> None:
        target = None
        # vb rect, NOT p.sceneBoundingRect(): the plot rect includes the
        # axis/title/legend chrome, so hovering an axis label would map to
        # an extrapolated view coordinate (same trap as the heatmap
        # colorbar column, lesson 2026-06-11-colorbaritem-label-axis…).
        for p in (self._plot_amp, self._plot_psd):
            if p.vb.sceneBoundingRect().contains(pos):
                target = p
                break
        if target is None or not self._entries:
            for line in (self._cursor_amp, self._cursor_psd):
                line.setVisible(False)
            self.cursor_info.emit("")
            return
        x = target.vb.mapSceneToView(pos).x()
        for line in (self._cursor_amp, self._cursor_psd):
            line.setPos(x)
            line.setVisible(True)
        rows = self.readout_at(x)
        text = "  |  ".join(
            f"{label}: {amp:.4g} / {psd:.4g}" for label, _f, amp, psd in rows)
        self.cursor_info.emit(f"f={rows[0][1]:.2f} Hz  {text}")

    # ------------------------------------------------------------------
    # remarks: snap to nearest sample on nearest curve (PlotCanvas parity)
    # ------------------------------------------------------------------
    def set_remark_enabled(self, enabled: bool) -> None:
        self._remark_enabled = bool(enabled)
        # Right-click priority (measured, pg 0.14.0): ViewBox.mouseClickEvent
        # raises the context menu BEFORE GraphicsScene emits sigMouseClicked,
        # so ev.accept() in _on_click cannot stop the popup. Gate the menu on
        # remark mode instead (lesson:
        # 2026-06-11-sigmouseclicked-fires-after-viewbox-menu).
        for p in (self._plot_amp, self._plot_psd):
            p.vb.setMenuEnabled(not self._remark_enabled)

    def clear_remarks(self) -> None:
        for r in self._remarks:
            r['plot'].removeItem(r['label'])
            r['plot'].removeItem(r['dot'])
        self._remarks = []

    def add_remark_at(self, which: str, x: float, y: float) -> None:
        if not self._remark_enabled or not self._entries:
            return
        plot = self._plot_amp if which == 'amp' else self._plot_psd
        key = 'amp' if which == 'amp' else 'psd'
        best = None  # (dy, snapped_x, snapped_y)
        for e in self._entries:
            idx = int(np.argmin(np.abs(np.asarray(e['freq']) - x)))
            sx, sy = float(e['freq'][idx]), float(e[key][idx])
            dy = abs(sy - y)
            if best is None or dy < best[0]:
                best = (dy, sx, sy)
        _dy, sx, sy = best
        label = pg.TextItem(f"({sx:.2f}, {sy:.4g})", color='#111827',
                            fill=pg.mkBrush(255, 255, 255, 200), anchor=(0, 1))
        label.setPos(sx, sy)
        # DANGER token red — matches the time-domain annotation dots
        # (pg_canvas/annotations.py) and PgHeatmapCanvas remark dots.
        dot = pg.ScatterPlotItem([sx], [sy], size=7,
                                 brush=pg.mkBrush('#dc2626'),
                                 pen=pg.mkPen('w', width=1))
        plot.addItem(label)
        plot.addItem(dot)
        self._remarks.append({'label': label, 'dot': dot, 'plot': plot})

    def remove_remark_near(self, which: str, x: float) -> None:
        plot = self._plot_amp if which == 'amp' else self._plot_psd
        cands = [r for r in self._remarks if r['plot'] is plot]
        if not cands:
            return
        nearest = min(cands, key=lambda r: abs(r['dot'].getData()[0][0] - x))
        plot.removeItem(nearest['label'])
        plot.removeItem(nearest['dot'])
        self._remarks.remove(nearest)

    def _on_click(self, ev) -> None:
        # vb rect, NOT p.sceneBoundingRect() — see _on_hover. With the
        # plot rect, a left-click on the axis gutter added a remark at an
        # extrapolated coordinate and a right-click deleted the nearest
        # remark with no distance gate.
        for which, p in (('amp', self._plot_amp), ('psd', self._plot_psd)):
            if p.vb.sceneBoundingRect().contains(ev.scenePos()):
                v = p.vb.mapSceneToView(ev.scenePos())
                if ev.button() == Qt.LeftButton:
                    self.add_remark_at(which, v.x(), v.y())
                elif ev.button() == Qt.RightButton and self._remark_enabled:
                    self.remove_remark_near(which, v.x())
                    ev.accept()
                return

    # ------------------------------------------------------------------
    def grab_pixmap(self, scale: float = 2.0) -> QPixmap:
        """Snapshot of the canvas for copy/export.

        Uses ``QWidget.grab()`` + smooth magnification rather than
        ``QWidget.render(QPainter)`` with a scale transform: a scaled
        render() clips to the widget rect in device pixels, exporting
        only the top-left quadrant at 2x (verified offscreen, Qt
        5.15.14). grab() is also the realizability probe (lesson
        2026-04-25-tightbbox-survives-offscreen-qt); pattern mirrors
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
