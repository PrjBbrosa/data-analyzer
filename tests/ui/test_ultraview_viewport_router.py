"""Event-sequence contracts for UltraView's canvas-wide viewport gestures."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QMouseEvent, QNativeGestureEvent, QWheelEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QPushButton, QWidget

from mf4_analyzer.ui.chart_stack.ultraview.viewport_router import ViewportGestureRouter
from mf4_analyzer.ui.ultraview_state import add_ref, make_ref, set_layout
from tests.ui.test_ultraview_page import (
    _Harness,
    _blank_board_point,
    _prepare_free_grid,
)


_START_KINDS = ("template_card", "template_grid", "free_card", "free_grid", "viewport")


def _target(harness, qtbot, kind: str):
    page = harness.page
    viewport = page.board_scroll_area().viewport()
    if kind in {"template_card", "template_grid"}:
        set_layout(harness.board, "split_horizontal")
        add_ref(harness.board, make_ref("time", "template-card"))
        page.set_board(harness.board)
        card = page.card_widget("time", "template-card")
        assert card is not None
        return card if kind == "template_card" else page.board_grid(), viewport
    free, cards = _prepare_free_grid(harness, qtbot, "free-card")
    if kind == "free_card":
        return cards[0], viewport
    if kind == "free_grid":
        return free, viewport
    return viewport, free


def _send_move(widget, global_pos: QPoint, *, buttons: Qt.MouseButtons) -> None:
    local = widget.mapFromGlobal(global_pos)
    event = QMouseEvent(
        QEvent.MouseMove,
        local,
        global_pos,
        Qt.NoButton,
        buttons,
        Qt.NoModifier,
    )
    QApplication.sendEvent(widget, event)


def _send_release(widget, global_pos: QPoint, button: Qt.MouseButton) -> None:
    local = widget.mapFromGlobal(global_pos)
    event = QMouseEvent(
        QEvent.MouseButtonRelease,
        local,
        global_pos,
        button,
        Qt.NoButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(widget, event)


@pytest.mark.parametrize("kind", _START_KINDS)
def test_middle_pan_continues_across_canvas_children(qtbot, kind):
    harness = _Harness(qtbot)
    page = harness.page
    page.set_board_zoom(2.0)
    start_widget, move_widget = _target(harness, qtbot, kind)
    scroll = page.board_scroll_area()
    horizontal = scroll.horizontalScrollBar()
    horizontal.setValue(max(30, horizontal.maximum() // 2))
    before = horizontal.value()
    start = start_widget.rect().center()
    global_start = start_widget.mapToGlobal(start)
    QTest.mousePress(start_widget, Qt.MiddleButton, pos=start)
    assert page.is_board_panning()

    global_end = global_start - QPoint(48, 0)
    _send_move(move_widget, global_end, buttons=Qt.MiddleButton)
    assert page.is_board_panning()
    _send_release(move_widget, global_end, Qt.MiddleButton)

    assert not page.is_board_panning()
    assert horizontal.value() != before


def test_middle_pan_survives_stale_foreign_active_window(qtbot, qapp):
    """Capture tests leave parentless shown widgets as activeWindow.

    setActiveWindow() can deliver WindowDeactivate without moving
    QGuiApplication.focusWindow(). Routing stays installed and effective
    for that leftover. A real focus-window change is what suspends it.
    """
    leftover = QWidget()
    leftover.resize(64, 48)
    leftover.show()
    qtbot.addWidget(leftover)
    harness = _Harness(qtbot)
    page = harness.page
    qapp.setActiveWindow(leftover)
    page.set_board_zoom(2.0)
    start_widget, _move_widget = _target(harness, qtbot, "template_card")
    start = start_widget.rect().center()
    QTest.mousePress(start_widget, Qt.MiddleButton, pos=start)
    assert page.is_board_panning()
    QTest.mouseRelease(start_widget, Qt.MiddleButton, pos=start)
    leftover.hide()


@pytest.mark.parametrize("kind", _START_KINDS)
def test_space_left_pan_continues_across_canvas_children(qtbot, kind):
    harness = _Harness(qtbot)
    page = harness.page
    page.set_board_zoom(2.0)
    start_widget, move_widget = _target(harness, qtbot, kind)
    scroll = page.board_scroll_area()
    horizontal = scroll.horizontalScrollBar()
    horizontal.setValue(max(30, horizontal.maximum() // 2))
    before = horizontal.value()
    start = start_widget.rect().center()
    global_start = start_widget.mapToGlobal(start)
    start_widget.setFocus(Qt.OtherFocusReason)
    QTest.keyPress(start_widget, Qt.Key_Space)
    QTest.mousePress(start_widget, Qt.LeftButton, pos=start)
    assert page.is_board_panning()

    global_end = global_start - QPoint(48, 0)
    _send_move(move_widget, global_end, buttons=Qt.LeftButton)
    assert page.is_board_panning()
    _send_release(move_widget, global_end, Qt.LeftButton)
    QTest.keyRelease(start_widget, Qt.Key_Space)

    assert not page.is_board_panning()
    assert horizontal.value() != before


@pytest.mark.parametrize("kind", _START_KINDS)
@pytest.mark.parametrize("modifier", (Qt.ControlModifier, Qt.MetaModifier))
def test_modified_wheel_zooms_from_every_canvas_child(qtbot, kind, modifier):
    harness = _Harness(qtbot)
    page = harness.page
    widget, _move_widget = _target(harness, qtbot, kind)
    pos = widget.rect().center()
    before = page.board_zoom()
    event = QWheelEvent(
        QPointF(pos),
        QPointF(widget.mapToGlobal(pos)),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.NoButton,
        modifier,
        Qt.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)
    assert page.board_zoom() > before


@pytest.mark.parametrize("kind", _START_KINDS)
def test_native_pinch_zooms_from_every_canvas_child(qtbot, kind):
    harness = _Harness(qtbot)
    page = harness.page
    widget, _move_widget = _target(harness, qtbot, kind)
    pos = QPointF(widget.rect().center())
    event = QNativeGestureEvent(
        Qt.ZoomNativeGesture,
        pos,
        pos,
        QPointF(widget.mapToGlobal(pos.toPoint())),
        0.2,
        1,
        0,
    )
    before = page.board_zoom()
    QApplication.sendEvent(widget, event)
    assert page.board_zoom() > before


def test_modified_wheel_outside_canvas_host_does_not_zoom(qtbot):
    harness = _Harness(qtbot)
    page = harness.page
    outside = QPushButton(page)
    outside.show()
    pos = outside.rect().center()
    event = QWheelEvent(
        QPointF(pos),
        QPointF(outside.mapToGlobal(pos)),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.NoButton,
        Qt.ControlModifier,
        Qt.NoScrollPhase,
        False,
    )

    before = page.board_zoom()
    QApplication.sendEvent(outside, event)
    assert page.board_zoom() == before


def test_router_uninstalls_on_hide_and_reinstalls_on_show(qtbot):
    harness = _Harness(qtbot)
    page = harness.page
    widget = page.board_scroll_area().viewport()
    pos = widget.rect().center()

    def send_modified_wheel() -> None:
        QApplication.sendEvent(
            widget,
            QWheelEvent(
                QPointF(pos),
                QPointF(widget.mapToGlobal(pos)),
                QPoint(0, 0),
                QPoint(0, 120),
                Qt.NoButton,
                Qt.ControlModifier,
                Qt.NoScrollPhase,
                False,
            ),
        )

    page.hide()
    before = page.board_zoom()
    send_modified_wheel()
    assert page.board_zoom() == before

    page.show()
    qtbot.wait(10)
    send_modified_wheel()
    assert page.board_zoom() > before


def test_plain_left_press_on_card_does_not_start_board_pan(qtbot):
    harness = _Harness(qtbot)
    page = harness.page
    page.set_board_zoom(2.0)
    card, _move_widget = _target(harness, qtbot, "template_card")

    QTest.mousePress(card, Qt.LeftButton, pos=card.rect().center())
    assert not page.is_board_panning()
    QTest.mouseRelease(card, Qt.LeftButton, pos=card.rect().center())


@pytest.mark.parametrize("kind", _START_KINDS)
def test_right_pan_continues_across_canvas_children(qtbot, kind):
    harness = _Harness(qtbot)
    page = harness.page
    page.set_board_zoom(2.0)
    start_widget, move_widget = _target(harness, qtbot, kind)
    scroll = page.board_scroll_area()
    horizontal = scroll.horizontalScrollBar()
    horizontal.setValue(max(30, horizontal.maximum() // 2))
    before = horizontal.value()
    start = start_widget.rect().center()
    global_start = start_widget.mapToGlobal(start)
    QTest.mousePress(start_widget, Qt.RightButton, pos=start)
    assert page.is_board_panning()
    assert not page.board_viewport().pan_committed()

    global_end = global_start - QPoint(48, 0)
    _send_move(move_widget, global_end, buttons=Qt.RightButton)
    assert page.is_board_panning()
    assert page.board_viewport().pan_committed()
    _send_release(move_widget, global_end, Qt.RightButton)

    assert not page.is_board_panning()
    assert horizontal.value() != before


def test_right_press_on_library_does_not_start_board_pan(qtbot):
    harness = _Harness(qtbot)
    page = harness.page
    page.set_library_visible(True)
    field = page.library_panel().search_field()
    qtbot.wait(10)
    QTest.mousePress(field, Qt.RightButton, pos=field.rect().center())
    assert not page.is_board_panning()
    QTest.mouseRelease(field, Qt.RightButton, pos=field.rect().center())


def test_space_is_not_consumed_while_text_input_has_focus(qtbot):
    harness = _Harness(qtbot)
    page = harness.page
    page.set_library_visible(True)
    field = page.library_panel().search_field()
    page.activateWindow()
    field.setFocus(Qt.OtherFocusReason)
    qtbot.wait(10)
    assert QApplication.focusWidget() is field
    QTest.keyPress(field, Qt.Key_Space)
    assert not page.board_viewport().space_down()
    QTest.keyRelease(field, Qt.Key_Space)


def _is_application_install_event_filter(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "installEventFilter":
        return False
    owner = func.value
    if isinstance(owner, ast.Name) and owner.id in {"app", "qApp"}:
        return True
    if isinstance(owner, ast.Call) and isinstance(owner.func, ast.Attribute):
        return owner.func.attr == "instance"
    return False


def test_only_viewport_router_installs_an_application_event_filter():
    root = (
        Path(__file__).resolve().parents[2]
        / "mf4_analyzer"
        / "ui"
        / "chart_stack"
        / "ultraview"
    )
    hits = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if _is_application_install_event_filter(node):
                hits.append(path.name)
    assert hits == ["viewport_router.py"]


def test_page_keeps_exactly_one_installed_viewport_router(qtbot):
    harness = _Harness(qtbot)
    routers = harness.page.findChildren(ViewportGestureRouter)
    assert len(routers) == 1
    assert routers[0]._installed is True


def _send_wheel(widget, *, angle: QPoint, pixel: QPoint, modifiers) -> None:
    pos = widget.rect().center()
    QApplication.sendEvent(
        widget,
        QWheelEvent(
            QPointF(pos),
            QPointF(widget.mapToGlobal(pos)),
            pixel,
            angle,
            Qt.NoButton,
            modifiers,
            Qt.NoScrollPhase,
            False,
        ),
    )


def _scroll_midpoint(page):
    page.set_board_zoom(2.0)
    scroll = page.board_scroll_area()
    horizontal = scroll.horizontalScrollBar()
    vertical = scroll.verticalScrollBar()
    assert horizontal.maximum() > 200
    assert vertical.maximum() > 200
    horizontal.setValue(max(120, horizontal.maximum() // 2))
    vertical.setValue(max(120, vertical.maximum() // 2))
    return scroll, horizontal, vertical


def test_shift_wheel_scrolls_horizontally_by_the_vertical_step(qtbot):
    harness = _Harness(qtbot)
    page = harness.page
    card, _move = _target(harness, qtbot, "free_card")
    _scroll, horizontal, vertical = _scroll_midpoint(page)
    viewport = page.board_scroll_area().viewport()
    origin_h = horizontal.value()
    origin_v = vertical.value()
    zoom = page.board_zoom()

    _send_wheel(viewport, angle=QPoint(0, 120), pixel=QPoint(0, 0), modifiers=Qt.NoModifier)
    plain_dh = horizontal.value() - origin_h
    plain_dv = vertical.value() - origin_v
    assert plain_dh == 0
    assert plain_dv != 0
    assert abs(plain_dv) < vertical.pageStep()

    horizontal.setValue(origin_h)
    vertical.setValue(origin_v)
    _send_wheel(card, angle=QPoint(0, 120), pixel=QPoint(0, 0), modifiers=Qt.ShiftModifier)
    assert vertical.value() == origin_v
    assert horizontal.value() - origin_h == plain_dv
    assert page.board_zoom() == zoom


def test_pixel_delta_wheel_scrolls_both_axes(qtbot):
    harness = _Harness(qtbot)
    page = harness.page
    card, _move = _target(harness, qtbot, "free_card")
    _scroll, horizontal, vertical = _scroll_midpoint(page)
    origin_h = horizontal.value()
    origin_v = vertical.value()
    zoom = page.board_zoom()
    sign = -1 if vertical.invertedControls() else 1
    _send_wheel(
        card,
        angle=QPoint(0, 0),
        pixel=QPoint(36, -18),
        modifiers=Qt.NoModifier,
    )
    assert horizontal.value() - origin_h == sign * 36
    assert vertical.value() - origin_v == sign * -18
    assert page.board_zoom() == zoom


def test_pan_move_without_buttons_cancels_and_keeps_scroll(qtbot):
    harness = _Harness(qtbot)
    page = harness.page
    _scroll, horizontal, vertical = _scroll_midpoint(page)
    widget = page.board_scroll_area().viewport()
    start = widget.rect().center()
    QTest.mousePress(widget, Qt.MiddleButton, pos=start)
    assert page.is_board_panning()
    before = (horizontal.value(), vertical.value())
    end = start + QPoint(-80, 30)
    _send_move(widget, widget.mapToGlobal(end), buttons=Qt.NoButton)
    assert not page.is_board_panning()
    assert (horizontal.value(), vertical.value()) == before


def test_right_press_during_left_pan_cancels_without_scrolling(qtbot):
    harness = _Harness(qtbot)
    page = harness.page
    page.set_board_zoom(2.0)
    widget = page.board_scroll_area().viewport()
    widget.setFocus(Qt.OtherFocusReason)
    QTest.keyPress(widget, Qt.Key_Space)
    start = widget.rect().center()
    QTest.mousePress(widget, Qt.LeftButton, pos=start)
    assert page.is_board_panning()
    horizontal = page.board_scroll_area().horizontalScrollBar()
    before = horizontal.value()
    QTest.mousePress(widget, Qt.RightButton, pos=start + QPoint(8, 4))
    assert not page.is_board_panning()
    assert horizontal.value() == before
    QTest.keyRelease(widget, Qt.Key_Space)


def test_ungrab_cancels_an_open_pan_without_scrolling(qtbot):
    harness = _Harness(qtbot)
    page = harness.page
    _scroll, horizontal, _vertical = _scroll_midpoint(page)
    widget = page.board_scroll_area().viewport()
    QTest.mousePress(widget, Qt.MiddleButton, pos=widget.rect().center())
    assert page.is_board_panning()
    before = horizontal.value()
    QApplication.sendEvent(widget, QEvent(QEvent.UngrabMouse))
    assert not page.is_board_panning()
    assert horizontal.value() == before


def test_marquee_move_without_buttons_cancels_and_keeps_placements(qtbot):
    harness = _Harness(qtbot)
    free, _cards = _prepare_free_grid(harness, qtbot, "lost-marquee")
    before = tuple(
        (
            item.ref.section,
            item.ref.view_id,
            item.rect.column,
            item.rect.row,
            item.rect.column_span,
            item.rect.row_span,
        )
        for item in free.current_placements()
    )
    pos = _blank_board_point(free)
    QTest.mousePress(free, Qt.LeftButton, Qt.NoModifier, pos)
    assert free.gesture().marquee() is not None
    far = QPoint(pos.x() + 80, pos.y() + 40)
    QApplication.sendEvent(
        free,
        QMouseEvent(
            QEvent.MouseMove,
            far,
            free.mapToGlobal(far),
            Qt.NoButton,
            Qt.NoButton,
            Qt.NoModifier,
        ),
    )
    assert free.gesture().marquee() is None
    assert not free.gesture().is_armed()
    after = tuple(
        (
            item.ref.section,
            item.ref.view_id,
            item.rect.column,
            item.rect.row,
            item.rect.column_span,
            item.rect.row_span,
        )
        for item in free.current_placements()
    )
    assert after == before
