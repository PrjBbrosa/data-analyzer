"""Qt-free placement contracts for UltraView's narrow-rail floating chrome."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mf4_analyzer.ui.chart_stack.ultraview.floating_layout import (
    ISLAND_GAP,
    ISLAND_HEIGHT,
    OVERLAY_ANCHOR_GLOBAL,
    RAIL_CONTENT_HEIGHT,
    RAIL_TO_CANVAS_GAP,
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
    safe = layout.stage.inset(SAFE_MARGIN)

    fit_left = SAFE_MARGIN + RAIL_WIDTH + RAIL_TO_CANVAS_GAP
    assert SAFE_MARGIN == 12
    assert RAIL_WIDTH == 64
    assert ISLAND_HEIGHT == 40
    assert layout.board == Rect(0, 0, 1280, 800)
    assert layout.fit == Rect(fit_left, 64, 1174, 676)
    assert layout.board.width >= 1182
    assert layout.board.height >= 700
    assert layout.fit.width >= 1174
    assert layout.rail.height <= RAIL_CONTENT_HEIGHT + 8
    assert layout.content_inset_bottom > 0
    assert layout.board_island.left == safe.left
    assert layout.status_island.left == safe.left
    assert layout.global_island.right == safe.right
    assert layout.navigation_island.right == safe.right
    assert layout.fit.left == fit_left
    assert layout.rail.top == safe.top + (safe.height - layout.rail.height) // 2

    for rect in layout.persistent_rects:
        _assert_inside(rect, layout.stage)
    _assert_non_overlapping(list(layout.chrome_rects))


def test_compact_stage_keeps_canvas_target_without_forced_width():
    layout = calculate_floating_layout((800, 560))

    assert layout.board == Rect(0, 0, 800, 560)
    assert layout.rail.width == 52
    assert layout.fit.x == SAFE_MARGIN + layout.rail.width + RAIL_TO_CANVAS_GAP
    assert layout.fit.y == 64
    assert layout.fit.width >= 700
    assert layout.board.width >= 710
    assert layout.board.height >= 470
    for rect in layout.persistent_rects:
        _assert_inside(rect, layout.stage)
    _assert_non_overlapping(list(layout.chrome_rects))


@pytest.mark.parametrize("stage_height", [280, 260, 220, 160])
def test_rail_never_overlaps_board_or_status_island_on_short_stages(stage_height):
    """§4.3: rail separation is a construction guarantee, not a coincidence.

    Before the fix, the rail's vertical position was a pure center-in-safe-
    stage computation with no awareness of BoardIsland/StatusIsland, so short
    stages (~280px tall, well within a realistic docked-panel height) let the
    rail cross into either island.
    """
    layout = calculate_floating_layout((1280, stage_height))

    assert not layout.rail.intersects(layout.board_island)
    assert not layout.rail.intersects(layout.status_island)
    for rect in layout.persistent_rects:
        _assert_inside(rect, layout.stage)


@pytest.mark.parametrize("rail_height", [48, 96, RAIL_CONTENT_HEIGHT])
def test_tool_rail_uses_requested_content_height_and_centers_in_safe_stage(rail_height):
    layout = calculate_floating_layout((1280, 800), rail_size=(RAIL_WIDTH, rail_height))
    safe = layout.stage.inset(SAFE_MARGIN)

    assert layout.rail.left == safe.left
    assert layout.rail.width == RAIL_WIDTH
    assert layout.rail.height == rail_height
    assert layout.rail.top == safe.top + (safe.height - rail_height) // 2
    assert layout.fit.left == layout.rail.right + 18


def test_overlay_never_participates_in_board_geometry():
    closed = calculate_floating_layout((1280, 800))
    opened = calculate_floating_layout(
        (1280, 800), overlay_open=True, overlay_size=(288, 600)
    )

    assert opened.board == closed.board
    assert opened.overlay is not None
    _assert_inside(opened.overlay, opened.stage)
    assert opened.overlay.left >= opened.rail.right


def test_rail_anchored_overlay_stays_vertically_near_its_trigger_button():
    """§4.3: a rail-anchored overlay follows the button that opened it.

    Before the fix, ``_place_overlay`` always hugged BoardIsland's bottom
    edge regardless of which rail button was pressed, so a button near the
    bottom of a tall rail popped a panel far away at the top of the canvas.
    """
    layout = calculate_floating_layout((1280, 800))
    rail = layout.rail
    trigger = Rect(rail.left, rail.bottom - 40, rail.width, 32)

    opened = calculate_floating_layout(
        (1280, 800),
        overlay_open=True,
        overlay_size=(280, 160),
        trigger_rect=trigger,
    )

    assert opened.overlay is not None
    _assert_inside(opened.overlay, opened.stage)
    assert not opened.overlay.intersects(opened.board_island)
    assert not opened.overlay.intersects(opened.navigation_island)
    # "Vertically near": the overlay's vertical center sits close to the
    # trigger's, not clear across the stage near BoardIsland.
    trigger_center = trigger.top + trigger.height / 2
    overlay_center = opened.overlay.top + opened.overlay.height / 2
    assert abs(overlay_center - trigger_center) <= trigger.height + ISLAND_GAP
    # And it should have moved well away from the always-hug-board-island
    # default that a trigger-less call still produces.
    default = calculate_floating_layout(
        (1280, 800), overlay_open=True, overlay_size=(280, 160)
    )
    assert opened.overlay.top > default.overlay.top


def test_global_overlay_right_aligns_under_global_island():
    layout = calculate_floating_layout(
        (1280, 800),
        overlay_open=True,
        overlay_size=(244, 154),
        overlay_anchor=OVERLAY_ANCHOR_GLOBAL,
    )

    assert layout.overlay is not None
    _assert_inside(layout.overlay, layout.stage)
    assert layout.overlay.right == layout.global_island.right
    assert layout.overlay.top >= layout.global_island.bottom
    assert layout.overlay.left > layout.rail.right
    assert not layout.overlay.intersects(layout.board_island)


def test_global_overlay_stays_off_the_rail_when_it_must_clear_board_island():
    layout = calculate_floating_layout(
        (800, 560),
        overlay_open=True,
        overlay_size=(520, 180),
        overlay_anchor=OVERLAY_ANCHOR_GLOBAL,
    )

    assert layout.overlay is not None
    _assert_inside(layout.overlay, layout.stage)
    assert layout.overlay.left > layout.rail.right
    assert not layout.overlay.intersects(layout.board_island)


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


def test_minimap_omitted_when_size_is_none():
    layout = calculate_floating_layout((1280, 800), minimap_size=None)
    assert layout.minimap is None


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


def test_card_context_avoids_board_island():
    island = Rect(78, 12, 200, 40)
    card = Rect(90, 64, 320, 180)
    placement = place_card_context((1280, 800), card, size=(232, 40), avoid=(island,))
    assert not placement.rect.intersects(island)
    _assert_inside(placement.rect, Rect(0, 0, 1280, 800))
