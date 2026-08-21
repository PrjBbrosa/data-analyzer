"""UltraView move/resize feedback pipeline: Page edge-pan, frames, viewport surface."""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.chart_stack.ultraview.elastic_workspace import EDGE_PAN_BAND_PX
from mf4_analyzer.ui.chart_stack.ultraview.viewport_feedback import ViewportFeedbackSurface
from mf4_analyzer.ui.chart_stack.ultraview.widgets import FreeGridBoard

from tests.ui.test_ultraview_page import (
    _Harness,
    _prepare_free_grid,
    _send_mouse_move,
)


def _wrap_plan_layout(monkeypatch):
    import mf4_analyzer.ui.chart_stack.ultraview.gesture as gesture_mod

    calls: list[object] = []
    real = gesture_mod.plan_layout

    def wrapped(*args, **kwargs):
        calls.append(args[2] if len(args) > 2 else kwargs.get("target"))
        return real(*args, **kwargs)

    monkeypatch.setattr(gesture_mod, "plan_layout", wrapped)
    return calls


def _center_card_in_viewport(page, card) -> None:
    viewport = page.board_scroll_area().viewport()
    board = page._free_grid
    target = card.mapTo(board, QPoint(card.width() // 2, card.height() // 2))
    page._board_scroll.horizontalScrollBar().setValue(
        max(0, target.x() - viewport.width() // 2)
    )
    page._board_scroll.verticalScrollBar().setValue(
        max(0, target.y() - viewport.height() // 2)
    )
    QApplication.processEvents()
    local = viewport.mapFromGlobal(card.mapToGlobal(QPoint(16, 16)))
    assert EDGE_PAN_BAND_PX < local.x() < viewport.width() - EDGE_PAN_BAND_PX
    assert EDGE_PAN_BAND_PX < local.y() < viewport.height() - EDGE_PAN_BAND_PX


def _hold_ms(qtbot, ms: int) -> None:
    qtbot.wait(ms)
    QApplication.processEvents()


def _start_center_move(page, card, *, unit: int) -> QPoint:
    _center_card_in_viewport(page, card)
    start = QPoint(16, 16)
    end = QPoint(start.x() + max(unit, QApplication.startDragDistance() + 8), start.y())
    QTest.mousePress(card, Qt.LeftButton, Qt.NoModifier, start)
    _send_mouse_move(card, end)
    QApplication.processEvents()
    return end


def test_full_page_stationary_center_move_does_not_represent(qtbot, monkeypatch):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "hold-move")
    page = harness.page
    page.set_board_zoom(1.0)
    plan_calls = _wrap_plan_layout(monkeypatch)
    end = _start_center_move(page, card, unit=free.metrics().column_width)
    assert free.gesture().is_active()
    assert not page._edge_pan_timer.isActive()
    QApplication.processEvents()
    after_settle = (
        len(plan_calls),
        free.feedback_pipeline_counts()["presents"],
        free.feedback_pipeline_counts()["generation"],
    )
    _hold_ms(qtbot, 500)
    assert not page._edge_pan_timer.isActive()
    assert len(plan_calls) == after_settle[0]
    assert free.feedback_pipeline_counts()["presents"] == after_settle[1]
    assert free.feedback_pipeline_counts()["generation"] == after_settle[2]
    QTest.mouseRelease(card, Qt.LeftButton, Qt.NoModifier, end)


def test_full_page_stationary_center_resize_does_not_represent(qtbot, monkeypatch):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "hold-resize")
    page = harness.page
    page.set_board_zoom(1.0)
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier, QPoint(40, 40))
    QApplication.processEvents()
    _center_card_in_viewport(page, card)
    plan_calls = _wrap_plan_layout(monkeypatch)
    handle = QPoint(card.width() - 2, card.height() // 2)
    unit = free.metrics().column_width + free.metrics().gutter
    end = QPoint(handle.x() + unit, handle.y())
    QTest.mousePress(card, Qt.LeftButton, Qt.NoModifier, handle)
    _send_mouse_move(card, end)
    QApplication.processEvents()
    session = free.gesture().session()
    assert session is not None and session.handle is not None
    assert free.ghost_overlay()._badge
    assert not page._edge_pan_timer.isActive()
    after_settle = (
        len(plan_calls),
        free.feedback_pipeline_counts()["presents"],
        free.feedback_pipeline_counts()["generation"],
    )
    _hold_ms(qtbot, 500)
    assert len(plan_calls) == after_settle[0]
    assert free.feedback_pipeline_counts()["presents"] == after_settle[1]
    assert free.ghost_overlay()._badge == session.badge()
    QTest.mouseRelease(card, Qt.LeftButton, Qt.NoModifier, end)


def test_workspace_timer_uses_latest_pointer_not_first_pointer(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "latest-ptr")
    page = harness.page
    page.set_board_zoom(1.0)
    _center_card_in_viewport(page, card)
    start = QPoint(16, 16)
    QTest.mousePress(card, Qt.LeftButton, Qt.NoModifier, start)
    _send_mouse_move(card, QPoint(start.x() + 24, start.y()))
    QApplication.processEvents()
    first = QPoint(page._edge_pan_global_pos) if page._edge_pan_global_pos else None
    viewport = page.board_scroll_area().viewport()
    b = viewport.mapToGlobal(QPoint(viewport.width() // 2, viewport.height() // 2))
    c = viewport.mapToGlobal(QPoint(2, max(1, viewport.height() // 2)))
    free.workspace_pointer_changed.emit(int(free.gesture().gesture_id()), b)
    free.workspace_pointer_changed.emit(int(free.gesture().gesture_id()), c)
    assert page._edge_pan_global_pos == c
    assert first != c
    seen: list[QPoint] = []
    real = free.reproject_after_viewport_change

    def wrapped(global_pos):
        seen.append(QPoint(global_pos) if global_pos is not None else QPoint())
        return real(global_pos)

    free.reproject_after_viewport_change = wrapped
    page._edge_pan_tick_for_global(page._edge_pan_global_pos)
    if seen:
        assert seen[-1] == c
    QTest.mouseRelease(card, Qt.LeftButton, Qt.NoModifier, start)


def test_zero_edge_velocity_never_reprojects_gesture(qtbot, monkeypatch):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "zero-vel")
    page = harness.page
    page.set_board_zoom(1.0)
    plan_calls = _wrap_plan_layout(monkeypatch)
    end = _start_center_move(page, card, unit=free.metrics().column_width)
    before = (len(plan_calls), page._diag_reproject_calls, free.feedback_pipeline_counts()["presents"])
    center = page.board_scroll_area().viewport().mapToGlobal(
        QPoint(
            page.board_scroll_area().viewport().width() // 2,
            page.board_scroll_area().viewport().height() // 2,
        )
    )
    page._edge_pan_global_pos = center
    page._edge_pan_tick_for_global(center)
    QApplication.processEvents()
    assert len(plan_calls) == before[0]
    assert page._diag_reproject_calls == before[1]
    assert free.feedback_pipeline_counts()["presents"] == before[2]
    QTest.mouseRelease(card, Qt.LeftButton, Qt.NoModifier, end)


def test_feedback_surface_is_bounded_to_viewport(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "bound-surface")
    page = harness.page
    viewport = page.board_scroll_area().viewport()
    surface = free.ghost_overlay()
    assert isinstance(surface, ViewportFeedbackSurface)
    assert surface.parentWidget() is viewport
    assert surface.width() * surface.height() <= viewport.width() * viewport.height()
    assert surface.width() <= viewport.width()
    assert surface.height() <= viewport.height()
    assert free.width() * free.height() > surface.width() * surface.height() or (
        free.width() <= viewport.width() and free.height() <= viewport.height()
    )
    _start_center_move(page, card, unit=free.metrics().column_width)
    QApplication.processEvents()
    assert surface.width() <= viewport.width()
    assert surface.height() <= viewport.height()
    QTest.mouseRelease(card, Qt.LeftButton, Qt.NoModifier, QPoint(24, 16))


def test_expose_repaints_cached_frame_without_replanning(qtbot, monkeypatch):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "expose-frame")
    page = harness.page
    page.set_board_zoom(1.0)
    plan_calls = _wrap_plan_layout(monkeypatch)
    end = _start_center_move(page, card, unit=free.metrics().column_width)
    surface = free.ghost_overlay()
    QApplication.processEvents()
    before = (
        len(plan_calls),
        free.feedback_pipeline_counts()["presents"],
        free.feedback_pipeline_counts()["generation"],
        surface.paint_count,
    )
    QApplication.sendEvent(surface, QEvent(QEvent.Expose))
    surface.update()
    QApplication.processEvents()
    assert len(plan_calls) == before[0]
    assert free.feedback_pipeline_counts()["presents"] == before[1]
    assert free.feedback_pipeline_counts()["generation"] == before[2]
    assert surface.paint_count >= before[3]
    assert surface.is_showing()
    QTest.mouseRelease(card, Qt.LeftButton, Qt.NoModifier, end)


def test_stale_clear_cannot_hide_newer_gesture_frame(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "stale-clear")
    page = harness.page
    page.set_board_zoom(1.0)
    end = _start_center_move(page, card, unit=free.metrics().column_width)
    first_id = int(free.gesture().gesture_id())
    QTest.mouseRelease(card, Qt.LeftButton, Qt.NoModifier, end)
    QApplication.processEvents()
    end = _start_center_move(page, card, unit=free.metrics().column_width * 2)
    second_id = int(free.gesture().gesture_id())
    assert second_id != first_id
    surface = free.ghost_overlay()
    assert surface.is_showing()
    surface.clear(first_id)
    QApplication.processEvents()
    assert surface.is_showing()
    assert int(surface._gesture_id) == second_id
    QTest.mouseRelease(card, Qt.LeftButton, Qt.NoModifier, end)


def test_free_grid_board_does_not_own_full_board_ghost_overlay():
    source = open(FreeGridBoard.__init__.__code__.co_filename, encoding="utf-8").read()
    assert "self._overlay = ViewportFeedbackSurface(self)" in source
    assert "self._overlay = GhostOverlay(self)" in source
    free_init = source.split("class FreeGridBoard")[1].split("class BoardScrollArea")[0]
    assert "ViewportFeedbackSurface(self)" in free_init
    assert "GhostOverlay(self)" not in free_init
