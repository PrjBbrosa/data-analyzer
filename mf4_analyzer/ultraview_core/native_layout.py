"""Qt-free native millimetre layout → UltraView free-grid plan.

WWT millimetre rects are semantic topology facts (source order / row /
column / compressed salience). Smart Layout chooses the final ``GridRect``s.
Planner 1× pitch is canonical 1600-wide screen metrics, not a 96px dummy.
Exact-overlap later views inherit the covered window's ``source_row`` and
stack as a continuation; they are not Manhattan-relocated upward.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .grid_geometry import GridMetrics, canonical_screen_metrics
from .model import GridRect, UltraViewRef
from .smart_layout import (
    SmartCardFact,
    SmartLayoutPolicy,
    cluster_source_row_ids,
    solve_smart_layout,
)

_OVERLAP_EPS = 1e-6
# Pairwise same-row: overlap vs the shorter band, plus close centerlines so a
# tall bridge cannot chain-merge two separated rows (spec §10 D5).
_ROW_OVERLAP_RATIO = 0.5
_ROW_CENTER_FACTOR = 0.5
_DEFAULT_TARGET_VIEWPORT = (1200, 750)
_DEFAULT_NATIVE_POLICY = SmartLayoutPolicy(
    mode="balanced",
    density="auto",
    target_viewport=_DEFAULT_TARGET_VIEWPORT,
    preserve_locked=True,
)


@dataclass(frozen=True)
class NativeLayoutRect:
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class NativeLayoutPlan:
    placed: tuple[tuple[UltraViewRef, GridRect], ...]
    unplaced: tuple[UltraViewRef, ...]
    warnings: tuple[str, ...]
    sources: tuple[tuple[UltraViewRef, NativeLayoutRect], ...] = ()
    relocated: tuple[UltraViewRef, ...] = ()
    facts: tuple[SmartCardFact, ...] = ()


@dataclass(frozen=True)
class NativeLayoutProjection:
    """Board-final placement counts for one native-layout apply.

    Unpacks as ``(placed_view_ids, warnings)`` so existing tests and the
    WWT import seam keep working. ``unplaced_ids`` are generated Views that
    landed in the tray; ids in ``generated_ids`` that are in neither placed
    nor unplaced are unprojected (cap), not unplaced.
    """

    placed_view_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    board_id: str = ""
    generated_ids: tuple[str, ...] = ()
    unplaced_ids: tuple[str, ...] = ()

    def __iter__(self):
        yield self.placed_view_ids
        yield self.warnings

    def __getitem__(self, index):
        return (self.placed_view_ids, self.warnings)[index]

    def __len__(self):
        return 2


@dataclass(frozen=True)
class _Item:
    ref: UltraViewRef
    rect: NativeLayoutRect
    source_order: int
    top: float
    bottom: float
    duplicate_of: int | None = None


# Native-layout codes that are not a degraded import by themselves.
# WWT import grading and UltraView leftover-toast filters share this set so
# ``exact_overlap_relocated`` cannot drift between owners.
NATIVE_LAYOUT_NON_DEGRADED_CODES = frozenset({
    "exact_overlap",
    "exact_overlap_relocated",
    "quantized_collision",
    "duplicate_ref",
    "invalid_rect",
})


def is_native_layout_non_degraded(
    code: str,
    *,
    unplaced_count: int = 0,
    unprojected_count: int = 0,
) -> bool:
    """True when ``code`` is a layout success/internal note, not user loss.

    ``quantized_collision`` stays silent as a code; unplaced is reported by
    structured placement counts. ``invalid_rect`` is silent only when nothing
    was left unplaced or unprojected.
    """
    token = str(code or "").split(":", 1)[0].strip()
    if token not in NATIVE_LAYOUT_NON_DEGRADED_CODES:
        return False
    if token == "invalid_rect":
        return int(unplaced_count or 0) == 0 and int(unprojected_count or 0) == 0
    return True


def generated_ids_from_plan(plan) -> tuple[str, ...]:
    ids: list[str] = []
    seen: set[str] = set()
    for ref, _rect in getattr(plan, "placed", ()) or ():
        vid = str(getattr(ref, "view_id", "") or "")
        if vid and vid not in seen:
            seen.add(vid)
            ids.append(vid)
    for ref in getattr(plan, "unplaced", ()) or ():
        vid = str(getattr(ref, "view_id", "") or "")
        if vid and vid not in seen:
            seen.add(vid)
            ids.append(vid)
    return tuple(ids)


def _edges_equal(left: NativeLayoutRect, right: NativeLayoutRect) -> bool:
    return (
        abs(left.x - right.x) <= _OVERLAP_EPS
        and abs(left.y - right.y) <= _OVERLAP_EPS
        and abs(left.width - right.width) <= _OVERLAP_EPS
        and abs(left.height - right.height) <= _OVERLAP_EPS
    )


def _valid_rect(rect: NativeLayoutRect) -> bool:
    return (
        all(
            isinstance(value, (int, float)) and float(value) == float(value)
            and abs(float(value)) != float("inf")
            for value in (rect.x, rect.y, rect.width, rect.height)
        )
        and rect.width > 0.0
        and rect.height > 0.0
    )


def _winwert_top(rect: NativeLayoutRect) -> float:
    return float(rect.y) - float(rect.height)


def _winwert_bottom(rect: NativeLayoutRect) -> float:
    return float(rect.y)


def _item_height(item: _Item) -> float:
    return item.bottom - item.top


def _item_center(item: _Item) -> float:
    return 0.5 * (item.top + item.bottom)


def _same_source_row(left: _Item, right: _Item) -> bool:
    """True when two unique windows share a stable visual row (spec §10 D5).

    Overlap ratio is against the shorter band. Centerlines must also be close
    relative to that shorter height, so a tall bridge that merely overlaps A
    and C does not union A with C.
    """
    height_left = _item_height(left)
    height_right = _item_height(right)
    if height_left <= _OVERLAP_EPS or height_right <= _OVERLAP_EPS:
        return False
    overlap = min(left.bottom, right.bottom) - max(left.top, right.top)
    if overlap <= _OVERLAP_EPS:
        return False
    min_height = min(height_left, height_right)
    if overlap / min_height < _ROW_OVERLAP_RATIO:
        return False
    return abs(_item_center(left) - _item_center(right)) <= (
        _ROW_CENTER_FACTOR * min_height
    )


def _cluster_source_rows(unique: Sequence[_Item]) -> list[int]:
    """Assign dense ``source_row`` ids. Independent of ``unique`` list order."""
    bands = tuple(
        (item.top, item.bottom, item.source_order) for item in unique
    )
    return list(cluster_source_row_ids(bands))


def _compressed_salience(area: float, median_area: float) -> float:
    if not (
        math.isfinite(area)
        and math.isfinite(median_area)
        and area > 0.0
        and median_area > 0.0
    ):
        return 1.0
    ratio = area / median_area
    if ratio <= 0.0:
        return 1.0
    return min(1.80, max(0.75, math.exp(0.35 * math.log(ratio))))


def _preview_aspect(
    ref: UltraViewRef,
    aspects: Mapping[UltraViewRef, tuple[float, float]] | None,
) -> tuple[float | None, str]:
    if aspects is None:
        return None, "fallback"
    try:
        pair = aspects[ref]
    except KeyError:
        return None, "fallback"
    try:
        width = float(pair[0])
        height = float(pair[1])
    except (TypeError, ValueError, IndexError):
        return None, "fallback"
    if not math.isfinite(width) or not math.isfinite(height) or width <= 0.0 or height <= 0.0:
        return None, "fallback"
    return width / height, "captured"


def _build_items(
    items: Sequence[tuple[UltraViewRef, NativeLayoutRect]],
) -> tuple[list[_Item], list[_Item], list[UltraViewRef], list[str]]:
    """Split valid unique windows from exact-overlap stacks.

    Duplicate *refs* are dropped (solver identity is unique). Exact-overlap
    later *windows* stay as stack members. Invalid rects are omitted here;
    the planner records ``invalid_rect`` separately.
    """
    unique: list[_Item] = []
    overlaps: list[_Item] = []
    skipped_refs: list[UltraViewRef] = []
    warnings: list[str] = []
    seen_refs: set[UltraViewRef] = set()
    seen_rects: list[NativeLayoutRect] = []
    unique_order: list[int] = []
    order = 0
    for ref, rect in items:
        if not _valid_rect(rect):
            continue
        if ref in seen_refs:
            skipped_refs.append(ref)
            warnings.append("duplicate_ref")
            continue
        seen_refs.add(ref)
        duplicate_of: int | None = None
        for previous_index, previous in enumerate(seen_rects):
            if _edges_equal(rect, previous):
                duplicate_of = unique_order[previous_index]
                break
        item = _Item(
            ref=ref,
            rect=rect,
            source_order=order,
            top=_winwert_top(rect),
            bottom=_winwert_bottom(rect),
            duplicate_of=duplicate_of,
        )
        order += 1
        if duplicate_of is not None:
            overlaps.append(item)
            continue
        seen_rects.append(rect)
        unique_order.append(item.source_order)
        unique.append(item)
    return unique, overlaps, skipped_refs, warnings


def native_layout_facts(
    items: Sequence[tuple[UltraViewRef, NativeLayoutRect]],
    *,
    aspects: Mapping[UltraViewRef, tuple[float, float]] | None = None,
) -> tuple[SmartCardFact, ...]:
    """Extract D4–D6 topology facts. Does not choose ``GridRect`` spans."""
    unique, overlaps, _skipped, _warnings = _build_items(items)
    if not unique:
        return ()
    row_ids = _cluster_source_rows(unique)
    row_of_order = {
        unique[index].source_order: row_ids[index] for index in range(len(unique))
    }
    members_by_row: dict[int, list[int]] = {}
    for index, row_id in enumerate(row_ids):
        members_by_row.setdefault(row_id, []).append(index)
    column_of_order: dict[int, int] = {}
    next_column: dict[int, int] = {}
    for row_id, members in members_by_row.items():
        ordered = sorted(
            members,
            key=lambda index: (unique[index].rect.x, unique[index].source_order),
        )
        for column, index in enumerate(ordered):
            column_of_order[unique[index].source_order] = column
        next_column[row_id] = len(ordered)

    # D6: exact-overlap inherits the covered window's row and appends after
    # the last known member by source_order. The solver packs overflow onto a
    # continuation row immediately below that group — never Manhattan-up.
    for item in overlaps:
        covered_row = row_of_order[int(item.duplicate_of)]
        column = next_column[covered_row]
        row_of_order[item.source_order] = covered_row
        column_of_order[item.source_order] = column
        next_column[covered_row] = column + 1

    areas = [
        float(item.rect.width) * float(item.rect.height)
        for item in (*unique, *overlaps)
    ]
    median_area = float(sorted(areas)[len(areas) // 2])
    ordered_items = sorted(
        (*unique, *overlaps),
        key=lambda item: item.source_order,
    )
    facts: list[SmartCardFact] = []
    for item in ordered_items:
        area = float(item.rect.width) * float(item.rect.height)
        aspect, confidence = _preview_aspect(item.ref, aspects)
        facts.append(
            SmartCardFact(
                ref=item.ref,
                source_order=item.source_order,
                source_row=row_of_order[item.source_order],
                source_column=column_of_order[item.source_order],
                source_salience=_compressed_salience(area, median_area),
                preview_aspect=aspect,
                preview_confidence=confidence,  # type: ignore[arg-type]
                current_rect=None,
                locked_rect=None,
            )
        )
    return tuple(facts)


def _overlap_warnings(
    unique: Sequence[_Item],
    overlaps: Sequence[_Item],
    placed_refs: set[UltraViewRef],
) -> tuple[list[str], tuple[UltraViewRef, ...]]:
    warnings: list[str] = []
    relocated: list[UltraViewRef] = []
    unique_by_order = {item.source_order: item for item in unique}
    for item in overlaps:
        covered = unique_by_order.get(int(item.duplicate_of))
        covered_index = (
            (covered.source_order + 1) if covered is not None else int(item.duplicate_of) + 1
        )
        token_index = item.source_order + 1
        if item.ref in placed_refs:
            relocated.append(item.ref)
            warnings.append(
                f"exact_overlap_relocated: {token_index} -> {covered_index}"
            )
        else:
            warnings.append(f"exact_overlap: {token_index} -> {covered_index}")
    return warnings, tuple(relocated)


def plan_native_layout(
    items: Sequence[tuple[UltraViewRef, NativeLayoutRect]],
    *,
    metrics: GridMetrics | None = None,
    aspects: Mapping[UltraViewRef, tuple[float, float]] | None = None,
    policy: SmartLayoutPolicy | None = None,
) -> NativeLayoutPlan:
    """Validate millimetre rects, extract facts, then ask Smart Layout.

    ``metrics`` remains keyword-only for call-site compatibility. Default
    planner pitch is ``canonical_screen_metrics``; the solver owns 1× spans
    and ignores a dummy 96px column. Do not pass window-stretched metrics
    expecting different ``GridRect``s.
    """
    _ = metrics if metrics is not None else canonical_screen_metrics(())
    valid: list[tuple[UltraViewRef, NativeLayoutRect]] = []
    unplaced: list[UltraViewRef] = []
    warnings: list[str] = []
    invalid_count = 0
    for ref, rect in items:
        if _valid_rect(rect):
            valid.append((ref, rect))
            continue
        unplaced.append(ref)
        invalid_count += 1
    sources = tuple(valid)
    if invalid_count:
        warnings.append(f"invalid_rect: {invalid_count}")
    if not valid:
        return NativeLayoutPlan((), tuple(unplaced), tuple(warnings), sources)

    unique, overlaps, skipped_refs, extra_warnings = _build_items(valid)
    warnings.extend(extra_warnings)
    unplaced.extend(skipped_refs)
    if not unique:
        return NativeLayoutPlan(
            (),
            tuple(unplaced) + tuple(ref for ref, _rect in valid if ref not in skipped_refs),
            tuple(warnings),
            sources,
        )

    facts = native_layout_facts(valid, aspects=aspects)
    used_policy = _DEFAULT_NATIVE_POLICY if policy is None else policy
    result = solve_smart_layout(facts, used_policy)
    if not result.accepted:
        reason = str(result.reason or "no_legal_layout")
        warnings.append(reason)
        remaining = [
            ref for ref, _rect in valid
            if ref not in skipped_refs
        ]
        return NativeLayoutPlan(
            placed=(),
            unplaced=tuple(unplaced) + tuple(remaining),
            warnings=tuple(warnings),
            sources=sources,
            relocated=(),
            facts=facts,
        )

    packed = {ref: rect for ref, rect in result.placements}
    placed = tuple((ref, packed[ref]) for ref, _rect in valid if ref in packed)
    placed_refs = {ref for ref, _rect in placed}
    for ref, _rect in valid:
        if ref in skipped_refs or ref in placed_refs:
            continue
        unplaced.append(ref)
    overlap_notes, relocated = _overlap_warnings(unique, overlaps, placed_refs)
    warnings.extend(overlap_notes)
    return NativeLayoutPlan(
        placed=placed,
        unplaced=tuple(unplaced),
        warnings=tuple(warnings),
        sources=sources,
        relocated=relocated,
        facts=facts,
    )
