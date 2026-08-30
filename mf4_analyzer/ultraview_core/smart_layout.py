"""Qt-free UltraView Smart Layout solver.

Owner of the spec §8 DTOs and ``solve_smart_layout``. Geometry chrome lives in
``grid_geometry``; this module must not import Qt, ``mf4_analyzer.ui``,
PreviewStore, QSettings, or viewport widgets.
"""
from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from .grid_geometry import (
    GridMetrics,
    canonical_screen_metrics,
    contained_preview_rect,
    inner_reading_box,
    plot_size_for_rect,
    preferred_hug_span,
    reading_fill,
    rect_to_pixels,
    rects_overlap,
    union_grid_rect,
)
from .model import (
    GRID_COLUMNS,
    GRID_MAX_COLUMN_SPAN,
    GRID_MAX_ROW_SPAN,
    GRID_MIN_COLUMN_SPAN,
    GRID_MIN_ROW_SPAN,
    SAFETY_ROW_MAX,
    FreeGridPlacement,
    GridRect,
    UltraViewRef,
    grid_rect_in_safety,
)

Mode = Literal["balanced", "preserve_salience", "equal_grid"]
Density = Literal["auto", "comfortable", "compact"]
PreviewConfidence = Literal["captured", "host-estimate", "fallback"]
Provenance = Literal["wwt-import", "manual-board", "project-current"]

SEARCH_VISIT_CAP = 4096
MAX_SPAN_CANDIDATES = 6
BEAM_WIDTH = 64
FALLBACK_ASPECT = 16.0 / 9.0
CANONICAL_VIEWPORT = (1600, 900)
BALANCED_AREA_RATIO = 1.35
PRESERVE_AREA_RATIO = 1.80
_READING_FILL_TARGET = 0.82
_MATERIAL_FILL_EPS = 0.03
_ROW_OVERLAP_RATIO = 0.5
_ROW_CENTER_FACTOR = 0.5
_OVERLAP_EPS = 1e-6

_Score = tuple[int, int, int, int, int, int, int, tuple[tuple[int, int, int, int], ...]]


@dataclass(frozen=True)
class SmartLayoutPolicy:
    mode: Mode
    density: Density
    target_viewport: tuple[int, int]
    preserve_locked: bool = True


@dataclass(frozen=True)
class SmartCardFact:
    ref: UltraViewRef
    source_order: int
    source_row: int | None
    source_column: int | None
    source_salience: float | None
    preview_aspect: float | None
    preview_confidence: PreviewConfidence
    current_rect: GridRect | None
    locked_rect: GridRect | None


@dataclass(frozen=True)
class SmartLayoutResult:
    accepted: bool
    placements: tuple[tuple[UltraViewRef, GridRect], ...]
    reason: str | None
    diagnostics: tuple[str, ...]
    search_visits: int
    used_fallback: bool


@dataclass(frozen=True)
class SmartLayoutInputSnapshot:
    facts: tuple[SmartCardFact, ...]
    policy: SmartLayoutPolicy
    facts_digest: str
    provenance: Provenance


@dataclass(frozen=True)
class MaterialCardFitDelta:
    column_delta: int
    row_delta: int
    reading_fill_improvement: float


def facts_digest(facts: Sequence[SmartCardFact]) -> str:
    """Stable digest of semantic topology only: (ref, source_row, ordinal column)."""
    rows = [
        (
            fact.ref.section,
            fact.ref.view_id,
            None if fact.source_row is None else int(fact.source_row),
            None if fact.source_column is None else int(fact.source_column),
        )
        for fact in sorted(facts, key=lambda item: (item.ref.section, item.ref.view_id))
    ]
    payload = repr(rows).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def cluster_source_row_ids(
    bands: Sequence[tuple[float, float, int]],
) -> tuple[int, ...]:
    """D5: overlap-ratio + centerline clustering. Independent of input order."""
    count = len(bands)
    if count == 0:
        return ()
    parent = list(range(count))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left == root_right:
            return
        if bands[root_left][2] > bands[root_right][2]:
            root_left, root_right = root_right, root_left
        parent[root_right] = root_left

    def same_row(left: int, right: int) -> bool:
        top_l, bottom_l, _order_l = bands[left]
        top_r, bottom_r, _order_r = bands[right]
        height_l = bottom_l - top_l
        height_r = bottom_r - top_r
        if height_l <= _OVERLAP_EPS or height_r <= _OVERLAP_EPS:
            return False
        overlap = min(bottom_l, bottom_r) - max(top_l, top_r)
        if overlap <= _OVERLAP_EPS:
            return False
        min_height = min(height_l, height_r)
        if overlap / min_height < _ROW_OVERLAP_RATIO:
            return False
        center_l = 0.5 * (top_l + bottom_l)
        center_r = 0.5 * (top_r + bottom_r)
        return abs(center_l - center_r) <= (_ROW_CENTER_FACTOR * min_height)

    for index in range(count):
        for other in range(index + 1, count):
            if same_row(index, other):
                union(index, other)

    clusters: dict[int, list[int]] = {}
    for index in range(count):
        clusters.setdefault(find(index), []).append(index)
    ranked = sorted(
        clusters.values(),
        key=lambda members: (
            min(0.5 * (bands[index][0] + bands[index][1]) for index in members),
            min(bands[index][2] for index in members),
        ),
    )
    rows = [0] * count
    for row_id, members in enumerate(ranked):
        for index in members:
            rows[index] = row_id
    return tuple(rows)


def _placement_pairs(
    placements: Sequence[FreeGridPlacement | tuple[UltraViewRef, GridRect]],
) -> tuple[tuple[UltraViewRef, GridRect], ...]:
    pairs: list[tuple[UltraViewRef, GridRect]] = []
    for item in placements:
        if isinstance(item, FreeGridPlacement):
            pairs.append((item.ref, item.rect))
            continue
        if isinstance(item, tuple) and len(item) == 2:
            ref, rect = item
            pairs.append((ref, rect))
            continue
        ref = getattr(item, "ref", None)
        rect = getattr(item, "rect", None)
        if ref is None or rect is None:
            raise TypeError(f"unsupported placement item: {item!r}")
        pairs.append((ref, rect))
    return tuple(pairs)


def _looks_like_placement(item: object) -> bool:
    if isinstance(item, FreeGridPlacement):
        return True
    if isinstance(item, SmartCardFact):
        return False
    if isinstance(item, tuple) and len(item) == 2:
        ref, rect = item
        return isinstance(ref, UltraViewRef) and isinstance(rect, GridRect)
    return hasattr(item, "ref") and hasattr(item, "rect") and not hasattr(
        item, "source_order"
    )


