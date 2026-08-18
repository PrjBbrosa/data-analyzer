"""Pure P2-A free-grid geometry and command contracts."""
from __future__ import annotations

from dataclasses import replace

import pytest

from mf4_analyzer.ui.chart_stack.ultraview.free_grid import (
    GRID_MIN_COLUMN_WIDTH,
    GRID_MIN_VISIBLE_ROWS,
    GRID_ROW_HEIGHT,
    GRID_SPARE_ROWS,
    FIT_SHORT_SIDE_GROW_MAX,
    HANDLE_HIT_PX,
    LAYOUT_MOVE,
    LAYOUT_RESIZE,
    LAYOUT_ARRANGE,
    PLANNER_SEARCH_CAP,
    LayoutRejectReason,
    avoidance_preferred_delta,
    candidate_move,
    candidate_resize,
    candidate_resize_handle,
    clamp_rect,
    export_grid_metrics,
    fit_rect_for_aspect,
    grid_metrics,
    group_translate_rects,
    hit_handle,
    keep_aspect_resize,
    legal_grid_rect,
    pixels_to_grid_delta,
    plan_layout,
    plan_auto_arrange,
    plan_neighbor_shrink,
    plan_overlap_avoidance,
    rect_is_available,
    rect_to_pixels,
    rects_overlap,
    screen_grid_metrics,
    snapped_move_rect,
    snapped_resize_rect,
    translated_move_rect,
    union_grid_rect,
)
from mf4_analyzer.ui.chart_stack.ultraview.layouts import (
    BASE_BOARD_SIZE,
    CARD_FIT_CHROME_HEIGHT,
    CARD_FOOTER_HEIGHT,
    CARD_HEADER_HEIGHT,
    CARD_IMAGE_PADDING,
    MIN_CARD_CHROME_HEIGHT,
    preview_reading_box,
)
from mf4_analyzer.ui.chart_stack.ultraview.gesture import FreeGridGesture
from mf4_analyzer.ui.ultraview_state import (
    GRID_COLUMNS,
    GRID_MAX_COLUMN_SPAN,
    GRID_MAX_ROW_SPAN,
    GRID_MIN_COLUMN_SPAN,
    GRID_MIN_ROW_SPAN,
    SAFETY_COLUMN_MAX,
    SAFETY_COLUMN_MIN,
    SAFETY_ROW_MAX,
    SAFETY_ROW_MIN,
    FreeGridPlacement,
    GridRect,
    default_board,
    make_ref,
    organized_placements,
    place_free_grid_from_unplaced,
)


def _placement(view_id: str, rect: GridRect) -> FreeGridPlacement:
    return FreeGridPlacement(make_ref("time", view_id), rect)


def test_grid_metrics_keeps_twelve_columns_chrome_readable_and_scrollable():
    metrics = grid_metrics((1280, 800), [])
    assert metrics.column_width >= GRID_MIN_COLUMN_WIDTH
    assert metrics.board_width > 1280
    floor_h = (
        32
        + GRID_MIN_VISIBLE_ROWS * GRID_ROW_HEIGHT
        + (GRID_MIN_VISIBLE_ROWS - 1) * metrics.gutter
    )
    assert metrics.board_height == max(800, floor_h)
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
    assert candidate_move(first.rect, -10, -10) == GridRect(-10, -10, 4, 3)
    assert candidate_move(first.rect, -100, -100) == GridRect(
        SAFETY_COLUMN_MIN, SAFETY_ROW_MIN, 4, 3
    )
    assert candidate_resize(first.rect, -10, -10) == GridRect(0, 0, 2, 2)


def test_organize_only_removes_fully_empty_rows_and_is_idempotent():
    placements = [
        _placement("a", GridRect(0, 2, 4, 2)),
        _placement("b", GridRect(6, 5, 3, 3)),
    ]
    organized = organized_placements(placements)
    assert [item.rect for item in organized] == [GridRect(0, 0, 4, 2), GridRect(6, 2, 3, 3)]
    assert organized_placements(organized) == organized


def test_clamp_rect_keeps_origin_plus_span_inside_safety():
    still_legal = clamp_rect(GridRect(11, 47, 6, 3))
    assert still_legal == GridRect(11, 47, 6, 3)
    overflow = clamp_rect(GridRect(58, 94, 6, 3))
    assert overflow.column_span == 6
    assert overflow.row_span == 3
    assert overflow.column + overflow.column_span <= SAFETY_COLUMN_MAX
    assert overflow.row + overflow.row_span <= SAFETY_ROW_MAX
    assert overflow.column == SAFETY_COLUMN_MAX - 6
    assert overflow.row == SAFETY_ROW_MAX - 3
    negative = clamp_rect(GridRect(-50, -50, 4, 3))
    assert negative == GridRect(SAFETY_COLUMN_MIN, SAFETY_ROW_MIN, 4, 3)


def test_export_grid_metrics_crop_short_boards_and_keep_screen_floor():
    short = [_placement("a", GridRect(0, 0, 4, 2))]
    screen = screen_grid_metrics(short)
    export = export_grid_metrics(short)
    assert screen.column_width == export.column_width
    assert screen.board_width == 1600
    assert export.board_width == 1600
    assert screen.board_height > export.board_height
    assert screen.board_height > 900


