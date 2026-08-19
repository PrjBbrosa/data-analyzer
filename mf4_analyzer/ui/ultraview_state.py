"""Qt-free UltraView board state, legalization, digest, and axis facts.

UltraView is a read-only snapshot Board over five source workspaces. This
module is the single owner of identity, layout mutation semantics, payload
legalization, presentation digest, and derived preview status. It must not
import Qt, MainWindow, ChartStack, or analysis compute modules.
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Sequence

SOURCE_SECTIONS = ("time", "fft", "fft_time", "frf", "order")

SECTION_LABELS_ZH = {
    "time": "时域",
    "fft": "频谱",
    "fft_time": "时频",
    "frf": "频响",
    "order": "阶次",
}

SECTION_LABELS_EN = {
    "time": "Time",
    "fft": "FFT",
    "fft_time": "FFT vs Time",
    "frf": "FRF",
    "order": "Order",
}

DEFAULT_LAYOUT_ID = "hero_left_4"
DEFAULT_BOARD_NAME = "全局对比"
DEFAULT_PRIMARY_RATIO = 0.67
RATIO_MIN = 0.40
RATIO_MAX = 0.80
RATIO_STEP = 0.05
# The nested UltraView workspace schema is independent of the top-level
# .tlproj document schema. Ordinary session fields (files, views,
# channel_order) live on the document; this number only versions the
# UltraView workspace blob so the rest of the session codec can keep
# reading older projects.
ULTRAVIEW_SCHEMA = 5
DIGEST_SCHEMA = 1
_BOARD_PAYLOAD_KEYS = frozenset(
    {
        "board_id",
        "name",
        "show_titles",
        "show_sources",
        "unplaced",
        "layout_mode",
        "layout_id",
        "primary_ratio",
        "free_grid",
        "placements",
        "author_objects",
    }
)
# Schema 1–3 stored this workspace preference on every Board.  Consume the
# retired key during parsing so an editable schema-4 re-save cannot recreate a
# conflicting Board-level source of truth.
# ``viewport`` was a write-only camera dump through schema 4; ignore it on
# read so old projects neither toast nor round-trip the unused field.
_RETIRED_BOARD_PAYLOAD_KEYS = frozenset({"show_card_actions", "viewport"})

LAYOUT_SLOTS: dict[str, tuple[str, ...]] = {
    "split_horizontal": ("left", "right"),
    "split_vertical": ("top", "bottom"),
    "grid_2x2": ("tl", "tr", "bl", "br"),
    "hero_left_4": ("primary", "aux_0", "aux_1", "aux_2"),
    "hero_top_4": ("primary", "aux_0", "aux_1", "aux_2"),
    "grid_3x2": ("r0c0", "r0c1", "r0c2", "r1c0", "r1c1", "r1c2"),
    "grid_3x3": tuple(
        f"r{row}c{column}" for row in range(3) for column in range(3)
    ),
    "grid_4x3": tuple(
        f"r{row}c{column}" for row in range(3) for column in range(4)
    ),
}

HERO_LAYOUTS = frozenset({"hero_left_4", "hero_top_4"})
EQUAL_LAYOUTS = frozenset(LAYOUT_SLOTS) - HERO_LAYOUTS

AXIS_KIND_TIME = "time"
AXIS_KIND_FREQUENCY = "frequency"
AXIS_KIND_TIME_FREQ = "time_freq"
AXIS_KIND_ORDER = "order"

SECTION_AXIS_KIND = {
    "time": AXIS_KIND_TIME,
    "fft": AXIS_KIND_FREQUENCY,
    "fft_time": AXIS_KIND_TIME_FREQ,
    "frf": AXIS_KIND_FREQUENCY,
    "order": AXIS_KIND_ORDER,
}

COMPARE_FILTER_ALL = "all"
COMPARE_FILTERS = (
    COMPARE_FILTER_ALL,
    AXIS_KIND_TIME,
    AXIS_KIND_FREQUENCY,
    AXIS_KIND_TIME_FREQ,
    AXIS_KIND_ORDER,
)

STATUS_FRESH = "fresh"
STATUS_STALE = "stale"
STATUS_MISSING = "missing"
STATUS_ORPHANED = "orphaned"

ULTRAVIEW_REF_MIME = "application/x-tracelab-ultraview-ref+json"
ULTRAVIEW_PAGE_OBJECT_NAME = "ultraViewPage"

RANGE_ABS_TOL = 1e-9
RANGE_REL_TOL = 1e-6


class UltraViewStateError(ValueError):
    """Invalid UltraView identity or mutation argument."""


@dataclass(frozen=True, order=True)
class UltraViewRef:
    section: str
    view_id: str

    def __post_init__(self) -> None:
        if self.section not in SOURCE_SECTIONS:
            raise UltraViewStateError(
                f"section must be one of {SOURCE_SECTIONS}, got {self.section!r}"
            )
        if not isinstance(self.view_id, str) or not self.view_id.strip():
            raise UltraViewStateError("view_id must be a non-empty string")
        if self.view_id != self.view_id.strip():
            object.__setattr__(self, "view_id", self.view_id.strip())

    def to_dict(self) -> dict[str, str]:
        return {"section": self.section, "view_id": self.view_id}


@dataclass
class CardPlacement:
    slot_id: str
    ref: UltraViewRef


# Schema 5 subdivides every schema-4 grid cell into a 2×2 logical lattice.
# The 12×48 physical reading frame and its pixel pitch do not change: only
# persisted coordinates gain half-cell placement and sizing precision.
GRID_RESOLUTION = 2
LEGACY_GRID_COLUMNS = 12
LEGACY_MAX_GRID_ROWS = 48
GRID_COLUMNS = LEGACY_GRID_COLUMNS * GRID_RESOLUTION
MAX_GRID_ROWS = LEGACY_MAX_GRID_ROWS * GRID_RESOLUTION
# Engineering safety cap remains the same physical extent as schema 4.
SAFETY_COLUMN_MIN = -48 * GRID_RESOLUTION
SAFETY_COLUMN_MAX = 60 * GRID_RESOLUTION
SAFETY_ROW_MIN = -48 * GRID_RESOLUTION
SAFETY_ROW_MAX = 96 * GRID_RESOLUTION
MAX_PLACED_CARDS = 24
MAX_UI_BOARDS = 20
MAX_BOARD_MEMBERSHIP = 200
MAX_AUTHOR_OBJECTS = 240
MAX_STICKY_TEXT = 3_000
MAX_TEXT_TEXT = 6_000
MAX_SHAPE_TEXT = 3_000
MAX_STROKE_POINTS = 2_048
MAX_AUTHOR_POINTS = 60_000
GRID_MIN_COLUMN_SPAN = 2 * GRID_RESOLUTION
GRID_MAX_COLUMN_SPAN = LEGACY_GRID_COLUMNS * GRID_RESOLUTION
GRID_MIN_ROW_SPAN = 2 * GRID_RESOLUTION
GRID_MAX_ROW_SPAN = 8 * GRID_RESOLUTION
LAYOUT_MODE_TEMPLATE = "template"
LAYOUT_MODE_FREE_GRID = "free_grid"
FREE_GRID_PRESETS: dict[str, tuple[int, int]] = {
    "small": (6, 4),
    "standard": (8, 6),
    "wide": (12, 6),
    "tall": (8, 10),
    "large": (12, 12),
    "banner": (24, 8),
}


@dataclass(frozen=True)
class GridRect:
    """Stable, screen-independent card rectangle for P2's controlled grid.

    ``column`` / ``row`` are signed. The base frame occupies columns
    ``[0, GRID_COLUMNS)`` and rows ``[0, MAX_GRID_ROWS)``; legal cards may sit
    anywhere inside the safety half-open interval
    ``[SAFETY_COLUMN_MIN, SAFETY_COLUMN_MAX)`` ×
    ``[SAFETY_ROW_MIN, SAFETY_ROW_MAX)``.
    """

    column: int
    row: int
    column_span: int
    row_span: int


@dataclass(frozen=True)
class GridBounds:
    """Immutable half-open cell rectangle ``[column, column_end) × [row, row_end)``."""

    column: int
    row: int
    column_span: int
    row_span: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "column", int(self.column))
        object.__setattr__(self, "row", int(self.row))
        object.__setattr__(self, "column_span", max(0, int(self.column_span)))
        object.__setattr__(self, "row_span", max(0, int(self.row_span)))

    @property
    def column_end(self) -> int:
        return self.column + self.column_span

    @property
    def row_end(self) -> int:
        return self.row + self.row_span

    def empty(self) -> bool:
        return self.column_span == 0 or self.row_span == 0

    def union(self, other: "GridBounds") -> "GridBounds":
        if self.empty():
            return other
        if other.empty():
            return self
        column = min(self.column, other.column)
        row = min(self.row, other.row)
        return GridBounds(
            column,
            row,
            max(self.column_end, other.column_end) - column,
            max(self.row_end, other.row_end) - row,
        )

    @classmethod
    def from_rect(cls, rect: GridRect) -> "GridBounds":
        return cls(rect.column, rect.row, rect.column_span, rect.row_span)

    @classmethod
    def from_edges(
        cls, column: int, row: int, column_end: int, row_end: int
    ) -> "GridBounds":
        return cls(column, row, column_end - column, row_end - row)


def base_frame_bounds() -> GridBounds:
    """Canonical physical frame in schema-5 micro-grid coordinates."""
    return GridBounds(0, 0, GRID_COLUMNS, MAX_GRID_ROWS)


def safety_grid_bounds() -> GridBounds:
    """Engineering cap. Not a daily layout suggestion and not persisted."""
    return GridBounds(
        SAFETY_COLUMN_MIN,
        SAFETY_ROW_MIN,
        SAFETY_COLUMN_MAX - SAFETY_COLUMN_MIN,
        SAFETY_ROW_MAX - SAFETY_ROW_MIN,
    )


def clamp_grid_rect(rect: GridRect) -> GridRect:
    """Clamp origin+span into the safety bounds. Spans keep their existing min/max."""
    col_span = min(GRID_MAX_COLUMN_SPAN, max(GRID_MIN_COLUMN_SPAN, int(rect.column_span)))
    row_span = min(GRID_MAX_ROW_SPAN, max(GRID_MIN_ROW_SPAN, int(rect.row_span)))
    return GridRect(
        column=min(SAFETY_COLUMN_MAX - col_span, max(SAFETY_COLUMN_MIN, int(rect.column))),
        row=min(SAFETY_ROW_MAX - row_span, max(SAFETY_ROW_MIN, int(rect.row))),
        column_span=col_span,
        row_span=row_span,
    )


def grid_rect_in_safety(rect: GridRect) -> bool:
    """True when ``rect`` already sits inside safety with a legal span."""
    return clamp_grid_rect(rect) == rect


@dataclass(frozen=True)
class GridAnchor:
    """Qt-free desired card centre in free-grid cell coordinates.

    This is transient interaction intent, never persisted in a board payload.
    """

    column: float
    row: float

    def __post_init__(self) -> None:
        try:
            column = float(self.column)
            row = float(self.row)
        except (TypeError, ValueError) as exc:
            raise UltraViewStateError("grid anchor must be numeric") from exc
        if not math.isfinite(column) or not math.isfinite(row):
            raise UltraViewStateError("grid anchor must be finite")
        object.__setattr__(self, "column", column)
        object.__setattr__(self, "row", row)


def _finite_coordinate(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise UltraViewStateError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise UltraViewStateError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise UltraViewStateError(f"{name} must be finite")
    return number


@dataclass(frozen=True)
class BoardPoint:
    """Persistent author-content point in schema-5 micro-grid coordinates."""

    x: float
    y: float

    def __post_init__(self) -> None:
        x = _finite_coordinate(self.x, "point.x")
        y = _finite_coordinate(self.y, "point.y")
        if not (SAFETY_COLUMN_MIN <= x < SAFETY_COLUMN_MAX):
            raise UltraViewStateError("point.x outside board safety bounds")
        if not (SAFETY_ROW_MIN <= y < SAFETY_ROW_MAX):
            raise UltraViewStateError("point.y outside board safety bounds")
        object.__setattr__(self, "x", x)
        object.__setattr__(self, "y", y)

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y}


@dataclass(frozen=True)
class BoardBox:
    """Persistent author-content box fully contained by the signed safety area."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        x = _finite_coordinate(self.x, "box.x")
        y = _finite_coordinate(self.y, "box.y")
        width = _finite_coordinate(self.width, "box.width")
        height = _finite_coordinate(self.height, "box.height")
        if width <= 0 or height <= 0:
            raise UltraViewStateError("box dimensions must be positive")
        if not (
            SAFETY_COLUMN_MIN <= x < SAFETY_COLUMN_MAX
            and SAFETY_ROW_MIN <= y < SAFETY_ROW_MAX
            and x + width <= SAFETY_COLUMN_MAX
            and y + height <= SAFETY_ROW_MAX
        ):
            raise UltraViewStateError("box outside board safety bounds")
        object.__setattr__(self, "x", x)
        object.__setattr__(self, "y", y)
        object.__setattr__(self, "width", width)
        object.__setattr__(self, "height", height)

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


