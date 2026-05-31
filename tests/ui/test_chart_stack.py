from pathlib import Path
import re

import numpy as np
import pytest

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QSizePolicy

from mf4_analyzer.ui.chart_stack import ChartStack, _CURSOR_HTML_SEP


def test_apply_mdi_icons_sets_navactive_property_on_active_button(qtbot):
    from PyQt5.QtWidgets import QToolBar, QToolButton
    from mf4_analyzer.ui.chart_stack import _apply_mdi_icons, _MDI_NAV_ICONS

    assert "pan" in _MDI_NAV_ICONS and "zoom" in _MDI_NAV_ICONS
    toolbar = QToolBar()
    qtbot.addWidget(toolbar)
    pan = toolbar.addAction("Pan")
    pan.setData("pan")
    zoom = toolbar.addAction("Zoom")
    zoom.setData("zoom")

    _apply_mdi_icons(toolbar, active_key="pan")
    pan_btn = toolbar.widgetForAction(pan)
    zoom_btn = toolbar.widgetForAction(zoom)

    assert isinstance(pan_btn, QToolButton)
    assert pan_btn.property("navActive") is True
    assert zoom_btn.property("navActive") is False

    _apply_mdi_icons(toolbar, active_key="zoom")
    assert pan_btn.property("navActive") is False
    assert zoom_btn.property("navActive") is True


def test_chart_stack_has_three_canvases(qapp):
    cs = ChartStack()
    # Four canvases after Task 3 (time / fft / fft_time / order); test name kept for git history.
    assert cs.count() == 4


def test_chart_stack_set_mode(qapp):
    cs = ChartStack()
    cs.set_mode('fft')
    assert cs.current_mode() == 'fft'
    cs.set_mode('order')
    assert cs.current_mode() == 'order'
    cs.set_mode('time')
    assert cs.current_mode() == 'time'


