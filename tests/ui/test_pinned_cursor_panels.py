"""Pinned CursorPill chrome, independence, consume, and undo (Task 2 / A09)."""
from __future__ import annotations

import numpy as np
from PyQt5 import sip
from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QCursor, QKeyEvent
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.chart_stack.cursor_display import live_pin_hint_text
from mf4_analyzer.ui.cursor_display_model import CursorDisplayChannel
from mf4_analyzer.ui.pinned_cursor_state import (
    DEFAULT_ANCHOR,
    collection_from_dict,
    collection_to_dict,
    empty_collection,
    next_record,
)
from mf4_analyzer.ui_kit.popup_shell import POPUP_SHELL_FLAGS


def _plot_speed(canvas):
    t = np.linspace(0.0, 1.0, 200)
    canvas.plot_channels(
        [
            (
                "speed",
                True,
                t,
                np.sin(2 * np.pi * t),
                "#1769e0",
                "rpm",
                "fid-a",
            ),
        ],
        mode="overlay",
    )


def _plot_four_subplots(canvas):
    t = np.linspace(0.0, 1.0, 200)
    canvas.plot_channels(
        [
            ("speed", True, t, np.sin(2 * np.pi * t), "#1769e0", "rpm", "fid-a"),
            ("torque", True, t, np.cos(2 * np.pi * t), "#16a34a", "Nm", "fid-a"),
            ("current", True, t, np.sin(4 * np.pi * t), "#d97706", "A", "fid-a"),
            ("angle", True, t, np.cos(4 * np.pi * t), "#7c3aed", "deg", "fid-a"),
        ],
        mode="subplot",
    )


def _make_stack(qtbot, qapp, *, mode="single"):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(1100, 560)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode("time")
    cs.set_cursor_mode_for_canvas(cs.canvas_time, mode)
    _plot_speed(cs.canvas_time)
    qapp.processEvents()
    return cs


def _viewport(canvas):
    return canvas._glw.viewport()


def _aim(qtbot, canvas, frac, controller):
    vp = _viewport(canvas)
    local = QPoint(max(8, int(vp.width() * frac)), max(8, int(vp.height() * 0.45)))
    global_pos = vp.mapToGlobal(local)
    QCursor.setPos(global_pos)
    qtbot.mouseMove(vp, local)
    controller._last_mouse_global = global_pos
    QApplication.processEvents()
    return local


def _press_p(target):
    override = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_P, Qt.NoModifier, "p")
    press = QKeyEvent(QEvent.KeyPress, Qt.Key_P, Qt.NoModifier, "p")
    QApplication.sendEvent(target, override)
    QApplication.sendEvent(target, press)
    QApplication.processEvents()
    return override


def _records(cs, canvas=None):
    canvas = cs.canvas_time if canvas is None else canvas
    collection = cs.pinned_cursors_for_canvas(canvas)
    return () if collection is None else collection.records


def _panel_expansion_by_ordinal(cs, canvas=None):
    return {
        record.ordinal: record.panel_expanded
        for record in _records(cs, canvas)
    }


def _visible_pinned_ordinals(cs, canvas=None):
    canvas = cs.canvas_time if canvas is None else canvas
    return {
        pill.ordinal()
        for pill in cs._pinned_cursors.pills_for(canvas)
        if pill.pin_role() == "pinned" and pill.isVisible()
    }


def _label_for_record(cs, record_id, canvas=None):
    canvas = cs.canvas_time if canvas is None else canvas
    labels = [
        label
        for label in cs._pinned_cursors.axis_labels_for(canvas)
        if record_id in label.record_ids()
    ]
    assert len(labels) == 1, (
        f"expected one Pn control for {record_id}, got {len(labels)}"
    )
    return labels[0]


def _click_record_label(qtbot, cs, record_id, canvas=None):
    label = _label_for_record(cs, record_id, canvas)
    qtbot.mouseClick(label, Qt.LeftButton, pos=label.rect().center())
    QApplication.processEvents()


