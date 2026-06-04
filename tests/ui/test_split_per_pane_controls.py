"""P2 Task 9 1a + 1b: per-pane cursor / plot-mode routing and control enabling.

Covers:
- _on_cursor_mode_changed routes the cursor toggle to ChartStack.focused_canvas()
  (primary outside split; secondary when the secondary card is focused).
- The secondary (compare) card's own 分屏/叠加/游标 controls are enabled only while
  it is focused and act on the SECONDARY canvas, leaving the primary untouched.
- Per-pane plot mode: plot_mode_for_canvas() resolves the layout from the card
  owning the target canvas.

Run offscreen:
    QT_QPA_PLATFORM=offscreen pytest tests/ui/test_split_per_pane_controls.py -q
"""
from tests.ui.test_split_routing import _has_channel, _make_speed_vs_torque_views
from tests.ui.test_view_switch_integration import _set_checked
from tests.ui.test_split_focus_routing import _click_card, _enter_split


# ---------------------------------------------------------------------------
# 1a: cursor-mode routing follows focus
# ---------------------------------------------------------------------------

def test_cursor_mode_targets_primary_when_not_split(qtbot, qapp, loaded_csv):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    assert cs.split_active() is False

    # Drive the primary card's cursor control -> primary canvas reacts.
    cs._time_card.set_cursor_mode("dual")
    qapp.processEvents()
    assert cs.canvas_time._cursor_visible is True
    assert cs.canvas_time._dual is True

    cs._time_card.set_cursor_mode("off")
    qapp.processEvents()
    assert cs.canvas_time._cursor_visible is False
    assert cs.canvas_time._dual is False


def test_cursor_mode_targets_secondary_when_secondary_focused(
    qtbot, qapp, loaded_csv
):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    _click_card(qapp, cs._secondary_card)
    assert cs.focused_canvas() is cs.secondary_canvas()

    primary_before = (cs.canvas_time._cursor_visible, cs.canvas_time._dual)

    # The primary card's cursor relay (which carries the active segmented
    # control) now lands on the FOCUSED (secondary) canvas via 1a routing.
    cs._time_card.set_cursor_mode("dual")
    qapp.processEvents()
    assert cs.secondary_canvas()._cursor_visible is True
    assert cs.secondary_canvas()._dual is True
    # Primary canvas is untouched.
    assert (cs.canvas_time._cursor_visible, cs.canvas_time._dual) == primary_before


def test_secondary_own_cursor_control_acts_on_secondary(qtbot, qapp, loaded_csv):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    _click_card(qapp, cs._secondary_card)

    primary_before = (cs.canvas_time._cursor_visible, cs.canvas_time._dual)

    cs._secondary_card.set_cursor_mode("single")
    qapp.processEvents()
    assert cs.secondary_canvas()._cursor_visible is True
    assert cs.secondary_canvas()._dual is False
    assert (cs.canvas_time._cursor_visible, cs.canvas_time._dual) == primary_before

    cs._secondary_card.set_cursor_mode("off")
    qapp.processEvents()
    assert cs.secondary_canvas()._cursor_visible is False


# ---------------------------------------------------------------------------
# 1b: secondary control enable/disable follows focus
# ---------------------------------------------------------------------------

def _control_buttons(card):
    return [card.btn_subplot, card.btn_overlay, *card._cursor_buttons.values()]


def test_secondary_controls_disabled_when_primary_focused(qtbot, qapp, loaded_csv):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    # Primary focused by default after enter_split.
    assert cs.focused_card() is cs._time_card
    for b in _control_buttons(cs._secondary_card):
        assert b.isEnabled() is False
    for b in _control_buttons(cs._time_card):
        assert b.isEnabled() is True


def test_focusing_secondary_enables_its_controls_and_disables_primary(
    qtbot, qapp, loaded_csv
):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    _click_card(qapp, cs._secondary_card)

    for b in _control_buttons(cs._secondary_card):
        assert b.isEnabled() is True
    for b in _control_buttons(cs._time_card):
        assert b.isEnabled() is False

    # Click back to primary: enable flips back.
    _click_card(qapp, cs._time_card)
    for b in _control_buttons(cs._secondary_card):
        assert b.isEnabled() is False
    for b in _control_buttons(cs._time_card):
        assert b.isEnabled() is True


def test_exit_split_restores_primary_controls(qtbot, qapp, loaded_csv):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    _click_card(qapp, cs._secondary_card)
    assert cs._secondary_card.btn_subplot.isEnabled() is True

    w.view_manager.set_split(None)
    qapp.processEvents()
    assert cs.split_active() is False
    # Primary controls live again in single-pane mode.
    for b in _control_buttons(cs._time_card):
        assert b.isEnabled() is True


# ---------------------------------------------------------------------------
# 1b: per-pane plot mode replots the secondary in its own layout
# ---------------------------------------------------------------------------

def test_plot_mode_for_canvas_resolves_per_pane(qtbot, qapp, loaded_csv):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)

    # View 0 (primary) was built in overlay; view 1 (secondary) in subplot.
    assert cs._time_card.plot_mode() == "overlay"
    assert cs._secondary_card.plot_mode() == "subplot"
    assert cs.plot_mode_for_canvas(cs.canvas_time) == "overlay"
    assert cs.plot_mode_for_canvas(cs.secondary_canvas()) == "subplot"


def test_secondary_plot_mode_toggle_relayouts_secondary_only(
    qtbot, qapp, loaded_csv
):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    _click_card(qapp, cs._secondary_card)

    # Put two channels on the secondary so subplot vs overlay is observable.
    _set_checked(w, "speed", "torque")
    w._ch_changed()
    qapp.processEvents()
    assert _has_channel(cs.secondary_canvas(), "speed")
    assert _has_channel(cs.secondary_canvas(), "torque")

    primary_overlay_before = cs.canvas_time._overlay_mode

    # Secondary starts in subplot (from view build). Flip it to overlay via
    # the secondary card's OWN control -> only the secondary re-lays out.
    cs._secondary_card.set_plot_mode("overlay")
    qapp.processEvents()
    assert cs.secondary_canvas()._overlay_mode is True
    # Primary layout untouched.
    assert cs.canvas_time._overlay_mode == primary_overlay_before

    # Flip back to subplot.
    cs._secondary_card.set_plot_mode("subplot")
    qapp.processEvents()
    assert cs.secondary_canvas()._overlay_mode is False
    assert cs.canvas_time._overlay_mode == primary_overlay_before
