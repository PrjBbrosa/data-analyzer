# tests/ui/test_side_panel_widgets.py
"""qtbot widget/controller tests for collapsible side panels."""
import pytest
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtWidgets import QWidget, QSplitter
from PyQt5.QtTest import QTest

from mf4_analyzer.ui.side_panels import Side, SidePanelStrip


def test_strip_emits_pin_on_left_click(qtbot):
    strip = SidePanelStrip(Side.LEFT)
    qtbot.addWidget(strip)
    strip.resize(12, 200)
    with qtbot.waitSignal(strip.pin_requested, timeout=500) as blocker:
        QTest.mouseClick(strip, Qt.LeftButton, pos=QPoint(6, 100))
    assert blocker.args == [Side.LEFT]


def test_strip_emits_peek_after_hover_debounce(qtbot):
    strip = SidePanelStrip(Side.RIGHT, hover_delay_ms=10)
    qtbot.addWidget(strip)
    with qtbot.waitSignal(strip.peek_requested, timeout=500) as blocker:
        strip.enterEvent(None)  # simulate hover-in; debounce timer starts
    assert blocker.args == [Side.RIGHT]


def test_strip_hover_out_before_debounce_cancels(qtbot):
    strip = SidePanelStrip(Side.LEFT, hover_delay_ms=300)
    qtbot.addWidget(strip)
    fired = []
    strip.peek_requested.connect(lambda s: fired.append(s))
    strip.enterEvent(None)
    strip.leaveEvent(None)   # leaves before 300ms debounce elapses
    qtbot.wait(120)
    assert fired == []


from mf4_analyzer.ui.side_panels import PeekOverlay


def test_overlay_emits_enter_and_leave(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    overlay = PeekOverlay(host)
    entered, left = [], []
    overlay.mouse_entered.connect(lambda: entered.append(1))
    overlay.mouse_left.connect(lambda: left.append(1))
    overlay.enterEvent(None)
    overlay.leaveEvent(None)
    assert entered == [1]
    assert left == [1]


def test_overlay_hosts_a_panel(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    overlay = PeekOverlay(host)
    panel = QWidget()
    overlay.set_panel(panel)
    assert panel.parent() is overlay
