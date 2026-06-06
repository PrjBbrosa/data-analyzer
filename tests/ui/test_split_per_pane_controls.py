"""P2 Task 9 1a + 1b: cursor / plot-mode routing and shared controls.

Covers:
- _on_cursor_mode_changed routes the cursor toggle to the primary outside split
  and synchronizes both panes while split is active.
- The visible shared 分屏/叠加/游标 controls stay enabled while either pane is
  focused; the secondary card's internal controls remain disabled because its
  toolbar is not part of the split UI.
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


def test_split_cursor_mode_targets_both_panes_when_secondary_focused(
    qtbot, qapp, loaded_csv
):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    _click_card(qapp, cs._secondary_card)
    assert cs.focused_canvas() is cs.secondary_canvas()

    # The shared cursor control now applies to both split panes; it no longer
    # depends on the currently focused pane.
    cs._time_card.set_cursor_mode("single")
    qapp.processEvents()
    assert cs.canvas_time._cursor_visible is True
    assert cs.canvas_time._dual is False
    assert cs.secondary_canvas()._cursor_visible is True
    assert cs.secondary_canvas()._dual is False

    cs._time_card.set_cursor_mode("dual")
    qapp.processEvents()
    assert cs.canvas_time._cursor_visible is True
    assert cs.canvas_time._dual is True
    assert cs.secondary_canvas()._cursor_visible is True
    assert cs.secondary_canvas()._dual is True


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


def test_focusing_secondary_keeps_shared_controls_enabled_and_secondary_disabled(
    qtbot, qapp, loaded_csv
):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    _click_card(qapp, cs._secondary_card)

    for b in _control_buttons(cs._secondary_card):
        assert b.isEnabled() is False
    for b in _control_buttons(cs._time_card):
        assert b.isEnabled() is True

    # Click back to primary: shared controls remain live and secondary stays
    # disabled because the secondary toolbar is not visible UI.
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
    assert cs._time_card.btn_subplot.isEnabled() is True
    assert cs._secondary_card.btn_subplot.isEnabled() is False

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


def test_shared_plot_mode_control_targets_focused_secondary(
    qtbot, qapp, loaded_csv
):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    _click_card(qapp, cs._secondary_card)

    _set_checked(w, "speed", "torque")
    w._ch_changed()
    qapp.processEvents()
    assert _has_channel(cs.secondary_canvas(), "speed")
    assert _has_channel(cs.secondary_canvas(), "torque")

    primary_overlay_before = cs.canvas_time._overlay_mode

    cs._time_card.set_plot_mode("overlay")
    qapp.processEvents()

    assert cs._secondary_card.plot_mode() == "overlay"
    assert cs.secondary_canvas()._overlay_mode is True
    assert cs.canvas_time._overlay_mode == primary_overlay_before


def test_secondary_plot_mode_toggle_uses_secondary_view_state_not_active(
    qtbot, qapp, loaded_csv
):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack

    # Move to View 1 (torque), then merge View 0 (speed) into it.
    w._switch_view(1)
    qapp.processEvents()
    w.view_manager.set_split(0)
    qapp.processEvents()

    assert _has_channel(cs.canvas_time, "torque")
    assert not _has_channel(cs.canvas_time, "speed")
    assert _has_channel(cs.secondary_canvas(), "speed")
    assert not _has_channel(cs.secondary_canvas(), "torque")

    _click_card(qapp, cs._secondary_card)
    assert cs.focused_canvas() is cs.secondary_canvas()

    # Toggle the focused secondary pane layout through the shared control.
    cs._time_card.set_plot_mode("overlay")
    qapp.processEvents()

    assert cs._secondary_card.plot_mode() == "overlay"
    assert _has_channel(cs.secondary_canvas(), "speed")
    assert not _has_channel(cs.secondary_canvas(), "torque")
    assert _has_channel(cs.canvas_time, "torque")
    assert not _has_channel(cs.canvas_time, "speed")


def test_programmatic_primary_plot_mode_does_not_rewrite_focused_secondary(
    qtbot, qapp, loaded_csv
):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    _click_card(qapp, cs._secondary_card)

    cs._secondary_card.set_plot_mode("overlay")
    qapp.processEvents()
    _click_card(qapp, cs._time_card)
    _click_card(qapp, cs._secondary_card)
    assert cs._time_card.plot_mode() == "overlay"
    assert cs._secondary_card.plot_mode() == "overlay"

    old = cs.blockSignals(True)
    try:
        cs.set_plot_mode("subplot")
    finally:
        cs.blockSignals(old)
    qapp.processEvents()

    assert cs.plot_mode() == "subplot"
    assert cs._secondary_card.plot_mode() == "overlay"
    assert cs._time_card.plot_mode() == "overlay"


def test_programmatic_primary_cursor_mode_does_not_rewrite_focused_secondary(
    qtbot, qapp, loaded_csv
):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    _click_card(qapp, cs._secondary_card)
    cs._secondary_card.set_cursor_mode("dual")
    qapp.processEvents()
    _click_card(qapp, cs._time_card)
    _click_card(qapp, cs._secondary_card)
    assert cs._time_card.cursor_mode() == "dual"
    assert cs._secondary_card.cursor_mode() == "dual"

    old = cs.blockSignals(True)
    try:
        cs.set_cursor_mode("off")
    finally:
        cs.blockSignals(old)
    qapp.processEvents()

    assert cs.cursor_mode() == "off"
    assert cs._secondary_card.cursor_mode() == "dual"
    assert cs._time_card.cursor_mode() == "dual"
    assert cs.secondary_canvas()._cursor_visible is True
    assert cs.secondary_canvas()._dual is True


# ---------------------------------------------------------------------------
# Follow-focus cursor pill: the secondary pane's readout reaches the shared
# pill (previously wired to the primary canvas only).
# ---------------------------------------------------------------------------

def test_secondary_canvas_cursor_readout_reaches_shared_pill(
    qtbot, qapp, loaded_csv
):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)

    # A readout emitted by the SECONDARY canvas now drives the single pill and
    # anchors it over the secondary pane.
    cs.secondary_canvas().cursor_info.emit("A=2.0s | speed=5")
    qapp.processEvents()
    assert "A=2.0s" in cs.cursor_pill_text()
    assert cs._active_cursor_card is cs._secondary_card

    # A later primary readout takes the pill back (follows whichever pane the
    # cursor is on).
    cs.canvas_time.cursor_info.emit("t=9.0s | speed=1")
    qapp.processEvents()
    assert "t=9.0s" in cs.cursor_pill_text()
    assert cs._active_cursor_card is cs._time_card


def test_pill_formats_detail_using_emitting_pane_cursor_mode(
    qtbot, qapp, loaded_csv
):
    from mf4_analyzer.ui.chart_stack import _CURSOR_HTML_SEP

    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    _click_card(qapp, cs._secondary_card)
    cs._secondary_card.set_cursor_mode("single")
    qapp.processEvents()

    text = _CURSOR_HTML_SEP.join([
        "<span>t=1.0000s</span>",
        "<span>speed=<b>1 rpm</b></span>",
    ])
    # Single-mode readout from the secondary canvas → detail table rendered
    # (formatter reads the SECONDARY pane's cursor mode, not the primary's).
    cs.secondary_canvas().cursor_info.emit(text)
    qapp.processEvents()
    assert cs._pill.has_detail() is True


# ---------------------------------------------------------------------------
# Shared toolbar pan/zoom/back/forward clicks broadcast to both panes while
# side-by-side is active. Home/options remain focused-pane operations.
# ---------------------------------------------------------------------------

def _viewbox_mouse_modes(canvas):
    return [
        ax.view_box.state["mouseMode"]
        for ax in canvas.axes_list
        if getattr(ax, "view_box", None) is not None
    ]


def test_shared_nav_pan_zoom_arm_both_split_panes(qtbot, qapp, loaded_csv):
    import pyqtgraph as pg

    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    shared = cs._time_toolbar  # the (detached) primary card toolbar
    secondary_tb = cs._secondary_card.toolbar

    shared._actions_by_key["zoom"].trigger()
    qapp.processEvents()

    assert shared.mode == "zoom"
    assert secondary_tb.mode == "zoom"
    assert _viewbox_mouse_modes(cs.canvas_time) == [pg.ViewBox.RectMode]
    assert _viewbox_mouse_modes(cs.secondary_canvas()) == [pg.ViewBox.RectMode]

    shared._actions_by_key["pan"].trigger()
    qapp.processEvents()

    assert shared.mode == "pan"
    assert secondary_tb.mode == "pan"
    assert _viewbox_mouse_modes(cs.canvas_time) == [pg.ViewBox.PanMode]
    assert _viewbox_mouse_modes(cs.secondary_canvas()) == [pg.ViewBox.PanMode]


def test_shared_nav_back_forward_runs_each_pane_toolbar(qtbot, qapp, loaded_csv):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    shared = cs._time_toolbar
    secondary_tb = cs._secondary_card.toolbar
    calls = []

    shared.back = lambda: calls.append("primary-back")
    secondary_tb.back = lambda: calls.append("secondary-back")
    shared.forward = lambda: calls.append("primary-forward")
    secondary_tb.forward = lambda: calls.append("secondary-forward")

    shared._actions_by_key["back"].trigger()
    shared._actions_by_key["forward"].trigger()

    assert calls == [
        "primary-back",
        "secondary-back",
        "primary-forward",
        "secondary-forward",
    ]


def test_shared_nav_highlight_reflects_broadcast_mode(qtbot, qapp, loaded_csv):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    shared = cs._time_toolbar

    shared._actions_by_key["zoom"].trigger()

    zoom_btn = shared.widgetForAction(shared._actions_by_key["zoom"])
    pan_btn = shared.widgetForAction(shared._actions_by_key["pan"])
    assert bool(zoom_btn.property("navActive")) is True
    assert bool(pan_btn.property("navActive")) is False


def test_split_save_image_combines_both_panes(
    qtbot, qapp, loaded_csv, monkeypatch, tmp_path
):
    from PyQt5.QtGui import QImage
    from mf4_analyzer.ui.chart_stack import _grab_pixmap_hidpi

    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    out = tmp_path / "split.png"
    monkeypatch.setattr(
        "mf4_analyzer.ui.chart_stack.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(out), "PNG (*.png)"),
    )

    cs._time_toolbar._click_save()
    qapp.processEvents()

    assert out.exists()
    img = QImage(str(out))
    single = _grab_pixmap_hidpi(cs.canvas_time)
    assert img.width() >= single.width() * 1.8


def test_split_copy_image_combines_both_panes(qtbot, qapp, loaded_csv):
    from mf4_analyzer.ui.chart_stack import _grab_pixmap_hidpi

    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    captured = []
    cs.image_captured.connect(captured.append)

    cs._time_card.copy_image_requested.emit()
    qapp.processEvents()

    assert captured
    single = _grab_pixmap_hidpi(cs.canvas_time)
    assert captured[-1].width() >= single.width() * 1.8


def test_shared_options_button_opens_focused_pane(qtbot, qapp, loaded_csv):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    _click_card(qapp, cs._secondary_card)

    opened = []
    cs.secondary_canvas().open_chart_options_dialog = lambda: opened.append("sec")
    cs.canvas_time.open_chart_options_dialog = lambda: opened.append("pri")

    cs._time_card._options_btn.click()
    qapp.processEvents()
    assert opened == ["sec"]

    _click_card(qapp, cs._time_card)
    cs._time_card._options_btn.click()
    qapp.processEvents()
    assert opened == ["sec", "pri"]
