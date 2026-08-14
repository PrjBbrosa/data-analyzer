"""Qt-free placement for UltraView's narrow-rail floating chrome.

This module owns only transient, page-relative rectangles.  It does not know
about widgets, Board state, previews, scroll bars, or persistence; callers map
the resulting integer rectangles to their Qt counterparts.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import TypeAlias


Size: TypeAlias = tuple[int, int]

SAFE_MARGIN = 12
RAIL_WIDTH = 48
RAIL_TO_CANVAS_GAP = 18
ISLAND_HEIGHT = 40
ISLAND_GAP = 12
OVERLAY_GAP = 8

BOARD_ISLAND_MAX_WIDTH = 240
GLOBAL_ISLAND_WIDTH = 116
STATUS_ISLAND_WIDTH = 200
NAVIGATION_ISLAND_WIDTH = 268
RAIL_CONTENT_HEIGHT = 160
DEFAULT_OVERLAY_SIZE: Size = (280, 384)
DEFAULT_MINIMAP_SIZE: Size = (172, 112)
DEFAULT_CARD_CONTEXT_SIZE: Size = (232, ISLAND_HEIGHT)


def _integer(value: object, *, default: int = 0) -> int:
    """Convert finite numeric input to an integer without leaking ValueError."""
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not isfinite(numeric):
        return default
    return int(numeric)


def _length(value: object) -> int:
    return max(0, _integer(value))


def _size(value: object) -> Size:
    try:
        width, height = value  # type: ignore[misc]
    except (TypeError, ValueError):
        return (0, 0)
    return (_length(width), _length(height))


@dataclass(frozen=True)
class Rect:
    """Small immutable integer rectangle with bounded, Qt-independent helpers."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", _integer(self.x))
        object.__setattr__(self, "y", _integer(self.y))
        object.__setattr__(self, "width", _length(self.width))
        object.__setattr__(self, "height", _length(self.height))

    @property
    def left(self) -> int:
        return self.x

    @property
    def top(self) -> int:
        return self.y

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def inset(self, amount: int) -> "Rect":
        """Return an inward-safe rect, collapsing rather than going negative."""
        margin = _length(amount)
        horizontal = min(margin, self.width)
        vertical = min(margin, self.height)
        return Rect(
            self.x + horizontal,
            self.y + vertical,
            max(0, self.width - 2 * margin),
            max(0, self.height - 2 * margin),
        )

    def clamp_to(self, bounds: "Rect") -> "Rect":
        """Keep this rectangle completely inside ``bounds`` without negatives."""
        width = min(self.width, bounds.width)
        height = min(self.height, bounds.height)
        x = min(max(self.x, bounds.left), bounds.right - width)
        y = min(max(self.y, bounds.top), bounds.bottom - height)
        return Rect(x, y, width, height)

    def intersects(self, other: "Rect") -> bool:
        """Return whether two positive-area rectangles overlap."""
        return (
            self.width > 0
            and self.height > 0
            and other.width > 0
            and other.height > 0
            and self.left < other.right
            and other.left < self.right
            and self.top < other.bottom
            and other.top < self.bottom
        )


@dataclass(frozen=True)
class CardContextPlacement:
    """A bounded card-action island and its selected placement strategy."""

    rect: Rect
    edge: str


@dataclass(frozen=True)
class FloatingLayout:
    """One CanvasHost layout pass, expressed entirely in stage coordinates.

    ``board`` deliberately sits underneath the floating chrome.  Reserving
    vertical space for every island would make the documented 1190×700 canvas
    target impossible at a 1280×800 stage; the islands instead avoid one
    another while the Board remains a continuous canvas below them.
    """

    stage: Rect
    rail: Rect
    board: Rect
    board_island: Rect
    global_island: Rect
    status_island: Rect
    navigation_island: Rect
    minimap: Rect | None
    overlay: Rect | None
    content_inset_bottom: int = 0

    @property
    def chrome_rects(self) -> tuple[Rect, ...]:
        """Persistent sibling overlays that must not obscure one another."""
        rects = (
            self.rail,
            self.board_island,
            self.global_island,
            self.status_island,
            self.navigation_island,
        )
        return rects if self.minimap is None else (*rects, self.minimap)

    @property
    def persistent_rects(self) -> tuple[Rect, ...]:
        """All geometry retained after a layout pass, including the canvas."""
        return (self.board, *self.chrome_rects)


