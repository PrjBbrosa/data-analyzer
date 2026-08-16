"""Qt-free geometry and history helpers for UltraView's controlled grid.

The screen Board and the off-screen compositor consume the same integer-grid
metrics.  No helper here knows about widgets, preview pixels, or MainWindow.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, Sequence

from mf4_analyzer.ui.ultraview_state import (
    GRID_COLUMNS,
    GRID_MAX_COLUMN_SPAN,
    GRID_MAX_ROW_SPAN,
    GRID_MIN_COLUMN_SPAN,
    GRID_MIN_ROW_SPAN,
    SAFETY_COLUMN_MAX,
    SAFETY_COLUMN_MIN,
    SAFETY_ROW_MAX,
    SAFETY_ROW_MIN,
    FreeGridPlacement,
    GridRect,
    UltraViewRef,
    clamp_grid_rect,
)

from .layouts import (
    BASE_BOARD_SIZE,
    BOARD_PADDING,
    MIN_CARD_CHROME_HEIGHT,
    SLOT_GUTTER,
)

# These are deliberately smaller than P1's reading-card floor.  A 2-column
# free-grid card is an allowed thumbnail role; the Board scrolls rather than
# reducing a column below this fixed chrome-readable width.
GRID_MIN_COLUMN_WIDTH = 96
GRID_ROW_HEIGHT = 88
GRID_MIN_VISIBLE_ROWS = 10
# Extra empty rows past the last occupied card so a 1× / fit canvas still
# has a drop target below the current layout. Export does not add these.
GRID_SPARE_ROWS = 2

Rect = tuple[int, int, int, int]

# Cell probes granted to *each* blocker the planner has to relocate, not to the
# whole plan (see ``_SearchBudget``).  A shared pool made dense-but-solvable
# boards report "no legal layout" (review 2026-08-15 P1-4).  Sized so one card
# can exhaust the *safety* board: a minimum-span card has 106×142 in-board
# origins, so ``SEARCH_CAP`` stays reserved for real give-ups rather than a
# full-board proof.
PLANNER_SEARCH_CAP = 768
LAYOUT_MOVE = "move"
LAYOUT_RESIZE = "resize"
# spec D9.7 预留，UI 整理入口未接：没有生产调用方传 "arrange"。板上的「整理」
# 走 ultraview_state.organized_placements（只压空行），不经 plan_layout，也没有
# 提交前整体预览。保留常量与 plan_neighbor_shrink 以待接线；2026-08-15 review
# §4.3 已确认现状，spec D9.7 处有对应批注。
LAYOUT_ARRANGE = "arrange"


class LayoutRejectReason(Enum):
    NO_LEGAL_LAYOUT = "no_legal_layout"
    SEARCH_CAP = "search_cap"
    SPAN_INVARIANT = "span_invariant"
    INVALID_INPUT = "invalid_input"
    OUT_OF_BOUNDS = "out_of_bounds"


@dataclass(frozen=True)
class RectTransition:
    ref: UltraViewRef
    before: GridRect
    after: GridRect


@dataclass(frozen=True)
class LayoutPlan:
    """Deterministic collision result. Widgets commit this object; they do not
    re-run grow/shrink heuristics on release."""

    accepted: bool
    reason: LayoutRejectReason | None
    mover_before: GridRect | None
    mover_after: GridRect | None
    displaced_before_after: tuple[RectTransition, ...]
    operation: str
    based_on_layout_revision: int
    mover_ref: UltraViewRef | None = None
    search_visits: int = 0

    def committed_updates(self) -> tuple[tuple[UltraViewRef, GridRect], ...]:
        if not self.accepted:
            return ()
        items: list[tuple[UltraViewRef, GridRect]] = []
        if (
            self.mover_ref is not None
            and self.mover_after is not None
            and self.mover_before != self.mover_after
        ):
            items.append((self.mover_ref, self.mover_after))
        items.extend((item.ref, item.after) for item in self.displaced_before_after)
        return tuple(items)

    def affected_count(self) -> int:
        return len(self.committed_updates())

    def preview_rects(self) -> tuple[tuple[UltraViewRef, GridRect], ...]:
        """Mover first, then displaced — the geometry ghost must paint."""
        items: list[tuple[UltraViewRef, GridRect]] = []
        if self.mover_ref is not None and self.mover_after is not None:
            items.append((self.mover_ref, self.mover_after))
        items.extend((item.ref, item.after) for item in self.displaced_before_after)
        return tuple(items)


@dataclass(frozen=True)
class GridMetrics:
    """Pixel mapping for the 12-column 1× pitch. Screen extent is separate.

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
        """Unrounded cell pitch. Use this for every grid ↔ pixel mapping."""
        base, scale = self._exact_source()
        return (
            (base.column_width + base.gutter) * scale,
            (base.row_height + base.gutter) * scale,
        )

    def exact_cell(self) -> tuple[float, float]:
        """Unrounded card cell size, i.e. pitch minus one gutter."""
        base, scale = self._exact_source()
        return (base.column_width * scale, base.row_height * scale)


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
        default=0,
    )
    if min_visible_rows is None:
        occupied_rows += GRID_SPARE_ROWS
    occupied_rows = min(SAFETY_ROW_MAX, max(floor_rows, occupied_rows))
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


