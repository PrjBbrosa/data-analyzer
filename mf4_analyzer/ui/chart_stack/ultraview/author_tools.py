"""Single transient interaction owner for an UltraView FreeGrid Board.

Qt-free. Page, FreeGridGesture, ToolRail, and card widgets consume projections
or send intents; they must not keep a parallel selection / tool / draft store.
``tool``, ``selection``, and ``draft`` are session-only and never enter a
persisted Board payload.

Identity is ``CardKey(UltraViewRef) | AuthorKey(object_id)``. Display titles,
short labels, and tooltips are not keys.
"""
from __future__ import annotations

from dataclasses import dataclass, field
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

from .author_geometry import (
    clamp_stroke_point,
    filter_stroke_samples,
    lasso_is_usable,
    persist_stroke_points,
    pixels_to_board_point,
    point_in_lasso,
)
from .author_style import DEFAULT_STICKY_PALETTE, DEFAULT_INK_PALETTE, normalize_ink_palette, normalize_sticky_palette

TOOL_SELECT = "select"
TOOL_STICKY = "sticky"
TOOL_TEXT = "text"
TOOL_SHAPES = "shapes"
TOOL_CONNECTOR = "connector"
TOOL_DRAW = "draw"
KNOWN_TOOLS = frozenset(
    {TOOL_SELECT, TOOL_STICKY, TOOL_TEXT, TOOL_SHAPES, TOOL_CONNECTOR, TOOL_DRAW}
)
POINTER_MODE_MOUSE = "mouse"
POINTER_MODE_LASER = "laser"
KNOWN_POINTER_MODES = frozenset({POINTER_MODE_MOUSE, POINTER_MODE_LASER})

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


def normalize_pointer_mode(value: object) -> str:
    checked = str(value or POINTER_MODE_MOUSE)
    return checked if checked in KNOWN_POINTER_MODES else POINTER_MODE_MOUSE


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
TEXT_DEFAULT_WIDTH = 6.0
TEXT_DEFAULT_HEIGHT = 1.0
TEXT_MIN_WIDTH = 2.0
TEXT_MIN_HEIGHT = 1.0
TEXT_CLICK_DRAG_THRESHOLD = 0.35
SHAPE_DEFAULT_WIDTH = 4.0
SHAPE_DEFAULT_HEIGHT = 3.0
SHAPE_MIN_WIDTH = 2.0
SHAPE_MIN_HEIGHT = 1.5
SHAPE_CLICK_DRAG_THRESHOLD = 0.35
CLOSED_SHAPE_TYPES = (
    "rectangle",
    "rounded_rectangle",
    "oval",
    "rhombus",
    "triangle",
)
SHAPE_CORNER_TYPES = frozenset({"rectangle", "rounded_rectangle"})
SHAPE_STROKE_WIDTHS = (1, 2, 4, 8)
SHAPE_CORNERS = (0, 8, 16, 24)
SHAPE_FILL_PALETTES = (
    None,
    "yellow",
    "orange",
    "red",
    "pink",
    "purple",
    "blue",
    "teal",
    "green",
)
SHAPE_STROKE_PALETTES = (
    "ink",
    "yellow",
    "orange",
    "red",
    "pink",
    "purple",
    "blue",
    "teal",
    "green",
)
SHAPE_LINE_STYLES = ("solid", "dashed")
DEFAULT_SHAPE = "rectangle"
CONNECTOR_TYPES = ("line", "arrow", "elbow_arrow")
DEFAULT_CONNECTOR = "arrow"
CONNECTOR_STROKE_WIDTHS = SHAPE_STROKE_WIDTHS
CONNECTOR_STROKE_PALETTES = SHAPE_STROKE_PALETTES
CONNECTOR_LINE_STYLES = SHAPE_LINE_STYLES
CONNECTOR_HEADS = ("none", "arrow")
CONNECTOR_CLICK_DRAG_THRESHOLD = 0.35
DRAW_INK_SUBTOOLS = ("pen", "highlighter")
DRAW_ERASER = "eraser"
DRAW_LASSO = "lasso"
DRAW_SUBTOOLS = (*DRAW_INK_SUBTOOLS, DRAW_ERASER, DRAW_LASSO)
DEFAULT_DRAW_SUBTOOL = "pen"
STROKE_LIVE_MAX_SAMPLES = 8_192
STROKE_WIDTH_MIN = 1
STROKE_WIDTH_MAX = 64