def test_cursor_pill_updates_on_time_signal(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('time')
    cs.canvas_time.cursor_info.emit("t=1.0s | Speed=100")
    assert "t=1.0s" in cs.cursor_pill_text()


def test_single_cursor_pill_uses_vertical_channel_readout(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('time')
    cs.set_cursor_mode('single')

    sep = '<span style="color:#cbd5e1;">  &nbsp;│&nbsp;  </span>'
    cs.canvas_time.cursor_info.emit(
        sep.join([
            '<span style="color:#111827;">t=89.1278s</span>',
            '<span style="color:#ef4444;">[tiadodamping] Rte_=<b>424.2</b></span>',
            '<span style="color:#7c3aed;">[tiadodamping] Rte_=<b>-1.486</b></span>',
        ])
    )

    assert cs._pill.primary_text() == '<span style="color:#111827;">t=89.1278s</span>'
    assert cs._pill.has_detail()
    detail = cs._pill._detail.text()
    assert '<table' in detail
    assert 'padding-top:6px' in detail
    assert '424.2' in detail
    assert '-1.486' in detail
    assert '│' not in detail


def test_cursor_pill_hidden_in_fft_mode(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('fft')
    assert not cs.cursor_pill_visible()


def test_analysis_cards_expose_annotation_toolbar_controls(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    assert not hasattr(cs._time_card, '_annotation_btn')
    for card in (cs._fft_card, cs._fft_time_card, cs._order_card):
        assert hasattr(card, '_annotation_btn')
        assert hasattr(card, '_clear_annotation_btn')
        assert card._annotation_btn.text() == '开启'
        assert card._annotation_btn.toolTip()


def test_annotation_toolbar_controls_are_pushed_right_after_hint_label(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    for card in (cs._fft_card, cs._fft_time_card, cs._order_card):
        loc_label = getattr(card.toolbar, 'locLabel', None)
        actions = card.toolbar.actions()
        hint_index = next(
            i for i, act in enumerate(actions)
            if card.toolbar.widgetForAction(act) is card._hint_label
        )
        spacer_index = next(
            i for i, act in enumerate(actions)
            if card.toolbar.widgetForAction(act) is card._annotation_spacer
        )
        loc_index = next(
            i for i, act in enumerate(actions)
            if card.toolbar.widgetForAction(act) is loc_label
        )
        annotation_index = next(
            i for i, act in enumerate(actions)
            if card.toolbar.widgetForAction(act) is card._annotation_label
        )

        assert loc_index < hint_index < spacer_index < annotation_index
        assert (
            card._annotation_spacer.sizePolicy().horizontalPolicy()
            == QSizePolicy.Expanding
        )
        assert card._annotation_spacer.testAttribute(Qt.WA_StyledBackground)


def test_time_toolbar_controls_are_pushed_right_before_loc_label(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    card = cs._time_card
    loc_label = getattr(card.toolbar, 'locLabel', None)
    actions = card.toolbar.actions()
    spacer_index = next(
        i for i, act in enumerate(actions)
        if card.toolbar.widgetForAction(act) is card._time_controls_spacer
    )
    loc_index = next(
        i for i, act in enumerate(actions)
        if card.toolbar.widgetForAction(act) is loc_label
    )
    subplot_index = next(
        i for i, act in enumerate(actions)
        if card.toolbar.widgetForAction(act) is card.btn_subplot
    )
    cursor_dual_index = next(
        i for i, act in enumerate(actions)
        if card.toolbar.widgetForAction(act) is card._cursor_buttons['dual']
    )

    assert loc_index < spacer_index < subplot_index < cursor_dual_index
    assert loc_label.minimumWidth() == loc_label.maximumWidth()
    assert (
        card._time_controls_spacer.sizePolicy().horizontalPolicy()
        == QSizePolicy.Expanding
    )
    assert card._time_controls_spacer.testAttribute(Qt.WA_StyledBackground)


def test_chart_nav_actions_have_chart_area_shortcuts(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    expected = {
        "home": "Alt+R",
        "back": "Alt+Z",
        "forward": "Alt+Shift+Z",
        "pan": "Alt+G",
        "zoom": "Alt+B",
    }
    for card in (cs._time_card, cs._fft_card, cs._fft_time_card, cs._order_card):
        card_action_keys = {act.data() for act in card.actions()}
        for key, shortcut in expected.items():
            action = next(act for act in card.toolbar.actions() if act.data() == key)
            assert action.shortcut().toString(QKeySequence.PortableText) == shortcut
            assert action.shortcutContext() == Qt.WidgetWithChildrenShortcut
            assert key in card_action_keys
            # Tooltip must include the shortcut in NativeText form so users
            # can discover it without consulting docs.
            assert action.toolTip()
            assert action.shortcut().toString(QKeySequence.NativeText) in action.toolTip()


def test_time_card_segmented_buttons_have_alt_digit_shortcuts(qapp, qtbot):
    """Alt+1..5 are wired to 分屏/叠加/游标关/单游标/双游标 buttons and the
    tooltip carries the shortcut in native form."""
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    card = cs._time_card
    expected_pairs = [
        (card.btn_subplot,                'Alt+1', '分屏'),
        (card.btn_overlay,                'Alt+2', '叠加'),
        (card._cursor_buttons['off'],     'Alt+3', '游标关'),
        (card._cursor_buttons['single'],  'Alt+4', '单游标'),
        (card._cursor_buttons['dual'],    'Alt+5', '双游标'),
    ]
    registered = {
        s.key().toString(): s for s in card._time_button_shortcuts
    }
    for _btn, shortcut, _label in expected_pairs:
        assert shortcut in registered, f"Missing shortcut {shortcut}"
        sc = registered[shortcut]
        assert sc.context() == Qt.WidgetWithChildrenShortcut
    for btn, shortcut, label in expected_pairs:
        native = QKeySequence(shortcut).toString(QKeySequence.NativeText)
        tip = btn.toolTip()
        assert label in tip
        assert native in tip


def test_time_toolbar_loc_label_text_does_not_jostle_right_controls(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(1500, 520)
    cs.show()
    qtbot.waitExposed(cs)

    card = cs._time_card
    loc_label = getattr(card.toolbar, 'locLabel', None)
    before = card._cursor_buttons['dual'].geometry().topLeft()

    loc_label.setText("(x, y) = (-19.0, 1.153)")
    qapp.processEvents()
    after = card._cursor_buttons['dual'].geometry().topLeft()

    assert after == before


def test_chart_toolbar_keeps_back_forward_actions_visible(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(820, 500)
    cs.show()
    qtbot.waitExposed(cs)
    qapp.processEvents()
    card = cs._time_card

    actions = {act.data(): act for act in card.toolbar.actions() if act.data()}
    assert {'back', 'forward'} <= set(actions)
    for key in ('back', 'forward'):
        widget = card.toolbar.widgetForAction(actions[key])
        assert widget is not None
        assert widget.isVisible()
        assert not widget.icon().isNull()


def test_pg_navigation_toolbar_pan_zoom_sets_all_subplot_viewboxes(qapp, qtbot):
    import pyqtgraph as pg

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 640)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')

    t = np.linspace(0.0, 1.0, 80)
    cs.canvas_time.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
        ("temp", True, t, 20.0 + t * 3.0, "#ea580c", "C"),
    ], mode="subplot")
    cs.canvas_time.draw()
    qapp.processEvents()

    handles = list(cs.canvas_time.axes_list)
    assert len(handles) == 3
    view_boxes = [handle.view_box for handle in handles]

    cs._time_card.toolbar.zoom()
    assert str(cs._time_card.toolbar.mode).lower() == 'zoom'
    assert [vb.state['mouseMode'] for vb in view_boxes] == [
        pg.ViewBox.RectMode,
        pg.ViewBox.RectMode,
        pg.ViewBox.RectMode,
    ]

    cs._time_card.toolbar.pan()
    assert str(cs._time_card.toolbar.mode).lower() == 'pan'
    assert [vb.state['mouseMode'] for vb in view_boxes] == [
        pg.ViewBox.PanMode,
        pg.ViewBox.PanMode,
        pg.ViewBox.PanMode,
    ]


def test_pg_zoom_mode_reapplied_to_subplot_viewboxes_after_replot(qapp, qtbot):
    """Bug 3: after activating zoom then re-plotting (e.g. toggling a
    channel rebuilds the ViewBoxes), every subplot ViewBox must STILL be
    RectMode. The toolbar mode stays 'zoom' but plot_channels builds fresh
    PanMode ViewBoxes, so the mode must be re-applied on rebuild."""
    import pyqtgraph as pg

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 640)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode("time")

    t = np.linspace(0.0, 1.0, 80)
    rows = [
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
        ("temp", True, t, 20.0 + t * 3.0, "#ea580c", "C"),
    ]
    cs.canvas_time.plot_channels(rows, mode="subplot")
    qapp.processEvents()

    cs._time_card.toolbar.zoom()
    assert str(cs._time_card.toolbar.mode).lower() == "zoom"

    # REPLOT — rebuilds every ViewBox at PanMode default.
    cs.canvas_time.plot_channels(rows, mode="subplot")
    qapp.processEvents()

    assert str(cs._time_card.toolbar.mode).lower() == "zoom", (
        "replot must not change the toolbar mode"
    )
    modes = [h.view_box.state["mouseMode"] for h in cs.canvas_time.axes_list]
    assert modes == [pg.ViewBox.RectMode] * len(modes), (
        f"zoom mode not re-applied to rebuilt subplot ViewBoxes; got {modes}"
    )


def test_pg_zoom_mode_reaches_overlay_x_master_viewbox(qapp, qtbot):
    """Bug 3: in overlay mode the aux ViewBoxes are mouse-disabled; the
    real mouse-capture surface is the X-master ViewBox. Activating zoom must
    set the X-master ViewBox to RectMode."""
    import pyqtgraph as pg

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 640)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode("time")

    t = np.linspace(0.0, 1.0, 80)
    rows = [
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
    ]
    cs.canvas_time.plot_channels(rows, mode="overlay")
    qapp.processEvents()

    cs._time_card.toolbar.zoom()
    qapp.processEvents()

    master_vb = cs.canvas_time._x_master_handle.view_box
    assert master_vb.state["mouseMode"] == pg.ViewBox.RectMode, (
        "zoom mode did not reach the overlay X-master ViewBox"
    )

    # Toggling back to pan must reach it too.
    cs._time_card.toolbar.pan()
    qapp.processEvents()
    assert master_vb.state["mouseMode"] == pg.ViewBox.PanMode


class _FakeMenuEvent:
    """Minimal pyqtgraph mouse-event stand-in for ``raiseContextMenu``."""

    def __init__(self, accepted_item):
        self.acceptedItem = accepted_item

    def screenPos(self):
        from PyQt5.QtCore import QPointF

        return QPointF(0.0, 0.0)


def _open_redesigned_menu(canvas, view_box, monkeypatch):
    """Drive the real ``raiseContextMenu`` path (assemble + reshape per design
    A–D) without showing a window; return the reshaped QMenu."""
    from PyQt5.QtWidgets import QMenu

    captured = {}

    def _fake_popup(self, *_a, **_k):
        captured["menu"] = self

    monkeypatch.setattr(QMenu, "popup", _fake_popup, raising=True)
    view_box.raiseContextMenu(_FakeMenuEvent(view_box))
    return captured.get("menu")


def _mouse_mode_actions(menu):
    """Return (pan_action, zoom_action) from the reshaped 鼠标操作 submenu."""
    mouse_menu = next(
        a.menu() for a in menu.actions()
        if a.text().replace("&", "").strip() == "鼠标操作"
    )
    acts = mouse_menu.actions()
    return acts[0], acts[1]


def test_pg_context_menu_mouse_mode_syncs_toolbar_both_directions(
    qapp, qtbot, monkeypatch
):
    """Design D single source of truth: selecting a 鼠标操作 menu item drives
    the SAME toolbar mode state machine (and its ViewBoxes), and re-opening
    the menu reflects whatever the toolbar currently is — both directions."""
    import pyqtgraph as pg

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 640)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode("time")

    t = np.linspace(0.0, 1.0, 80)
    cs.canvas_time.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
    ], mode="subplot")
    qapp.processEvents()

    toolbar = cs._time_card.toolbar
    vb = cs.canvas_time.axes_list[0].view_box
    view_boxes = [h.view_box for h in cs.canvas_time.axes_list]

    # Default card start is pan.
    assert str(toolbar.mode).lower() == "pan"

    # ---- Direction 1: menu → toolbar ----
    menu = _open_redesigned_menu(cs.canvas_time, vb, monkeypatch)
    pan_act, zoom_act = _mouse_mode_actions(menu)
    # Checkmark reflects current toolbar state (pan).
    assert pan_act.isChecked() and not zoom_act.isChecked()
    # Selecting 框选 must flip the SHARED toolbar state + the ViewBoxes.
    zoom_act.trigger()
    qapp.processEvents()
    assert str(toolbar.mode).lower() == "zoom"
    assert [b.state["mouseMode"] for b in view_boxes] == [pg.ViewBox.RectMode] * len(view_boxes)

    # ---- Direction 2: toolbar → menu ----
    toolbar.pan()
    qapp.processEvents()
    assert str(toolbar.mode).lower() == "pan"
    menu2 = _open_redesigned_menu(cs.canvas_time, vb, monkeypatch)
    pan_act2, zoom_act2 = _mouse_mode_actions(menu2)
    assert pan_act2.isChecked() and not zoom_act2.isChecked()


def _flush_history_debounce(toolbar, qapp):
    """Fire the toolbar's coalesce timer immediately so a simulated gesture
    is committed to the history stack without waiting wall-clock ms."""
    timer = getattr(toolbar, "_history_timer", None)
    if timer is not None and timer.isActive():
        timer.stop()
        toolbar._commit_pending_view()
    qapp.processEvents()


def _simulate_pan(canvas, toolbar, qapp, lo, hi):
    """Drive a user pan: set the primary range then emit the ViewBox's
    manual-range signal (what a real drag emits) and flush the debounce."""
    primary = canvas._primary_xaxis_ax
    primary.set_xlim(lo, hi)
    vb = primary.view_box
    vb.sigRangeChangedManually.emit(vb.state["mouseEnabled"])
    _flush_history_debounce(toolbar, qapp)


def test_pg_toolbar_back_forward_tracks_pan_history(qapp, qtbot):
    """Task 1: a completed pan/zoom gesture appends the resulting view; back()
    steps to the previous view, forward() returns, and a new gesture after
    back() truncates the forward history. matplotlib-toolbar parity."""
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 640)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode("time")

    t = np.linspace(0.0, 10.0, 200)
    cs.canvas_time.plot_channels([
        ("speed", True, t, np.sin(t), "#1769e0", "rpm"),
        ("torque", True, t, np.cos(t), "#ef4444", "Nm"),
    ], mode="subplot")
    qapp.processEvents()
    toolbar = cs._time_card.toolbar
    canvas = cs.canvas_time
    primary = canvas._primary_xaxis_ax

    baseline = primary.get_xlim()

    # Gesture 1: pan to a sub-window.
    _simulate_pan(canvas, toolbar, qapp, 2.0, 4.0)
    assert primary.get_xlim() == pytest.approx((2.0, 4.0))

    # Gesture 2: pan to another window.
    _simulate_pan(canvas, toolbar, qapp, 6.0, 8.0)
    assert primary.get_xlim() == pytest.approx((6.0, 8.0))

    # back() → previous view (2,4); back() again → baseline.
    toolbar.back()
    qapp.processEvents()
    assert primary.get_xlim() == pytest.approx((2.0, 4.0))
    toolbar.back()
    qapp.processEvents()
    assert primary.get_xlim() == pytest.approx(baseline)

    # forward() walks back to (2,4) then (6,8).
    toolbar.forward()
    qapp.processEvents()
    assert primary.get_xlim() == pytest.approx((2.0, 4.0))
    toolbar.forward()
    qapp.processEvents()
    assert primary.get_xlim() == pytest.approx((6.0, 8.0))

    # back() once, then a NEW gesture must truncate the forward history.
    toolbar.back()
    qapp.processEvents()
    assert primary.get_xlim() == pytest.approx((2.0, 4.0))
    _simulate_pan(canvas, toolbar, qapp, 1.0, 3.0)
    toolbar.forward()  # no-op: forward truncated by the new gesture
    qapp.processEvents()
    assert primary.get_xlim() == pytest.approx((1.0, 3.0))