def screen_grid_metrics(placements: Sequence[FreeGridPlacement]) -> GridMetrics:
    """Canonical free-grid screen metrics: same 1600-wide columns as export.

    Window size must not change column width or card aspect. Zoom scales this
    1× result uniformly via ``scale_grid_metrics``. Empty trailing rows stay
    so the user can drop beside or below existing cards.
    """
    return grid_metrics((BASE_BOARD_SIZE[0], 0), placements)


def fit_rect_for_aspect(
    origin: GridRect,
    image_size: tuple[int, int],
    metrics: GridMetrics,
    *,
    chrome_height: int = MIN_CARD_CHROME_HEIGHT,
) -> GridRect:
    """Contain the image aspect in the current card: shrink only, never grow.

    Candidates stay at the origin and may only reduce column/row span. The
    plot-area ratio (card height minus chrome) is matched first; ties keep
    the larger area so a discrete grid does not collapse to the minimum
    similar span. See spec §1 of the 2026-08-15 fit-zoom-and-dismiss design.
    """
    image_w = max(1, int(image_size[0]))
    image_h = max(1, int(image_size[1]))
    target = image_w / float(image_h)
    chrome = max(0, int(chrome_height))
    max_col = min(int(origin.column_span), GRID_MAX_COLUMN_SPAN)
    max_row = min(int(origin.row_span), GRID_MAX_ROW_SPAN)
    best: tuple[tuple[float, int], GridRect] | None = None
    for col_span in range(GRID_MIN_COLUMN_SPAN, max_col + 1):
        if int(origin.column) + col_span > SAFETY_COLUMN_MAX:
            continue
        for row_span in range(GRID_MIN_ROW_SPAN, max_row + 1):
            if int(origin.row) + row_span > SAFETY_ROW_MAX:
                continue
            candidate = GridRect(
                int(origin.column), int(origin.row), col_span, row_span
            )
            _x, _y, width, height = rect_to_pixels(candidate, metrics)
            plot_h = max(1, int(height) - chrome)
            ratio = max(1, int(width)) / float(plot_h)
            area = col_span * row_span
            key = (abs(ratio - target), -area)
            if best is None or key < best[0]:
                best = (key, candidate)
    return best[1] if best is not None else origin


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
        left = max(SAFETY_COLUMN_MIN, min(left, right - GRID_MIN_COLUMN_SPAN))
        left = max(right - GRID_MAX_COLUMN_SPAN, left)
    elif handle in _HANDLE_EAST:
        right += int(column_delta)
        right = min(SAFETY_COLUMN_MAX, max(right, left + GRID_MIN_COLUMN_SPAN))
        right = min(left + GRID_MAX_COLUMN_SPAN, right)
    if handle in _HANDLE_NORTH:
        top += int(row_delta)
        top = max(SAFETY_ROW_MIN, min(top, bottom - GRID_MIN_ROW_SPAN))
        top = max(bottom - GRID_MAX_ROW_SPAN, top)
    elif handle in _HANDLE_SOUTH:
        bottom += int(row_delta)
        bottom = min(SAFETY_ROW_MAX, max(bottom, top + GRID_MIN_ROW_SPAN))
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
_AVOID_SEARCH_LIMIT = max(
    SAFETY_COLUMN_MAX - SAFETY_COLUMN_MIN,
    SAFETY_ROW_MAX - SAFETY_ROW_MIN,
)