@dataclass(frozen=True)
class DrawPreset:
    """One Pen/Highlighter chip: palette name plus 1× pixel width."""

    palette: str
    width_px_100: int


DEFAULT_DRAW_PRESETS: dict[str, tuple[DrawPreset, ...]] = {
    "pen": (
        DrawPreset("ink", 2),
        DrawPreset("blue", 4),
        DrawPreset("red", 8),
    ),
    "highlighter": (
        DrawPreset("yellow", 8),
        DrawPreset("green", 12),
        DrawPreset("pink", 16),
    ),
}


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
    snap: bool = True,
) -> tuple[float, float, float, float]:
    """Keep a Sticky box inside the signed safety area at or above min size."""
    max_w = float(SAFETY_COLUMN_MAX - SAFETY_COLUMN_MIN)
    max_h = float(SAFETY_ROW_MAX - SAFETY_ROW_MIN)
    width = min(max(float(min_width), float(width)), max_w)
    height = min(max(float(min_height), float(height)), max_h)
    x = min(max(float(x), float(SAFETY_COLUMN_MIN)), float(SAFETY_COLUMN_MAX) - width)
    y = min(max(float(y), float(SAFETY_ROW_MIN)), float(SAFETY_ROW_MAX) - height)
    if not snap:
        return (float(x), float(y), float(width), float(height))
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


def text_box_from_click(origin: tuple[float, float]) -> tuple[float, float, float, float]:
    """Default 6×1 auto-width text box whose origin is the click, then safety-clamped."""
    return clamp_author_box(
        origin[0],
        origin[1],
        TEXT_DEFAULT_WIDTH,
        TEXT_DEFAULT_HEIGHT,
        min_width=TEXT_MIN_WIDTH,
        min_height=TEXT_MIN_HEIGHT,
    )


def text_box_from_points(
    origin: tuple[float, float],
    current: tuple[float, float] | None,
) -> tuple[float, float, float, float]:
    """Click uses the default width; a real drag sets wrap width and min height."""
    if current is None:
        return text_box_from_click(origin)
    dx = abs(current[0] - origin[0])
    dy = abs(current[1] - origin[1])
    if dx < TEXT_CLICK_DRAG_THRESHOLD and dy < TEXT_CLICK_DRAG_THRESHOLD:
        return text_box_from_click(origin)
    x = min(origin[0], current[0])
    y = min(origin[1], current[1])
    return clamp_author_box(
        x,
        y,
        max(dx, TEXT_MIN_WIDTH),
        max(dy, TEXT_MIN_HEIGHT),
        min_width=TEXT_MIN_WIDTH,
        min_height=TEXT_MIN_HEIGHT,
    )


def resize_text_box(
    box: tuple[float, float, float, float],
    handle: str,
    dx: float,
    dy: float,
) -> tuple[float, float, float, float]:
    """East/west change wrap width; north/south change minimum height."""
    x, y, width, height = box
    x2, y2 = x + width, y + height
    if "w" in handle:
        x = x + dx
    if "e" in handle:
        x2 = x2 + dx
    if "n" in handle:
        y = y + dy
    if "s" in handle:
        y2 = y2 + dy
    return clamp_author_box(
        min(x, x2),
        min(y, y2),
        abs(x2 - x),
        abs(y2 - y),
        min_width=TEXT_MIN_WIDTH,
        min_height=TEXT_MIN_HEIGHT,
    )


def _shape_clamp(
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    snap: bool,
) -> tuple[float, float, float, float]:
    return clamp_author_box(
        x,
        y,
        width,
        height,
        min_width=SHAPE_MIN_WIDTH,
        min_height=SHAPE_MIN_HEIGHT,
        snap=snap,
    )


def shape_box_from_click(
    origin: tuple[float, float],
    *,
    snap: bool = True,
) -> tuple[float, float, float, float]:
    """Default 4×3 closed shape whose origin is the click, then safety-clamped."""
    return _shape_clamp(
        origin[0], origin[1], SHAPE_DEFAULT_WIDTH, SHAPE_DEFAULT_HEIGHT, snap=snap
    )


