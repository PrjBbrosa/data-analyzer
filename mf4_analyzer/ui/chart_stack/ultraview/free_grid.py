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


def translated_move_rect(
    origin: GridRect, pixel_delta: tuple[int, int], metrics: GridMetrics
) -> GridRect:
    """Apply a pointer delta without clamping. Out of bounds stays illegal."""
    column_delta, row_delta = pixels_to_grid_delta(pixel_delta, metrics)
    return GridRect(
        origin.column + column_delta,
        origin.row + row_delta,
        origin.column_span,
        origin.row_span,
    )


def snapped_move_rect(
    origin: GridRect, pixel_delta: tuple[int, int], metrics: GridMetrics
) -> GridRect:
    """Clamp a pointer delta onto the same legal rectangle ``candidate_move`` uses."""
    return clamp_rect(translated_move_rect(origin, pixel_delta, metrics))


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


_CARDINAL_DELTAS = ((0, 1), (1, 0), (-1, 0), (0, -1))
_AVOID_SEARCH_LIMIT = max(GRID_COLUMNS, MAX_GRID_ROWS)


def avoidance_preferred_delta(origin: GridRect, candidate: GridRect) -> tuple[int, int]:
    """Pick the dominant move/resize axis so blockers slide the same way."""
    dc = int(candidate.column) - int(origin.column)
    dr = int(candidate.row) - int(origin.row)
    if dc == 0 and dr == 0:
        dc = (int(candidate.column) + int(candidate.column_span)) - (
            int(origin.column) + int(origin.column_span)
        )
        dr = (int(candidate.row) + int(candidate.row_span)) - (
            int(origin.row) + int(origin.row_span)
        )
    if dc == 0 and dr == 0:
        return (0, 1)
    if abs(dc) >= abs(dr):
        return (1 if dc > 0 else -1, 0)
    return (0, 1 if dr > 0 else -1)


def _rect_free(candidate: GridRect, occupied: Sequence[GridRect]) -> bool:
    return not any(rects_overlap(candidate, other) for other in occupied)


def find_avoidance_rect(
    rect: GridRect,
    occupied: Sequence[GridRect],
    preferred: tuple[int, int] = (0, 1),
) -> GridRect | None:
    """Same-size slot that misses ``occupied``. Prefers the drag axis, then rings."""
    directions: list[tuple[int, int]] = []
    pref = (int(preferred[0]), int(preferred[1]))
    if pref != (0, 0):
        directions.append(pref)
    for delta in _CARDINAL_DELTAS:
        if delta not in directions:
            directions.append(delta)
    for dc, dr in directions:
        column, row = int(rect.column), int(rect.row)
        for _ in range(_AVOID_SEARCH_LIMIT):
            column += dc
            row += dr
            candidate = GridRect(column, row, rect.column_span, rect.row_span)
            if clamp_rect(candidate) != candidate:
                break
            if _rect_free(candidate, occupied):
                return candidate
    max_dist = GRID_COLUMNS + MAX_GRID_ROWS
    for dist in range(1, max_dist):
        for dc in range(-dist, dist + 1):
            dr_span = dist - abs(dc)
            for dr in (-dr_span, dr_span) if dr_span else (0,):
                candidate = GridRect(
                    rect.column + dc,
                    rect.row + dr,
                    rect.column_span,
                    rect.row_span,
                )
                if clamp_rect(candidate) != candidate:
                    continue
                if _rect_free(candidate, occupied):
                    return candidate
    return None


def plan_overlap_avoidance(
    incoming: Mapping[UltraViewRef, GridRect],
    placements: Sequence[FreeGridPlacement],
    *,
    preferred: tuple[int, int] = (0, 1),
) -> tuple[tuple[tuple[UltraViewRef, GridRect], ...], bool]:
    """Move overlapping cards out of ``incoming``.

    Returns ``(updates, True)`` when every blocker has a same-size hole.
    Returns ``((), False)`` when a blocker is boxed in at the grid edge.
    ``updates`` lists every rect that differs from ``placements``.
    """
    current = {item.ref: item.rect for item in placements}
    wanted = dict(incoming)
    if not wanted:
        return (), True
    if any(ref not in current for ref in wanted):
        return (), False
    frozen = tuple(wanted.values())
    for index, left in enumerate(frozen):
        if clamp_rect(left) != left:
            return (), False
        for right in frozen[index + 1 :]:
            if rects_overlap(left, right):
                return (), False

    remaining: dict[UltraViewRef, GridRect] = {}
    queue: list[UltraViewRef] = []
    queued: set[UltraViewRef] = set()
    for ref, rect in current.items():
        if ref in wanted:
            continue
        if any(rects_overlap(rect, block) for block in frozen):
            queue.append(ref)
            queued.add(ref)
        else:
            remaining[ref] = rect
    if not queue:
        updates = tuple(
            (ref, rect) for ref, rect in wanted.items() if current[ref] != rect
        )
        return updates, True

    queue.sort(
        key=lambda ref: (
            current[ref].row,
            current[ref].column,
            ref.section,
            ref.view_id,
        )
    )
    placed: dict[UltraViewRef, GridRect] = {}
    while queue:
        ref = queue.pop(0)
        obstacles = (*frozen, *remaining.values(), *placed.values())
        found = find_avoidance_rect(current[ref], obstacles, preferred)
        if found is None:
            return (), False
        displaced = [
            other
            for other, rect in tuple(remaining.items())
            if rects_overlap(found, rect)
        ]
        for other in displaced:
            remaining.pop(other)
            if other not in queued:
                queue.append(other)
                queued.add(other)
        placed[ref] = found

    proposed = dict(current)
    proposed.update(wanted)
    proposed.update(placed)
    items = tuple(proposed.items())
    for index, (_ref_a, left) in enumerate(items):
        if clamp_rect(left) != left:
            return (), False
        for _ref_b, right in items[index + 1 :]:
            if rects_overlap(left, right):
                return (), False
    updates = tuple(
        (ref, rect) for ref, rect in items if current[ref] != rect
    )
    return updates, True