def test_pg_toolbar_back_survives_plot_channels_rebuild(qapp, qtbot):
    """Task 1: history is keyed by channel name + range, not by a live axis
    handle, so a back() target still restores after a plot_channels rebuild
    swaps the underlying ViewBoxes for fresh objects."""
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 640)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode("time")

    t = np.linspace(0.0, 10.0, 200)
    rows = [
        ("speed", True, t, np.sin(t), "#1769e0", "rpm"),
        ("torque", True, t, np.cos(t), "#ef4444", "Nm"),
    ]
    cs.canvas_time.plot_channels(rows, mode="subplot")
    qapp.processEvents()
    toolbar = cs._time_card.toolbar
    canvas = cs.canvas_time

    baseline = canvas._primary_xaxis_ax.get_xlim()
    _simulate_pan(canvas, toolbar, qapp, 3.0, 5.0)

    # Rebuild — fresh ViewBoxes; the stale-handle snapshot would no-op here.
    cs.canvas_time.plot_channels(rows, mode="subplot")
    qapp.processEvents()
    # The rebuilt primary handle is a NEW object.
    new_primary = canvas._primary_xaxis_ax

    toolbar.back()
    qapp.processEvents()
    assert new_primary.get_xlim() == pytest.approx(baseline), (
        "back() after rebuild must restore the pre-pan range on the fresh handle"
    )


def test_pg_toolbar_home_keeps_subplot_x_ranges_identical_after_auto_range(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode("time")
    t1 = np.linspace(0.0, 1.0, 50)
    t2 = np.linspace(2.0, 4.0, 50)
    cs.canvas_time.plot_channels([
        ("a", True, t1, np.sin(t1), "#1769e0", "u"),
        ("b", True, t2, np.cos(t2), "#ef4444", "u"),
    ], mode="subplot")
    for handle in cs.canvas_time.axes_list:
        handle.set_xlim(0.25, 0.75)

    cs._time_card.toolbar.home()

    ranges = [handle.get_xlim() for handle in cs.canvas_time.axes_list]
    assert ranges[0] == pytest.approx((0.0, 4.0))
    assert ranges[1] == pytest.approx(ranges[0])


def test_pg_toolbar_home_restores_global_x_and_y_from_raw_data(qapp, qtbot):
    """Bug 4: Home must restore BOTH X (raw union) and Y (raw full min/max
    per channel) in one click. The hot-path PlotDataItem holds only the
    viewport-clipped envelope, so an autoRange()-based home read Y from the
    clipped window and left Y stuck near the previous zoom."""
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 640)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode("time")

    t = np.linspace(0.0, 10.0, 4000)
    rows = [
        ("a", True, t, 100.0 * np.sin(t), "#1769e0", "u", "fid"),
        ("b", True, t, 5.0 + 2.0 * np.cos(t), "#ef4444", "u", "fid"),
    ]
    cs.canvas_time.plot_channels(rows, mode="subplot")
    qapp.processEvents()

    # Zoom into a narrow X window and drive a real envelope refresh so each
    # PlotDataItem holds ONLY the clipped envelope for [4.0, 4.5].
    for h in cs.canvas_time.axes_list:
        h.set_xlim(4.0, 4.5)
    cs.canvas_time._flush_pending_refresh()
    qapp.processEvents()
    # Also pin a tiny Y window far from the data extents.
    for h in cs.canvas_time.axes_list:
        h.set_ylim(0.0, 0.01)
    qapp.processEvents()

    cs._time_card.toolbar.home()
    qapp.processEvents()

    # X must be the raw union for every axis.
    for h in cs.canvas_time.axes_list:
        xlo, xhi = h.get_xlim()
        assert xlo <= 0.05, f"X low not restored to ~0.0; got {xlo}"
        assert xhi >= 9.95, f"X high not restored to ~10.0; got {xhi}"

    # Y must span each channel's RAW full min/max (pyqtgraph adds a little
    # padding, so the restored range must CONTAIN the raw extents).
    handle0 = cs.canvas_time.axes_list[0]
    raw_a = cs.canvas_time.channel_data["a"][1]
    ylo0, yhi0 = handle0.get_ylim()
    assert ylo0 <= float(raw_a.min()) and yhi0 >= float(raw_a.max()), (
        f"Home left channel 'a' Y at ({ylo0}, {yhi0}); raw extents are "
        f"({raw_a.min()}, {raw_a.max()}) — Y was read from the clipped envelope"
    )

    handle1 = cs.canvas_time.axes_list[1]
    raw_b = cs.canvas_time.channel_data["b"][1]
    ylo1, yhi1 = handle1.get_ylim()
    assert ylo1 <= float(raw_b.min()) and yhi1 >= float(raw_b.max())


