"""Qt-free geometry and history helpers for UltraView's controlled grid.

The screen Board and the off-screen compositor consume the same integer-grid
metrics.  No helper here knows about widgets, preview pixels, or MainWindow.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from mf4_analyzer.ui.ultraview_state import (
    GRID_COLUMNS,
    GRID_MAX_COLUMN_SPAN,
    GRID_MAX_ROW_SPAN,
    GRID_MIN_COLUMN_SPAN,
    GRID_MIN_ROW_SPAN,
    MAX_GRID_ROWS,
    FreeGridPlacement,
    GridRect,
    UltraViewRef,
)

from .layouts import BOARD_PADDING, SLOT_GUTTER

# These are deliberately smaller than P1's reading-card floor.  A 2-column
# free-grid card is an allowed thumbnail role; the Board scrolls rather than
# reducing a column below this fixed chrome-readable width.
GRID_MIN_COLUMN_WIDTH = 96
GRID_ROW_HEIGHT = 88
GRID_MIN_VISIBLE_ROWS = 6

Rect = tuple[int, int, int, int]


@dataclass(frozen=True)
class GridMetrics:
    """Pixel mapping for the fixed 12-column, vertically growing Board."""

    board_width: int
    board_height: int
    column_width: int
    row_height: int
    gutter: int = SLOT_GUTTER
    padding: int = BOARD_PADDING

    @property
    def content_width(self) -> int:
        return self.board_width - 2 * self.padding


@dataclass(frozen=True)
class GridGeometryCommand:
    """One ref geometry transition, suitable for a per-Board undo stack."""

    ref: UltraViewRef
    before: GridRect
    after: GridRect
    reason: str


def grid_metrics(
    viewport_size: tuple[int, int], placements: Sequence[FreeGridPlacement]
) -> GridMetrics:
    """Return stable, screen-size-independent metrics for the visible Board."""
    viewport_w = max(1, int(viewport_size[0]))
    viewport_h = max(1, int(viewport_size[1]))
    minimum_width = (
        2 * BOARD_PADDING
        + GRID_COLUMNS * GRID_MIN_COLUMN_WIDTH
        + (GRID_COLUMNS - 1) * SLOT_GUTTER
    )
    board_width = max(viewport_w, minimum_width)
    usable_width = board_width - 2 * BOARD_PADDING - (GRID_COLUMNS - 1) * SLOT_GUTTER
    column_width = max(GRID_MIN_COLUMN_WIDTH, usable_width // GRID_COLUMNS)
    # The Board can always add a new standard card into the initially visible
    # canvas, but its height only grows from actual, persistent row identity.
    occupied_rows = max(
        (item.rect.row + item.rect.row_span for item in placements),
        default=GRID_MIN_VISIBLE_ROWS,
    )
    occupied_rows = min(MAX_GRID_ROWS, max(GRID_MIN_VISIBLE_ROWS, occupied_rows))
    minimum_height = (
        2 * BOARD_PADDING
        + occupied_rows * GRID_ROW_HEIGHT
        + (occupied_rows - 1) * SLOT_GUTTER
    )
    return GridMetrics(
        board_width=board_width,
        board_height=max(viewport_h, minimum_height),
        column_width=column_width,
        row_height=GRID_ROW_HEIGHT,
    )


def rect_to_pixels(rect: GridRect, metrics: GridMetrics) -> Rect:
    """Map a legal logical rectangle to the same pixel rectangle everywhere."""
    x = metrics.padding + rect.column * (metrics.column_width + metrics.gutter)
    y = metrics.padding + rect.row * (metrics.row_height + metrics.gutter)
    width = rect.column_span * metrics.column_width + (rect.column_span - 1) * metrics.gutter
    height = rect.row_span * metrics.row_height + (rect.row_span - 1) * metrics.gutter
    return x, y, width, height


def pixels_to_grid_delta(delta: tuple[int, int], metrics: GridMetrics) -> tuple[int, int]:
    """Round a drag delta to a deterministic whole-cell move."""
    dx, dy = int(delta[0]), int(delta[1])
    unit_x = max(1, metrics.column_width + metrics.gutter)
    unit_y = max(1, metrics.row_height + metrics.gutter)
    return _round_cell(dx, unit_x), _round_cell(dy, unit_y)


def _round_cell(value: int, unit: int) -> int:
    if value >= 0:
        return (value + unit // 2) // unit
    return -((-value + unit // 2) // unit)


def rects_overlap(left: GridRect, right: GridRect) -> bool:
    return (
        left.column < right.column + right.column_span
        and right.column < left.column + left.column_span
        and left.row < right.row + right.row_span
        and right.row < left.row + left.row_span
    )


def clamp_rect(rect: GridRect) -> GridRect:
    col_span = min(GRID_MAX_COLUMN_SPAN, max(GRID_MIN_COLUMN_SPAN, int(rect.column_span)))
    row_span = min(GRID_MAX_ROW_SPAN, max(GRID_MIN_ROW_SPAN, int(rect.row_span)))
    return GridRect(
        column=min(GRID_COLUMNS - col_span, max(0, int(rect.column))),
        row=min(MAX_GRID_ROWS - row_span, max(0, int(rect.row))),
        column_span=col_span,
        row_span=row_span,
    )


def candidate_move(rect: GridRect, column_delta: int, row_delta: int) -> GridRect:
    return clamp_rect(
        GridRect(rect.column + int(column_delta), rect.row + int(row_delta), rect.column_span, rect.row_span)
    )


def candidate_resize(
    rect: GridRect, column_delta: int, row_delta: int
) -> GridRect:
    return clamp_rect(
        GridRect(rect.column, rect.row, rect.column_span + int(column_delta), rect.row_span + int(row_delta))
    )


def rect_is_available(
    candidate: GridRect,
    placements: Iterable[FreeGridPlacement],
    *,
    excluding: UltraViewRef | None = None,
) -> bool:
    return not any(
        item.ref != excluding and rects_overlap(candidate, item.rect)
        for item in placements
    )


def organized_placements(
    placements: Sequence[FreeGridPlacement],
) -> list[FreeGridPlacement]:
    """Remove fully empty rows while retaining each card's size/order/column.

    Unlike packing, this never moves a card left/right, never changes a span,
    and never crosses cards.  It is deterministic and idempotent.
    """
    occupied_rows = {
        row
        for item in placements
        for row in range(item.rect.row, item.rect.row + item.rect.row_span)
    }
    empty_before: list[int] = []
    result: list[FreeGridPlacement] = []
    for row in range(MAX_GRID_ROWS):
        if row not in occupied_rows:
            empty_before.append(row)
    for item in placements:
        shift = sum(1 for row in empty_before if row < item.rect.row)
        rect = item.rect
        result.append(
            FreeGridPlacement(
                item.ref,
                GridRect(rect.column, rect.row - shift, rect.column_span, rect.row_span),
            )
        )
    return result
