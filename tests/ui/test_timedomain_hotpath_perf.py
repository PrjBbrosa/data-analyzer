"""Hot-path "don't redo work" regression tests.

Each test pins one contract from
docs/superpowers/specs/2026-06-10-timedomain-plot-optimization.md (Wave A).
They assert on CALL COUNTS of internal seams, not on pixels: the
optimizations must make repeated/no-op invocations free without changing
any rendered output (rendered-output parity is covered by the existing
test_pg_timedomain_canvas.py suite).
"""
import numpy as np

from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG


def _rows(n=3):
    """Channel rows in the MainWindow shape (name, visible, t, sig, color, unit, fid)."""
    t = np.linspace(0.0, 1.0, 2_000, dtype=np.float64)
    waves = [
        ("speed", 1000.0 * np.sin(2 * np.pi * 5 * t), "#1769e0", "rpm"),
        ("torque", 50.0 + 5.0 * np.cos(2 * np.pi * 3 * t), "#ef4444", "Nm"),
        ("pressure", 0.2 * t + 0.1 * np.sin(2 * np.pi * 7 * t), "#00b894", "bar"),
        ("temp", 60.0 + 2.0 * np.cos(2 * np.pi * 1.5 * t), "#fbbf24", "C"),
    ]
    return [
        (name, True, t, sig, color, unit, "fid-1")
        for name, sig, color, unit in waves[:n]
    ]


def _make_canvas(qtbot, rows, mode):
    canvas = TimeDomainCanvasPG()
    qtbot.addWidget(canvas)
    canvas.resize(600, 360)
    canvas.show()
    canvas.plot_channels(rows, mode=mode)
    canvas._flush_pending_refresh()
    return canvas