def _preview_lookup(
    ref: UltraViewRef,
    preview_aspect: (
        Callable[[UltraViewRef], float | None]
        | Mapping[UltraViewRef, float | None]
        | None
    ),
) -> tuple[float | None, PreviewConfidence]:
    if preview_aspect is None:
        return None, "fallback"
    if callable(preview_aspect) and not isinstance(preview_aspect, Mapping):
        raw = preview_aspect(ref)
    else:
        try:
            raw = preview_aspect[ref]  # type: ignore[index]
        except (KeyError, TypeError):
            return None, "fallback"
    if raw is None:
        return None, "fallback"
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None, "fallback"
    if not math.isfinite(number) or number <= 0.0:
        return None, "fallback"
    return number, "host-estimate"


def _merge_continuation_rows(
    items: Sequence[tuple[UltraViewRef, GridRect, int]],
    row_ids: Sequence[int],
) -> list[int]:
    """D6: an overflow remainder immediately below a full row stays in that row."""
    merged = list(row_ids)
    if not items:
        return merged
    buckets: dict[int, list[int]] = {}
    for index, row_id in enumerate(merged):
        buckets.setdefault(row_id, []).append(index)

    def band_key(row_id: int) -> tuple[int, int]:
        members = buckets[row_id]
        min_row = min(items[index][1].row for index in members)
        min_order = min(items[index][2] for index in members)
        return (min_row, min_order)

    ordered_rows = sorted(buckets, key=band_key)
    alive = set(ordered_rows)
    for previous, current in zip(ordered_rows, ordered_rows[1:]):
        if previous not in alive or current not in alive:
            continue
        prev_members = buckets[previous]
        cur_members = buckets[current]
        if len(cur_members) >= len(prev_members):
            continue
        prev_bottom = max(
            items[index][1].row + items[index][1].row_span for index in prev_members
        )
        cur_top = min(items[index][1].row for index in cur_members)
        if cur_top != prev_bottom:
            continue
        rightmost = max(prev_members, key=lambda index: items[index][1].column)
        last = items[rightmost][1]
        first = items[min(cur_members, key=lambda index: items[index][1].column)][1]
        leftover = GRID_COLUMNS - (last.column + last.column_span)
        if leftover >= first.column_span:
            continue
        for index in cur_members:
            merged[index] = previous
        buckets[previous].extend(cur_members)
        del buckets[current]
        alive.discard(current)
    remapped: dict[int, int] = {}
    dense = [0] * len(merged)
    next_id = 0
    for index, row_id in enumerate(merged):
        # Dense ids in first-seen order after reading-order sort of items.
        if row_id not in remapped:
            remapped[row_id] = next_id
            next_id += 1
        dense[index] = remapped[row_id]
    # Re-rank by visual top so ids stay 0..n-1 in reading order.
    groups: dict[int, list[int]] = {}
    for index, row_id in enumerate(dense):
        groups.setdefault(row_id, []).append(index)
    ranked = sorted(
        groups,
        key=lambda row_id: (
            min(items[index][1].row for index in groups[row_id]),
            min(items[index][2] for index in groups[row_id]),
        ),
    )
    rank_of = {row_id: rank for rank, row_id in enumerate(ranked)}
    return [rank_of[row_id] for row_id in dense]


def smart_layout_facts_from_placements(
    placements: Sequence[FreeGridPlacement | tuple[UltraViewRef, GridRect]],
    *,
    preview_aspect: (
        Callable[[UltraViewRef], float | None]
        | Mapping[UltraViewRef, float | None]
        | None
    ) = None,
    locked_refs: Mapping[UltraViewRef, GridRect] | None = None,
    prior_facts: Sequence[SmartCardFact] | None = None,
) -> tuple[SmartCardFact, ...]:
    """Rebuild semantic facts from an already-laid Board.

    ``source_column`` is the 0..n-1 reading-order ordinal inside a semantic
    row band, never the absolute ``GridRect.column``.
    """
    pairs = _placement_pairs(placements)
    if not pairs:
        return ()
    prior_by_ref = {fact.ref: fact for fact in (prior_facts or ())}
    reading = sorted(
        pairs,
        key=lambda item: (
            item[1].row,
            item[1].column,
            item[0].section,
            item[0].view_id,
        ),
    )
    tagged = [
        (ref, rect, order) for order, (ref, rect) in enumerate(reading)
    ]
    bands = [
        (float(rect.row), float(rect.row + rect.row_span), order)
        for _ref, rect, order in tagged
    ]
    row_ids = list(cluster_source_row_ids(bands))
    if prior_facts:
        for index, (ref, _rect, _order) in enumerate(tagged):
            prior = prior_by_ref.get(ref)
            if prior is not None and prior.source_row is not None:
                row_ids[index] = int(prior.source_row)
    else:
        row_ids = _merge_continuation_rows(tagged, row_ids)

    members: dict[int, list[int]] = {}
    for index, row_id in enumerate(row_ids):
        members.setdefault(row_id, []).append(index)
    ordinal: dict[int, int] = {}
    for _row_id, indexes in members.items():
        ordered = sorted(
            indexes,
            key=lambda index: (
                tagged[index][1].row,
                tagged[index][1].column,
                tagged[index][0].section,
                tagged[index][0].view_id,
            ),
        )
        for column, index in enumerate(ordered):
            ordinal[index] = column

    facts: list[SmartCardFact] = []
    for index, (ref, rect, order) in enumerate(tagged):
        prior = prior_by_ref.get(ref)
        aspect, confidence = _preview_lookup(ref, preview_aspect)
        locked = None if locked_refs is None else locked_refs.get(ref)
        if prior is not None:
            if preview_aspect is None:
                aspect = prior.preview_aspect
                confidence = prior.preview_confidence
            if locked is None:
                locked = prior.locked_rect
            salience = prior.source_salience
            source_order = prior.source_order
        else:
            salience = None
            source_order = order
        if aspect is None:
            confidence = "fallback"
        facts.append(
            SmartCardFact(
                ref=ref,
                source_order=int(source_order),
                source_row=int(row_ids[index]),
                source_column=int(ordinal[index]),
                source_salience=salience,
                preview_aspect=aspect,
                preview_confidence=confidence,
                current_rect=rect,
                locked_rect=locked,
            )
        )
    facts.sort(key=lambda item: (item.source_order, item.ref.section, item.ref.view_id))
    return tuple(facts)


