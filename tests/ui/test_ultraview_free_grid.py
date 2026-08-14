"""Pure P2-A free-grid geometry and command contracts."""
from __future__ import annotations

from mf4_analyzer.ui.chart_stack.ultraview.free_grid import (
    GRID_MIN_COLUMN_WIDTH,
    candidate_move,
    candidate_resize,
    clamp_rect,
    export_grid_metrics,
    grid_metrics,
    organized_placements,
    pixels_to_grid_delta,
    rect_is_available,
    rect_to_pixels,
    rects_overlap,
)
from mf4_analyzer.ui.ultraview_state import (
    GRID_COLUMNS,
    MAX_GRID_ROWS,
    FreeGridPlacement,
    GridRect,
    make_ref,
)


def _placement(view_id: str, rect: GridRect) -> FreeGridPlacement:
    return FreeGridPlacement(make_ref("time", view_id), rect)


def test_grid_metrics_keeps_twelve_columns_chrome_readable_and_scrollable():
    metrics = grid_metrics((1280, 800), [])
    assert metrics.column_width >= GRID_MIN_COLUMN_WIDTH
    assert metrics.board_width > 1280
    assert metrics.board_height == 800
    assert metrics.content_width >= 12 * GRID_MIN_COLUMN_WIDTH + 11 * metrics.gutter


def test_grid_pixel_mapping_is_inside_logical_canvas_and_non_overlapping():
    placements = [
        _placement("a", GridRect(0, 0, 6, 3)),
        _placement("b", GridRect(6, 0, 6, 3)),
        _placement("c", GridRect(0, 3, 4, 5)),
    ]
    metrics = grid_metrics((1600, 900), placements)
    pixels = [rect_to_pixels(item.rect, metrics) for item in placements]
    for x, y, width, height in pixels:
        assert x >= metrics.padding and y >= metrics.padding
        assert x + width <= metrics.board_width - metrics.padding
        assert y + height <= metrics.board_height - metrics.padding
    assert not rects_overlap(placements[0].rect, placements[1].rect)
    assert pixels_to_grid_delta((metrics.column_width + metrics.gutter, 0), metrics) == (1, 0)
    assert pixels_to_grid_delta((0, -(metrics.row_height + metrics.gutter)), metrics) == (0, -1)


def test_move_resize_candidate_and_collision_rejection_are_deterministic():
    first = _placement("a", GridRect(0, 0, 4, 3))
    second = _placement("b", GridRect(4, 0, 4, 3))
    candidate = candidate_move(first.rect, 4, 0)
    assert not rect_is_available(candidate, [first, second], excluding=first.ref)
    resized = candidate_resize(first.rect, 2, 0)
    assert not rect_is_available(resized, [first, second], excluding=first.ref)
    assert candidate_move(first.rect, -10, -10) == GridRect(0, 0, 4, 3)
    assert candidate_resize(first.rect, -10, -10) == GridRect(0, 0, 2, 2)


def test_organize_only_removes_fully_empty_rows_and_is_idempotent():
    placements = [
        _placement("a", GridRect(0, 2, 4, 2)),
        _placement("b", GridRect(6, 5, 3, 3)),
    ]
    organized = organized_placements(placements)
    assert [item.rect for item in organized] == [GridRect(0, 0, 4, 2), GridRect(6, 2, 3, 3)]
    assert organized_placements(organized) == organized


def test_clamp_rect_keeps_origin_plus_span_inside_board():
    legal = clamp_rect(GridRect(11, 47, 6, 3))
    assert legal.column_span == 6
    assert legal.row_span == 3
    assert legal.column + legal.column_span <= GRID_COLUMNS
    assert legal.row + legal.row_span <= MAX_GRID_ROWS


def test_export_grid_metrics_crop_short_boards_and_keep_screen_floor():
    short = [_placement("a", GridRect(0, 0, 4, 2))]
    screen = grid_metrics((1600, 900), short)
    export = export_grid_metrics(short)
    assert screen.board_height == 900
    assert export.board_height < 900
    assert export.board_width == 1600
