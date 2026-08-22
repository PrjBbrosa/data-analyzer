"""UltraView move/resize feedback pipeline: Page edge-pan, frames, viewport surface."""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QWidget

from mf4_analyzer.ui.chart_stack.ultraview.elastic_workspace import EDGE_PAN_BAND_PX
from mf4_analyzer.ui.chart_stack.ultraview.viewport_feedback import ViewportFeedbackSurface
from mf4_analyzer.ui.chart_stack.ultraview.widgets import FreeGridBoard

from tests.ui.test_ultraview_page import (
    _Harness,
    _prepare_free_grid,
    _send_mouse_move,
)

_FEEDBACK_DIAGNOSTIC_KEYS = frozenset(
    {
        "planner",
        "presents",
        "paints",
        "generation",
        "gesture_id",
        "layout_revision",
        "present_count",
        "paint_count",
        "feedback_pipeline",
        "_diag_planner_calls",
        "_diag_frame_presents",
        "_feedback_generation",
    }
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


def _payload_keys(value) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(str(key) for key in value)
        for item in value.values():
            keys.update(_payload_keys(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            keys.update(_payload_keys(item))
    return keys


def _assert_feedback_cleared(page, free) -> None:
    QApplication.processEvents()
    surface = free.ghost_overlay()
    counts = free.feedback_pipeline_counts()
    assert not page._edge_pan_timer.isActive()
    assert QWidget.mouseGrabber() is not free
    assert counts["gesture_id"] == 0
    assert surface.gesture_id == 0
    frame = surface.current_frame()
    assert frame is None or str(frame.operation) not in {"move", "resize"}
    assert surface._ghost_rect is None
    assert not surface._badge
    assert free._dimmed_refs == set()
    assert not free._gesture_dimmed


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
        free.feedback_pipeline_counts()["gesture_id"],
        free.feedback_pipeline_counts()["layout_revision"],
    )
    assert after_settle[3] > 0
    assert after_settle[3] == int(free.gesture().gesture_id())
    _hold_ms(qtbot, 500)
    assert not page._edge_pan_timer.isActive()
    assert len(plan_calls) == after_settle[0]
    assert free.feedback_pipeline_counts()["presents"] == after_settle[1]
    assert free.feedback_pipeline_counts()["generation"] == after_settle[2]
    assert free.feedback_pipeline_counts()["gesture_id"] == after_settle[3]
    assert free.feedback_pipeline_counts()["layout_revision"] == after_settle[4]
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
        free.feedback_pipeline_counts()["gesture_id"],
        free.feedback_pipeline_counts()["layout_revision"],
    )
    assert after_settle[3] > 0
    _hold_ms(qtbot, 500)
    assert len(plan_calls) == after_settle[0]
    assert free.feedback_pipeline_counts()["presents"] == after_settle[1]
    assert free.feedback_pipeline_counts()["gesture_id"] == after_settle[3]
    assert free.feedback_pipeline_counts()["layout_revision"] == after_settle[4]
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


def test_release_clears_timer_grab_frame_and_dimming(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "rel-clear")
    page = harness.page
    page.set_board_zoom(1.0)
    end = _start_center_move(page, card, unit=free.metrics().column_width)
    assert free.gesture().is_active()
    assert free.ghost_overlay().is_showing()
    assert free.feedback_pipeline_counts()["gesture_id"] > 0
    QTest.mouseRelease(card, Qt.LeftButton, Qt.NoModifier, end)
    _assert_feedback_cleared(page, free)


def test_escape_cancel_clears_timer_grab_frame_and_dimming(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "esc-clear")
    page = harness.page
    page.set_board_zoom(1.0)
    _start_center_move(page, card, unit=free.metrics().column_width)
    assert free.gesture().is_active()
    assert free.ghost_overlay().is_showing()
    assert page.handle_escape() is True
    _assert_feedback_cleared(page, free)
    assert not free.gesture().is_armed()


def test_feedback_diagnostics_are_not_persisted(qtbot):
    harness = _Harness(qtbot)
    free, (card,) = _prepare_free_grid(harness, qtbot, "diag-persist")
    page = harness.page
    page.set_board_zoom(1.0)
    end = _start_center_move(page, card, unit=free.metrics().column_width)
    counts = free.feedback_pipeline_counts()
    assert counts["planner"] >= 1
    assert counts["presents"] >= 1
    assert counts["gesture_id"] > 0
    payload = page.board_payload()
    keys = _payload_keys(payload)
    assert not (keys & _FEEDBACK_DIAGNOSTIC_KEYS)
    QTest.mouseRelease(card, Qt.LeftButton, Qt.NoModifier, end)
    after = _payload_keys(page.board_payload())
    assert not (after & _FEEDBACK_DIAGNOSTIC_KEYS)


def test_page_does_not_read_private_author_geometry_session():
    page_source = Path(
        FreeGridBoard.__init__.__code__.co_filename
    ).with_name("page.py").read_text(encoding="utf-8")
    assert "_author_geometry_session" not in page_source
    assert "interaction_facts" in page_source
