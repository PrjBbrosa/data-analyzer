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

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QVBoxLayout, QWidget


def _resolve_colormap(name: str) -> pg.ColorMap:
    """Map the inspector's matplotlib cmap names to pg ColorMaps.

    matplotlib stays a dependency (batch.py), so getFromMatplotlib gives
    exact color parity with the old canvases.
    """
    try:
        return pg.colormap.getFromMatplotlib(name)
    except Exception:
        return pg.colormap.get('viridis')


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


class PgHeatmapCanvas(QWidget):
    cursor_info = pyqtSignal(str)
    # Emitted when the user drags the interactive colorbar (lo, hi).
    levels_changed = pyqtSignal(float, float)

    def __init__(self, parent=None, with_slice: bool = False):
        super().__init__(parent)
        self._with_slice = bool(with_slice)
        self._glw = pg.GraphicsLayoutWidget(self)
        # White chart surface to match the package baseline
        # (TimeDomainCanvasPG, canvas.py:198) and the matplotlib
        # CHART_FACE; full style parity is arbitrated in the P1 visual
        # acceptance task.
        self._glw.setBackground("#ffffff")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._glw)

        self._plot = self._glw.addPlot(row=0, col=0)
        self._axis_bottom = self._plot.getAxis('bottom')
        self._axis_left = self._plot.getAxis('left')
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        self._img = pg.ImageItem()
        # row-major: matrix[row, col] -> row = Y (origin at rect bottom,
        # matching imshow origin='lower'), col = X.
        self._img.setOpts(axisOrder='row-major')
        self._plot.addItem(self._img)

        self._cbar = None
        self._has_result = False
        self._matrix_disp = None  # display-space matrix
        self._extents = None      # (x0, x1, y0, y1)
        self._remarks = []
        self._remark_enabled = False
        # remarks: card contract is set_remark_enabled / clear_remarks
        # (chart_stack.py:1314, 1330-1332).
        self._plot.scene().sigMouseClicked.connect(self._on_scene_click)

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
    ):
        # ``interp`` accepted for call-site parity but currently ignored:
        # pg ImageItem.paint is a raw drawImage (no smoothing knob), so
        # any visual difference vs mpl 'bilinear' is arbitrated by the
        # P1 visual acceptance gate (M6).
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

        if self._cbar is None:
            self._cbar = pg.ColorBarItem(
                colorMap=cm, interactive=True, label=cbar_label,
            )
            self._cbar.setImageItem(self._img, insert_in=self._plot)
            self._cbar.sigLevelsChanged.connect(self._on_cbar_levels)
        else:
            self._cbar.setColorMap(cm)
            # Vertical ColorBarItem places its ``label=`` on the LEFT axis
            # at __init__ (pg 0.14.0 source: getAxis('left').setLabel) —
            # the right axis carries the tick values. Update the same axis.
            self._cbar.getAxis('left').setLabel(cbar_label)
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

        self._plot.setLabel('bottom', x_label)
        self._plot.setLabel('left', y_label)
        self._plot.setTitle(title)

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

    def has_result(self) -> bool:
        return self._has_result

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
        for axis, density in ((self._axis_bottom, x_d), (self._axis_left, y_d)):
            axis.setStyle(maxTickLevel=0)
            axis.setTickDensity(density)

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
        col = min(int((x - x0) / max(x1 - x0, 1e-12) * cols), cols - 1)
        row = min(int((y - y0) / max(y1 - y0, 1e-12) * rows), rows - 1)
        return float(self._matrix_disp[row, col])

    def _on_scene_click(self, ev) -> None:
        if not self._plot.sceneBoundingRect().contains(ev.scenePos()):
            return
        p = self._plot.vb.mapSceneToView(ev.scenePos())
        if ev.button() == Qt.LeftButton:
            self.add_remark_at(p.x(), p.y())
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
