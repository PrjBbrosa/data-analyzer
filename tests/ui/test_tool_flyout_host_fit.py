"""UltraView ToolFlyoutSurface stays inside the host (S13 embedded)."""
from __future__ import annotations

from PyQt5.QtCore import QPoint
from PyQt5.QtWidgets import QLabel, QWidget

from mf4_analyzer.ui.chart_stack.ultraview.author_chrome import ToolFlyoutSurface
from mf4_analyzer.ui_kit.dialog_geometry import SCREEN_MARGIN


def test_hosted_flyout_popup_stays_inside_compact_parent(qapp, qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(200, 160)
    host.show()
    qtbot.waitExposed(host)
    flyout = ToolFlyoutSurface(host)
    qtbot.addWidget(flyout)
    for index in range(12):
        flyout.inner_layout().addWidget(QLabel(f"工具项 {index}", flyout))
    flyout.popup(host.mapToGlobal(QPoint(8, 8)))
    qapp.processEvents()
    assert host.rect().contains(flyout.geometry())
    assert flyout.height() <= max(1, host.height() - 2 * SCREEN_MARGIN)
    assert flyout.vertical_scroll_enabled() or flyout.height() <= host.height()
