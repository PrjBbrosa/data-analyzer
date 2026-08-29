"""Qt-free native millimetre layout → UltraView free-grid plan."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .grid_geometry import (
    BOARD_PADDING,
    GRID_MIN_COLUMN_WIDTH,
    GRID_ROW_HEIGHT,
    SLOT_GUTTER,
    GridMetrics,
)
from .model import (
    GRID_COLUMNS,
    GRID_RESOLUTION,
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


def plan_native_layout(
    items: Sequence[tuple[UltraViewRef, NativeLayoutRect]],
    *,
    metrics: GridMetrics | None = None,
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
    if invalid_count:
        warnings.append(f"invalid_rect: {invalid_count}")
    if not valid:
        return NativeLayoutPlan((), tuple(unplaced), tuple(warnings))

    seen_rects: list[NativeLayoutRect] = []
    unique: list[tuple[UltraViewRef, NativeLayoutRect]] = []
    for index, (ref, rect) in enumerate(valid):
        duplicate_of = None
        for previous_index, previous in enumerate(seen_rects):
            if _edges_equal(rect, previous):
                duplicate_of = previous_index
                break
        if duplicate_of is not None:
            unplaced.append(ref)
            warnings.append(f"exact_overlap: {index + 1} -> {duplicate_of + 1}")
            continue
        seen_rects.append(rect)
        unique.append((ref, rect))

    xs = [rect.x for _, rect in unique]
    tops = [rect.y - rect.height for _, rect in unique]
    rights = [rect.x + rect.width for _, rect in unique]
    origin_x = min(xs)
    origin_top = min(tops)
    total_width_mm = max(rights) - origin_x
    if total_width_mm <= 0.0:
        return NativeLayoutPlan((), tuple(ref for ref, _ in items), tuple(warnings))

    used_metrics = _canonical_grid_metrics() if metrics is None else metrics
    pitch_x, pitch_y = used_metrics.exact_pitch()
    px_per_mm = (GRID_COLUMNS * pitch_x) / total_width_mm

    quantized: list[tuple[UltraViewRef, GridRect]] = []
    for ref, rect in unique:
        left_px = (rect.x - origin_x) * px_per_mm
        width_px = rect.width * px_per_mm
        top_px = (rect.y - rect.height - origin_top) * px_per_mm
        height_px = rect.height * px_per_mm
        left = round(left_px / pitch_x)
        right = round((left_px + width_px) / pitch_x)
        top = round(top_px / pitch_y)
        bottom = round((top_px + height_px) / pitch_y)
        grid = clamp_grid_rect(
            GridRect(left, top, max(1, right - left), max(1, bottom - top))
        )
        quantized.append((ref, grid))

    accepted: list[tuple[UltraViewRef, GridRect]] = []
    for order, (ref, grid) in enumerate(quantized):
        if any(_grid_overlap(grid, other) for _, other in accepted):
            unplaced.append(ref)
            warnings.append(f"quantized_collision: {order + 1}")
            continue
        accepted.append((ref, grid))

    return NativeLayoutPlan(
        placed=tuple(accepted),
        unplaced=tuple(unplaced),
        warnings=tuple(warnings),
    )