def test_screen_grid_metrics_are_independent_of_window_size():
    placements = [_placement("a", GridRect(0, 0, 4, 3))]
    left = screen_grid_metrics(placements)
    right = screen_grid_metrics(placements)
    export = export_grid_metrics(placements)
    assert left.column_width == right.column_width == export.column_width
    assert left.board_width == BASE_BOARD_SIZE[0]
    assert left.row_height == GRID_ROW_HEIGHT
    occupied = 3 + GRID_SPARE_ROWS
    rows = max(GRID_MIN_VISIBLE_ROWS, occupied)
    assert left.board_height > export.board_height
    assert rows >= GRID_MIN_VISIBLE_ROWS


def test_fit_rect_for_aspect_prefers_matching_span():
    metrics = screen_grid_metrics([])
    origin = GridRect(0, 0, 4, 3)
    wide = fit_rect_for_aspect(origin, (1600, 400), metrics)
    tall = fit_rect_for_aspect(origin, (400, 1600), metrics)
    square = fit_rect_for_aspect(origin, (800, 800), metrics)
    assert wide.column_span > wide.row_span
    assert tall.row_span >= tall.column_span
    assert abs(square.column_span - square.row_span) <= 2
    assert wide.column == origin.column and wide.row == origin.row
    chrome = CARD_FIT_CHROME_HEIGHT
    _, _, ww, wh = rect_to_pixels(wide, metrics)
    _, _, tw, th = rect_to_pixels(tall, metrics)
    assert ww / max(1, wh - chrome) > tw / max(1, th - chrome)


def test_preview_reading_box_height_fills_a_wide_16x9_capture():
    box_w, box_h = preview_reading_box(512, 214, (1600, 900))
    assert box_h == 214
    assert box_w < 512
    assert box_w / box_h == pytest.approx(1600 / 900, rel=0.02)
    assert abs(box_w / box_h - 4 / 3) > 0.2


def test_preview_reading_box_uses_the_capture_aspect_not_4x3():
    box_w, box_h = preview_reading_box(400, 500, (1600, 900))
    assert box_w == 400
    assert box_h < 500
    assert box_w / box_h == pytest.approx(1600 / 900, rel=0.02)


def test_fit_rect_for_aspect_prefers_side_gutter_over_bottom_gap():
    metrics = screen_grid_metrics([])
    chrome = CARD_FIT_CHROME_HEIGHT
    origin = GridRect(0, 0, 4, 5)
    image = (1600, 900)

    def leftover_h(rect):
        _x, _y, width, height = rect_to_pixels(rect, metrics)
        plot_h = max(1, height - chrome)
        scale = min(width / float(image[0]), plot_h / float(image[1]))
        return plot_h - image[1] * scale

    fitted = fit_rect_for_aspect(origin, image, metrics)
    assert leftover_h(fitted) <= leftover_h(origin) + 1
    _x, _y, width, height = rect_to_pixels(fitted, metrics)
    plot_h = max(1, height - chrome)
    scale = min(width / float(image[0]), plot_h / float(image[1]))
    side = width - image[0] * scale
    bottom = plot_h - image[1] * scale
    assert side + 1 >= bottom


def test_fit_rect_for_aspect_grows_short_side_at_most_two_cells():
    """Shrink first; only the short side may grow, and by at most two cells."""
    metrics = screen_grid_metrics([])
    image = (1000, 800)
    origins = (
        GridRect(0, 0, 4, 6),
        GridRect(0, 0, 10, 3),
        GridRect(0, 0, 6, 4),
    )
    results = [fit_rect_for_aspect(origin, image, metrics) for origin in origins]
    spans = [(item.column_span, item.row_span) for item in results]
    assert len(set(spans)) == 3
    for origin, fitted in zip(origins, results):
        assert fitted.column == origin.column and fitted.row == origin.row
        dc = fitted.column_span - origin.column_span
        dr = fitted.row_span - origin.row_span
        assert dc <= FIT_SHORT_SIDE_GROW_MAX
        assert dr <= FIT_SHORT_SIDE_GROW_MAX
        assert dc <= 0 or dr <= 0
        assert fitted.column_span <= GRID_MAX_COLUMN_SPAN
        assert fitted.row_span <= GRID_MAX_ROW_SPAN
        assert fitted.column_span >= GRID_MIN_COLUMN_SPAN
        assert fitted.row_span >= GRID_MIN_ROW_SPAN
        assert (fitted.column_span, fitted.row_span) != (7, 8)


def test_fit_rect_for_aspect_tall_frf_from_standard_adds_rows():
    """A portrait FRF-style preview starting at 4×3 grows rows instead of letterboxing."""
    metrics = screen_grid_metrics([])
    origin = GridRect(0, 0, 4, 3)
    image = (800, 1400)
    fitted = fit_rect_for_aspect(origin, image, metrics)
    assert fitted.column == origin.column and fitted.row == origin.row
    assert fitted.row_span > origin.row_span
    assert fitted.row_span - origin.row_span <= FIT_SHORT_SIDE_GROW_MAX
    assert fitted.column_span <= origin.column_span
    assert fitted.column_span <= GRID_MAX_COLUMN_SPAN
    assert fitted.row_span <= GRID_MAX_ROW_SPAN


