"""Compact native WWT layout: topology, width ranks, and overlap relocation."""
from __future__ import annotations

import pytest

from mf4_analyzer.ultraview_core.grid_geometry import (
    BOARD_PADDING,
    GRID_MIN_COLUMN_WIDTH,
    GRID_ROW_HEIGHT,
    SLOT_GUTTER,
    GridMetrics,
    rect_to_pixels,
)
from mf4_analyzer.ultraview_core.model import (
    GRID_COLUMNS,
    GRID_RESOLUTION,
    MAX_BOARD_MEMBERSHIP,
    MAX_PLACED_CARDS,
    FreeGridPlacement,
    GridRect,
    UltraViewRef,
    default_board,
)
from mf4_analyzer.ultraview_core.native_layout import (
    NativeLayoutPlan,
    NativeLayoutRect,
    plan_native_layout,
)
from mf4_analyzer.ultraview_core.board_ops import (
    apply_native_layout,
    membership_set,
)


UCAN_MM = (
    NativeLayoutRect(25.0, 65.0, 100.0, 60.0),
    NativeLayoutRect(41.0, 138.2, 90.0, 60.0),
    NativeLayoutRect(147.5, 62.5, 50.0, 60.0),
    NativeLayoutRect(215.5, 62.5, 50.0, 60.0),
    NativeLayoutRect(147.5, 138.0, 50.0, 60.0),
    NativeLayoutRect(214.5, 138.0, 50.0, 60.0),
    NativeLayoutRect(214.5, 138.0, 50.0, 60.0),
)


def _grid_overlap(left: GridRect, right: GridRect) -> bool:
    return not (
        left.column + left.column_span <= right.column
        or right.column + right.column_span <= left.column
        or left.row + left.row_span <= right.row
        or right.row + right.row_span <= left.row
    )


def _assert_no_overlaps(placed) -> None:
    rects = [grid for _ref, grid in placed]
    for index, left in enumerate(rects):
        for right in rects[index + 1 :]:
            assert not _grid_overlap(left, right), (left, right)


def _row_bands(rects: list[GridRect]):
    ordered = sorted(rects, key=lambda rect: (rect.row, rect.column))
    bands: list[list[GridRect]] = []
    bounds: list[list[int]] = []
    for rect in ordered:
        top = rect.row
        bottom = rect.row + rect.row_span
        matched = None
        for index, band in enumerate(bounds):
            if top < band[1] and bottom > band[0]:
                matched = index
                break
        if matched is None:
            bands.append([rect])
            bounds.append([top, bottom])
            continue
        bands[matched].append(rect)
        bounds[matched][0] = min(bounds[matched][0], top)
        bounds[matched][1] = max(bounds[matched][1], bottom)
    order = sorted(range(len(bands)), key=lambda index: bounds[index][0])
    return [bands[index] for index in order], [bounds[index] for index in order]


def _assert_compact_packing(placed) -> None:
    rects = [grid for _ref, grid in placed]
    if not rects:
        return
    _assert_no_overlaps(placed)
    bands, bounds = _row_bands(rects)
    for band in bands:
        ordered = sorted(band, key=lambda rect: rect.column)
        for left, right in zip(ordered, ordered[1:]):
            assert right.column == left.column + left.column_span, (left, right)
    for previous, nxt in zip(bounds, bounds[1:]):
        assert nxt[0] == previous[1], (previous, nxt)


