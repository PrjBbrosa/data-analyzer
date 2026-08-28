"""Literal UCAN GridRects and exact-overlap unplaced membership."""
from __future__ import annotations

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