def _pinned_pill_for_ordinal(cs, ordinal, canvas=None):
    canvas = cs.canvas_time if canvas is None else canvas
    for pill in cs._pinned_cursors.pills_for(canvas):
        if pill.pin_role() == "pinned" and pill.ordinal() == ordinal:
            return pill
    raise AssertionError(f"missing pinned pill P{ordinal}")


def _open_title_menu(pill, qapp):
    opener = getattr(pill, "_on_title_menu_clicked", None)
    assert callable(opener)
    opener()
    qapp.processEvents()
    menu = getattr(pill, "_title_menu", None)
    assert menu is not None
    assert not sip.isdeleted(menu)
    return menu


def _title_menu_action(menu, text):
    for action in menu.actions():
        if action.text() == text:
            return action
    raise AssertionError(
        f"missing {text!r}: {[action.text() for action in menu.actions()]}"
    )


def _is_descendant_of(widget, ancestor):
    while widget is not None:
        if widget is ancestor:
            return True
        widget = widget.parentWidget()
    return False


def _live_cursor_item_groups(canvas):
    cursor = canvas._cursor
    return (
        tuple(cursor._cursor_line_items or ()),
        tuple(cursor._cursor_a_items or ()),
        tuple(cursor._cursor_b_items or ()),
        tuple(cursor._dual_cursor_extreme_markers or ()),
    )


def _assert_live_cursor_items_hidden(canvas, *, require_hover=True):
    hover, a_items, b_items, markers = _live_cursor_item_groups(canvas)
    if require_hover:
        assert hover, "expected live InfiniteLines after hover/pin"
    for item in (*hover, *a_items, *b_items, *markers):
        assert item.isVisible() is False


def _assert_overlay_pin_lines_present(cs, canvas=None):
    canvas = cs.canvas_time if canvas is None else canvas
    records = _records(cs, canvas)
    assert records
    lines = canvas._pinned_overlay.lines_for(records[0].record_id)
    assert lines
    assert all(line.isVisible() for line in lines)
    return lines