def canonicalize_smart_card_facts(
    snapshot_or_facts,
    *,
    placements=None,
):
    """Accept a snapshot, a facts sequence, or placements. Deterministic."""
    if isinstance(snapshot_or_facts, SmartLayoutInputSnapshot):
        facts = snapshot_or_facts.facts
        if placements is not None:
            facts = smart_layout_facts_from_placements(
                placements,
                prior_facts=facts,
            )
        return SmartLayoutInputSnapshot(
            facts=facts,
            policy=snapshot_or_facts.policy,
            facts_digest=facts_digest(facts),
            provenance=snapshot_or_facts.provenance,
        )
    seq = tuple(snapshot_or_facts or ())
    if seq and _looks_like_placement(seq[0]) and placements is None:
        return smart_layout_facts_from_placements(seq)
    facts = seq
    if placements is not None:
        facts = smart_layout_facts_from_placements(placements, prior_facts=facts)
    return facts


def material_card_fit_delta(
    rect: GridRect,
    preview_aspect: float | None,
    metrics: GridMetrics,
) -> MaterialCardFitDelta | None:
    """Read-only origin-pinned hug probe using canonical chrome 34 / 24 / 8."""
    aspect, used_fallback = _finite_aspect(preview_aspect)
    if used_fallback and preview_aspect is None:
        return None
    if used_fallback:
        return None
    plot = plot_size_for_rect(rect, metrics)
    if plot is None:
        return None
    hug = preferred_hug_span(rect, plot, aspect, metrics)
    if hug is None:
        return None
    hug_cs, hug_rs = int(hug[0]), int(hug[1])
    column_delta = hug_cs - int(rect.column_span)
    row_delta = hug_rs - int(rect.row_span)
    hug_rect = GridRect(int(rect.column), int(rect.row), hug_cs, hug_rs)
    current_fill = _contain_fill(rect.column_span, rect.row_span, aspect, metrics)
    hug_fill = _contain_fill(hug_cs, hug_rs, aspect, metrics)
    improvement = float(hug_fill) - float(current_fill)
    if not math.isfinite(improvement):
        improvement = 0.0
    return MaterialCardFitDelta(
        column_delta=int(column_delta),
        row_delta=int(row_delta),
        reading_fill_improvement=improvement,
    )


def _material_delta_is_noop(delta: MaterialCardFitDelta | None) -> bool:
    if delta is None:
        return True
    col = abs(int(delta.column_delta))
    row = abs(int(delta.row_delta))
    fill = float(delta.reading_fill_improvement)
    if col == 0 and row == 0:
        return True
    one_axis_micro = (col <= 1 and row == 0) or (row <= 1 and col == 0)
    return one_axis_micro and fill < _MATERIAL_FILL_EPS


@dataclass(frozen=True)
class _Work:
    fact: SmartCardFact
    aspect: float
    aspect_fallback: bool
    candidates: tuple[tuple[int, int], ...]
    locked: GridRect | None
    group_key: int | None
    target_area: float


def solve_smart_layout(
    facts: Sequence[SmartCardFact],
    policy: SmartLayoutPolicy,
    *,
    _validate_fixed_point: bool = True,
) -> SmartLayoutResult:
    """Solve a whole-board Smart Layout. Never mutates ``facts``."""
    diagnostics: list[str] = []
    items = tuple(facts)
    if not items:
        return _result(True, (), None, diagnostics, 0, False)

    refs = [item.ref for item in items]
    if len(set(refs)) != len(refs):
        return _result(False, (), "no_legal_layout:duplicate_ref", diagnostics, 0, False)

    frozen = tuple(
        sorted(items, key=lambda item: (item.source_order, item.ref.section, item.ref.view_id))
    )
    viewport, viewport_fallback = _freeze_viewport(policy.target_viewport)
    if viewport_fallback:
        diagnostics.append("target_viewport_fallback:1600x900")

    preserve_locked = bool(policy.preserve_locked)
    locked_pairs: list[tuple[UltraViewRef, GridRect]] = []
    for fact in frozen:
        if not preserve_locked or fact.locked_rect is None:
            continue
        locked = fact.locked_rect
        if not _legal_rect(locked):
            return _result(
                False, (), "no_legal_layout:locked_illegal", diagnostics, 0, False
            )
        locked_pairs.append((fact.ref, locked))
    for index, (_ref, left) in enumerate(locked_pairs):
        for _ref_b, right in locked_pairs[index + 1 :]:
            if rects_overlap(left, right):
                return _result(
                    False, (), "no_legal_layout:locked_overlap", diagnostics, 0, False
                )

    metrics = canonical_screen_metrics(())
    require_min = policy.density != "compact"
    min_w, min_h = _min_inner_reading_box(len(frozen), policy.density)
    aspects: list[float] = []
    aspect_flags: list[bool] = []
    for fact in frozen:
        aspect, used_aspect_fallback = _finite_aspect(fact.preview_aspect)
        aspects.append(aspect)
        aspect_flags.append(used_aspect_fallback)
        if used_aspect_fallback:
            diagnostics.append(
                f"preview_aspect_fallback:{fact.ref.section}:{fact.ref.view_id}"
            )

    density_area = _density_target_area(len(frozen), policy.density, min_w, min_h, metrics)
    shared_floor = _shared_area_floor(
        aspects,
        min_w,
        min_h,
        require_min,
        metrics,
    )
    mode = policy.mode
    works: list[_Work] = []
    for fact, aspect, used_aspect_fallback in zip(frozen, aspects, aspect_flags, strict=True):
        locked = fact.locked_rect if preserve_locked else None
        target = _card_target_area(
            mode,
            density_area,
            shared_floor,
            fact.source_salience,
        )
        if locked is not None:
            candidates: tuple[tuple[int, int], ...] = (
                (locked.column_span, locked.row_span),
            )
        else:
            candidates = _span_candidates(
                aspect,
                target,
                min_w,
                min_h,
                require_min,
                metrics,
                ratio=_ratio_cap(mode),
                current_rect=fact.current_rect,
            )
        works.append(
            _Work(
                fact=fact,
                aspect=aspect,
                aspect_fallback=used_aspect_fallback,
                candidates=candidates,
                locked=locked,
                group_key=fact.source_row,
                target_area=target,
            )
        )

    pack_order = _pack_order(works)
    occupied0 = [work.locked for work in works if work.locked is not None]
    best, visits, hit_cap = _beam_search(
        works,
        pack_order,
        occupied0,
        metrics,
        viewport,
        min_w,
        min_h,
        require_min,
        mode,
    )

    used_fallback = False
    if hit_cap:
        diagnostics.append("search_budget_fallback")
        used_fallback = True
        best = None
    if best is None:
        reduced_best = _greedy_pack(
            _with_reduced_candidates(works),
            pack_order,
            occupied0,
            metrics,
            viewport,
            min_w,
            min_h,
            require_min,
            mode,
        )
        if reduced_best is not None:
            best = reduced_best
        else:
            grid_best = _equal_grid_pack(
                works,
                pack_order,
                occupied0,
                metrics,
                viewport,
                min_w,
                min_h,
                require_min,
                mode,
            )
            if grid_best is not None:
                if hit_cap:
                    diagnostics.append("equal_grid_fallback")
                best = grid_best

    visits = min(SEARCH_VISIT_CAP, max(0, int(visits)))
    if best is None:
        return _result(
            False,
            (),
            "no_legal_layout",
            diagnostics,
            visits,
            used_fallback,
        )

    rects, _score = best
    placements = tuple((work.fact.ref, rects[index]) for index, work in enumerate(works))
    diagnostics.extend(_quality_diagnostics(works, rects, metrics))
    diagnostics.extend(_forced_gap_diagnostics(works, rects))
    leftover = _unlocked_captured_have_material_leftover(
        works, rects, metrics, min_w, min_h, require_min
    )
    if leftover:
        diagnostics.append("material_fit_leftover")
        return _result(
            False,
            (),
            "material_fit_failure",
            diagnostics,
            visits,
            used_fallback,
        )
    result = _result(True, placements, None, diagnostics, visits, used_fallback)
    if not _validate_fixed_point:
        return result
    canonical = canonicalize_smart_card_facts(frozen, placements=placements)
    probe = solve_smart_layout(
        canonical, policy, _validate_fixed_point=False
    )
    if not probe.accepted or probe.placements != result.placements:
        diagnostics = list(result.diagnostics) + ["fixed_point_failure"]
        return _result(
            False,
            (),
            "fixed_point_failure",
            diagnostics,
            visits,
            used_fallback,
        )
    return result


