"""Wave 2 Task 2.3: ViewportController owns BoardViewport and camera apply."""
from __future__ import annotations

import ast
from pathlib import Path

from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QMouseEvent, QWheelEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.chart_stack.ultraview.viewport_controller import ViewportController
from tests.ui.test_ultraview_page import _Harness


ULTRAVIEW_ROOT = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "chart_stack"
    / "ultraview"
)
PAGE_PATH = ULTRAVIEW_ROOT / "page.py"
CONTROLLER_PATH = ULTRAVIEW_ROOT / "viewport_controller.py"
VIEWPORT_PATH = ULTRAVIEW_ROOT / "viewport.py"


def _board_viewport_calls(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "BoardViewport":
            lines.append(node.lineno)
        elif isinstance(func, ast.Attribute) and func.attr == "BoardViewport":
            lines.append(node.lineno)
    return lines


def test_board_viewport_is_constructed_in_the_controller_not_page():
    page_hits = _board_viewport_calls(PAGE_PATH)
    controller_hits = _board_viewport_calls(CONTROLLER_PATH)
    definition_hits = _board_viewport_calls(VIEWPORT_PATH)
    assert page_hits == []
    assert len(controller_hits) == 1
    assert definition_hits == []


def test_page_forwards_zoom_fit_and_handle_zoom_wheel():
    source = PAGE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(PAGE_PATH))
    bodies: dict[str, ast.FunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in {
            "zoom_fit",
            "handle_zoom_wheel",
        }:
            bodies[node.name] = node
    assert set(bodies) == {"zoom_fit", "handle_zoom_wheel"}
    assert "self._viewport_ctrl.zoom_fit()" in source
    assert "self._viewport_ctrl.handle_zoom_wheel" in source
    for name, function in bodies.items():
        calls = [
            item
            for item in ast.walk(function)
            if isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and item.func.attr in {name, "handle_zoom_wheel", "zoom_fit"}
        ]
        assert calls, f"UltraViewPage.{name} must forward to ViewportController"


def test_page_composes_one_viewport_controller():
    source = PAGE_PATH.read_text(encoding="utf-8")
    assert "ViewportController(" in source
    assert source.count("ViewportController(") == 1
    public = {
        name
        for name, value in vars(ViewportController).items()
        if callable(value) and not name.startswith("_")
    }
    assert {
        "hide",
        "reset",
        "cancel",
        "zoom_fit",
        "handle_zoom_wheel",
        "handle_scroll_wheel",
        "abandon_board_pan",
        "fit_on_open",
        "begin_board_pan",
    } <= public


def test_update_board_pan_without_buttons_does_not_scroll(qtbot):
    harness = _Harness(qtbot)
    page = harness.page
    page.set_board_zoom(2.0)
    scroll = page.board_scroll_area()
    horizontal = scroll.horizontalScrollBar()
    horizontal.setValue(max(40, horizontal.maximum() // 2))
    widget = scroll.viewport()
    start = widget.rect().center()
    QTest.mousePress(widget, Qt.MiddleButton, pos=start)
    assert page.is_board_panning()
    before = horizontal.value()
    end = start + QPoint(-70, 20)
    event = QMouseEvent(
        QEvent.MouseMove,
        QPointF(end),
        QPointF(widget.mapToGlobal(end)),
        Qt.NoButton,
        Qt.NoButton,
        Qt.NoModifier,
    )
    page._viewport_ctrl.update_board_pan(event)
    assert not page.is_board_panning()
    assert horizontal.value() == before


def test_controller_shift_wheel_does_not_move_the_vertical_bar(qtbot):
    harness = _Harness(qtbot)
    page = harness.page
    page.set_board_zoom(2.0)
    scroll = page.board_scroll_area()
    horizontal = scroll.horizontalScrollBar()
    vertical = scroll.verticalScrollBar()
    horizontal.setValue(max(80, horizontal.maximum() // 2))
    vertical.setValue(max(80, vertical.maximum() // 2))
    origin_h = horizontal.value()
    origin_v = vertical.value()
    pos = QPointF(scroll.viewport().rect().center())
    event = QWheelEvent(
        pos,
        pos,
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.NoButton,
        Qt.ShiftModifier,
        Qt.NoScrollPhase,
        False,
    )
    assert page._viewport_ctrl.handle_scroll_wheel(event) is True
    assert vertical.value() == origin_v
    assert horizontal.value() != origin_h