def test_fit_chrome_includes_image_padding():
    assert CARD_IMAGE_PADDING == 8
    assert CARD_FIT_CHROME_HEIGHT == (
        CARD_HEADER_HEIGHT + CARD_FOOTER_HEIGHT + 2 * CARD_IMAGE_PADDING
    )
    assert CARD_FIT_CHROME_HEIGHT == MIN_CARD_CHROME_HEIGHT + 16


def test_fit_rect_for_aspect_matches_user_contract():
    """Wide bottleneck keeps columns; tall bottleneck keeps rows (pixel + chrome)."""
    metrics = screen_grid_metrics([])
    chrome = CARD_FIT_CHROME_HEIGHT
    target = GridRect(0, 0, 6, 4)
    _x, _y, width, height = rect_to_pixels(target, metrics)
    image = (width, max(1, height - chrome))
    extra_rows = GridRect(0, 0, target.column_span, target.row_span * 2)
    extra_cols = GridRect(
        0, 0, min(GRID_COLUMNS, target.column_span * 2), target.row_span
    )
    keep_cols = fit_rect_for_aspect(extra_rows, image, metrics)
    keep_rows = fit_rect_for_aspect(extra_cols, image, metrics)
    assert keep_cols.column_span == target.column_span
    assert keep_cols.row_span == target.row_span
    assert keep_rows.row_span == target.row_span
    assert keep_rows.column_span == target.column_span


def test_fit_rect_for_aspect_prefers_the_largest_span_on_a_tie():
    metrics = screen_grid_metrics([])
    square = replace(metrics, column_width=metrics.row_height, gutter=0)
    origin = GridRect(0, 0, 4, 4)
    fitted = fit_rect_for_aspect(origin, (100, 100), square, chrome_height=0)
    assert fitted == origin
    assert (fitted.column_span, fitted.row_span) != (2, 2)


def test_fit_rect_for_aspect_result_is_a_subset():
    metrics = screen_grid_metrics([])
    origin = GridRect(2, 3, 6, 5)
    fitted = fit_rect_for_aspect(origin, (1000, 800), metrics)
    assert fitted.column == origin.column
    assert fitted.row == origin.row
    assert fitted.column_span <= origin.column_span
    assert fitted.row_span <= origin.row_span
    assert fitted.column + fitted.column_span <= origin.column + origin.column_span
    assert fitted.row + fitted.row_span <= origin.row + origin.row_span


def test_place_free_grid_from_unplaced_honors_optional_span():
    board = default_board()
    ref = make_ref("time", "tray")
    board.unplaced.append(ref)
    assert place_free_grid_from_unplaced(board, ref, span=(2, 5)) == []
    item = board.free_grid[0]
    assert item.ref == ref
    assert (item.rect.column_span, item.rect.row_span) == (2, 5)


def test_place_free_grid_from_unplaced_defaults_to_standard_span():
    board = default_board()
    ref = make_ref("frf", "tray")
    board.unplaced.append(ref)
    assert place_free_grid_from_unplaced(board, ref) == []
    item = board.free_grid[0]
    assert (item.rect.column_span, item.rect.row_span) == (4, 3)


def test_insert_preview_uses_resolver_span_not_default(qapp):
    from PyQt5.QtCore import QPoint

    from mf4_analyzer.ui.chart_stack.ultraview.widgets import FreeGridBoard

    board = FreeGridBoard()
    board.set_default_insert_span((4, 3))
    board.set_insert_span_resolver(
        lambda section, view_id: (2, 5) if section == "frf" else None
    )
    board._insert_drag_ref = ("frf", "bode")
    fitted = board._insertion_rect_at(QPoint(80, 80))
    assert fitted is not None
    assert (fitted.column_span, fitted.row_span) == (2, 5)
    board._insert_drag_ref = ("time", "missing-preview")
    fallback = board._insertion_rect_at(QPoint(80, 80))
    assert fallback is not None
    assert (fallback.column_span, fallback.row_span) == (4, 3)


def test_card_preview_pixmap_is_centered_not_stretched(qapp, qtbot):
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QImage

    from mf4_analyzer.ui.chart_stack.ultraview.widgets import CardViewModel, UltraViewCard

    image = QImage(120, 80, QImage.Format_ARGB32)
    image.fill(Qt.blue)
    card = UltraViewCard(
        CardViewModel(slot_id="tl", section="time", view_id="v1", image=image)
    )
    qtbot.addWidget(card)
    card.resize(300, 240)
    card.show()
    qtbot.wait(10)
    card._fit_card_image()
    assert card._image.alignment() == Qt.AlignCenter
    pixmap = card.scale_buffer()
    assert pixmap is not None
    logical_w = pixmap.width() / pixmap.devicePixelRatioF()
    logical_h = pixmap.height() / pixmap.devicePixelRatioF()
    avail = card._preview_fit_size()
    box_w, box_h = preview_reading_box(
        avail.width(), avail.height(), (120, 80)
    )
    assert logical_w == pytest.approx(box_w, abs=1)
    assert logical_h == pytest.approx(box_h, abs=1)
    assert logical_w <= avail.width() + 1
    assert logical_h <= avail.height() + 1
    assert abs(logical_w / logical_h - 120 / 80) < 0.05