def stage_rect(stage_size: Size) -> Rect:
    """Return a nonnegative stage rooted at the CanvasHost origin."""
    width, height = _size(stage_size)
    return Rect(0, 0, width, height)


def calculate_floating_layout(
    stage_size: Size,
    *,
    overlay_open: bool = False,
    overlay_size: Size = DEFAULT_OVERLAY_SIZE,
    minimap_size: Size | None = DEFAULT_MINIMAP_SIZE,
    board_island_size: Size | None = None,
    global_island_size: Size | None = None,
    status_island_size: Size | None = None,
    navigation_island_size: Size | None = None,
    rail_size: Size | None = None,
) -> FloatingLayout:
    """Calculate narrow-rail CanvasHost geometry without changing board space.

    An open overlay is intentionally omitted from the Board allocation.  It is
    an on-demand sibling of the scroll area, so merely opening a library or a
    menu cannot reflow cards, change viewport size, or alter zoom.
    """
    stage = stage_rect(stage_size)
    safe = stage.inset(SAFE_MARGIN)

    board_left = min(safe.right, safe.left + RAIL_WIDTH + RAIL_TO_CANVAS_GAP)
    # Keep a real top safety lane for the Board/global islands.  Letting the
    # scroll host start at y=12 technically maximises pixels, but the first
    # card title/status then lives underneath the floating controls.  At the
    # two supported compact sizes this 52px lane still exceeds the documented
    # Board viewport floors (1190x700 / 710x470).
    board_top = min(safe.bottom, safe.top + ISLAND_HEIGHT + ISLAND_GAP)
    board = Rect(
        board_left,
        board_top,
        max(0, safe.right - board_left),
        max(0, safe.bottom - board_top),
    )

    island_height = min(ISLAND_HEIGHT, safe.height)
    global_width = min(
        _length(global_island_size[0]) if global_island_size is not None else GLOBAL_ISLAND_WIDTH,
        safe.width,
    )
    global_island = Rect(safe.right - global_width, safe.top, global_width, island_height)

    max_board_island_width = max(0, global_island.left - ISLAND_GAP - board.left)
    board_width = min(
        BOARD_ISLAND_MAX_WIDTH,
        max_board_island_width,
        _length(board_island_size[0]) if board_island_size is not None else BOARD_ISLAND_MAX_WIDTH,
    )
    board_island = Rect(
        board.left,
        safe.top,
        board_width,
        island_height,
    ).clamp_to(safe)

    bottom_island_height = min(ISLAND_HEIGHT, safe.height)
    bottom_y = safe.bottom - bottom_island_height
    navigation_width = min(
        _length(navigation_island_size[0]) if navigation_island_size is not None else NAVIGATION_ISLAND_WIDTH,
        safe.width,
    )
    navigation_island = Rect(
        safe.right - navigation_width,
        bottom_y,
        navigation_width,
        bottom_island_height,
    ).clamp_to(safe)

    status_max_width = max(0, navigation_island.left - ISLAND_GAP - board.left)
    status_width = min(
        status_max_width,
        _length(status_island_size[0]) if status_island_size is not None else STATUS_ISLAND_WIDTH,
    )
    status_island = Rect(
        board.left,
        bottom_y,
        status_width,
        bottom_island_height,
    ).clamp_to(safe)

    rail_top = min(safe.bottom, board_island.bottom + ISLAND_GAP)
    rail_available = max(0, status_island.top - ISLAND_GAP - rail_top)
    rail_height = min(
        rail_available,
        _length(rail_size[1]) if rail_size is not None else RAIL_CONTENT_HEIGHT,
    )
    rail = Rect(
        safe.left,
        rail_top,
        min(RAIL_WIDTH, safe.width),
        rail_height,
    ).clamp_to(safe)

    minimap = _place_minimap(safe, navigation_island, minimap_size)
    overlay = (
        _place_overlay(safe, rail, board_island, navigation_island, overlay_size)
        if overlay_open
        else None
    )
    return FloatingLayout(
        stage=stage,
        rail=rail,
        board=board,
        board_island=board_island,
        global_island=global_island,
        status_island=status_island,
        navigation_island=navigation_island,
        minimap=minimap,
        overlay=overlay,
        content_inset_bottom=min(ISLAND_HEIGHT + OVERLAY_GAP, max(0, board.height // 4)),
    )


def place_card_context(
    stage_size: Size,
    card: Rect,
    *,
    size: Size = DEFAULT_CARD_CONTEXT_SIZE,
    gap: int = OVERLAY_GAP,
    avoid: tuple[Rect, ...] = (),
) -> CardContextPlacement:
    """Place a selected-card action island above, below, or inside the card.

    The preferred location is above the card.  When that would cross the safe
    edge, it flips below.  If neither side has room, the island is clamped to
    the card's inside top edge, preserving an actionable, bounded target.
    Persistent chrome rectangles in ``avoid`` are skipped so the strip cannot
    sit on top of Board/Global/navigation islands.
    """
    stage = stage_rect(stage_size)
    safe = stage.inset(SAFE_MARGIN)
    requested_width, requested_height = _size(size)
    width = min(requested_width, safe.width)
    height = min(requested_height, safe.height)
    bounded_card = card.clamp_to(safe)
    spacing = _length(gap)
    preferred_x = bounded_card.left + (bounded_card.width - width) // 2
    blockers = tuple(item for item in avoid if item.width > 0 and item.height > 0)

    def _clear(rect: Rect) -> Rect | None:
        placed = rect.clamp_to(safe)
        if placed.width <= 0 or placed.height <= 0:
            return None
        if any(placed.intersects(item) for item in blockers):
            return None
        return placed

    above = Rect(preferred_x, bounded_card.top - spacing - height, width, height)
    if above.top >= safe.top:
        placed = _clear(above)
        if placed is not None:
            return CardContextPlacement(placed, "above")

    below = Rect(preferred_x, bounded_card.bottom + spacing, width, height)
    if below.bottom <= safe.bottom:
        placed = _clear(below)
        if placed is not None:
            return CardContextPlacement(placed, "below")

    inside = Rect(preferred_x, bounded_card.top + spacing, width, height)
    placed = _clear(inside)
    if placed is not None:
        return CardContextPlacement(placed, "inside")

    nudged = inside.clamp_to(safe)
    for item in blockers:
        if nudged.intersects(item):
            candidate = Rect(
                nudged.x,
                min(max(item.bottom + spacing, safe.top), max(safe.top, bounded_card.bottom - height)),
                nudged.width,
                nudged.height,
            ).clamp_to(safe)
            cleared = _clear(candidate)
            if cleared is not None:
                return CardContextPlacement(cleared, "inside")
            nudged = candidate
    return CardContextPlacement(nudged, "inside")


def _place_overlay(
    safe: Rect,
    rail: Rect,
    board_island: Rect,
    navigation_island: Rect,
    size: Size,
) -> Rect:
    width, height = _size(size)
    x = min(safe.right, rail.right + OVERLAY_GAP)
    y = min(safe.bottom, board_island.bottom + ISLAND_GAP)
    max_width = max(0, safe.right - x)
    max_height = max(0, navigation_island.top - OVERLAY_GAP - y)
    return Rect(x, y, min(width, max_width), min(height, max_height)).clamp_to(safe)


def _place_minimap(
    safe: Rect, navigation_island: Rect, size: Size | None
) -> Rect | None:
    if size is None:
        return None
    width, height = _size(size)
    max_height = max(0, navigation_island.top - OVERLAY_GAP - safe.top)
    width = min(width, safe.width)
    height = min(height, max_height)
    if width == 0 or height == 0:
        # In short canvases minimap folds into the overview action instead of
        # creating a zero-sized overlap target.
        return None
    return Rect(
        safe.right - width,
        navigation_island.top - OVERLAY_GAP - height,
        width,
        height,
    ).clamp_to(safe)


__all__ = [
    "BOARD_ISLAND_MAX_WIDTH",
    "DEFAULT_CARD_CONTEXT_SIZE",
    "DEFAULT_MINIMAP_SIZE",
    "DEFAULT_OVERLAY_SIZE",
    "GLOBAL_ISLAND_WIDTH",
    "ISLAND_HEIGHT",
    "NAVIGATION_ISLAND_WIDTH",
    "RAIL_CONTENT_HEIGHT",
    "RAIL_WIDTH",
    "SAFE_MARGIN",
    "STATUS_ISLAND_WIDTH",
    "CardContextPlacement",
    "FloatingLayout",
    "Rect",
    "calculate_floating_layout",
    "place_card_context",
    "stage_rect",
]