class _SearchBudget:
    """Bounded cell probes for one plan. Mouse-move must not search the board.

    The allowance is **per relocated blocker**, not per plan: ring search grows
    as ``2·d²``, so on a dense board the first blocker alone could eat a shared
    pool and make every later blocker report "no legal layout" when one exists
    (review 2026-08-15 P1-4: 60 × 2×2 cards + a big resize needed 587 probes in
    total and was rejected at 512/512).  Each blocker gets ``per_blocker``
    probes; nothing rolls over, so the plan stays bounded at
    ``per_blocker × number of relocated cards`` and each card enters the
    relocation queue at most once.
    """

    __slots__ = ("per_blocker", "cap", "visits", "exhausted")

    def __init__(self, per_blocker: int) -> None:
        self.per_blocker = max(1, int(per_blocker))
        self.cap = self.per_blocker
        self.visits = 0
        self.exhausted = False

    def begin_blocker(self) -> None:
        """Hand the next blocker its own allowance."""
        self.cap = self.visits + self.per_blocker

    def consume(self) -> bool:
        if self.visits >= self.cap:
            self.exhausted = True
            return False
        self.visits += 1
        return True


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
    *,
    budget: _SearchBudget | None = None,
) -> GridRect | None:
    """Same-size slot that misses ``occupied``. Prefers the drag axis, then rings.

    Only *in-board* candidates spend budget: an off-board offset is rejected by
    arithmetic, not by an occupancy probe, and charging for it made the cap
    depend on where the card happens to sit rather than on how much of the
    board was really searched.
    """
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
            if budget is not None and not budget.consume():
                return None
            if _rect_free(candidate, occupied):
                return candidate
    # Ring offsets are pruned to the ones that can land in-board at all, so the
    # loop cost tracks the budget instead of the (much larger) offset square.
    # The order in which in-board candidates are visited is unchanged.
    min_dc = SAFETY_COLUMN_MIN - int(rect.column)
    max_dc = SAFETY_COLUMN_MAX - int(rect.column_span) - int(rect.column)
    min_dr = SAFETY_ROW_MIN - int(rect.row)
    max_dr = SAFETY_ROW_MAX - int(rect.row_span) - int(rect.row)
    max_dist = (
        max(abs(min_dc), abs(max_dc)) + max(abs(min_dr), abs(max_dr)) + 1
    )
    for dist in range(1, max_dist):
        for dc in range(max(-dist, min_dc), min(dist, max_dc) + 1):
            dr_span = dist - abs(dc)
            for dr in (-dr_span, dr_span) if dr_span else (0,):
                if dr < min_dr or dr > max_dr:
                    continue
                candidate = GridRect(
                    rect.column + dc,
                    rect.row + dr,
                    rect.column_span,
                    rect.row_span,
                )
                if clamp_rect(candidate) != candidate:
                    continue
                if budget is not None and not budget.consume():
                    return None
                if _rect_free(candidate, occupied):
                    return candidate
    return None


def plan_overlap_avoidance(
    incoming: Mapping[UltraViewRef, GridRect],
    placements: Sequence[FreeGridPlacement],
    *,
    preferred: tuple[int, int] = (0, 1),
    search_cap: int = PLANNER_SEARCH_CAP,
    budget: _SearchBudget | None = None,
) -> tuple[tuple[tuple[UltraViewRef, GridRect], ...], bool]:
    """Move overlapping cards out of ``incoming``.

    Returns ``(updates, True)`` when every blocker has a same-size hole.
    Returns ``((), False)`` when a blocker is boxed in at the grid edge.
    ``updates`` lists every rect that differs from ``placements``.
    """
    search = budget if budget is not None else _SearchBudget(search_cap)
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
        search.begin_blocker()
        found = find_avoidance_rect(
            current[ref], obstacles, preferred, budget=search
        )
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
    left = max(0, SAFETY_COLUMN_MIN - int(rect.column))
    top = max(0, SAFETY_ROW_MIN - int(rect.row))
    right = max(0, int(rect.column) + int(rect.column_span) - SAFETY_COLUMN_MAX)
    bottom = max(0, int(rect.row) + int(rect.row_span) - SAFETY_ROW_MAX)
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


def _normalize_operation(operation: str) -> str:
    value = operation.value if isinstance(operation, Enum) else str(operation)
    if value not in {LAYOUT_MOVE, LAYOUT_RESIZE, LAYOUT_ARRANGE}:
        return LAYOUT_MOVE
    return value