def test_snapped_move_rect_matches_candidate_move_and_stays_clamped():
    metrics = grid_metrics((1280, 800), [])
    origin = GridRect(0, 0, 6, 3)
    delta = (10_000, 0)
    snapped = snapped_move_rect(origin, delta, metrics)
    assert snapped == candidate_move(origin, *pixels_to_grid_delta(delta, metrics))
    assert snapped == clamp_rect(snapped)
    assert snapped.column + snapped.column_span <= SAFETY_COLUMN_MAX
    assert snapped.column >= SAFETY_COLUMN_MIN


def test_legal_grid_rect_clamps_origin_plus_span():
    metrics = grid_metrics((1280, 800), [])
    legal = legal_grid_rect((metrics.board_width - 2, 20), metrics, column_span=6, row_span=3)
    assert legal == clamp_rect(legal)
    assert legal.column + legal.column_span <= SAFETY_COLUMN_MAX
    assert legal.column >= SAFETY_COLUMN_MIN


def test_gesture_move_plans_overlap_as_legal_same_size_translate():
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
    assert session.legal is True
    assert session.plan is not None and session.plan.accepted
    displaced = {item.ref: item.after for item in session.plan.displaced_before_after}
    assert displaced[make_ref("time", "b")].column_span == 4
    assert displaced[make_ref("time", "b")].row_span == 3
    cancelled = gesture.cancel()
    assert cancelled is session
    assert gesture.is_armed() is False


def test_gesture_move_across_base_frame_is_legal():
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
    assert session.candidate == GridRect(-8, 0, 4, 3)
    assert session.candidate == clamp_rect(session.candidate)
    assert session.legal is True


def test_gesture_move_keeps_out_of_bounds_candidate_illegal():
    metrics = grid_metrics((1280, 800), [])
    origin = GridRect(0, 0, 4, 3)
    placements = [_placement("a", origin)]
    gesture = FreeGridGesture()
    gesture.press(make_ref("time", "a"), origin, (10, 10), (10, 10))
    unit = metrics.column_width + metrics.gutter
    past_safety = abs(SAFETY_COLUMN_MIN) + origin.column_span + 8
    session = gesture.update(
        (10 - unit * past_safety, 10), metrics, placements, start_drag_distance=20
    )
    assert session is not None and session.active
    assert session.candidate == translated_move_rect(
        origin, (-unit * past_safety, 0), metrics
    )
    assert session.candidate != clamp_rect(session.candidate)
    assert session.legal is False


def test_group_move_left_by_three_stays_inside_safety():
    metrics = grid_metrics((1280, 800), [])
    first = GridRect(0, 0, 4, 3)
    second = GridRect(4, 0, 4, 3)
    placements = [_placement("a", first), _placement("b", second)]
    origins = {make_ref("time", "a"): first, make_ref("time", "b"): second}
    gesture = FreeGridGesture()
    gesture.press(
        make_ref("time", "a"), first, (10, 10), (10, 10), group_origins=origins
    )
    unit = metrics.column_width + metrics.gutter
    session = gesture.update(
        (10 - unit * 3, 10), metrics, placements, start_drag_distance=20
    )
    assert session is not None and session.active
    assert session.legal is True
    assert session.plan is not None and session.plan.accepted


def test_group_move_out_of_bounds_ghost_stays_a_rigid_translation():
    """An out-of-safety group drag commits nothing, so its ghost must keep showing
    the rigid translation in the reject state.  Clamping each member on its own
    drew a squashed, self-overlapping shape that was neither the pointer position
    nor the outcome (review 2026-08-15 §4.3 群组越界 ghost)."""
    metrics = grid_metrics((1280, 800), [])
    first = GridRect(0, 0, 4, 3)
    second = GridRect(4, 0, 4, 3)
    placements = [_placement("a", first), _placement("b", second)]
    origins = {make_ref("time", "a"): first, make_ref("time", "b"): second}
    gesture = FreeGridGesture()
    gesture.press(
        make_ref("time", "a"), first, (10, 10), (10, 10), group_origins=origins
    )
    unit = metrics.column_width + metrics.gutter
    past_safety = abs(SAFETY_COLUMN_MIN) + 8
    session = gesture.update(
        (10 - unit * past_safety, 10), metrics, placements, start_drag_distance=20
    )
    assert session is not None and session.active
    assert session.legal is False and session.plan is None

    ghosts = session.group_ghost_pixels(metrics, (10 - unit * past_safety, 10))
    highlights = session.group_highlight_pixels(metrics)
    assert len(ghosts) == len(highlights) == 2
    assert ghosts == highlights
    # Rigid: the ghosts keep the selection's own spacing and every span.
    assert ghosts[1][0] - ghosts[0][0] == rect_to_pixels(second, metrics)[0] - rect_to_pixels(
        first, metrics
    )[0]
    for ghost, origin in zip(ghosts, (first, second)):
        expected = rect_to_pixels(origin, metrics)
        assert (ghost[2], ghost[3]) == (expected[2], expected[3])
    assert ghosts[0][0] < 0
    assert ghosts[0][0] + ghosts[0][2] <= ghosts[1][0]


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
    _across_base, legal_right = group_translate_rects(selected, (), 1, 0)
    assert legal_right is True
    _overflow, legal_past_safety = group_translate_rects(
        selected, (), SAFETY_COLUMN_MAX, 0
    )
    assert legal_past_safety is False
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


