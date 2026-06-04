"""Repro: (1) view-tab name compression on init, (2) selected file double blue line.

Run on the Windows desktop (NOT offscreen):
    PYTHONPATH=. .venv/Scripts/python.exe scripts/repro_tab_and_filerow.py
"""
import os
import sys

os.environ.pop("QT_QPA_PLATFORM", None)

from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui_kit import load_stylesheet

MF4 = os.path.join(os.path.dirname(__file__), "..", "testfile",
                   "resonance_high500degree.mf4")
OUT = os.path.join(os.path.dirname(__file__), "..", "testfile")


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    load_stylesheet(app)

    w = MainWindow()
    w.resize(1500, 860)
    w.show()
    app.processEvents()
    w.load_file(os.path.abspath(MF4))
    app.processEvents()

    cs = w.chart_stack
    # Ensure time mode so the bottom view-tab dock is visible.
    w._on_mode_changed("time")
    app.processEvents()

    # Add a couple of views so the tab bar has multiple labels.
    w._on_view_new(); app.processEvents()
    w._on_view_new(); app.processEvents()

    bar = cs._view_tabbar
    tabs = bar.tabBar()
    print("view count:", tabs.count())
    for i in range(tabs.count()):
        r = tabs.tabRect(i)
        print(f"  tab[{i}] text={tabs.tabText(i)!r} rect_w={r.width()} hint_w={tabs.sizeHint().width()}")
    print("tabbar fixedWidth:", tabs.width(), "sizeHint:", tabs.sizeHint().width())

    bar.repaint(); app.processEvents()
    tab_shot = os.path.abspath(os.path.join(OUT, "repro_tabbar.png"))
    # Grab the whole bottom dock so the +, tabs, and any compression are visible.
    cs._time_bottom_dock.grab().save(tab_shot)
    print("TAB SHOT:", tab_shot)

    # Select the file row (active) to expose the left-edge styling.
    fid = next(iter(w.files))
    w.navigator.set_active_file(fid) if hasattr(w.navigator, "set_active_file") else None
    app.processEvents()
    row = w.navigator._rows.get(fid)
    if row is not None:
        row.set_active(True)
        app.processEvents()
        nav_shot = os.path.abspath(os.path.join(OUT, "repro_filerow.png"))
        row.repaint(); app.processEvents()
        row.grab().save(nav_shot)
        print("FILEROW SHOT:", nav_shot)
        print("row active:", row.property("active"),
              "| accent active:", row._accent.property("active"),
              "| accent width:", row._accent.width())

    w.close()


if __name__ == "__main__":
    main()