def _result(
    accepted: bool,
    placements: tuple[tuple[UltraViewRef, GridRect], ...],
    reason: str | None,
    diagnostics: Sequence[str],
    search_visits: int,
    used_fallback: bool,
) -> SmartLayoutResult:
    seen: list[str] = []
    for token in diagnostics:
        if token not in seen:
            seen.append(token)
    return SmartLayoutResult(
        accepted=accepted,
        placements=placements,
        reason=reason,
        diagnostics=tuple(seen),
        search_visits=int(search_visits),
        used_fallback=bool(used_fallback),
    )


def _freeze_viewport(raw: tuple[int, int]) -> tuple[tuple[int, int], bool]:
    try:
        width = float(raw[0])
        height = float(raw[1])
    except (TypeError, ValueError, IndexError):
        return CANONICAL_VIEWPORT, True
    if not math.isfinite(width) or not math.isfinite(height) or width <= 0.0 or height <= 0.0:
        return CANONICAL_VIEWPORT, True
    return (int(width), int(height)), False


def _is_finite_positive(value: float | None) -> bool:
    if value is None:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0.0


def _finite_aspect(value: float | None) -> tuple[float, bool]:
    if _is_finite_positive(value):
        return float(value), False
    return FALLBACK_ASPECT, True


def _min_inner_reading_box(count: int, density: str) -> tuple[int, int]:
    if density == "compact":
        return 1, 1
    if count <= 8:
        return 240, 135
    if count <= 12:
        return 200, 112
    return 176, 99


def _ratio_cap(mode: str) -> float:
    if mode == "preserve_salience":
        return PRESERVE_AREA_RATIO
    return BALANCED_AREA_RATIO


def _legal_rect(rect: GridRect | None) -> bool:
    if rect is None:
        return False
    values = (rect.column, rect.row, rect.column_span, rect.row_span)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        return False
    return grid_rect_in_safety(rect)


_INNER_CACHE: dict[tuple, tuple[int, int]] = {}
_FILL_CACHE: dict[tuple, float] = {}
_SPAN_CACHE: dict[tuple, tuple[tuple[int, int, int, int, float], ...]] = {}


def _inner_wh(cs: int, rs: int, metrics: GridMetrics) -> tuple[int, int]:
    key = (
        cs,
        rs,
        metrics.column_width,
        metrics.row_height,
        metrics.gutter,
        metrics.padding,
        metrics.resolution,
        round(float(metrics.scale), 6),
    )
    cached = _INNER_CACHE.get(key)
    if cached is not None:
        return cached
    box = inner_reading_box(GridRect(0, 0, cs, rs), metrics)
    value = (int(box[2]), int(box[3]))
    _INNER_CACHE[key] = value
    return value


def _contain_fill(cs: int, rs: int, aspect: float, metrics: GridMetrics) -> float:
    width, height = _inner_wh(cs, rs, metrics)
    if width <= 0 or height <= 0:
        return 0.0
    fill_key = (
        cs,
        rs,
        round(float(aspect), 8),
        metrics.column_width,
        metrics.row_height,
        metrics.gutter,
        metrics.padding,
        metrics.resolution,
        round(float(metrics.scale), 6),
    )
    cached = _FILL_CACHE.get(fill_key)
    if cached is not None:
        return cached
    box = inner_reading_box(GridRect(0, 0, cs, rs), metrics)
    preview = contained_preview_rect(box, (float(aspect), 1.0))
    fill = reading_fill(preview, box)
    if not math.isfinite(fill) or fill < 0.0:
        fill = 0.0
    else:
        fill = float(fill)
    _FILL_CACHE[fill_key] = fill
    return fill


def _legal_spans(min_w: int, min_h: int, require_min: bool, metrics: GridMetrics):
    key = (
        min_w,
        min_h,
        require_min,
        metrics.column_width,
        metrics.row_height,
        metrics.gutter,
        metrics.padding,
        metrics.resolution,
        round(float(metrics.scale), 6),
    )
    cached = _SPAN_CACHE.get(key)
    if cached is not None:
        return cached
    spans: list[tuple[int, int, int, int, float]] = []
    for cs in range(GRID_MIN_COLUMN_SPAN, GRID_MAX_COLUMN_SPAN + 1):
        for rs in range(GRID_MIN_ROW_SPAN, GRID_MAX_ROW_SPAN + 1):
            if not grid_rect_in_safety(GridRect(0, 0, cs, rs)):
                continue
            width, height = _inner_wh(cs, rs, metrics)
            if width <= 0 or height <= 0:
                continue
            if require_min and (width < min_w or height < min_h):
                continue
            spans.append((cs, rs, width, height, float(width * height)))
    stored = tuple(spans)
    _SPAN_CACHE[key] = stored
    return stored


