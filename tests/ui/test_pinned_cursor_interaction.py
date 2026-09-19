"""Real Qt P-key routing for pinned cursors (plan Task 2 / A01–A12)."""
from __future__ import annotations

import numpy as np
import pytest
from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QCursor, QKeyEvent
from PyQt5.QtWidgets import QApplication, QLineEdit

from mf4_analyzer.ui.chart_stack import ChartStack


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


def _plot_point(canvas, frac):
    vp = _viewport(canvas)
    return QPoint(max(8, int(vp.width() * frac)), max(8, int(vp.height() * 0.45)))


def _aim(qtbot, canvas, frac, controller=None):
    vp = _viewport(canvas)
    qtbot.waitUntil(lambda: vp.width() > 20 and vp.height() > 20, timeout=2000)
    local = _plot_point(canvas, frac)
    x = canvas.data_x_from_viewport_pos(local)
    if x is None:
        for candidate in (0.3, 0.4, 0.5, 0.6, 0.7):
            local = _plot_point(canvas, candidate)
            x = canvas.data_x_from_viewport_pos(local)
            if x is not None:
                break
    global_pos = vp.mapToGlobal(local)
    QCursor.setPos(global_pos)
    qtbot.mouseMove(vp, local)
    if controller is not None:
        controller._last_mouse_global = global_pos
    QApplication.processEvents()
    return local


def _press_p(target, *, autorepeat=False):
    override = QKeyEvent(
        QEvent.ShortcutOverride, Qt.Key_P, Qt.NoModifier, "p",
    )
    press = QKeyEvent(
        QEvent.KeyPress, Qt.Key_P, Qt.NoModifier, "p", autorepeat, 1,
    )
    QApplication.sendEvent(target, override)
    QApplication.sendEvent(target, press)
    QApplication.processEvents()
    return override


def _records(cs, canvas=None):
    canvas = cs.canvas_time if canvas is None else canvas
    return cs.pinned_cursors_for_canvas(canvas).records