def shape_box_from_points(
    origin: tuple[float, float],
    current: tuple[float, float] | None,
    *,
    keep_aspect: bool = False,
    from_center: bool = False,
    snap: bool = True,
) -> tuple[float, float, float, float]:
    """Click uses the default 4×3; a real drag uses start/end with modifiers."""
    if current is None:
        if from_center:
            return _shape_clamp(
                origin[0] - SHAPE_DEFAULT_WIDTH / 2.0,
                origin[1] - SHAPE_DEFAULT_HEIGHT / 2.0,
                SHAPE_DEFAULT_WIDTH,
                SHAPE_DEFAULT_HEIGHT,
                snap=snap,
            )
        return shape_box_from_click(origin, snap=snap)
    dx = current[0] - origin[0]
    dy = current[1] - origin[1]
    if abs(dx) < SHAPE_CLICK_DRAG_THRESHOLD and abs(dy) < SHAPE_CLICK_DRAG_THRESHOLD:
        if from_center:
            return _shape_clamp(
                origin[0] - SHAPE_DEFAULT_WIDTH / 2.0,
                origin[1] - SHAPE_DEFAULT_HEIGHT / 2.0,
                SHAPE_DEFAULT_WIDTH,
                SHAPE_DEFAULT_HEIGHT,
                snap=snap,
            )
        return shape_box_from_click(origin, snap=snap)
    if from_center:
        width = max(abs(dx) * 2.0, SHAPE_MIN_WIDTH)
        height = max(abs(dy) * 2.0, SHAPE_MIN_HEIGHT)
        if keep_aspect:
            side = max(width, height)
            width = height = side
        return _shape_clamp(
            origin[0] - width / 2.0,
            origin[1] - height / 2.0,
            width,
            height,
            snap=snap,
        )
    if keep_aspect:
        side = max(abs(dx), abs(dy), SHAPE_MIN_WIDTH, SHAPE_MIN_HEIGHT)
        x = origin[0] if dx >= 0.0 else origin[0] - side
        y = origin[1] if dy >= 0.0 else origin[1] - side
        return _shape_clamp(x, y, side, side, snap=snap)
    x = min(origin[0], current[0])
    y = min(origin[1], current[1])
    return _shape_clamp(
        x, y, max(abs(dx), SHAPE_MIN_WIDTH), max(abs(dy), SHAPE_MIN_HEIGHT), snap=snap
    )


def resize_shape_box(
    box: tuple[float, float, float, float],
    handle: str,
    dx: float,
    dy: float,
    *,
    keep_aspect: bool = False,
    from_center: bool = False,
    snap: bool = True,
) -> tuple[float, float, float, float]:
    """Eight-handle resize, plus ``move``. Shift keeps aspect; Alt scales from center."""
    x, y, width, height = box
    if handle == "move":
        return _shape_clamp(x + dx, y + dy, width, height, snap=snap)
    x2, y2 = x + width, y + height
    checked = str(handle or "")
    if from_center:
        if "w" in checked:
            x = x - dx
            x2 = x2 + dx
        if "e" in checked:
            x = x - dx
            x2 = x2 + dx
        if "n" in checked:
            y = y - dy
            y2 = y2 + dy
        if "s" in checked:
            y = y - dy
            y2 = y2 + dy
    else:
        if "w" in checked:
            x = x + dx
        if "e" in checked:
            x2 = x2 + dx
        if "n" in checked:
            y = y + dy
        if "s" in checked:
            y2 = y2 + dy
    new_w = abs(x2 - x)
    new_h = abs(y2 - y)
    left = min(x, x2)
    top = min(y, y2)
    if keep_aspect and height > 0.0:
        ratio = width / height
        if checked in {"n", "s"}:
            new_w = new_h * ratio
        elif checked in {"e", "w"}:
            new_h = new_w / ratio if ratio else new_h
        elif abs(dx) * height >= abs(dy) * width:
            new_h = new_w / ratio if ratio else new_h
        else:
            new_w = new_h * ratio
        if "w" in checked:
            left = (x2 if not from_center else (x + x2) / 2.0 + new_w / 2.0) - new_w
            if from_center:
                left = (box[0] + box[2] / 2.0) - new_w / 2.0
        elif "e" in checked or checked in {"n", "s"}:
            if from_center:
                left = (box[0] + box[2] / 2.0) - new_w / 2.0
        if "n" in checked:
            if from_center:
                top = (box[1] + box[3] / 2.0) - new_h / 2.0
            elif not from_center:
                top = y2 - new_h if y2 >= y else y - new_h
        elif from_center:
            top = (box[1] + box[3] / 2.0) - new_h / 2.0
    return _shape_clamp(left, top, new_w, new_h, snap=snap)


def default_shape_corner(shape: str) -> int:
    return 8 if str(shape) == "rounded_rectangle" else 0


