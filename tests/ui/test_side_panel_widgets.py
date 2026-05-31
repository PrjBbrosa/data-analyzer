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
    overlay.mouse_left.emit()                                # start collapse timer
    overlay.mouse_entered.emit()                             # cancel within window
    # Deterministic: re-entry must have STOPPED the timer, so it can never fire.
    assert ctrl._collapse_timer.isActive() is False
    assert ctrl.state == PanelState.PEEK                     # still peeking


def test_redock_takes_width_from_canvas_not_other_panel(qtbot):
    # 3-pane [nav(0), canvas(1), inspector(2)] with inspector WIDER than canvas.
    # Re-docking the nav must pull its width from the canvas, never the inspector.
    host = QWidget(); host.resize(900, 600); qtbot.addWidget(host); host.show()
    splitter = QSplitter(Qt.Horizontal, host)
    nav, canvas, insp = QWidget(), QWidget(), QWidget()
    for w in (nav, canvas, insp):
        w.setMinimumWidth(10)
    splitter.addWidget(nav); splitter.addWidget(canvas); splitter.addWidget(insp)
    splitter.resize(900, 600)
    strip = SidePanelStrip(Side.LEFT, hover_delay_ms=10)
    overlay = PeekOverlay(host)
    ctrl = SidePanelController(
        side=Side.LEFT, splitter=splitter, panel=nav, panel_index=0,
        strip=strip, overlay=overlay, host=host,
        collapse_delay_ms=20, default_width=250, canvas=canvas,
    )
    splitter.setSizes([0, 350, 550]); ctrl.on_splitter_moved()   # -> HIDDEN
    assert ctrl.state == PanelState.HIDDEN
    # Snapshot the inspector width AFTER Qt normalises the setSizes call
    # (QSplitter subtracts handle pixels, so the stored value may differ from
    # the requested 550).  The invariant under test is that this value is
    # PRESERVED after re-docking the nav — the delta must come only from canvas.
    insp_before = splitter.sizes()[2]
    canvas_before = splitter.sizes()[1]
    strip.pin_requested.emit(Side.LEFT)                          # re-dock at 250
    sizes = splitter.sizes()
    assert ctrl.state == PanelState.PINNED
    assert sizes[0] == 250                          # nav restored to remembered width
    assert sizes[2] == insp_before                  # inspector UNTOUCHED (the bug would shrink this)
    assert sizes[1] == canvas_before - 250          # canvas absorbed the full 250 delta


def test_peek_overlay_offset_keeps_strip_exposed(qtbot):
    ctrl, splitter, panel, strip, overlay = _make_controller(qtbot)
    splitter.setSizes([0, 900]); ctrl.on_splitter_moved()   # -> HIDDEN
    strip.peek_requested.emit(Side.LEFT)                     # -> PEEK
    assert ctrl.state == PanelState.PEEK
    # Overlay starts at the strip's inner edge, leaving the strip clickable.
    assert overlay.geometry().x() == strip.WIDTH_PX


def test_peek_one_side_then_other_side_events_do_not_crash(qtbot):
    # Reproduces the cross-side IndexError: when LEFT peeks, nav leaves the
    # splitter and it renumbers (3->2 panes). The still-PINNED RIGHT controller
    # (fixed panel_index=2) must not crash on splitterMoved or on its own hover.
    host = QWidget(); host.resize(1000, 600); qtbot.addWidget(host); host.show()
    splitter = QSplitter(Qt.Horizontal, host)
    nav, canvas, insp = QWidget(), QWidget(), QWidget()
    for wdg in (nav, canvas, insp):
        wdg.setMinimumWidth(10)
    splitter.addWidget(nav); splitter.addWidget(canvas); splitter.addWidget(insp)
    splitter.resize(1000, 600)
    splitter.setSizes([250, 500, 250])
    strip_l = SidePanelStrip(Side.LEFT, hover_delay_ms=10)
    strip_r = SidePanelStrip(Side.RIGHT, hover_delay_ms=10)
    ov_l, ov_r = PeekOverlay(host), PeekOverlay(host)
    ctrl_l = SidePanelController(
        side=Side.LEFT, splitter=splitter, panel=nav, panel_index=0,
        strip=strip_l, overlay=ov_l, host=host,
        collapse_delay_ms=20, default_width=250, canvas=canvas)
    ctrl_r = SidePanelController(
        side=Side.RIGHT, splitter=splitter, panel=insp, panel_index=2,
        strip=strip_r, overlay=ov_r, host=host,
        collapse_delay_ms=20, default_width=250, canvas=canvas)

    # Collapse BOTH sides so each is HIDDEN before peeking.
    splitter.setSizes([0, 750, 0])
    ctrl_l.on_splitter_moved()   # LEFT -> HIDDEN
    ctrl_r.on_splitter_moved()   # RIGHT -> HIDDEN

    # Peek the LEFT: nav is reparented OUT, splitter renumbers (3->2 panes).
    strip_l.peek_requested.emit(Side.LEFT)                          # LEFT -> PEEK
    assert ctrl_l.state == PanelState.PEEK
    assert splitter.indexOf(nav) == -1                             # nav left splitter

    # These would raise IndexError before the fix:
    ctrl_l.on_splitter_moved()
    ctrl_r.on_splitter_moved()
    strip_r.peek_requested.emit(Side.RIGHT)                        # RIGHT also peeks
    assert ctrl_r.state == PanelState.PEEK