def test_chart_choice_checked_qss_uses_visible_blue_selection_tokens():
    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
    match = re.search(
        r'QWidget#chartToolbar QPushButton\[role="chart-choice"\]:checked\s*\{(?P<body>[^}]*)\}',
        qss,
        flags=re.S,
    )
    assert match is not None
    body = match.group('body')

    assert 'background-color: #ffffff;' not in body
    assert 'background-color: #e8efff;' in body
    assert 'border-color: #2563eb;' in body
    assert 'color: #2563eb;' in body


def test_time_toolbar_controls_fit_when_inspector_narrows_chart(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(820, 500)
    cs.show()
    qtbot.waitExposed(cs)
    qapp.processEvents()

    card = cs._time_card
    controls = [
        card.btn_subplot,
        card.btn_overlay,
        card._cursor_buttons['off'],
        card._cursor_buttons['single'],
        card._cursor_buttons['dual'],
    ]
    right_edge = card.toolbar.rect().right()
    for button in controls:
        assert button.isVisible()
        assert button.geometry().right() <= right_edge


def test_cursor_off_clears_dual_cursor_pill(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')

    cs.set_cursor_mode('dual')
    cs.canvas_time.cursor_info.emit("A=1.0s")
    cs.canvas_time.dual_cursor_info.emit("<b>stats</b>")
    assert cs.cursor_pill_visible()

    cs._time_card.set_cursor_mode('off')

    assert not cs.cursor_pill_visible()
    assert cs.cursor_pill_text() == ""


def test_single_cursor_pill_detail_uses_row_spacing(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('time')
    cs.set_cursor_mode('single')

    text = _CURSOR_HTML_SEP.join([
        '<span>t=1.0000s</span>',
        '<span style="color:#1769e0;">speed=<b>1 rpm</b></span>',
        '<span style="color:#ef4444;">torque=<b>2 Nm</b></span>',
    ])

    primary, detail = cs._format_cursor_info_for_pill(text)

    assert primary == '<span>t=1.0000s</span>'
    assert '<table' in detail
    assert 'padding-top:6px' in detail
    assert 'speed=' in detail and 'torque=' in detail


def test_copy_card_image_renders_at_hidpi_scale(qapp, qtbot):
    """Spec §E: the toolbar copy path must request a hi-DPI render (scale
    > 1) of the canvas so the clipboard bitmap is crisp. Geometry gate:
    the copied pixmap is magnified vs a 1× grab of the same canvas."""
    from PyQt5.QtWidgets import QApplication

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')
    t = np.linspace(0, 1, 200)
    cs.canvas_time.plot_channels(
        [("speed", True, t, np.sin(t * 20), "#1769e0", "rpm", "f")]
    )
    QApplication.processEvents()

    base = cs.canvas_time.grab_pixmap(scale=1.0)
    assert not base.isNull()

    captured = []
    cs.image_captured.connect(captured.append)

    cs._copy_card_image(cs._time_card)
    QApplication.processEvents()
    assert captured, "copy path did not emit captured pixmap"
    pix = captured[-1]
    assert pix is not None and not pix.isNull(), "clipboard pixmap is null"
    # Hi-DPI: clipboard bitmap is wider than a 1× grab of the same canvas.
    assert pix.width() > base.width(), (
        f"copy pixmap width {pix.width()} not magnified vs 1x base {base.width()}"
    )


def test_copy_card_image_composites_scaled_cursor_pill(qapp, qtbot, monkeypatch):
    """Spec §E: the copy path must still composite the cursor pill, and
    BOTH its position and size must scale by the same factor so it lines
    up on the magnified bitmap. We intercept the QPainter.drawPixmap call
    to capture the scaled pill rect actually drawn."""
    from PyQt5.QtGui import QPainter
    from PyQt5.QtWidgets import QApplication

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')
    t = np.linspace(0, 1, 200)
    cs.canvas_time.plot_channels(
        [("speed", True, t, np.sin(t * 20), "#1769e0", "rpm", "f")]
    )
    QApplication.processEvents()

    # Make the pill visible and place it well inside the canvas so the
    # overlap branch fires.
    cs._pill.set_primary('<span style="color:#111827;">t=0.5s</span>')
    cs._pill.setVisible(True)
    cs._pill.mark_user_placed(True)
    cs._pill.move(40, 40)
    QApplication.processEvents()

    drawn = []
    real_draw = QPainter.drawPixmap

    def _spy_draw(self, *args):
        # signature used by the copy path: drawPixmap(QRect, QPixmap)
        drawn.append(args)
        return real_draw(self, *args)

    monkeypatch.setattr(QPainter, "drawPixmap", _spy_draw)

    captured = []
    cs.image_captured.connect(captured.append)

    cs._copy_card_image(cs._time_card)
    QApplication.processEvents()

    assert captured, "copy path did not emit captured pixmap"
    assert drawn, "copy path did not composite the cursor pill"
    rect = drawn[-1][0]
    pill = cs._pill
    # The composited pill rect must be scaled (> 1×) relative to the
    # unscaled pill geometry so it lines up on the magnified bitmap.
    assert rect.width() > pill.width(), (
        f"composited pill width {rect.width()} not scaled vs {pill.width()}"
    )
    assert rect.height() > pill.height(), (
        f"composited pill height {rect.height()} not scaled vs {pill.height()}"
    )


def test_copy_card_image_composites_cursor_pill_inside_hidpi_pixmap(
    qapp, qtbot, monkeypatch
):
    """On macOS Retina, QPixmap painting uses logical DPR coordinates. The
    copied image is normalized before pill compositing so the pill is painted
    inside the final pixel buffer rather than off the right edge."""
    from PyQt5.QtGui import QColor, QPixmap
    from PyQt5.QtWidgets import QApplication

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')
    QApplication.processEvents()

    source = QPixmap(1000, 600)
    source.fill(QColor("#ffffff"))
    source.setDevicePixelRatio(2.0)

    def _fake_grab(scale=1.0):
        return QPixmap(source)

    red_pill = QPixmap(120, 60)
    red_pill.fill(QColor("#ff0000"))

    monkeypatch.setattr(cs.canvas_time, "grab_pixmap", _fake_grab)
    monkeypatch.setattr(cs, "_grab_pill_scaled", lambda _scale: red_pill)

    cs._pill.resize(80, 40)
    cs._pill.setVisible(True)
    cs._pill.mark_user_placed(True)
    canvas_origin = cs.canvas_time.mapTo(cs.stack, cs.canvas_time.rect().topLeft())
    cs._pill.move(canvas_origin.x() + 400, canvas_origin.y() + 20)

    captured = []
    cs.image_captured.connect(captured.append)
    cs._copy_card_image(cs._time_card)

    assert captured
    pix = captured[-1]
    assert pix.devicePixelRatioF() == 1.0
    img = pix.toImage()
    red_samples = 0
    for x in range(0, img.width(), 10):
        for y in range(0, img.height(), 10):
            color = img.pixelColor(x, y)
            if color.red() > 200 and color.green() < 80 and color.blue() < 80:
                red_samples += 1
    assert red_samples > 0


def test_save_figure_uses_hidpi_scale(qapp, qtbot, monkeypatch, tmp_path):
    """Spec §E: save_figure must request a hi-DPI render (scale > 1)."""
    from PyQt5.QtWidgets import QFileDialog

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')
    cs.canvas_time.plot_channels(
        [("speed", True, np.linspace(0, 1, 100), np.zeros(100), "#1769e0", "rpm", "f")]
    )

    out = str(tmp_path / "out.png")
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (out, "PNG (*.png)"))
    )
    captured = {}
    real_grab = cs._time_card.canvas.grab_pixmap

    def _spy_grab(scale=1.0):
        captured["scale"] = scale
        return real_grab(scale=scale)

    monkeypatch.setattr(cs._time_card.canvas, "grab_pixmap", _spy_grab)
    cs._time_card.toolbar.save_figure()

    assert captured.get("scale", 1.0) > 1.0, (
        f"save_figure used scale={captured.get('scale')}, expected hi-DPI > 1"
    )
    assert Path(out).exists(), "save_figure did not write the file"


def test_overlay_curve_drag_leaves_toolbar_idle_during_selection(qapp, qtbot):
    """Selecting a curve in overlay mode must drop pan (so blank clicks can
    later deselect), and a Y-drag on the selected curve must shift its ylim
    while X stays pinned. The pyqtgraph canvas has no pixel curve-select
    gesture, so we drive selection via the public ``select_overlay_channel``
    seam (established PG-test convention); the toolbar pan-drop and Y-drag
    are the real observable user outcomes."""
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')

    t = np.linspace(0.0, 1.0, 80)
    cs.canvas_time.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
    ], mode="overlay")
    cs.canvas_time.draw()
    assert 'pan' in str(cs._time_card.toolbar.mode).lower()

    primary = cs.canvas_time._primary_xaxis_ax
    # Pin xlim explicitly so the Y-drag X-stability assertion is byte-exact
    # (an unset xlim leaves pyqtgraph X auto-range on, which would drift).
    primary.set_xlim(0.0, 1.0)
    primary.set_ylim(-2.0, 8.0)
    qapp.processEvents()
    before_xlim = primary.get_xlim()
    before_primary_ylim = primary.get_ylim()

    # Frame A → B: selecting 'torque' fires overlay_channel_selected, which
    # TimeChartCard wires to drop the nav toolbar out of pan.
    cs.canvas_time.select_overlay_channel("torque")
    qapp.processEvents()
    assert cs.canvas_time._selected_overlay_channel == "torque"
    selected_axis = cs.canvas_time._channel_lines["torque"][0]
    before_selected_ylim = selected_axis.get_ylim()
    # Selection must have dropped pan so a subsequent blank click can
    # reach the deselect gate without being eaten by a pan press.
    assert 'pan' not in str(cs._time_card.toolbar.mode).lower()

    # Y-drag on the selected curve: 40 px downward shifts ylim; X must not
    # move (Fix 2 captures+restores the primary xlim around set_ylim).
    cs.canvas_time._begin_overlay_y_drag_at(start_y_px=100.0)
    moved = cs.canvas_time._apply_overlay_y_drag_at(current_y_px=140.0)
    qapp.processEvents()

    assert moved is True
    assert selected_axis.get_ylim() != pytest.approx(before_selected_ylim)
    assert primary.get_ylim() == pytest.approx(before_primary_ylim)
    # X is byte-stable after a Y-only drag (Fix 2).
    assert primary.get_xlim() == pytest.approx(before_xlim, abs=0.0, rel=0.0)
    # Drag does not auto-restore pan.
    assert 'pan' not in str(cs._time_card.toolbar.mode).lower()


