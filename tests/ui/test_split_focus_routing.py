"""P2 Task 9 Step 5: side-by-side focus routing.

Covers ChartStack.focused_card()/focused_canvas()/set_focused_card() and the
MainWindow channel-check routing to the focused canvas. Run offscreen:

    QT_QPA_PLATFORM=offscreen pytest tests/ui/test_split_focus_routing.py -q
"""
import pytest

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


def test_secondary_range_changes_write_back_to_original_view_state(
    qtbot, qapp, loaded_csv
):
    w, _fid_value, _v1_xlim, _v1_ylims, _v2_xlim, _v2_ylims = (
        _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    )
    cs = w.chart_stack

    w._switch_view(1)
    qapp.processEvents()
    w.view_manager.set_split(0)
    qapp.processEvents()

    secondary = cs.secondary_canvas()
    assert secondary is not None
    assert w.view_manager.split_with == 0

    target_xlim = (0.23, 0.47)
    secondary.restore_visible_xlim(target_xlim)
    w._capture_canvas_ranges_for_bound_view(secondary)

    assert w.view_manager.get(0).xlim == pytest.approx(target_xlim)

    # Open View 0 as primary; it should keep the secondary pane's last range.
    w._switch_view(0)
    qapp.processEvents()
    assert w.canvas_time.get_visible_xlim() == pytest.approx(target_xlim)


def test_tick_density_change_routes_to_focused_secondary_view(
    qtbot, qapp, loaded_csv
):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    _click_card(qapp, cs._secondary_card)

    primary_before = cs.canvas_time._tick_density

    w._update_all_tick_density_pair(17, 4)
    qapp.processEvents()

    assert cs.secondary_canvas()._tick_density == (17, 4)
    assert cs.canvas_time._tick_density == primary_before
    assert w.view_manager.get(1).axis_opts["tick_density"] == {"x": 17, "y": 4}


def test_focus_switch_captures_previous_focused_inspector_state(
    qtbot, qapp, loaded_csv
):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    _click_card(qapp, cs._secondary_card)

    top = w.inspector.top
    old_xt = top.spin_xt.blockSignals(True)
    old_yt = top.spin_yt.blockSignals(True)
    try:
        top.spin_xt.setValue(21)
        top.spin_yt.setValue(9)
    finally:
        top.spin_yt.blockSignals(old_yt)
        top.spin_xt.blockSignals(old_xt)

    _click_card(qapp, cs._time_card)

    assert w.view_manager.get(1).axis_opts["tick_density"] == {"x": 21, "y": 9}
    assert w.inspector.top.tick_density() == (8, 5)