def test_overlap_avoidance_slides_blocker_past_the_old_twelve_column_wall():
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
    assert by_ref[second.ref] == GridRect(12, 0, 6, 3)


def test_overlap_avoidance_slides_blocker_down_when_safety_right_is_blocked():
    first = _placement("a", GridRect(SAFETY_COLUMN_MAX - 12, 0, 6, 3))
    second = _placement("b", GridRect(SAFETY_COLUMN_MAX - 6, 0, 6, 3))
    updates, ok = plan_overlap_avoidance(
        {first.ref: GridRect(SAFETY_COLUMN_MAX - 6, 0, 6, 3)},
        [first, second],
        preferred=(1, 0),
    )
    assert ok is True
    by_ref = dict(updates)
    assert by_ref[first.ref] == GridRect(SAFETY_COLUMN_MAX - 6, 0, 6, 3)
    assert by_ref[second.ref] == GridRect(SAFETY_COLUMN_MAX - 6, 3, 6, 3)


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


def test_overlap_avoidance_slides_past_the_old_twelve_column_wall():
    cards = [
        _placement(f"c{index}", GridRect(0, index * 8, 12, 8))
        for index in range(6)
    ]
    updates, ok = plan_overlap_avoidance(
        {cards[0].ref: GridRect(0, 1, 12, 8)},
        cards,
        preferred=(0, 1),
    )
    assert ok is True
    by_ref = dict(updates)
    assert by_ref[cards[0].ref] == GridRect(0, 1, 12, 8)
    blocker = by_ref[cards[1].ref]
    assert (blocker.column_span, blocker.row_span) == (12, 8)
    assert blocker.column + blocker.column_span > GRID_COLUMNS or blocker.row != 8


def test_signed_origin_inside_safety_is_accepted_without_rebasing():
    card = _placement("a", GridRect(2, 0, 4, 3))
    plan = plan_layout(
        [card], card.ref, GridRect(-2, 0, 4, 3), LAYOUT_MOVE, preferred=(-1, 0)
    )
    assert plan.accepted is True
    assert dict(plan.committed_updates())[card.ref] == GridRect(-2, 0, 4, 3)


def test_crossing_base_frame_is_legal_and_does_not_shrink_neighbors():
    left_top = _placement("a", GridRect(0, 0, 4, 3))
    left_bottom = _placement("b", GridRect(0, 3, 4, 3))
    mover = _placement("c", GridRect(4, 0, 8, 6))
    plan = plan_layout(
        [left_top, left_bottom, mover],
        mover.ref,
        GridRect(5, 0, 8, 6),
        LAYOUT_MOVE,
        preferred=(1, 0),
    )
    assert plan.accepted is True
    assert dict(plan.committed_updates())[mover.ref] == GridRect(5, 0, 8, 6)
    assert left_top.rect == GridRect(0, 0, 4, 3)
    assert left_bottom.rect == GridRect(0, 3, 4, 3)


def test_safety_edge_drop_rejects_wall_instead_of_shrinking_neighbors():
    left_top = _placement("a", GridRect(SAFETY_COLUMN_MIN, 0, 4, 3))
    left_bottom = _placement("b", GridRect(SAFETY_COLUMN_MIN, 3, 4, 3))
    mover = _placement("c", GridRect(SAFETY_COLUMN_MIN + 4, 0, 8, 6))
    plan = plan_layout(
        [left_top, left_bottom, mover],
        mover.ref,
        GridRect(SAFETY_COLUMN_MIN - 1, 0, 8, 6),
        LAYOUT_MOVE,
        preferred=(-1, 0),
    )
    assert plan.accepted is False
    assert plan.reason is LayoutRejectReason.OUT_OF_BOUNDS
    assert plan.committed_updates() == ()
    assert left_top.rect == GridRect(SAFETY_COLUMN_MIN, 0, 4, 3)
    assert mover.rect == GridRect(SAFETY_COLUMN_MIN + 4, 0, 8, 6)


def test_safety_edge_fails_when_left_neighbors_are_already_minimum():
    left_top = _placement("a", GridRect(SAFETY_COLUMN_MIN, 0, 2, 3))
    left_bottom = _placement("b", GridRect(SAFETY_COLUMN_MIN, 3, 2, 3))
    mover = _placement("c", GridRect(SAFETY_COLUMN_MIN + 2, 0, 10, 6))
    plan = plan_layout(
        [left_top, left_bottom, mover],
        mover.ref,
        GridRect(SAFETY_COLUMN_MIN - 1, 0, 10, 6),
        LAYOUT_MOVE,
        preferred=(-1, 0),
    )
    assert plan.accepted is False
    assert plan.reason is LayoutRejectReason.OUT_OF_BOUNDS
    assert plan.committed_updates() == ()