def test_overlay_blank_click_clears_selection_after_curve_drag(qapp, qtbot):
    """After a curve selection, a deselect interaction clears the selection
    (emitting overlay_channel_selected(None)) and X stays unchanged. The PG
    canvas has no wired blank-click gesture, so deselect is driven via the
    public ``select_overlay_channel(None)`` seam (PG-test convention)."""
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')

    t = np.linspace(0.0, 1.0, 80)
    cs.canvas_time.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
    ], mode="overlay")
    cs.canvas_time.draw()
    assert 'pan' in str(cs._time_card.toolbar.mode).lower()

    primary = cs.canvas_time._primary_xaxis_ax
    primary.set_xlim(0.0, 1.0)
    qapp.processEvents()

    events = []
    cs.canvas_time.overlay_channel_selected.connect(events.append)

    cs.canvas_time.select_overlay_channel("torque")
    qapp.processEvents()
    assert cs.canvas_time._selected_overlay_channel == "torque"
    assert events[-1] == "torque"
    assert 'pan' not in str(cs._time_card.toolbar.mode).lower()

    before_xlim = primary.get_xlim()

    # Deselect (the blank-click outcome): selection clears, X unchanged.
    cs.canvas_time.select_overlay_channel(None)
    qapp.processEvents()

    assert cs.canvas_time._selected_overlay_channel is None
    assert events[-1] is None
    assert len(events) == 2  # exactly select + deselect
    assert primary.get_xlim() == pytest.approx(before_xlim, abs=0.0, rel=0.0)
    # Deselect does not re-engage pan.
    assert 'pan' not in str(cs._time_card.toolbar.mode).lower()


