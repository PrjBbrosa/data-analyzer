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

        # FFT-vs-Time slice row (with_slice=True). The Order map
        # (with_slice=False) never builds these; every consumer of the
        # slice state guards on ``self._slice_curve is not None``.
        self._slice_curve = None
        self._slice_plot = None
        self._slice_marker = None
        self._result = None     # SpectrogramResult-like payload
        # Amplitude mode of the last plot_result render (slice mode only).
        # Parity with SpectrogramCanvas._amplitude_mode (canvases.py:1622):
        # the hover/remark readout labels values 'dB' in dB mode and the
        # channel unit otherwise, and the slice y-label switches with it.
        self._amplitude_mode = 'amplitude_db'
        self._db_cache = None   # (cache_key, ndarray) keyed (id(result), db_ref)
        if self._with_slice:
            # Second GraphicsLayout row: 1D frequency slice at the
            # selected frame (parity with SpectrogramCanvas._ax_slice,
            # canvases.py:1775). Capped height keeps the 2D map dominant.
            self._slice_plot = self._glw.addPlot(row=1, col=0)
            self._slice_plot.setMaximumHeight(140)
            self._slice_plot.showGrid(x=True, y=True, alpha=0.25)
            self._slice_plot.setLabel('bottom', 'Frequency (Hz)')
            # Left (amplitude) axis label. dB vs linear is switched per
            # render in select_time_index, mirroring the mpl original's
            # _plot_slice ylabel (canvases.py:1878-1880); seed the default
            # here so the axis is never unlabeled before the first render.
            self._slice_plot.setLabel('left', 'Amplitude (dB)')
            self._slice_curve = self._slice_plot.plot(
                pen=pg.mkPen('#2563eb', width=1.2))
            # Vertical marker on the 2D map tracking the selected time.
            # movable=False — selection is driven by clicks, not drags.
            self._slice_marker = pg.InfiniteLine(
                angle=90, movable=False, pen=pg.mkPen('#e03131', width=1))
            self._plot.addItem(self._slice_marker)
            self._slice_marker.setVisible(False)
            # Hover readout (t / freq / value) parity with
            # SpectrogramCanvas._on_motion (canvases.py:2000). Only wired
            # in slice mode; the Order map has no hover-readout contract.
            self._plot.scene().sigMouseMoved.connect(self._on_scene_hover)

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
            # colorMapMenu=False suppresses pg's built-in right-click
            # ColorMapMenu on the bar. That menu (verified live: actions
            # None/local/cet/matplotlib under a real right-click) lets the
            # user swap the colormap straight on the bar, desyncing it from
            # the Inspector cmap dropdown — a double source of truth. The
            # host ViewBox's setMenuEnabled(False) does NOT silence it
            # (lesson 2026-06-11-colorbaritem-label-axis-and-silent-setlevels);
            # the bar's own mouseClickEvent short-circuits only when
            # colorMapMenu is False (pg 0.14.0 ColorBarItem.mouseClickEvent).
            self._cbar = pg.ColorBarItem(
                colorMap=cm, interactive=True, label=cbar_label,
                colorMapMenu=False,
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
        self._plot.setTitle(None)
        self._plot.setLabel('bottom', '')
        self._plot.setLabel('left', '')
        self._matrix_disp = None
        self._extents = None
        self._has_result = False
        # FFT-vs-Time slice state. Keep the persistent slice row / curve /
        # marker widgets (built once in __init__) so the GraphicsLayout
        # row is not orphaned; just blank them and drop the result + dB
        # cache so a stale slice never outlives its data.
        self._result = None
        self._db_cache = None
        if self._slice_curve is not None:
            self._slice_curve.clear()
            self._slice_plot.setTitle(None)
            self._slice_marker.setVisible(False)

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
        """
        if self._extents is None:
            self._plot.vb.autoRange()
            return
        x0, x1, y0, y1 = self._extents
        self._plot.setXRange(float(x0), float(x1), padding=0)
        self._plot.setYRange(float(y0), float(y1), padding=0)

    # ------------------------------------------------------------------
    # FFT-vs-Time: spectrogram render + frequency slice (with_slice=True)
    # ------------------------------------------------------------------
    def plot_result(
        self, result, *, amplitude_mode='amplitude_db', cmap='turbo',
        z_auto=False, z_floor=-80.0, z_ceiling=0.0, freq_range=None,
        x_auto=True, x_min=0.0, x_max=0.0,
        y_auto=True, y_min=0.0, y_max=0.0,
    ):
        """Render a ``SpectrogramResult`` as a 2D heatmap + frequency slice.

        Signature mirrors ``SpectrogramCanvas.plot_result``
        (canvases.py:1722) and the ``MainWindow._render_fft_time`` call
        site (main_window.py:2825). ``result.amplitude`` is shape
        ``(freq_bins, frames)`` → rows are frequency (Y), columns are
        time (X).

        dB conversion is done HERE (memoized via ``self._db_cache``,
        keyed ``(id(result), db_reference)`` — parity with
        ``SpectrogramCanvas._display_matrix``), and the already-converted
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
            key = (id(result), db_ref)
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
            z_auto=True, vmin=vmin, vmax=vmax,
            x_auto=x_auto, x_min=x_min, x_max=x_max,
            y_auto=y_auto, y_min=y_min, y_max=y_max,
        )
        # plot_or_update_heatmap stores the matrix it was handed (the
        # display matrix) in self._matrix_disp; re-pin it explicitly so
        # the slice and remarks read the same display-space values.
        self._matrix_disp = m
        if self._slice_curve is not None and len(result.times):
            self.select_time_index(0)

    def select_time_index(self, idx: int) -> None:
        """Update the frequency slice + marker to frame ``idx``.

        Clamps to ``[0, frames-1]``. No-op without a result or slice row.
        """
        if self._result is None or self._slice_curve is None:
            return
        idx = int(np.clip(idx, 0, len(self._result.times) - 1))
        self._slice_curve.setData(
            self._result.frequencies, self._matrix_disp[:, idx])
        # Switch the amplitude-axis label with the mode (mpl _plot_slice,
        # canvases.py:1878-1880). _matrix_disp is dB in dB mode here.
        self._slice_plot.setLabel(
            'left',
            'Amplitude (dB)' if self._amplitude_mode == 'amplitude_db'
            else 'Amplitude',
        )
        t = float(self._result.times[idx])
        self._slice_plot.setTitle(f"t = {t:.3f} s")
        self._slice_marker.setPos(t)
        self._slice_marker.setVisible(True)

    def _time_index_for(self, x: float) -> int:
        """Nearest frame index to a view-space time ``x``."""
        return int(np.argmin(np.abs(np.asarray(self._result.times) - x)))

    def _freq_index_for(self, y: float) -> int:
        """Nearest frequency-bin index to a view-space frequency ``y``."""
        return int(np.argmin(np.abs(np.asarray(self._result.frequencies) - y)))

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
            elif self._slice_curve is not None and self._result is not None:
                # FFT-vs-Time: left-click selects the nearest frame and
                # updates the slice + marker. Guard out-of-extent clicks
                # (the colorbar column is inside the plot's scene rect).
                if self._extents is not None:
                    x0, x1, y0, y1 = self._extents
                    if x0 <= p.x() <= x1:
                        self.select_time_index(self._time_index_for(p.x()))
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
