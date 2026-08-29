"""Qt-free native millimetre layout → UltraView free-grid plan."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .model import (
    GRID_COLUMNS,
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


def plan_native_layout(
    items: Sequence[tuple[UltraViewRef, NativeLayoutRect]],
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
    total_width = max(rights) - origin_x
    if total_width <= 0.0:
        return NativeLayoutPlan((), tuple(ref for ref, _ in items), tuple(warnings))
    scale = GRID_COLUMNS / total_width

    quantized: list[tuple[UltraViewRef, GridRect]] = []
    for ref, rect in unique:
        left = round((rect.x - origin_x) * scale)
        right = round((rect.x + rect.width - origin_x) * scale)
        top = round((rect.y - rect.height - origin_top) * scale)
        bottom = round((rect.y - origin_top) * scale)
        grid = clamp_grid_rect(GridRect(left, top, max(1, right - left), max(1, bottom - top)))
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
