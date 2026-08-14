"""Qt-free geometry and history helpers for UltraView's controlled grid.

The screen Board and the off-screen compositor consume the same integer-grid
metrics.  No helper here knows about widgets, preview pixels, or MainWindow.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

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

from .layouts import BASE_BOARD_SIZE, BOARD_PADDING, SLOT_GUTTER

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
        default=floor_rows,
    )
    occupied_rows = min(MAX_GRID_ROWS, max(floor_rows, occupied_rows))
    minimum_height = (
        2 * BOARD_PADDING
        + occupied_rows * GRID_ROW_HEIGHT
        + max(0, occupied_rows - 1) * SLOT_GUTTER
    )
    board_height = minimum_height if raw_h <= 0 else max(raw_h, minimum_height)
    return GridMetrics(
        board_width=board_width,
        board_height=board_height,
        column_width=column_width,
        row_height=GRID_ROW_HEIGHT,
    )


def export_grid_metrics(placements: Sequence[FreeGridPlacement]) -> GridMetrics:
    """Canonical free-grid export metrics: 1600-wide, cropped to occupied rows."""
    return grid_metrics(
        (BASE_BOARD_SIZE[0], 0), placements, min_visible_rows=1
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


def snapped_move_rect(
    origin: GridRect, pixel_delta: tuple[int, int], metrics: GridMetrics
) -> GridRect:
    """Clamp a pointer delta onto the same legal rectangle ``candidate_move`` uses."""
    column_delta, row_delta = pixels_to_grid_delta(pixel_delta, metrics)
    return candidate_move(origin, column_delta, row_delta)


def pixel_to_origin(pos: tuple[int, int], metrics: GridMetrics) -> tuple[int, int]:
    unit_x = max(1, metrics.column_width + metrics.gutter)
    unit_y = max(1, metrics.row_height + metrics.gutter)
    column = (int(pos[0]) - metrics.padding) // unit_x
    row = (int(pos[1]) - metrics.padding) // unit_y
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


HANDLE_HIT_PX = 8
HANDLE_VISUAL_PX = 6
HANDLE_NAMES = ("nw", "n", "ne", "w", "e", "sw", "s", "se")
_HANDLE_WEST = frozenset({"w", "nw", "sw"})
_HANDLE_EAST = frozenset({"e", "ne", "se"})
_HANDLE_NORTH = frozenset({"n", "nw", "ne"})
_HANDLE_SOUTH = frozenset({"s", "sw", "se"})
_HANDLE_CORNERS = ("nw", "ne", "sw", "se")


def handle_hit_rects(
    card_px: Rect, hit: int = HANDLE_HIT_PX
) -> dict[str, Rect]:
    """Axis-aligned hit zones. Corners are ``hit×hit`` and take priority."""
    x, y, width, height = (int(card_px[0]), int(card_px[1]), int(card_px[2]), int(card_px[3]))
    zone = max(HANDLE_HIT_PX, int(hit))
    inner_w = max(1, width - 2 * zone)
    inner_h = max(1, height - 2 * zone)
    return {
        "nw": (x, y, zone, zone),
        "n": (x + zone, y, inner_w, zone),
        "ne": (x + width - zone, y, zone, zone),
        "w": (x, y + zone, zone, inner_h),
        "e": (x + width - zone, y + zone, zone, inner_h),
        "sw": (x, y + height - zone, zone, zone),
        "s": (x + zone, y + height - zone, inner_w, zone),
        "se": (x + width - zone, y + height - zone, zone, zone),
    }


def hit_handle(
    card_px: Rect, pos: tuple[int, int], hit: int = HANDLE_HIT_PX
) -> str | None:
    px, py = int(pos[0]), int(pos[1])
    zones = handle_hit_rects(card_px, hit)
    for name in _HANDLE_CORNERS:
        x, y, width, height = zones[name]
        if x <= px < x + width and y <= py < y + height:
            return name
    for name in ("n", "s", "w", "e"):
        x, y, width, height = zones[name]
        if x <= px < x + width and y <= py < y + height:
            return name
    return None


def handle_visual_rects(card_px: Rect, size: int = HANDLE_VISUAL_PX) -> dict[str, Rect]:
    x, y, width, height = (int(card_px[0]), int(card_px[1]), int(card_px[2]), int(card_px[3]))
    half = max(2, int(size)) // 2
    anchors = {
        "nw": (x, y),
        "n": (x + width // 2, y),
        "ne": (x + width, y),
        "w": (x, y + height // 2),
        "e": (x + width, y + height // 2),
        "sw": (x, y + height),
        "s": (x + width // 2, y + height),
        "se": (x + width, y + height),
    }
    box = max(2, int(size))
    return {
        name: (ax - half, ay - half, box, box) for name, (ax, ay) in anchors.items()
    }


def candidate_resize_handle(
    rect: GridRect, handle: str, column_delta: int, row_delta: int
) -> GridRect:
    """Resize by moving the named edge/corner; unmoved edges stay put."""
    left = rect.column
    top = rect.row
    right = rect.column + rect.column_span
    bottom = rect.row + rect.row_span
    if handle in _HANDLE_WEST:
        left += int(column_delta)
        left = max(0, min(left, right - GRID_MIN_COLUMN_SPAN))
        left = max(right - GRID_MAX_COLUMN_SPAN, left)
    elif handle in _HANDLE_EAST:
        right += int(column_delta)
        right = min(GRID_COLUMNS, max(right, left + GRID_MIN_COLUMN_SPAN))
        right = min(left + GRID_MAX_COLUMN_SPAN, right)
    if handle in _HANDLE_NORTH:
        top += int(row_delta)
        top = max(0, min(top, bottom - GRID_MIN_ROW_SPAN))
        top = max(bottom - GRID_MAX_ROW_SPAN, top)
    elif handle in _HANDLE_SOUTH:
        bottom += int(row_delta)
        bottom = min(MAX_GRID_ROWS, max(bottom, top + GRID_MIN_ROW_SPAN))
        bottom = min(top + GRID_MAX_ROW_SPAN, bottom)
    return clamp_rect(GridRect(left, top, right - left, bottom - top))


def keep_aspect_resize(origin: GridRect, candidate: GridRect, handle: str) -> GridRect:
    """Lock the dragged primary span and round the other to the origin ratio."""
    ratio = origin.column_span / float(origin.row_span)
    dc = abs(candidate.column_span - origin.column_span)
    dr = abs(candidate.row_span - origin.row_span)
    edge_horizontal = handle in _HANDLE_WEST or handle in _HANDLE_EAST
    edge_vertical = handle in _HANDLE_NORTH or handle in _HANDLE_SOUTH
    if edge_horizontal and not edge_vertical:
        cols = candidate.column_span
        rows = min(
            GRID_MAX_ROW_SPAN,
            max(GRID_MIN_ROW_SPAN, int(round(cols / ratio))),
        )
    elif edge_vertical and not edge_horizontal:
        rows = candidate.row_span
        cols = min(
            GRID_MAX_COLUMN_SPAN,
            max(GRID_MIN_COLUMN_SPAN, int(round(rows * ratio))),
        )
    elif dc >= dr:
        cols = candidate.column_span
        rows = min(
            GRID_MAX_ROW_SPAN,
            max(GRID_MIN_ROW_SPAN, int(round(cols / ratio))),
        )
    else:
        rows = candidate.row_span
        cols = min(
            GRID_MAX_COLUMN_SPAN,
            max(GRID_MIN_COLUMN_SPAN, int(round(rows * ratio))),
        )
    column = (
        origin.column + origin.column_span - cols
        if handle in _HANDLE_WEST
        else origin.column
    )
    row = (
        origin.row + origin.row_span - rows
        if handle in _HANDLE_NORTH
        else origin.row
    )
    return clamp_rect(GridRect(column, row, cols, rows))


def snapped_resize_rect(
    origin: GridRect,
    pixel_delta: tuple[int, int],
    metrics: GridMetrics,
    handle: str,
    *,
    keep_aspect: bool = False,
) -> GridRect:
    column_delta, row_delta = pixels_to_grid_delta(pixel_delta, metrics)
    candidate = candidate_resize_handle(origin, handle, column_delta, row_delta)
    if keep_aspect:
        candidate = keep_aspect_resize(origin, candidate, handle)
    return clamp_rect(candidate)


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


def group_translate_rects(
    selected: Mapping[UltraViewRef, GridRect],
    others: Iterable[GridRect],
    column_delta: int,
    row_delta: int,
) -> tuple[dict[UltraViewRef, GridRect], bool]:
    """Rigid-translate a selection. Illegal if any member would clamp or the
    union collides with a non-selected rectangle (spec §9)."""
    translated: dict[UltraViewRef, GridRect] = {}
    in_bounds = True
    for ref, rect in selected.items():
        raw = GridRect(
            rect.column + int(column_delta),
            rect.row + int(row_delta),
            rect.column_span,
            rect.row_span,
        )
        if raw != clamp_rect(raw):
            in_bounds = False
        translated[ref] = raw
    union = union_grid_rect(translated.values())
    if union is None:
        return translated, False
    legal = in_bounds and not any(rects_overlap(union, other) for other in others)
    return translated, legal