def _axis_overlap_rows(left: GridRect, right: GridRect) -> bool:
    return (
        left.row < right.row + right.row_span
        and right.row < left.row + left.row_span
    )


def _axis_overlap_cols(left: GridRect, right: GridRect) -> bool:
    return (
        left.column < right.column + right.column_span
        and right.column < left.column + left.column_span
    )


def _connected_components(
    refs: Sequence[UltraViewRef],
    current: Mapping[UltraViewRef, GridRect],
    overlap_fn,
) -> list[list[UltraViewRef]]:
    remaining = list(refs)
    groups: list[list[UltraViewRef]] = []
    while remaining:
        seed = remaining.pop(0)
        group = [seed]
        changed = True
        while changed:
            changed = False
            keep: list[UltraViewRef] = []
            for other in remaining:
                if any(overlap_fn(current[item], current[other]) for item in group):
                    group.append(other)
                    changed = True
                else:
                    keep.append(other)
            remaining = keep
        groups.append(group)
    return groups


def _min_packed_span(
    refs: Sequence[UltraViewRef],
    current: Mapping[UltraViewRef, GridRect],
    *,
    horizontal: bool,
) -> int:
    if not refs:
        return 0
    overlap_fn = _axis_overlap_rows if horizontal else _axis_overlap_cols
    min_span = GRID_MIN_COLUMN_SPAN if horizontal else GRID_MIN_ROW_SPAN
    groups = _connected_components(refs, current, overlap_fn)
    return max(min_span * len(group) for group in groups)


def _rect_overflow(rect: GridRect) -> tuple[int, int, int, int]:
    left = max(0, -int(rect.column))
    top = max(0, -int(rect.row))
    right = max(0, int(rect.column) + int(rect.column_span) - GRID_COLUMNS)
    bottom = max(0, int(rect.row) + int(rect.row_span) - MAX_GRID_ROWS)
    return left, top, right, bottom


def _proposed_is_legal(proposed: Mapping[UltraViewRef, GridRect]) -> bool:
    items = tuple(proposed.items())
    for index, (_ref, left) in enumerate(items):
        if clamp_rect(left) != left:
            return False
        for _other, right in items[index + 1 :]:
            if rects_overlap(left, right):
                return False
    return True


def _updates_from(
    current: Mapping[UltraViewRef, GridRect],
    proposed: Mapping[UltraViewRef, GridRect],
) -> tuple[tuple[UltraViewRef, GridRect], ...]:
    return tuple(
        (ref, rect) for ref, rect in proposed.items() if current.get(ref) != rect
    )


def _pack_row_group(
    refs: Sequence[UltraViewRef],
    current: Mapping[UltraViewRef, GridRect],
    pocket_origin: int,
    pocket_span: int,
    *,
    horizontal: bool,
) -> dict[UltraViewRef, GridRect] | None:
    min_span = GRID_MIN_COLUMN_SPAN if horizontal else GRID_MIN_ROW_SPAN
    ordered = sorted(
        refs,
        key=lambda ref: (
            current[ref].column if horizontal else current[ref].row,
            current[ref].row if horizontal else current[ref].column,
            ref.section,
            ref.view_id,
        ),
    )
    spans = [
        min(
            pocket_span,
            current[ref].column_span if horizontal else current[ref].row_span,
        )
        for ref in ordered
    ]
    extra = sum(spans) - pocket_span
    while extra > 0:
        shrinkable = [index for index, span in enumerate(spans) if span > min_span]
        if not shrinkable:
            return None
        index = max(shrinkable, key=lambda item: spans[item])
        spans[index] -= 1
        extra -= 1
    cursor = pocket_origin
    packed: dict[UltraViewRef, GridRect] = {}
    for ref, span in zip(ordered, spans):
        rect = current[ref]
        packed[ref] = (
            GridRect(cursor, rect.row, span, rect.row_span)
            if horizontal
            else GridRect(rect.column, cursor, rect.column_span, span)
        )
        cursor += span
    return packed