def normalize_closed_shape(shape: object) -> str | None:
    checked = str(shape or "")
    if checked == "diamond":
        return "rhombus"
    if checked in CLOSED_SHAPE_TYPES:
        return checked
    return None


def normalize_connector_type(kind: object) -> str | None:
    checked = str(kind or "")
    if checked in {"elbow", "elbow-arrow", "orthogonal"}:
        return "elbow_arrow"
    if checked in {"straight", "straight_line"}:
        return "line"
    if checked in CONNECTOR_TYPES:
        return checked
    return None


def connector_style_from_type(kind: object) -> dict[str, str]:
    checked = normalize_connector_type(kind) or DEFAULT_CONNECTOR
    if checked == "line":
        return {"route": "straight", "start_head": "none", "end_head": "none"}
    if checked == "elbow_arrow":
        return {"route": "elbow", "start_head": "none", "end_head": "arrow"}
    return {"route": "straight", "start_head": "none", "end_head": "arrow"}


def connector_type_from_style(*, route: object, end_head: object) -> str:
    if str(route) == "elbow":
        return "elbow_arrow"
    if str(end_head) == "none":
        return "line"
    return "arrow"


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
    locked: bool | None = None
    font_size: int | str | None = None
    shape: str | None = None


@dataclass(frozen=True)
class TextCreateIntent:
    """Typed Text create. Coordinator must not treat this as a generic dict."""

    object_id: str
    box: tuple[float, float, float, float]
    text: str = ""
    font_role: str = "sans"
    font_size: int = 14
    bold: bool = False
    italic: bool = False
    underline: bool = False
    align: str = "left"
    list_style: str = "none"
    text_palette: str = "ink"
    fill_palette: str | None = None
    opacity: int = 100
    link: str | None = None


@dataclass(frozen=True)
class TextUpdateIntent:
    """Partial Text update. Missing fields stay as they are on the Board."""

    object_id: str
    box: tuple[float, float, float, float] | None = None
    text: str | None = None
    font_role: str | None = None
    font_size: int | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    align: str | None = None
    list_style: str | None = None
    text_palette: str | None = None
    fill_palette: str | None = None
    opacity: int | None = None
    link: object = None
    locked: bool | None = None
    clear_link: bool = False


@dataclass(frozen=True)
class ShapeCreateIntent:
    """Typed closed-shape create. Coordinator must not treat this as a generic dict."""

    object_id: str
    box: tuple[float, float, float, float]
    shape: str = DEFAULT_SHAPE
    text: str = ""
    fill_palette: str | None = None
    stroke_palette: str = "ink"
    stroke_width: int = 1
    line_style: str = "solid"
    corner_radius: int | None = None
    locked: bool = False


@dataclass(frozen=True)
class ShapeUpdateIntent:
    """Partial closed-shape update. Missing fields stay as they are on the Board."""

    object_id: str
    box: tuple[float, float, float, float] | None = None
    shape: str | None = None
    text: str | None = None
    fill_palette: object = None
    stroke_palette: str | None = None
    stroke_width: int | None = None
    line_style: str | None = None
    corner_radius: int | None = None
    locked: bool | None = None
    clear_fill: bool = False


@dataclass(frozen=True)
class ConnectorCreateIntent:
    """Typed connector create. Identity is AnchorTarget / free point, never a label."""

    object_id: str
    start: tuple[float, float]
    end: tuple[float, float]
    connector_type: str = DEFAULT_CONNECTOR
    start_target: object = None
    end_target: object = None
    route: str | None = None
    elbow_bias: float | None = None
    line_style: str = "solid"
    stroke_palette: str = "ink"
    stroke_width: int = 1
    start_head: str | None = None
    end_head: str | None = None
    text: str = ""
    locked: bool = False


@dataclass(frozen=True)
class ConnectorUpdateIntent:
    """Partial connector update. Missing fields stay as they are on the Board."""

    object_id: str
    start: tuple[float, float] | None = None
    end: tuple[float, float] | None = None
    start_target: object = None
    end_target: object = None
    route: str | None = None
    elbow_bias: float | None = None
    line_style: str | None = None
    stroke_palette: str | None = None
    stroke_width: int | None = None
    start_head: str | None = None
    end_head: str | None = None
    text: str | None = None
    locked: bool | None = None
    clear_start_target: bool = False
    clear_end_target: bool = False
    font_size: int | None = None
    align: str | None = None
    text_palette: str | None = None


@dataclass(frozen=True)
class AuthorDeleteIntent:
    object_ids: tuple[str, ...]