def _author_id(value: object, field_name: str = "object id") -> str:
    if not isinstance(value, str) or not value.strip():
        raise UltraViewStateError(f"{field_name} must be a non-empty string")
    cleaned = value.strip()
    if len(cleaned) > 128:
        raise UltraViewStateError(f"{field_name} is too long")
    return cleaned


@dataclass(frozen=True)
class BoardItemKey:
    """Unambiguous selection identity for a card or a persisted author object."""

    kind: str
    ref: UltraViewRef | None = None
    object_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind == "card" and isinstance(self.ref, UltraViewRef) and self.object_id is None:
            return
        if self.kind == "author" and self.ref is None and self.object_id is not None:
            object.__setattr__(self, "object_id", _author_id(self.object_id))
            return
        raise UltraViewStateError("BoardItemKey must identify exactly one card or author object")

    @classmethod
    def card(cls, ref: UltraViewRef) -> "BoardItemKey":
        return cls("card", ref=ref)

    @classmethod
    def author(cls, object_id: str) -> "BoardItemKey":
        return cls("author", object_id=object_id)

    def to_dict(self) -> dict[str, Any]:
        if self.kind == "card":
            assert self.ref is not None
            return {"kind": "card", "ref": self.ref.to_dict()}
        assert self.object_id is not None
        return {"kind": "author", "object_id": self.object_id}


@dataclass(frozen=True)
class AnchorTarget:
    """Structured connector target; names alone never select a card/object."""

    kind: str
    card: UltraViewRef | None = None
    object_id: str | None = None
    anchor: str = "auto"

    def __post_init__(self) -> None:
        if self.anchor not in {"auto", "n", "e", "s", "w"}:
            raise UltraViewStateError("anchor must be auto, n, e, s, or w")
        if self.kind == "card" and isinstance(self.card, UltraViewRef) and self.object_id is None:
            return
        if self.kind == "author" and self.card is None and self.object_id is not None:
            object.__setattr__(self, "object_id", _author_id(self.object_id))
            return
        raise UltraViewStateError("AnchorTarget must identify exactly one card or author object")

    def to_dict(self) -> dict[str, Any]:
        if self.kind == "card":
            assert self.card is not None
            return {"kind": "card", "card": self.card.to_dict(), "anchor": self.anchor}
        assert self.object_id is not None
        return {"kind": "author", "object_id": self.object_id, "anchor": self.anchor}


def _checked_string(value: object, field_name: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise UltraViewStateError(f"{field_name} must be a string")
    if len(value) > limit:
        raise UltraViewStateError(f"{field_name} is too long")
    return value


@dataclass(frozen=True)
class AuthorCommon:
    object_id: str
    kind: str
    locked: bool = False

    def _validate_common(self, expected_kind: str) -> None:
        object.__setattr__(self, "object_id", _author_id(self.object_id))
        if self.kind != expected_kind:
            raise UltraViewStateError(f"author kind must be {expected_kind}")
        object.__setattr__(self, "locked", bool(self.locked))


@dataclass(frozen=True)
class StickyObject(AuthorCommon):
    box: BoardBox = field(default_factory=lambda: BoardBox(0, 0, 1, 1))
    text: str = ""
    palette: str = "yellow"
    shape: str = "square"
    font_size: int | str = "auto"

    def __post_init__(self) -> None:
        self._validate_common("sticky")
        if self.shape not in {"square", "wide"}:
            raise UltraViewStateError("unknown sticky shape")
        if self.font_size != "auto" and (
            isinstance(self.font_size, bool) or not isinstance(self.font_size, int) or not 8 <= self.font_size <= 96
        ):
            raise UltraViewStateError("illegal sticky font size")
        _checked_string(self.text, "sticky text", limit=MAX_STICKY_TEXT)
        _checked_string(self.palette, "sticky palette", limit=64)


@dataclass(frozen=True)
class TextObject(AuthorCommon):
    box: BoardBox = field(default_factory=lambda: BoardBox(0, 0, 1, 1))
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

    def __post_init__(self) -> None:
        self._validate_common("text")
        _checked_string(self.text, "text", limit=MAX_TEXT_TEXT)
        if self.font_role not in {"sans", "serif", "mono"}:
            raise UltraViewStateError("unknown font role")
        if isinstance(self.font_size, bool) or not isinstance(self.font_size, int) or not 8 <= self.font_size <= 96:
            raise UltraViewStateError("illegal text font size")
        if self.align not in {"left", "center", "right"}:
            raise UltraViewStateError("unknown text alignment")
        if self.list_style not in {"none", "bullet", "number"}:
            raise UltraViewStateError("unknown list style")
        _checked_string(self.text_palette, "text palette", limit=64)
        if self.fill_palette is not None:
            _checked_string(self.fill_palette, "fill palette", limit=64)
        if isinstance(self.opacity, bool) or not isinstance(self.opacity, int) or not 0 <= self.opacity <= 100:
            raise UltraViewStateError("illegal text opacity")
        if self.link is not None:
            _checked_string(self.link, "link", limit=2_048)


@dataclass(frozen=True)
class ShapeTextStyle:
    font_size: int = 14
    bold: bool = False
    italic: bool = False
    underline: bool = False
    align: str = "center"
    text_palette: str = "ink"

    def __post_init__(self) -> None:
        if isinstance(self.font_size, bool) or not isinstance(self.font_size, int) or not 8 <= self.font_size <= 96:
            raise UltraViewStateError("illegal shape label font size")
        if self.align not in {"left", "center", "right"}:
            raise UltraViewStateError("unknown shape label alignment")
        _checked_string(self.text_palette, "shape text palette", limit=64)

    def to_dict(self) -> dict[str, Any]:
        return {
            "font_size": self.font_size,
            "bold": bool(self.bold),
            "italic": bool(self.italic),
            "underline": bool(self.underline),
            "align": self.align,
            "text_palette": self.text_palette,
        }


@dataclass(frozen=True)
class ShapeObject(AuthorCommon):
    box: BoardBox = field(default_factory=lambda: BoardBox(0, 0, 1, 1))
    shape: str = "rectangle"
    text: str = ""
    fill_palette: str | None = None
    stroke_palette: str = "ink"
    stroke_width: int = 1
    line_style: str = "solid"
    text_style: ShapeTextStyle = field(default_factory=ShapeTextStyle)

    def __post_init__(self) -> None:
        self._validate_common("shape")
        if self.shape not in {"rectangle", "oval", "rhombus", "triangle", "block_arrow"}:
            raise UltraViewStateError("unknown shape")
        _checked_string(self.text, "shape text", limit=MAX_SHAPE_TEXT)
        if self.fill_palette is not None:
            _checked_string(self.fill_palette, "shape fill palette", limit=64)
        _checked_string(self.stroke_palette, "shape stroke palette", limit=64)
        if isinstance(self.stroke_width, bool) or not isinstance(self.stroke_width, int) or not 1 <= self.stroke_width <= 32:
            raise UltraViewStateError("illegal shape stroke width")
        if self.line_style not in {"solid", "dashed"}:
            raise UltraViewStateError("unknown shape line style")
        if not isinstance(self.text_style, ShapeTextStyle):
            raise UltraViewStateError("shape text style must be typed")


@dataclass(frozen=True)
class StrokeObject(AuthorCommon):
    points: tuple[BoardPoint, ...] = ()
    tool: str = "pen"
    palette: str = "ink"
    width_px_100: int = 1

    def __post_init__(self) -> None:
        self._validate_common("stroke")
        if not isinstance(self.points, tuple) or not 2 <= len(self.points) <= MAX_STROKE_POINTS:
            raise UltraViewStateError("stroke must contain 2..MAX_STROKE_POINTS points")
        if not all(isinstance(point, BoardPoint) for point in self.points):
            raise UltraViewStateError("stroke points must be BoardPoint values")
        if self.tool not in {"pen", "highlighter"}:
            raise UltraViewStateError("unknown stroke tool")
        _checked_string(self.palette, "stroke palette", limit=64)
        if isinstance(self.width_px_100, bool) or not isinstance(self.width_px_100, int) or not 1 <= self.width_px_100 <= 64:
            raise UltraViewStateError("illegal stroke width")


@dataclass(frozen=True)
class ConnectorEndpoint:
    point: BoardPoint
    target: AnchorTarget | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.point, BoardPoint):
            raise UltraViewStateError("connector endpoint point must be typed")
        if self.target is not None and not isinstance(self.target, AnchorTarget):
            raise UltraViewStateError("connector endpoint target must be typed")

    def to_dict(self) -> dict[str, Any]:
        return {"point": self.point.to_dict(), "target": None if self.target is None else self.target.to_dict()}


@dataclass(frozen=True)
class ConnectorObject(AuthorCommon):
    start: ConnectorEndpoint = field(default_factory=lambda: ConnectorEndpoint(BoardPoint(0, 0)))
    end: ConnectorEndpoint = field(default_factory=lambda: ConnectorEndpoint(BoardPoint(1, 1)))
    route: str = "straight"
    elbow_bias: float | None = None
    line_style: str = "solid"
    stroke_palette: str = "ink"
    stroke_width: int = 1
    start_head: str = "none"
    end_head: str = "arrow"

    def __post_init__(self) -> None:
        self._validate_common("connector")
        if not isinstance(self.start, ConnectorEndpoint) or not isinstance(self.end, ConnectorEndpoint):
            raise UltraViewStateError("connector endpoints must be typed")
        if self.route not in {"straight", "elbow"}:
            raise UltraViewStateError("unknown connector route")
        if self.elbow_bias is not None:
            bias = _finite_coordinate(self.elbow_bias, "elbow bias")
            if not 0.0 <= bias <= 1.0:
                raise UltraViewStateError("elbow bias outside 0..1")
            object.__setattr__(self, "elbow_bias", bias)
        if self.line_style not in {"solid", "dashed"}:
            raise UltraViewStateError("unknown connector line style")
        _checked_string(self.stroke_palette, "connector stroke palette", limit=64)
        if isinstance(self.stroke_width, bool) or not isinstance(self.stroke_width, int) or not 1 <= self.stroke_width <= 32:
            raise UltraViewStateError("illegal connector stroke width")
        if self.start_head not in {"none", "arrow"} or self.end_head not in {"none", "arrow"}:
            raise UltraViewStateError("unknown connector head")


@dataclass(frozen=True)
class UnknownAuthorObject:
    """Newer author object retained exactly, without pretending to render it."""

    raw: dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.raw, dict):
            raise UltraViewStateError("unknown author object must retain a mapping")


AuthorObject = StickyObject | TextObject | ShapeObject | StrokeObject | ConnectorObject | UnknownAuthorObject


@dataclass
class FreeGridPlacement:
    ref: UltraViewRef
    rect: GridRect


@dataclass(frozen=True)
class BoardPlacementSnapshot:
    """Qt-free Board membership + geometry for placement undo.

    Captures placed template slots, free-grid rects, tray order, and the
    layout fields needed to restore them exactly. Name, preview pixels, and
    Qt objects stay out.
    """

    layout_mode: str
    layout_id: str
    primary_ratio: float
    placements: tuple[tuple[str, UltraViewRef], ...]
    free_grid: tuple[tuple[UltraViewRef, GridRect], ...]
    unplaced: tuple[UltraViewRef, ...]


@dataclass(frozen=True)
class ObjectPatch:
    """One reversible author-object change, including its z-order positions.

    Payload mappings are deliberately retained instead of typed DTO instances:
    the history must restore an unknown future object just as faithfully as a
    known Sticky or Stroke.  The constructor defensively copies the mappings
    because callers commonly build a draft payload then continue editing it.
    """

    object_id: str
    before: Mapping[str, Any] | None
    after: Mapping[str, Any] | None
    before_index: int | None
    after_index: int | None

    def __post_init__(self) -> None:
        object_id = _author_id(self.object_id, "patch object id")
        object.__setattr__(self, "object_id", object_id)
        for name, payload, index in (
            ("before", self.before, self.before_index),
            ("after", self.after, self.after_index),
        ):
            if payload is None:
                if index is not None:
                    raise UltraViewStateError(f"{name}_index requires {name} payload")
                continue
            if not isinstance(payload, Mapping):
                raise UltraViewStateError(f"patch {name} must be a mapping")
            if not isinstance(index, int) or isinstance(index, bool) or index < 0:
                raise UltraViewStateError(f"patch {name}_index must be non-negative")
            copied = deepcopy(dict(payload))
            if _author_id(copied.get("id"), f"patch {name} id") != object_id:
                raise UltraViewStateError("patch object id does not match payload")
            object.__setattr__(self, name, copied)
        if self.before is None and self.after is None:
            raise UltraViewStateError("object patch cannot be empty")


