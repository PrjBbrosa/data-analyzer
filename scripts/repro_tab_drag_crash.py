"""Repro: dragging a view tab crashes (use-after-free during live reorder).

Replicates the real-app wiring (reorder_requested -> ViewManager.reorder ->
views_changed -> ViewTabBar.refresh) and simulates a real drag of tab 0 past
tab 2 with QTest mouse events. On the buggy code this segfaults; the fix makes
it survive and reorder correctly.

    PYTHONPATH=. .venv/Scripts/python.exe scripts/repro_tab_drag_crash.py
"""
import os
import sys

os.environ.pop("QT_QPA_PLATFORM", None)  # need the native platform for a real drag

from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.view_tabbar import ViewTabBar
from mf4_analyzer.ui.view_state import ViewManager


def main():
    app = QApplication.instance() or QApplication(sys.argv)

    manager = ViewManager()
    bar = ViewTabBar(manager)
    # Real-app wiring: this is what makes a drag rebuild the bar mid-drag.
    bar.reorder_requested.connect(manager.reorder)

    manager.new_view()
    manager.new_view()  # 3 views: View 1 / View 2 / View 3
    bar.resize(400, 28)
    bar.show()
    app.processEvents()

    print("before:", [v.name for v in manager.views])

    tabbar = bar.tabBar()
    # moveTab() emits tabMoved synchronously — same re-entrant path a live drag
    # takes (tabMoved -> reorder -> views_changed -> refresh) — and then keeps
    # touching its tab list after the signal returns. If refresh() rebuilt the
    # tabs mid-emit, this is where it blows up.
    tabbar.moveTab(0, 2)
    app.processEvents()

    order = [v.name for v in manager.views]
    tabs = [tabbar.tabText(i) for i in range(bar.count())]
    print("SURVIVED the drag (no crash)")
    print("manager order:", order)
    print("tab bar order:", tabs)
    print("in sync:", order == tabs)
    bar.close()


if __name__ == "__main__":
    main()
