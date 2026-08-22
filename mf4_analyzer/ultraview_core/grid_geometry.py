"""Qt-free UltraView grid metrics and rect↔pixel primitives.

``free_grid`` (layout planner, handle-hit UI) and ``card_fit`` (hug scoring)
depend on this module one way. Do not import either from here.

Task 5.2: ``GridRect`` / ``GRID_*`` / ``FreeGridPlacement`` / ``clamp_grid_rect``
come from ``ultraview_core.model``. This module must not import
``mf4_analyzer.ui``, ``chart_stack``, widgets, Qt, or ``card_fit``.

Pitch chrome (``BOARD_PADDING`` / ``SLOT_GUTTER``) is numerically identical to
``ui.chart_stack.ultraview.layouts``; core cannot import ``chart_stack``. A
focused test pins the identity. Do not drift.

``rect_to_pixels`` rounds the two edges, never the pitch. Rounding the pitch
first and then multiplying by the cell index is what made zoom non-linear.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

from .model import (
    GRID_COLUMNS,
    GRID_RESOLUTION,
    SAFETY_ROW_MAX,
    FreeGridPlacement,
    GridRect,
    clamp_grid_rect,
)

# Same numbers as ``layouts.BOARD_PADDING`` / ``SLOT_GUTTER``. Do not drift.
BOARD_PADDING = 16
SLOT_GUTTER = 12

# These are deliberately smaller than P1's reading-card floor.  A four-micro-
# column free-grid card is an allowed thumbnail role; the Board scrolls rather
# than reducing a column below this fixed chrome-readable width.
GRID_MIN_COLUMN_WIDTH = 96
GRID_ROW_HEIGHT = 88
GRID_MIN_VISIBLE_ROWS = 10 * GRID_RESOLUTION
# Extra empty rows past the last occupied card so a 1× / fit canvas still
# has a drop target below the current layout. Export does not add these.
GRID_SPARE_ROWS = 2 * GRID_RESOLUTION

Rect = tuple[int, int, int, int]


@dataclass(frozen=True)
class GridMetrics:
    """Pixel mapping for the schema-5 2× micro-grid. Screen extent is separate.

    ``scale`` / ``base`` carry the screen zoom and the 1× metrics it came
    from, so the pixel map can multiply *before* rounding.  Rounding each
    metric first and then multiplying by a cell index leaves an error that
    grows with the index; the signed elastic origin drives that index past 40
    and turned the error into tens of pixels of wheel-zoom jitter.  1×
    metrics leave these at ``(1.0, None)``, where every mapping below reduces
    to the original integer arithmetic — the export path is unchanged.
    """

    board_width: int
    board_height: int
    column_width: int
    row_height: int
    gutter: int = SLOT_GUTTER
    padding: int = BOARD_PADDING
    resolution: int = GRID_RESOLUTION
    scale: float = 1.0
    base: "GridMetrics | None" = None

    @property
    def content_width(self) -> int:
        return self.board_width - 2 * self.padding

    def _exact_source(self) -> tuple["GridMetrics", float]:
        """1× metrics and the factor to apply, for unrounded geometry."""
        if self.base is None:
            return self, 1.0
        return self.base, float(self.scale)

    def exact_padding(self) -> float:
        base, scale = self._exact_source()
        return base.padding * scale

    def exact_pitch(self) -> tuple[float, float]:
        """Unrounded micro-cell pitch for every grid ↔ pixel mapping."""
        base, scale = self._exact_source()
        resolution = max(1, int(base.resolution))
        return (
            (base.column_width + base.gutter) * scale / resolution,
            (base.row_height + base.gutter) * scale / resolution,
        )

    def exact_cell(self) -> tuple[float, float]:
        """Unrounded micro-card size, i.e. pitch minus one physical gutter."""
        base, scale = self._exact_source()
        pitch_x, pitch_y = self.exact_pitch()
        return (
            pitch_x - base.gutter * scale,
            pitch_y - base.gutter * scale,
        )


def grid_metrics(
    viewport_size: tuple[int, int],
    placements: Sequence[FreeGridPlacement],
    *,
    min_visible_rows: int | None = None,
) -> GridMetrics:
    """Return stable, screen-size-independent metrics for the visible Board.

    Screen callers omit ``min_visible_rows`` so an empty Board still has a
    readable canvas.  Export passes ``min_visible_rows=1`` and a non-positive
    viewport height so trailing empty rows are not padded up to 900px.
    """
    viewport_w = max(1, int(viewport_size[0]))
    raw_h = int(viewport_size[1])
    floor_rows = (
        GRID_MIN_VISIBLE_ROWS
        if min_visible_rows is None
        else max(1, int(min_visible_rows))
    )
    physical_columns = max(1, GRID_COLUMNS // GRID_RESOLUTION)
    minimum_width = (
        2 * BOARD_PADDING
        + physical_columns * GRID_MIN_COLUMN_WIDTH
        + (physical_columns - 1) * SLOT_GUTTER
    )
    board_width = max(viewport_w, minimum_width)
    usable_width = board_width - 2 * BOARD_PADDING - (physical_columns - 1) * SLOT_GUTTER
    column_width = max(GRID_MIN_COLUMN_WIDTH, usable_width // physical_columns)
    # The Board can always add a new standard card into the initially visible
    # canvas, but its height only grows from actual, persistent row identity.
    occupied_rows = max(
        (item.rect.row + item.rect.row_span for item in placements),
        default=0,
    )
    if min_visible_rows is None:
        occupied_rows += GRID_SPARE_ROWS
    occupied_rows = min(SAFETY_ROW_MAX, max(floor_rows, occupied_rows))
    physical_rows = max(1, math.ceil(occupied_rows / GRID_RESOLUTION))
    minimum_height = (
        2 * BOARD_PADDING
        + physical_rows * GRID_ROW_HEIGHT
        + max(0, physical_rows - 1) * SLOT_GUTTER
    )
    board_height = minimum_height if raw_h <= 0 else max(raw_h, minimum_height)
    return GridMetrics(
        board_width=board_width,
        board_height=board_height,
        column_width=column_width,
        row_height=GRID_ROW_HEIGHT,
        resolution=GRID_RESOLUTION,
    )


def rect_to_pixels(
    rect: GridRect,
    metrics: GridMetrics,
    origin_offset: tuple[int, int] = (0, 0),
) -> Rect:
    """Map a logical rectangle to pixels without rebasing the GridRect.

    Negative cells produce negative (or sub-padding) pixel origins. Callers
    that need a non-negative screen/export bitmap pass ``origin_offset`` as
    the workspace or content origin; the rect itself is left unchanged.
    """
    col0, row0 = int(origin_offset[0]), int(origin_offset[1])
    padding = metrics.exact_padding()
    pitch_x, pitch_y = metrics.exact_pitch()
    cell_w, cell_h = metrics.exact_cell()
    # Round the two edges, never the pitch: rounding the pitch first and then
    # multiplying by the cell index is what made zoom non-linear.
    left = padding + (rect.column - col0) * pitch_x
    top = padding + (rect.row - row0) * pitch_y
    right = left + (rect.column_span - 1) * pitch_x + cell_w
    bottom = top + (rect.row_span - 1) * pitch_y + cell_h
    x, y = int(round(left)), int(round(top))
    return x, y, int(round(right)) - x, int(round(bottom)) - y


def pixels_to_grid_delta(delta: tuple[int, int], metrics: GridMetrics) -> tuple[int, int]:
    """Round a drag delta to a deterministic whole-cell move."""
    dx, dy = float(delta[0]), float(delta[1])
    pitch_x, pitch_y = metrics.exact_pitch()
    return (
        _round_cell(dx, max(1.0, pitch_x)),
        _round_cell(dy, max(1.0, pitch_y)),
    )


def pixel_to_origin(pos: tuple[int, int], metrics: GridMetrics) -> tuple[int, int]:
    padding = metrics.exact_padding()
    pitch_x, pitch_y = metrics.exact_pitch()
    column = math.floor((float(pos[0]) - padding) / max(1.0, pitch_x))
    row = math.floor((float(pos[1]) - padding) / max(1.0, pitch_y))
    return int(column), int(row)


def legal_grid_rect(
    pos: tuple[int, int],
    metrics: GridMetrics,
    *,
    column_span: int,
    row_span: int,
    grab_offset: tuple[int, int] = (0, 0),
) -> GridRect:
    """Map a board pixel to a clamped origin+span rectangle (S6)."""
    origin = (int(pos[0]) - int(grab_offset[0]), int(pos[1]) - int(grab_offset[1]))
    column, row = pixel_to_origin(origin, metrics)
    return clamp_rect(GridRect(column, row, int(column_span), int(row_span)))


def _round_cell(value: float, unit: float) -> int:
    """Half-away-from-zero cell rounding for a (possibly fractional) pitch."""
    if unit <= 0.0:
        return 0
    if value >= 0.0:
        return int(math.floor(value / unit + 0.5))
    return -int(math.floor(-value / unit + 0.5))


def rects_overlap(left: GridRect, right: GridRect) -> bool:
    return (
        left.column < right.column + right.column_span
        and right.column < left.column + left.column_span
        and left.row < right.row + right.row_span
        and right.row < left.row + left.row_span
    )


def clamp_rect(rect: GridRect) -> GridRect:
    """Clamp origin+span into the safety bounds, not the 12-column base frame."""
    return clamp_grid_rect(rect)


def union_grid_rect(rects: Iterable[GridRect]) -> GridRect | None:
    """Axis-aligned bounding box of ``rects``. Empty input returns ``None``."""
    items = tuple(rects)
    if not items:
        return None
    left = min(item.column for item in items)
    top = min(item.row for item in items)
    right = max(item.column + item.column_span for item in items)
    bottom = max(item.row + item.row_span for item in items)
    return GridRect(left, top, right - left, bottom - top)