@dataclass(frozen=True)
class BoardEditEntry:
    """Atomic board edit: optional card placement plus author-object patches."""

    label: str
    placement_before: BoardPlacementSnapshot | None
    placement_after: BoardPlacementSnapshot | None
    object_patches: tuple[ObjectPatch, ...]

    def __post_init__(self) -> None:
        _checked_string(self.label, "board edit label", limit=128)
        if (self.placement_before is None) != (self.placement_after is None):
            raise UltraViewStateError("board edit placement snapshots must be paired")
        if not isinstance(self.object_patches, tuple) or not all(
            isinstance(item, ObjectPatch) for item in self.object_patches
        ):
            raise UltraViewStateError("board edit patches must be ObjectPatch values")
        object_ids = [item.object_id for item in self.object_patches]
        if len(set(object_ids)) != len(object_ids):
            raise UltraViewStateError("board edit cannot patch one object twice")
        if self.placement_before is None and not self.object_patches:
            raise UltraViewStateError("board edit cannot be empty")

    @property
    def kind(self) -> str:
        """Compatibility with placement-history callers that inspect ``kind``."""
        return self.label


@dataclass(frozen=True)
class AuthorMutationResult:
    """Qt-free mutation result; the coordinator decides dirty/history policy."""

    patches: tuple[ObjectPatch, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.patches)


@dataclass
class UltraViewBoardState:
    board_id: str
    name: str
    layout_id: str
    primary_ratio: float
    placements: list[CardPlacement] = field(default_factory=list)
    unplaced: list[UltraViewRef] = field(default_factory=list)
    show_titles: bool = True
    show_sources: bool = True
    layout_mode: str = LAYOUT_MODE_FREE_GRID
    free_grid: list[FreeGridPlacement] = field(default_factory=list)
    free_grid_default_size: str = "standard"
    # Additive schema-5 authoring content.  List order is the author z-order.
    author_objects: list[AuthorObject] = field(default_factory=list)
    passthrough: dict[str, Any] = field(default_factory=dict)


@dataclass
class UltraViewWorkspaceState:
    """Qt-free, ordered collection of independent UltraView Boards."""

    active_board_id: str
    boards: list[UltraViewBoardState] = field(default_factory=list)
    preview_sidecar: Mapping[str, Any] | None = None
    # A future writer must not destroy a newer nested payload merely because
    # this application cannot interpret it yet.  The coordinator serializes
    # this blob unchanged unless the user mutates the workspace.
    opaque_payload: Mapping[str, Any] | None = None
    # False reveals card actions on hover/focus; true pins them for every Board.
    # Kept after existing fields so positional construction of this Qt-free DTO
    # remains backward compatible.
    show_card_actions: bool = False


@dataclass
class PreviewMeta:
    """Capture metadata without Qt pixels. Status is always derived."""

    ref: UltraViewRef
    captured_digest: str | None = None
    captured_at: float | None = None
    axis_kind: str | None = None
    x_unit: str | None = None
    x_range: tuple[float, float] | None = None
    y_unit: str | None = None
    title: str = ""
    source_summary: str = ""
    tab_color: str = ""


@dataclass(frozen=True)
class AxisConsistencyFacts:
    unit_inconsistent_kinds: tuple[str, ...]
    range_inconsistent_kinds: tuple[str, ...]


def layout_slots(layout_id: str) -> tuple[str, ...]:
    return LAYOUT_SLOTS[layout_id]


def layout_capacity(layout_id: str) -> int:
    return len(layout_slots(layout_id))


def is_hero_layout(layout_id: str) -> bool:
    return layout_id in HERO_LAYOUTS


_TEMPLATE_BY_CAPACITY: tuple[tuple[int, str], ...] = (
    (2, "split_horizontal"),
    (4, "grid_2x2"),
    (6, "grid_3x2"),
    (9, "grid_3x3"),
    (12, "grid_4x3"),
)


def best_template_for(count: int) -> str:
    """Smallest equal-grid template that can hold ``count`` cards.

    Used when leaving free-grid via the rail toggle. Explicit LayoutPicker
    choices are not routed through this helper. Counts above 12 still return
    ``grid_4x3``; overflow goes to the unplaced tray.
    """
    try:
        n = int(count)
    except (TypeError, ValueError):
        n = 0
    n = max(0, n)
    for capacity, layout_id in _TEMPLATE_BY_CAPACITY:
        if n <= capacity:
            return layout_id
    return "grid_4x3"


def default_board() -> UltraViewBoardState:
    return UltraViewBoardState(
        board_id=str(uuid.uuid4()),
        name=DEFAULT_BOARD_NAME,
        layout_id=DEFAULT_LAYOUT_ID,
        primary_ratio=DEFAULT_PRIMARY_RATIO,
        placements=[],
        unplaced=[],
        show_titles=True,
        show_sources=True,
        layout_mode=LAYOUT_MODE_FREE_GRID,
    )


def default_workspace() -> UltraViewWorkspaceState:
    board = default_board()
    return UltraViewWorkspaceState(
        active_board_id=board.board_id,
        boards=[board],
        show_card_actions=False,
    )


def active_board(workspace: UltraViewWorkspaceState) -> UltraViewBoardState:
    """Return the selected Board, repairing only an in-memory bad selection."""
    if not workspace.boards:
        board = default_board()
        workspace.boards.append(board)
        workspace.active_board_id = board.board_id
        return board
    for board in workspace.boards:
        if board.board_id == workspace.active_board_id:
            return board
    workspace.active_board_id = workspace.boards[0].board_id
    return workspace.boards[0]


def mark_workspace_mutated(workspace: UltraViewWorkspaceState) -> None:
    """Allow a known schema to be written after an explicit user mutation.

    A future-schema payload is deliberately retained byte-for-byte while the
    user merely opens and saves a project.  Once they change workspace state,
    however, serializing that opaque payload would discard the change.  The
    coordinator calls this after every Board-level intent; workspace-level
    mutators call it themselves.
    """
    workspace.opaque_payload = None


def set_workspace_preview_sidecar(
    workspace: UltraViewWorkspaceState,
    descriptor: Mapping[str, Any] | None,
) -> None:
    """Attach or clear the sidecar pointer without discarding a future payload.

    Saving preview pixels is an acceleration-layer write, not a Board mutation,
    so a newer nested schema must keep its opaque body and only overlay the
    descriptor.  Otherwise the just-written ``.uvpz`` becomes an orphan.
    """
    workspace.preview_sidecar = (
        dict(descriptor) if isinstance(descriptor, Mapping) else None
    )
    if workspace.opaque_payload is None:
        return
    payload = dict(workspace.opaque_payload)
    if workspace.preview_sidecar is not None:
        payload["preview_sidecar"] = dict(workspace.preview_sidecar)
    else:
        payload.pop("preview_sidecar", None)
    workspace.opaque_payload = payload


def set_workspace_show_card_actions(
    workspace: UltraViewWorkspaceState, checked: bool
) -> None:
    """Set the workspace-wide card action visibility preference.

    This is intentionally not a Board presentation property: every current
    and future Board in the project projects the same preference.
    """
    workspace.show_card_actions = bool(checked)
    mark_workspace_mutated(workspace)


def _board_index(workspace: UltraViewWorkspaceState, board_id: str) -> int | None:
    for index, board in enumerate(workspace.boards):
        if board.board_id == board_id:
            return index
    return None


def set_active_board(workspace: UltraViewWorkspaceState, board_id: str) -> list[str]:
    if _board_index(workspace, str(board_id)) is None:
        return [_warn("unknown_board", str(board_id))]
    workspace.active_board_id = str(board_id)
    mark_workspace_mutated(workspace)
    return []


def create_board(
    workspace: UltraViewWorkspaceState, *, name: str | None = None
) -> UltraViewBoardState | None:
    if len(workspace.boards) >= MAX_UI_BOARDS:
        return None
    board = default_board()
    ordinal = len(workspace.boards) + 1
    board.name = str(name).strip() if isinstance(name, str) and name.strip() else f"{DEFAULT_BOARD_NAME} {ordinal}"
    workspace.boards.append(board)
    workspace.active_board_id = board.board_id
    mark_workspace_mutated(workspace)
    return board


def _copy_board(board: UltraViewBoardState) -> UltraViewBoardState:
    clone = UltraViewBoardState(
        board_id=str(uuid.uuid4()),
        name=board.name,
        layout_id=board.layout_id,
        primary_ratio=board.primary_ratio,
        placements=[CardPlacement(item.slot_id, item.ref) for item in board.placements],
        unplaced=list(board.unplaced),
        show_titles=board.show_titles,
        show_sources=board.show_sources,
        layout_mode=board.layout_mode,
        free_grid=[FreeGridPlacement(item.ref, item.rect) for item in board.free_grid],
        free_grid_default_size=board.free_grid_default_size,
        author_objects=_clone_author_objects(board.author_objects),
        # Unknown future fields may contain nested authoring payloads.  A Board
        # duplicate is independently editable, so a shallow outer dict here
        # would let one Board rewrite another Board's preserved extension.
        passthrough=deepcopy(board.passthrough),
    )
    return clone


def duplicate_board(
    workspace: UltraViewWorkspaceState, board_id: str
) -> UltraViewBoardState | None:
    index = _board_index(workspace, str(board_id))
    if index is None:
        return None
    if len(workspace.boards) >= MAX_UI_BOARDS:
        return None
    clone = _copy_board(workspace.boards[index])
    clone.name = f"{clone.name} 副本"
    workspace.boards.insert(index + 1, clone)
    workspace.active_board_id = clone.board_id
    mark_workspace_mutated(workspace)
    return clone


def rename_board(
    workspace: UltraViewWorkspaceState, board_id: str, name: str
) -> list[str]:
    index = _board_index(workspace, str(board_id))
    if index is None:
        return [_warn("unknown_board", str(board_id))]
    cleaned = str(name or "").strip()
    if cleaned:
        workspace.boards[index].name = cleaned
        mark_workspace_mutated(workspace)
    return []


def delete_board(workspace: UltraViewWorkspaceState, board_id: str) -> list[str]:
    index = _board_index(workspace, str(board_id))
    if index is None:
        return [_warn("unknown_board", str(board_id))]
    if len(workspace.boards) <= 1:
        return [_warn("last_board_retained")]
    removed = workspace.boards.pop(index)
    if workspace.active_board_id == removed.board_id:
        workspace.active_board_id = workspace.boards[max(0, index - 1)].board_id
    mark_workspace_mutated(workspace)
    return []


def reorder_board(
    workspace: UltraViewWorkspaceState, board_id: str, index: int
) -> list[str]:
    old_index = _board_index(workspace, str(board_id))
    if old_index is None:
        return [_warn("unknown_board", str(board_id))]
    try:
        target = int(index)
    except (TypeError, ValueError):
        return [_warn("invalid_board_index", repr(index))]
    target = max(0, min(target, len(workspace.boards) - 1))
    board = workspace.boards.pop(old_index)
    workspace.boards.insert(target, board)
    mark_workspace_mutated(workspace)
    return []


def make_ref(section: str, view_id: str) -> UltraViewRef:
    return UltraViewRef(section=str(section), view_id=str(view_id))


def parse_ref_payload(payload: Mapping[str, Any] | None) -> UltraViewRef | None:
    if not isinstance(payload, Mapping):
        return None
    try:
        return make_ref(payload.get("section", ""), payload.get("view_id", ""))
    except (TypeError, UltraViewStateError):
        return None


def clamp_ratio(value: float) -> float:
    return min(RATIO_MAX, max(RATIO_MIN, float(value)))


def all_refs(board: UltraViewBoardState) -> list[UltraViewRef]:
    if board.layout_mode == LAYOUT_MODE_FREE_GRID:
        return [p.ref for p in board.free_grid] + list(board.unplaced)
    return [p.ref for p in board.placements] + list(board.unplaced)


def placed_ref_set(board: UltraViewBoardState) -> set[UltraViewRef]:
    if board.layout_mode == LAYOUT_MODE_FREE_GRID:
        return {p.ref for p in board.free_grid}
    return {p.ref for p in board.placements}


def membership_set(board: UltraViewBoardState) -> set[UltraViewRef]:
    return set(all_refs(board))


def placement_for(board: UltraViewBoardState, ref: UltraViewRef) -> CardPlacement | None:
    if board.layout_mode == LAYOUT_MODE_FREE_GRID:
        return None
    for placement in board.placements:
        if placement.ref == ref:
            return placement
    return None


def slot_occupant(board: UltraViewBoardState, slot_id: str) -> UltraViewRef | None:
    if board.layout_mode == LAYOUT_MODE_FREE_GRID:
        return None
    for placement in board.placements:
        if placement.slot_id == slot_id:
            return placement.ref
    return None


