"""P2 Task 9 Step 5: side-by-side focus routing.

Covers ChartStack.focused_card()/focused_canvas()/set_focused_card() and the
MainWindow channel-check routing to the focused canvas. Run offscreen:

    QT_QPA_PLATFORM=offscreen pytest tests/ui/test_split_focus_routing.py -q
"""
from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QMouseEvent

from tests.ui.test_split_routing import _has_channel
from tests.ui.test_view_switch_integration import _fid, _set_checked
from tests.ui.test_split_routing import _make_speed_vs_torque_views


def _click_card(qapp, card):
    """Dispatch a real left-button press at the card's center so the focus
    event filter fires exactly as it would for a user click on the canvas."""
    canvas = getattr(card, "canvas", card)
    pos = QPoint(canvas.width() // 2, canvas.height() // 2)
    press = QMouseEvent(
        QEvent.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )
    qapp.sendEvent(canvas, press)
    qapp.processEvents()


def _focused_prop(card):
    return bool(card.property("focused"))


def _enter_split(w, qapp):
    w.view_manager.set_split(1)
    qapp.processEvents()
    assert w.chart_stack.split_active() is True


# ---------------------------------------------------------------------------
# focused_canvas / focused_card defaults
# ---------------------------------------------------------------------------

def test_focused_canvas_is_primary_when_not_split(qtbot, qapp, loaded_csv):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack

    assert cs.split_active() is False
    assert cs.focused_canvas() is cs.canvas_time
    assert cs.focused_card() is cs._time_card
    # No focus property in single-pane mode.
    assert _focused_prop(cs._time_card) is False


def test_enter_split_seeds_primary_focus(qtbot, qapp, loaded_csv):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)

    assert cs.focused_canvas() is cs.canvas_time
    assert cs.focused_card() is cs._time_card
    assert _focused_prop(cs._time_card) is True
    assert _focused_prop(cs._secondary_card) is False


# ---------------------------------------------------------------------------
# click -> focus switch + highlight
# ---------------------------------------------------------------------------

def test_click_secondary_focuses_it_and_lights_border(qtbot, qapp, loaded_csv):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)

    captured = []
    cs.focus_changed.connect(lambda secondary: captured.append(secondary))

    _click_card(qapp, cs._secondary_card)

    assert cs.focused_canvas() is cs.secondary_canvas()
    assert cs.focused_card() is cs._secondary_card
    assert _focused_prop(cs._secondary_card) is True
    assert _focused_prop(cs._time_card) is False
    assert captured == [True]


def test_click_primary_returns_focus_to_primary(qtbot, qapp, loaded_csv):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)

    _click_card(qapp, cs._secondary_card)
    assert cs.focused_card() is cs._secondary_card

    captured = []
    cs.focus_changed.connect(lambda secondary: captured.append(secondary))

    _click_card(qapp, cs._time_card)

    assert cs.focused_canvas() is cs.canvas_time
    assert cs.focused_card() is cs._time_card
    assert _focused_prop(cs._time_card) is True
    assert _focused_prop(cs._secondary_card) is False
    assert captured == [False]


def test_re_click_same_card_does_not_re_emit(qtbot, qapp, loaded_csv):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)

    captured = []
    cs.focus_changed.connect(lambda secondary: captured.append(secondary))

    # Primary is already focused; clicking it again must not re-emit.
    _click_card(qapp, cs._time_card)
    assert captured == []


# ---------------------------------------------------------------------------
# exit split clears focus highlighting
# ---------------------------------------------------------------------------

def test_exit_split_resets_focus_to_primary(qtbot, qapp, loaded_csv):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    _click_card(qapp, cs._secondary_card)
    assert cs.focused_card() is cs._secondary_card

    w.view_manager.set_split(None)
    qapp.processEvents()

    assert cs.split_active() is False
    assert cs.focused_canvas() is cs.canvas_time
    assert cs.focused_card() is cs._time_card
    assert _focused_prop(cs._time_card) is False
    assert _focused_prop(cs._secondary_card) is False


# ---------------------------------------------------------------------------
# channel-check routing follows focus
# ---------------------------------------------------------------------------

def test_channel_check_routes_to_focused_secondary(qtbot, qapp, loaded_csv):
    w, fid, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)

    # active view (index 0) shows "speed"; secondary (view 1) shows "torque".
    assert _has_channel(cs.canvas_time, "speed")
    assert _has_channel(cs.secondary_canvas(), "torque")

    # Focus the secondary, then change the channel selection. The replot must
    # land on the SECONDARY canvas, leaving the primary untouched.
    _click_card(qapp, cs._secondary_card)
    assert cs.focused_canvas() is cs.secondary_canvas()

    _set_checked(w, "speed", "torque")
    w._ch_changed()
    qapp.processEvents()

    assert _has_channel(cs.secondary_canvas(), "speed")
    assert _has_channel(cs.secondary_canvas(), "torque")
    # Primary keeps its original single channel (not the new selection).
    assert _has_channel(cs.canvas_time, "speed")
    assert not _has_channel(cs.canvas_time, "torque")


def test_channel_check_routes_to_primary_when_primary_focused(
    qtbot, qapp, loaded_csv
):
    w, fid, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)

    # Primary is focused by default after enter_split.
    assert cs.focused_canvas() is cs.canvas_time

    _set_checked(w, "speed", "torque")
    w._ch_changed()
    qapp.processEvents()

    assert _has_channel(cs.canvas_time, "speed")
    assert _has_channel(cs.canvas_time, "torque")
    # Secondary keeps its compare-view snapshot (torque only).
    assert _has_channel(cs.secondary_canvas(), "torque")
    assert not _has_channel(cs.secondary_canvas(), "speed")