def _pack_into_pocket(
    refs: Sequence[UltraViewRef],
    current: Mapping[UltraViewRef, GridRect],
    pocket_origin: int,
    pocket_span: int,
    *,
    horizontal: bool,
) -> dict[UltraViewRef, GridRect] | None:
    min_span = GRID_MIN_COLUMN_SPAN if horizontal else GRID_MIN_ROW_SPAN
    if not refs:
        return {}
    if pocket_span < min_span:
        return None
    overlap_fn = _axis_overlap_rows if horizontal else _axis_overlap_cols
    packed: dict[UltraViewRef, GridRect] = {}
    for group in _connected_components(refs, current, overlap_fn):
        placed = _pack_row_group(
            group, current, pocket_origin, pocket_span, horizontal=horizontal
        )
        if placed is None:
            return None
        packed.update(placed)
    return packed


def plan_neighbor_shrink(
    incoming: Mapping[UltraViewRef, GridRect],
    placements: Sequence[FreeGridPlacement],
    *,
    horizontal: bool | None = None,
) -> tuple[tuple[tuple[UltraViewRef, GridRect], ...], bool]:
    """Pack overlapping neighbours into leftover cells, shrinking to min span.

    ``incoming`` must already be in-board. Cards keep their row (or column)
    when the squeeze is horizontal (or vertical). Returns ``((), False)`` when
    a neighbour would drop below the legal minimum.
    """
    current = {item.ref: item.rect for item in placements}
    wanted = dict(incoming)
    if not wanted or any(ref not in current for ref in wanted):
        return (), False
    frozen = tuple(wanted.values())
    for index, left in enumerate(frozen):
        if clamp_rect(left) != left:
            return (), False
        for right in frozen[index + 1 :]:
            if rects_overlap(left, right):
                return (), False
    union = union_grid_rect(frozen)
    if union is None:
        return (), False
    if horizontal is None:
        dc = sum(abs(wanted[ref].column - current[ref].column) for ref in wanted)
        dr = sum(abs(wanted[ref].row - current[ref].row) for ref in wanted)
        ds_c = sum(
            abs(wanted[ref].column_span - current[ref].column_span) for ref in wanted
        )
        ds_r = sum(
            abs(wanted[ref].row_span - current[ref].row_span) for ref in wanted
        )
        horizontal = (dc + ds_c) >= (dr + ds_r)

    blockers = [
        ref
        for ref, rect in current.items()
        if ref not in wanted and any(rects_overlap(rect, block) for block in frozen)
    ]
    proposed = dict(current)
    proposed.update(wanted)
    if not blockers:
        if not _proposed_is_legal(proposed):
            return (), False
        updates = _updates_from(current, proposed)
        return updates, bool(updates)

    if horizontal:
        left_origin, left_span = 0, union.column
        right_origin = union.column + union.column_span
        right_span = GRID_COLUMNS - right_origin
        left_refs: list[UltraViewRef] = []
        right_refs: list[UltraViewRef] = []
        mover_mid = union.column * 2 + union.column_span
        for ref in blockers:
            rect = current[ref]
            block_mid = rect.column * 2 + rect.column_span
            (left_refs if block_mid <= mover_mid else right_refs).append(ref)
        min_span = GRID_MIN_COLUMN_SPAN
        if left_refs and left_span < min_span:
            right_refs.extend(left_refs)
            left_refs = []
        if right_refs and right_span < min_span:
            left_refs.extend(right_refs)
            right_refs = []
        packed_left = _pack_into_pocket(
            left_refs, current, left_origin, left_span, horizontal=True
        )
        packed_right = _pack_into_pocket(
            right_refs, current, right_origin, right_span, horizontal=True
        )
    else:
        top_origin, top_span = 0, union.row
        bottom_origin = union.row + union.row_span
        bottom_span = MAX_GRID_ROWS - bottom_origin
        top_refs: list[UltraViewRef] = []
        bottom_refs: list[UltraViewRef] = []
        mover_mid = union.row * 2 + union.row_span
        for ref in blockers:
            rect = current[ref]
            block_mid = rect.row * 2 + rect.row_span
            (top_refs if block_mid <= mover_mid else bottom_refs).append(ref)
        min_span = GRID_MIN_ROW_SPAN
        if top_refs and top_span < min_span:
            bottom_refs.extend(top_refs)
            top_refs = []
        if bottom_refs and bottom_span < min_span:
            top_refs.extend(bottom_refs)
            bottom_refs = []
        packed_left = _pack_into_pocket(
            top_refs, current, top_origin, top_span, horizontal=False
        )
        packed_right = _pack_into_pocket(
            bottom_refs, current, bottom_origin, bottom_span, horizontal=False
        )
    if packed_left is None or packed_right is None:
        return (), False
    proposed.update(packed_left)
    proposed.update(packed_right)
    if not _proposed_is_legal(proposed):
        return (), False
    updates = _updates_from(current, proposed)
    return updates, bool(updates)


