"""T0 failing contracts for UltraView Smart Layout (Qt-free).

Owner of the frozen solver / canonical-metrics API named in
``docs/analyzer/specs/2026-08-30-ultraview-adaptive-smart-layout-and-fit-spec.md``
and ``findings.md``. These tests must fail until T1/T2 land the interfaces;
they must not pass by stubbing product modules.
"""
from __future__ import annotations

import math
import random
from collections.abc import Sequence

import pytest

from mf4_analyzer.ultraview_core.grid_geometry import (
    CARD_FOOTER_HEIGHT,
    CARD_HEADER_HEIGHT,
    CARD_IMAGE_PADDING,
    GridMetrics,
    canonical_export_metrics,
    canonical_screen_metrics,
    contained_preview_rect,
    grid_metrics,
    inner_reading_box,
    reading_fill,
    rect_to_pixels,
    rects_overlap,
)
from mf4_analyzer.ultraview_core.model import (
    FreeGridPlacement,
    GridRect,
    UltraViewRef,
    grid_rect_in_safety,
)
from mf4_analyzer.ultraview_core.smart_layout import (
    SmartCardFact,
    SmartLayoutPolicy,
    SmartLayoutResult,
    solve_smart_layout,
)

# Copied from tests/ui/test_ultraview_native_layout.py ``UCAN_MM``.
# WinWert y is the window bottom. Not loaded from testdoc/.
UCAN_MM = (
    (25.0, 65.0, 100.0, 60.0),
    (41.0, 138.2, 90.0, 60.0),
    (147.5, 62.5, 50.0, 60.0),
    (215.5, 62.5, 50.0, 60.0),
    (147.5, 138.0, 50.0, 60.0),
    (214.5, 138.0, 50.0, 60.0),
    (214.5, 138.0, 50.0, 60.0),
)

# Frozen topology: upper group views 1,3,4 / lower group 2,5,6,7.
# View 7 exact-overlaps View 6 → same source_row, continuation after View 6.
UCAN_SOURCE = (
    ("v1", 0, 0, 0),
    ("v2", 1, 1, 0),
    ("v3", 2, 0, 1),
    ("v4", 3, 0, 2),
    ("v5", 4, 1, 1),
    ("v6", 5, 1, 2),
    ("v7", 6, 1, 3),
)

UCAN_UPPER = ("v1", "v3", "v4")
UCAN_LOWER = ("v2", "v5", "v6", "v7")

CANONICAL_VIEWPORT = (1600, 900)
UCAN_VIEWPORT = (1200, 750)
FALLBACK_ASPECT = 16.0 / 9.0
SEARCH_VISIT_CAP = 4096
ASPECT_16_9 = (16.0, 9.0)

# A card whose inner reading box is close to 16:9 after chrome deduction.
WELL_CHOSEN_16X9_RECT = GridRect(0, 0, 16, 13)


def _card_fact(
    view_id: str,
    source_order: int,
    *,
    section: str = "time",
    source_row: int | None = 0,
    source_column: int | None = 0,
    source_salience: float | None = 1.0,
    preview_aspect: float | None = FALLBACK_ASPECT,
    preview_confidence: str = "captured",
    current_rect: GridRect | None = None,
    locked_rect: GridRect | None = None,
) -> SmartCardFact:
    return SmartCardFact(
        ref=UltraViewRef(section, view_id),
        source_order=source_order,
        source_row=source_row,
        source_column=source_column,
        source_salience=source_salience,
        preview_aspect=preview_aspect,
        preview_confidence=preview_confidence,
        current_rect=current_rect,
        locked_rect=locked_rect,
    )


def _compressed_salience(area: float, median_area: float) -> float:
    ratio = area / median_area
    return min(1.80, max(0.75, math.exp(0.35 * math.log(ratio))))