@dataclass(frozen=True)
class StrokeUpdateIntent:
    """Partial stroke update. Missing fields stay as they are on the Board."""

    object_id: str
    points: tuple[tuple[float, float], ...] | None = None
    tool: str | None = None
    palette: str | None = None
    width_px_100: int | None = None
    locked: bool | None = None


@dataclass(frozen=True)
class AuthorBatchStyleIntent:
    """Apply one toolbar style key to many objects as a single mutation."""

    object_ids: tuple[str, ...]
    key: str
    value: object = True


@dataclass(frozen=True)
class AuthorAlignIntent:
    object_ids: tuple[str, ...]
    alignment: str


@dataclass(frozen=True)
class AuthorDistributeIntent:
    object_ids: tuple[str, ...]
    axis: str


@dataclass(frozen=True)
class AuthorDuplicateIntent:
    object_ids: tuple[str, ...]


@dataclass(frozen=True)
class AuthorLockIntent:
    object_ids: tuple[str, ...]
    locked: bool | None = None


@dataclass(frozen=True)
class AuthorZOrderIntent:
    object_ids: tuple[str, ...]
    direction: str


@dataclass(frozen=True)
class AuthorNudgeIntent:
    object_ids: tuple[str, ...]
    dx: float
    dy: float


@dataclass(frozen=True)
class AuthorClipboardPayload:
    """Typed copy payload. Display labels are never identity keys."""

    objects: tuple[dict, ...]


@dataclass(frozen=True)
class AuthorPasteIntent:
    payload: AuthorClipboardPayload
    dx: float = 1.0
    dy: float = 1.0


@dataclass(frozen=True)
class SelectionDeleteIntent:
    """Author delete plus card Unplaced, recorded as one history entry."""

    author_ids: tuple[str, ...]
    card_refs: tuple[UltraViewRef, ...] = ()


@dataclass(frozen=True)
class SelectionNudgeIntent:
    author_ids: tuple[str, ...]
    card_refs: tuple[UltraViewRef, ...]
    dx: float
    dy: float


@dataclass(frozen=True)
class StrokeCreateIntent:
    """Typed stroke create. Points are Board coordinates, never event samples."""

    object_id: str
    points: tuple[tuple[float, float], ...]
    tool: str = DEFAULT_DRAW_SUBTOOL
    palette: str = DEFAULT_INK_PALETTE
    width_px_100: int = 2
    locked: bool = False