def test_a01_mouse_over_plot_without_click_pins(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    vp = _viewport(cs.canvas_time)
    local = _aim(qtbot, cs.canvas_time, 0.35, cs._pinned_cursors)
    expected = cs.canvas_time.data_x_from_viewport_pos(local)
    feedback = []
    cs.pin_feedback.connect(feedback.append)

    override = _press_p(vp)

    assert override.isAccepted()
    records = _records(cs)
    assert len(records) == 1
    assert records[0].mode == "single"
    assert records[0].domain == "time"
    assert records[0].ordinal == 1
    assert records[0].x == pytest.approx(expected)
    assert any("P1 已固定" in item for item in feedback)
    pills = cs._pinned_cursors.pills_for(cs.canvas_time)
    assert len(pills) == 1
    assert pills[0].isVisible()
    assert pills[0].pin_role() == "pinned"


def test_a02_p_uses_latest_physical_x_not_throttled_pill(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    vp = _viewport(cs.canvas_time)
    _aim(qtbot, cs.canvas_time, 0.25, cs._pinned_cursors)
    local = _aim(qtbot, cs.canvas_time, 0.72, cs._pinned_cursors)
    expected = cs.canvas_time.data_x_from_viewport_pos(local)
    sample = cs.canvas_time._cursor.evaluate_single_cursor_sample(expected)

    _press_p(vp)

    records = _records(cs)
    assert len(records) == 1
    assert records[0].x == pytest.approx(expected)
    assert sample is not None
    assert records[0].x == pytest.approx(sample.x)


def test_a03_autorepeat_and_same_point_do_not_duplicate(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    vp = _viewport(cs.canvas_time)
    _aim(qtbot, cs.canvas_time, 0.4, cs._pinned_cursors)
    _press_p(vp)
    _press_p(vp, autorepeat=True)
    _press_p(vp)
    assert len(_records(cs)) == 1

    _aim(qtbot, cs.canvas_time, 0.75, cs._pinned_cursors)
    _press_p(vp)
    assert len(_records(cs)) == 2
    xs = sorted(item.x for item in _records(cs))
    assert xs[1] - xs[0] > 0.05


def test_a05_dual_none_a_only_complete_equal_and_reversed(qapp, qtbot):
    cs = _make_stack(qtbot, qapp, mode="dual")
    vp = _viewport(cs.canvas_time)
    cursor = cs.canvas_time._cursor
    feedback = []
    cs.pin_feedback.connect(feedback.append)
    _aim(qtbot, cs.canvas_time, 0.4, cs._pinned_cursors)

    _press_p(vp)
    assert _records(cs) == ()
    assert any("A" in item or "B" in item for item in feedback)

    cursor._ax = 0.20
    cursor._bx = None
    cursor._placing = "B"
    feedback.clear()
    _press_p(vp)
    assert _records(cs) == ()
    assert any("先放置 B" in item for item in feedback)

    cursor._bx = 0.80
    _press_p(vp)
    records = _records(cs)
    assert len(records) == 1
    assert records[0].mode == "dual"
    assert records[0].ax == pytest.approx(0.20)
    assert records[0].bx == pytest.approx(0.80)
    placement = cs.canvas_time.snapshot_cursor_placement()
    assert placement["ax"] == pytest.approx(0.20)
    assert placement["bx"] == pytest.approx(0.80)

    t = np.linspace(0.0, 1.0, 200)
    same = float(t[100])
    cursor._ax = same
    cursor._bx = same
    _press_p(vp)
    records = _records(cs)
    assert len(records) == 2
    equal = records[1]
    assert equal.ax == pytest.approx(equal.bx)

    cursor._ax = 0.90
    cursor._bx = 0.10
    _press_p(vp)
    reversed_pin = _records(cs)[2]
    assert reversed_pin.ax == pytest.approx(0.90)
    assert reversed_pin.bx == pytest.approx(0.10)


def test_a08_off_does_not_create_and_keeps_existing_pins(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    vp = _viewport(cs.canvas_time)
    _aim(qtbot, cs.canvas_time, 0.4, cs._pinned_cursors)
    _press_p(vp)
    assert len(_records(cs)) == 1

    cs.set_cursor_mode("off")
    qapp.processEvents()
    override = _press_p(vp)
    assert not override.isAccepted()
    assert len(_records(cs)) == 1
    pills = cs._pinned_cursors.pills_for(cs.canvas_time)
    assert pills and pills[0].isVisible()
    assert not cs.cursor_pill_visible()


def test_a12_mouse_target_not_focus_and_text_and_ultraview(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    cs.enter_split()
    qapp.processEvents()
    secondary = cs.secondary_canvas()
    _plot_speed(secondary)
    cs.set_cursor_mode_for_canvas(secondary, "single")
    qapp.processEvents()

    cs.set_focused_card(cs._time_card)
    _aim(qtbot, secondary, 0.4, cs._pinned_cursors)
    _press_p(_viewport(secondary))
    assert _records(cs, cs.canvas_time) == ()
    assert len(_records(cs, secondary)) == 1

    edit = QLineEdit(cs)
    edit.setGeometry(8, 8, 160, 24)
    edit.show()
    edit.setFocus(Qt.OtherFocusReason)
    qapp.processEvents()
    before = len(_records(cs, secondary))
    _aim(qtbot, secondary, 0.7, cs._pinned_cursors)
    override = _press_p(_viewport(secondary))
    assert not override.isAccepted()
    assert len(_records(cs, secondary)) == before

    cs.stack.setCurrentWidget(cs.page_ultraview)
    qapp.processEvents()
    uv = cs.page_ultraview
    qtbot.mouseMove(uv, uv.rect().center())
    cs._pinned_cursors._last_mouse_global = uv.mapToGlobal(uv.rect().center())
    override = _press_p(uv)
    assert not override.isAccepted()


def test_gesture_in_progress_does_not_pin(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    vp = _viewport(cs.canvas_time)
    local = _aim(qtbot, cs.canvas_time, 0.4, cs._pinned_cursors)
    qtbot.mousePress(vp, Qt.LeftButton, pos=local)
    qapp.processEvents()
    override = _press_p(vp)
    assert not override.isAccepted()
    assert _records(cs) == ()
    qtbot.mouseRelease(vp, Qt.LeftButton, pos=local)