def empty_slots(board: UltraViewBoardState) -> list[str]:
    if board.layout_mode == LAYOUT_MODE_FREE_GRID:
        return []
    occupied = {p.slot_id for p in board.placements}
    return [slot for slot in layout_slots(board.layout_id) if slot not in occupied]


def first_empty_slot(board: UltraViewBoardState) -> str | None:
    slots = empty_slots(board)
    return slots[0] if slots else None


def _warn(code: str, detail: str = "") -> str:
    return f"{code}: {detail}" if detail else code


def _take_membership(
    seen_refs: set[UltraViewRef], ref: UltraViewRef, warnings: list[str]
) -> bool:
    if ref in seen_refs:
        warnings.append(_warn("duplicate_ref", f"{ref.section}/{ref.view_id}"))
        return False
    if len(seen_refs) >= MAX_BOARD_MEMBERSHIP:
        warnings.append(_warn("membership_truncated", f"{ref.section}/{ref.view_id}"))
        return False
    seen_refs.add(ref)
    return True


def _remove_ref_everywhere(board: UltraViewBoardState, ref: UltraViewRef) -> None:
    board.placements = [p for p in board.placements if p.ref != ref]
    board.free_grid = [p for p in board.free_grid if p.ref != ref]
    board.unplaced = [item for item in board.unplaced if item != ref]


def _append_unplaced(board: UltraViewBoardState, ref: UltraViewRef) -> None:
    is_placed = (
        any(item.ref == ref for item in board.free_grid)
        if board.layout_mode == LAYOUT_MODE_FREE_GRID
        else placement_for(board, ref) is not None
    )
    if ref not in board.unplaced and not is_placed:
        board.unplaced.append(ref)


def _place(board: UltraViewBoardState, slot_id: str, ref: UltraViewRef) -> None:
    board.layout_mode = LAYOUT_MODE_TEMPLATE
    _remove_ref_everywhere(board, ref)
    board.placements = [p for p in board.placements if p.slot_id != slot_id]
    board.placements.append(CardPlacement(slot_id=slot_id, ref=ref))
    _sort_placements(board)


def _sort_placements(board: UltraViewBoardState) -> None:
    order = {slot: i for i, slot in enumerate(layout_slots(board.layout_id))}
    board.placements.sort(key=lambda p: order.get(p.slot_id, 10_000))


def add_ref(
    board: UltraViewBoardState,
    ref: UltraViewRef,
    *,
    preferred_anchor: GridAnchor | None = None,
    span: tuple[int, int] | None = None,
) -> list[str]:
    """Add ``ref`` to the first empty slot, or the tray if the board is full.

    Duplicate membership is a no-op so the caller can locate the existing card.
    ``span`` overrides the Board default size for a free-grid insert so ghost,
    model, and card can share one shrink-only aspect.
    """
    warnings: list[str] = []
    if ref in membership_set(board):
        return warnings
    if len(membership_set(board)) >= MAX_BOARD_MEMBERSHIP:
        return [_warn("membership_limit")]
    if board.layout_mode == LAYOUT_MODE_FREE_GRID:
        if len(board.free_grid) >= MAX_PLACED_CARDS:
            _append_unplaced(board, ref)
            return warnings
        span = _resolved_insert_span(board, span)
        rect = (
            resolve_free_grid_insert_rect(board.free_grid, span=span, anchor=preferred_anchor)
            if preferred_anchor is not None
            else _first_free_grid_rect(board.free_grid, span=span)
        )
        if rect is None:
            _append_unplaced(board, ref)
        else:
            board.free_grid.append(FreeGridPlacement(ref, rect))
        return warnings
    slot = first_empty_slot(board)
    if slot is None:
        _append_unplaced(board, ref)
        return warnings
    _place(board, slot, ref)
    return warnings


def replace_slot(
    board: UltraViewBoardState, slot_id: str, ref: UltraViewRef
) -> list[str]:
    """Put ``ref`` in ``slot_id``. The previous occupant goes to the tray."""
    warnings: list[str] = []
    if slot_id not in layout_slots(board.layout_id):
        return [_warn("unknown_slot", slot_id)]
    current = slot_occupant(board, slot_id)
    if current == ref:
        return warnings
    displaced = current
    _remove_ref_everywhere(board, ref)
    board.placements = [p for p in board.placements if p.slot_id != slot_id]
    if displaced is not None and displaced != ref:
        _append_unplaced(board, displaced)
    _place(board, slot_id, ref)
    return warnings


def swap_slots(board: UltraViewBoardState, slot_a: str, slot_b: str) -> list[str]:
    slots = layout_slots(board.layout_id)
    warnings: list[str] = []
    if slot_a not in slots:
        warnings.append(_warn("unknown_slot", slot_a))
    if slot_b not in slots:
        warnings.append(_warn("unknown_slot", slot_b))
    if warnings:
        return warnings
    if slot_a == slot_b:
        return warnings
    ref_a = slot_occupant(board, slot_a)
    ref_b = slot_occupant(board, slot_b)
    board.placements = [
        p for p in board.placements if p.slot_id not in {slot_a, slot_b}
    ]
    if ref_b is not None:
        board.placements.append(CardPlacement(slot_id=slot_a, ref=ref_b))
    if ref_a is not None:
        board.placements.append(CardPlacement(slot_id=slot_b, ref=ref_a))
    _sort_placements(board)
    return warnings


def place_from_unplaced(
    board: UltraViewBoardState, slot_id: str, ref: UltraViewRef
) -> list[str]:
    """Drop a tray ref onto a slot. An occupant returns to the tray."""
    if ref not in board.unplaced:
        return [_warn("not_unplaced", f"{ref.section}/{ref.view_id}")]
    return replace_slot(board, slot_id, ref)


def place_free_grid_from_unplaced(
    board: UltraViewBoardState,
    ref: UltraViewRef,
    *,
    preferred_anchor: GridAnchor | None = None,
    span: tuple[int, int] | None = None,
) -> list[str]:
    """Place a tray ref at the next legal free-grid rect without re-compute.

    ``span`` is the same optional override ``add_ref`` uses so a PreviewStore
    fit, the insert ghost, and the committed card share one rectangle.
    """
    if board.layout_mode != LAYOUT_MODE_FREE_GRID:
        return [_warn("not_free_grid")]
    if ref not in board.unplaced:
        return [_warn("not_unplaced", f"{ref.section}/{ref.view_id}")]
    if len(board.free_grid) >= MAX_PLACED_CARDS:
        return [_warn("grid_full")]
    span = _resolved_insert_span(board, span)
    rect = (
        resolve_free_grid_insert_rect(board.free_grid, span=span, anchor=preferred_anchor)
        if preferred_anchor is not None
        else _first_free_grid_rect(board.free_grid, span=span)
    )
    if rect is None:
        return [_warn("grid_full")]
    board.unplaced.remove(ref)
    board.free_grid.append(FreeGridPlacement(ref, rect))
    return []


def replace_free_grid_ref(
    board: UltraViewBoardState, target: UltraViewRef, new_ref: UltraViewRef
) -> list[str]:
    """Put ``new_ref`` in ``target``'s rectangle. The previous occupant goes to the tray."""
    if board.layout_mode != LAYOUT_MODE_FREE_GRID:
        return [_warn("not_free_grid")]
    item = free_grid_placement_for(board, target)
    if item is None:
        return [_warn("unknown_ref", f"{target.section}/{target.view_id}")]
    if target == new_ref:
        return []
    rect = item.rect
    _remove_ref_everywhere(board, new_ref)
    _remove_ref_everywhere(board, target)
    board.free_grid.append(FreeGridPlacement(new_ref, rect))
    _append_unplaced(board, target)
    return []


def set_layout(board: UltraViewBoardState, layout_id: str) -> list[str]:
    warnings: list[str] = []
    if layout_id not in LAYOUT_SLOTS:
        warnings.append(_warn("unknown_layout", str(layout_id)))
        layout_id = DEFAULT_LAYOUT_ID
    tray_count = len(board.unplaced)
    placed_count = (
        len(board.free_grid)
        if board.layout_mode == LAYOUT_MODE_FREE_GRID
        else len(board.placements)
    )
    ordered_refs = all_refs(board)
    board.layout_mode = LAYOUT_MODE_TEMPLATE
    board.free_grid.clear()
    board.unplaced.clear()
    new_slots = layout_slots(layout_id)
    board.layout_id = layout_id
    board.placements = []
    overflow = ordered_refs[len(new_slots):]
    for slot, ref in zip(new_slots, ordered_refs):
        board.placements.append(CardPlacement(slot_id=slot, ref=ref))
    for ref in overflow:
        _append_unplaced(board, ref)
    extra_slots = max(0, len(new_slots) - placed_count)
    refilled = min(tray_count, extra_slots)
    if refilled:
        warnings.append(_warn("tray_refilled", str(refilled)))
    if overflow:
        warnings.append(_warn("layout_overflow", str(len(overflow))))
    return warnings


def set_ratio(board: UltraViewBoardState, ratio: float) -> list[str]:
    warnings: list[str] = []
    try:
        value = float(ratio)
    except (TypeError, ValueError):
        warnings.append(_warn("illegal_ratio", repr(ratio)))
        value = DEFAULT_PRIMARY_RATIO
    if not math.isfinite(value):
        warnings.append(_warn("illegal_ratio", repr(ratio)))
        value = DEFAULT_PRIMARY_RATIO
    clamped = clamp_ratio(value)
    if clamped != value:
        warnings.append(_warn("illegal_ratio", str(ratio)))
    board.primary_ratio = clamped
    return warnings


def nudge_ratio(board: UltraViewBoardState, steps: int) -> list[str]:
    return set_ratio(board, board.primary_ratio + int(steps) * RATIO_STEP)


def move_to_unplaced(board: UltraViewBoardState, ref: UltraViewRef) -> list[str]:
    """Cancel placement but keep Board membership."""
    if ref not in membership_set(board):
        return [_warn("unknown_ref", f"{ref.section}/{ref.view_id}")]
    _remove_ref_everywhere(board, ref)
    _append_unplaced(board, ref)
    return []


def remove_ref(board: UltraViewBoardState, ref: UltraViewRef) -> list[str]:
    """Remove membership from both placements and the tray."""
    if ref not in membership_set(board):
        return [_warn("unknown_ref", f"{ref.section}/{ref.view_id}")]
    _remove_ref_everywhere(board, ref)
    return []


def rebind_ref(
    board: UltraViewBoardState, old_ref: UltraViewRef, new_ref: UltraViewRef
) -> list[str]:
    """Replace an (often orphaned) ref in-place with ``new_ref``."""
    if board.layout_mode == LAYOUT_MODE_FREE_GRID:
        for item in board.free_grid:
            if item.ref == old_ref:
                if new_ref in membership_set(board):
                    _remove_ref_everywhere(board, old_ref)
                else:
                    item.ref = new_ref
                return []
    placement = placement_for(board, old_ref)
    in_tray = old_ref in board.unplaced
    if placement is None and not in_tray:
        return [_warn("unknown_ref", f"{old_ref.section}/{old_ref.view_id}")]
    if new_ref == old_ref:
        return []
    if new_ref in membership_set(board):
        _remove_ref_everywhere(board, old_ref)
        return []
    if placement is not None:
        _remove_ref_everywhere(board, old_ref)
        _place(board, placement.slot_id, new_ref)
        return []
    _remove_ref_everywhere(board, old_ref)
    _append_unplaced(board, new_ref)
    return []