def _density_target_area(
    count: int,
    density: str,
    min_w: int,
    min_h: int,
    metrics: GridMetrics,
) -> float:
    min_area = float(max(1, min_w) * max(1, min_h))
    area_6x6 = float(_inner_wh(6, 6, metrics)[0] * _inner_wh(6, 6, metrics)[1])
    area_4x5 = float(_inner_wh(4, 5, metrics)[0] * _inner_wh(4, 5, metrics)[1])
    area_5x6 = float(_inner_wh(5, 6, metrics)[0] * _inner_wh(5, 6, metrics)[1])
    if density == "compact":
        return min_area
    if density == "comfortable":
        if count <= 8:
            return max(min_area * 2.0, area_6x6)
        if count <= 12:
            return max(min_area * 1.6, area_5x6)
        return max(min_area * 1.2, area_4x5)
    if count <= 8:
        return max(min_area, area_6x6)
    if count <= 12:
        return max(min_area, area_5x6)
    return max(min_area, area_4x5)


def _shared_area_floor(
    aspects: Sequence[float],
    min_w: int,
    min_h: int,
    require_min: bool,
    metrics: GridMetrics,
) -> float:
    spans = _legal_spans(min_w, min_h, require_min, metrics)
    if not spans:
        return 1.0
    floors: list[float] = []
    for aspect in aspects:
        filled = [
            area
            for cs, rs, _w, _h, area in spans
            if _contain_fill(cs, rs, aspect, metrics) >= _READING_FILL_TARGET
        ]
        if filled:
            floors.append(min(filled))
            continue
        floors.append(min(area for _cs, _rs, _w, _h, area in spans))
    floor = max(floors) if floors else 1.0
    return float(floor)


def _card_target_area(
    mode: str,
    density_area: float,
    shared_floor: float,
    salience: float | None,
) -> float:
    base = max(float(density_area), float(shared_floor))
    if mode != "preserve_salience":
        return base
    scale = 1.0
    if salience is not None and _is_finite_positive(salience):
        scale = min(PRESERVE_AREA_RATIO, max(0.75, float(salience)))
    return base * scale


def _hug_span_from(
    aspect: float,
    current: GridRect,
    metrics: GridMetrics,
) -> tuple[int, int] | None:
    plot = plot_size_for_rect(current, metrics)
    if plot is None:
        return None
    hug = preferred_hug_span(current, plot, aspect, metrics)
    if hug is None:
        return None
    return int(hug[0]), int(hug[1])


def _span_candidates(
    aspect: float,
    target_area: float,
    min_w: int,
    min_h: int,
    require_min: bool,
    metrics: GridMetrics,
    *,
    ratio: float,
    current_rect: GridRect | None = None,
) -> tuple[tuple[int, int], ...]:
    spans = _legal_spans(min_w, min_h, require_min, metrics)
    if not spans:
        return ((GRID_MIN_COLUMN_SPAN, GRID_MIN_ROW_SPAN),)
    legal_set = {(item[0], item[1]) for item in spans}
    lo = target_area / max(ratio, 1.0)
    hi = target_area * max(ratio, 1.0)
    band = [item for item in spans if lo <= item[4] <= hi]
    if not band:
        band = list(spans)

    def rank(item: tuple[int, int, int, int, float]) -> tuple[int, int, int, int]:
        cs, rs, _w, _h, area = item
        unused = 1.0 - _contain_fill(cs, rs, aspect, metrics)
        return (_q(unused), _q(abs(area - target_area)), cs, rs)

    by_key = {(item[0], item[1]): item for item in spans}
    band_rank = {(item[0], item[1]): rank(item) for item in band}
    primary = min(band, key=rank)
    density_key = (primary[0], primary[1])
    density_virtual = GridRect(0, 0, density_key[0], density_key[1])
    density_hug = _hug_span_from(aspect, density_virtual, metrics)
    if density_hug is not None and density_hug not in legal_set:
        density_hug = None
    current_key = None
    current_hug = None
    if current_rect is not None:
        current_key = (int(current_rect.column_span), int(current_rect.row_span))
        if current_key not in legal_set:
            current_key = None
        current_hug = _hug_span_from(aspect, current_rect, metrics)
        if current_hug is not None and current_hug not in legal_set:
            current_hug = None

    pinned: list[tuple[int, int]] = []
    for key in (density_hug, current_hug, current_key, density_key):
        if key is None or key in pinned:
            continue
        pinned.append(key)

    # Adjacent quantized spans around the density hug so the neighborhood
    # does not drift when current_rect is filled in after the first solve.
    center = density_hug if density_hug is not None else density_key
    adjacent: list[tuple[int, int]] = []
    for distance in range(1, 3):
        ring = [
            key
            for key in legal_set
            if abs(key[0] - center[0]) + abs(key[1] - center[1]) == distance
        ]
        ring.sort(key=lambda key: (band_rank.get(key, rank(by_key[key])), key))
        for key in ring:
            if key not in pinned and key not in adjacent:
                adjacent.append(key)

    density_ring: list[tuple[int, int]] = []
    pcs, prs = density_key
    for distance in range(0, GRID_MAX_COLUMN_SPAN + GRID_MAX_ROW_SPAN + 1):
        ring = [
            key
            for key in band_rank
            if abs(key[0] - pcs) + abs(key[1] - prs) == distance
        ]
        ring.sort(key=lambda key: (band_rank[key], key))
        for key in ring:
            if key not in pinned and key not in adjacent and key not in density_ring:
                density_ring.append(key)

    chosen: list[tuple[int, int]] = list(pinned)
    for key in adjacent + density_ring:
        if key in chosen:
            continue
        chosen.append(key)
        if len(chosen) >= MAX_SPAN_CANDIDATES:
            break
    # Density hug must survive the cap: pinned prefix is never dropped.
    hug_key = density_hug if density_hug is not None else current_hug
    if hug_key is not None and hug_key not in chosen[:MAX_SPAN_CANDIDATES]:
        chosen = [hug_key] + [key for key in chosen if key != hug_key]
    rest = chosen[len(pinned):]
    rest.sort(key=lambda key: (band_rank.get(key, rank(by_key[key])), key))
    ordered = list(pinned) + rest
    return tuple(ordered[:MAX_SPAN_CANDIDATES])


def _pack_order(works: Sequence[_Work]) -> tuple[int, ...]:
    groups: dict[int | None, list[int]] = {}
    for index, work in enumerate(works):
        groups.setdefault(work.group_key, []).append(index)
    keys = sorted(groups, key=lambda key: (key is None, key if key is not None else 0))
    order: list[int] = []
    for key in keys:
        order.extend(groups[key])
    return tuple(order)


def _fits(rect: GridRect, occupied: Sequence[GridRect]) -> bool:
    if not _legal_rect(rect):
        return False
    if rect.column < 0 or rect.column + rect.column_span > GRID_COLUMNS:
        return False
    if rect.row < 0 or rect.row + rect.row_span > SAFETY_ROW_MAX:
        return False
    for other in occupied:
        if rects_overlap(rect, other):
            return False
    return True


