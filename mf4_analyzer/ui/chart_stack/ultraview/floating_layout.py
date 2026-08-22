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
RAIL_WIDTH_DESKTOP = 64
RAIL_WIDTH_COMPACT = 52
RAIL_WIDTH = RAIL_WIDTH_DESKTOP
COMPACT_STAGE_WIDTH = 900
COMPACT_STAGE_HEIGHT = 640
RAIL_TO_CANVAS_GAP = 18
ISLAND_HEIGHT = 40
ISLAND_GAP = 12
OVERLAY_GAP = 8

BOARD_ISLAND_MAX_WIDTH = 240
GLOBAL_ISLAND_WIDTH = 116
STATUS_ISLAND_WIDTH = 200
NAVIGATION_ISLAND_WIDTH = 268
RAIL_CONTENT_HEIGHT = 268
DEFAULT_OVERLAY_SIZE: Size = (280, 384)
DEFAULT_MINIMAP_SIZE: Size = (172, 112)
DEFAULT_CARD_CONTEXT_SIZE: Size = (232, ISLAND_HEIGHT)
# Intrinsic navigation island width: 4px margins + five 32px buttons + 42px
# zoom label + six 2px gaps. Must stay in lockstep with NavigationIsland.
NAVIGATION_ISLAND_INTRINSIC_WIDTH = 4 + 32 * 5 + 42 + 2 * 6 + 4
DEFAULT_NAVIGATION_ISLAND_SIZE: Size = (
    min(NAVIGATION_ISLAND_WIDTH, NAVIGATION_ISLAND_INTRINSIC_WIDTH),
    ISLAND_HEIGHT,
)
OVERLAY_ANCHOR_RAIL = "rail"
OVERLAY_ANCHOR_GLOBAL = "global"


def is_compact_stage(stage_size: Size) -> bool:
    """800×560 and other short/narrow stages use the compact rail."""
    width = _integer(stage_size[0] if stage_size else 0)
    height = _integer(stage_size[1] if stage_size and len(stage_size) > 1 else 0)
    return width < COMPACT_STAGE_WIDTH or height < COMPACT_STAGE_HEIGHT


def rail_width_for_stage(stage_size: Size) -> int:
    return RAIL_WIDTH_COMPACT if is_compact_stage(stage_size) else RAIL_WIDTH_DESKTOP


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

    def inflate(self, amount: int) -> "Rect":
        """Expand on all sides. Negative amounts fall back to ``inset``."""
        margin = _integer(amount)
        if margin < 0:
            return self.inset(-margin)
        return Rect(
            self.x - margin,
            self.y - margin,
            self.width + 2 * margin,
            self.height + 2 * margin,
        )


@dataclass(frozen=True)
class CardContextPlacement:
    """A bounded card-action island and its selected placement strategy."""

    rect: Rect
    edge: str


@dataclass(frozen=True)
class MinimapPlacementFacts:
    """Qt-free inputs for minimap candidate selection.

    Selection/toolbar/editor rectangles are already in stage coordinates and,
    for selection, already inflated by handle/hit margin.  This policy never
    reads preview pixels, walks widgets, or persists a placement.
    """

    stage: Rect
    board_island: Rect
    global_island: Rect
    status_island: Rect
    navigation_island: Rect
    rail: Rect
    avoid: tuple[Rect, ...] = ()
    gesture_active: bool = False
    size: Size | None = DEFAULT_MINIMAP_SIZE


