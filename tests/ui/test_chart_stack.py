from pathlib import Path

import numpy as np
import pytest

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QSizePolicy

from mf4_analyzer.ui.chart_stack import ChartStack


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
        "home": "Ctrl+R",
        "back": "Ctrl+Z",
        "forward": "Ctrl+Shift+Z",
        "pan": "Ctrl+G",
        "zoom": "Ctrl+B",
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


def test_time_card_segmented_buttons_have_ctrl_digit_shortcuts(qapp, qtbot):
    """Ctrl+1..5 are wired to 分屏/叠加/游标关/单游标/双游标 buttons and the
    tooltip carries the shortcut in native form."""
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.show()
    qtbot.waitExposed(cs)
    card = cs._time_card
    expected_pairs = [
        (card.btn_subplot,                'Ctrl+1', '分屏'),
        (card.btn_overlay,                'Ctrl+2', '叠加'),
        (card._cursor_buttons['off'],     'Ctrl+3', '游标关'),
        (card._cursor_buttons['single'],  'Ctrl+4', '单游标'),
        (card._cursor_buttons['dual'],    'Ctrl+5', '双游标'),
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
    before_ylim = primary.get_ylim()

    # Frame A → B: selecting 'torque' fires overlay_channel_selected, which
    # TimeChartCard wires to drop the nav toolbar out of pan.
    cs.canvas_time.select_overlay_channel("torque")
    qapp.processEvents()
    assert cs.canvas_time._selected_overlay_channel == "torque"
    # Selection must have dropped pan so a subsequent blank click can
    # reach the deselect gate without being eaten by a pan press.
    assert 'pan' not in str(cs._time_card.toolbar.mode).lower()

    # Y-drag on the selected curve: 40 px downward shifts ylim; X must not
    # move (Fix 2 captures+restores the primary xlim around set_ylim).
    cs.canvas_time._begin_overlay_y_drag_at(start_y_px=100.0)
    moved = cs.canvas_time._apply_overlay_y_drag_at(current_y_px=140.0)
    qapp.processEvents()

    assert moved is True
    assert primary.get_ylim() != pytest.approx(before_ylim)
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