def _coerce_grid_int(value: object, *, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _legal_grid_rect(
    raw: Mapping[str, Any] | GridRect,
    *,
    warnings: list[str] | None = None,
) -> GridRect | None:
    if isinstance(raw, GridRect):
        values = (raw.column, raw.row, raw.column_span, raw.row_span)
    elif isinstance(raw, Mapping):
        values = (
            _coerce_grid_int(raw.get("column"), default=0),
            _coerce_grid_int(raw.get("row"), default=0),
            _coerce_grid_int(raw.get("column_span"), default=4),
            _coerce_grid_int(raw.get("row_span"), default=3),
        )
    else:
        return None
    column, row, col_span, row_span = values
    parsed = GridRect(int(column), int(row), int(col_span), int(row_span))
    legal = clamp_grid_rect(parsed)
    if warnings is not None and legal != parsed:
        warnings.append(
            _warn(
                "grid_rect_clamped",
                f"{parsed.column},{parsed.row},{parsed.column_span},{parsed.row_span}",
            )
        )
    return legal


def _legacy_grid_rect(
    raw: Mapping[str, Any], *, warnings: list[str] | None = None
) -> GridRect:
    """Legalize a schema-1–4 rect, then lift it into schema-5 coordinates.

    Legacy validation intentionally happens before scaling.  Applying the
    schema-5 four-cell floor first would turn a valid old 4×3 card into 8×8,
    changing its physical height during the migration.
    """
    parsed = GridRect(
        _coerce_grid_int(raw.get("column"), default=0),
        _coerce_grid_int(raw.get("row"), default=0),
        _coerce_grid_int(raw.get("column_span"), default=4),
        _coerce_grid_int(raw.get("row_span"), default=3),
    )
    col_span = min(LEGACY_GRID_COLUMNS, max(2, int(parsed.column_span)))
    row_span = min(8, max(2, int(parsed.row_span)))
    legal = GridRect(
        column=min(60 - col_span, max(-48, int(parsed.column))),
        row=min(96 - row_span, max(-48, int(parsed.row))),
        column_span=col_span,
        row_span=row_span,
    )
    if warnings is not None and legal != parsed:
        warnings.append(
            _warn(
                "grid_rect_clamped",
                f"{parsed.column},{parsed.row},{parsed.column_span},{parsed.row_span}",
            )
        )
    return GridRect(
        legal.column * GRID_RESOLUTION,
        legal.row * GRID_RESOLUTION,
        legal.column_span * GRID_RESOLUTION,
        legal.row_span * GRID_RESOLUTION,
    )


def _grid_overlaps(left: GridRect, right: GridRect) -> bool:
    return (
        left.column < right.column + right.column_span
        and right.column < left.column + left.column_span
        and left.row < right.row + right.row_span
        and right.row < left.row + left.row_span
    )


def _iter_safety_origins(col_span: int, row_span: int):
    """Every legal origin for ``(col_span, row_span)`` inside safety bounds."""
    for row in range(SAFETY_ROW_MIN, SAFETY_ROW_MAX - row_span + 1):
        for column in range(SAFETY_COLUMN_MIN, SAFETY_COLUMN_MAX - col_span + 1):
            yield column, row


def _iter_first_free_origins(col_span: int, row_span: int):
    """Base-frame origins first so legacy first-fit still lands at ``(0, 0)``."""
    base_row_last = MAX_GRID_ROWS - row_span
    base_col_last = GRID_COLUMNS - col_span
    for row in range(0, base_row_last + 1):
        for column in range(0, base_col_last + 1):
            yield column, row
    for column, row in _iter_safety_origins(col_span, row_span):
        if 0 <= row <= base_row_last and 0 <= column <= base_col_last:
            continue
        yield column, row


def _first_free_grid_rect(
    placements: Sequence[FreeGridPlacement], *, span: tuple[int, int] = (4, 3)
) -> GridRect | None:
    prototype = _legal_grid_rect({"column": 0, "row": 0, "column_span": span[0], "row_span": span[1]})
    if prototype is None:
        return None
    for column, row in _iter_first_free_origins(prototype.column_span, prototype.row_span):
        candidate = GridRect(column, row, prototype.column_span, prototype.row_span)
        if not any(_grid_overlaps(candidate, item.rect) for item in placements):
            return candidate
    return None


def free_grid_default_span(board: UltraViewBoardState) -> tuple[int, int]:
    """Resolve the persisted preset name without widening payload semantics."""
    return FREE_GRID_PRESETS.get(
        str(board.free_grid_default_size), FREE_GRID_PRESETS["standard"]
    )


def _resolved_insert_span(
    board: UltraViewBoardState, span: tuple[int, int] | None
) -> tuple[int, int]:
    if span is None:
        return free_grid_default_span(board)
    try:
        column_span, row_span = int(span[0]), int(span[1])
    except (TypeError, ValueError, IndexError):
        return free_grid_default_span(board)
    legal = _legal_grid_rect(
        {
            "column": 0,
            "row": 0,
            "column_span": column_span,
            "row_span": row_span,
        }
    )
    if legal is None:
        return free_grid_default_span(board)
    return (legal.column_span, legal.row_span)


def capture_board_placement(board: UltraViewBoardState) -> BoardPlacementSnapshot:
    """Immutable placement snapshot. Safe to keep on an undo stack."""
    return BoardPlacementSnapshot(
        layout_mode=str(board.layout_mode),
        layout_id=str(board.layout_id),
        primary_ratio=float(board.primary_ratio),
        placements=tuple((item.slot_id, item.ref) for item in board.placements),
        free_grid=tuple((item.ref, item.rect) for item in board.free_grid),
        unplaced=tuple(board.unplaced),
    )


def apply_board_placement(
    board: UltraViewBoardState, snapshot: BoardPlacementSnapshot
) -> bool:
    """Restore exact membership, tray order, slots, and GridRects.

    Does not first-fit, re-anchor, or consult PreviewStore. Returns False
    only when ``snapshot`` is not a placement snapshot.
    """
    if not isinstance(snapshot, BoardPlacementSnapshot):
        return False
    board.layout_mode = snapshot.layout_mode
    board.layout_id = snapshot.layout_id
    board.primary_ratio = snapshot.primary_ratio
    board.placements = [
        CardPlacement(slot_id, ref) for slot_id, ref in snapshot.placements
    ]
    board.free_grid = [
        FreeGridPlacement(ref, rect) for ref, rect in snapshot.free_grid
    ]
    board.unplaced = list(snapshot.unplaced)
    return True


def _nearest_grid_index(value: float) -> int:
    """Round half upward so replay does not depend on Python's banker's round."""
    return int(math.floor(float(value) + 0.5))


def resolve_free_grid_insert_rect(
    placements: Sequence[FreeGridPlacement],
    *,
    span: tuple[int, int],
    anchor: GridAnchor,
) -> GridRect | None:
    """Return the unoccupied rectangle whose centre is nearest ``anchor``.

    This is intentionally a pure insertion resolver.  Unlike the interactive
    layout planner, it never moves or resizes an existing placement.
    """
    prototype = _legal_grid_rect(
        {
            "column": 0,
            "row": 0,
            "column_span": span[0],
            "row_span": span[1],
        }
    )
    if prototype is None:
        return None
    requested = _legal_grid_rect(
        {
            "column": _nearest_grid_index(anchor.column - prototype.column_span / 2.0),
            "row": _nearest_grid_index(anchor.row - prototype.row_span / 2.0),
            "column_span": prototype.column_span,
            "row_span": prototype.row_span,
        }
    )
    if requested is not None and not any(
        _grid_overlaps(requested, item.rect) for item in placements
    ):
        return requested

    candidates: list[tuple[float, int, int, GridRect]] = []
    for column, row in _iter_safety_origins(prototype.column_span, prototype.row_span):
        candidate = GridRect(
            column, row, prototype.column_span, prototype.row_span
        )
        if any(_grid_overlaps(candidate, item.rect) for item in placements):
            continue
        centre_column = candidate.column + candidate.column_span / 2.0
        centre_row = candidate.row + candidate.row_span / 2.0
        distance_sq = (
            (centre_column - anchor.column) ** 2
            + (centre_row - anchor.row) ** 2
        )
        candidates.append((distance_sq, row, column, candidate))
    if not candidates:
        return None
    return min(candidates)[3]


def template_to_free_grid(board: UltraViewBoardState) -> list[str]:
    if board.layout_mode == LAYOUT_MODE_FREE_GRID:
        return []
    placements = list(board.placements)
    board.placements.clear()
    board.free_grid.clear()
    board.layout_mode = LAYOUT_MODE_FREE_GRID
    rects = _template_grid_rects(board.layout_id)
    for index, item in enumerate(placements):
        rect = rects[index] if index < len(rects) else _first_free_grid_rect(board.free_grid)
        if rect is None or len(board.free_grid) >= MAX_PLACED_CARDS:
            _append_unplaced(board, item.ref)
        else:
            board.free_grid.append(FreeGridPlacement(item.ref, rect))
    return []


def free_grid_to_template(
    board: UltraViewBoardState, layout_id: str = DEFAULT_LAYOUT_ID
) -> list[str]:
    refs = sorted(
        board.free_grid,
        key=lambda item: (item.rect.row, item.rect.column, item.ref.section, item.ref.view_id),
    )
    tray_refs = list(board.unplaced)
    board.free_grid.clear()
    board.unplaced.clear()
    board.layout_mode = LAYOUT_MODE_TEMPLATE
    board.layout_id = layout_id if layout_id in LAYOUT_SLOTS else DEFAULT_LAYOUT_ID
    board.placements.clear()
    for item in refs:
        add_ref(board, item.ref)
    for ref in tray_refs:
        if ref not in membership_set(board):
            _append_unplaced(board, ref)
    return []


def set_free_grid_rect(board: UltraViewBoardState, ref: UltraViewRef, rect: GridRect) -> list[str]:
    if board.layout_mode != LAYOUT_MODE_FREE_GRID:
        return [_warn("not_free_grid")]
    legal = _legal_grid_rect(rect)
    if legal is None:
        return [_warn("invalid_grid_rect")]
    for item in board.free_grid:
        if item.ref == ref:
            if any(_grid_overlaps(legal, other.rect) for other in board.free_grid if other.ref != ref):
                return [_warn("grid_collision")]
            item.rect = legal
            return []
    return [_warn("unknown_ref", f"{ref.section}/{ref.view_id}")]


def set_free_grid_rects(
    board: UltraViewBoardState,
    updates: Sequence[tuple[UltraViewRef, GridRect]],
) -> list[str]:
    """Apply several free-grid moves atomically. Overflow is not clamped."""
    if board.layout_mode != LAYOUT_MODE_FREE_GRID:
        return [_warn("not_free_grid")]
    if not updates:
        return []
    by_ref = {item.ref: item for item in board.free_grid}
    proposed: dict[UltraViewRef, GridRect] = {}
    for ref, rect in updates:
        if ref not in by_ref:
            return [_warn("unknown_ref", f"{ref.section}/{ref.view_id}")]
        legal = _legal_grid_rect(rect)
        if legal is None or legal != rect:
            return [_warn("invalid_grid_rect")]
        proposed[ref] = legal
    new_rects = {
        item.ref: proposed.get(item.ref, item.rect) for item in board.free_grid
    }
    items = tuple(new_rects.items())
    for index, (_ref_a, rect_a) in enumerate(items):
        for _ref_b, rect_b in items[index + 1 :]:
            if _grid_overlaps(rect_a, rect_b):
                return [_warn("grid_collision")]
    for item in board.free_grid:
        replacement = proposed.get(item.ref)
        if replacement is not None:
            item.rect = replacement
    return []


def free_grid_placement_for(
    board: UltraViewBoardState, ref: UltraViewRef
) -> FreeGridPlacement | None:
    for item in board.free_grid:
        if item.ref == ref:
            return item
    return None


def apply_free_grid_preset(
    board: UltraViewBoardState, ref: UltraViewRef, preset: str
) -> list[str]:
    span = FREE_GRID_PRESETS.get(str(preset))
    if span is None:
        return [_warn("unknown_grid_preset", str(preset))]
    item = free_grid_placement_for(board, ref)
    if item is None:
        return [_warn("unknown_ref", f"{ref.section}/{ref.view_id}")]
    return set_free_grid_rect(
        board,
        ref,
        GridRect(item.rect.column, item.rect.row, span[0], span[1]),
    )


def organized_placements(
    placements: Sequence[FreeGridPlacement],
) -> list[FreeGridPlacement]:
    """Remove fully empty rows while retaining each card's size/order/column.

    Empty rows compress toward row 0 (the base-frame origin) from both
    sides, so a legacy board whose cards sit at rows 2 and 5 still packs to
    0 and 2, and signed cards above the origin pack downward toward 0.
    """
    occupied_rows = {
        row
        for item in placements
        for row in range(item.rect.row, item.rect.row + item.rect.row_span)
    }
    result: list[FreeGridPlacement] = []
    for item in placements:
        rect = item.rect
        if rect.row >= 0:
            shift = sum(1 for row in range(0, rect.row) if row not in occupied_rows)
            new_row = rect.row - shift
        else:
            shift = sum(1 for row in range(rect.row, 0) if row not in occupied_rows)
            new_row = rect.row + shift
        result.append(
            FreeGridPlacement(
                item.ref,
                GridRect(rect.column, new_row, rect.column_span, rect.row_span),
            )
        )
    return result


def organize_free_grid(board: UltraViewBoardState) -> list[str]:
    """Remove only wholly empty rows, preserving card order/columns/spans."""
    if board.layout_mode != LAYOUT_MODE_FREE_GRID:
        return [_warn("not_free_grid")]
    board.free_grid = organized_placements(board.free_grid)
    return []


def _template_grid_rects(layout_id: str) -> list[GridRect]:
    """Frozen conversion map from P0/P1 templates to schema-5 micro-grid."""
    maps: dict[str, list[GridRect]] = {
        "split_horizontal": [GridRect(0, 0, 6, 3), GridRect(6, 0, 6, 3)],
        "split_vertical": [GridRect(0, 0, 12, 3), GridRect(0, 3, 12, 3)],
        "grid_2x2": [
            GridRect(0, 0, 6, 3), GridRect(6, 0, 6, 3),
            GridRect(0, 3, 6, 3), GridRect(6, 3, 6, 3),
        ],
        "hero_left_4": [
            GridRect(0, 0, 8, 6), GridRect(8, 0, 4, 2),
            GridRect(8, 2, 4, 2), GridRect(8, 4, 4, 2),
        ],
        "hero_top_4": [
            GridRect(0, 0, 12, 3), GridRect(0, 3, 4, 3),
            GridRect(4, 3, 4, 3), GridRect(8, 3, 4, 3),
        ],
    }
    if layout_id in maps:
        return [_scale_legacy_grid_rect(rect) for rect in maps[layout_id]]
    if layout_id == "grid_3x2":
        return [_scale_legacy_grid_rect(GridRect(col * 4, row * 3, 4, 3)) for row in range(2) for col in range(3)]
    if layout_id == "grid_3x3":
        return [_scale_legacy_grid_rect(GridRect(col * 4, row * 3, 4, 3)) for row in range(3) for col in range(3)]
    if layout_id == "grid_4x3":
        return [_scale_legacy_grid_rect(GridRect(col * 3, row * 3, 3, 3)) for row in range(3) for col in range(4)]
    return _template_grid_rects(DEFAULT_LAYOUT_ID)


def _scale_legacy_grid_rect(rect: GridRect) -> GridRect:
    return GridRect(
        rect.column * GRID_RESOLUTION,
        rect.row * GRID_RESOLUTION,
        rect.column_span * GRID_RESOLUTION,
        rect.row_span * GRID_RESOLUTION,
    )


def set_presentation_flags(
    board: UltraViewBoardState,
    *,
    show_titles: bool | None = None,
    show_sources: bool | None = None,
) -> list[str]:
    """Apply only explicitly supplied Board presentation flags."""
    if show_titles is not None:
        board.show_titles = bool(show_titles)
    if show_sources is not None:
        board.show_sources = bool(show_sources)
    return []


_RECOGNIZED_AUTHOR_KINDS = frozenset({"sticky", "text", "shape", "stroke", "connector"})


def _point_from_payload(raw: object) -> BoardPoint:
    if not isinstance(raw, Mapping):
        raise UltraViewStateError("point must be a mapping")
    return BoardPoint(raw.get("x"), raw.get("y"))


def _box_from_payload(raw: object) -> BoardBox:
    if not isinstance(raw, Mapping):
        raise UltraViewStateError("box must be a mapping")
    return BoardBox(raw.get("x"), raw.get("y"), raw.get("width"), raw.get("height"))


def _anchor_target_from_payload(raw: object) -> AnchorTarget | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise UltraViewStateError("anchor target must be a mapping or null")
    kind = raw.get("kind")
    anchor = raw.get("anchor", "auto")
    if kind == "card":
        card_raw = raw.get("card", raw.get("ref"))
        card = parse_ref_payload(card_raw if isinstance(card_raw, Mapping) else None)
        if card is None:
            raise UltraViewStateError("card anchor target must contain a structured ref")
        return AnchorTarget("card", card=card, anchor=anchor)
    if kind == "author":
        return AnchorTarget("author", object_id=raw.get("object_id"), anchor=anchor)
    raise UltraViewStateError("anchor target kind must be card or author")


def _endpoint_from_payload(raw: object) -> ConnectorEndpoint:
    if not isinstance(raw, Mapping):
        raise UltraViewStateError("connector endpoint must be a mapping")
    return ConnectorEndpoint(
        point=_point_from_payload(raw.get("point")),
        target=_anchor_target_from_payload(raw.get("target")),
    )


def _shape_text_style_from_payload(raw: object) -> ShapeTextStyle:
    if raw is None:
        return ShapeTextStyle()
    if not isinstance(raw, Mapping):
        raise UltraViewStateError("shape text style must be a mapping")
    return ShapeTextStyle(
        font_size=raw.get("font_size", 14),
        bold=raw.get("bold", False),
        italic=raw.get("italic", False),
        underline=raw.get("underline", False),
        align=raw.get("align", "center"),
        text_palette=raw.get("text_palette", "ink"),
    )


def _recognized_author_object_from_payload(raw: Mapping[str, Any]) -> AuthorObject:
    kind = raw.get("kind")
    common = {
        "object_id": raw.get("id"),
        "kind": kind,
        "locked": raw.get("locked", False),
    }
    if kind == "sticky":
        return StickyObject(
            **common,
            box=_box_from_payload(raw.get("box")),
            text=raw.get("text", ""),
            palette=raw.get("palette", "yellow"),
            shape=raw.get("shape", "square"),
            font_size=raw.get("font_size", "auto"),
        )
    if kind == "text":
        return TextObject(
            **common,
            box=_box_from_payload(raw.get("box")),
            text=raw.get("text", ""),
            font_role=raw.get("font_role", "sans"),
            font_size=raw.get("font_size", 14),
            bold=raw.get("bold", False),
            italic=raw.get("italic", False),
            underline=raw.get("underline", False),
            align=raw.get("align", "left"),
            list_style=raw.get("list_style", "none"),
            text_palette=raw.get("text_palette", "ink"),
            fill_palette=raw.get("fill_palette"),
            opacity=raw.get("opacity", 100),
            link=raw.get("link"),
        )
    if kind == "shape":
        return ShapeObject(
            **common,
            box=_box_from_payload(raw.get("box")),
            shape=raw.get("shape", "rectangle"),
            text=raw.get("text", ""),
            fill_palette=raw.get("fill_palette"),
            stroke_palette=raw.get("stroke_palette", "ink"),
            stroke_width=raw.get("stroke_width", 1),
            line_style=raw.get("line_style", "solid"),
            text_style=_shape_text_style_from_payload(raw.get("text_style")),
        )
    if kind == "stroke":
        raw_points = raw.get("points")
        if not isinstance(raw_points, list):
            raise UltraViewStateError("stroke points must be a list")
        return StrokeObject(
            **common,
            points=tuple(_point_from_payload(point) for point in raw_points),
            tool=raw.get("tool", "pen"),
            palette=raw.get("palette", "ink"),
            width_px_100=raw.get("width_px_100", 1),
        )
    if kind == "connector":
        return ConnectorObject(
            **common,
            start=_endpoint_from_payload(raw.get("start")),
            end=_endpoint_from_payload(raw.get("end")),
            route=raw.get("route", "straight"),
            elbow_bias=raw.get("elbow_bias"),
            line_style=raw.get("line_style", "solid"),
            stroke_palette=raw.get("stroke_palette", "ink"),
            stroke_width=raw.get("stroke_width", 1),
            start_head=raw.get("start_head", "none"),
            end_head=raw.get("end_head", "arrow"),
        )
    raise UltraViewStateError("unrecognized author kind")


def author_object_to_payload(item: AuthorObject) -> dict[str, Any]:
    """Serialize one author object as a new, JSON-ready mapping."""
    if isinstance(item, UnknownAuthorObject):
        return deepcopy(item.raw)
    common = {"id": item.object_id, "kind": item.kind, "locked": bool(item.locked)}
    if isinstance(item, StickyObject):
        return {
            **common, "box": item.box.to_dict(), "text": item.text, "palette": item.palette,
            "shape": item.shape, "font_size": item.font_size,
        }
    if isinstance(item, TextObject):
        return {
            **common, "box": item.box.to_dict(), "text": item.text, "font_role": item.font_role,
            "font_size": item.font_size, "bold": bool(item.bold), "italic": bool(item.italic),
            "underline": bool(item.underline), "align": item.align, "list_style": item.list_style,
            "text_palette": item.text_palette, "fill_palette": item.fill_palette,
            "opacity": item.opacity, "link": item.link,
        }
    if isinstance(item, ShapeObject):
        return {
            **common, "box": item.box.to_dict(), "shape": item.shape, "text": item.text,
            "fill_palette": item.fill_palette, "stroke_palette": item.stroke_palette,
            "stroke_width": item.stroke_width, "line_style": item.line_style,
            "text_style": item.text_style.to_dict(),
        }
    if isinstance(item, StrokeObject):
        return {
            **common, "points": [point.to_dict() for point in item.points], "tool": item.tool,
            "palette": item.palette, "width_px_100": item.width_px_100,
        }
    if isinstance(item, ConnectorObject):
        return {
            **common, "start": item.start.to_dict(), "end": item.end.to_dict(),
            "route": item.route, "elbow_bias": item.elbow_bias, "line_style": item.line_style,
            "stroke_palette": item.stroke_palette, "stroke_width": item.stroke_width,
            "start_head": item.start_head, "end_head": item.end_head,
        }
    raise TypeError(f"unsupported author object {type(item).__name__}")


def _clone_author_objects(items: Sequence[AuthorObject]) -> list[AuthorObject]:
    """Clone via payload so future raw mappings and every nested list are isolated."""
    cloned: list[AuthorObject] = []
    for item in items:
        raw = author_object_to_payload(item)
        if isinstance(item, UnknownAuthorObject):
            cloned.append(UnknownAuthorObject(deepcopy(raw)))
        else:
            cloned.append(_recognized_author_object_from_payload(raw))
    return cloned


def _author_object_id(item: AuthorObject) -> str:
    """Return a stable id for known and opaque future objects alike."""
    if isinstance(item, UnknownAuthorObject):
        return _author_id(item.raw.get("id"))
    return item.object_id


def _author_object_from_payload(raw: Mapping[str, Any]) -> AuthorObject:
    """Decode one history payload without dropping an unknown future kind."""
    copied = deepcopy(dict(raw))
    _author_id(copied.get("id"))
    kind = copied.get("kind")
    if not isinstance(kind, str):
        raise UltraViewStateError("author object kind must be a string")
    if kind in _RECOGNIZED_AUTHOR_KINDS:
        return _recognized_author_object_from_payload(copied)
    return UnknownAuthorObject(copied)


def _author_objects_valid(items: Sequence[AuthorObject]) -> bool:
    """Strict mutation-time limits; normalization warnings are not a mutation API."""
    if len(items) > MAX_AUTHOR_OBJECTS:
        return False
    seen: set[str] = set()
    total_points = 0
    try:
        for item in items:
            object_id = _author_object_id(item)
            if object_id in seen:
                return False
            seen.add(object_id)
            if isinstance(item, StrokeObject):
                total_points += len(item.points)
                if total_points > MAX_AUTHOR_POINTS:
                    return False
    except UltraViewStateError:
        return False
    return True


def _payload_equal(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    """JSON payload equality keeps unknown nested mappings deterministic."""
    try:
        return json.dumps(first, ensure_ascii=False, sort_keys=True, separators=(",", ":")) == json.dumps(
            second, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError):
        return first == second


def _author_patch_candidate(
    items: Sequence[AuthorObject],
    patches: Sequence[ObjectPatch],
    *,
    forward: bool,
) -> list[AuthorObject] | None:
    """Build a target z-order without mutating ``items`` on a failed patch."""
    if not patches:
        return _clone_author_objects(items)
    if len({patch.object_id for patch in patches}) != len(patches):
        return None
    current = _clone_author_objects(items)
    current_ids = [_author_object_id(item) for item in current]
    if len(set(current_ids)) != len(current_ids):
        return None
    target_values: list[tuple[int, AuthorObject]] = []
    removed_ids: set[str] = set()
    for patch in patches:
        source = patch.before if forward else patch.after
        source_index = patch.before_index if forward else patch.after_index
        target = patch.after if forward else patch.before
        target_index = patch.after_index if forward else patch.before_index
        if source is None:
            if patch.object_id in current_ids:
                return None
        else:
            assert source_index is not None
            if source_index >= len(current) or current_ids[source_index] != patch.object_id:
                return None
            if not _payload_equal(author_object_to_payload(current[source_index]), source):
                return None
            removed_ids.add(patch.object_id)
        if target is not None:
            assert target_index is not None
            try:
                decoded = _author_object_from_payload(target)
            except UltraViewStateError:
                return None
            if _author_object_id(decoded) != patch.object_id:
                return None
            target_values.append((target_index, decoded))

    retained = [item for item in current if _author_object_id(item) not in removed_ids]
    retained_ids = {_author_object_id(item) for item in retained}
    target_ids = [_author_object_id(item) for _index, item in target_values]
    if len(set(target_ids)) != len(target_ids) or retained_ids.intersection(target_ids):
        return None
    final_size = len(retained) + len(target_values)
    target_indexes = [index for index, _item in target_values]
    if (
        len(set(target_indexes)) != len(target_indexes)
        or any(index < 0 or index >= final_size for index in target_indexes)
    ):
        return None
    candidate = list(retained)
    for index, item in sorted(target_values, key=lambda pair: pair[0]):
        candidate.insert(index, item)
    return candidate if _author_objects_valid(candidate) else None


def apply_author_patches(
    board: UltraViewBoardState,
    patches: Sequence[ObjectPatch],
    *,
    forward: bool,
) -> bool:
    """Atomically apply the before or after side of object patches."""
    candidate = _author_patch_candidate(board.author_objects, patches, forward=forward)
    if candidate is None:
        return False
    board.author_objects = candidate
    return True


def _author_mutation(patches: Sequence[ObjectPatch]) -> AuthorMutationResult:
    return AuthorMutationResult(tuple(patches), ())


def _author_warning(code: str) -> AuthorMutationResult:
    return AuthorMutationResult((), (code,))


def _author_index(board: UltraViewBoardState, object_id: str) -> int | None:
    try:
        checked = _author_id(object_id)
    except UltraViewStateError:
        return None
    for index, item in enumerate(board.author_objects):
        if _author_object_id(item) == checked:
            return index
    return None


def create_author_object(
    board: UltraViewBoardState,
    item: AuthorObject,
    *,
    index: int | None = None,
) -> AuthorMutationResult:
    """Insert one typed or opaque author object and return its reversible patch."""
    try:
        payload = author_object_to_payload(item)
        object_id = _author_id(payload.get("id"))
    except (TypeError, UltraViewStateError):
        return _author_warning("illegal_author_object")
    if _author_index(board, object_id) is not None:
        return _author_warning("duplicate_author_object_id")
    target_index = len(board.author_objects) if index is None else index
    if isinstance(target_index, bool) or not isinstance(target_index, int) or not 0 <= target_index <= len(board.author_objects):
        return _author_warning("illegal_author_index")
    patch = ObjectPatch(object_id, None, payload, None, target_index)
    if not apply_author_patches(board, (patch,), forward=True):
        return _author_warning("author_object_limit")
    return _author_mutation((patch,))


def update_author_object(
    board: UltraViewBoardState,
    object_id: str,
    item: AuthorObject,
) -> AuthorMutationResult:
    """Replace one object payload in place (style/text/geometry are all one patch)."""
    index = _author_index(board, object_id)
    if index is None:
        return _author_warning("author_object_missing")
    try:
        before = author_object_to_payload(board.author_objects[index])
        after = author_object_to_payload(item)
        checked = _author_id(object_id)
    except (TypeError, UltraViewStateError):
        return _author_warning("illegal_author_object")
    if _author_id(after.get("id")) != checked:
        return _author_warning("author_object_id_changed")
    if _payload_equal(before, after):
        return AuthorMutationResult()
    patch = ObjectPatch(checked, before, after, index, index)
    if not apply_author_patches(board, (patch,), forward=True):
        return _author_warning("illegal_author_object")
    return _author_mutation((patch,))


def delete_author_objects(
    board: UltraViewBoardState, object_ids: Iterable[str]
) -> AuthorMutationResult:
    """Delete a deterministic sweep of objects as one multi-patch mutation."""
    requested: set[str] = set()
    for object_id in object_ids:
        try:
            requested.add(_author_id(object_id))
        except UltraViewStateError:
            return _author_warning("illegal_author_object_id")
    patches = tuple(
        ObjectPatch(
            _author_object_id(item), author_object_to_payload(item), None, index, None
        )
        for index, item in enumerate(board.author_objects)
        if _author_object_id(item) in requested
    )
    if not patches:
        return _author_warning("author_object_missing")
    if not apply_author_patches(board, patches, forward=True):
        return _author_warning("illegal_author_object")
    return _author_mutation(patches)


def reorder_author_object(
    board: UltraViewBoardState, object_id: str, index: int
) -> AuthorMutationResult:
    """Move an object to its final author z-order index."""
    before_index = _author_index(board, object_id)
    if before_index is None:
        return _author_warning("author_object_missing")
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(board.author_objects):
        return _author_warning("illegal_author_index")
    if index == before_index:
        return AuthorMutationResult()
    item = board.author_objects[before_index]
    payload = author_object_to_payload(item)
    patch = ObjectPatch(_author_object_id(item), payload, payload, before_index, index)
    if not apply_author_patches(board, (patch,), forward=True):
        return _author_warning("illegal_author_object")
    return _author_mutation((patch,))


def set_author_locked(
    board: UltraViewBoardState, object_id: str, locked: bool
) -> AuthorMutationResult:
    """Set a known author's lock bit without special-casing a renderer."""
    index = _author_index(board, object_id)
    if index is None:
        return _author_warning("author_object_missing")
    item = board.author_objects[index]
    if isinstance(item, UnknownAuthorObject):
        return _author_warning("unknown_author_object")
    return update_author_object(board, object_id, replace(item, locked=bool(locked)))


def _placement_snapshot_payload(snapshot: BoardPlacementSnapshot) -> dict[str, Any]:
    return {
        "layout_mode": snapshot.layout_mode,
        "layout_id": snapshot.layout_id,
        "primary_ratio": snapshot.primary_ratio,
        "placements": [
            {"slot_id": slot_id, "ref": ref.to_dict()}
            for slot_id, ref in snapshot.placements
        ],
        "free_grid": [
            {"ref": ref.to_dict(), "rect": rect.__dict__}
            for ref, rect in snapshot.free_grid
        ],
        "unplaced": [ref.to_dict() for ref in snapshot.unplaced],
    }


def board_edit_entry_byte_cost(entry: BoardEditEntry) -> int:
    """Stable UTF-8 payload cost used by the bounded per-Board history."""
    payload = {
        "label": entry.label,
        "placement_before": None if entry.placement_before is None else _placement_snapshot_payload(entry.placement_before),
        "placement_after": None if entry.placement_after is None else _placement_snapshot_payload(entry.placement_after),
        "object_patches": [
            {
                "object_id": patch.object_id,
                "before": patch.before,
                "after": patch.after,
                "before_index": patch.before_index,
                "after_index": patch.after_index,
            }
            for patch in entry.object_patches
        ],
    }
    try:
        return len(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError):
        # A future opaque object that cannot be represented as JSON must never
        # silently evade the byte budget.
        return 32 * 1024 * 1024 + 1


def apply_board_edit_entry(
    board: UltraViewBoardState,
    entry: BoardEditEntry,
    *,
    forward: bool,
) -> bool:
    """Restore a mixed placement+author edit atomically or leave ``board`` untouched."""
    staged = replace(
        board,
        placements=[CardPlacement(item.slot_id, item.ref) for item in board.placements],
        unplaced=list(board.unplaced),
        free_grid=[FreeGridPlacement(item.ref, item.rect) for item in board.free_grid],
        author_objects=_clone_author_objects(board.author_objects),
    )
    snapshot = entry.placement_after if forward else entry.placement_before
    if snapshot is not None and not apply_board_placement(staged, snapshot):
        return False
    if entry.object_patches and not apply_author_patches(
        staged, entry.object_patches, forward=forward
    ):
        return False
    if snapshot is not None:
        board.layout_mode = staged.layout_mode
        board.layout_id = staged.layout_id
        board.primary_ratio = staged.primary_ratio
        board.placements = staged.placements
        board.free_grid = staged.free_grid
        board.unplaced = staged.unplaced
    if entry.object_patches:
        board.author_objects = staged.author_objects
    return True


def _reconcile_connector_targets(
    objects: Sequence[AuthorObject],
    *,
    placed_cards: set[UltraViewRef],
    warnings: list[str],
) -> list[AuthorObject]:
    anchorable_ids = {
        item.object_id
        for item in objects
        if isinstance(item, (StickyObject, TextObject, ShapeObject))
    }

    def detached(endpoint: ConnectorEndpoint) -> ConnectorEndpoint:
        target = endpoint.target
        if target is None:
            return endpoint
        if target.kind == "author" and target.object_id not in anchorable_ids:
            warnings.append(_warn("dangling_author_target", str(target.object_id)))
            return replace(endpoint, target=None)
        if target.kind == "card" and target.card not in placed_cards:
            detail = "" if target.card is None else f"{target.card.section}/{target.card.view_id}"
            warnings.append(_warn("dangling_card_target", detail))
            return replace(endpoint, target=None)
        return endpoint

    normalized: list[AuthorObject] = []
    for item in objects:
        if isinstance(item, ConnectorObject):
            normalized.append(replace(item, start=detached(item.start), end=detached(item.end)))
        else:
            normalized.append(item)
    return normalized


def _normalize_author_objects(
    raw_objects: object,
    *,
    placed_cards: set[UltraViewRef],
    warnings: list[str],
) -> list[AuthorObject]:
    if raw_objects is None:
        return []
    if not isinstance(raw_objects, list):
        warnings.append(_warn("illegal_author_objects", type(raw_objects).__name__))
        return []
    objects: list[AuthorObject] = []
    seen_ids: set[str] = set()
    total_points = 0
    for raw in raw_objects:
        if len(objects) >= MAX_AUTHOR_OBJECTS:
            warnings.append(_warn("author_object_limit"))
            break
        if not isinstance(raw, Mapping):
            warnings.append(_warn("illegal_author_object", type(raw).__name__))
            continue
        kind = raw.get("kind")
        if not isinstance(kind, str) or kind not in _RECOGNIZED_AUTHOR_KINDS:
            objects.append(UnknownAuthorObject(deepcopy(dict(raw))))
            continue
        object_id = raw.get("id")
        try:
            checked_id = _author_id(object_id)
        except UltraViewStateError:
            checked_id = str(object_id)
        if checked_id in seen_ids:
            warnings.append(_warn("duplicate_author_object_id", checked_id))
            continue
        try:
            item = _recognized_author_object_from_payload(raw)
        except UltraViewStateError:
            warnings.append(_warn("illegal_author_object", f"{kind}/{checked_id}"))
            continue
        if isinstance(item, StrokeObject) and total_points + len(item.points) > MAX_AUTHOR_POINTS:
            warnings.append(_warn("author_point_limit", item.object_id))
            continue
        seen_ids.add(item.object_id)
        if isinstance(item, StrokeObject):
            total_points += len(item.points)
        objects.append(item)
    return _reconcile_connector_targets(objects, placed_cards=placed_cards, warnings=warnings)


def board_identity_payload(board: UltraViewBoardState) -> dict[str, Any]:
    """Card-presentation payload without transient/authoring-only content."""
    payload = _board_payload(board)
    payload.pop("viewport", None)
    # Preview freshness describes captured analysis cards.  Board notes and
    # ink must persist and export, but cannot stale an otherwise unchanged
    # card preview or perturb the capture digest.
    payload.pop("author_objects", None)
    return payload


def _board_payload(board: UltraViewBoardState) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "board_id": board.board_id,
        "name": board.name,
        "show_titles": bool(board.show_titles),
        "show_sources": bool(board.show_sources),
        "unplaced": [ref.to_dict() for ref in board.unplaced],
        "layout_mode": board.layout_mode,
        # Free-grid mode still needs the last template identity so closing the
        # grid (and a later project reopen) can restore the same slots.
        "layout_id": board.layout_id,
        "primary_ratio": board.primary_ratio,
    }
    for key, value in board.passthrough.items():
        if key not in payload:
            # Serialization is a snapshot, not an alias to mutable state.
            payload[key] = deepcopy(value)
    if board.layout_mode == LAYOUT_MODE_FREE_GRID:
        payload["free_grid"] = {
            "columns": GRID_COLUMNS,
            "default_size": board.free_grid_default_size,
            "placements": [
                {**item.ref.to_dict(), "column": item.rect.column, "row": item.rect.row,
                 "column_span": item.rect.column_span, "row_span": item.rect.row_span}
                for item in board.free_grid
            ],
        }
    else:
        payload["placements"] = [
            {"slot_id": item.slot_id, **item.ref.to_dict()} for item in board.placements
        ]
    # Omit the empty additive field so loading and re-saving a pre-authoring
    # board produces no needless payload churn.
    if board.author_objects:
        payload["author_objects"] = [
            author_object_to_payload(item) for item in board.author_objects
        ]
    return payload


def board_to_payload(board: UltraViewBoardState) -> dict[str, Any]:
    return {"schema": ULTRAVIEW_SCHEMA, "board": _board_payload(board)}


def normalize_board_payload(
    payload: Mapping[str, Any] | None,
) -> tuple[UltraViewBoardState, list[str]]:
    """Legalize a persisted UltraView payload. Never silently drop without warning."""
    warnings: list[str] = []
    if payload is None:
        return default_board(), warnings
    if not isinstance(payload, Mapping):
        warnings.append(_warn("unknown_ultraview_schema", type(payload).__name__))
        return default_board(), warnings

    schema = payload.get("schema", 1)
    board_raw = payload.get("board", payload if "layout_id" in payload else None)
    if schema not in {1, 2, 3, 4, 5}:
        warnings.append(_warn("unknown_ultraview_schema", repr(schema)))
        return default_board(), warnings
    if not isinstance(board_raw, Mapping):
        warnings.append(_warn("unknown_ultraview_schema", "missing board"))
        return default_board(), warnings

    board = default_board()
    board_id = board_raw.get("board_id")
    if isinstance(board_id, str) and board_id.strip():
        board.board_id = board_id.strip()
    name = board_raw.get("name")
    if isinstance(name, str) and name.strip():
        board.name = name.strip()

    # Missing layout_mode is an old template project. Do not inherit the
    # current in-memory default (free-grid); that would rewrite saved boards.
    mode = board_raw.get("layout_mode", LAYOUT_MODE_TEMPLATE)
    if mode not in {LAYOUT_MODE_TEMPLATE, LAYOUT_MODE_FREE_GRID}:
        warnings.append(_warn("unknown_layout_mode", repr(mode)))
        mode = LAYOUT_MODE_TEMPLATE
    board.layout_mode = mode
    layout_id = board_raw.get("layout_id", DEFAULT_LAYOUT_ID)
    if layout_id not in LAYOUT_SLOTS:
        warnings.append(_warn("unknown_layout", repr(layout_id)))
        layout_id = DEFAULT_LAYOUT_ID
    board.layout_id = layout_id
    warnings.extend(set_ratio(board, board_raw.get("primary_ratio", DEFAULT_PRIMARY_RATIO)))
    board.show_titles = bool(board_raw.get("show_titles", True))
    board.show_sources = bool(board_raw.get("show_sources", True))
    board.passthrough = {
        key: deepcopy(value)
        for key, value in board_raw.items()
        if key not in _BOARD_PAYLOAD_KEYS | _RETIRED_BOARD_PAYLOAD_KEYS
    }

    seen_refs: set[UltraViewRef] = set()
    if board.layout_mode == LAYOUT_MODE_FREE_GRID:
        free_raw = board_raw.get("free_grid")
        if not isinstance(free_raw, Mapping):
            warnings.append(_warn("missing_free_grid"))
            free_raw = {}
        legacy_grid = schema < ULTRAVIEW_SCHEMA
        expected_columns = LEGACY_GRID_COLUMNS if legacy_grid else GRID_COLUMNS
        if free_raw.get("columns", expected_columns) != expected_columns:
            warnings.append(_warn("grid_columns_normalized"))
        default_size = free_raw.get("default_size")
        if isinstance(default_size, str) and default_size:
            board.free_grid_default_size = default_size
        for item in free_raw.get("placements") or []:
            if not isinstance(item, Mapping):
                warnings.append(_warn("illegal_grid_placement"))
                continue
            ref = parse_ref_payload(item)
            rect = (
                _legacy_grid_rect(item, warnings=warnings)
                if legacy_grid
                else _legal_grid_rect(item, warnings=warnings)
            )
            if ref is None or rect is None:
                warnings.append(_warn("illegal_grid_placement"))
                continue
            if not _take_membership(seen_refs, ref, warnings):
                continue
            if len(board.free_grid) >= MAX_PLACED_CARDS or any(
                _grid_overlaps(rect, existing.rect) for existing in board.free_grid
            ):
                _append_unplaced(board, ref)
                warnings.append(_warn("grid_to_tray", f"{ref.section}/{ref.view_id}"))
                continue
            board.free_grid.append(FreeGridPlacement(ref, rect))
        for item in board_raw.get("unplaced") or []:
            ref = parse_ref_payload(item if isinstance(item, Mapping) else None)
            if ref is None:
                warnings.append(_warn("illegal_ref"))
            elif _take_membership(seen_refs, ref, warnings):
                board.unplaced.append(ref)
        board.author_objects = _normalize_author_objects(
            board_raw.get("author_objects"),
            placed_cards=placed_ref_set(board),
            warnings=warnings,
        )
        return board, warnings

    seen_slots: set[str] = set()
    legal_slots = set(layout_slots(board.layout_id))

    for item in board_raw.get("placements") or []:
        if not isinstance(item, Mapping):
            warnings.append(_warn("illegal_placement", type(item).__name__))
            continue
        slot_id = item.get("slot_id")
        ref = parse_ref_payload(item)
        if ref is None:
            section = item.get("section")
            view_id = item.get("view_id")
            if section not in SOURCE_SECTIONS:
                warnings.append(_warn("illegal_section", repr(section)))
            elif not isinstance(view_id, str) or not str(view_id).strip():
                warnings.append(_warn("empty_view_id", repr(view_id)))
            else:
                warnings.append(_warn("illegal_ref", repr(item)))
            continue
        if slot_id not in legal_slots:
            warnings.append(_warn("unknown_slot", repr(slot_id)))
            if _take_membership(seen_refs, ref, warnings):
                _append_unplaced(board, ref)
            continue
        if slot_id in seen_slots:
            warnings.append(_warn("duplicate_slot", str(slot_id)))
            if _take_membership(seen_refs, ref, warnings):
                _append_unplaced(board, ref)
            continue
        if not _take_membership(seen_refs, ref, warnings):
            continue
        seen_slots.add(slot_id)
        board.placements.append(CardPlacement(slot_id=str(slot_id), ref=ref))

    _sort_placements(board)

    for item in board_raw.get("unplaced") or []:
        ref = parse_ref_payload(item if isinstance(item, Mapping) else None)
        if ref is None:
            if isinstance(item, Mapping):
                section = item.get("section")
                view_id = item.get("view_id")
                if section not in SOURCE_SECTIONS:
                    warnings.append(_warn("illegal_section", repr(section)))
                else:
                    warnings.append(_warn("empty_view_id", repr(view_id)))
            else:
                warnings.append(_warn("illegal_ref", type(item).__name__))
            continue
        if not _take_membership(seen_refs, ref, warnings):
            continue
        board.unplaced.append(ref)

    board.author_objects = _normalize_author_objects(
        board_raw.get("author_objects"),
        placed_cards=placed_ref_set(board),
        warnings=warnings,
    )
    return board, warnings


def workspace_to_payload(workspace: UltraViewWorkspaceState) -> dict[str, Any]:
    """Serialize the active multi-Board workspace without runtime state."""
    if workspace.opaque_payload is not None:
        return dict(workspace.opaque_payload)
    return {
        "schema": ULTRAVIEW_SCHEMA,
        "workspace": {
            "active_board_id": active_board(workspace).board_id,
            "show_card_actions": bool(workspace.show_card_actions),
            "boards": [_board_payload(board) for board in workspace.boards],
        },
        **({"preview_sidecar": dict(workspace.preview_sidecar)} if workspace.preview_sidecar else {}),
    }


def normalize_workspace_payload(
    payload: Mapping[str, Any] | None,
) -> tuple[UltraViewWorkspaceState, list[str]]:
    """Migrate schema 1–5 to one editable workspace, never dropping refs."""
    warnings: list[str] = []
    if payload is None:
        return default_workspace(), warnings
    if not isinstance(payload, Mapping):
        return default_workspace(), [_warn("unknown_ultraview_schema", type(payload).__name__)]
    schema = payload.get("schema", 1)
    if not isinstance(schema, int) or isinstance(schema, bool):
        return default_workspace(), [_warn("unknown_ultraview_schema", repr(schema))]
    if schema > ULTRAVIEW_SCHEMA:
        fallback = default_workspace()
        fallback.opaque_payload = dict(payload)
        return fallback, [_warn("future_ultraview_schema", str(schema))]
    if schema < 1:
        return default_workspace(), [_warn("unknown_ultraview_schema", repr(schema))]
    root = payload.get("workspace") if schema >= 2 else None
    if not isinstance(root, Mapping):
        # Schema 1's single board is intentionally routed through the same
        # legalizer so historical projects gain no special mutation semantics.
        board, board_warnings = normalize_board_payload({"schema": 1, "board": payload.get("board")})
        workspace = UltraViewWorkspaceState(board.board_id, [board])
        return workspace, board_warnings
    boards_raw = root.get("boards")
    if not isinstance(boards_raw, list) or not boards_raw:
        return default_workspace(), [_warn("missing_boards")]
    boards: list[UltraViewBoardState] = []
    board_ids: set[str] = set()
    for raw in boards_raw:
        board, board_warnings = normalize_board_payload({"schema": schema, "board": raw})
        warnings.extend(board_warnings)
        if board.board_id in board_ids:
            old = board.board_id
            board.board_id = str(uuid.uuid4())
            warnings.append(_warn("duplicate_board_id", old))
        board_ids.add(board.board_id)
        boards.append(board)
    if len(boards) > MAX_UI_BOARDS:
        warnings.append(_warn("ui_board_limit", str(len(boards))))
    requested = root.get("active_board_id")
    active = str(requested) if isinstance(requested, str) else ""
    if active not in board_ids:
        if active:
            warnings.append(_warn("invalid_active_board", active))
        active = boards[0].board_id
    descriptor = payload.get("preview_sidecar")
    return UltraViewWorkspaceState(
        active_board_id=active,
        boards=boards,
        show_card_actions=(
            bool(root.get("show_card_actions", False)) if schema >= 4 else False
        ),
        preview_sidecar=dict(descriptor) if isinstance(descriptor, Mapping) else None,
    ), warnings


def _canonical_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError(f"non-finite float is not digest-stable: {value!r}")
        return value
    if isinstance(value, tuple):
        return {"__tuple__": [_canonical_json_value(item) for item in value]}
    if isinstance(value, list):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, dict):
        encoded = {}
        for key in sorted(value, key=lambda item: str(item)):
            encoded[str(key)] = _canonical_json_value(value[key])
        return encoded
    raise TypeError(
        f"unserializable digest value of type {type(value).__name__}"
    )


