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


def test_overlay_take_panel_round_trip(qtbot):
    host = QWidget(); qtbot.addWidget(host)
    overlay = PeekOverlay(host)
    panel = QWidget()
    overlay.set_panel(panel)
    returned = overlay.take_panel()
    assert returned is panel
    assert overlay._panel is None
    assert overlay._lay.count() == 0


def test_overlay_set_panel_evicts_previous(qtbot):
    host = QWidget(); qtbot.addWidget(host)
    overlay = PeekOverlay(host)
    a, b = QWidget(), QWidget()
    overlay.set_panel(a)
    overlay.set_panel(b)
    assert overlay._panel is b
    assert overlay._lay.count() == 1


from mf4_analyzer.ui.side_panels import (
    PanelState, SidePanelController,
)


def _make_controller(qtbot):
    host = QWidget()
    host.resize(900, 600)
    host.show()                              # must be shown for child isVisible() to work
    qtbot.addWidget(host)
    splitter = QSplitter(Qt.Horizontal, host)
    panel = QWidget()
    panel.setMinimumWidth(50)
    middle = QWidget()
    middle.setMinimumWidth(100)
    splitter.addWidget(panel)
    splitter.addWidget(middle)
    splitter.resize(900, 600)               # must have non-zero size for setSizes to be honoured
    splitter.setSizes([250, 650])
    strip = SidePanelStrip(Side.LEFT, hover_delay_ms=10)
    overlay = PeekOverlay(host)
    ctrl = SidePanelController(
        side=Side.LEFT, splitter=splitter, panel=panel, panel_index=0,
        strip=strip, overlay=overlay, host=host,
        collapse_delay_ms=20, default_width=250,
    )
    return ctrl, splitter, panel, strip, overlay


def test_controller_starts_pinned_strip_hidden(qtbot):
    ctrl, splitter, panel, strip, overlay = _make_controller(qtbot)
    assert ctrl.state == PanelState.PINNED
    assert strip.isVisible() is False


def test_drag_collapse_hides_panel_and_shows_strip(qtbot):
    ctrl, splitter, panel, strip, overlay = _make_controller(qtbot)
    splitter.setSizes([0, 900])          # user dragged handle to the edge
    ctrl.on_splitter_moved()
    assert ctrl.state == PanelState.HIDDEN
    assert strip.isVisible() is True
    assert panel.isVisible() is False


def test_click_strip_redocks_with_remembered_width(qtbot):
    ctrl, splitter, panel, strip, overlay = _make_controller(qtbot)
    splitter.setSizes([0, 900]); ctrl.on_splitter_moved()   # -> HIDDEN
    strip.pin_requested.emit(Side.LEFT)                      # click
    assert ctrl.state == PanelState.PINNED
    assert splitter.sizes()[0] == 250                        # remembered
    assert strip.isVisible() is False


def test_hover_peeks_into_overlay_then_autohides(qtbot):
    ctrl, splitter, panel, strip, overlay = _make_controller(qtbot)
    splitter.setSizes([0, 900]); ctrl.on_splitter_moved()   # -> HIDDEN
    strip.peek_requested.emit(Side.LEFT)                     # hover
    assert ctrl.state == PanelState.PEEK
    assert panel.parent() is overlay
    assert overlay.isVisible() is True
    overlay.mouse_left.emit()                                # mouse leaves
    qtbot.waitUntil(lambda: ctrl.state == PanelState.HIDDEN, timeout=500)
    assert overlay.isVisible() is False
    assert panel.isVisible() is False


def test_reentry_cancels_autohide(qtbot):
    ctrl, splitter, panel, strip, overlay = _make_controller(qtbot)
    splitter.setSizes([0, 900]); ctrl.on_splitter_moved()
    strip.peek_requested.emit(Side.LEFT)
    overlay.mouse_left.emit()                                # start timer
    overlay.mouse_entered.emit()                             # cancel within window
    qtbot.wait(60)
    assert ctrl.state == PanelState.PEEK                     # still peeking