def test_a09_full_mini_independent_drag_close_and_reuse_ordinal(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    vp = _viewport(cs.canvas_time)
    _aim(qtbot, cs.canvas_time, 0.3, cs._pinned_cursors)
    _press_p(vp)
    _aim(qtbot, cs.canvas_time, 0.7, cs._pinned_cursors)
    _press_p(vp)
    records = _records(cs)
    assert len(records) == 2
    _click_record_label(qtbot, cs, records[0].record_id)
    _click_record_label(qtbot, cs, records[1].record_id)
    pills = {
        pill.ordinal(): pill
        for pill in cs._pinned_cursors.pills_for(cs.canvas_time)
    }
    assert set(pills) == {1, 2}
    first, second = pills[1], pills[2]
    assert first.display_mode() == "mini"
    assert second.display_mode() == "mini"
    second._toggle_mode()
    qapp.processEvents()
    assert first.display_mode() == "mini"
    assert second.display_mode() == "full"
    cs._pill._toggle_mode()
    qapp.processEvents()
    assert first.display_mode() == "mini"
    assert second.display_mode() == "full"

    _click_record_label(qtbot, cs, records[1].record_id)
    qapp.processEvents()
    assert _panel_expansion_by_ordinal(cs)[2] is False
    _click_record_label(qtbot, cs, records[1].record_id)
    qapp.processEvents()
    assert _panel_expansion_by_ordinal(cs)[2] is True
    assert pills[2].display_mode() == "full"

    x_before = _records(cs)[0].x
    start = first.rect().center()
    qtbot.mousePress(first, Qt.LeftButton, pos=start)
    qtbot.mouseMove(first, start + QPoint(-40, 30))
    qtbot.mouseRelease(first, Qt.LeftButton, pos=start + QPoint(-40, 30))
    qapp.processEvents()
    assert _records(cs)[0].x == x_before
    assert first.is_user_placed()

    closed_id = _records(cs)[1].record_id
    closed_ordinal = _records(cs)[1].ordinal
    heard = []
    cs.pin_feedback.connect(heard.append)
    second.close_requested.emit()
    qapp.processEvents()
    assert len(_records(cs)) == 1
    assert closed_id not in {item.record_id for item in _records(cs)}
    assert any(text.startswith("已关闭") for text in heard)
    assert not hasattr(cs._pinned_cursors, "undo_close")
    assert all(item.ordinal != closed_ordinal or item.record_id != closed_id
               for item in _records(cs))

    first_record = next(item for item in _records(cs) if item.ordinal == 1)
    first_pill = next(
        pill for pill in cs._pinned_cursors.pills_for(cs.canvas_time)
        if pill.ordinal() == 1
    )
    _aim(qtbot, cs.canvas_time, 0.3, cs._pinned_cursors)
    first_pill.unpin_requested.emit()
    qapp.processEvents()
    assert first_record.record_id not in {
        item.record_id for item in _records(cs)
    }
    assert cs._pill.isVisible()
    assert cs._pill.pin_role() == "live"
    _press_p(vp)
    reused = [item for item in _records(cs) if item.ordinal == 1]
    assert reused, _records(cs)


def test_new_pins_start_collapsed_but_keep_their_pn_controls(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    vp = _viewport(cs.canvas_time)
    _aim(qtbot, cs.canvas_time, 0.3, cs._pinned_cursors)
    _press_p(vp)
    _aim(qtbot, cs.canvas_time, 0.7, cs._pinned_cursors)
    _press_p(vp)

    records = _records(cs)
    assert [record.ordinal for record in records] == [1, 2]
    assert _panel_expansion_by_ordinal(cs) == {1: False, 2: False}
    assert _visible_pinned_ordinals(cs) == set()
    for record in records:
        assert _label_for_record(cs, record.record_id).isVisible()


def test_pn_clicks_toggle_only_the_target_panel(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    vp = _viewport(cs.canvas_time)
    for fraction in (0.2, 0.5, 0.8):
        _aim(qtbot, cs.canvas_time, fraction, cs._pinned_cursors)
        _press_p(vp)

    records = _records(cs)
    assert [record.ordinal for record in records] == [1, 2, 3]
    assert _panel_expansion_by_ordinal(cs) == {
        1: False, 2: False, 3: False,
    }

    _click_record_label(qtbot, cs, records[0].record_id)
    assert _panel_expansion_by_ordinal(cs) == {
        1: True, 2: False, 3: False,
    }
    assert _visible_pinned_ordinals(cs) == {1}

    _click_record_label(qtbot, cs, records[1].record_id)
    assert _panel_expansion_by_ordinal(cs) == {
        1: True, 2: True, 3: False,
    }
    assert _visible_pinned_ordinals(cs) == {1, 2}

    _click_record_label(qtbot, cs, records[0].record_id)
    assert _panel_expansion_by_ordinal(cs) == {
        1: False, 2: True, 3: False,
    }
    assert _visible_pinned_ordinals(cs) == {2}


def test_three_expanded_pins_use_separate_actual_card_rects_and_hits(qapp, qtbot):
    """A09: the real stack hit target must agree with the painted card."""
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    t = np.linspace(0.0, 1.0, 200)
    canvas.plot_channels(
        [
            (
                "VeryLongPowertrainSignal_EngineSpeed_Validated",
                True, t, np.sin(2 * np.pi * t), "#1769e0", "rpm", "fid-a",
            ),
            (
                "VeryLongPowertrainSignal_RequestedTorque_Validated",
                True, t, np.cos(2 * np.pi * t), "#16a34a", "Nm", "fid-a",
            ),
        ],
        mode="overlay",
    )
    qapp.processEvents()
    vp = _viewport(canvas)
    for fraction in (0.18, 0.50, 0.82):
        _aim(qtbot, canvas, fraction, cs._pinned_cursors)
        _press_p(vp)
    records = _records(cs)
    assert len(records) == 3
    for record in records:
        _click_record_label(qtbot, cs, record.record_id)

    pills = sorted(
        (
            pill for pill in cs._pinned_cursors.pills_for(canvas)
            if pill.isVisible()
        ),
        key=lambda pill: pill.ordinal(),
    )
    assert len(pills) == 3
    assert all(record.anchor == DEFAULT_ANCHOR for record in _records(cs))
    for index, pill in enumerate(pills):
        assert pill.safe_rect().contains(pill.geometry()), pill.geometry()
        for other in pills[index + 1:]:
            assert not pill.geometry().intersects(other.geometry())
        hit = cs.stack.childAt(pill.geometry().center())
        assert hit is not None
        assert _is_descendant_of(hit, pill), (
            f"stack.childAt({pill.geometry().center()}) hit {hit!r}, "
            f"not P{pill.ordinal()}"
        )


def test_expanding_a_new_card_does_not_move_a_user_placed_card(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    vp = _viewport(canvas)
    for fraction in (0.3, 0.7):
        _aim(qtbot, canvas, fraction, cs._pinned_cursors)
        _press_p(vp)
    first_record, second_record = _records(cs)
    _click_record_label(qtbot, cs, first_record.record_id)
    first = next(
        pill for pill in cs._pinned_cursors.pills_for(canvas)
        if pill.ordinal() == first_record.ordinal
    )
    start = first.rect().center()
    qtbot.mousePress(first, Qt.LeftButton, pos=start)
    qtbot.mouseRelease(first, Qt.LeftButton, pos=start + QPoint(-34, 24))
    qapp.processEvents()
    assert first.is_user_placed()
    placed = first.geometry()
    _click_record_label(qtbot, cs, second_record.record_id)
    assert first.geometry() == placed
    assert _records(cs)[0].anchor != DEFAULT_ANCHOR


def test_panel_expansion_defaults_and_explicit_restore(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    _aim(qtbot, cs.canvas_time, 0.45, cs._pinned_cursors)
    _press_p(_viewport(cs.canvas_time))
    record = _records(cs)[0]

    legacy_payload = collection_to_dict(
        cs.pinned_cursors_for_canvas(cs.canvas_time)
    )
    assert "panel_expanded" not in legacy_payload["records"][0]
    legacy = collection_from_dict(legacy_payload)
    assert legacy.records[0].panel_expanded is False

    malformed_payload = collection_to_dict(legacy)
    malformed_payload["records"][0]["panel_expanded"] = "false"
    malformed = collection_from_dict(malformed_payload)
    assert malformed.records[0].panel_expanded is False

    expanded_payload = collection_to_dict(legacy)
    expanded_payload["records"][0]["panel_expanded"] = True
    restored = collection_from_dict(collection_to_dict(
        collection_from_dict(expanded_payload)
    ))
    assert restored.records[0].record_id == record.record_id
    assert restored.records[0].panel_expanded is True
    assert collection_to_dict(restored)["records"][0]["panel_expanded"] is True

    cs.set_pinned_cursors_for_canvas(cs.canvas_time, restored)
    qapp.processEvents()
    assert _panel_expansion_by_ordinal(cs) == {1: True}
    assert _visible_pinned_ordinals(cs) == {1}


def test_live_consumed_after_single_pin_returns_on_next_move(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    vp = _viewport(canvas)
    empty_info = []

    def _note_empty_info(text):
        if text == "":
            empty_info.append(text)

    canvas.cursor_info.connect(_note_empty_info)
    _aim(qtbot, canvas, 0.4, cs._pinned_cursors)
    _press_p(vp)
    assert not cs._pill.isVisible()
    assert cs._pinned_cursors.is_live_suppressed(canvas)
    assert canvas._cursor._cursor_visible is True
    assert "" not in empty_info
    _assert_overlay_pin_lines_present(cs, canvas)
    _assert_live_cursor_items_hidden(canvas)

    channel = CursorDisplayChannel(
        identity=("fid-a", "speed"),
        source_label="",
        channel_label="speed",
        current_value=1.5,
        unit_suffix=" rpm",
    )
    canvas.single_cursor_rows.emit((channel,))
    qapp.processEvents()
    assert cs._pill.isVisible()
    assert cs._pill.pin_role() == "live"
    assert not cs._pinned_cursors.is_live_suppressed(canvas)
    assert live_pin_hint_text("single") == "按 P 固定当前读数"
    assert live_pin_hint_text("dual") == "按 P 固定此组"
    assert live_pin_hint_text("dual", dual_complete=False) == ""
    assert cs._pill._pin_btn.isVisibleTo(cs._pill)
    assert cs._pill._pin_btn.toolTip() == live_pin_hint_text("single")

    canvas._cursor._last_t = 0
    _aim(qtbot, canvas, 0.55, cs._pinned_cursors)
    hover_items = tuple(canvas._cursor._cursor_line_items or ())
    assert hover_items
    assert any(item.isVisible() for item in hover_items)


def test_subplot_pin_hides_live_lines_keeps_overlay_pins(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _plot_four_subplots(canvas)
    qapp.processEvents()
    _aim(qtbot, canvas, 0.35, cs._pinned_cursors)
    _press_p(_viewport(canvas))
    records = _records(cs)
    assert records
    assert canvas._cursor._cursor_visible is True
    pin_lines = _assert_overlay_pin_lines_present(cs, canvas)
    hover_items = tuple(canvas._cursor._cursor_line_items or ())
    assert hover_items
    assert len(hover_items) == len(pin_lines)
    _assert_live_cursor_items_hidden(canvas)
    overlay_ids = {id(line) for line in pin_lines}
    for item in hover_items:
        assert id(item) not in overlay_ids
        assert item.isVisible() is False


def test_dual_pin_hides_live_and_keeps_placement(qapp, qtbot):
    cs = _make_stack(qtbot, qapp, mode="dual")
    cursor = cs.canvas_time._cursor
    cursor._ax = 0.2
    cursor._bx = 0.8
    cursor._redraw_dual_placement_items()
    cs.canvas_time._cursor._emit_dual_cursor_html()
    qapp.processEvents()
    assert cs._pill.isVisible()
    _aim(qtbot, cs.canvas_time, 0.5, cs._pinned_cursors)
    _press_p(_viewport(cs.canvas_time))
    assert _records(cs)
    assert not cs._pill.isVisible()
    placement = cs.canvas_time.snapshot_cursor_placement()
    assert placement["ax"] == 0.2
    assert placement["bx"] == 0.8
    assert cursor._placing in {"A", "B"}
    assert cursor._cursor_visible is True
    _assert_overlay_pin_lines_present(cs)
    _assert_live_cursor_items_hidden(cs.canvas_time)


def test_hidden_owner_does_not_clear_other_live_pill(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    cs.set_cursor_mode_for_canvas(cs.canvas_time, "single")
    channel = CursorDisplayChannel(
        identity=("fid-a", "speed"),
        source_label="",
        channel_label="speed",
        current_value=2.0,
        unit_suffix=" rpm",
    )
    cs.canvas_time.single_cursor_rows.emit((channel,))
    cs.canvas_time.cursor_info.emit(
        '<span style="color:#111827;">t=0.5000s</span>'
    )
    qapp.processEvents()
    assert cs._pill.isVisible()
    live_text = cs._pill.primary_text()

    cs.canvas_fft.cursor_info.emit("")
    qapp.processEvents()
    assert cs._pill.isVisible()
    assert cs._pill.primary_text() == live_text


def test_live_p_button_pins_current_readout_not_button_coords(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    local = _aim(qtbot, cs.canvas_time, 0.3, cs._pinned_cursors)
    domain = cs._pinned_cursors._domain_for(cs.canvas_time)
    expected_x = cs._pinned_cursors._physical_x(cs.canvas_time, domain, local)
    assert expected_x is not None
    sync = getattr(cs.canvas_time, "sync_single_cursor_line", None)
    if callable(sync):
        sync(expected_x)
    channel = CursorDisplayChannel(
        identity=("fid-a", "speed"),
        source_label="",
        channel_label="speed",
        current_value=1.5,
        unit_suffix=" rpm",
    )
    cs.canvas_time.single_cursor_rows.emit((channel,))
    qapp.processEvents()
    assert cs._pill.isVisible()
    assert cs._pill._pin_btn.isVisibleTo(cs._pill)
    qtbot.mouseClick(cs._pill._pin_btn, Qt.LeftButton)
    qapp.processEvents()
    records = _records(cs)
    assert len(records) == 1
    assert abs(records[0].x - expected_x) < 1e-6
    assert records[0].presentation == "mini"


def test_dual_incomplete_hides_live_p_button(qapp, qtbot):
    cs = _make_stack(qtbot, qapp, mode="dual")
    cursor = cs.canvas_time._cursor
    cursor._ax = 0.2
    cursor._bx = None
    cursor._emit_dual_cursor_html()
    qapp.processEvents()
    assert cs._pill.isVisible()
    assert live_pin_hint_text("dual", dual_complete=False) == ""
    assert not cs._pill._pin_btn.isVisibleTo(cs._pill)


def test_expanded_pn_chip_has_filled_chrome_and_collapse_tooltip(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    vp = _viewport(cs.canvas_time)
    _aim(qtbot, cs.canvas_time, 0.3, cs._pinned_cursors)
    _press_p(vp)
    records = _records(cs)
    label = _label_for_record(cs, records[0].record_id)
    qapp.processEvents()
    idle = label.grab().toImage().pixelColor(label.width() // 2, label.height() // 2)
    assert label.panel_open() is False
    assert "展开" in label.toolTip()
    _click_record_label(qtbot, cs, records[0].record_id)
    qapp.processEvents()
    label = _label_for_record(cs, records[0].record_id)
    assert label.panel_open() is True
    assert "收起" in label.toolTip()
    opened = label.grab().toImage().pixelColor(label.width() // 2, label.height() // 2)
    assert opened != idle
    _click_record_label(qtbot, cs, records[0].record_id)
    qapp.processEvents()
    label = _label_for_record(cs, records[0].record_id)
    assert label.panel_open() is False
    assert "展开" in label.toolTip()


def test_pinned_title_uses_menu_not_duplicate_html_or_pin_button(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    _aim(qtbot, cs.canvas_time, 0.35, cs._pinned_cursors)
    _press_p(_viewport(cs.canvas_time))
    record = _records(cs)[0]
    _click_record_label(qtbot, cs, record.record_id)
    qapp.processEvents()
    pill = _pinned_pill_for_ordinal(cs, record.ordinal)
    menu_btn = pill._title_menu_btn
    assert menu_btn.isVisibleTo(pill)
    assert menu_btn.text() == f"P{record.ordinal} ▾"
    assert not pill._pin_btn.isVisibleTo(pill)
    assert pill._close_btn.isVisibleTo(pill)
    assert pill._close_btn.toolTip() == f"删除 P{record.ordinal}"
    assert pill._close_btn.accessibleName() == f"删除 P{record.ordinal}"
    primary = pill.primary_text()
    assert f"P{record.ordinal}" not in primary
    assert "t=" in primary
    leading = pill._title_leading_chrome_width()
    trailing = pill._title_trailing_chrome_width()
    assert leading > 0
    assert pill._title_chrome_width() == leading + trailing
    assert pill._primary.contentsMargins().left() == leading
    menu_rect = menu_btn.geometry()
    close_rect = pill._close_btn.geometry()
    mode_rect = pill._mode_control.geometry()
    assert menu_rect.left() >= 0
    assert not menu_rect.intersects(close_rect)
    assert not menu_rect.intersects(mode_rect)
    assert not close_rect.intersects(mode_rect)


def test_title_menu_collapse_only_keeps_pin_and_reopens_from_pn(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _aim(qtbot, canvas, 0.3, cs._pinned_cursors)
    _press_p(_viewport(canvas))
    record = _records(cs)[0]
    record_id = record.record_id
    _click_record_label(qtbot, cs, record_id)
    qapp.processEvents()
    pill = _pinned_pill_for_ordinal(cs, 1)
    menu = _open_title_menu(pill, qapp)
    assert menu.parent() is pill
    assert menu.testAttribute(Qt.WA_TranslucentBackground)
    assert (menu.windowFlags() & POPUP_SHELL_FLAGS) == POPUP_SHELL_FLAGS
    labels = [action.text() for action in menu.actions() if action.text()]
    assert labels[:2] == ["收起面板，保留 Pin", "取消固定，继续调整"]
    assert f"删除 P{record.ordinal}" in labels
    _title_menu_action(menu, "收起面板，保留 Pin").trigger()
    qapp.processEvents()
    assert _panel_expansion_by_ordinal(cs)[1] is False
    assert record_id in {item.record_id for item in _records(cs)}
    assert _label_for_record(cs, record_id).isVisible()
    overlay_lines = canvas._pinned_overlay.lines_for(record_id)
    assert overlay_lines
    assert all(line.isVisible() for line in overlay_lines)
    cs._pinned_cursors.collapse_record_panel(canvas, record_id)
    qapp.processEvents()
    assert _panel_expansion_by_ordinal(cs)[1] is False
    _click_record_label(qtbot, cs, record_id)
    qapp.processEvents()
    assert _panel_expansion_by_ordinal(cs)[1] is True
    assert 1 in _visible_pinned_ordinals(cs)


def test_title_menu_unpin_restores_live_and_reuses_ordinal(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    vp = _viewport(cs.canvas_time)
    _aim(qtbot, cs.canvas_time, 0.32, cs._pinned_cursors)
    _press_p(vp)
    record = _records(cs)[0]
    _click_record_label(qtbot, cs, record.record_id)
    qapp.processEvents()
    pill = _pinned_pill_for_ordinal(cs, 1)
    menu = _open_title_menu(pill, qapp)
    _title_menu_action(menu, "取消固定，继续调整").trigger()
    qapp.processEvents()
    assert _records(cs) == ()
    assert cs._pill.isVisible()
    assert cs._pill.pin_role() == "live"
    assert cs._pill._pin_btn.isVisibleTo(cs._pill)
    _aim(qtbot, cs.canvas_time, 0.32, cs._pinned_cursors)
    _press_p(vp)
    reused = _records(cs)
    assert len(reused) == 1
    assert reused[0].ordinal == 1


def test_title_menu_unpin_restores_dual_and_reuses_ordinal(qapp, qtbot):
    cs = _make_stack(qtbot, qapp, mode="dual")
    cursor = cs.canvas_time._cursor
    cursor._ax = 0.2
    cursor._bx = 0.8
    cursor._redraw_dual_placement_items()
    cs.canvas_time._cursor._emit_dual_cursor_html()
    qapp.processEvents()
    _aim(qtbot, cs.canvas_time, 0.5, cs._pinned_cursors)
    _press_p(_viewport(cs.canvas_time))
    record = _records(cs)[0]
    cs._pinned_cursors.toggle_record_panel(cs.canvas_time, record.record_id)
    qapp.processEvents()
    pill = _pinned_pill_for_ordinal(cs, 1)
    menu = _open_title_menu(pill, qapp)
    _title_menu_action(menu, "取消固定，继续调整").trigger()
    qapp.processEvents()
    assert _records(cs) == ()
    assert cs._pill.isVisible()
    placement = cs.canvas_time.snapshot_cursor_placement()
    assert abs(placement["ax"] - 0.2) < 1e-6
    assert abs(placement["bx"] - 0.8) < 1e-6
    _aim(qtbot, cs.canvas_time, 0.5, cs._pinned_cursors)
    _press_p(_viewport(cs.canvas_time))
    assert _records(cs)[0].ordinal == 1


def test_close_button_and_menu_delete_clear_projections_without_live_restore(
    qapp, qtbot,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    vp = _viewport(canvas)
    _aim(qtbot, canvas, 0.28, cs._pinned_cursors)
    _press_p(vp)
    _aim(qtbot, canvas, 0.72, cs._pinned_cursors)
    _press_p(vp)
    first, second = _records(cs)
    _click_record_label(qtbot, cs, first.record_id)
    _click_record_label(qtbot, cs, second.record_id)
    qapp.processEvents()
    first_pill = _pinned_pill_for_ordinal(cs, 1)
    qtbot.mouseClick(first_pill._close_btn, Qt.LeftButton)
    qapp.processEvents()
    remaining = _records(cs)
    assert [item.ordinal for item in remaining] == [2]
    assert canvas._pinned_overlay.lines_for(first.record_id) == []
    assert all(
        first.record_id not in label.record_ids()
        for label in cs._pinned_cursors.axis_labels_for(canvas)
    )
    assert not cs._pill.isVisible()

    second_pill = _pinned_pill_for_ordinal(cs, 2)
    menu = _open_title_menu(second_pill, qapp)
    _title_menu_action(menu, "删除 P2").trigger()
    qapp.processEvents()
    assert _records(cs) == ()
    assert canvas._pinned_overlay.records() == ()
    assert cs._pinned_cursors.pills_for(canvas) == ()
    assert cs._pinned_cursors.axis_labels_for(canvas) == ()
    assert not cs._pill.isVisible()


def test_title_chrome_child_clicks_do_not_drag_pinned_panel(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    _aim(qtbot, cs.canvas_time, 0.4, cs._pinned_cursors)
    _press_p(_viewport(cs.canvas_time))
    record = _records(cs)[0]
    _click_record_label(qtbot, cs, record.record_id)
    qapp.processEvents()
    pill = _pinned_pill_for_ordinal(cs, 1)
    origin = QPoint(pill.pos())
    start = pill.rect().center()
    qtbot.mousePress(pill, Qt.LeftButton, pos=start)
    qtbot.mouseMove(pill, start + QPoint(-24, 16))
    qtbot.mouseRelease(pill, Qt.LeftButton, pos=start + QPoint(-24, 16))
    qapp.processEvents()
    assert pill.is_user_placed()
    origin = QPoint(pill.pos())
    for widget in (
        pill._title_menu_btn,
        pill._mode_control.button_for("mini"),
        pill._close_btn,
    ):
        if sip.isdeleted(pill):
            break
        qtbot.mousePress(widget, Qt.LeftButton, pos=widget.rect().center())
        qapp.processEvents()
        assert pill.is_dragging() is False
        assert pill.pos() == origin
        qtbot.mouseRelease(widget, Qt.LeftButton, pos=widget.rect().center())
        qapp.processEvents()
        dismiss = getattr(pill, "dismiss_title_menu", None)
        if callable(dismiss):
            dismiss()
            qapp.processEvents()
        if sip.isdeleted(pill):
            break
        origin = QPoint(pill.pos())


def test_title_menu_closes_on_pin_replacement_without_old_scope_callback(
    qapp, qtbot,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _aim(qtbot, canvas, 0.3, cs._pinned_cursors)
    _press_p(_viewport(canvas))
    old = _records(cs)[0]
    _click_record_label(qtbot, cs, old.record_id)
    qapp.processEvents()
    pill = _pinned_pill_for_ordinal(cs, 1)
    menu = _open_title_menu(pill, qapp)
    old_actions = list(menu.actions())
    replacement, _intent = next_record(empty_collection(), {
        "mode": "single",
        "domain": "time",
        "x": 0.8,
        "x_unit": "s",
        "bindings": [{"fid": "fid-a", "channel": "speed"}],
        "presentation": "full",
        "panel_expanded": True,
    })
    cs.set_pinned_cursors_for_canvas(canvas, replacement)
    qapp.processEvents()
    assert sip.isdeleted(menu) or not menu.isVisible()
    for action in old_actions:
        if sip.isdeleted(action):
            continue
        action.trigger()
    qapp.processEvents()
    live = _records(cs)
    assert len(live) == 1
    assert live[0].record_id != old.record_id
    assert live[0].ordinal == 1
    assert abs(live[0].x - 0.8) < 1e-6
    new_pill = _pinned_pill_for_ordinal(cs, 1)
    assert new_pill is not pill
    assert sip.isdeleted(pill) or not pill.isVisible()


def test_title_menu_highlight_holds_while_open(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _aim(qtbot, canvas, 0.4, cs._pinned_cursors)
    _press_p(_viewport(canvas))
    record = _records(cs)[0]
    _click_record_label(qtbot, cs, record.record_id)
    qapp.processEvents()
    pill = _pinned_pill_for_ordinal(cs, 1)
    overlay = canvas._pinned_overlay
    QApplication.sendEvent(pill, QEvent(QEvent.Enter))
    qapp.processEvents()
    _open_title_menu(pill, qapp)
    QApplication.sendEvent(pill, QEvent(QEvent.Leave))
    qapp.processEvents()
    assert overlay.highlight_id() == record.record_id
    pill.dismiss_title_menu()
    qapp.processEvents()