def _place_after(
    cs: int,
    rs: int,
    last: GridRect | None,
    occupied: Sequence[GridRect],
    origin_row: int,
) -> GridRect | None:
    best: GridRect | None = None
    for column in range(0, GRID_COLUMNS - cs + 1):
        row = max(0, int(origin_row))
        for other in occupied:
            if other.column < column + cs and column < other.column + other.column_span:
                row = max(row, other.row + other.row_span)
        if last is not None:
            if row < last.row:
                row = last.row
            if row == last.row and column < last.column + last.column_span:
                row = last.row + last.row_span
                for other in occupied:
                    if other.column < column + cs and column < other.column + other.column_span:
                        row = max(row, other.row + other.row_span)
                if row < last.row + last.row_span:
                    row = last.row + last.row_span
        rect = GridRect(column, row, cs, rs)
        if not _fits(rect, occupied):
            continue
        key = (rect.row, rect.column)
        if best is None or key < (best.row, best.column):
            best = rect
    return best


def _packed_origin(
    rects: Sequence[GridRect | None],
    pack_order: Sequence[int],
    step: int,
) -> int:
    bottoms = [
        rects[index].row + rects[index].row_span
        for index in pack_order[:step]
        if rects[index] is not None
    ]
    return max(bottoms) if bottoms else 0


def _beam_search(
    works: Sequence[_Work],
    pack_order: Sequence[int],
    occupied0: Sequence[GridRect],
    metrics: GridMetrics,
    viewport: tuple[int, int],
    min_w: int,
    min_h: int,
    require_min: bool,
    mode: str,
) -> tuple[tuple[tuple[GridRect, ...], _Score] | None, int, bool]:
    n = len(works)
    empty: list[GridRect | None] = [None] * n
    beam: list[tuple[list[GridRect | None], list[GridRect], GridRect | None, int]] = [
        (list(empty), list(occupied0), None, 0)
    ]
    visits = 0
    hit_cap = False
    best: tuple[tuple[GridRect, ...], _Score] | None = None
    for step, index in enumerate(pack_order):
        work = works[index]
        group_key = work.group_key
        next_beam: list[
            tuple[tuple, list[GridRect | None], list[GridRect], GridRect | None, int]
        ] = []
        for rects, occupied, last, origin_row in beam:
            if step == 0 or works[pack_order[step - 1]].group_key != group_key:
                last = None
                origin_row = _packed_origin(rects, pack_order, step)
            if work.locked is not None:
                visits += 1
                if visits >= SEARCH_VISIT_CAP:
                    hit_cap = True
                    break
                locked = work.locked
                if last is not None and (locked.row, locked.column) < (last.row, last.column):
                    continue
                placed = list(rects)
                placed[index] = locked
                next_beam.append(
                    (
                        _partial_rank(works, placed, pack_order[: step + 1], metrics),
                        placed,
                        occupied,
                        locked,
                        origin_row,
                    )
                )
                continue
            for cs, rs in work.candidates:
                visits += 1
                if visits >= SEARCH_VISIT_CAP:
                    hit_cap = True
                    break
                rect = _place_after(cs, rs, last, occupied, origin_row)
                if rect is None:
                    continue
                placed = list(rects)
                placed[index] = rect
                next_occupied = occupied + [rect]
                next_beam.append(
                    (
                        _partial_rank(works, placed, pack_order[: step + 1], metrics),
                        placed,
                        next_occupied,
                        rect,
                        origin_row,
                    )
                )
            if hit_cap:
                break
        if hit_cap:
            break
        next_beam.sort(key=lambda item: item[0])
        trimmed = next_beam[:BEAM_WIDTH]
        beam = [(rects, occupied, last, origin_row) for _key, rects, occupied, last, origin_row in trimmed]
        if not beam:
            break

    if not hit_cap:
        for rects, _occupied, _last, _origin in beam:
            if any(rects[index] is None for index in range(n)):
                continue
            placed = tuple(rects[index] for index in range(n))  # type: ignore[misc]
            evaluated = _evaluate(
                works,
                placed,
                metrics,
                viewport,
                min_w,
                min_h,
                require_min,
                mode,
            )
            if evaluated is None:
                continue
            if best is None or evaluated[1] < best[1]:
                best = evaluated
    return best, visits, hit_cap


def _partial_rank(
    works: Sequence[_Work],
    rects: Sequence[GridRect | None],
    prefix: Sequence[int],
    metrics: GridMetrics,
) -> tuple:
    unused = 0.0
    area_dev = 0.0
    values: list[int] = []
    for index in prefix:
        rect = rects[index]
        if rect is None:
            unused += 1.0
            area_dev += 10**9
            values.extend((10**6, 10**6, 0, 0))
            continue
        fill = _contain_fill(rect.column_span, rect.row_span, works[index].aspect, metrics)
        unused += max(0.0, 1.0 - fill)
        width, height = _inner_wh(rect.column_span, rect.row_span, metrics)
        area_dev += abs(float(width * height) - works[index].target_area)
        values.extend((rect.row, rect.column, rect.column_span, rect.row_span))
    return (_q(unused), _q(area_dev), tuple(values))


def _greedy_pack(
    works: Sequence[_Work],
    pack_order: Sequence[int],
    occupied0: Sequence[GridRect],
    metrics: GridMetrics,
    viewport: tuple[int, int],
    min_w: int,
    min_h: int,
    require_min: bool,
    mode: str,
) -> tuple[tuple[GridRect, ...], _Score] | None:
    n = len(works)
    rects: list[GridRect | None] = [None] * n
    occupied = list(occupied0)
    last: GridRect | None = None
    origin_row = 0
    prev_group: object = object()
    for step, index in enumerate(pack_order):
        work = works[index]
        if work.group_key != prev_group:
            last = None
            origin_row = _packed_origin(rects, pack_order, step)
            prev_group = work.group_key
        if work.locked is not None:
            locked = work.locked
            if last is not None and (locked.row, locked.column) < (last.row, last.column):
                return None
            rects[index] = locked
            last = locked
            continue
        placed_rect: GridRect | None = None
        for cs, rs in work.candidates:
            rect = _place_after(cs, rs, last, occupied, origin_row)
            if rect is not None:
                placed_rect = rect
                break
        if placed_rect is None:
            return None
        rects[index] = placed_rect
        occupied.append(placed_rect)
        last = placed_rect
    if any(rect is None for rect in rects):
        return None
    placed = tuple(rects)  # type: ignore[arg-type]
    return _evaluate(works, placed, metrics, viewport, min_w, min_h, require_min, mode)