def test_ucan_plan_places_all_seven_compact_and_relocates_overlap():
    refs = tuple(UltraViewRef("time", f"v{i}") for i in range(7))
    plan = plan_native_layout(list(zip(refs, UCAN_MM)))
    assert len(plan.placed) == 7
    assert plan.unplaced == ()
    assert tuple(ref for ref, _grid in plan.placed) == refs
    assert refs[6] in plan.relocated
    assert refs[6] not in plan.unplaced
    assert any("exact_overlap_relocated: 7 -> 6" in warning for warning in plan.warnings)
    assert not any(warning.startswith("exact_overlap:") for warning in plan.warnings)
    _assert_compact_packing(plan.placed)
    _assert_placed_aspects(list(zip(refs, UCAN_MM)), plan, _canonical_metrics())
    by_ref = dict(plan.placed)
    wide = (by_ref[refs[0]].column_span, by_ref[refs[1]].column_span)
    narrow = [
        by_ref[refs[index]].column_span
        for index in (2, 3, 4, 5, 6)
    ]
    narrow_span = min(narrow)
    for span in wide:
        assert abs(span - 2 * narrow_span) <= 1
    assert by_ref[refs[0]].column < by_ref[refs[2]].column < by_ref[refs[3]].column
    assert by_ref[refs[1]].column < by_ref[refs[4]].column < by_ref[refs[5]].column
    assert by_ref[refs[6]] != by_ref[refs[5]]


