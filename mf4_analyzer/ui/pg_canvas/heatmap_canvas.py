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
from PyQt5.QtCore import QRectF, pyqtSignal
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


class _DensityAxis(pg.AxisItem):
    """AxisItem whose tick density scales with the global chart option.

    pg has no MaxNLocator equivalent; scaling the *size* argument that
    tickSpacing sees makes pg believe there is more/less room, which
    yields proportionally more/fewer major ticks.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._density = 1.0

    def set_density(self, density: float) -> None:
        self._density = max(0.2, min(5.0, float(density)))
        self.picture = None
        self.update()

    def tickSpacing(self, minVal, maxVal, size):
        return super().tickSpacing(minVal, maxVal, size * self._density)


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

        self._axis_bottom = _DensityAxis('bottom')
        self._axis_left = _DensityAxis('left')
        self._plot = self._glw.addPlot(
            row=0, col=0,
            axisItems={'bottom': self._axis_bottom, 'left': self._axis_left},
        )
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

    # ------------------------------------------------------------------
    # main API (signature mirrors canvases.PlotCanvas.plot_or_update_heatmap)
    # ------------------------------------------------------------------
    def plot_or_update_heatmap(
        self, matrix, x_extent, y_extent, *,
        x_label='', y_label='', title='', cmap='turbo', interp=None,
        cbar_label='Amplitude', amplitude_mode='amplitude',
        z_auto=False, z_floor=-30.0, z_ceiling=0.0,
        x_auto=True, x_min=0.0, x_max=0.0,
        y_auto=True, y_min=0.0, y_max=0.0,
        vmin=None, vmax=None,
    ):
        # ``interp`` accepted for call-site parity; pg ImageItem rendering
        # is already smooth-scaled, no per-call interpolation knob.
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

        self._matrix_disp = m
        self._extents = (x0, x1, y0, y1)
        self._has_result = True

    def has_result(self) -> bool:
        return self._has_result

    def set_tick_density(self, x_density, y_density) -> None:
        self._axis_bottom.set_density(float(x_density))
        self._axis_left.set_density(float(y_density))

    # ------------------------------------------------------------------
    def _on_cbar_levels(self, bar) -> None:
        lo, hi = bar.levels()
        self.levels_changed.emit(float(lo), float(hi))
