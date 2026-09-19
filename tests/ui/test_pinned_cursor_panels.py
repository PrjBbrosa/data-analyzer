"""Pinned CursorPill chrome, independence, consume, and undo (Task 2 / A09)."""
from __future__ import annotations

import numpy as np
from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QCursor, QKeyEvent
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.chart_stack.cursor_display import live_pin_hint_text
from mf4_analyzer.ui.cursor_display_model import CursorDisplayChannel


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


def test_a09_full_mini_independent_drag_close_and_reuse_ordinal(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    vp = _viewport(cs.canvas_time)
    _aim(qtbot, cs.canvas_time, 0.3, cs._pinned_cursors)
    _press_p(vp)
    _aim(qtbot, cs.canvas_time, 0.7, cs._pinned_cursors)
    _press_p(vp)
    pills = cs._pinned_cursors.pills_for(cs.canvas_time)
    assert len(pills) == 2
    first, second = pills
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