def test_plan_layout_move_keeps_every_span():
    first = _placement("a", GridRect(0, 0, 6, 3))
    second = _placement("b", GridRect(6, 0, 6, 3))
    plan = plan_layout(
        [first, second],
        first.ref,
        GridRect(6, 0, 6, 3),
        LAYOUT_MOVE,
        preferred=(1, 0),
        layout_revision=7,
    )
    assert plan.accepted is True
    assert plan.based_on_layout_revision == 7
    assert plan.mover_before == first.rect
    assert plan.mover_after == GridRect(6, 0, 6, 3)
    assert plan.mover_after.column_span == 6
    assert plan.mover_after.row_span == 3
    blocker = plan.displaced_before_after[0]
    assert blocker.ref == second.ref
    assert blocker.before == second.rect
    assert blocker.after.column_span == 6
    assert blocker.after.row_span == 3
    assert blocker.after == GridRect(12, 0, 6, 3)


def test_plan_layout_resize_only_changes_mover_span():
    first = _placement("a", GridRect(0, 0, 6, 3))
    second = _placement("b", GridRect(6, 0, 6, 3))
    plan = plan_layout(
        [first, second],
        first.ref,
        GridRect(0, 0, 8, 3),
        LAYOUT_RESIZE,
        preferred=(1, 0),
    )
    assert plan.accepted is True
    assert plan.mover_after == GridRect(0, 0, 8, 3)
    blocker = plan.displaced_before_after[0]
    assert blocker.after.column_span == 6
    assert blocker.after.row_span == 3
    assert blocker.after.column != blocker.before.column or blocker.after.row != blocker.before.row


def test_plan_layout_edge_without_hole_rejects_without_grow_or_shrink():
    left_top = _placement("a", GridRect(SAFETY_COLUMN_MIN, 0, 4, 3))
    left_bottom = _placement("b", GridRect(SAFETY_COLUMN_MIN, 3, 4, 3))
    mover = _placement("c", GridRect(SAFETY_COLUMN_MIN + 4, 0, 8, 6))
    plan = plan_layout(
        [left_top, left_bottom, mover],
        mover.ref,
        GridRect(SAFETY_COLUMN_MIN - 1, 0, 8, 6),
        LAYOUT_MOVE,
        preferred=(-1, 0),
    )
    assert plan.accepted is False
    assert plan.reason is LayoutRejectReason.OUT_OF_BOUNDS
    assert plan.committed_updates() == ()


def test_plan_layout_is_deterministic_for_displacement_order():
    first = _placement("a", GridRect(0, 0, 6, 3))
    second = _placement("b", GridRect(6, 0, 6, 3))
    kwargs = dict(
        placements=[first, second],
        mover_ref=first.ref,
        target=GridRect(6, 0, 6, 3),
        operation=LAYOUT_MOVE,
        preferred=(1, 0),
        layout_revision=3,
    )
    left = plan_layout(**kwargs)
    right = plan_layout(**kwargs)
    assert left == right
    assert [item.ref for item in left.displaced_before_after] == [
        item.ref for item in right.displaced_before_after
    ]


