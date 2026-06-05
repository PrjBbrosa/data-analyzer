"""Manual verification for overlay grid/tick alignment.

Usage:
    QT_QPA_PLATFORM=offscreen PYTHONPATH=. python scripts/verify_overlay_grid_ticks.py

Output:
    /tmp/overlay_grid_ticks.png plus channel ylim/tick values on stdout.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt5")

import numpy as np
from PyQt5.QtCore import QCoreApplication
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG


def main() -> int:
    app = QApplication.instance() or QApplication([])
    canvas = TimeDomainCanvasPG()
    canvas.resize(900, 480)
    canvas.show()

    t = np.linspace(0.0, 1.0, 512)
    rows = [
        ("voltage", True, t, 2.0 * np.sin(2 * np.pi * t) + 1.0, "#1769e0", "V", "f0"),
        ("current", True, t, 0.4 * np.cos(2 * np.pi * 3 * t), "#e07b17", "A", "f1"),
        ("torque", True, t, 6.0 + np.sin(2 * np.pi * 2 * t), "#16a34a", "Nm", "f2"),
    ]
    canvas.plot_channels(rows, mode="overlay")
    canvas.set_tick_density(10, 8)
    QCoreApplication.processEvents()

    for handle in canvas.axes_list:
        axis = handle.y_axis_item()
        major = []
        if axis is not None and getattr(axis, "_tickLevels", None):
            major = [value for value, _label in axis._tickLevels[0]]
        print("ylim:", handle.get_ylim(), "ticks:", major)

    out = "/tmp/overlay_grid_ticks.png"
    pixmap = canvas.grab_pixmap() if hasattr(canvas, "grab_pixmap") else canvas.grab()
    ok = pixmap.save(out)
    print(f"saved={ok} path={out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
