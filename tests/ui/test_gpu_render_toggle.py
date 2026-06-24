"""GPU render toggle: the GL viewport must repaint the whole scene.

Regression (2026-06-23): with GPU acceleration on, dragging the time-domain
canvas blanked every curve (拖动时曲线消失). A ``QOpenGLWidget`` viewport does
not preserve its framebuffer between paints, and pyqtgraph's ``GraphicsView``
defaults to ``MinimalViewportUpdate`` (repaint the dirty rect only), so each
pan tick painted only the moved strip and dropped the rest of the scene.
``_apply_gpu_viewport`` must switch the view to ``FullViewportUpdate`` while GL
owns the viewport and restore ``MinimalViewportUpdate`` for the CPU raster path.

A recording ``_glw`` double keeps these deterministic — a real GL context is
unavailable offscreen, and the production design notes headless cannot capture
the GL framebuffer.
"""

import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import QGraphicsItem, QGraphicsView

from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG


class _RecordingGlw:
    """Minimal GraphicsLayoutWidget double: records the viewport-update mode."""

    def __init__(self):
        self.gl_calls = []
        self.update_mode = QGraphicsView.MinimalViewportUpdate

    def useOpenGL(self, on):
        self.gl_calls.append(bool(on))

    def setViewportUpdateMode(self, mode):
        self.update_mode = mode

    def viewport(self):
        return None

    def update(self):
        pass


def _canvas_with_recording_glw():
    c = TimeDomainCanvasPG()
    c._glw = _RecordingGlw()
    c._gpu_render_on = False
    return c


def test_gl_viewport_uses_full_update_mode(qapp):
    c = _canvas_with_recording_glw()

    c.set_gpu_render(True)

    assert c._gpu_render_on is True
    assert c._glw.gl_calls[-1] is True
    assert c._glw.update_mode == QGraphicsView.FullViewportUpdate, (
        "GL viewport must repaint the whole scene; MinimalViewportUpdate "
        "blanks curves outside the dirty rect on every pan tick"
    )


def test_cpu_raster_restores_minimal_update_mode(qapp):
    c = _canvas_with_recording_glw()

    c.set_gpu_render(True)
    c.set_gpu_render(False)

    assert c._gpu_render_on is False
    assert c._glw.gl_calls[-1] is False
    assert c._glw.update_mode == QGraphicsView.MinimalViewportUpdate, (
        "CPU raster path keeps the cheap dirty-rect repaint"
    )


def test_idempotent_toggle_does_not_re_swap(qapp):
    c = _canvas_with_recording_glw()

    c.set_gpu_render(True)
    n = len(c._glw.gl_calls)
    c.set_gpu_render(True)  # same value → no extra useOpenGL/viewport swap

    assert len(c._glw.gl_calls) == n


# --- DeviceCoordinateCache must not be used under the GL viewport -----------
# A DeviceCoordinateCache renders each curve to an offscreen raster pixmap that
# does NOT composite onto a QOpenGLWidget viewport — the cached curves vanish
# (static, not just on drag) while uncached axes/labels still paint. The
# idle-AA path must skip the cache while GL is on, and toggling GL on must drop
# any cache the CPU path already set.

def _subplot_canvas():
    c = TimeDomainCanvasPG()
    c.resize(800, 600)
    t = np.linspace(0, 10, 5000)
    rows = [
        (f"ch{i}", True, t, np.sin(t + i), "#1769e0", "u", "fid")
        for i in range(3)
    ]
    c.plot_channels(rows, mode="subplot")
    return c


def _curve_cache_modes(c):
    scene = c._glw.scene()
    return [it.cacheMode() for it in scene.items()
            if isinstance(it, pg.PlotCurveItem)]


def test_idle_aa_skips_device_cache_under_gl(qapp):
    c = _subplot_canvas()
    c._gpu_render_on = True

    c.try_enable_idle_quality()

    modes = _curve_cache_modes(c)
    assert modes, "expected curve items on the scene"
    assert all(m == QGraphicsItem.NoCache for m in modes), (
        "GL viewport: curves must stay NoCache — DeviceCoordinateCache pixmaps "
        "do not composite onto QOpenGLWidget and the curves vanish"
    )


def test_idle_aa_uses_device_cache_on_cpu(qapp):
    c = _subplot_canvas()
    c._gpu_render_on = False

    c.try_enable_idle_quality()

    modes = _curve_cache_modes(c)
    assert modes, "expected curve items on the scene"
    assert all(m == QGraphicsItem.DeviceCoordinateCache for m in modes), (
        "CPU raster subplot keeps the DeviceCoordinateCache perf win"
    )


def test_gpu_on_clears_curve_device_cache(qapp):
    c = _canvas_with_recording_glw()
    calls = []
    c._quality._set_curves_cache_mode = lambda m: calls.append(m)

    c.set_gpu_render(True)

    assert QGraphicsItem.NoCache in calls, (
        "switching to GL must drop DeviceCoordinateCache so a cache set while "
        "on CPU does not leave the curves invisible under GL"
    )


# --- Toggling GPU must REBUILD the curves on the swapped viewport -----------
# useOpenGL() swaps the viewport widget (setViewport); curve items built on the
# PREVIOUS viewport do not re-render on the freshly-swapped GL viewport (a
# pan/refresh reuses the same stale items and stays blank). User-confirmed: 开
# GPU 后曲线消失，pan/缩放不回来、只有重新「绘图」才回来. So the window must
# re-plot the time domain on toggle so the curves are rebuilt on the new
# viewport instead of vanishing until a manual re-plot.

def _window_with_file(qtbot):
    from types import SimpleNamespace
    import pandas as pd
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    t = np.arange(2048, dtype=float) / 1000.0
    win.files["f1"] = SimpleNamespace(
        data=pd.DataFrame({"sig": np.sin(2 * np.pi * 50.0 * t)}),
        time_array=t,
        fs=1000.0,
        channel_units={"sig": ""},
    )
    return win


def test_gpu_toggle_replots_time_so_curves_rebuild(qapp, qtbot, monkeypatch):
    win = _window_with_file(qtbot)
    monkeypatch.setattr(win.chart_stack, "current_mode", lambda: "time")
    calls = []
    monkeypatch.setattr(win, "plot_time", lambda: calls.append(True))

    win._on_gpu_render_toggled(True)
    assert calls, "GPU ON with a file in time mode must re-plot so curves rebuild"

    calls.clear()
    win._on_gpu_render_toggled(False)
    assert calls, "GPU OFF also swaps the viewport → must re-plot to rebuild curves"


def test_gpu_toggle_no_replot_without_file(qapp, qtbot, monkeypatch):
    win = _window_with_file(qtbot)
    win.files.clear()
    monkeypatch.setattr(win.chart_stack, "current_mode", lambda: "time")
    calls = []
    monkeypatch.setattr(win, "plot_time", lambda: calls.append(True))

    win._on_gpu_render_toggled(True)
    assert not calls, "no file loaded → nothing to draw → no wasteful re-plot"


def test_gpu_toggle_no_replot_outside_time_mode(qapp, qtbot, monkeypatch):
    win = _window_with_file(qtbot)
    monkeypatch.setattr(win.chart_stack, "current_mode", lambda: "fft")
    calls = []
    monkeypatch.setattr(win, "plot_time", lambda: calls.append(True))

    win._on_gpu_render_toggled(True)
    assert not calls, (
        "GPU render owns the time canvas; an FFT-mode toggle should not re-plot "
        "time (switching back to time re-plots on its own)"
    )