def _force_move_spans(
    incoming: Mapping[UltraViewRef, GridRect],
    current: Mapping[UltraViewRef, GridRect],
) -> dict[UltraViewRef, GridRect]:
    forced: dict[UltraViewRef, GridRect] = {}
    for ref, rect in incoming.items():
        origin = current[ref]
        forced[ref] = GridRect(
            int(rect.column),
            int(rect.row),
            origin.column_span,
            origin.row_span,
        )
    return forced


def _spans_match(left: GridRect, right: GridRect) -> bool:
    return left.column_span == right.column_span and left.row_span == right.row_span


def _span_invariants_hold(
    operation: str,
    current: Mapping[UltraViewRef, GridRect],
    proposed: Mapping[UltraViewRef, GridRect],
    mover_ref: UltraViewRef,
) -> bool:
    for ref, rect in proposed.items():
        origin = current.get(ref)
        if origin is None:
            return False
        if operation == LAYOUT_MOVE and not _spans_match(rect, origin):
            return False
        if operation == LAYOUT_RESIZE and ref != mover_ref and not _spans_match(rect, origin):
            return False
    return True


def _empty_plan(
    *,
    accepted: bool,
    reason: LayoutRejectReason | None,
    operation: str,
    layout_revision: int,
    mover_ref: UltraViewRef | None = None,
    mover_before: GridRect | None = None,
    mover_after: GridRect | None = None,
    displaced: tuple[RectTransition, ...] = (),
    search_visits: int = 0,
) -> LayoutPlan:
    return LayoutPlan(
        accepted=accepted,
        reason=reason,
        mover_before=mover_before,
        mover_after=mover_after,
        displaced_before_after=displaced,
        operation=operation,
        based_on_layout_revision=int(layout_revision),
        mover_ref=mover_ref,
        search_visits=search_visits,
    )


def _plan_from_updates(
    current: Mapping[UltraViewRef, GridRect],
    mover_ref: UltraViewRef,
    updates: Sequence[tuple[UltraViewRef, GridRect]],
    operation: str,
    layout_revision: int,
    search_visits: int,
) -> LayoutPlan:
    by_ref = dict(updates)
    mover_before = current[mover_ref]
    mover_after = by_ref.get(mover_ref, mover_before)
    displaced = tuple(
        sorted(
            (
                RectTransition(ref, current[ref], after)
                for ref, after in updates
                if ref != mover_ref
            ),
            key=lambda item: (
                item.before.row,
                item.before.column,
                item.ref.section,
                item.ref.view_id,
            ),
        )
    )
    proposed = dict(current)
    proposed.update(by_ref)
    if not _span_invariants_hold(operation, current, proposed, mover_ref):
        return _empty_plan(
            accepted=False,
            reason=LayoutRejectReason.SPAN_INVARIANT,
            operation=operation,
            layout_revision=layout_revision,
            mover_ref=mover_ref,
            mover_before=mover_before,
            mover_after=mover_after,
            search_visits=search_visits,
        )
    return LayoutPlan(
        accepted=True,
        reason=None,
        mover_before=mover_before,
        mover_after=mover_after,
        displaced_before_after=displaced,
        operation=operation,
        based_on_layout_revision=int(layout_revision),
        mover_ref=mover_ref,
        search_visits=search_visits,
    )


