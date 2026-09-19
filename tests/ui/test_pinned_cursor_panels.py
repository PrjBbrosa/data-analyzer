"""Pinned CursorPill chrome, independence, consume, and undo (Task 2 / A09)."""
from __future__ import annotations

import numpy as np
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
)


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


def _is_descendant_of(widget, ancestor):
    while widget is not None:
        if widget is ancestor:
            return True
        widget = widget.parentWidget()
    return False


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
    assert first.display_mode() == "full"
    assert second.display_mode() == "full"
    second._toggle_mode()
    qapp.processEvents()
    assert first.display_mode() == "full"
    assert second.display_mode() == "mini"
    cs._pill._toggle_mode()
    qapp.processEvents()
    assert first.display_mode() == "full"
    assert second.display_mode() == "mini"

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
    vp = _viewport(cs.canvas_time)
    _aim(qtbot, cs.canvas_time, 0.4, cs._pinned_cursors)
    _press_p(vp)
    assert not cs._pill.isVisible()
    assert cs._pinned_cursors.is_live_suppressed(cs.canvas_time)

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
    assert cs._pill.pin_role() == "live"
    assert not cs._pinned_cursors.is_live_suppressed(cs.canvas_time)
    assert live_pin_hint_text("single") == "P 固定"


def test_dual_pin_hides_live_and_keeps_placement(qapp, qtbot):
    cs = _make_stack(qtbot, qapp, mode="dual")
    cursor = cs.canvas_time._cursor
    cursor._ax = 0.2
    cursor._bx = 0.8
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