def _opposite_neighbors(
    mover: GridRect,
    current: Mapping[UltraViewRef, GridRect],
    mover_ref: UltraViewRef,
    *,
    side: str,
) -> list[UltraViewRef]:
    found: list[UltraViewRef] = []
    for ref, rect in current.items():
        if ref == mover_ref:
            continue
        if side in {"left", "right"} and not _axis_overlap_rows(rect, mover):
            continue
        if side in {"top", "bottom"} and not _axis_overlap_cols(rect, mover):
            continue
        if side == "left" and rect.column < mover.column:
            found.append(ref)
        elif side == "right" and rect.column + rect.column_span > mover.column + mover.column_span:
            found.append(ref)
        elif side == "top" and rect.row < mover.row:
            found.append(ref)
        elif side == "bottom" and rect.row + rect.row_span > mover.row + mover.row_span:
            found.append(ref)
    return found


def _wall_grow_wanted(
    incoming: Mapping[UltraViewRef, GridRect],
    current: Mapping[UltraViewRef, GridRect],
) -> dict[UltraViewRef, GridRect] | None:
    if len(incoming) != 1:
        return None
    ref, raw = next(iter(incoming.items()))
    origin = current[ref]
    left, top, right, bottom = _rect_overflow(raw)
    if max(left, right) >= max(top, bottom) and max(left, right) > 0:
        horizontal = True
        overflow = right if right >= left else left
        side = "left" if right >= left else "right"
    elif max(top, bottom) > 0:
        horizontal = False
        overflow = bottom if bottom >= top else top
        side = "top" if bottom >= top else "bottom"
    else:
        return None
    neighbors = _opposite_neighbors(origin, current, ref, side=side)
    if not neighbors:
        return None
    pocket_span = (
        origin.column if side == "left"
        else GRID_COLUMNS - (origin.column + origin.column_span) if side == "right"
        else origin.row if side == "top"
        else MAX_GRID_ROWS - (origin.row + origin.row_span)
    )
    yieldable = pocket_span - _min_packed_span(
        neighbors, current, horizontal=horizontal
    )
    steal = min(int(overflow), max(0, yieldable))
    if steal <= 0:
        return None
    if horizontal:
        column = origin.column - steal if side == "left" else origin.column
        column_span = origin.column_span + steal
        grown = GridRect(column, origin.row, column_span, origin.row_span)
    else:
        row = origin.row - steal if side == "top" else origin.row
        row_span = origin.row_span + steal
        grown = GridRect(origin.column, row, origin.column_span, row_span)
    grown = clamp_rect(grown)
    if grown == origin:
        return None
    return {ref: grown}


def plan_boundary_yield(
    incoming: Mapping[UltraViewRef, GridRect],
    placements: Sequence[FreeGridPlacement],
    *,
    preferred: tuple[int, int] = (0, 1),
) -> tuple[tuple[tuple[UltraViewRef, GridRect], ...], bool]:
    """Keep an out-of-board drop in-grid by clamping, then shrinking neighbours.

    Same-size avoidance runs first when the clamped slot is a new cell.
    Hitting the wall with neighbours on the opposite side grows the mover by
    stealing span those neighbours can yield down to the legal minimum.
    """
    current = {item.ref: item.rect for item in placements}
    raw = dict(incoming)
    if not raw or any(ref not in current for ref in raw):
        return (), False
    clamped = {ref: clamp_rect(rect) for ref, rect in raw.items()}
    if all(clamped[ref] == raw[ref] for ref in raw):
        return (), False
    wall_stuck = all(clamped[ref] == current[ref] for ref in raw)

    if not wall_stuck:
        updates, ok = plan_overlap_avoidance(
            clamped, placements, preferred=preferred
        )
        if ok and updates:
            return updates, True
        return plan_neighbor_shrink(clamped, placements)

    grown = _wall_grow_wanted(raw, current)
    if grown is None:
        return (), False
    shrink_updates, shrink_ok = plan_neighbor_shrink(grown, placements)
    if shrink_ok and shrink_updates:
        return shrink_updates, True
    return plan_overlap_avoidance(grown, placements, preferred=preferred)