def test_dblclick_chart_options_does_not_leave_pan_drag_active(qapp, qtbot, monkeypatch):
    """A native double-click over a subplot opens the chart-options dialog
    for THAT subplot's axis handle (Fix 1), and leaves no stuck drag: xlim
    is unchanged and the ViewBox is back at its default (PanMode) mouse
    mode. Driven with QTest.mouseDClick now that the gesture is wired via a
    viewport event filter; the dialog open is observed by monkeypatching
    the handle-aware entry point."""
    from PyQt5.QtTest import QTest

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')

    t = np.linspace(0.0, 1.0, 80)
    cs.canvas_time.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
    ], mode="overlay")
    cs.canvas_time.draw()
    assert 'pan' in str(cs._time_card.toolbar.mode).lower()

    primary = cs.canvas_time._primary_xaxis_ax
    # Pin xlim so the post-double-click X-stability check is byte-exact.
    primary.set_xlim(0.0, 1.0)
    qapp.processEvents()
    before_xlim = primary.get_xlim()

    from mf4_analyzer.ui import _axis_interaction

    captured = []

    def fake_edit(parent, handle):
        # The dialog must be opened for an axis handle the canvas owns.
        assert handle in cs.canvas_time.axes_list
        captured.append(handle)
        return True

    monkeypatch.setattr(
        _axis_interaction, 'edit_chart_options_dialog', fake_edit, raising=False
    )

    viewport = cs.canvas_time._glw.viewport()
    center = viewport.rect().center()
    QTest.mouseDClick(viewport, Qt.LeftButton, Qt.NoModifier, center)
    qapp.processEvents()

    # The chart-options open path fired exactly once for a real axis handle.
    assert len(captured) == 1
    # No stuck pan-drag: the canvas's overlay-drag bookkeeping is cleared
    # and the ViewBox is back at its default PanMode mouse mode.
    assert cs.canvas_time._overlay_y_drag_start is None
    assert not cs.canvas_time._chart_options_opening
    import pyqtgraph as pg
    assert primary.view_box.state['mouseMode'] == pg.ViewBox.PanMode
    # xlim byte-stable across the double-click.
    assert primary.get_xlim() == pytest.approx(before_xlim, abs=0.0, rel=0.0)


def test_dblclick_chart_options_restores_pan_without_starting_span_selector(
    qapp, qtbot, monkeypatch
):
    """A double-click opens the chart-options dialog AND must not arm a span
    selector. The PG design keeps ``span_selector`` None by contract
    (enable_span_selector stores the callback but never installs a widget),
    so we assert the double-click opens options while span_selector stays
    None and the view returns to its default interactive mouse mode."""
    from PyQt5.QtTest import QTest

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 520)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')

    t = np.linspace(0.0, 1.0, 80)
    cs.canvas_time.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
    ], mode="subplot")
    # enable_span_selector stores the callback but installs NO widget — the
    # always-on SpanSelector was retired (design §4.2). span_selector is None.
    cs.canvas_time.enable_span_selector(lambda _xmin, _xmax: None)
    cs.canvas_time.draw()
    assert 'pan' in str(cs._time_card.toolbar.mode).lower()
    assert cs.canvas_time.span_selector is None

    primary = cs.canvas_time._primary_xaxis_ax
    primary.set_xlim(0.0, 1.0)
    qapp.processEvents()
    before_xlim = primary.get_xlim()

    from mf4_analyzer.ui import _axis_interaction

    captured = []
    monkeypatch.setattr(
        _axis_interaction,
        'edit_chart_options_dialog',
        lambda parent, handle: (captured.append(handle), True)[1],
        raising=False,
    )

    viewport = cs.canvas_time._glw.viewport()
    center = viewport.rect().center()
    QTest.mouseDClick(viewport, Qt.LeftButton, Qt.NoModifier, center)
    qapp.processEvents()

    # Options opened for the subplot axis.
    assert len(captured) == 1
    assert captured[-1] in cs.canvas_time.axes_list
    # Double-click did NOT create a span selector (PG design keeps it None).
    assert cs.canvas_time.span_selector is None
    # View returned to default interactive state, no stuck drag.
    import pyqtgraph as pg
    assert primary.view_box.state['mouseMode'] == pg.ViewBox.PanMode
    assert not cs.canvas_time._chart_options_opening
    assert primary.get_xlim() == pytest.approx(before_xlim, abs=0.0, rel=0.0)


def test_dblclick_second_subplot_opens_options_for_that_axis(qapp, qtbot, monkeypatch):
    """Targeting test (per signal-processing/2026-05-19-branch-reached-is-not-
    behavior-correct): with ≥3 subplots, double-clicking the SECOND subplot's
    plot face must open chart-options for THAT subplot's ``PgAxisHandle`` — by
    object identity, not membership in ``axes_list`` — and double-clicking the
    THIRD must open the third's, proving the viewport→scene hit-test really
    discriminates subplots rather than always returning the primary/index-1.

    Geometry is computed from real ViewBox ``sceneBoundingRect()`` centers
    mapped back to viewport pixels via the GraphicsView's ``mapFromScene``
    (the exact inverse of the production ``mapToScene`` path), so the pixel
    coords are derived from live pyqtgraph geometry, not guessed."""
    from PyQt5.QtTest import QTest

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 640)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode('time')

    t = np.linspace(0.0, 1.0, 80)
    # subplot mode requires len(vis) > 1; plot 3 channels so axes_list has 3
    # distinct PgAxisHandles each with its own ViewBox.
    cs.canvas_time.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
        ("temp", True, t, 20.0 + t * 3.0, "#ea580c", "C"),
    ], mode="subplot")
    cs.canvas_time.draw()
    qapp.processEvents()

    handles = list(cs.canvas_time.axes_list)
    assert len(handles) == 3, "expected one PgAxisHandle per subplot channel"
    # Each subplot must own a distinct ViewBox with a distinct scene region,
    # otherwise the targeting assertion below would be vacuous.
    rects = [h.view_box.sceneBoundingRect() for h in handles]
    centers = [r.center() for r in rects]
    ys = sorted(c.y() for c in centers)
    assert ys[0] < ys[1] < ys[2], "subplot ViewBox centers must be vertically distinct"

    from mf4_analyzer.ui import _axis_interaction

    glw = cs.canvas_time._glw
    viewport = glw.viewport()

    def dblclick_subplot_center(idx):
        """Double-click at the viewport pixel for the center of subplot idx's
        ViewBox, mapping the live scene center back through the GraphicsView."""
        scene_center = handles[idx].view_box.sceneBoundingRect().center()
        viewport_pt = glw.mapFromScene(scene_center)
        QTest.mouseDClick(viewport, Qt.LeftButton, Qt.NoModifier, viewport_pt)
        qapp.processEvents()

    captured = []
    monkeypatch.setattr(
        _axis_interaction,
        'edit_chart_options_dialog',
        lambda parent, handle: (captured.append(handle), True)[1],
        raising=False,
    )

    # --- Double-click the SECOND subplot --------------------------------
    dblclick_subplot_center(1)
    assert len(captured) == 1
    # Identity, not membership: it must be the SAME handle (and same
    # underlying ViewBox) as the second subplot, not merely "a handle".
    assert captured[-1] is handles[1]
    assert captured[-1].view_box is handles[1].view_box
    # And explicitly NOT the primary/first or third.
    assert captured[-1] is not handles[0]
    assert captured[-1] is not handles[2]

    # --- Double-click the THIRD subplot ---------------------------------
    # Repeat for a third subplot so we know the resolver is not just always
    # returning index 1.
    dblclick_subplot_center(2)
    assert len(captured) == 2
    assert captured[-1] is handles[2]
    assert captured[-1].view_box is handles[2].view_box
    assert captured[-1] is not handles[1]

    # --- And the FIRST subplot for completeness -------------------------
    dblclick_subplot_center(0)
    assert len(captured) == 3
    assert captured[-1] is handles[0]
    assert captured[-1].view_box is handles[0].view_box


