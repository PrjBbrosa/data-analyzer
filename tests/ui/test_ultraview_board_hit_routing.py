"""Select-tool hit routing: Connector/Stroke go through classify_press."""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.chart_stack.ultraview.author_edits import apply_author_update
from mf4_analyzer.ui.chart_stack.ultraview.author_geometry import board_point_to_pixels
from mf4_analyzer.ui.chart_stack.ultraview.author_tools import (
    HIT_RESIZE_HANDLE,
    TOOL_SELECT,
    AuthorKey,
)
from mf4_analyzer.ui.ultraview_state import (
    BoardBox,
    BoardPoint,
    ConnectorEndpoint,
    ConnectorObject,
    StrokeObject,
    TextObject,
)
from tests.ui.test_ultraview_page import _Harness, _prepare_free_grid


def _send(widget, etype, pos: QPoint, *, buttons=Qt.LeftButton, mods=Qt.NoModifier) -> None:
    event = QMouseEvent(
        etype,
        pos,
        widget.mapToGlobal(pos),
        Qt.LeftButton,
        buttons,
        mods,
    )
    QApplication.sendEvent(widget, event)
    QApplication.processEvents()


def _pixel(free, x: float, y: float) -> QPoint:
    mapped = board_point_to_pixels(
        (x, y),
        free.metrics(),
        origin_offset=free.author_paint_layer().model().origin_offset,
    )
    assert mapped is not None
    return QPoint(int(round(mapped[0])), int(round(mapped[1])))


def test_select_hits_connector_over_card_and_card_beside_it(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "hit-0")
    placement = harness.board.free_grid[0]
    rect = placement.rect
    mid_y = float(rect.row) + float(rect.row_span) / 2.0
    start_x = max(0.25, float(rect.column) - 3.0)
    end_x = float(rect.column) + float(rect.column_span) + 4.0
    line = ConnectorObject(
        "line-cross",
        "connector",
        start=ConnectorEndpoint(BoardPoint(start_x, mid_y)),
        end=ConnectorEndpoint(BoardPoint(end_x, mid_y)),
        route="straight",
        end_head="arrow",
    )
    harness.board.author_objects = [line]
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    harness.page.interaction().set_active_tool(TOOL_SELECT)
    past_card = float(rect.column) + float(rect.column_span) + 2.0
    QTest.mouseClick(free, Qt.LeftButton, Qt.NoModifier, _pixel(free, past_card, mid_y))
    QApplication.processEvents()
    assert harness.page.interaction().author_selection_ids() == frozenset({"line-cross"})
    # Click the card well above the connector corridor.
    local = QPoint(40, 12)
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier, local)
    QApplication.processEvents()
    refs = harness.page.interaction().card_selection()
    assert any(ref.view_id == "hit-0" for ref in refs)
    assert "line-cross" not in harness.page.interaction().author_selection_ids()


def test_select_clicks_stroke_and_shows_ink_toolbar(qtbot):
    harness = _Harness(qtbot)
    free, _cards = _prepare_free_grid(harness, qtbot, "ink-0")
    stroke = StrokeObject(
        "ink-1",
        "stroke",
        points=(BoardPoint(1.0, 1.0), BoardPoint(6.0, 1.0)),
        tool="pen",
        palette="ink",
        width_px_100=8,
    )
    harness.board.author_objects = [stroke]
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    harness.page.interaction().set_active_tool(TOOL_SELECT)
    QTest.mouseClick(free, Qt.LeftButton, Qt.NoModifier, _pixel(free, 3.0, 1.0))
    QApplication.processEvents()
    harness.page._refresh_author_toolbar()
    QApplication.processEvents()
    assert harness.page.interaction().author_selection_ids() == frozenset({"ink-1"})
    toolbar = harness.page.selection_toolbar()
    assert toolbar.isVisible()
    assert toolbar.kind() == "stroke"


def _apply_updates(harness) -> None:
    def _on_update(intent) -> None:
        apply_author_update(harness.board, intent)
        harness.page.set_board(harness.board)

    harness.page.author_update_requested.connect(_on_update)


def test_select_connector_end_handle_classifies_and_drags(qtbot):
    harness = _Harness(qtbot)
    free, _cards = _prepare_free_grid(harness, qtbot, "h-0")
    _apply_updates(harness)
    line = ConnectorObject(
        "line-h",
        "connector",
        start=ConnectorEndpoint(BoardPoint(1.0, 18.0)),
        end=ConnectorEndpoint(BoardPoint(8.0, 18.0)),
        route="straight",
        end_head="arrow",
    )
    harness.board.author_objects = [line]
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    harness.page.interaction().set_active_tool(TOOL_SELECT)
    harness.page.interaction().select_only_author("line-h")
    free.sync_selection_projection()
    QApplication.processEvents()
    end = _pixel(free, 8.0, 18.0)
    hit = free.classify_press(end)
    assert hit.kind == HIT_RESIZE_HANDLE
    assert isinstance(hit.item, AuthorKey)
    assert hit.item.object_id == "line-h"
    assert hit.handle == "end"
    dest = end + QPoint(120, 40)
    _send(free, QEvent.MouseButtonPress, end, mods=Qt.ControlModifier)
    _send(free, QEvent.MouseMove, dest, buttons=Qt.LeftButton, mods=Qt.ControlModifier)
    _send(free, QEvent.MouseButtonRelease, dest, buttons=Qt.NoButton, mods=Qt.ControlModifier)
    item = next(
        obj for obj in harness.board.author_objects if getattr(obj, "object_id", "") == "line-h"
    )
    assert item.end.point.x > 8.0
    assert item.end.target is None


def test_select_text_body_drag_moves_box(qtbot):
    harness = _Harness(qtbot)
    free, _cards = _prepare_free_grid(harness, qtbot, "txt-0")
    _apply_updates(harness)
    note = TextObject(
        "text-h",
        "text",
        box=BoardBox(2.0, 12.0, 6.0, 2.0),
        text="拖动",
    )
    harness.board.author_objects = [note]
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    harness.page.interaction().set_active_tool(TOOL_SELECT)
    start = _pixel(free, 5.0, 13.0)
    dest = start + QPoint(80, 0)
    _send(free, QEvent.MouseButtonPress, start)
    _send(free, QEvent.MouseMove, dest, buttons=Qt.LeftButton)
    _send(free, QEvent.MouseButtonRelease, dest, buttons=Qt.NoButton)
    item = next(
        obj for obj in harness.board.author_objects if getattr(obj, "object_id", "") == "text-h"
    )
    assert item.box.x > 2.0
