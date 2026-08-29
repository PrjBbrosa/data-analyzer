"""Literal UCAN GridRects and exact-overlap unplaced membership."""
from __future__ import annotations

import pytest

from mf4_analyzer.ultraview_core.model import (
    GridRect,
    UltraViewRef,
    default_board,
)
from mf4_analyzer.ultraview_core.native_layout import (
    NativeLayoutRect,
    plan_native_layout,
)
from mf4_analyzer.ultraview_core.board_ops import apply_native_layout


UCAN_MM = (
    NativeLayoutRect(25.0, 65.0, 100.0, 60.0),
    NativeLayoutRect(41.0, 138.2, 90.0, 60.0),
    NativeLayoutRect(147.5, 62.5, 50.0, 60.0),
    NativeLayoutRect(215.5, 62.5, 50.0, 60.0),
    NativeLayoutRect(147.5, 138.0, 50.0, 60.0),
    NativeLayoutRect(214.5, 138.0, 50.0, 60.0),
    NativeLayoutRect(214.5, 138.0, 50.0, 60.0),
)


def test_ucan_plan_has_literal_gridrects_and_seventh_unplaced():
    refs = tuple(UltraViewRef("time", f"v{i}") for i in range(7))
    plan = plan_native_layout(list(zip(refs, UCAN_MM)))
    assert plan.placed == (
        (refs[0], GridRect(0, 0, 10, 6)),
        (refs[1], GridRect(2, 8, 9, 6)),
        (refs[2], GridRect(12, 0, 5, 6)),
        (refs[3], GridRect(19, 0, 5, 6)),
        (refs[4], GridRect(12, 8, 5, 6)),
        (refs[5], GridRect(19, 8, 5, 6)),
    )
    assert plan.unplaced == (refs[6],)
    assert plan.warnings == ("exact_overlap: 7 -> 6",)


def test_apply_native_layout_is_one_board_mutation():
    refs = tuple(UltraViewRef("time", f"v{i}") for i in range(7))
    plan = plan_native_layout(list(zip(refs, UCAN_MM)))
    board = default_board()
    warnings = apply_native_layout(board, plan)
    assert [item.rect for item in board.free_grid] == [
        GridRect(0, 0, 10, 6),
        GridRect(2, 8, 9, 6),
        GridRect(12, 0, 5, 6),
        GridRect(19, 0, 5, 6),
        GridRect(12, 8, 5, 6),
        GridRect(19, 8, 5, 6),
    ]
    assert board.unplaced == [refs[6]]
    assert "exact_overlap: 7 -> 6" in warnings


def test_coordinator_commits_native_layout_to_its_owned_workspace(qapp):
    from PyQt5.QtWidgets import QWidget

    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controller = coordinator._workspace_controller
    board = coordinator.board
    try:
        placed_ids = coordinator.add_time_views_from_native_layout(
            (
                ("view-left", NativeLayoutRect(0.0, 60.0, 100.0, 60.0)),
                ("view-right", NativeLayoutRect(120.0, 60.0, 100.0, 60.0)),
            )
        )

        assert coordinator.workspace is controller.workspace
        assert coordinator.board is board
        assert placed_ids == ("view-left", "view-right")
        assert [(item.ref, item.rect) for item in board.free_grid] == [
            (UltraViewRef("time", "view-left"), GridRect(0, 0, 11, 7)),
            (UltraViewRef("time", "view-right"), GridRect(13, 0, 11, 7)),
        ]
        assert board.unplaced == []
        history = controller.grid_histories[board.board_id]
        assert len(history.undo) == 1
        assert history.redo == []
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()


def test_workspace_controller_commits_native_layout_with_overlap_warning(qapp):
    from PyQt5.QtWidgets import QWidget

    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controller = coordinator._workspace_controller
    board = coordinator.board
    refs = (
        UltraViewRef("time", "view-front"),
        UltraViewRef("time", "view-overlap"),
    )
    plan = plan_native_layout(
        (
            (refs[0], NativeLayoutRect(0.0, 60.0, 100.0, 60.0)),
            (refs[1], NativeLayoutRect(0.0, 60.0, 100.0, 60.0)),
        )
    )
    coordinator.workspace.opaque_payload = {"schema": 999}
    refreshes: list[None] = []
    controller._refresh_projection = lambda: refreshes.append(None)
    try:
        placed_ids = controller.apply_native_layout_plan(plan)

        assert placed_ids == ("view-front",)
        assert [(item.ref, item.rect) for item in board.free_grid] == [
            (refs[0], GridRect(0, 0, 24, 14)),
        ]
        assert board.unplaced == [refs[1]]
        history = controller.grid_histories[board.board_id]
        assert len(history.undo) == 1
        assert history.redo == []
        assert coordinator.workspace.opaque_payload is None
        assert refreshes == [None]
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()


def test_coordinator_rejects_incomplete_native_layout_before_mutating(qapp):
    from PyQt5.QtWidgets import QWidget

    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controller = coordinator._workspace_controller
    board = coordinator.board
    try:
        with pytest.raises(AttributeError):
            coordinator.add_time_views_from_native_layout(
                (
                    ("valid", NativeLayoutRect(0.0, 60.0, 100.0, 60.0)),
                    ("invalid", object()),
                )
            )

        assert board.free_grid == []
        assert board.unplaced == []
        assert board.board_id not in controller.grid_histories
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()