def test_annotation_toolbar_spacer_has_toolbar_background_rule():
    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")

    assert "QWidget#chartToolbar QWidget#chartAnnotationSpacer" in qss
    assert "background-color: #ffffff;" in qss
    assert "QWidget#chartToolbar QWidget#chartTimeControlsSpacer" in qss


def test_chart_toolbar_disabled_nav_buttons_have_visible_style():
    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")

    assert "QWidget#chartToolbar QToolButton:disabled" in qss
    assert "border: 1px solid #e5eaf2;" in qss


def test_chart_cards_have_chart_options_toolbar_button(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    for card in (cs._time_card, cs._fft_card, cs._fft_time_card, cs._order_card):
        assert hasattr(card, '_options_btn')
        assert card._options_btn.objectName() == 'chartOptionsButton'
        assert card._options_btn.toolTip() == '图表选项'
        assert card._options_btn.autoRaise()


def test_chart_options_toolbar_button_delegates_to_canvas(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    called = []

    def fake_open():
        called.append(True)
        return True

    cs.canvas_fft.open_chart_options_dialog = fake_open
    cs._fft_card._options_btn.click()

    assert called == [True]


def test_chart_toolbar_removes_native_customize_button(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)

    for card in (cs._time_card, cs._fft_card, cs._fft_time_card, cs._order_card):
        for act in card.toolbar.actions():
            assert (act.text() or '').strip().lower() != 'customize'
            assert 'edit axis, curve and image parameters' not in (
                act.toolTip() or ''
            ).lower()


def test_annotation_toolbar_toggles_canvas_modes(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    seen = []
    cs.annotation_enabled_changed.connect(lambda mode, enabled: seen.append((mode, enabled)))

    cs._fft_card._annotation_btn.click()
    assert cs.canvas_fft._remark_enabled is True
    assert cs._fft_card._annotation_btn.text() == '关闭'

    cs._fft_time_card._annotation_btn.click()
    assert cs.canvas_fft_time._remark_enabled is True
    assert cs._fft_time_card._annotation_btn.text() == '关闭'

    cs._order_card._annotation_btn.click()
    assert cs.canvas_order._remark_enabled is True
    assert cs._order_card._annotation_btn.text() == '关闭'

    assert ('fft', True) in seen
    assert ('fft_time', True) in seen
    assert ('order', True) in seen


def test_stats_strip_update(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    cs.stats_strip.update_stats({
        'ch1': {'min': 0, 'max': 10, 'mean': 5, 'rms': 6, 'std': 2, 'p2p': 10, 'unit': 'V'}
    })
    assert 'ch1' in cs.stats_strip._lbl_summary.text()


def test_stats_strip_toggle(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    assert not cs.stats_strip._panel.isVisible()
    cs.stats_strip.toggle()
    qapp.processEvents()
    assert cs.stats_strip._panel.isVisible()


# ---- TimeChartCard (2026-04-24 UI cleanup) ----

def test_chart_stack_exposes_plot_mode_api(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    assert cs.plot_mode() == 'subplot'
    with qtbot.waitSignal(cs.plot_mode_changed, timeout=200) as bl:
        cs.set_plot_mode('overlay')
    assert bl.args == ['overlay']
    assert cs.plot_mode() == 'overlay'


def test_chart_stack_exposes_cursor_mode_api(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    # default must be 'off' per spec §8
    assert cs.cursor_mode() == 'off'
    with qtbot.waitSignal(cs.cursor_mode_changed, timeout=200) as bl:
        cs.set_cursor_mode('single')
    assert bl.args == ['single']
    assert cs.cursor_mode() == 'single'


def test_time_chart_card_has_segmented_controls(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack, TimeChartCard
    cs = ChartStack()
    qtbot.addWidget(cs)
    # First card in the stack is the time-domain card.
    card = cs.stack.widget(0)
    assert isinstance(card, TimeChartCard)
    # Five segmented buttons on the card toolbar (post-i18n labels):
    # 分屏 / 叠加 / 游标关 / 单游标 / 双游标
    texts = {b.text() for b in card.findChildren(type(card.btn_subplot))}
    assert {'分屏', '叠加', '游标关', '单游标', '双游标'} <= texts


def test_time_chart_card_removes_subplots_config_button(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    card = cs.stack.widget(0)
    # No QAction on the native nav toolbar should map to 'configure_subplots'.
    native_tb = card.toolbar
    for act in native_tb.actions():
        # The action object name / icon text varies; check both.
        assert act.text().lower() not in ('subplots', 'configure subplots')


def test_fft_card_also_strips_subplots_button(qapp, qtbot):
    """Subplots action is stripped from every card since tight_layout is the default."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    fft_card = cs.stack.widget(1)
    for act in fft_card.toolbar.actions():
        assert act.text().lower() not in ('subplots', 'configure subplots')


def test_set_plot_mode_noop_does_not_emit(qapp, qtbot):
    """set_plot_mode with the current mode should not re-emit."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    # default is 'subplot'; calling with 'subplot' again should not emit.
    assert cs.plot_mode() == 'subplot'
    # qtbot.waitSignal with timeout=50 and check=[] — use a different approach:
    received = []
    cs.plot_mode_changed.connect(lambda m: received.append(m))
    cs.set_plot_mode('subplot')
    assert received == []
    # sanity: a real change does still emit
    cs.set_plot_mode('overlay')
    assert received == ['overlay']


def test_set_cursor_mode_noop_does_not_emit(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    assert cs.cursor_mode() == 'off'
    received = []
    cs.cursor_mode_changed.connect(lambda m: received.append(m))
    cs.set_cursor_mode('off')
    assert received == []
    cs.set_cursor_mode('dual')
    assert received == ['dual']


def test_chart_stack_exposes_fft_time_card(qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack

    stack = ChartStack()
    qtbot.addWidget(stack)
    stack.set_mode('fft_time')

    assert stack.current_mode() == 'fft_time'
    assert stack.canvas_fft_time is not None
    assert stack.stack.currentWidget() is stack._fft_time_card


# ---- Task 5: SpectrogramCanvas rendering, cursor, hover ----

def test_spectrogram_canvas_plots_main_and_slice(qtbot):
    import numpy as np
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.canvases import SpectrogramCanvas

    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    result = SpectrogramResult(
        times=np.array([0.1, 0.2, 0.3]),
        frequencies=np.array([10.0, 20.0, 30.0]),
        amplitude=np.array([[1, 2, 3], [2, 4, 6], [1, 3, 5]], dtype=np.float32),
        params=SpectrogramParams(fs=100.0, nfft=8, window='hanning', overlap=0.5),
        channel_name='demo',
        unit='V',
    )

    canvas.plot_result(result, amplitude_mode='amplitude', cmap='viridis')

    assert len(canvas.fig.axes) >= 2
    assert canvas.selected_index() == 0


def test_spectrogram_canvas_applies_dynamic_and_freq_range(qtbot):
    import numpy as np
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.canvases import SpectrogramCanvas

    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    # Magnitudes spanning ~120 dB.
    amp = np.array([[1e-6, 1e-3], [1e-3, 1.0], [1.0, 0.1]], dtype=np.float32)
    result = SpectrogramResult(
        times=np.array([0.1, 0.2]),
        frequencies=np.array([10.0, 100.0, 200.0]),
        amplitude=amp,
        params=SpectrogramParams(fs=400.0, nfft=8, db_reference=1.0),
        channel_name='demo',
    )

    canvas.plot_result(
        result,
        amplitude_mode='amplitude_db',
        cmap='turbo',
        z_auto=False,
        z_floor=-60.0,
        z_ceiling=0.0,
        freq_range=(0.0, 150.0),
    )

    im = canvas._ax_spec.images[0]
    vmin, vmax = im.get_clim()
    assert (vmax - vmin) == 60.0          # z_floor=-60 / z_ceiling=0 applied
    assert canvas._ax_spec.get_ylim()[1] <= 150.0  # freq_range applied


def test_spectrogram_canvas_emits_cursor_info_on_hover(qtbot):
    import numpy as np
    from matplotlib.backend_bases import MouseEvent
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.canvases import SpectrogramCanvas

    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    result = SpectrogramResult(
        times=np.array([0.0, 0.1, 0.2]),
        frequencies=np.array([0.0, 50.0, 100.0]),
        amplitude=np.ones((3, 3), dtype=np.float32),
        params=SpectrogramParams(fs=200.0, nfft=8),
        channel_name='demo',
    )
    canvas.plot_result(result, amplitude_mode='amplitude')
    canvas.draw()

    seen = []
    canvas.cursor_info.connect(seen.append)

    # Synthesize hover at data coords (t=0.1, f=50).
    ax = canvas._ax_spec
    x_pix, y_pix = ax.transData.transform((0.1, 50.0))
    evt = MouseEvent('motion_notify_event', canvas, x_pix, y_pix)
    evt.inaxes = ax
    evt.xdata = 0.1
    evt.ydata = 50.0
    canvas._on_motion(evt)

    assert seen, "cursor_info should fire on hover"
    assert '0.1' in seen[-1] or 't=0.1' in seen[-1]


# ---- Task 9: SpectrogramCanvas export pixmaps ----

def test_spectrogram_canvas_export_pixmaps(qtbot):
    import numpy as np
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.canvases import SpectrogramCanvas

    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    result = SpectrogramResult(
        times=np.array([0.1, 0.2]),
        frequencies=np.array([10.0, 20.0]),
        amplitude=np.ones((2, 2), dtype=np.float32),
        params=SpectrogramParams(fs=100.0, nfft=8),
        channel_name='demo',
    )
    canvas.plot_result(result, amplitude_mode='amplitude')

    assert not canvas.grab_full_view().isNull()
    assert not canvas.grab_main_chart().isNull()


# ---- Task 2.7: Chinese segmented buttons + idle hint ----

def test_time_card_segmented_buttons_chinese(qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('time')
    card = cs._time_card
    assert card.btn_subplot.text() == '分屏'
    assert card.btn_overlay.text() == '叠加'
    assert card._cursor_buttons['off'].text() == '游标关'
    assert card._cursor_buttons['single'].text() == '单游标'
    assert card._cursor_buttons['dual'].text() == '双游标'


def test_tool_hints_idle_mentions_dblclick():
    from mf4_analyzer.ui.chart_stack import _TOOL_HINTS
    # _TOOL_HINTS values are (title, detail) tuples since MDI icon refactor;
    # the double-click chart-options phrase lives in the detail string.
    assert '双击图面' in _TOOL_HINTS[''][1]
    assert '图表选项' in _TOOL_HINTS[''][1]


# ---- Bottom hint bar (Persistent + Context layers) ----

def test_bottom_hint_bar_persistent_always_present(qapp):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    for card in (cs._time_card, cs._fft_card, cs._fft_time_card, cs._order_card):
        # Bar exists, is visible, and the persistent label spells the three
        # always-on shortcuts.
        assert card._hint_bar is not None
        assert card._hint_persistent is not None
        text = card._hint_persistent.text()
        assert "Ctrl" in text
        assert "Shift" in text
        assert "双击图面" in text
        assert "图表选项" in text


def test_bottom_hint_bar_context_pan_default(qapp):
    """Default after construction is pan mode → context label = pan hint."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    card = cs._time_card
    assert "平移模式" in card._hint_context.text()


def test_bottom_hint_bar_context_switches_with_cursor_mode(qapp):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    card = cs._time_card
    # cursor=single → 单游标 hint
    card.set_cursor_mode('single')
    assert "单游标" in card._hint_context.text()
    # cursor=dual → 双游标 hint
    card.set_cursor_mode('dual')
    assert "双游标" in card._hint_context.text()
    # cursor=off → fall back to current toolbar mode hint (pan by default)
    card.set_cursor_mode('off')
    assert "平移模式" in card._hint_context.text()


def test_bottom_hint_bar_spectrogram_hint(qapp):
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    fft_time = cs._fft_time_card
    # Spectrogram card defaults to pan mode (toolbar.pan() in base init), so
    # the toolbar-mode hint wins. Force toolbar mode off to surface the
    # spectrogram-specific hint and confirm the override path.
    fft_time.toolbar.mode = ''  # type: ignore[attr-defined]
    fft_time._refresh_bottom_hint()
    assert "谱图" in fft_time._hint_context.text()


def test_bottom_hint_bar_idle_for_base_card_with_no_mode(qapp):
    """Plain _ChartCard (e.g. fft / order) with no toolbar mode shows empty."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    card = cs._fft_card
    card.toolbar.mode = ''  # type: ignore[attr-defined]
    card._refresh_bottom_hint()
    assert card._hint_context.text() == ''


def test_bottom_hint_bar_constants_exposed():
    """Module-level dict MUST expose the documented context keys verbatim."""
    from mf4_analyzer.ui.chart_stack import (
        _BOTTOM_HINT_CONTEXT, _BOTTOM_HINT_PERSISTENT,
    )
    assert "Ctrl" in _BOTTOM_HINT_PERSISTENT
    assert "Shift" in _BOTTOM_HINT_PERSISTENT
    assert "双击图面" in _BOTTOM_HINT_PERSISTENT
    assert "图表选项" in _BOTTOM_HINT_PERSISTENT
    for key in ('pan', 'zoom', 'cursor_single', 'cursor_dual',
                'spectrogram', 'idle'):
        assert key in _BOTTOM_HINT_CONTEXT
    assert _BOTTOM_HINT_CONTEXT['idle'] == ''


def test_bottom_hint_bar_does_not_break_existing_top_hint(qapp):
    """Sanity: existing in-toolbar _hint_label remains untouched."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    cs = ChartStack()
    card = cs._time_card
    # Default mode is pan → top hint label paints '移动曲线' title.
    assert "移动曲线" in card._hint_label.text()
