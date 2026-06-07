"""Real-window (cocoa) smoke for P2 Task 9 Step 5 focus highlight.

Loads a CSV, builds two views (speed / torque), enters side-by-side split,
then screenshots the chart stack BEFORE and AFTER clicking the secondary card
so the primary-blue focus border can be visually confirmed to move.

Run on macOS desktop (NOT offscreen):
    .venv/bin/python scripts/focus_routing_cocoa_smoke.py
"""
import os
import sys
import tempfile

# Must NOT be offscreen — we want a real rendered border.
os.environ.pop("QT_QPA_PLATFORM", None)

import numpy as np
import pandas as pd
from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui_kit import load_stylesheet


def _make_csv():
    t = np.linspace(0, 1.0, 1000)
    df = pd.DataFrame({
        "time": t,
        "speed": 1000 * np.sin(2 * np.pi * 5 * t),
        "torque": 50 + 5 * np.cos(2 * np.pi * 3 * t),
    })
    p = os.path.join(tempfile.gettempdir(), "focus_routing_smoke.csv")
    df.to_csv(p, index=False)
    return p


def _set_checked(w, *channels):
    fid = next(iter(w.files))
    w.navigator.set_checked_channels([(fid, ch) for ch in channels])


def _click_card(app, card):
    canvas = card.canvas
    pos = QPoint(canvas.width() // 2, canvas.height() // 2)
    press = QMouseEvent(
        QEvent.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )
    app.sendEvent(canvas, press)
    app.processEvents()


def _grab(w, path):
    w.chart_stack.repaint()
    w.repaint()
    QApplication.processEvents()
    pm = w.chart_stack.grab()
    pm.save(path)
    return path


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    load_stylesheet(app)
    csv = _make_csv()

    w = MainWindow()
    w.resize(1400, 820)
    w.show()
    app.processEvents()
    w.load_file(csv)
    app.processEvents()

    cs = w.chart_stack

    # View 0: speed
    _set_checked(w, "speed")
    cs.set_plot_mode("overlay")
    w.plot_time()
    w._capture_current_view()

    # View 1: torque
    w._on_view_new()
    app.processEvents()
    _set_checked(w, "torque")
    cs.set_plot_mode("subplot")
    w.plot_time()
    w._capture_current_view()

    # Back to view 0, then split against view 1.
    w._switch_view(0)
    app.processEvents()
    w.view_manager.set_split(1)
    app.processEvents()

    print("split_active:", cs.split_active())
    print("BEFORE click: focused_card is primary:",
          cs.focused_card() is cs._time_card,
          "primary.focused=", cs._time_card.property("focused"),
          "secondary.focused=", cs._secondary_card.property("focused"))
    before = _grab(w, os.path.join(tempfile.gettempdir(),
                                   "focus_routing_primary.png"))

    _click_card(app, cs._secondary_card)
    print("AFTER click secondary: focused_card is secondary:",
          cs.focused_card() is cs._secondary_card,
          "primary.focused=", cs._time_card.property("focused"),
          "secondary.focused=", cs._secondary_card.property("focused"))
    after = _grab(w, os.path.join(tempfile.gettempdir(),
                                  "focus_routing_secondary.png"))

    _click_card(app, cs._time_card)
    print("AFTER click primary again: focused_card is primary:",
          cs.focused_card() is cs._time_card,
          "primary.focused=", cs._time_card.property("focused"),
          "secondary.focused=", cs._secondary_card.property("focused"))
    back = _grab(w, os.path.join(tempfile.gettempdir(),
                                 "focus_routing_back_to_primary.png"))

    print("SCREENSHOTS:")
    print(" ", before)
    print(" ", after)
    print(" ", back)
    w.close()


if __name__ == "__main__":
    main()
