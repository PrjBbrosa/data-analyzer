"""Single transient interaction owner for an UltraView FreeGrid Board.

Qt-free. Page, FreeGridGesture, ToolRail, and card widgets consume projections
or send intents; they must not keep a parallel selection / tool / draft store.
``tool``, ``selection``, and ``draft`` are session-only and never enter a
persisted Board payload.

Identity is ``CardKey(UltraViewRef) | AuthorKey(object_id)``. Display titles,
short labels, and tooltips are not keys.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import uuid

from mf4_analyzer.ui.ultraview_state import (
    SAFETY_COLUMN_MAX,
    SAFETY_COLUMN_MIN,
    SAFETY_ROW_MAX,
    SAFETY_ROW_MIN,
    UltraViewRef,
    UltraViewStateError,
)

from .author_style import DEFAULT_STICKY_PALETTE, normalize_sticky_palette

TOOL_SELECT = "select"
TOOL_STICKY = "sticky"
TOOL_TEXT = "text"
TOOL_SHAPES = "shapes"
TOOL_DRAW = "draw"
KNOWN_TOOLS = frozenset(
    {TOOL_SELECT, TOOL_STICKY, TOOL_TEXT, TOOL_SHAPES, TOOL_DRAW}
)

HIT_EDITOR = "editor"
HIT_VIEWPORT_PAN = "viewport_pan"
HIT_RESIZE_HANDLE = "resize_handle"
HIT_AUTHOR = "author"
HIT_CARD = "card"
HIT_BLANK = "blank"

ESC_EDITOR = "editor"
ESC_DRAFT = "draft"
ESC_SELECT = "select"
ESC_SELECTION = "selection"


def _author_object_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UltraViewStateError("AuthorKey object_id must be a non-empty string")
    cleaned = value.strip()
    if len(cleaned) > 128:
        raise UltraViewStateError("AuthorKey object_id is too long")
    return cleaned


@dataclass(frozen=True, order=True)
class CardKey:
    """Board identity for a placed View card. ``UltraViewRef`` is the key."""

    ref: UltraViewRef

    def __post_init__(self) -> None:
        if not isinstance(self.ref, UltraViewRef):
            raise UltraViewStateError("CardKey requires an UltraViewRef")


@dataclass(frozen=True, order=True)
class AuthorKey:
    """Board identity for a persisted author object. Titles are not keys."""

    object_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "object_id", _author_object_id(self.object_id))


BoardItemKey = CardKey | AuthorKey


def card_key(ref: UltraViewRef) -> CardKey:
    return CardKey(ref)


def author_key(object_id: str) -> AuthorKey:
    return AuthorKey(object_id)


def is_card_key(item: object) -> bool:
    return isinstance(item, CardKey)


def is_author_key(item: object) -> bool:
    return isinstance(item, AuthorKey)


@dataclass(frozen=True)
class HitTarget:
    """Result of Spec I3 pointer routing. Author objects may stay inert."""

    kind: str
    item: BoardItemKey | None = None
    handle: str | None = None


STICKY_DEFAULT_WIDTH = 4.0
STICKY_DEFAULT_HEIGHT = 3.0
STICKY_MIN_WIDTH = 2.0
STICKY_MIN_HEIGHT = 1.5
STICKY_CLICK_DRAG_THRESHOLD = 0.35
STICKY_LATTICE = 0.25


def new_author_object_id() -> str:
    return uuid.uuid4().hex


def _snap_sticky(value: float) -> float:
    step = STICKY_LATTICE
    return round(float(value) / step) * step


def clamp_author_box(
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    min_width: float = STICKY_MIN_WIDTH,
    min_height: float = STICKY_MIN_HEIGHT,
) -> tuple[float, float, float, float]:
    """Keep a Sticky box inside the signed safety area at or above min size."""
    max_w = float(SAFETY_COLUMN_MAX - SAFETY_COLUMN_MIN)
    max_h = float(SAFETY_ROW_MAX - SAFETY_ROW_MIN)
    width = min(max(float(min_width), float(width)), max_w)
    height = min(max(float(min_height), float(height)), max_h)
    x = min(max(float(x), float(SAFETY_COLUMN_MIN)), float(SAFETY_COLUMN_MAX) - width)
    y = min(max(float(y), float(SAFETY_ROW_MIN)), float(SAFETY_ROW_MAX) - height)
    return (_snap_sticky(x), _snap_sticky(y), _snap_sticky(width), _snap_sticky(height))


def sticky_box_from_click(origin: tuple[float, float]) -> tuple[float, float, float, float]:
    """Default 4×3 Sticky whose origin is the click, then safety-clamped."""
    return clamp_author_box(
        origin[0], origin[1], STICKY_DEFAULT_WIDTH, STICKY_DEFAULT_HEIGHT
    )


def sticky_box_from_points(
    origin: tuple[float, float],
    current: tuple[float, float] | None,
) -> tuple[float, float, float, float]:
    """Click uses the default size; a real drag uses the axis-aligned start/end box."""
    if current is None:
        return sticky_box_from_click(origin)
    dx = abs(current[0] - origin[0])
    dy = abs(current[1] - origin[1])
    if dx < STICKY_CLICK_DRAG_THRESHOLD and dy < STICKY_CLICK_DRAG_THRESHOLD:
        return sticky_box_from_click(origin)
    x = min(origin[0], current[0])
    y = min(origin[1], current[1])
    return clamp_author_box(x, y, max(dx, STICKY_MIN_WIDTH), max(dy, STICKY_MIN_HEIGHT))


@dataclass(frozen=True)
class AuthorCreateIntent:
    """Page→coordinator create payload. Not a Board object and not a Qt type."""

    kind: str
    object_id: str
    box: tuple[float, float, float, float]
    text: str = ""
    palette: str = "yellow"


@dataclass(frozen=True)
class AuthorUpdateIntent:
    """Partial author update. Missing fields stay as they are on the Board."""

    object_id: str
    box: tuple[float, float, float, float] | None = None
    text: str | None = None
    palette: str | None = None


@dataclass(frozen=True)
class AuthorDeleteIntent:
    object_ids: tuple[str, ...]


@dataclass
class DraftGesture:
    """In-progress creation gesture. Unpersisted until the first non-empty commit."""

    tool: str
    origin: tuple[float, float] | None = None
    current: tuple[float, float] | None = None
    object_id: str | None = None
    palette: str = "yellow"


@dataclass
class TransactionBeforeState:
    """Before-image for a Board mutation. R3 only needs card stubs."""

    kind: str
    payload: object | None = None


def resolve_board_hit(
    *,
    editor_active: bool = False,
    viewport_pan: bool = False,
    resize_handle: str | None = None,
    author_hits_rev_z: Sequence[AuthorKey] = (),
    card: CardKey | None = None,
) -> HitTarget:
    """Spec I3 priority, plus viewport pan which still wins over creation tools.

    1. active text editor / popup
    2. viewport pan (middle, Space+left, right deferred pan)
    3. resize / anchor handle
    4. author object, reverse z-order
    5. card
    6. blank canvas
    """
    if editor_active:
        return HitTarget(HIT_EDITOR)
    if viewport_pan:
        return HitTarget(HIT_VIEWPORT_PAN)
    if resize_handle:
        return HitTarget(HIT_RESIZE_HANDLE, item=card, handle=str(resize_handle))
    if author_hits_rev_z:
        return HitTarget(HIT_AUTHOR, item=author_hits_rev_z[0])
    if card is not None:
        return HitTarget(HIT_CARD, item=card)
    return HitTarget(HIT_BLANK)


class BoardInteractionController:
    """Owns tool, selection, draft, hover, and transaction lifecycle.

    FreeGridGesture move/resize sessions stay on the gesture object; this
    controller owns identity selection so Page / gesture / author chrome are
    projections of one frozenset.
    """

    def __init__(self) -> None:
        self._active_tool = TOOL_SELECT
        self._pinned_tool: str | None = None
        self._selection: frozenset[BoardItemKey] = frozenset()
        self._primary_card: UltraViewRef | None = None
        self._draft: DraftGesture | None = None
        self._hover_target: BoardItemKey | None = None
        self._transaction_before: TransactionBeforeState | None = None
        self._editor_active = False
        self._guides: tuple[object, ...] = ()
        self._sticky_palette = DEFAULT_STICKY_PALETTE

    # -- tool -------------------------------------------------------------

    def active_tool(self) -> str:
        return self._active_tool

    def pinned_tool(self) -> str | None:
        return self._pinned_tool

    def set_active_tool(self, tool: str, *, pinned: bool = False) -> None:
        checked = str(tool or TOOL_SELECT)
        if checked not in KNOWN_TOOLS:
            checked = TOOL_SELECT
        self._active_tool = checked
        if pinned and checked != TOOL_SELECT:
            self._pinned_tool = checked
        elif not pinned:
            if checked == TOOL_SELECT:
                self._pinned_tool = None
        self._hover_target = None

    def arm_tool(self, tool: str) -> None:
        self.set_active_tool(tool, pinned=False)

    def pin_tool(self, tool: str) -> None:
        self.set_active_tool(tool, pinned=True)

    def sticky_palette(self) -> str:
        return self._sticky_palette

    def set_sticky_palette(self, token: str) -> None:
        self._sticky_palette = normalize_sticky_palette(token)
        if self._draft is not None and self._draft.tool == TOOL_STICKY:
            self._draft.palette = self._sticky_palette

    def _restore_tool_after_gesture(self) -> None:
        if self._pinned_tool and self._pinned_tool in KNOWN_TOOLS:
            self._active_tool = self._pinned_tool
            return
        self._active_tool = TOOL_SELECT

    # -- selection --------------------------------------------------------

    def selection(self) -> frozenset[BoardItemKey]:
        return self._selection

    def card_selection(self) -> frozenset[UltraViewRef]:
        return frozenset(item.ref for item in self._selection if isinstance(item, CardKey))

    def author_selection_ids(self) -> frozenset[str]:
        return frozenset(
            item.object_id for item in self._selection if isinstance(item, AuthorKey)
        )

    def primary_card(self) -> UltraViewRef | None:
        cards = self.card_selection()
        if not cards:
            self._primary_card = None
            return None
        if self._primary_card in cards:
            return self._primary_card
        self._primary_card = min(cards)
        return self._primary_card

    def hover_target(self) -> BoardItemKey | None:
        return self._hover_target

    def set_hover_target(self, item: BoardItemKey | None) -> None:
        self._hover_target = item

    def select_only(self, item: BoardItemKey) -> None:
        key = _checked_key(item)
        self._selection = frozenset((key,))
        self._primary_card = key.ref if isinstance(key, CardKey) else None

    def select_only_card(self, ref: UltraViewRef) -> None:
        self.select_only(CardKey(ref))

    def select_only_author(self, object_id: str) -> None:
        self.select_only(AuthorKey(object_id))

    def toggle(self, item: BoardItemKey) -> None:
        key = _checked_key(item)
        current = set(self._selection)
        if key in current:
            current.discard(key)
        else:
            current.add(key)
        self._selection = frozenset(current)
        self._refresh_primary_card()

    def toggle_card(self, ref: UltraViewRef) -> None:
        self.toggle(CardKey(ref))

    def set_selection(self, items: Iterable[BoardItemKey]) -> None:
        self._selection = frozenset(_checked_key(item) for item in items)
        self._refresh_primary_card()

    def add_to_selection(self, items: Iterable[BoardItemKey]) -> None:
        extra = frozenset(_checked_key(item) for item in items)
        self._selection = self._selection | extra
        self._refresh_primary_card()

    def add_cards_to_selection(self, refs: Iterable[UltraViewRef]) -> None:
        self.add_to_selection(CardKey(ref) for ref in refs)

    def replace_card_selection(self, refs: Iterable[UltraViewRef]) -> None:
        """Replace card keys and drop author keys (non-additive marquee)."""
        self._selection = frozenset(CardKey(ref) for ref in refs)
        self._refresh_primary_card()

    def clear_selection(self) -> bool:
        if not self._selection and self._primary_card is None:
            return False
        self._selection = frozenset()
        self._primary_card = None
        self._hover_target = None
        return True

    def clear_card_keys(self) -> bool:
        cards = [item for item in self._selection if isinstance(item, CardKey)]
        if not cards:
            if self._primary_card is None:
                return False
            self._primary_card = None
            return True
        self._selection = frozenset(
            item for item in self._selection if isinstance(item, AuthorKey)
        )
        self._primary_card = None
        return True

    def clear_author_keys(self) -> bool:
        authors = [item for item in self._selection if isinstance(item, AuthorKey)]
        if not authors:
            return False
        self._selection = frozenset(
            item for item in self._selection if isinstance(item, CardKey)
        )
        self._refresh_primary_card()
        return True

    def restrict_cards(self, wanted: Iterable[UltraViewRef]) -> None:
        allowed = set(wanted)
        self._selection = frozenset(
            item
            for item in self._selection
            if not isinstance(item, CardKey) or item.ref in allowed
        )
        self._refresh_primary_card()

    def restrict_authors(self, wanted: Iterable[str]) -> None:
        allowed = {str(item) for item in wanted if str(item)}
        self._selection = frozenset(
            item
            for item in self._selection
            if not isinstance(item, AuthorKey) or item.object_id in allowed
        )

    def _refresh_primary_card(self) -> None:
        cards = self.card_selection()
        if not cards:
            self._primary_card = None
            return
        if self._primary_card not in cards:
            self._primary_card = min(cards)

    # -- editor / draft / transaction stubs --------------------------------

    def is_editor_active(self) -> bool:
        return self._editor_active

    def set_editor_active(self, active: bool) -> None:
        self._editor_active = bool(active)
        if not self._editor_active:
            return

    def draft(self) -> DraftGesture | None:
        return self._draft

    def begin_draft(
        self,
        tool: str,
        *,
        origin: tuple[float, float] | None = None,
        object_id: str | None = None,
    ) -> DraftGesture:
        checked = str(tool or self._active_tool)
        if checked not in KNOWN_TOOLS:
            checked = self._active_tool
        palette = self._sticky_palette if checked == TOOL_STICKY else DEFAULT_STICKY_PALETTE
        self._draft = DraftGesture(
            tool=checked, origin=origin, object_id=object_id, palette=palette
        )
        if checked != TOOL_SELECT:
            self._active_tool = checked
        return self._draft

    def update_draft(self, current: tuple[float, float] | None) -> DraftGesture | None:
        if self._draft is None:
            return None
        self._draft.current = current
        return self._draft

    def cancel_draft(self) -> bool:
        if self._draft is None:
            return False
        self._draft = None
        self._restore_tool_after_gesture()
        return True

    def commit_draft(self) -> DraftGesture | None:
        """R3 stub: return the draft and clear it. No persisted mutation."""
        draft = self._draft
        self._draft = None
        self._restore_tool_after_gesture()
        return draft

    def transaction_before(self) -> TransactionBeforeState | None:
        return self._transaction_before

    def begin_transaction(
        self, kind: str, payload: object | None = None
    ) -> TransactionBeforeState:
        self._transaction_before = TransactionBeforeState(kind=str(kind), payload=payload)
        return self._transaction_before

    def commit_transaction(self) -> TransactionBeforeState | None:
        before = self._transaction_before
        self._transaction_before = None
        return before

    def cancel_transaction(self) -> TransactionBeforeState | None:
        before = self._transaction_before
        self._transaction_before = None
        return before

    def set_guides(self, guides: Iterable[object] = ()) -> None:
        self._guides = tuple(guides)

    def guides(self) -> tuple[object, ...]:
        return self._guides

    def consume_escape(self) -> str | None:
        """Spec I4: editor → draft → Select → clear selection.

        Overlay / presentation unwind stays on the Page.
        """
        if self._editor_active:
            self._editor_active = False
            return ESC_EDITOR
        if self._draft is not None:
            self.cancel_draft()
            return ESC_DRAFT
        if self._active_tool != TOOL_SELECT:
            self.set_active_tool(TOOL_SELECT)
            return ESC_SELECT
        if self._selection:
            self.clear_selection()
            return ESC_SELECTION
        return None

    def reset_session(self) -> None:
        """Board switch / clear / destroy: drop transient interaction state."""
        self.cancel_draft()
        self.cancel_transaction()
        self._editor_active = False
        self._hover_target = None
        self._guides = ()
        self._selection = frozenset()
        self._primary_card = None
        self._active_tool = TOOL_SELECT
        self._pinned_tool = None
        self._sticky_palette = DEFAULT_STICKY_PALETTE

    def transient_state(self) -> dict[str, object]:
        """Diagnostic snapshot. Must never be merged into a project payload."""
        return {
            "active_tool": self._active_tool,
            "pinned_tool": self._pinned_tool,
            "selection": tuple(sorted(_key_sort_tuple(item) for item in self._selection)),
            "draft": None if self._draft is None else self._draft.tool,
            "hover": None
            if self._hover_target is None
            else _key_sort_tuple(self._hover_target),
            "editor_active": self._editor_active,
        }


def _checked_key(item: BoardItemKey) -> BoardItemKey:
    if isinstance(item, (CardKey, AuthorKey)):
        return item
    raise UltraViewStateError("BoardItemKey must be CardKey or AuthorKey")


def _key_sort_tuple(item: BoardItemKey) -> tuple:
    if isinstance(item, CardKey):
        return ("card", item.ref.section, item.ref.view_id)
    return ("author", item.object_id)