def _with_reduced_candidates(works: Sequence[_Work]) -> tuple[_Work, ...]:
    reduced: list[_Work] = []
    for work in works:
        if work.locked is not None:
            reduced.append(work)
            continue
        reduced.append(
            _Work(
                fact=work.fact,
                aspect=work.aspect,
                aspect_fallback=work.aspect_fallback,
                candidates=work.candidates[:2] or work.candidates,
                locked=work.locked,
                group_key=work.group_key,
                target_area=work.target_area,
            )
        )
    return tuple(reduced)


def _equal_grid_pack(
    works: Sequence[_Work],
    pack_order: Sequence[int],
    occupied0: Sequence[GridRect],
    metrics: GridMetrics,
    viewport: tuple[int, int],
    min_w: int,
    min_h: int,
    require_min: bool,
    mode: str,
) -> tuple[tuple[GridRect, ...], _Score] | None:
    landscape, portrait = _equal_grid_spans(min_w, min_h, require_min, metrics)
    equalized: list[_Work] = []
    for work in works:
        if work.locked is not None:
            equalized.append(work)
            continue
        span = landscape if work.aspect >= 1.0 else portrait
        virtual = GridRect(0, 0, span[0], span[1])
        hug = _hug_span_from(work.aspect, virtual, metrics)
        candidates: list[tuple[int, int]] = []
        if hug is not None and hug != span:
            candidates.append(hug)
        candidates.append(span)
        equalized.append(
            _Work(
                fact=work.fact,
                aspect=work.aspect,
                aspect_fallback=work.aspect_fallback,
                candidates=tuple(candidates),
                locked=work.locked,
                group_key=work.group_key,
                target_area=work.target_area,
            )
        )
    return _greedy_pack(
        equalized,
        pack_order,
        occupied0,
        metrics,
        viewport,
        min_w,
        min_h,
        require_min,
        mode,
    )