def plan_layout(
    placements: Sequence[FreeGridPlacement],
    mover_ref: UltraViewRef,
    target: GridRect,
    operation: str,
    *,
    layout_revision: int = 0,
    preferred: tuple[int, int] | None = None,
    search_cap: int = PLANNER_SEARCH_CAP,
    incoming: Mapping[UltraViewRef, GridRect] | None = None,
) -> LayoutPlan:
    """Pure size-preserving collision plan for move/resize (arrange may shrink).

    Does not write widgets, emit signals, or push undo. Same inputs yield the
    same displacement order. Search is capped at ``search_cap`` cell probes.
    """
    op = _normalize_operation(operation)
    current = {item.ref: item.rect for item in placements}
    if mover_ref not in current:
        return _empty_plan(
            accepted=False,
            reason=LayoutRejectReason.INVALID_INPUT,
            operation=op,
            layout_revision=layout_revision,
            mover_ref=mover_ref,
        )
    raw = dict(incoming) if incoming else {mover_ref: target}
    if mover_ref not in raw:
        raw[mover_ref] = target
    if any(ref not in current for ref in raw):
        return _empty_plan(
            accepted=False,
            reason=LayoutRejectReason.INVALID_INPUT,
            operation=op,
            layout_revision=layout_revision,
            mover_ref=mover_ref,
            mover_before=current[mover_ref],
        )
    if op == LAYOUT_MOVE:
        raw = _force_move_spans(raw, current)
    elif op == LAYOUT_RESIZE:
        for ref, rect in tuple(raw.items()):
            if ref != mover_ref:
                origin = current[ref]
                raw[ref] = GridRect(
                    rect.column, rect.row, origin.column_span, origin.row_span
                )
    origin = current[mover_ref]
    axis = preferred or avoidance_preferred_delta(origin, raw[mover_ref])
    budget = _SearchBudget(search_cap)

    out_of_bounds = any(clamp_rect(rect) != rect for rect in raw.values())
    if out_of_bounds:
        return _empty_plan(
            accepted=False,
            reason=LayoutRejectReason.OUT_OF_BOUNDS,
            operation=op,
            layout_revision=layout_revision,
            mover_ref=mover_ref,
            mover_before=origin,
            mover_after=clamp_rect(raw[mover_ref]),
            search_visits=budget.visits,
        )
    wanted = dict(raw)
    if op != LAYOUT_ARRANGE and not _span_invariants_hold(op, current, wanted, mover_ref):
        return _empty_plan(
            accepted=False,
            reason=LayoutRejectReason.SPAN_INVARIANT,
            operation=op,
            layout_revision=layout_revision,
            mover_ref=mover_ref,
            mover_before=origin,
            mover_after=wanted.get(mover_ref),
            search_visits=budget.visits,
        )

    updates, ok = plan_overlap_avoidance(
        wanted, placements, preferred=axis, budget=budget
    )
    if ok:
        if not updates and all(wanted[ref] == current[ref] for ref in wanted):
            return _plan_from_updates(
                current, mover_ref, (), op, layout_revision, budget.visits
            )
        plan = _plan_from_updates(
            current, mover_ref, updates, op, layout_revision, budget.visits
        )
        if plan.accepted:
            return plan
        return _empty_plan(
            accepted=False,
            reason=plan.reason or LayoutRejectReason.SPAN_INVARIANT,
            operation=op,
            layout_revision=layout_revision,
            mover_ref=mover_ref,
            mover_before=origin,
            mover_after=wanted[mover_ref],
            search_visits=budget.visits,
        )

    if op == LAYOUT_ARRANGE:
        shrink_updates, shrink_ok = plan_neighbor_shrink(wanted, placements)
        if shrink_ok and shrink_updates:
            return _plan_from_updates(
                current,
                mover_ref,
                shrink_updates,
                op,
                layout_revision,
                budget.visits,
            )

    reason = (
        LayoutRejectReason.SEARCH_CAP
        if budget.exhausted
        else LayoutRejectReason.NO_LEGAL_LAYOUT
    )
    return _empty_plan(
        accepted=False,
        reason=reason,
        operation=op,
        layout_revision=layout_revision,
        mover_ref=mover_ref,
        mover_before=origin,
        mover_after=wanted[mover_ref],
        search_visits=budget.visits,
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

    **spec D9.7 预留，UI 整理入口未接**：唯一调用点是 ``plan_layout`` 的
    ``LAYOUT_ARRANGE`` 分支，而没有生产代码传 ``"arrange"``——普通 move/resize
    永远不缩邻卡，这是 D9.2 的硬契约。接线（含提交前整体预览）不在
    2026-08-15 修复批范围。
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
        left_origin, left_span = SAFETY_COLUMN_MIN, union.column - SAFETY_COLUMN_MIN
        right_origin = union.column + union.column_span
        right_span = SAFETY_COLUMN_MAX - right_origin
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
        top_origin, top_span = SAFETY_ROW_MIN, union.row - SAFETY_ROW_MIN
        bottom_origin = union.row + union.row_span
        bottom_span = SAFETY_ROW_MAX - bottom_origin
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
        origin.column - SAFETY_COLUMN_MIN if side == "left"
        else SAFETY_COLUMN_MAX - (origin.column + origin.column_span) if side == "right"
        else origin.row - SAFETY_ROW_MIN if side == "top"
        else SAFETY_ROW_MAX - (origin.row + origin.row_span)
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