@dataclass(frozen=True)
class FloatingLayout:
    """One CanvasHost layout pass, expressed entirely in stage coordinates.

    ``board`` is the full-bleed scroll host so zoom/pan can travel under the
    floating chrome.  ``fit`` is the chrome-safe 1× parking rect: the same
    inset the previous Board allocation used, so 1× still keeps cards clear
    of the rail and top islands. 适应 uses a taller fill (same left, stage-safe
    top and bottom) so floating chrome does not shrink the panel.
    """

    stage: Rect
    rail: Rect
    board: Rect
    fit: Rect
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
    overlay_anchor: str = OVERLAY_ANCHOR_RAIL,
    minimap_size: Size | None = DEFAULT_MINIMAP_SIZE,
    board_island_size: Size | None = None,
    global_island_size: Size | None = None,
    status_island_size: Size | None = None,
    navigation_island_size: Size | None = None,
    rail_size: Size | None = None,
    trigger_rect: Rect | None = None,
) -> FloatingLayout:
    """Calculate narrow-rail CanvasHost geometry without changing board space.

    An open overlay is intentionally omitted from the Board allocation.  It is
    an on-demand sibling of the scroll area, so merely opening a library or a
    menu cannot reflow cards, change viewport size, or alter zoom.

    ``trigger_rect``, when given with the rail anchor, is the stage-relative
    rectangle of the rail button that opened the overlay: the overlay's y is
    anchored to that button instead of always hugging BoardIsland's bottom
    edge, then clamped into the safe band between BoardIsland and
    NavigationIsland so it can never climb onto either island.
    """
    stage = stage_rect(stage_size)
    safe = stage.inset(SAFE_MARGIN)
    board = stage
    rail_width = rail_width_for_stage(stage_size)

    # Cards still park to the rail's right so Fit keeps the canvas clear of
    # the tool strip.  Persistent left islands instead share the stage-safe
    # left axis; their vertical separation keeps them clear of that strip.
    content_left = min(safe.right, safe.left + rail_width + RAIL_TO_CANVAS_GAP)
    content_top = min(safe.bottom, safe.top + ISLAND_HEIGHT + ISLAND_GAP)

    island_height = min(ISLAND_HEIGHT, safe.height)
    global_width = min(
        _length(global_island_size[0]) if global_island_size is not None else GLOBAL_ISLAND_WIDTH,
        safe.width,
    )
    global_island = Rect(safe.right - global_width, safe.top, global_width, island_height)

    max_board_island_width = max(0, global_island.left - ISLAND_GAP - safe.left)
    board_width = min(
        BOARD_ISLAND_MAX_WIDTH,
        max_board_island_width,
        _length(board_island_size[0]) if board_island_size is not None else BOARD_ISLAND_MAX_WIDTH,
    )
    board_island = Rect(
        safe.left,
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

    status_max_width = max(0, navigation_island.left - ISLAND_GAP - safe.left)
    status_width = min(
        status_max_width,
        _length(status_island_size[0]) if status_island_size is not None else STATUS_ISLAND_WIDTH,
    )
    status_island = Rect(
        safe.left,
        bottom_y,
        status_width,
        bottom_island_height,
    ).clamp_to(safe)

    # The rail sits centered between BoardIsland and StatusIsland, but on
    # short stages naive centering can push it past either island's edge.
    # Separate it as a real construction guarantee: shrink to the band those
    # two islands leave open (never producing a taller rail than fits), then
    # clamp the centered position into that band rather than into the full
    # safe stage.
    rail_band_top = min(safe.bottom, board_island.bottom + ISLAND_GAP)
    rail_band_bottom = max(rail_band_top, status_island.top - ISLAND_GAP)
    rail_band_height = max(0, rail_band_bottom - rail_band_top)
    requested_rail_height = (
        _length(rail_size[1]) if rail_size is not None else RAIL_CONTENT_HEIGHT
    )
    rail_height = min(safe.height, requested_rail_height, rail_band_height)
    rail_top = safe.top + (safe.height - rail_height) // 2
    rail_top = min(max(rail_top, rail_band_top), rail_band_bottom - rail_height)
    rail = Rect(
        safe.left,
        rail_top,
        min(rail_width, safe.width),
        rail_height,
    ).clamp_to(safe)

    fit_bottom = max(content_top, navigation_island.top - OVERLAY_GAP)
    fit = Rect(
        content_left,
        content_top,
        max(0, safe.right - content_left),
        max(0, fit_bottom - content_top),
    )
    minimap = place_minimap(
        MinimapPlacementFacts(
            stage=stage,
            board_island=board_island,
            global_island=global_island,
            status_island=status_island,
            navigation_island=navigation_island,
            rail=rail,
            size=minimap_size,
        )
    )
    overlay = (
        _place_overlay(
            safe,
            rail,
            board_island,
            global_island,
            navigation_island,
            overlay_size,
            overlay_anchor=overlay_anchor,
            trigger_rect=trigger_rect,
        )
        if overlay_open
        else None
    )
    return FloatingLayout(
        stage=stage,
        rail=rail,
        board=board,
        fit=fit,
        board_island=board_island,
        global_island=global_island,
        status_island=status_island,
        navigation_island=navigation_island,
        minimap=minimap,
        overlay=overlay,
        content_inset_bottom=max(0, board.bottom - fit.bottom),
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


def _overlay_anchor(value: object) -> str:
    text = str(value or OVERLAY_ANCHOR_RAIL).strip().lower()
    if text == OVERLAY_ANCHOR_GLOBAL:
        return OVERLAY_ANCHOR_GLOBAL
    return OVERLAY_ANCHOR_RAIL


def _place_overlay(
    safe: Rect,
    rail: Rect,
    board_island: Rect,
    global_island: Rect,
    navigation_island: Rect,
    size: Size,
    *,
    overlay_anchor: str = OVERLAY_ANCHOR_RAIL,
    trigger_rect: Rect | None = None,
) -> Rect:
    width, height = _size(size)
    if _overlay_anchor(overlay_anchor) == OVERLAY_ANCHOR_GLOBAL:
        return _place_global_overlay(
            safe, board_island, global_island, navigation_island, width, height
        )
    x = min(safe.right, rail.right + OVERLAY_GAP)
    max_width = max(0, safe.right - x)
    width = min(width, max_width)

    # Default anchor (no trigger given): hug BoardIsland's bottom edge, same
    # as before trigger-following was added.
    min_y = min(safe.bottom, board_island.bottom + ISLAND_GAP)
    max_y = max(min_y, navigation_island.top - OVERLAY_GAP - height)
    if trigger_rect is not None and (trigger_rect.width > 0 and trigger_rect.height > 0):
        anchor_y = trigger_rect.top + (trigger_rect.height - height) // 2
    else:
        anchor_y = min_y
    y = min(max(anchor_y, min_y), max_y)

    max_height = max(0, navigation_island.top - OVERLAY_GAP - y)
    height = min(height, max_height)
    return Rect(x, y, width, height).clamp_to(safe)


@dataclass(frozen=True)
class OverlayAnchorFacts:
    """Adjacency/clamp facts for a rail-anchored overlay.

    A tall panel may be safe-rect clamped so its center cannot sit on the
    trigger.  The satisfiable contract is: the trigger center lies in the
    overlay's visible vertical span, or the nearest overlay edge stays
    adjacent, and the overlay sits to the right of the rail.
    """

    trigger_center_in_span: bool
    vertically_adjacent: bool
    horizontally_right_of_rail: bool
    clamp_reason: str | None
    center_error_y: int
    nearest_edge_gap_y: int
    requested_height: int
    placed_height: int


def overlay_anchor_facts(
    overlay: Rect,
    trigger: Rect,
    rail: Rect,
    *,
    requested_height: int | None = None,
    board_island: Rect | None = None,
    navigation_island: Rect | None = None,
    adjacent_px: int = ISLAND_GAP,
) -> OverlayAnchorFacts:
    """Describe how a placed overlay relates to its rail trigger.

    ``center_error_y`` is recorded for diagnostics; callers must not treat
    it as a pass/fail budget when the panel was clamped.
    """
    requested = _length(requested_height if requested_height is not None else overlay.height)
    trigger_cy = trigger.top + trigger.height // 2
    overlay_cy = overlay.top + overlay.height // 2
    in_span = overlay.height > 0 and overlay.top <= trigger_cy < overlay.bottom
    if in_span:
        nearest_gap = 0
    elif trigger_cy < overlay.top:
        nearest_gap = overlay.top - trigger.bottom
    else:
        nearest_gap = trigger.top - overlay.bottom
    adjacency = max(0, _length(adjacent_px))
    vertically_adjacent = in_span or nearest_gap <= adjacency
    unconstrained_y = trigger.top + (trigger.height - requested) // 2
    clamp_reason: str | None = None
    if overlay.height < requested:
        clamp_reason = "height_clamped_to_safe_band"
    elif overlay.y != unconstrained_y:
        nav_ceiling = (
            navigation_island.top - OVERLAY_GAP - overlay.height
            if navigation_island is not None
            else None
        )
        board_floor = (
            board_island.bottom + ISLAND_GAP if board_island is not None else None
        )
        if nav_ceiling is not None and overlay.y >= nav_ceiling:
            clamp_reason = "navigation_ceiling"
        elif board_floor is not None and overlay.y <= board_floor:
            clamp_reason = "safe_rect_vertical"
        else:
            clamp_reason = "safe_rect_vertical"
    return OverlayAnchorFacts(
        trigger_center_in_span=in_span,
        vertically_adjacent=vertically_adjacent,
        horizontally_right_of_rail=overlay.left >= rail.right,
        clamp_reason=clamp_reason,
        center_error_y=abs(overlay_cy - trigger_cy),
        nearest_edge_gap_y=nearest_gap,
        requested_height=requested,
        placed_height=overlay.height,
    )


def _place_global_overlay(
    safe: Rect,
    board_island: Rect,
    global_island: Rect,
    navigation_island: Rect,
    width: int,
    height: int,
) -> Rect:
    """Right-align an overlay under GlobalIsland; never fall back to the rail."""
    y = min(safe.bottom, global_island.bottom + ISLAND_GAP)
    max_height = max(0, navigation_island.top - OVERLAY_GAP - y)
    height = min(height, max_height)
    width = min(width, safe.width)
    placed = Rect(global_island.right - width, y, width, height).clamp_to(safe)
    if placed.intersects(board_island):
        y = min(safe.bottom, max(placed.y, board_island.bottom + ISLAND_GAP))
        max_height = max(0, navigation_island.top - OVERLAY_GAP - y)
        placed = Rect(placed.x, y, placed.width, min(placed.height, max_height)).clamp_to(safe)
    if placed.intersects(board_island):
        x = min(safe.right, board_island.right + OVERLAY_GAP)
        max_width = max(0, safe.right - x)
        placed = Rect(x, placed.y, min(placed.width, max_width), placed.height).clamp_to(safe)
    return placed


def _rect_key(rect: Rect | None) -> tuple[int, int, int, int] | None:
    if rect is None or rect.width <= 0 or rect.height <= 0:
        return None
    return (rect.x, rect.y, rect.width, rect.height)


def minimap_placement_fingerprint(facts: MinimapPlacementFacts) -> tuple:
    """Stable identity for stage/safe/chrome/selection/gesture — not pointer samples."""
    size = None if facts.size is None else _size(facts.size)
    avoid = tuple(_rect_key(item) for item in facts.avoid)
    return (
        _rect_key(facts.stage),
        _rect_key(facts.board_island),
        _rect_key(facts.global_island),
        _rect_key(facts.status_island),
        _rect_key(facts.navigation_island),
        _rect_key(facts.rail),
        avoid,
        bool(facts.gesture_active),
        size,
    )


def place_minimap(facts: MinimapPlacementFacts) -> Rect | None:
    """Choose a safe minimap rect or ``None`` so the map folds into overview.

    Candidates are tried in a stable order: bottom-right above Navigation,
    then top-right below GlobalIsland.  The top-left Board Island is never a
    candidate.  Geometry gestures hide the map entirely; pointer-move samples
    are not an input, so they cannot chatter the result.
    """
    if facts.gesture_active or facts.size is None:
        return None
    width, height = _size(facts.size)
    if width <= 0 or height <= 0:
        return None
    safe = facts.stage.inset(SAFE_MARGIN)
    width = min(width, safe.width)
    if width <= 0:
        return None
    blockers = tuple(
        item
        for item in (
            facts.board_island,
            facts.global_island,
            facts.status_island,
            facts.navigation_island,
            facts.rail,
            *facts.avoid,
        )
        if item.width > 0 and item.height > 0
    )

    def _fits(rect: Rect | None) -> Rect | None:
        if rect is None or rect.width <= 0 or rect.height <= 0:
            return None
        if (
            rect.left < safe.left
            or rect.top < safe.top
            or rect.right > safe.right
            or rect.bottom > safe.bottom
        ):
            return None
        if rect.intersects(facts.board_island):
            return None
        if any(rect.intersects(item) for item in blockers):
            return None
        return rect

    def _right_aligned(top: int, bottom: int) -> Rect | None:
        band = max(0, bottom - top)
        fitted_height = min(height, band)
        if fitted_height <= 0:
            return None
        return Rect(
            safe.right - width,
            bottom - fitted_height,
            width,
            fitted_height,
        ).clamp_to(safe)

    nav_ceiling = facts.navigation_island.top - OVERLAY_GAP
    bottom_right = _right_aligned(safe.top, nav_ceiling)
    fitted = _fits(bottom_right)
    if fitted is not None:
        return fitted

    top_right_top = max(safe.top, facts.global_island.bottom + OVERLAY_GAP)
    # Sit just under GlobalIsland rather than sliding along the band.
    top_band = max(0, nav_ceiling - top_right_top)
    top_height = min(height, top_band)
    top_right = None
    if top_height > 0:
        top_right = Rect(
            safe.right - width,
            top_right_top,
            width,
            top_height,
        ).clamp_to(safe)
    return _fits(top_right)


__all__ = [
    "BOARD_ISLAND_MAX_WIDTH",
    "DEFAULT_CARD_CONTEXT_SIZE",
    "DEFAULT_NAVIGATION_ISLAND_SIZE",
    "DEFAULT_MINIMAP_SIZE",
    "DEFAULT_OVERLAY_SIZE",
    "GLOBAL_ISLAND_WIDTH",
    "ISLAND_HEIGHT",
    "NAVIGATION_ISLAND_WIDTH",
    "OVERLAY_ANCHOR_GLOBAL",
    "OVERLAY_ANCHOR_RAIL",
    "RAIL_CONTENT_HEIGHT",
    "RAIL_WIDTH",
    "RAIL_WIDTH_COMPACT",
    "RAIL_WIDTH_DESKTOP",
    "SAFE_MARGIN",
    "is_compact_stage",
    "rail_width_for_stage",
    "STATUS_ISLAND_WIDTH",
    "CardContextPlacement",
    "FloatingLayout",
    "MinimapPlacementFacts",
    "OverlayAnchorFacts",
    "Rect",
    "calculate_floating_layout",
    "minimap_placement_fingerprint",
    "overlay_anchor_facts",
    "place_card_context",
    "place_minimap",
    "stage_rect",
]
