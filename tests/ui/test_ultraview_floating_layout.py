"""Qt-free placement contracts for UltraView's narrow-rail floating chrome."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mf4_analyzer.ui.chart_stack.ultraview.floating_layout import (
    ISLAND_HEIGHT,
    RAIL_WIDTH,
    SAFE_MARGIN,
    CardContextPlacement,
    Rect,
    calculate_floating_layout,
    place_card_context,
)


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "chart_stack"
    / "ultraview"
    / "floating_layout.py"
)


def _assert_inside(rect: Rect, bounds: Rect) -> None:
    assert rect.x >= bounds.x
    assert rect.y >= bounds.y
    assert rect.right <= bounds.right
    assert rect.bottom <= bounds.bottom
    assert rect.width >= 0
    assert rect.height >= 0


def _assert_non_overlapping(rectangles: list[Rect]) -> None:
    for index, first in enumerate(rectangles):
        for second in rectangles[index + 1 :]:
            assert not first.intersects(second), (first, second)


def test_floating_layout_module_is_qt_free():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module.split(".")[0])
    assert "PyQt5" not in imported
    assert "sip" not in imported
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "QWidget" not in source
    assert "MainWindow" not in source


def test_standard_stage_keeps_canvas_target_and_separates_chrome():
    layout = calculate_floating_layout((1280, 800))

    assert SAFE_MARGIN == 12
    assert RAIL_WIDTH == 48
    assert ISLAND_HEIGHT == 40
    assert layout.board == Rect(78, 64, 1190, 724)
    assert layout.board.width >= 1190
    assert layout.board.height >= 700

    for rect in layout.persistent_rects:
        _assert_inside(rect, layout.stage)
    _assert_non_overlapping(list(layout.chrome_rects))


def test_compact_stage_keeps_canvas_target_without_forced_width():
    layout = calculate_floating_layout((800, 560))

    assert layout.board == Rect(78, 64, 710, 484)
    assert layout.board.width >= 710
    assert layout.board.height >= 470
    for rect in layout.persistent_rects:
        _assert_inside(rect, layout.stage)
    _assert_non_overlapping(list(layout.chrome_rects))


def test_overlay_never_participates_in_board_geometry():
    closed = calculate_floating_layout((1280, 800))
    opened = calculate_floating_layout(
        (1280, 800), overlay_open=True, overlay_size=(288, 600)
    )

    assert opened.board == closed.board
    assert opened.overlay is not None
    _assert_inside(opened.overlay, opened.stage)
    assert opened.overlay.left >= opened.rail.right


@pytest.mark.parametrize(
    ("card", "expected_edge"),
    [
        (Rect(300, 14, 320, 160), "below"),
        (Rect(1170, 340, 140, 160), "above"),
        (Rect(420, 700, 320, 68), "above"),
    ],
)
def test_card_context_flips_or_clamps_at_stage_edges(card, expected_edge):
    placement = place_card_context((1280, 800), card, size=(232, 40))

    assert isinstance(placement, CardContextPlacement)
    assert placement.edge == expected_edge
    _assert_inside(placement.rect, Rect(0, 0, 1280, 800))
    if card.x + card.width > 1268:
        assert placement.rect.right == 1268


def test_minimap_moves_above_navigation_and_never_overlaps_it():
    layout = calculate_floating_layout((800, 560), minimap_size=(192, 132))

    assert layout.minimap is not None
    _assert_inside(layout.minimap, layout.stage)
    assert not layout.minimap.intersects(layout.navigation_island)
    assert layout.minimap.bottom <= layout.navigation_island.top


@pytest.mark.parametrize("size", [(-1, -10), (0, 0), (1, 1), (20, 10), (60, 50)])
def test_invalid_or_tiny_stages_produce_only_bounded_nonnegative_rectangles(size):
    layout = calculate_floating_layout(
        size, overlay_open=True, overlay_size=(-10, -20), minimap_size=(300, 300)
    )

    for rect in layout.persistent_rects:
        _assert_inside(rect, layout.stage)
    if layout.overlay is not None:
        _assert_inside(layout.overlay, layout.stage)
    if layout.minimap is not None:
        _assert_inside(layout.minimap, layout.stage)
        assert not layout.minimap.intersects(layout.navigation_island)

    context = place_card_context(size, Rect(-50, -30, -1, -1), size=(-10, -20))
    _assert_inside(context.rect, layout.stage)