def test_toolbar_has_no_inspector_button_and_cockpit_on_right(qtbot):
    from mf4_analyzer.ui.toolbar import Toolbar
    tb = Toolbar()
    qtbot.addWidget(tb)
    assert not hasattr(tb, "btn_inspector")
    assert not hasattr(tb, "inspector_visibility_changed")
    # Cockpit button now lives in the right-segment host widget.
    assert tb.btn_acquisition_cockpit.parent() is tb._right_widget


def test_peek_overlay_clamps_width_to_capped_panel(qtbot):
    # A width-capped panel (like the inspector, pinned to a fixed width) can't
    # stretch to fill PEEK_EXTRA_PX, so the overlay must clamp to the panel's
    # max width — otherwise the surplus shows as a blank band of overlay bg.
    host = QWidget(); host.resize(900, 600); qtbot.addWidget(host); host.show()
    splitter = QSplitter(Qt.Horizontal, host)
    panel = QWidget(); panel.setFixedWidth(360)        # min == max == 360
    middle = QWidget(); middle.setMinimumWidth(100)
    splitter.addWidget(panel); splitter.addWidget(middle)   # panel is index 0
    splitter.resize(900, 600); splitter.setSizes([360, 540])
    strip = SidePanelStrip(Side.LEFT, hover_delay_ms=10)
    overlay = PeekOverlay(host)
    ctrl = SidePanelController(
        side=Side.LEFT, splitter=splitter, panel=panel, panel_index=0,
        strip=strip, overlay=overlay, host=host,
        collapse_delay_ms=20, default_width=360, canvas=middle)
    splitter.setSizes([0, 900]); ctrl.on_splitter_moved()   # panel slot 0 -> HIDDEN
    strip.peek_requested.emit(Side.LEFT)                     # -> PEEK
    assert ctrl.state == PanelState.PEEK
    # Clamped to the 360 cap, NOT 360 + PEEK_EXTRA_PX.
    assert overlay.geometry().width() == 360


def test_peek_overlay_uncapped_panel_keeps_extra_width(qtbot):
    # An uncapped panel (like the navigator) keeps the +PEEK_EXTRA_PX bonus.
    ctrl, splitter, panel, strip, overlay = _make_controller(qtbot)
    splitter.setSizes([0, 900]); ctrl.on_splitter_moved()   # -> HIDDEN
    strip.peek_requested.emit(Side.LEFT)                     # -> PEEK
    assert ctrl.state == PanelState.PEEK
    assert overlay.geometry().width() == ctrl._remembered_width + ctrl.PEEK_EXTRA_PX


def test_peek_width_floor_widens_narrow_panel_for_symmetry(qtbot):
    # A narrow uncapped panel with a peek_width floor peeks out to that floor
    # (L/R symmetry: the 250-wide navigator peeks to the inspector's 360).
    host = QWidget(); host.resize(900, 600); qtbot.addWidget(host); host.show()
    splitter = QSplitter(Qt.Horizontal, host)
    panel = QWidget(); panel.setMinimumWidth(50)        # uncapped
    middle = QWidget(); middle.setMinimumWidth(100)
    splitter.addWidget(panel); splitter.addWidget(middle)
    splitter.resize(900, 600); splitter.setSizes([250, 650])
    strip = SidePanelStrip(Side.LEFT, hover_delay_ms=10)
    overlay = PeekOverlay(host)
    ctrl = SidePanelController(
        side=Side.LEFT, splitter=splitter, panel=panel, panel_index=0,
        strip=strip, overlay=overlay, host=host,
        collapse_delay_ms=20, default_width=250, canvas=middle, peek_width=360)
    splitter.setSizes([0, 900]); ctrl.on_splitter_moved()   # -> HIDDEN
    strip.peek_requested.emit(Side.LEFT)                     # -> PEEK
    assert ctrl.state == PanelState.PEEK
    # remembered(250)+EXTRA(24)=274 < floor 360 -> floored to 360.
    assert overlay.geometry().width() == 360