def _equal_grid_spans(
    min_w: int,
    min_h: int,
    require_min: bool,
    metrics: GridMetrics,
) -> tuple[tuple[int, int], tuple[int, int]]:
    spans = _legal_spans(min_w, min_h, require_min, metrics)
    if not spans:
        fallback = (GRID_MIN_COLUMN_SPAN, GRID_MIN_ROW_SPAN)
        return fallback, fallback

    def pick(aspect: float) -> tuple[int, int]:
        ranked = sorted(
            spans,
            key=lambda item: (
                _q(1.0 - _contain_fill(item[0], item[1], aspect, metrics)),
                -max(1, GRID_COLUMNS // max(1, item[0])),
                item[0],
                item[1],
            ),
        )
        return (ranked[0][0], ranked[0][1])

    return pick(FALLBACK_ASPECT), pick(9.0 / 16.0)


def _compact_normalize(
    works: Sequence[_Work],
    rects: Sequence[GridRect],
) -> tuple[GridRect, ...] | None:
    """Topology-preserving left-pack of already chosen spans (UFP-06)."""
    pack_order = _pack_order(works)
    n = len(works)
    out: list[GridRect | None] = [None] * n
    occupied: list[GridRect] = []
    for index, work in enumerate(works):
        if work.locked is not None:
            out[index] = work.locked
            occupied.append(work.locked)
    last: GridRect | None = None
    origin_row = 0
    prev_group: object = object()
    for step, index in enumerate(pack_order):
        work = works[index]
        if work.group_key != prev_group:
            last = None
            origin_row = _packed_origin(out, pack_order, step)
            prev_group = work.group_key
        if work.locked is not None:
            last = work.locked
            continue
        placed = _place_after(
            int(rects[index].column_span),
            int(rects[index].row_span),
            last,
            occupied,
            origin_row,
        )
        if placed is None:
            return None
        out[index] = placed
        occupied.append(placed)
        last = placed
    if any(item is None for item in out):
        return None
    return tuple(out)  # type: ignore[arg-type]


def _forced_gap_diagnostics(
    works: Sequence[_Work],
    rects: Sequence[GridRect],
) -> tuple[str, ...]:
    locked = [work.locked for work in works if work.locked is not None]
    buckets: dict[tuple[int | None, int], list[GridRect]] = {}
    for work, rect in zip(works, rects, strict=True):
        if work.locked is not None:
            continue
        buckets.setdefault((work.group_key, int(rect.row)), []).append(rect)
    tokens: list[str] = []
    for _key, row_rects in buckets.items():
        ordered = sorted(row_rects, key=lambda item: int(item.column))
        for left, right in zip(ordered, ordered[1:]):
            gap_start = int(left.column + left.column_span)
            gap_end = int(right.column)
            if gap_end <= gap_start:
                continue
            forced = any(
                lock.row <= left.row < lock.row + lock.row_span
                and lock.column < gap_end
                and lock.column + lock.column_span > gap_start
                for lock in locked
            )
            tokens.append("forced_gap" if forced else "unforced_gap")
    return tuple(tokens)


def _unlocked_captured_have_material_leftover(
    works: Sequence[_Work],
    rects: Sequence[GridRect],
    metrics: GridMetrics,
    min_w: int,
    min_h: int,
    require_min: bool,
) -> bool:
    legal = {
        (item[0], item[1])
        for item in _legal_spans(min_w, min_h, require_min, metrics)
    }
    for work, rect in zip(works, rects, strict=True):
        if work.locked is not None:
            continue
        if work.fact.preview_confidence != "captured" or work.aspect_fallback:
            continue
        delta = material_card_fit_delta(rect, work.aspect, metrics)
        if _material_delta_is_noop(delta):
            continue
        hug = (
            int(rect.column_span) + int(delta.column_delta),
            int(rect.row_span) + int(delta.row_delta),
        )
        if hug not in legal:
            continue
        return True
    return False


def _evaluate(
    works: Sequence[_Work],
    rects: Sequence[GridRect],
    metrics: GridMetrics,
    viewport: tuple[int, int],
    min_w: int,
    min_h: int,
    require_min: bool,
    mode: str,
) -> tuple[tuple[GridRect, ...], _Score] | None:
    placed = tuple(rects)
    if len(placed) != len(works):
        return None
    compacted = _compact_normalize(works, placed)
    if compacted is None:
        return None
    placed = compacted
    if not _hard_constraints(works, placed, metrics, min_w, min_h, require_min, mode):
        return None
    if _unlocked_captured_have_material_leftover(
        works, placed, metrics, min_w, min_h, require_min
    ):
        return None
    score = _score_vector(works, placed, metrics, viewport, min_w, min_h, mode)
    return placed, score


def _hard_constraints(
    works: Sequence[_Work],
    rects: Sequence[GridRect],
    metrics: GridMetrics,
    min_w: int,
    min_h: int,
    require_min: bool,
    mode: str,
) -> bool:
    for rect in rects:
        if not _legal_rect(rect):
            return False
    for index, left in enumerate(rects):
        for right in rects[index + 1 :]:
            if rects_overlap(left, right):
                return False
    for work, rect in zip(works, rects, strict=True):
        if work.locked is not None and rect != work.locked:
            return False
        if require_min:
            _x, _y, width, height = inner_reading_box(rect, metrics)
            if width < min_w or height < min_h:
                return False
    grouped: dict[int | None, list[tuple[int, GridRect]]] = {}
    for work, rect in zip(works, rects, strict=True):
        grouped.setdefault(work.group_key, []).append((work.fact.source_order, rect))
    for items in grouped.values():
        items.sort(key=lambda item: (item[1].row, item[1].column))
        orders = [item[0] for item in items]
        if orders != sorted(orders):
            return False
        rows = [item[1] for item in items]
        for prev, current in zip(rows, rows[1:]):
            if current.row > prev.row and current.row > prev.row + prev.row_span:
                # Continuation must sit on or immediately below some earlier card
                # of this group; allow chain of adjacent continuation rows.
                adjacent = any(
                    current.row == other.row + other.row_span for other in rows if other.row <= prev.row
                )
                if not adjacent and current.row != prev.row + prev.row_span:
                    return False
    if mode == "balanced":
        areas = []
        for rect in rects:
            _x, _y, width, height = inner_reading_box(rect, metrics)
            areas.append(width * height)
        if areas and min(areas) > 0 and max(areas) / min(areas) > BALANCED_AREA_RATIO + 1e-9:
            return False
    return True


def _score_vector(
    works: Sequence[_Work],
    rects: Sequence[GridRect],
    metrics: GridMetrics,
    viewport: tuple[int, int],
    min_w: int,
    min_h: int,
    mode: str,
) -> _Score:
    placements = tuple(FreeGridPlacement(work.fact.ref, rect) for work, rect in zip(works, rects, strict=True))
    layout_metrics = canonical_screen_metrics(placements)
    union = union_grid_rect(rects)
    if union is None:
        union_w = union_h = 1
    else:
        _x, _y, union_w, union_h = rect_to_pixels(union, layout_metrics)
        union_w = max(1, union_w)
        union_h = max(1, union_h)
    view_w, view_h = float(viewport[0]), float(viewport[1])
    scale = min(view_w / float(union_w), view_h / float(union_h))
    fit_scale = min(1.0, max(0.0, scale))
    deficit = 0.0
    unused_sum = 0.0
    area_dev = 0.0
    salience_dev = 0.0
    movement = 0
    outer_sum = 0
    areas: list[float] = []
    for work, rect in zip(works, rects, strict=True):
        box = inner_reading_box(rect, layout_metrics)
        width, height = int(box[2]), int(box[3])
        fitted_w = width * fit_scale
        fitted_h = height * fit_scale
        deficit += max(0.0, min_w - fitted_w) ** 2 + max(0.0, min_h - fitted_h) ** 2
        preview = contained_preview_rect(box, (work.aspect, 1.0))
        fill = reading_fill(preview, box)
        unused_sum += max(0.0, 1.0 - (fill if math.isfinite(fill) else 0.0))
        area = float(max(0, width) * max(0, height))
        areas.append(area)
        area_dev += abs(area - work.target_area)
        if mode == "preserve_salience":
            salience_dev += abs(area - work.target_area)
        elif mode == "equal_grid":
            salience_dev += 0.0
        else:
            salience_dev += 0.0
        current = work.fact.current_rect
        if current is not None:
            movement += (
                abs(rect.column - current.column)
                + abs(rect.row - current.row)
                + abs(rect.column_span - current.column_span)
                + abs(rect.row_span - current.row_span)
            )
        _ox, _oy, ow, oh = rect_to_pixels(rect, layout_metrics)
        outer_sum += max(0, ow) * max(0, oh)
    if mode == "equal_grid" and areas:
        mean = sum(areas) / float(len(areas))
        salience_dev = sum(abs(area - mean) for area in areas)
    elif mode == "balanced" and areas:
        mean = sum(areas) / float(len(areas))
        salience_dev = sum(abs(area - mean) for area in areas)
    whitespace = 1.0 - (float(outer_sum) / float(max(1, union_w * union_h)))
    union_aspect = float(union_w) / float(union_h)
    view_aspect = view_w / max(view_h, 1.0)
    aspect_err = abs(union_aspect - view_aspect)
    topology = _topology_penalty(works, rects)
    serialized = tuple(
        (rect.column, rect.row, rect.column_span, rect.row_span) for rect in rects
    )
    return (
        _q(deficit),
        int(topology),
        _q(area_dev),
        _q(unused_sum),
        _q(whitespace) + _q(aspect_err),
        _q(salience_dev),
        int(movement),
        serialized,
    )


def _topology_penalty(works: Sequence[_Work], rects: Sequence[GridRect]) -> int:
    grouped: dict[int | None, list[GridRect]] = {}
    order: list[int | None] = []
    for work, rect in zip(works, rects, strict=True):
        if work.group_key not in grouped:
            order.append(work.group_key)
        grouped.setdefault(work.group_key, []).append(rect)
    continuations = 0
    breaks = 0
    prev_min: int | None = None
    prev_max: int | None = None
    for key in order:
        items = grouped[key]
        visual_rows = sorted({rect.row for rect in items})
        continuations += max(0, len(visual_rows) - 1)
        gmin = min(rect.row for rect in items)
        gmax = max(rect.row + rect.row_span for rect in items)
        if prev_max is not None and gmin < prev_max:
            breaks += 1
        if prev_min is not None and gmin < prev_min:
            breaks += 2
        prev_min, prev_max = gmin, gmax
    return breaks * 100 + continuations


def _quality_diagnostics(
    works: Sequence[_Work],
    rects: Sequence[GridRect],
    metrics: GridMetrics,
) -> tuple[str, ...]:
    tokens: list[str] = []
    placements = tuple(FreeGridPlacement(work.fact.ref, rect) for work, rect in zip(works, rects, strict=True))
    layout_metrics = canonical_screen_metrics(placements)
    for work, rect in zip(works, rects, strict=True):
        if work.fact.preview_confidence != "captured" or work.aspect_fallback:
            continue
        box = inner_reading_box(rect, layout_metrics)
        preview = contained_preview_rect(box, (work.aspect, 1.0))
        fill = reading_fill(preview, box)
        if not math.isfinite(fill) or fill < _READING_FILL_TARGET:
            tokens.append("reading_fill_below_0.82")
            break
    return tuple(tokens)


def _q(value: float) -> int:
    if not math.isfinite(value):
        return 10**12
    return int(round(float(value) * 1000.0))