@dataclass
class DraftGesture:
    """In-progress creation gesture. Unpersisted until the first non-empty commit."""

    tool: str
    origin: tuple[float, float] | None = None
    current: tuple[float, float] | None = None
    object_id: str | None = None
    palette: str = "yellow"
    shape: str = DEFAULT_SHAPE
    connector: str = DEFAULT_CONNECTOR
    start_target: object | None = None
    awaiting_end: bool = False
    points: list[tuple[float, float]] = field(default_factory=list)
    subtool: str = DEFAULT_DRAW_SUBTOOL
    width_px_100: int = 2
    paused: bool = False
    erased_ids: list[str] = field(default_factory=list)
    hit_index: tuple[object, ...] = ()
    additive: bool = False


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
    handle_item: BoardItemKey | None = None,
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
        return HitTarget(
            HIT_RESIZE_HANDLE,
            item=handle_item if handle_item is not None else card,
            handle=str(resize_handle),
        )
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
        self._pointer_mode = POINTER_MODE_MOUSE
        self._pinned_tool: str | None = None
        self._selection: frozenset[BoardItemKey] = frozenset()
        self._primary_card: UltraViewRef | None = None
        self._draft: DraftGesture | None = None
        self._hover_target: BoardItemKey | None = None
        self._transaction_before: TransactionBeforeState | None = None
        self._editor_active = False
        self._guides: tuple[object, ...] = ()
        self._sticky_palette = DEFAULT_STICKY_PALETTE
        self._text_format = TextCreateIntent(object_id="format", box=(0.0, 0.0, 1.0, 1.0))
        self._last_shape = DEFAULT_SHAPE
        self._shape_format = ShapeCreateIntent(object_id="format", box=(0.0, 0.0, 1.0, 1.0))
        self._last_connector = DEFAULT_CONNECTOR
        self._connector_format = ConnectorCreateIntent(
            object_id="format", start=(0.0, 0.0), end=(1.0, 1.0)
        )
        self._last_draw_subtool = DEFAULT_DRAW_SUBTOOL
        self._draw_preset_index = 0
        self._draw_style = StrokeCreateIntent(object_id="format", points=())
        self._clipboard: AuthorClipboardPayload | None = None
        self._geometry_sessions: dict[str, dict[str, object] | None] = {
            TOOL_TEXT: None,
            TOOL_SHAPES: None,
            TOOL_CONNECTOR: None,
        }

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

    def pointer_mode(self) -> str:
        return self._pointer_mode

    def set_pointer_mode(self, mode: str) -> str:
        self._pointer_mode = normalize_pointer_mode(mode)
        return self._pointer_mode

    def activate_pointer_mode(self, mode: str) -> str:
        """Enter Select with a cursor-only pointer appearance.

        Mouse and Laser share one Select interaction state.  Leaving a
        creation tool follows Select's existing draft-cancel rule, while a
        Mouse/Laser appearance switch deliberately keeps selection and its
        resize handles intact.
        """
        if self._active_tool != TOOL_SELECT and self._draft is not None:
            self.cancel_draft()
        self.set_pointer_mode(mode)
        self.set_active_tool(TOOL_SELECT, pinned=False)
        return self._pointer_mode

    def is_laser_active(self) -> bool:
        return self._active_tool == TOOL_SELECT and self._pointer_mode == POINTER_MODE_LASER

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

    def text_format(self) -> TextCreateIntent:
        return self._text_format

    def set_text_format(self, **changes: object) -> TextCreateIntent:
        """Replace remembered whole-box Text style. Unknown keys are ignored."""
        current = self._text_format
        allowed = {
            "font_role": current.font_role,
            "font_size": current.font_size,
            "bold": current.bold,
            "italic": current.italic,
            "underline": current.underline,
            "align": current.align,
            "list_style": current.list_style,
            "text_palette": current.text_palette,
            "fill_palette": current.fill_palette,
            "opacity": current.opacity,
            "link": current.link,
        }
        for key, value in changes.items():
            if key in allowed:
                allowed[key] = value
        self._text_format = TextCreateIntent(
            object_id=current.object_id,
            box=current.box,
            text=current.text,
            **allowed,
        )
        return self._text_format

    def last_shape(self) -> str:
        return self._last_shape

    def set_last_shape(self, shape: str) -> str:
        checked = normalize_closed_shape(shape) or DEFAULT_SHAPE
        self._last_shape = checked
        if self._draft is not None and self._draft.tool == TOOL_SHAPES:
            self._draft.shape = checked
        return checked

    def shape_format(self) -> ShapeCreateIntent:
        return self._shape_format

    def set_shape_format(self, **changes: object) -> ShapeCreateIntent:
        current = self._shape_format
        allowed = {
            "shape": current.shape,
            "fill_palette": current.fill_palette,
            "stroke_palette": current.stroke_palette,
            "stroke_width": current.stroke_width,
            "line_style": current.line_style,
            "corner_radius": current.corner_radius,
        }
        for key, value in changes.items():
            if key in allowed:
                allowed[key] = value
        shape = normalize_closed_shape(allowed["shape"]) or current.shape
        allowed["shape"] = shape
        self._last_shape = shape
        self._shape_format = ShapeCreateIntent(
            object_id=current.object_id,
            box=current.box,
            text=current.text,
            **allowed,
        )
        return self._shape_format

    def last_connector(self) -> str:
        return self._last_connector

    def set_last_connector(self, kind: str) -> str:
        checked = normalize_connector_type(kind) or DEFAULT_CONNECTOR
        self._last_connector = checked
        if self._draft is not None and self._draft.tool == TOOL_CONNECTOR:
            self._draft.connector = checked
        return checked

    def connector_format(self) -> ConnectorCreateIntent:
        return self._connector_format

    def set_connector_format(self, **changes: object) -> ConnectorCreateIntent:
        current = self._connector_format
        allowed = {
            "connector_type": current.connector_type,
            "route": current.route,
            "line_style": current.line_style,
            "stroke_palette": current.stroke_palette,
            "stroke_width": current.stroke_width,
            "start_head": current.start_head,
            "end_head": current.end_head,
        }
        for key, value in changes.items():
            if key in allowed:
                allowed[key] = value
        kind = normalize_connector_type(allowed["connector_type"]) or current.connector_type
        allowed["connector_type"] = kind
        self._last_connector = kind
        self._connector_format = ConnectorCreateIntent(
            object_id=current.object_id,
            start=current.start,
            end=current.end,
            **allowed,
        )
        return self._connector_format

    def last_draw_subtool(self) -> str:
        return self._last_draw_subtool

    def is_draw_ink(self) -> bool:
        return is_draw_ink_subtool(self._last_draw_subtool)

    def is_eraser(self) -> bool:
        return self._last_draw_subtool == DRAW_ERASER

    def is_lasso(self) -> bool:
        return self._last_draw_subtool == DRAW_LASSO

    def draw_preset_index(self) -> int:
        return self._draw_preset_index

    def draw_style(self) -> StrokeCreateIntent:
        return self._draw_style

    def set_draw_style(
        self,
        *,
        tool: str | None = None,
        palette: str | None = None,
        width_px_100: int | None = None,
        preset_index: int | None = None,
    ) -> StrokeCreateIntent:
        subtool = normalize_draw_subtool(tool) if tool is not None else self._last_draw_subtool
        current = self._draw_style
        width = current.width_px_100 if width_px_100 is None else _clamp_stroke_width(width_px_100)
        ink = current.palette if palette is None else normalize_ink_palette(palette)
        self._last_draw_subtool = subtool
        if preset_index is not None:
            presets = DEFAULT_DRAW_PRESETS.get(subtool, ())
            if 0 <= int(preset_index) < len(presets):
                self._draw_preset_index = int(preset_index)
        self._draw_style = StrokeCreateIntent(
            object_id=current.object_id,
            points=current.points,
            tool=subtool,
            palette=ink,
            width_px_100=width,
        )
        if self._draft is not None and self._draft.tool == TOOL_DRAW:
            self._draft.subtool = subtool
            self._draft.palette = ink
            self._draft.width_px_100 = width
        return self._draw_style

    def pointer_sample_from_event(self, event, metrics, *, origin_offset=(0.0, 0.0)):
        """Normalize mouse/tablet events to a Board point. Pressure/tilt are ignored."""
        pos = event.pos() if hasattr(event, "pos") else event
        try:
            x = float(pos.x()) if hasattr(pos, "x") else float(pos[0])
            y = float(pos.y()) if hasattr(pos, "y") else float(pos[1])
        except (TypeError, ValueError, IndexError, AttributeError):
            return None
        return pixels_to_board_point((x, y), metrics, origin_offset=origin_offset)

    def pause_draw_samples(self) -> None:
        if self._draft is not None and self._draft.tool == TOOL_DRAW:
            self._draft.paused = True

    def resume_draw_samples(self) -> None:
        if self._draft is not None and self._draft.tool == TOOL_DRAW:
            self._draft.paused = False

    def append_draw_sample(
        self, point: tuple[float, float] | None, metrics, *, dpr: float = 1.0
    ) -> str | None:
        """Accept one live Board sample. Returns a named stop code or ``None``."""
        draft = self._draft
        if draft is None or draft.tool != TOOL_DRAW or draft.paused or point is None:
            return None
        parsed = clamp_stroke_point(point)
        if parsed is None:
            return None
        if draft.points:
            pair = filter_stroke_samples((draft.points[-1], parsed), metrics, dpr=dpr)
            if len(pair) < 2:
                return None
            parsed = pair[-1]
        draft.points.append(parsed)
        draft.current = parsed
        if len(draft.points) >= STROKE_LIVE_MAX_SAMPLES:
            return "stroke_sample_limit"
        return None

    def persist_draft_stroke(self, metrics, *, dpr: float = 1.0) -> tuple[tuple[float, float], ...]:
        draft = self._draft
        if draft is None or draft.tool != TOOL_DRAW or not is_draw_ink_subtool(draft.subtool):
            return ()
        return persist_stroke_points(draft.points, metrics, dpr=dpr)

    def arm_eraser_index(self, records: Iterable[object]) -> None:
        draft = self._draft
        if draft is None or draft.subtool != DRAW_ERASER:
            return
        draft.hit_index = tuple(records)
        draft.erased_ids = []

    def note_eraser_hits(self, object_ids: Iterable[str]) -> None:
        draft = self._draft
        if draft is None or draft.subtool != DRAW_ERASER:
            return
        seen = set(draft.erased_ids)
        for object_id in object_ids:
            text = str(object_id or "")
            if text and text not in seen:
                seen.add(text)
                draft.erased_ids.append(text)

    def finish_lasso_selection(
        self, items: Iterable[BoardItemKey], *, additive: bool
    ) -> None:
        keys = tuple(_checked_key(item) for item in items)
        if additive:
            self.add_to_selection(keys)
        else:
            self.set_selection(keys)
        self.commit_draft()
        self.set_active_tool(TOOL_SELECT)

    def _restore_tool_after_gesture(self) -> None:
        if self._pinned_tool and self._pinned_tool in KNOWN_TOOLS:
            self._active_tool = self._pinned_tool
            return
        if self._active_tool == TOOL_DRAW:
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

    def geometry_session(self, tool: str) -> dict[str, object] | None:
        return self._geometry_sessions.get(str(tool))

    def set_geometry_session(self, tool: str, session: dict[str, object] | None) -> None:
        checked = str(tool)
        if checked in self._geometry_sessions:
            self._geometry_sessions[checked] = session

    def clear_geometry_sessions(self) -> None:
        for tool in self._geometry_sessions:
            self._geometry_sessions[tool] = None

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

    def clipboard(self) -> AuthorClipboardPayload | None:
        """Session-only typed copy buffer. Survives Board switch, not save."""
        return self._clipboard

    def set_clipboard(self, payload: AuthorClipboardPayload | None) -> None:
        self._clipboard = payload

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
        draw = self._draw_style
        if checked == TOOL_DRAW:
            palette = draw.palette
        self._draft = DraftGesture(
            tool=checked,
            origin=origin,
            object_id=object_id,
            palette=palette,
            shape=self._last_shape,
            connector=self._last_connector,
            subtool=self._last_draw_subtool,
            width_px_100=draw.width_px_100,
        )
        if checked == TOOL_DRAW and origin is not None:
            parsed = clamp_stroke_point(origin)
            if parsed is not None:
                self._draft.points.append(parsed)
                self._draft.current = parsed
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
        self._pointer_mode = POINTER_MODE_MOUSE
        self._pinned_tool = None
        self._sticky_palette = DEFAULT_STICKY_PALETTE
        self._text_format = TextCreateIntent(object_id="format", box=(0.0, 0.0, 1.0, 1.0))
        self._shape_format = ShapeCreateIntent(object_id="format", box=(0.0, 0.0, 1.0, 1.0))
        self._connector_format = ConnectorCreateIntent(
            object_id="format", start=(0.0, 0.0), end=(1.0, 1.0)
        )
        self._last_draw_subtool = DEFAULT_DRAW_SUBTOOL
        self._draw_preset_index = 0
        self._draw_style = StrokeCreateIntent(object_id="format", points=())

    def transient_state(self) -> dict[str, object]:
        """Diagnostic snapshot. Must never be merged into a project payload."""
        return {
            "active_tool": self._active_tool,
            "pointer_mode": self._pointer_mode,
            "pinned_tool": self._pinned_tool,
            "selection": tuple(sorted(_key_sort_tuple(item) for item in self._selection)),
            "draft": None if self._draft is None else self._draft.tool,
            "hover": None
            if self._hover_target is None
            else _key_sort_tuple(self._hover_target),
            "editor_active": self._editor_active,
        }


