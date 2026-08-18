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
from tests.ui.test_ultraview_page import _Harness, _prepare_free_grid


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

    The router must still begin a pan on the UltraView card; WindowDeactivate
    already uninstalls when a real foreign window takes the session.
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