def _ucan_facts(
    *,
    aspects: Sequence[float | None] | None = None,
    confidence: str = "captured",
) -> tuple[SmartCardFact, ...]:
    areas = tuple(width * height for _x, _y, width, height in UCAN_MM)
    median = sorted(areas)[len(areas) // 2]
    chosen = aspects if aspects is not None else tuple(FALLBACK_ASPECT for _ in UCAN_MM)
    facts: list[SmartCardFact] = []
    for (view_id, order, row, column), area, aspect in zip(
        UCAN_SOURCE, areas, chosen, strict=True
    ):
        if aspect is None or not math.isfinite(aspect) or aspect <= 0.0:
            conf: str = "fallback"
            preview = None
        else:
            conf = confidence
            preview = float(aspect)
        facts.append(
            _card_fact(
                view_id,
                order,
                source_row=row,
                source_column=column,
                source_salience=_compressed_salience(area, median),
                preview_aspect=preview,
                preview_confidence=conf,
            )
        )
    return tuple(facts)


def _balanced_ucan_policy() -> SmartLayoutPolicy:
    return SmartLayoutPolicy(
        mode="balanced",
        density="auto",
        target_viewport=UCAN_VIEWPORT,
        preserve_locked=True,
    )


def _policy(
    *,
    mode: str = "balanced",
    density: str = "auto",
    target_viewport: tuple[int, int] = UCAN_VIEWPORT,
    preserve_locked: bool = True,
) -> SmartLayoutPolicy:
    return SmartLayoutPolicy(
        mode=mode,
        density=density,
        target_viewport=target_viewport,
        preserve_locked=preserve_locked,
    )


def _as_placements(
    pairs: Sequence[tuple[UltraViewRef, GridRect]],
) -> tuple[FreeGridPlacement, ...]:
    return tuple(FreeGridPlacement(ref, rect) for ref, rect in pairs)


def _scale_metrics(metrics: GridMetrics, scale: float) -> GridMetrics:
    """Uniform 1× → DPR/zoom multiply without importing UI viewport.py."""
    base = metrics.base if metrics.base is not None else metrics
    if abs(float(scale) - 1.0) < 1e-12:
        return base
    return GridMetrics(
        board_width=max(1, int(round(base.board_width * scale))),
        board_height=max(1, int(round(base.board_height * scale))),
        column_width=max(1, int(round(base.column_width * scale))),
        row_height=max(1, int(round(base.row_height * scale))),
        gutter=max(0, int(round(base.gutter * scale))),
        padding=max(0, int(round(base.padding * scale))),
        resolution=base.resolution,
        scale=float(scale),
        base=base,
    )


def _min_inner_reading_box(count: int) -> tuple[int, int]:
    if count <= 8:
        return 240, 135
    if count <= 12:
        return 200, 112
    return 176, 99


def _assert_finite_rect(rect: GridRect) -> None:
    for value in (rect.column, rect.row, rect.column_span, rect.row_span):
        assert isinstance(value, int)
        assert math.isfinite(float(value))
        assert not isinstance(value, bool)


def _assert_legal_solve(
    result: SmartLayoutResult,
    facts: Sequence[SmartCardFact],
    *,
    require_min_reading_box: bool = True,
) -> dict[UltraViewRef, GridRect]:
    assert result.accepted is True
    assert result.search_visits <= SEARCH_VISIT_CAP
    refs = [ref for ref, _rect in result.placements]
    assert len(refs) == len(facts)
    assert len(set(refs)) == len(facts)
    assert set(refs) == {fact.ref for fact in facts}
    by_ref = {ref: rect for ref, rect in result.placements}
    rects = list(by_ref.values())
    for index, left in enumerate(rects):
        _assert_finite_rect(left)
        assert grid_rect_in_safety(left)
        for right in rects[index + 1 :]:
            assert not rects_overlap(left, right), (left, right)
    for fact in facts:
        if fact.locked_rect is not None:
            assert by_ref[fact.ref] == fact.locked_rect
    if require_min_reading_box:
        metrics = canonical_screen_metrics(_as_placements(result.placements))
        min_w, min_h = _min_inner_reading_box(len(facts))
        for _ref, rect in result.placements:
            _x, _y, width, height = inner_reading_box(rect, metrics)
            assert width >= min_w and height >= min_h, (width, height, min_w, min_h)
    order_by_ref = {fact.ref: fact.source_order for fact in facts}
    row_by_ref = {fact.ref: fact.source_row for fact in facts}
    grouped: dict[int | None, list[tuple[int, GridRect]]] = {}
    for ref, rect in result.placements:
        grouped.setdefault(row_by_ref[ref], []).append((order_by_ref[ref], rect))
    for _source_row, items in grouped.items():
        items.sort(key=lambda item: (item[1].row, item[1].column))
        source_orders = [item[0] for item in items]
        assert source_orders == sorted(source_orders)
    return by_ref


def _facts_for_count(count: int, *, aspect: float | None = FALLBACK_ASPECT) -> tuple[SmartCardFact, ...]:
    cols = 6 if count >= 6 else max(1, count)
    return tuple(
        _card_fact(
            f"c{index}",
            index,
            source_row=index // cols,
            source_column=index % cols,
            preview_aspect=aspect,
            preview_confidence="captured" if aspect is not None else "fallback",
        )
        for index in range(count)
    )


def _facts_for_aspect(aspect: float | None, *, count: int = 4) -> tuple[SmartCardFact, ...]:
    if aspect is None or not math.isfinite(aspect) or aspect <= 0.0:
        confidence = "fallback"
        preview = None if aspect is None else aspect
    else:
        confidence = "captured"
        preview = float(aspect)
    return tuple(
        _card_fact(
            f"a{index}",
            index,
            source_row=0,
            source_column=index,
            preview_aspect=preview,
            preview_confidence=confidence,
        )
        for index in range(count)
    )


def _facts_for_topology(topology: str) -> tuple[SmartCardFact, ...]:
    if topology == "single_row":
        coords = [(0, index) for index in range(4)]
    elif topology == "multi_row":
        coords = [(index // 2, index % 2) for index in range(4)]
    elif topology == "staggered":
        coords = [(0, 0), (0, 2), (1, 1), (1, 3)]
    elif topology == "exact_overlap":
        coords = [(0, 0), (0, 1), (0, 2), (0, 2)]
    elif topology == "partial_overlap":
        coords = [(0, 0), (0, 1), (1, 0), (1, 1)]
    elif topology == "bridge_rect":
        # Distinct source rows so a tall bridge cannot chain-merge 0 with 2.
        coords = [(0, 0), (1, 1), (2, 0), (0, 2)]
    else:
        raise AssertionError(f"unknown topology {topology!r}")
    return tuple(
        _card_fact(
            f"t{index}",
            index,
            source_row=row,
            source_column=column,
            preview_aspect=FALLBACK_ASPECT,
        )
        for index, (row, column) in enumerate(coords)
    )


# ---------------------------------------------------------------------------
# 1. Metric parity
# ---------------------------------------------------------------------------


def test_neutral_chrome_constants_live_in_grid_geometry():
    assert CARD_HEADER_HEIGHT == 34
    assert CARD_FOOTER_HEIGHT == 24
    assert CARD_IMAGE_PADDING == 8


def test_canonical_planner_screen_export_share_1x_outer_pixel_rect():
    ref = UltraViewRef("time", "metric")
    rect = GridRect(2, 4, 16, 12)
    placements = (FreeGridPlacement(ref, rect),)
    screen = canonical_screen_metrics(placements)
    export = canonical_export_metrics(placements)
    planner = grid_metrics((1600, 0), placements)
    px_screen = rect_to_pixels(rect, screen)
    px_export = rect_to_pixels(rect, export)
    px_planner = rect_to_pixels(rect, planner)
    assert px_screen == px_export == px_planner
    assert px_screen[2] > 0 and px_screen[3] > 0


def test_dpr_scale_is_uniform_multiply_and_window_width_does_not_plan_gridrect():
    ref = UltraViewRef("time", "metric")
    rect = GridRect(4, 6, 12, 10)
    placements = (FreeGridPlacement(ref, rect),)
    screen = canonical_screen_metrics(placements)
    export = canonical_export_metrics(placements)
    planner = grid_metrics((1600, 0), placements)
    px_1x = rect_to_pixels(rect, screen)
    assert px_1x == rect_to_pixels(rect, export)
    assert px_1x == rect_to_pixels(rect, planner)

    scaled = _scale_metrics(screen, 2.0)
    assert scaled.exact_padding() == pytest.approx(screen.exact_padding() * 2.0)
    pitch_1x = screen.exact_pitch()
    pitch_2x = scaled.exact_pitch()
    assert pitch_2x[0] == pytest.approx(pitch_1x[0] * 2.0)
    assert pitch_2x[1] == pytest.approx(pitch_1x[1] * 2.0)

    px_2x = rect_to_pixels(rect, scaled)
    logical_from_dpr2 = tuple(component / 2.0 for component in px_2x)
    for recovered, original in zip(logical_from_dpr2, px_1x):
        assert abs(recovered - original) <= 1.0

    # Canonical 1× pitch is the 1600-wide contract, not the current window.
    assert screen.column_width == planner.column_width == export.column_width
    assert screen.column_width == grid_metrics((1600, 0), placements).column_width
    assert rect == GridRect(4, 6, 12, 10)


# ---------------------------------------------------------------------------
# 2. Aspect fitting (chrome-aware reading box)
# ---------------------------------------------------------------------------


def test_captured_16x9_reading_fill_on_well_chosen_card():
    placements = (FreeGridPlacement(UltraViewRef("time", "fit"), WELL_CHOSEN_16X9_RECT),)
    metrics = canonical_screen_metrics(placements)
    outer = rect_to_pixels(WELL_CHOSEN_16X9_RECT, metrics)
    reading = inner_reading_box(WELL_CHOSEN_16X9_RECT, metrics)
    assert reading[0] == outer[0] + CARD_IMAGE_PADDING
    assert reading[1] == outer[1] + CARD_HEADER_HEIGHT + CARD_IMAGE_PADDING
    assert reading[2] == outer[2] - 2 * CARD_IMAGE_PADDING
    assert reading[3] == (
        outer[3] - CARD_HEADER_HEIGHT - CARD_FOOTER_HEIGHT - 2 * CARD_IMAGE_PADDING
    )
    preview = contained_preview_rect(reading, ASPECT_16_9)
    px, py, pw, ph = preview
    rx, ry, rw, rh = reading
    assert pw > 0 and ph > 0
    assert px >= rx and py >= ry
    assert px + pw <= rx + rw
    assert py + ph <= ry + rh
    fill = reading_fill(preview, reading)
    assert math.isfinite(fill)
    assert fill >= 0.82


# ---------------------------------------------------------------------------
# 3–4. U-Can synthetic topology and balanced size ratio
# ---------------------------------------------------------------------------


def test_ucan_synthetic_keeps_two_groups_and_view_7_does_not_float():
    facts = _ucan_facts()
    result = solve_smart_layout(facts, _balanced_ucan_policy())
    by_ref = _assert_legal_solve(result, facts)
    assert result.used_fallback is False

    id_to_ref = {fact.ref.view_id: fact.ref for fact in facts}
    upper_rects = [by_ref[id_to_ref[view_id]] for view_id in UCAN_UPPER]
    lower_rects = [by_ref[id_to_ref[view_id]] for view_id in UCAN_LOWER]
    upper_bottom = max(rect.row + rect.row_span for rect in upper_rects)
    lower_top = min(rect.row for rect in lower_rects)
    assert upper_bottom <= lower_top

    view6 = by_ref[id_to_ref["v6"]]
    view7 = by_ref[id_to_ref["v7"]]
    same_row = view7.row == view6.row
    continuation = view7.row == view6.row + view6.row_span
    assert same_row or continuation
    lower_without_v7 = [by_ref[id_to_ref[view_id]] for view_id in ("v2", "v5", "v6")]
    rest_lower_top = min(rect.row for rect in lower_without_v7)
    assert not (upper_bottom <= view7.row < rest_lower_top)

    def _row_then_col(view_id: str) -> tuple[int, int]:
        rect = by_ref[id_to_ref[view_id]]
        return (rect.row, rect.column)

    assert _row_then_col("v1") < _row_then_col("v3") < _row_then_col("v4")
    assert _row_then_col("v2") < _row_then_col("v5") < _row_then_col("v6") < _row_then_col("v7")


def test_ucan_balanced_ordinary_reading_area_ratio_at_most_1_35():
    facts = _ucan_facts()
    result = solve_smart_layout(facts, _balanced_ucan_policy())
    by_ref = _assert_legal_solve(result, facts)
    metrics = canonical_screen_metrics(_as_placements(result.placements))
    areas = []
    for _ref, rect in by_ref.items():
        _x, _y, width, height = inner_reading_box(rect, metrics)
        area = width * height
        assert area > 0
        areas.append(area)
    ratio = max(areas) / min(areas)
    assert math.isfinite(ratio)
    assert ratio <= 1.35


# ---------------------------------------------------------------------------
# 5. Determinism
# ---------------------------------------------------------------------------


UCAN_DISTINCT_ASPECTS = (1.0, 4.0 / 3.0, 16.0 / 9.0, 9.0 / 16.0, 2.4, 0.5, 21.0 / 9.0)


def test_ucan_permutations_and_repeats_are_byte_identical():
    forward = _ucan_facts(aspects=UCAN_DISTINCT_ASPECTS)
    reverse = tuple(reversed(forward))
    shuffled = list(forward)
    random.Random(0).shuffle(shuffled)
    policy = _balanced_ucan_policy()

    first = solve_smart_layout(forward, policy)
    _assert_legal_solve(first, forward)
    assert first.search_visits <= SEARCH_VISIT_CAP
    assert first.placements == solve_smart_layout(reverse, policy).placements
    assert first.placements == solve_smart_layout(tuple(shuffled), policy).placements

    for _ in range(100):
        again = solve_smart_layout(forward, policy)
        assert again.placements == first.placements
        assert again.search_visits == first.search_visits
        assert again.used_fallback == first.used_fallback
        assert again.accepted == first.accepted


# ---------------------------------------------------------------------------
# 6. Count / aspect / topology matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("count", (2, 3, 4, 7, 8, 9, 12, 13, 24))
def test_count_matrix_legal_pack(count: int):
    facts = _facts_for_count(count)
    result = solve_smart_layout(facts, _policy())
    _assert_legal_solve(result, facts)


@pytest.mark.parametrize(
    "label, aspect",
    (
        ("1:1", 1.0),
        ("4:3", 4.0 / 3.0),
        ("16:9", 16.0 / 9.0),
        ("9:16", 9.0 / 16.0),
        ("ultrawide", 21.0 / 9.0),
        ("ultra-tall", 9.0 / 21.0),
        ("missing", None),
        ("invalid", float("nan")),
    ),
    ids=("1:1", "4:3", "16:9", "9:16", "ultrawide", "ultra-tall", "missing", "invalid"),
)
def test_aspect_matrix_four_cards_legal_and_finite(label: str, aspect: float | None):
    facts = _facts_for_aspect(aspect)
    result = solve_smart_layout(facts, _policy())
    _assert_legal_solve(result, facts)
    for _ref, rect in result.placements:
        _assert_finite_rect(rect)


@pytest.mark.parametrize(
    "topology",
    (
        "single_row",
        "multi_row",
        "staggered",
        "exact_overlap",
        "partial_overlap",
        "bridge_rect",
    ),
)
def test_topology_matrix_legal_pack(topology: str):
    facts = _facts_for_topology(topology)
    result = solve_smart_layout(facts, _policy())
    by_ref = _assert_legal_solve(result, facts)
    if topology == "exact_overlap":
        stacked = by_ref[facts[2].ref]
        continuation = by_ref[facts[3].ref]
        assert continuation != stacked
        assert continuation.row >= stacked.row
        if continuation.row > stacked.row:
            assert continuation.row == stacked.row + stacked.row_span


@pytest.mark.parametrize("mode", ("balanced", "preserve_salience", "equal_grid"))
@pytest.mark.parametrize("density", ("auto", "comfortable", "compact"))
def test_policy_mode_and_density_solve_four_cards(mode: str, density: str):
    facts = _facts_for_count(4)
    result = solve_smart_layout(facts, _policy(mode=mode, density=density))
    _assert_legal_solve(result, facts, require_min_reading_box=density != "compact")


# ---------------------------------------------------------------------------
# 7. Locked unsolvable → reject, zero mutation
# ---------------------------------------------------------------------------


def test_locked_unsolvable_rejects_without_mutating_input():
    lock = GridRect(0, 0, 12, 8)
    facts = [
        _card_fact("locked-a", 0, locked_rect=lock, current_rect=lock),
        _card_fact("locked-b", 1, locked_rect=lock, current_rect=lock),
        _card_fact("free", 2, current_rect=GridRect(12, 0, 8, 6)),
    ]
    original = list(facts)
    original_ids = [id(item) for item in facts]
    result = solve_smart_layout(facts, _policy())
    assert result.accepted is False
    assert isinstance(result.reason, str) and result.reason
    assert facts == original
    assert [id(item) for item in facts] == original_ids
    assert all(left is right for left, right in zip(facts, original))
    if result.placements:
        placed = dict(result.placements)
        assert placed[facts[0].ref] == lock
        assert placed[facts[1].ref] == lock


# ---------------------------------------------------------------------------
# 8. 4096 visit cap → deterministic equal-grid fallback
# ---------------------------------------------------------------------------


def test_search_budget_caps_at_4096_with_equal_grid_fallback():
    aspects = (1.0, 4.0 / 3.0, 16.0 / 9.0, 9.0 / 16.0, 3.5, 0.3, 21.0 / 9.0, 0.4)
    facts = tuple(
        _card_fact(
            f"explode{index}",
            index,
            source_row=0,
            source_column=index,
            source_salience=0.75 + (index % 8) * 0.13,
            preview_aspect=aspects[index % len(aspects)],
        )
        for index in range(24)
    )
    policy = _policy(mode="preserve_salience", density="comfortable")
    first = solve_smart_layout(facts, policy)
    second = solve_smart_layout(facts, policy)
    assert first.search_visits <= SEARCH_VISIT_CAP
    assert second.search_visits == first.search_visits
    assert first.placements == second.placements
    assert first.used_fallback == second.used_fallback
    assert first.accepted == second.accepted
    tokens = " ".join(first.diagnostics)
    if first.used_fallback:
        assert "search_budget_fallback" in tokens or "search_budget_fallback" in first.diagnostics
        if first.accepted:
            _assert_legal_solve(first, facts, require_min_reading_box=True)
        else:
            assert first.reason
            assert "no_legal_layout" in first.reason
    else:
        assert first.accepted is False
        assert first.reason
        assert "no_legal_layout" in first.reason


# ---------------------------------------------------------------------------
# Extra contracts from spec §9 / §8
# ---------------------------------------------------------------------------


def test_missing_and_nonfinite_preview_falls_back_to_16x9_without_nan():
    variants: tuple[float | None, ...] = (
        None,
        float("nan"),
        float("inf"),
        float("-inf"),
        0.0,
        -1.5,
    )
    explicit = _facts_for_aspect(FALLBACK_ASPECT, count=3)
    expected = solve_smart_layout(explicit, _policy())
    _assert_legal_solve(expected, explicit)
    for aspect in variants:
        facts = _facts_for_aspect(aspect, count=3)
        result = solve_smart_layout(facts, _policy())
        _assert_legal_solve(result, facts)
        assert result.placements == expected.placements
        for _ref, rect in result.placements:
            _assert_finite_rect(rect)


@pytest.mark.parametrize(
    "bad_viewport",
    (
        (0, 0),
        (0, 900),
        (1600, 0),
        (-10, 800),
        (1600, -4),
        (float("nan"), 900),
        (1600, float("inf")),
    ),
)
def test_illegal_target_viewport_uses_canonical_1600x900(bad_viewport):
    facts = _facts_for_count(4)
    illegal = solve_smart_layout(facts, _policy(target_viewport=bad_viewport))
    canonical = solve_smart_layout(
        facts, _policy(target_viewport=CANONICAL_VIEWPORT)
    )
    _assert_legal_solve(canonical, facts)
    assert illegal.placements == canonical.placements
    assert illegal.accepted is True


def test_facts_are_keyed_by_composite_ref_not_display_title():
    facts = (
        _card_fact("Torque", 0, section="time", source_row=0, source_column=0),
        _card_fact("Torque", 1, section="fft", source_row=0, source_column=1),
        _card_fact("方向盘扭矩", 2, section="time", source_row=1, source_column=0),
        _card_fact("方向盘扭矩", 3, section="order", source_row=1, source_column=1),
    )
    result = solve_smart_layout(facts, _policy())
    by_ref = _assert_legal_solve(result, facts)
    assert facts[0].ref != facts[1].ref
    assert facts[2].ref != facts[3].ref
    assert len(by_ref) == 4
    assert set(by_ref) == {fact.ref for fact in facts}


def test_result_exposes_search_diagnostics_not_a_scalar_score():
    facts = _facts_for_count(4)
    result = solve_smart_layout(facts, _policy())
    _assert_legal_solve(result, facts)
    assert isinstance(result.diagnostics, tuple)
    assert isinstance(result.search_visits, int)
    assert isinstance(result.used_fallback, bool)
    score = getattr(result, "score", None)
    assert not isinstance(score, float)
    vector = getattr(result, "score_vector", None)
    if vector is not None:
        assert isinstance(vector, (tuple, list))
        assert len(vector) >= 2