def presentation_digest(payload: Mapping[str, Any]) -> str:
    """SHA-256 of a schema-versioned canonical JSON payload.

    Callers must pass a lightweight mapping. Large arrays are rejected.
    """
    if not isinstance(payload, Mapping):
        raise TypeError("presentation digest payload must be a mapping")
    canonical = {
        "digest_schema": DIGEST_SCHEMA,
        "payload": _canonical_json_value(dict(payload)),
    }
    blob = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def derive_preview_status(
    ref_exists: bool,
    image_valid: bool,
    captured_digest: str | None,
    current_digest: str | None,
) -> str:
    """Derive card status. A missing current digest must never be fresh."""
    if not ref_exists:
        return STATUS_ORPHANED
    if not image_valid:
        return STATUS_MISSING
    if current_digest and captured_digest and current_digest == captured_digest:
        return STATUS_FRESH
    return STATUS_STALE


def normalize_unit(unit: str | None) -> str:
    if unit is None:
        return ""
    return str(unit).strip()


def ranges_close(
    left: Sequence[float] | None, right: Sequence[float] | None
) -> bool:
    if left is None or right is None:
        return True
    if len(left) != 2 or len(right) != 2:
        return False
    for a, b in zip(left, right):
        try:
            fa = float(a)
            fb = float(b)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(fa) or not math.isfinite(fb):
            return False
        if abs(fa - fb) > RANGE_ABS_TOL + RANGE_REL_TOL * max(abs(fa), abs(fb)):
            return False
    return True