def normalize_draw_subtool(value: object) -> str:
    checked = str(value or "")
    return checked if checked in DRAW_SUBTOOLS else DEFAULT_DRAW_SUBTOOL


def is_draw_ink_subtool(value: object) -> bool:
    return str(value or "") in DRAW_INK_SUBTOOLS


def lasso_selection_keys(
    *,
    path: Iterable[tuple[float, float]],
    author_centers: Iterable[tuple[str, tuple[float, float]]],
    card_centers: Iterable[tuple[UltraViewRef, tuple[float, float]]],
) -> tuple[BoardItemKey, ...]:
    """Center-point lasso hits. Locked objects stay selectable here."""
    if not lasso_is_usable(path):
        return ()
    keys: list[BoardItemKey] = []
    for object_id, center in author_centers:
        if point_in_lasso(center, path):
            keys.append(AuthorKey(object_id))
    for ref, center in card_centers:
        if point_in_lasso(center, path):
            keys.append(CardKey(ref))
    return tuple(keys)


def _clamp_stroke_width(value: object) -> int:
    try:
        width = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 2
    return min(STROKE_WIDTH_MAX, max(STROKE_WIDTH_MIN, width))


def _checked_key(item: BoardItemKey) -> BoardItemKey:
    if isinstance(item, (CardKey, AuthorKey)):
        return item
    raise UltraViewStateError("BoardItemKey must be CardKey or AuthorKey")


def _key_sort_tuple(item: BoardItemKey) -> tuple:
    if isinstance(item, CardKey):
        return ("card", item.ref.section, item.ref.view_id)
    return ("author", item.object_id)
