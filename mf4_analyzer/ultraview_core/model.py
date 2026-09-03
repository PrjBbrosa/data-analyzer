"""Qt-free UltraView identity, Board/Workspace, author DTOs, and constants.

Wave 5 Task 5.2. This module must not import Qt, ``mf4_analyzer.ui``,
chart_stack, MainWindow, compositor, or Card Fit. Board/workspace mutators
live in ``mf4_analyzer.ultraview_core.board_ops``. Live author mutators live
in ``mf4_analyzer.ultraview_core.author_ops``. Presentation/filter/axis facts
live in ``mf4_analyzer.ultraview_core.presentation``. Payload legalization
and presentation digest live in ``mf4_analyzer.ultraview_core.serialization``.
"""
from __future__ import annotations

import math
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping

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
MAX_SHAPE_TEXT = 6_000
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


_SHAPE_KINDS = {
    "rectangle",
    "rounded_rectangle",
    "oval",
    "rhombus",
    "diamond",
    "triangle",
    "block_arrow",
}
_SHAPE_CORNERS = {0, 8, 16, 24}


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
    corner_radius: int = 0

    def __post_init__(self) -> None:
        self._validate_common("shape")
        if self.shape not in _SHAPE_KINDS:
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
        if isinstance(self.corner_radius, bool) or not isinstance(self.corner_radius, int) or self.corner_radius not in _SHAPE_CORNERS:
            raise UltraViewStateError("illegal shape corner radius")


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
    text: str = ""
    text_style: ShapeTextStyle = field(default_factory=ShapeTextStyle)

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
        _checked_string(self.text, "connector text", limit=MAX_SHAPE_TEXT)
        if not isinstance(self.text_style, ShapeTextStyle):
            raise UltraViewStateError("connector text style must be typed")


@dataclass(frozen=True)
class UnknownAuthorObject:
    """Newer author object retained exactly, without pretending to render it."""

    raw: dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.raw, dict):
            raise UltraViewStateError("unknown author object must retain a mapping")

    @property
    def object_id(self) -> str:
        return str(self.raw.get("id") or "")

    @property
    def kind(self) -> str:
        return str(self.raw.get("kind") or "unknown")

    @property
    def locked(self) -> bool:
        return bool(self.raw.get("locked"))


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
    locked_refs: frozenset[UltraViewRef] = frozenset()


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
    # Free-grid locks are persisted user intent.  They are carried by
    # placement snapshots so undo/redo cannot detach a lock from its card.
    locked_refs: set[UltraViewRef] = field(default_factory=set)
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


def make_ref(section: str, view_id: str) -> UltraViewRef:
    return UltraViewRef(section=str(section), view_id=str(view_id))


def parse_ref_payload(payload: Mapping[str, Any] | None) -> UltraViewRef | None:
    if not isinstance(payload, Mapping):
        return None
    try:
        return make_ref(payload.get("section", ""), payload.get("view_id", ""))
    except (TypeError, UltraViewStateError):
        return None


@dataclass(frozen=True)
class FreeGridRectPlan:
    """Dry-run of ``set_free_grid_rects``. Never writes the live Board."""

    proposed: tuple[tuple[UltraViewRef, GridRect], ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return not self.warnings