def _dense_2x2_board(count: int) -> list[FreeGridPlacement]:
    """``count`` 2×2 cards packed six-per-row from the top-left corner."""
    per_row = GRID_COLUMNS // 2
    return [
        _placement(
            f"c{index}",
            GridRect((index % per_row) * 2, (index // per_row) * 2, 2, 2),
        )
        for index in range(count)
    ]


def test_plan_layout_24_card_search_is_capped():
    cards = _dense_2x2_board(24)
    assert len(cards) == 24
    plan = plan_layout(
        cards,
        cards[0].ref,
        GridRect(2, 0, 2, 2),
        LAYOUT_MOVE,
        preferred=(1, 0),
        search_cap=PLANNER_SEARCH_CAP,
    )
    assert plan.accepted, "a one-cell shove on a 24-card board has a legal layout"
    assert plan.search_visits <= PLANNER_SEARCH_CAP * len(cards)
    edge = _placement("edge", GridRect(SAFETY_COLUMN_MAX - 4, 0, 4, 3))
    rejected = plan_layout(
        [edge],
        edge.ref,
        GridRect(SAFETY_COLUMN_MAX - 3, 0, 4, 3),
        LAYOUT_MOVE,
        preferred=(1, 0),
        search_cap=PLANNER_SEARCH_CAP,
    )
    assert rejected.accepted is False
    assert rejected.reason is LayoutRejectReason.OUT_OF_BOUNDS
    assert rejected.search_visits <= PLANNER_SEARCH_CAP


@pytest.mark.parametrize("count", (48, 60))
def test_plan_layout_dense_board_big_resize_is_not_rejected_by_the_budget(count):
    """A dense board must not report "no legal layout" because an earlier blocker
    drained a plan-wide pool.  Review 2026-08-15 P1-4: 60 × 2×2 cards + a
    2×2 → 12×8 resize needs 587 probes and was rejected at 512/512, while the
    same input with cap=100000 accepted."""
    cards = _dense_2x2_board(count)
    target = GridRect(0, 0, 12, 8)
    # No explicit ``preferred``: take the same axis the drag path derives.
    plan = plan_layout(
        cards, cards[0].ref, target, LAYOUT_RESIZE, search_cap=PLANNER_SEARCH_CAP
    )
    generous = plan_layout(
        cards, cards[0].ref, target, LAYOUT_RESIZE, search_cap=100_000
    )
    assert generous.accepted, "fixture must be a solvable board"
    assert plan.accepted, (
        f"{count}-card board rejected with {plan.reason} after "
        f"{plan.search_visits} probes, but a legal layout exists "
        f"({generous.search_visits} probes)"
    )
    assert plan.reason is None
    assert plan == generous
    # Still bounded: the allowance is per relocated card, not unlimited.
    assert plan.search_visits <= PLANNER_SEARCH_CAP * len(cards)
    # Size preservation still holds for every displaced neighbour.
    assert plan.mover_after == target
    for item in plan.displaced_before_after:
        assert (item.after.column_span, item.after.row_span) == (
            item.before.column_span,
            item.before.row_span,
        )


def test_search_cap_reject_is_distinct_from_no_legal_layout():
    """The two rejects must stay separable so the UI can stop saying "it does not
    fit" when the planner merely gave up (review 2026-08-15 P1-4)."""
    cards = _dense_2x2_board(60)
    starved = plan_layout(
        cards,
        cards[0].ref,
        GridRect(0, 0, 12, 8),
        LAYOUT_RESIZE,
        preferred=(0, 1),
        search_cap=1,
    )
    assert starved.accepted is False
    assert starved.reason is LayoutRejectReason.SEARCH_CAP
    first = _placement("a", GridRect(0, 0, 4, 3))
    second = _placement("b", GridRect(4, 0, 4, 3))
    boxed = plan_layout(
        [first, second],
        first.ref,
        GridRect(0, 0, 4, 3),
        LAYOUT_MOVE,
        incoming={
            first.ref: GridRect(0, 0, 4, 3),
            second.ref: GridRect(0, 0, 4, 3),
        },
        search_cap=PLANNER_SEARCH_CAP,
    )
    assert boxed.accepted is False
    assert boxed.reason is LayoutRejectReason.NO_LEGAL_LAYOUT


def test_neighbor_shrink_packs_blockers_into_remaining_columns():
    right_top = _placement("a", GridRect(SAFETY_COLUMN_MAX - 4, 0, 4, 3))
    right_bottom = _placement("b", GridRect(SAFETY_COLUMN_MAX - 4, 3, 4, 3))
    mover = _placement("c", GridRect(SAFETY_COLUMN_MAX - 12, 0, 8, 6))
    updates, ok = plan_neighbor_shrink(
        {mover.ref: GridRect(SAFETY_COLUMN_MAX - 12, 0, 10, 6)},
        [right_top, right_bottom, mover],
    )
    assert ok is True
    by_ref = dict(updates)
    assert by_ref[mover.ref] == GridRect(SAFETY_COLUMN_MAX - 12, 0, 10, 6)
    assert by_ref[right_top.ref] == GridRect(SAFETY_COLUMN_MAX - 2, 0, 2, 3)
    assert by_ref[right_bottom.ref] == GridRect(SAFETY_COLUMN_MAX - 2, 3, 2, 3)


def test_neighbor_shrink_fails_below_minimum_span():
    fillers = [
        _placement(
            f"m{index}",
            GridRect(SAFETY_COLUMN_MIN + index * 12, 0, 12, 3),
        )
        for index in range(8)
    ]
    last = _placement("m8", GridRect(SAFETY_COLUMN_MIN + 96, 0, 10, 3))
    blocker = _placement("b", GridRect(SAFETY_COLUMN_MAX - 2, 0, 2, 3))
    incoming = {item.ref: item.rect for item in fillers}
    incoming[last.ref] = GridRect(SAFETY_COLUMN_MIN + 96, 0, 11, 3)
    updates, ok = plan_neighbor_shrink(
        incoming,
        [*fillers, last, blocker],
    )
    assert ok is False
    assert updates == ()


def test_rect_to_pixels_supports_negative_cells_without_rebasing():
    metrics = screen_grid_metrics([])
    origin = GridRect(0, 0, 4, 3)
    negative = GridRect(-4, -3, 4, 3)
    x0, y0, w0, h0 = rect_to_pixels(origin, metrics)
    xn, yn, wn, hn = rect_to_pixels(negative, metrics)
    assert (wn, hn) == (w0, h0)
    unit_x = metrics.column_width + metrics.gutter
    unit_y = metrics.row_height + metrics.gutter
    assert xn == x0 - 4 * unit_x
    assert yn == y0 - 3 * unit_y
    shifted = rect_to_pixels(negative, metrics, origin_offset=(-4, -3))
    assert shifted == (x0, y0, w0, h0)
    assert negative == GridRect(-4, -3, 4, 3)


def test_organize_compresses_signed_rows_toward_the_base_origin():
    placements = [
        _placement("above", GridRect(-6, -5, 4, 2)),
        _placement("below", GridRect(2, 4, 3, 3)),
    ]
    organized = organized_placements(placements)
    assert organized[0].rect == GridRect(-6, -2, 4, 2)
    assert organized[1].rect == GridRect(2, 0, 3, 3)
    assert organized_placements(organized) == organized


def test_planner_search_stays_capped_for_signed_safety_board():
    cards = _dense_2x2_board(24)
    plan = plan_layout(
        cards,
        cards[0].ref,
        GridRect(-4, 0, 2, 2),
        LAYOUT_MOVE,
        preferred=(-1, 0),
        search_cap=PLANNER_SEARCH_CAP,
    )
    assert plan.accepted is True
    assert plan.search_visits <= PLANNER_SEARCH_CAP * len(cards)
    assert plan.mover_after == GridRect(-4, 0, 2, 2)


def test_plan_auto_arrange_is_idempotent_and_keeps_spans():
    scattered = [
        _placement("b", GridRect(8, 10, 4, 3)),
        _placement("a", GridRect(0, 20, 6, 4)),
        _placement("c", GridRect(3, 2, 3, 2)),
    ]
    original = [(item.ref, item.rect) for item in scattered]
    first = plan_auto_arrange(scattered, layout_revision=7)
    second = plan_auto_arrange(scattered, layout_revision=7)
    assert first == second
    assert first.accepted is True
    assert first.operation == LAYOUT_ARRANGE
    assert first.mover_ref is None
    assert first.based_on_layout_revision == 7
    assert [(item.ref, item.rect) for item in scattered] == original
    by_ref = {item.ref: item.rect for item in scattered}
    updates = dict(first.committed_updates())
    assert set(updates) <= set(by_ref)
    packed = []
    for item in scattered:
        after = updates.get(item.ref, item.rect)
        assert (after.column_span, after.row_span) == (
            item.rect.column_span,
            item.rect.row_span,
        )
        assert clamp_rect(after) == after
        packed.append(after)
    for index, left in enumerate(packed):
        for right in packed[index + 1 :]:
            assert not rects_overlap(left, right)
    ordered = sorted(
        scattered,
        key=lambda item: (item.rect.row, item.rect.column, item.ref.view_id),
    )
    first_after = updates.get(ordered[0].ref, ordered[0].rect)
    assert first_after.column == 0
    assert first_after.row == 0


def test_plan_auto_arrange_compacts_unlike_empty_row_organize():
    placements = [
        _placement("left", GridRect(8, 0, 4, 3)),
        _placement("right", GridRect(8, 10, 4, 3)),
    ]
    organized = organized_placements(placements)
    assert organized[0].rect.column == 8
    plan = plan_auto_arrange(placements)
    assert plan.accepted is True
    updates = dict(plan.committed_updates())
    assert updates[placements[0].ref] == GridRect(0, 0, 4, 3)
    assert updates[placements[1].ref] == GridRect(4, 0, 4, 3)
    again = plan_auto_arrange(
        [
            FreeGridPlacement(item.ref, updates[item.ref])
            for item in placements
        ]
    )
    assert again.accepted is True
    assert again.committed_updates() == ()


def test_plan_auto_arrange_rejects_illegal_or_unsolvable_input():
    too_few = plan_auto_arrange([_placement("only", GridRect(0, 0, 4, 3))])
    assert too_few.accepted is False
    assert too_few.reason is LayoutRejectReason.INVALID_INPUT
    assert too_few.committed_updates() == ()

    overlap = plan_auto_arrange(
        [
            _placement("a", GridRect(0, 0, 4, 3)),
            _placement("b", GridRect(2, 0, 4, 3)),
        ]
    )
    assert overlap.accepted is False
    assert overlap.reason is LayoutRejectReason.INVALID_INPUT

    duplicate = plan_auto_arrange(
        [
            FreeGridPlacement(make_ref("time", "same"), GridRect(0, 0, 4, 3)),
            FreeGridPlacement(make_ref("time", "same"), GridRect(4, 0, 4, 3)),
        ]
    )
    assert duplicate.accepted is False

    illegal = plan_auto_arrange(
        [
            _placement("thin", GridRect(0, 0, 1, 3)),
            _placement("ok", GridRect(4, 0, 4, 3)),
        ]
    )
    assert illegal.accepted is False
    assert illegal.reason is LayoutRejectReason.INVALID_INPUT

    # 12×8 cards fill rows 0–95; a 13th legal card cannot fit.
    unsolvable = [
        _placement(f"huge-{index}", GridRect(0, index * 8, 12, 8))
        for index in range(12)
    ]
    unsolvable.append(_placement("overflow", GridRect(0, -8, 12, 8)))
    rejected = plan_auto_arrange(unsolvable)
    assert rejected.accepted is False
    assert rejected.reason is LayoutRejectReason.NO_LEGAL_LAYOUT
    assert rejected.committed_updates() == ()
    assert unsolvable[-1].rect == GridRect(0, -8, 12, 8)