def test_apply_native_layout_is_one_board_mutation():
    refs = tuple(UltraViewRef("time", f"v{i}") for i in range(7))
    plan = plan_native_layout(list(zip(refs, UCAN_MM)))
    board = default_board()
    warnings = apply_native_layout(board, plan)
    assert len(board.free_grid) == 7
    assert board.unplaced == []
    assert [item.ref for item in board.free_grid] == list(refs)
    assert "exact_overlap_relocated: 7 -> 6" in warnings
    _assert_compact_packing([(item.ref, item.rect) for item in board.free_grid])


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
        placed_ids, _warnings = coordinator.add_time_views_from_native_layout(
            (
                ("view-left", NativeLayoutRect(0.0, 60.0, 100.0, 60.0)),
                ("view-right", NativeLayoutRect(120.0, 60.0, 100.0, 60.0)),
            )
        )

        assert coordinator.workspace is controller.workspace
        assert coordinator.board is board
        assert placed_ids == ("view-left", "view-right")
        assert [(item.ref, item.rect) for item in board.free_grid] == [
            (UltraViewRef("time", "view-left"), GridRect(0, 0, 12, 8)),
            (UltraViewRef("time", "view-right"), GridRect(12, 0, 12, 8)),
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
        placed_ids, _warnings = controller.apply_native_layout_plan(plan)

        assert placed_ids == ("view-front", "view-overlap")
        assert {item.ref for item in board.free_grid} == {refs[0], refs[1]}
        assert board.unplaced == []
        _assert_compact_packing([(item.ref, item.rect) for item in board.free_grid])
        assert any("exact_overlap_relocated" in item for item in _warnings)
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


def test_plan_invalid_rect_goes_to_unplaced_with_warning():
    valid = UltraViewRef("time", "valid")
    zero = UltraViewRef("time", "zero-width")
    nan_ref = UltraViewRef("time", "nan-width")
    plan = plan_native_layout(
        (
            (valid, NativeLayoutRect(0.0, 60.0, 100.0, 60.0)),
            (zero, NativeLayoutRect(20.0, 40.0, 0.0, 50.0)),
            (nan_ref, NativeLayoutRect(0.0, 60.0, float("nan"), 60.0)),
        )
    )
    placed_refs = {ref for ref, _rect in plan.placed}
    assert valid in placed_refs
    assert zero in plan.unplaced
    assert nan_ref in plan.unplaced
    assert zero not in placed_refs
    assert nan_ref not in placed_refs
    assert any("invalid_rect" in warning for warning in plan.warnings)


def _canonical_metrics() -> GridMetrics:
    physical_columns = GRID_COLUMNS // GRID_RESOLUTION
    return GridMetrics(
        board_width=(
            2 * BOARD_PADDING
            + physical_columns * GRID_MIN_COLUMN_WIDTH
            + (physical_columns - 1) * SLOT_GUTTER
        ),
        board_height=2 * BOARD_PADDING + GRID_ROW_HEIGHT,
        column_width=GRID_MIN_COLUMN_WIDTH,
        row_height=GRID_ROW_HEIGHT,
        gutter=SLOT_GUTTER,
        padding=BOARD_PADDING,
        resolution=GRID_RESOLUTION,
    )


def _nonsquare_metrics() -> GridMetrics:
    return GridMetrics(
        board_width=2000,
        board_height=1000,
        column_width=120,
        row_height=60,
        gutter=SLOT_GUTTER,
        padding=BOARD_PADDING,
        resolution=GRID_RESOLUTION,
    )


def _assert_aspect_within_one_cell(
    pixel_w: int,
    pixel_h: int,
    mm_w: float,
    mm_h: float,
    pitch_x: float,
    pitch_y: float,
) -> None:
    """Rendered pixel aspect may differ from mm aspect by at most one cell.

    Changing width by ``pitch_x`` or height by ``pitch_y`` is the quantization
    envelope: the millimetre aspect must stay inside that range.
    """
    rendered = pixel_w / pixel_h
    target = mm_w / mm_h
    neighbors = [rendered]
    if pixel_w + pitch_x > 0:
        neighbors.append((pixel_w + pitch_x) / pixel_h)
    if pixel_w - pitch_x > 0:
        neighbors.append((pixel_w - pitch_x) / pixel_h)
    if pixel_h + pitch_y > 0:
        neighbors.append(pixel_w / (pixel_h + pitch_y))
    if pixel_h - pitch_y > 0:
        neighbors.append(pixel_w / (pixel_h - pitch_y))
    lo, hi = min(neighbors), max(neighbors)
    assert lo <= target <= hi, (
        f"rendered aspect {rendered:.6f} vs mm aspect {target:.6f} "
        f"outside one-cell envelope [{lo:.6f}, {hi:.6f}] "
        f"(pixel={pixel_w}x{pixel_h} mm={mm_w}x{mm_h} "
        f"pitch=({pitch_x}, {pitch_y}))"
    )


def _assert_placed_aspects(
    items: list[tuple[UltraViewRef, NativeLayoutRect]],
    plan: NativeLayoutPlan,
    metrics: GridMetrics,
) -> None:
    pitch_x, pitch_y = metrics.exact_pitch()
    mm_by_ref = {ref: rect for ref, rect in items}
    for ref, grid in plan.placed:
        _x, _y, pixel_w, pixel_h = rect_to_pixels(grid, metrics)
        mm = mm_by_ref[ref]
        _assert_aspect_within_one_cell(
            pixel_w, pixel_h, mm.width, mm.height, pitch_x, pitch_y
        )


def test_plan_metrics_are_keyword_only():
    items = ((UltraViewRef("time", "v"), NativeLayoutRect(0.0, 60.0, 100.0, 60.0)),)
    with pytest.raises(TypeError):
        plan_native_layout(items, _canonical_metrics())


def test_plan_default_metrics_match_canonical_not_stretched_column():
    items = (
        (UltraViewRef("time", "left"), NativeLayoutRect(0.0, 60.0, 100.0, 60.0)),
        (UltraViewRef("time", "right"), NativeLayoutRect(120.0, 60.0, 100.0, 60.0)),
    )
    canonical = _canonical_metrics()
    stretched = GridMetrics(
        board_width=4096,
        board_height=2048,
        column_width=200,
        row_height=GRID_ROW_HEIGHT,
        gutter=SLOT_GUTTER,
        padding=BOARD_PADDING,
        resolution=GRID_RESOLUTION,
    )
    assert stretched.column_width > GRID_MIN_COLUMN_WIDTH
    default_plan = plan_native_layout(items)
    assert default_plan.placed == plan_native_layout(items, metrics=canonical).placed
    stretched_plan = plan_native_layout(items, metrics=stretched)
    assert [rect.column_span for _, rect in default_plan.placed] == [
        rect.column_span for _, rect in stretched_plan.placed
    ]
    assert [rect.row_span for _, rect in default_plan.placed] != [
        rect.row_span for _, rect in stretched_plan.placed
    ]


def test_plan_wide_rect_aspect_within_one_micro_cell():
    metrics = _canonical_metrics()
    ref = UltraViewRef("time", "wide")
    items = [(ref, NativeLayoutRect(0.0, 50.0, 180.0, 50.0))]
    plan = plan_native_layout(items, metrics=metrics)
    assert tuple(item[0] for item in plan.placed) == (ref,)
    _assert_placed_aspects(items, plan, metrics)


def test_plan_tall_narrow_rect_aspect_within_one_micro_cell():
    metrics = _canonical_metrics()
    tall = UltraViewRef("time", "tall")
    companion = UltraViewRef("time", "companion")
    items = [
        (tall, NativeLayoutRect(0.0, 120.0, 40.0, 120.0)),
        (companion, NativeLayoutRect(50.0, 80.0, 160.0, 80.0)),
    ]
    plan = plan_native_layout(items, metrics=metrics)
    assert tuple(item[0] for item in plan.placed) == (tall, companion)
    tall_grid = dict(plan.placed)[tall]
    assert tall_grid.column_span < tall_grid.row_span
    _assert_placed_aspects(items, plan, metrics)


def test_plan_stacked_top_bottom_preserves_source_order_and_aspect():
    metrics = _canonical_metrics()
    first = UltraViewRef("time", "lower-on-board")
    second = UltraViewRef("time", "upper-on-board")
    items = [
        (first, NativeLayoutRect(0.0, 150.0, 100.0, 60.0)),
        (second, NativeLayoutRect(0.0, 70.0, 100.0, 60.0)),
    ]
    plan = plan_native_layout(items, metrics=metrics)
    assert tuple(item[0] for item in plan.placed) == (first, second)
    assert plan.placed[0][1].row > plan.placed[1][1].row
    assert (
        plan.placed[0][1].row
        == plan.placed[1][1].row + plan.placed[1][1].row_span
    )
    _assert_placed_aspects(items, plan, metrics)
    _assert_compact_packing(plan.placed)


def test_plan_side_by_side_preserves_source_order_and_aspect():
    metrics = _canonical_metrics()
    left = UltraViewRef("time", "left")
    right = UltraViewRef("time", "right")
    items = [
        (left, NativeLayoutRect(0.0, 60.0, 100.0, 60.0)),
        (right, NativeLayoutRect(120.0, 60.0, 100.0, 60.0)),
    ]
    plan = plan_native_layout(items, metrics=metrics)
    assert tuple(item[0] for item in plan.placed) == (left, right)
    assert plan.placed[0][1].column < plan.placed[1][1].column
    assert (
        plan.placed[1][1].column
        == plan.placed[0][1].column + plan.placed[0][1].column_span
    )
    _assert_placed_aspects(items, plan, metrics)
    _assert_compact_packing(plan.placed)


def test_plan_exact_overlap_relocates_and_keeps_source_order():
    metrics = _canonical_metrics()
    front = UltraViewRef("time", "front")
    overlap = UltraViewRef("time", "overlap")
    unique = UltraViewRef("time", "unique")
    items = [
        (front, NativeLayoutRect(0.0, 60.0, 100.0, 60.0)),
        (overlap, NativeLayoutRect(0.0, 60.0, 100.0, 60.0)),
        (unique, NativeLayoutRect(120.0, 60.0, 80.0, 60.0)),
    ]
    plan = plan_native_layout(items, metrics=metrics)
    assert tuple(item[0] for item in plan.placed) == (front, overlap, unique)
    assert plan.unplaced == ()
    assert plan.relocated == (overlap,)
    assert plan.warnings == ("exact_overlap_relocated: 2 -> 1",)
    _assert_compact_packing(plan.placed)
    _assert_placed_aspects(items, plan, metrics)


def test_plan_nonsquare_pitch_divides_y_by_pitch_y():
    metrics = _nonsquare_metrics()
    pitch_x, pitch_y = metrics.exact_pitch()
    assert pitch_x != pitch_y
    left = UltraViewRef("time", "left")
    right = UltraViewRef("time", "right")
    items = [
        (left, NativeLayoutRect(0.0, 60.0, 100.0, 60.0)),
        (right, NativeLayoutRect(120.0, 60.0, 100.0, 60.0)),
    ]
    plan = plan_native_layout(items, metrics=metrics)
    assert tuple(item[0] for item in plan.placed) == (left, right)
    for _ref, grid in plan.placed:
        assert grid.row_span == 13
        assert grid.row_span != 7
    _assert_placed_aspects(items, plan, metrics)
    _assert_compact_packing(plan.placed)


def test_apply_native_layout_collision_with_existing_relocates():
    existing = UltraViewRef("time", "keep-me")
    incoming = UltraViewRef("time", "incoming")
    occupied = GridRect(0, 0, 10, 6)
    board = default_board()
    board.free_grid.append(FreeGridPlacement(existing, occupied))
    plan = NativeLayoutPlan(
        placed=((incoming, occupied),),
        unplaced=(),
        warnings=(),
    )
    apply_native_layout(board, plan)
    placed_refs = {item.ref for item in board.free_grid}
    assert existing in placed_refs
    assert incoming in placed_refs
    assert incoming not in board.unplaced
    assert existing not in board.unplaced
    _assert_no_overlaps([(item.ref, item.rect) for item in board.free_grid])
    assert incoming in membership_set(board)
    assert existing in membership_set(board)


def test_apply_native_layout_migrates_template_cards_before_projection():
    from mf4_analyzer.ultraview_core.model import (
        LAYOUT_MODE_FREE_GRID,
        LAYOUT_MODE_TEMPLATE,
        CardPlacement,
    )

    kept_a = UltraViewRef("time", "existing-a")
    kept_b = UltraViewRef("time", "existing-b")
    incoming = UltraViewRef("time", "native")
    board = default_board()
    board.layout_mode = LAYOUT_MODE_TEMPLATE
    board.layout_id = "split_horizontal"
    board.placements = [
        CardPlacement("left", kept_a),
        CardPlacement("right", kept_b),
    ]
    plan = NativeLayoutPlan(
        placed=((incoming, GridRect(12, 8, 5, 6)),),
        unplaced=(),
        warnings=(),
    )
    apply_native_layout(board, plan)
    members = membership_set(board)
    assert kept_a in members
    assert kept_b in members
    assert incoming in members
    assert board.layout_mode == LAYOUT_MODE_FREE_GRID
    assert board.placements == []
    placed_refs = {item.ref for item in board.free_grid}
    assert kept_a in placed_refs
    assert kept_b in placed_refs


def test_apply_native_layout_membership_cap_refuses_extras():
    board = default_board()
    board.unplaced = [
        UltraViewRef("time", f"u{index}")
        for index in range(MAX_BOARD_MEMBERSHIP)
    ]
    extras = (
        UltraViewRef("time", "extra-0"),
        UltraViewRef("time", "extra-1"),
    )
    plan = NativeLayoutPlan(
        placed=(
            (extras[0], GridRect(0, 0, 4, 4)),
            (extras[1], GridRect(8, 0, 4, 4)),
        ),
        unplaced=(),
        warnings=(),
    )
    warnings = apply_native_layout(board, plan)
    assert len(membership_set(board)) <= MAX_BOARD_MEMBERSHIP
    assert extras[0] not in membership_set(board)
    assert extras[1] not in membership_set(board)
    assert any("membership_limit" in warning for warning in warnings)


def test_apply_native_layout_placed_cap_refuses_overflow():
    board = default_board()
    for index in range(MAX_PLACED_CARDS):
        board.free_grid.append(
            FreeGridPlacement(
                UltraViewRef("time", f"p{index}"),
                GridRect(0, index * 4, 4, 4),
            )
        )
    extras = (
        UltraViewRef("time", "grid-extra-0"),
        UltraViewRef("time", "grid-extra-1"),
    )
    plan = NativeLayoutPlan(
        placed=(
            (extras[0], GridRect(12, 0, 4, 4)),
            (extras[1], GridRect(16, 0, 4, 4)),
        ),
        unplaced=(),
        warnings=(),
    )
    warnings = apply_native_layout(board, plan)
    assert len(board.free_grid) == MAX_PLACED_CARDS
    assert extras[0] not in {item.ref for item in board.free_grid}
    assert extras[1] not in {item.ref for item in board.free_grid}
    assert extras[0] in board.unplaced
    assert extras[1] in board.unplaced
    assert any(
        "placed_limit" in warning or "grid_full" in warning
        for warning in warnings
    )
    assert len(membership_set(board)) == MAX_PLACED_CARDS + 2


def test_apply_native_layout_plan_commits_collision_with_existing_cards(qapp):
    from PyQt5.QtWidgets import QWidget

    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controller = coordinator._workspace_controller
    board = coordinator.board
    captured = []
    real = coordinator.add_time_views_from_native_layout

    def _capture(items):
        captured.append(tuple((str(view_id), rect) for view_id, rect in items))
        return real(items)

    coordinator.add_time_views_from_native_layout = _capture
    try:
        first_ids, _first_warnings = real(
            (("view-left", NativeLayoutRect(0.0, 60.0, 100.0, 60.0)),)
        )
        existing = [(item.ref, item.rect) for item in board.free_grid]
        assert first_ids == ("view-left",)
        second_ids, _second_warnings = coordinator.add_time_views_from_native_layout(
            (("view-collide", NativeLayoutRect(0.0, 60.0, 100.0, 60.0)),)
        )
        assert captured
        assert captured[-1][0][0] == "view-collide"
        assert first_ids == ("view-left",)
        collide = UltraViewRef("time", "view-collide")
        assert "view-collide" in second_ids
        assert collide not in board.unplaced
        placed_now = [(item.ref, item.rect) for item in board.free_grid]
        assert existing[0] in placed_now
        _assert_no_overlaps(placed_now)
        history = controller.grid_histories[board.board_id]
        assert len(history.undo) == 2
        assert history.redo == []
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()


def test_ucan_import_preview_reflow_is_one_undo(qapp):
    from PyQt5.QtGui import QColor, QImage
    from PyQt5.QtWidgets import QWidget

    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )
    from mf4_analyzer.ui.ultraview_state import PreviewMeta

    host = QWidget()
    coordinator = UltraViewCoordinator(host, parent=host)
    controller = coordinator._workspace_controller
    items = tuple((f"v{index}", rect) for index, rect in enumerate(UCAN_MM))
    try:
        result = coordinator.add_time_views_from_native_layout(items)
        placed, warnings = result
        assert placed == tuple(f"v{index}" for index in range(7))
        assert set(result.generated_ids) == set(placed)
        assert result.unplaced_ids == ()
        assert (
            len(result.placed_view_ids) + len(result.unplaced_ids)
            == len(result.generated_ids)
        )
        assert coordinator.board.unplaced == []
        assert any("exact_overlap_relocated" in item for item in warnings)
        history = controller.grid_histories[coordinator.board.board_id]
        assert len(history.undo) == 1
        _assert_compact_packing(
            [(item.ref, item.rect) for item in coordinator.board.free_grid]
        )
        for index in range(7):
            ref = UltraViewRef("time", f"v{index}")
            image = QImage(400, 240, QImage.Format_ARGB32)
            image.fill(QColor("#336699"))
            coordinator.store.publish(
                ref,
                image,
                digest=f"v{index}",
                meta=PreviewMeta(ref=ref, title=f"v{index}"),
            )
        coordinator._maybe_apply_pending_auto_aspect(UltraViewRef("time", "v0"))
        assert len(history.undo) == 1
        assert len(coordinator.board.free_grid) == 7
        _assert_no_overlaps(
            [(item.ref, item.rect) for item in coordinator.board.free_grid]
        )
        coordinator._on_free_grid_undo()
        assert coordinator.board.free_grid == []
        assert coordinator.board.unplaced == []
        assert history.undo == []
        assert history.redo
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()