def axis_consistency_facts(records: Iterable[Mapping[str, Any]]) -> AxisConsistencyFacts:
    """Structured unit/range warnings. Never parse human title strings."""
    by_kind: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        kind = record.get("axis_kind")
        if kind not in SECTION_AXIS_KIND.values():
            continue
        by_kind.setdefault(kind, []).append(record)

    unit_inconsistent: list[str] = []
    range_inconsistent: list[str] = []
    for kind, group in by_kind.items():
        units = []
        for record in group:
            unit = normalize_unit(record.get("x_unit"))
            if unit:
                units.append(unit)
        unique_units = tuple(dict.fromkeys(units))
        if len(unique_units) > 1:
            unit_inconsistent.append(kind)
            continue
        if not unique_units:
            continue
        ranges = [
            record.get("x_range")
            for record in group
            if record.get("x_range") is not None
        ]
        finite_ranges = []
        for item in ranges:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            try:
                lo, hi = float(item[0]), float(item[1])
            except (TypeError, ValueError):
                continue
            if math.isfinite(lo) and math.isfinite(hi):
                finite_ranges.append((lo, hi))
        if len(finite_ranges) >= 2:
            first = finite_ranges[0]
            if any(not ranges_close(first, other) for other in finite_ranges[1:]):
                range_inconsistent.append(kind)
    return AxisConsistencyFacts(
        unit_inconsistent_kinds=tuple(unit_inconsistent),
        range_inconsistent_kinds=tuple(range_inconsistent),
    )


def card_matches_compare_filter(axis_kind: str | None, filter_id: str) -> bool:
    if filter_id == COMPARE_FILTER_ALL:
        return True
    return axis_kind == filter_id


def section_search_haystack(section: str, name: str, source_summary: str) -> str:
    parts = [
        section,
        SECTION_LABELS_ZH.get(section, ""),
        SECTION_LABELS_EN.get(section, ""),
        name,
        source_summary,
    ]
    return " ".join(part for part in parts if part).lower()
