"""Qt-free native millimetre layout → UltraView free-grid plan.

WWT millimetre rects decide row/column order and wide/narrow rank. Empty
screenshot distances are discarded: neighbours in a row share one grid
gutter, and rows share one row gap. Exact-overlap later views relocate to
the nearest legal slot instead of the unplaced tray.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .grid_geometry import (
    BOARD_PADDING,
    GRID_MIN_COLUMN_WIDTH,
    GRID_ROW_HEIGHT,
    SLOT_GUTTER,
    GridMetrics,
)
from .model import (
    GRID_COLUMNS,
    GRID_MAX_COLUMN_SPAN,
    GRID_MAX_ROW_SPAN,
    GRID_MIN_COLUMN_SPAN,
    GRID_MIN_ROW_SPAN,
    GRID_RESOLUTION,
    SAFETY_COLUMN_MAX,
    SAFETY_COLUMN_MIN,
    SAFETY_ROW_MAX,
    SAFETY_ROW_MIN,
    GridRect,
    UltraViewRef,
    clamp_grid_rect,
)

_OVERLAP_EPS = 1e-6


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


@dataclass(frozen=True)
class _Slot:
    ref: UltraViewRef
    rect: NativeLayoutRect
    source_index: int
    top: float
    bottom: float
    duplicate_of: int | None = None


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


def _grid_overlap(left: GridRect, right: GridRect) -> bool:
    return not (
        left.column + left.column_span <= right.column
        or right.column + right.column_span <= left.column
        or left.row + left.row_span <= right.row
        or right.row + right.row_span <= left.row
    )


def _canonical_grid_metrics() -> GridMetrics:
    """1× pitch independent of the current window width.

    ``board_width`` / ``board_height`` are dummy extents so callers never
    inherit a viewport-stretched ``column_width``. Pitch uses the min
    column and fixed row height only.
    """
    physical_columns = max(1, GRID_COLUMNS // GRID_RESOLUTION)
    return GridMetrics(
        board_width=(
            2 * BOARD_PADDING
            + physical_columns * GRID_MIN_COLUMN_WIDTH
            + max(0, physical_columns - 1) * SLOT_GUTTER
        ),
        board_height=2 * BOARD_PADDING + GRID_ROW_HEIGHT,
        column_width=GRID_MIN_COLUMN_WIDTH,
        row_height=GRID_ROW_HEIGHT,
        gutter=SLOT_GUTTER,
        padding=BOARD_PADDING,
        resolution=GRID_RESOLUTION,
    )


def _round_positive(value: float) -> int:
    return int(math.floor(float(value) + 0.5))


def _clamp_span(value: int, lo: int, hi: int) -> int:
    return min(int(hi), max(int(lo), int(value)))


def _winwert_top(rect: NativeLayoutRect) -> float:
    return float(rect.y) - float(rect.height)


def _winwert_bottom(rect: NativeLayoutRect) -> float:
    return float(rect.y)


def _cluster_rows(unique: Sequence[_Slot]) -> list[list[_Slot]]:
    ordered = sorted(
        unique,
        key=lambda slot: (slot.top, slot.rect.x, slot.source_index),
    )
    rows: list[list[_Slot]] = []
    bounds: list[list[float]] = []
    for slot in ordered:
        matched: int | None = None
        for index, band in enumerate(bounds):
            if slot.top < band[1] - _OVERLAP_EPS and slot.bottom > band[0] + _OVERLAP_EPS:
                matched = index
                break
        if matched is None:
            rows.append([slot])
            bounds.append([slot.top, slot.bottom])
            continue
        rows[matched].append(slot)
        bounds[matched][0] = min(bounds[matched][0], slot.top)
        bounds[matched][1] = max(bounds[matched][1], slot.bottom)
    for row in rows:
        row.sort(key=lambda slot: (slot.rect.x, slot.source_index))
    return rows


def _item_spans(
    rect: NativeLayoutRect,
    *,
    scale: float,
    pitch_x: float,
    pitch_y: float,
    aspect: tuple[float, float] | None,
) -> tuple[int, int]:
    width = float(rect.width)
    height = float(rect.height)
    if aspect is not None:
        aspect_w = float(aspect[0])
        aspect_h = float(aspect[1])
        if aspect_w > 0.0 and aspect_h > 0.0:
            height = width * aspect_h / aspect_w
    pitch_y = max(pitch_y, 1e-9)
    column_span = _clamp_span(
        _round_positive(width * scale),
        GRID_MIN_COLUMN_SPAN,
        GRID_MAX_COLUMN_SPAN,
    )
    row_span = _clamp_span(
        _round_positive(height * scale * pitch_x / pitch_y),
        GRID_MIN_ROW_SPAN,
        GRID_MAX_ROW_SPAN,
    )
    return column_span, row_span


def _fit_row_column_spans(spans: list[int]) -> list[int]:
    fitted = list(spans)
    while sum(fitted) > GRID_COLUMNS:
        widest = max(range(len(fitted)), key=lambda index: fitted[index])
        if fitted[widest] <= GRID_MIN_COLUMN_SPAN:
            break
        fitted[widest] -= 1
    return fitted


def _nearest_unoccupied(
    occupied: Sequence[GridRect],
    span: tuple[int, int],
    origin: GridRect,
) -> GridRect | None:
    from .board_ops import nearest_unoccupied_origin

    return nearest_unoccupied_origin(occupied, span, origin)


def _legal_in_safety(rect: GridRect) -> bool:
    return (
        SAFETY_COLUMN_MIN <= rect.column
        and rect.column + rect.column_span <= SAFETY_COLUMN_MAX
        and SAFETY_ROW_MIN <= rect.row
        and rect.row + rect.row_span <= SAFETY_ROW_MAX
        and GRID_MIN_COLUMN_SPAN <= rect.column_span <= GRID_MAX_COLUMN_SPAN
        and GRID_MIN_ROW_SPAN <= rect.row_span <= GRID_MAX_ROW_SPAN
    )


def plan_native_layout(
    items: Sequence[tuple[UltraViewRef, NativeLayoutRect]],
    *,
    metrics: GridMetrics | None = None,
    aspects: Mapping[UltraViewRef, tuple[float, float]] | None = None,
    span_overrides: Mapping[UltraViewRef, tuple[int, int]] | None = None,
) -> NativeLayoutPlan:
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

    unique: list[_Slot] = []
    relocates: list[_Slot] = []
    seen: list[NativeLayoutRect] = []
    unique_source_index: list[int] = []
    for index, (ref, rect) in enumerate(valid):
        duplicate_of = None
        for previous_index, previous in enumerate(seen):
            if _edges_equal(rect, previous):
                duplicate_of = unique_source_index[previous_index]
                break
        slot = _Slot(
            ref=ref,
            rect=rect,
            source_index=index + 1,
            top=_winwert_top(rect),
            bottom=_winwert_bottom(rect),
            duplicate_of=duplicate_of,
        )
        if duplicate_of is not None:
            relocates.append(slot)
            continue
        seen.append(rect)
        unique_source_index.append(index + 1)
        unique.append(slot)

    if not unique:
        return NativeLayoutPlan(
            (),
            tuple(unplaced) + tuple(slot.ref for slot in relocates),
            tuple(warnings),
            sources,
        )

    rows = _cluster_rows(unique)
    max_row_mm = max(sum(slot.rect.width for slot in row) for row in rows)
    if max_row_mm <= 0.0:
        return NativeLayoutPlan(
            (),
            tuple(ref for ref, _rect in items),
            tuple(warnings),
            sources,
        )

    used_metrics = _canonical_grid_metrics() if metrics is None else metrics
    pitch_x, pitch_y = used_metrics.exact_pitch()
    scale = float(GRID_COLUMNS) / max_row_mm
    aspect_map = aspects or {}
    override_map = span_overrides or {}

    def _spans_for(slot: _Slot) -> tuple[int, int]:
        override = override_map.get(slot.ref)
        if override is not None:
            column_span, row_span = int(override[0]), int(override[1])
            return (
                _clamp_span(column_span, GRID_MIN_COLUMN_SPAN, GRID_MAX_COLUMN_SPAN),
                _clamp_span(row_span, GRID_MIN_ROW_SPAN, GRID_MAX_ROW_SPAN),
            )
        return _item_spans(
            slot.rect,
            scale=scale,
            pitch_x=pitch_x,
            pitch_y=pitch_y,
            aspect=aspect_map.get(slot.ref),
        )

    packed: dict[UltraViewRef, GridRect] = {}
    occupied: list[GridRect] = []
    row_origin = 0
    for row in rows:
        spans = [_spans_for(slot) for slot in row]
        column_spans = _fit_row_column_spans([span[0] for span in spans])
        column = 0
        row_height = 0
        for slot, (_column_span_raw, row_span), column_span in zip(
            row, spans, column_spans
        ):
            candidate = clamp_grid_rect(
                GridRect(column, row_origin, column_span, row_span)
            )
            if any(_grid_overlap(candidate, other) for other in occupied):
                found = _nearest_unoccupied(
                    occupied, (column_span, row_span), candidate
                )
                if found is None or not _legal_in_safety(found):
                    unplaced.append(slot.ref)
                    warnings.append(f"quantized_collision: {slot.source_index}")
                    continue
                candidate = found
            packed[slot.ref] = candidate
            occupied.append(candidate)
            column = candidate.column + candidate.column_span
            row_height = max(row_height, candidate.row_span)
        row_origin += max(row_height, GRID_MIN_ROW_SPAN)

    first_by_source = {slot.source_index: slot.ref for slot in unique}
    relocated_refs: list[UltraViewRef] = []
    for slot in relocates:
        first_ref = first_by_source.get(int(slot.duplicate_of or 0))
        preferred = packed.get(first_ref) if first_ref is not None else None
        column_span, row_span = _spans_for(slot)
        origin = (
            preferred
            if preferred is not None
            else GridRect(0, 0, column_span, row_span)
        )
        found = _nearest_unoccupied(occupied, (column_span, row_span), origin)
        if found is None or not _legal_in_safety(found):
            unplaced.append(slot.ref)
            if slot.duplicate_of is not None:
                warnings.append(
                    f"exact_overlap: {slot.source_index} -> {slot.duplicate_of}"
                )
            continue
        packed[slot.ref] = found
        occupied.append(found)
        relocated_refs.append(slot.ref)
        warnings.append(
            f"exact_overlap_relocated: {slot.source_index} -> {slot.duplicate_of}"
        )

    placed = tuple(
        (ref, packed[ref]) for ref, _rect in valid if ref in packed
    )
    return NativeLayoutPlan(
        placed=placed,
        unplaced=tuple(unplaced),
        warnings=tuple(warnings),
        sources=sources,
        relocated=tuple(relocated_refs),
    )
