"""WWT native layout → UltraView: topology, apply transactions, Smart Layout seams."""
from __future__ import annotations

from pathlib import Path

import pytest

from mf4_analyzer.ultraview_core.grid_geometry import (
    BOARD_PADDING,
    GRID_MIN_COLUMN_WIDTH,
    GRID_ROW_HEIGHT,
    SLOT_GUTTER,
    GridMetrics,
    canonical_screen_metrics,
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
# Views 1,3,4 on the upper WinWert band; 2,5,6,7 on the lower band.
# View 7 exact-overlaps View 6 and must follow that reading group.
UCAN_UPPER_ORDERS = (0, 2, 3)
UCAN_LOWER_ORDERS = (1, 4, 5, 6)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_UCAN_SAMPLE_CANDIDATES = (
    _REPO_ROOT / "testdoc" / "WWT" / "U-Can_D6-CSER double_00479.wwt",
    _REPO_ROOT / "testdoc" / "wwt" / "U-Can_D6-CSER double_00479.wwt",
)


def _optional_ucan_sample() -> Path | None:
    for path in _UCAN_SAMPLE_CANDIDATES:
        if path.is_file():
            return path
    return None


def _ucan_refs() -> tuple[UltraViewRef, ...]:
    return tuple(UltraViewRef("time", f"v{index}") for index in range(7))


def _ucan_items(refs: tuple[UltraViewRef, ...]):
    return list(zip(refs, UCAN_MM))


def _source_row_groups(plan, refs: tuple[UltraViewRef, ...]):
    """Prefer solver facts; fall back to placed GridRect bands."""
    facts = getattr(plan, "facts", None) or getattr(plan, "card_facts", None)
    if facts:
        buckets: dict[int, list[UltraViewRef]] = {}
        order = {ref: index for index, ref in enumerate(refs)}
        for fact in facts:
            buckets.setdefault(int(fact.source_row), []).append(fact.ref)
        groups = []
        for row_id in sorted(
            buckets,
            key=lambda rid: min(order[ref] for ref in buckets[rid]),
        ):
            members = tuple(sorted(buckets[row_id], key=lambda ref: order[ref]))
            groups.append(members)
        return groups
    items = list(plan.placed)
    ordered = sorted(items, key=lambda pair: (pair[1].row, pair[1].column))
    bands: list[list[UltraViewRef]] = []
    bounds: list[list[int]] = []
    for ref, rect in ordered:
        top = rect.row
        bottom = rect.row + rect.row_span
        matched = None
        for index, band in enumerate(bounds):
            if top < band[1] and bottom > band[0]:
                matched = index
                break
        if matched is None:
            bands.append([ref])
            bounds.append([top, bottom])
            continue
        bands[matched].append(ref)
        bounds[matched][0] = min(bounds[matched][0], top)
        bounds[matched][1] = max(bounds[matched][1], bottom)
    order = sorted(range(len(bands)), key=lambda index: bounds[index][0])
    return [tuple(bands[index]) for index in order]


def _assert_ucan_reading_groups(plan, refs: tuple[UltraViewRef, ...]) -> None:
    upper = {refs[index] for index in UCAN_UPPER_ORDERS}
    lower = {refs[index] for index in UCAN_LOWER_ORDERS}
    groups = _source_row_groups(plan, refs)
    group_sets = [set(group) for group in groups]
    mixed = [group for group in group_sets if not (group <= upper or group <= lower)]
    assert not mixed, f"reading groups mixed upper/lower members: {mixed}"
    upper_bands = [group for group in group_sets if group <= upper]
    lower_bands = [group for group in group_sets if group <= lower]
    assert set().union(*upper_bands) == upper
    assert set().union(*lower_bands) == lower
    v6_bands = [index for index, group in enumerate(groups) if refs[5] in group]
    v7_bands = [index for index, group in enumerate(groups) if refs[6] in group]
    assert v6_bands and v7_bands
    assert abs(v7_bands[0] - v6_bands[0]) <= 1, (
        "View 7 must follow View 6's reading group or an adjacent continuation, "
        f"not float between groups: groups={groups}"
    )


def _assert_view7_follows_view6(placed, refs: tuple[UltraViewRef, ...]) -> None:
    by_ref = dict(placed)
    rect6 = by_ref[refs[5]]
    rect7 = by_ref[refs[6]]
    overlapping = not (
        rect6.row + rect6.row_span <= rect7.row
        or rect7.row + rect7.row_span <= rect6.row
    )
    continuation = rect7.row == rect6.row + rect6.row_span
    assert overlapping or continuation, (
        "View 7 must share View 6's reading band or sit on the next "
        f"continuation row: {rect6!r} vs {rect7!r}"
    )
    upper = [by_ref[refs[index]] for index in UCAN_UPPER_ORDERS]
    lower_core = [by_ref[refs[index]] for index in (1, 4, 5)]
    upper_bottom = max(rect.row + rect.row_span for rect in upper)
    lower_top = min(rect.row for rect in lower_core)
    if upper_bottom < lower_top:
        floating = (
            upper_bottom <= rect7.row
            and rect7.row + rect7.row_span <= lower_top
        )
        assert not floating, (
            f"View 7 floated between groups: {rect7!r} gap=[{upper_bottom}, {lower_top})"
        )


def _ordinary_reading_area_ratio(placed) -> float:
    """balanced ordinary reading-box area ratio via frozen geometry helpers.

    Helpers live on ``ultraview_core.grid_geometry`` (findings.md). Missing
    names are an intended T0 failure.
    """
    from mf4_analyzer.ultraview_core.grid_geometry import (
        canonical_screen_metrics,
        inner_reading_box,
    )

    placements = tuple(FreeGridPlacement(ref, rect) for ref, rect in placed)
    metrics = canonical_screen_metrics(placements)
    areas: list[float] = []
    for _ref, rect in placed:
        _x, _y, width, height = inner_reading_box(rect, metrics)
        area = float(width) * float(height)
        assert area > 0.0
        areas.append(area)
    return max(areas) / min(areas)


def _ucan_reading_area_ratio(plan) -> float:
    direct = getattr(plan, "ordinary_reading_area_ratio", None)
    if isinstance(direct, (int, float)):
        return float(direct)
    result = getattr(plan, "result", None)
    if result is not None:
        ratio = getattr(result, "size_ratio", None)
        if isinstance(ratio, (int, float)):
            return float(ratio)
    return _ordinary_reading_area_ratio(plan.placed)


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


def test_ucan_plan_places_all_seven_preserving_reading_groups():
    """Spec §10/§18: 7 placed, source order, groups 1,3,4 / 2,5,6,7, View 7 follows 6.

    Does not require Manhattan ``exact_overlap_relocated`` upward or compact
    first-fit packing. Continuation rows must stay adjacent to the lower group.
    """
    refs = _ucan_refs()
    plan = plan_native_layout(_ucan_items(refs))
    assert len(plan.placed) == 7
    assert plan.unplaced == ()
    assert tuple(ref for ref, _grid in plan.placed) == refs
    assert refs[6] not in plan.unplaced
    _assert_no_overlaps(plan.placed)
    _assert_ucan_reading_groups(plan, refs)
    _assert_view7_follows_view6(plan.placed, refs)
    by_ref = dict(plan.placed)
    assert by_ref[refs[0]].column < by_ref[refs[2]].column < by_ref[refs[3]].column
    assert by_ref[refs[6]] != by_ref[refs[5]]


def test_ucan_balanced_ordinary_reading_area_ratio_at_most_1_35():
    """Spec §7.1/§18: balanced ordinary reading-area ratio <= 1.35; no 100mm hero."""
    refs = _ucan_refs()
    plan = plan_native_layout(_ucan_items(refs))
    assert len(plan.placed) == 7
    ratio = _ucan_reading_area_ratio(plan)
    assert ratio <= 1.35, (
        "balanced ordinary reading-area ratio must be <= 1.35 "
        f"(got {ratio:.3f}; 100mm source width is not a hero command)"
    )


def test_apply_native_layout_is_one_board_mutation():
    refs = _ucan_refs()
    plan = plan_native_layout(_ucan_items(refs))
    board = default_board()
    warnings = apply_native_layout(board, plan)
    assert len(board.free_grid) == 7
    assert board.unplaced == []
    assert [item.ref for item in board.free_grid] == list(refs)
    _assert_no_overlaps([(item.ref, item.rect) for item in board.free_grid])
    _assert_ucan_reading_groups(plan, refs)


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
            (UltraViewRef("time", "view-left"), GridRect(0, 0, 6, 6)),
            (UltraViewRef("time", "view-right"), GridRect(6, 0, 6, 6)),
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
    """Planner 1× pitch is the 1600-wide canonical screen metrics, not 96px."""
    return canonical_screen_metrics(())


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
    # Smart Layout owns spans from canonical pitch; a dummy/stretched
    # ``metrics=`` must not reopen the 96px millimetre conversion path.
    assert stretched_plan.placed == default_plan.placed


def test_plan_wide_rect_is_not_a_full_row_hero():
    """Source millimetre width is salience, not a GRID_COLUMNS hero command."""
    ref = UltraViewRef("time", "wide")
    items = [(ref, NativeLayoutRect(0.0, 50.0, 180.0, 50.0))]
    plan = plan_native_layout(items, metrics=_canonical_metrics())
    assert tuple(item[0] for item in plan.placed) == (ref,)
    wide = plan.placed[0][1]
    assert wide.column_span < GRID_COLUMNS
    assert wide.column_span == plan_native_layout(
        [(UltraViewRef("time", "narrow"), NativeLayoutRect(0.0, 50.0, 50.0, 50.0))],
        metrics=_canonical_metrics(),
    ).placed[0][1].column_span


def test_plan_tall_and_companion_keep_source_order_without_mm_spans():
    tall = UltraViewRef("time", "tall")
    companion = UltraViewRef("time", "companion")
    items = [
        (tall, NativeLayoutRect(0.0, 120.0, 40.0, 120.0)),
        (companion, NativeLayoutRect(50.0, 80.0, 160.0, 80.0)),
    ]
    plan = plan_native_layout(items, metrics=_canonical_metrics())
    assert tuple(item[0] for item in plan.placed) == (tall, companion)
    by_ref = dict(plan.placed)
    assert by_ref[tall].column < by_ref[companion].column
    _assert_no_overlaps(plan.placed)


def test_plan_stacked_top_bottom_preserves_source_order():
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
    _assert_compact_packing(plan.placed)


def test_plan_side_by_side_preserves_source_order():
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
    by_ref = dict(plan.placed)
    assert by_ref[overlap] != by_ref[front]
    assert by_ref[overlap].row >= by_ref[front].row


def test_plan_nonsquare_metrics_do_not_change_canonical_spans():
    """Dummy nonsquare pitch must not reopen millimetre→span conversion."""
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
    assert plan.placed == plan_native_layout(items).placed
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


def test_ucan_import_is_one_undo_through_the_real_projection_seam(qapp):
    """WWT→UltraView owner boundary: real plan_native_layout + apply, one undo.

    Does not replace the projection with a lambda. Warning-bearing placement
    still commits history/dirty/refresh. Undo once returns to the empty Board.
    """
    from PyQt5.QtWidgets import QWidget

    from mf4_analyzer.ui.main_window.ultraview_coordinator import (
        UltraViewCoordinator,
    )

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
        history = controller.grid_histories[coordinator.board.board_id]
        assert len(history.undo) == 1
        placed_pairs = [(item.ref, item.rect) for item in coordinator.board.free_grid]
        _assert_no_overlaps(placed_pairs)
        refs = _ucan_refs()
        _assert_view7_follows_view6(placed_pairs, refs)
        coordinator._on_free_grid_undo()
        assert coordinator.board.free_grid == []
        assert coordinator.board.unplaced == []
        assert history.undo == []
        assert history.redo
    finally:
        coordinator.shutdown()
        host.deleteLater()
        qapp.processEvents()


@pytest.mark.skipif(
    _optional_ucan_sample() is None,
    reason="optional local U-Can WWT sample is not present",
)
def test_optional_ucan_wwt_sample_smoke(qapp, monkeypatch):
    """Optional testdoc smoke. Missing sample skips this test only, not owners."""
    from mf4_analyzer.ui.main_window import MainWindow

    path = _optional_ucan_sample()
    assert path is not None
    mw = MainWindow()
    qapp.processEvents()

    class _AcceptLayout:
        def ask(self, body, informative=""):
            return True

        def noop(self, *args, **kwargs):
            return None

    accept = _AcceptLayout()
    monkeypatch.setattr(mw._wwt_import, "_ask_layout", accept.ask)
    monkeypatch.setattr(mw, "plot_time", accept.noop)
    monkeypatch.setattr(mw, "_apply_active_view", accept.noop)
    try:
        mw._load_one(str(path))
        qapp.processEvents()
        board = mw._ultraview.board
        assert len(board.free_grid) == 7
        assert board.unplaced == []
        placed = [(item.ref, item.rect) for item in board.free_grid]
        _assert_no_overlaps(placed)
        refs = tuple(item.ref for item in board.free_grid)
        assert len(refs) == 7
        history = mw._ultraview._workspace_controller.grid_histories[board.board_id]
        assert len(history.undo) == 1
    finally:
        mw.close()
        mw.deleteLater()
        qapp.processEvents()
