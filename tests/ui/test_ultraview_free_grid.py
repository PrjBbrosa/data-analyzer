"""Pure P2-A free-grid geometry and command contracts."""
from __future__ import annotations

from mf4_analyzer.ui.chart_stack.ultraview.free_grid import (
    GRID_MIN_COLUMN_WIDTH,
    HANDLE_HIT_PX,
    avoidance_preferred_delta,
    candidate_move,
    candidate_resize,
    candidate_resize_handle,
    clamp_rect,
    export_grid_metrics,
    grid_metrics,
    group_translate_rects,
    hit_handle,
    keep_aspect_resize,
    legal_grid_rect,
    pixels_to_grid_delta,
    plan_boundary_yield,
    plan_neighbor_shrink,
    plan_overlap_avoidance,
    rect_is_available,
    rect_to_pixels,
    rects_overlap,
    snapped_move_rect,
    snapped_resize_rect,
    translated_move_rect,
    union_grid_rect,
)
from mf4_analyzer.ui.chart_stack.ultraview.gesture import FreeGridGesture
from mf4_analyzer.ui.ultraview_state import (
    GRID_COLUMNS,
    MAX_GRID_ROWS,
    FreeGridPlacement,
    GridRect,
    make_ref,
    organized_placements,
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


def test_snapped_move_rect_matches_candidate_move_and_stays_clamped():
    metrics = grid_metrics((1280, 800), [])
    origin = GridRect(0, 0, 6, 3)
    delta = (10_000, 0)
    snapped = snapped_move_rect(origin, delta, metrics)
    assert snapped == candidate_move(origin, *pixels_to_grid_delta(delta, metrics))
    assert snapped == clamp_rect(snapped)
    assert snapped.column + snapped.column_span <= GRID_COLUMNS


def test_legal_grid_rect_clamps_origin_plus_span():
    metrics = grid_metrics((1280, 800), [])
    legal = legal_grid_rect((metrics.board_width - 2, 20), metrics, column_span=6, row_span=3)
    assert legal == clamp_rect(legal)
    assert legal.column + legal.column_span <= GRID_COLUMNS


def test_gesture_move_uses_snapped_move_rect_and_reports_collision():
    metrics = grid_metrics((1280, 800), [])
    origin = GridRect(0, 0, 4, 3)
    other = GridRect(6, 0, 4, 3)
    placements = [_placement("a", origin), _placement("b", other)]
    gesture = FreeGridGesture()
    gesture.press(make_ref("time", "a"), origin, (10, 10), (10, 10))
    idle = gesture.update((12, 10), metrics, placements, start_drag_distance=20)
    assert idle is not None and not idle.active
    unit = metrics.column_width + metrics.gutter
    session = gesture.update((10 + unit * 6, 10), metrics, placements, start_drag_distance=20)
    assert session is not None and session.active
    assert session.candidate == snapped_move_rect(origin, (unit * 6, 0), metrics)
    assert session.legal is False
    cancelled = gesture.cancel()
    assert cancelled is session
    assert gesture.is_armed() is False


def test_gesture_move_keeps_out_of_bounds_candidate_illegal():
    metrics = grid_metrics((1280, 800), [])
    origin = GridRect(0, 0, 4, 3)
    placements = [_placement("a", origin)]
    gesture = FreeGridGesture()
    gesture.press(make_ref("time", "a"), origin, (10, 10), (10, 10))
    unit = metrics.column_width + metrics.gutter
    session = gesture.update(
        (10 - unit * 8, 10), metrics, placements, start_drag_distance=20
    )
    assert session is not None and session.active
    assert session.candidate == translated_move_rect(origin, (-unit * 8, 0), metrics)
    assert session.candidate != clamp_rect(session.candidate)
    assert session.legal is False


def test_handle_hit_zones_are_at_least_eight_px_and_corners_win():
    card = (0, 0, 120, 80)
    assert HANDLE_HIT_PX >= 8
    assert hit_handle(card, (4, 4)) == "nw"
    assert hit_handle(card, (116, 4)) == "ne"
    assert hit_handle(card, (60, 4)) == "n"
    assert hit_handle(card, (116, 40)) == "e"
    assert hit_handle(card, (4, 40)) == "w"
    assert hit_handle(card, (60, 20)) is None
    east = hit_handle(card, (120 - HANDLE_HIT_PX, 40))
    assert east == "e"
    assert hit_handle(card, (120 - HANDLE_HIT_PX - 1, 40)) is None


def test_resize_handle_snaps_clamps_and_keeps_aspect():
    metrics = grid_metrics((1280, 800), [])
    origin = GridRect(0, 0, 6, 3)
    unit = metrics.column_width + metrics.gutter
    grown = snapped_resize_rect(origin, (unit * 2, 0), metrics, "e")
    assert grown == GridRect(0, 0, 8, 3)
    assert grown.column_span <= 12
    clamped = candidate_resize_handle(origin, "e", 40, 0)
    assert clamped.column_span == 12
    assert clamped.row_span == 3
    shrunk = candidate_resize_handle(origin, "e", -40, 0)
    assert shrunk.column_span == 2
    ratio = keep_aspect_resize(origin, GridRect(0, 0, 8, 3), "e")
    assert ratio == GridRect(0, 0, 8, 4)
    gesture = FreeGridGesture()
    gesture.press_resize(make_ref("time", "a"), origin, "e", (100, 50), (4, 50))
    session = gesture.update(
        (100 + unit * 2, 50), metrics, [_placement("a", origin)], 1, keep_aspect=True
    )
    assert session is not None
    assert session.badge() == "8×4"
    assert session.candidate.column_span <= 12
    assert session.candidate.row_span <= 8


def test_union_and_group_translate_reject_overflow_or_union_collision():
    first = GridRect(0, 0, 6, 3)
    second = GridRect(6, 0, 6, 3)
    blocker = GridRect(0, 3, 4, 3)
    union = union_grid_rect((first, second))
    assert union == GridRect(0, 0, 12, 3)
    selected = {
        make_ref("time", "a"): first,
        make_ref("time", "b"): second,
    }
    down, legal_down = group_translate_rects(selected, (), 0, 1)
    assert legal_down is True
    assert down[make_ref("time", "a")] == GridRect(0, 1, 6, 3)
    assert down[make_ref("time", "b")] == GridRect(6, 1, 6, 3)
    _overflow, legal_right = group_translate_rects(selected, (), 1, 0)
    assert legal_right is False
    _blocked, legal_blocked = group_translate_rects(selected, (blocker,), 0, 1)
    assert legal_blocked is False
    empty, legal_empty = group_translate_rects({}, (), 1, 0)
    assert legal_empty is False
    assert empty == {}


def test_avoidance_preferred_delta_follows_move_then_resize_axis():
    origin = GridRect(0, 0, 6, 3)
    assert avoidance_preferred_delta(origin, GridRect(2, 0, 6, 3)) == (1, 0)
    assert avoidance_preferred_delta(origin, GridRect(0, 4, 6, 3)) == (0, 1)
    assert avoidance_preferred_delta(origin, GridRect(0, 0, 8, 3)) == (1, 0)
    assert avoidance_preferred_delta(origin, GridRect(0, 0, 6, 5)) == (0, 1)


def test_overlap_avoidance_slides_blocker_down_when_right_is_blocked():
    first = _placement("a", GridRect(0, 0, 6, 3))
    second = _placement("b", GridRect(6, 0, 6, 3))
    updates, ok = plan_overlap_avoidance(
        {first.ref: GridRect(6, 0, 6, 3)},
        [first, second],
        preferred=(1, 0),
    )
    assert ok is True
    by_ref = dict(updates)
    assert by_ref[first.ref] == GridRect(6, 0, 6, 3)
    assert by_ref[second.ref] == GridRect(6, 3, 6, 3)


def test_overlap_avoidance_slides_blocker_along_preferred_axis_when_open():
    first = _placement("a", GridRect(0, 0, 4, 3))
    second = _placement("b", GridRect(4, 0, 4, 3))
    updates, ok = plan_overlap_avoidance(
        {first.ref: GridRect(4, 0, 4, 3)},
        [first, second],
        preferred=(1, 0),
    )
    assert ok is True
    by_ref = dict(updates)
    assert by_ref[second.ref] == GridRect(8, 0, 4, 3)


def test_overlap_avoidance_fails_when_board_is_packed():
    cards = [
        _placement(f"c{index}", GridRect(0, index * 8, 12, 8))
        for index in range(6)
    ]
    updates, ok = plan_overlap_avoidance(
        {cards[0].ref: GridRect(0, 1, 12, 8)},
        cards,
        preferred=(0, 1),
    )
    assert ok is False
    assert updates == ()


def test_boundary_yield_clamps_into_empty_cell():
    card = _placement("a", GridRect(2, 0, 4, 3))
    updates, ok = plan_boundary_yield(
        {card.ref: GridRect(-2, 0, 4, 3)},
        [card],
        preferred=(-1, 0),
    )
    assert ok is True
    assert dict(updates)[card.ref] == GridRect(0, 0, 4, 3)


def test_boundary_yield_shrinks_left_neighbors_when_mover_hits_right_wall():
    left_top = _placement("a", GridRect(0, 0, 4, 3))
    left_bottom = _placement("b", GridRect(0, 3, 4, 3))
    mover = _placement("c", GridRect(4, 0, 8, 6))
    updates, ok = plan_boundary_yield(
        {mover.ref: GridRect(5, 0, 8, 6)},
        [left_top, left_bottom, mover],
        preferred=(1, 0),
    )
    assert ok is True
    by_ref = dict(updates)
    assert by_ref[mover.ref] == GridRect(3, 0, 9, 6)
    assert by_ref[left_top.ref] == GridRect(0, 0, 3, 3)
    assert by_ref[left_bottom.ref] == GridRect(0, 3, 3, 3)


def test_boundary_yield_fails_when_left_neighbors_are_already_minimum():
    left_top = _placement("a", GridRect(0, 0, 2, 3))
    left_bottom = _placement("b", GridRect(0, 3, 2, 3))
    mover = _placement("c", GridRect(2, 0, 10, 6))
    updates, ok = plan_boundary_yield(
        {mover.ref: GridRect(3, 0, 10, 6)},
        [left_top, left_bottom, mover],
        preferred=(1, 0),
    )
    assert ok is False
    assert updates == ()


def test_boundary_yield_ignores_in_bounds_incoming():
    first = _placement("a", GridRect(0, 0, 6, 3))
    second = _placement("b", GridRect(6, 0, 6, 3))
    updates, ok = plan_boundary_yield(
        {first.ref: GridRect(6, 0, 6, 3)},
        [first, second],
        preferred=(1, 0),
    )
    assert ok is False
    assert updates == ()


def test_neighbor_shrink_packs_blockers_into_remaining_columns():
    left_top = _placement("a", GridRect(0, 0, 4, 3))
    left_bottom = _placement("b", GridRect(0, 3, 4, 3))
    mover = _placement("c", GridRect(4, 0, 8, 6))
    updates, ok = plan_neighbor_shrink(
        {mover.ref: GridRect(0, 0, 10, 6)},
        [left_top, left_bottom, mover],
    )
    assert ok is True
    by_ref = dict(updates)
    assert by_ref[mover.ref] == GridRect(0, 0, 10, 6)
    assert by_ref[left_top.ref] == GridRect(10, 0, 2, 3)
    assert by_ref[left_bottom.ref] == GridRect(10, 3, 2, 3)


def test_neighbor_shrink_fails_below_minimum_span():
    left = _placement("a", GridRect(0, 0, 2, 3))
    mover = _placement("c", GridRect(2, 0, 10, 3))
    updates, ok = plan_neighbor_shrink(
        {mover.ref: GridRect(0, 0, 11, 3)},
        [left, mover],
    )
    assert ok is False
    assert updates == ()
