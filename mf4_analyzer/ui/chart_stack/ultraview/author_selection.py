"""Typed selection capabilities, arrange math, and style cycling.

Qt-free. Page and SelectionToolbar consume ``SelectionCapabilities``; they
must not scatter kind if/else to decide which controls exist.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from mf4_analyzer.ui.ultraview_state import (
    ConnectorObject,
    ShapeObject,
    StickyObject,
    StrokeObject,
    TextObject,
    UltraViewRef,
    UnknownAuthorObject,
)

from .author_geometry import clamp_stroke_point
from .author_style import STICKY_PALETTE_TOKENS
from .author_tools import (
    AuthorKey,
    BoardItemKey,
    CLOSED_SHAPE_TYPES,
    CONNECTOR_LINE_STYLES,
    CONNECTOR_STROKE_PALETTES,
    CONNECTOR_STROKE_WIDTHS,
    CardKey,
    DRAW_INK_SUBTOOLS,
    SHAPE_CORNER_TYPES,
    SHAPE_CORNERS,
    SHAPE_FILL_PALETTES,
    SHAPE_LINE_STYLES,
    SHAPE_STROKE_PALETTES,
    SHAPE_STROKE_WIDTHS,
    STROKE_WIDTH_MAX,
    STROKE_WIDTH_MIN,
    clamp_author_box,
    is_author_key,
    is_card_key,
    SHAPE_MIN_HEIGHT,
    SHAPE_MIN_WIDTH,
    STICKY_MIN_HEIGHT,
    STICKY_MIN_WIDTH,
    TEXT_MIN_HEIGHT,
    TEXT_MIN_WIDTH,
)

INDETERMINATE = "—"
NUDGE_STEP = 1.0
NUDGE_STEP_SHIFT = 4.0
FORBIDDEN_TOOLBAR_WORDS = frozenset(
    {
        "TIME",
        "FFT",
        "SHAPE",
        "INK",
        "类型",
        "填充",
        "描边",
        "线宽",
        "线型",
        "圆角",
        "文字",
        "复制",
        "锁定",
        "打开源",
        "同步",
        "聚焦",
        "Card Fit",
    }
)
_FONT_ROLE_LABELS = {"sans": "Sans", "serif": "Serif", "mono": "Mono"}

_TEXT_FONT_ROLES = ("sans", "serif", "mono")
_TEXT_FONT_SIZES = (8, 10, 12, 14, 18, 24, 32, 48, 72)
_TEXT_ALIGNS = ("left", "center", "right")
_TEXT_LISTS = ("none", "bullet", "number")
_TEXT_COLORS = ("ink", "blue", "red", "green")
_TEXT_FILLS = (None, "yellow", "blue", "green")
_STICKY_SHAPES = ("square", "wide")
_STICKY_FONT_SIZES = ("auto", 12, 14, 18, 24)
_STROKE_WIDTHS = (2, 4, 8, 16)

ALIGNMENTS = ("left", "center", "right", "top", "middle", "bottom")
DISTRIBUTE_AXES = ("horizontal", "vertical")
Z_ORDER_DIRECTIONS = ("front", "back", "forward", "backward")

_SPINES = {
    "sticky": "NOTE",
    "text": "TEXT",
    "shape": "SHAPE",
    "connector": "LINE",
    "stroke": "INK",
    "mixed": "MIXED",
    "card_author": "MIXED",
}
_AXIS_SPINE = {
    "time": ("TIME", "time"),
    "fft": ("FFT", "fft"),
    "frequency": ("FFT", "fft"),
    "fft_time": ("TF", "fft_time"),
    "tf": ("TF", "fft_time"),
    "frf": ("FRF", "frf"),
    "order": ("ORDER", "order"),
}
SPINE_TOKEN_SELECTION = "selection"

_KIND_TYPES = {
    StickyObject: "sticky",
    TextObject: "text",
    ShapeObject: "shape",
    ConnectorObject: "connector",
    StrokeObject: "stroke",
}


@dataclass(frozen=True)
class ToolbarControl:
    """One selection-toolbar control. UI copy is tooltip-only except allowed values."""

    key: str
    label: str
    tooltip: str = ""
    mixed: bool = False
    checkable: bool = False
    checked: bool = False
    wide: bool = False
    enabled: bool = True
    icon_role: str = "icon"
    value: object = None
    visible_text: str = ""
    group: str = ""


@dataclass(frozen=True)
class SelectionCapabilities:
    """Resolved toolbar + safe actions for the current Board selection."""

    kind: str
    spine: str
    spine_token: str
    controls: tuple[ToolbarControl, ...]
    selection: tuple[BoardItemKey, ...]
    author_ids: tuple[str, ...]
    card_refs: tuple[UltraViewRef, ...]
    skipped_unknown: tuple[str, ...]
    skipped_locked: tuple[str, ...]
    can_style: bool
    can_align: bool
    can_distribute: bool
    can_duplicate: bool
    can_lock: bool
    can_delete: bool
    can_nudge: bool
    can_z_order: bool
    lock_state: bool | None = None
    homogeneous_kind: str | None = None


def item_id(item: object) -> str:
    if isinstance(item, UnknownAuthorObject):
        return str(item.raw.get("id") or "")
    return str(getattr(item, "object_id", "") or "")


def is_unknown(item: object) -> bool:
    return isinstance(item, UnknownAuthorObject)


def is_locked(item: object) -> bool:
    if isinstance(item, UnknownAuthorObject):
        return bool(item.raw.get("locked"))
    return bool(getattr(item, "locked", False))


def resolve_selection_capabilities(
    board,
    selection: Iterable[BoardItemKey],
    *,
    editor_kind: str = "",
    editor_object_id: str = "",
    axis_kinds: Mapping[object, str] | None = None,
    show_card_fit: bool = True,
) -> SelectionCapabilities:
    """Compute toolbar controls from identity keys. Display labels are ignored."""
    keys = tuple(selection)
    if editor_object_id:
        keys = (AuthorKey(editor_object_id),)
    author_ids = tuple(item.object_id for item in keys if is_author_key(item))
    card_refs = tuple(item.ref for item in keys if is_card_key(item))
    by_id = {item_id(item): item for item in getattr(board, "author_objects", ())}
    authors = [by_id[object_id] for object_id in author_ids if object_id in by_id]
    unknown_ids = tuple(item_id(item) for item in authors if is_unknown(item))
    locked_ids = tuple(
        item_id(item) for item in authors if is_locked(item) and not is_unknown(item)
    )
    known = [item for item in authors if not is_unknown(item)]
    movable = [item for item in known if not is_locked(item)]
    kinds = { _KIND_TYPES[type(item)] for item in known if type(item) in _KIND_TYPES }
    if editor_kind in _SPINES:
        kinds = {editor_kind}
    has_cards = bool(card_refs)
    has_authors = bool(author_ids)
    if not has_cards and not has_authors:
        return _empty_caps(keys)
    if has_cards and has_authors:
        kind = "card_author"
    elif has_cards:
        kind = "card"
    elif len(kinds) == 1:
        kind = next(iter(kinds))
    else:
        kind = "mixed"
    if unknown_ids and not has_cards:
        kind = "mixed"
    homogeneous = next(iter(kinds)) if len(kinds) == 1 else None
    can_style = kind in {"sticky", "text", "shape", "connector", "stroke"} and not unknown_ids
    can_align = (not has_cards) and len(movable) >= 2
    can_distribute = can_align
    can_lock = bool(known)
    can_delete = bool(movable) or has_cards
    can_duplicate = bool(movable)
    can_nudge = bool(movable) or has_cards
    can_z_order = bool(known) and not has_cards
    lock_values = {is_locked(item) for item in known}
    lock_state = None if len(lock_values) != 1 else next(iter(lock_values))
    spine, spine_token = _spine_for(kind, card_refs, axis_kinds)
    controls = _controls_for(
        kind,
        known,
        can_align=can_align,
        can_distribute=can_distribute,
        can_duplicate=can_duplicate,
        can_lock=can_lock,
        lock_state=lock_state,
        can_style=can_style,
        can_z_order=can_z_order,
        can_delete=can_delete,
        card_count=len(card_refs),
        show_card_fit=bool(show_card_fit),
    )
    return SelectionCapabilities(
        kind=kind,
        spine=spine,
        spine_token=spine_token,
        controls=tuple(controls),
        selection=keys,
        author_ids=author_ids,
        card_refs=card_refs,
        skipped_unknown=unknown_ids,
        skipped_locked=locked_ids,
        can_style=can_style,
        can_align=can_align,
        can_distribute=can_distribute,
        can_duplicate=can_duplicate,
        can_lock=can_lock,
        can_delete=can_delete,
        can_nudge=can_nudge,
        can_z_order=can_z_order,
        lock_state=lock_state,
        homogeneous_kind=homogeneous,
    )


def _empty_caps(keys: tuple[BoardItemKey, ...]) -> SelectionCapabilities:
    return SelectionCapabilities(
        kind="empty",
        spine="",
        spine_token=SPINE_TOKEN_SELECTION,
        controls=(),
        selection=keys,
        author_ids=(),
        card_refs=(),
        skipped_unknown=(),
        skipped_locked=(),
        can_style=False,
        can_align=False,
        can_distribute=False,
        can_duplicate=False,
        can_lock=False,
        can_delete=False,
        can_nudge=False,
        can_z_order=False,
    )


def _spine_for(
    kind: str,
    card_refs: Sequence[UltraViewRef],
    axis_kinds: Mapping[object, str] | None,
) -> tuple[str, str]:
    if kind == "card":
        labels: list[str | None] = []
        tokens: list[str | None] = []
        mapping = axis_kinds or {}
        for ref in card_refs:
            mapped = _AXIS_SPINE.get(str(mapping.get(ref) or ""))
            if mapped is None:
                labels.append(None)
                tokens.append(None)
            else:
                labels.append(mapped[0])
                tokens.append(mapped[1])
        unique = {label for label in labels if label is not None}
        if labels and None not in labels and len(unique) == 1:
            return labels[0] or "CARD", tokens[0] or SPINE_TOKEN_SELECTION
        return "CARD", SPINE_TOKEN_SELECTION
    if kind in _SPINES:
        return _SPINES[kind], SPINE_TOKEN_SELECTION
    return "MIXED", SPINE_TOKEN_SELECTION


def _controls_for(
    kind: str,
    items: Sequence[object],
    *,
    can_align: bool,
    can_distribute: bool,
    can_duplicate: bool,
    can_lock: bool,
    lock_state: bool | None,
    can_style: bool,
    can_z_order: bool,
    can_delete: bool,
    card_count: int = 0,
    show_card_fit: bool = True,
) -> list[ToolbarControl]:
    del can_z_order, can_delete, card_count, show_card_fit
    controls: list[ToolbarControl] = []
    if kind == "sticky" and can_style:
        controls.extend(_sticky_controls(items))
    elif kind == "text" and can_style:
        controls.extend(_text_controls(items))
    elif kind == "shape" and can_style:
        controls.extend(_shape_controls(items))
    elif kind == "connector" and can_style:
        controls.extend(_connector_controls(items))
    elif kind == "stroke" and can_style:
        controls.extend(_stroke_controls(items))
    elif kind in {"card", "card_author"}:
        pass
    if can_align:
        for key, label in (
            ("align_left", "左齐"),
            ("align_center", "水平居中"),
            ("align_right", "右齐"),
            ("align_top", "顶齐"),
            ("align_middle", "垂直居中"),
            ("align_bottom", "底齐"),
        ):
            controls.append(ToolbarControl(key, label, label, wide=True, group="arrange"))
    if can_distribute:
        controls.append(ToolbarControl("distribute_h", "水平分布", "水平分布", wide=True, group="arrange"))
        controls.append(ToolbarControl("distribute_v", "垂直分布", "垂直分布", wide=True, group="arrange"))
    if can_duplicate:
        controls.append(ToolbarControl("duplicate", "复制", "复制 · Ctrl/Cmd+D", group="object"))
    if can_lock:
        if lock_state is None:
            controls.append(
                ToolbarControl(
                    "lock",
                    "锁定",
                    "锁定",
                    mixed=True,
                    checkable=True,
                    icon_role="icon",
                    group="object",
                )
            )
        else:
            controls.append(
                ToolbarControl(
                    "lock",
                    "解锁" if lock_state else "锁定",
                    "解锁" if lock_state else "锁定",
                    checkable=True,
                    checked=bool(lock_state),
                    icon_role="icon",
                    value=bool(lock_state),
                    group="object",
                )
            )
    return controls


def _sticky_controls(items: Sequence[object]) -> list[ToolbarControl]:
    whole = "应用到整个便签"
    return [
        _value_control(items, "shape", "形状", "shape", tooltip=whole, icon_role="shape", group="style"),
        _value_control(items, "palette", "色板", "palette", tooltip=whole, icon_role="swatch", group="style"),
        _value_control(
            items, "font_size", "字号", "font_size", tooltip=whole, icon_role="value", group="type"
        ),
    ]


def _text_controls(items: Sequence[object]) -> list[ToolbarControl]:
    whole = "应用到整个文本框"
    return [
        _value_control(
            items, "font_role", "字体", "font_role", tooltip=f"字体 · {whole}", icon_role="value", group="font"
        ),
        _value_control(
            items, "font_size", "字号", "font_size", tooltip=f"字号 · {whole}", icon_role="value", group="font"
        ),
        _bool_control(items, "bold", "B", f"加粗 · {whole}", icon_role="glyph", group="format"),
        _bool_control(items, "italic", "I", f"斜体 · {whole}", icon_role="glyph", wide=True, group="format"),
        _bool_control(items, "underline", "U", f"下划线 · {whole}", icon_role="glyph", wide=True, group="format"),
        _value_control(
            items, "align", "对齐", "align", tooltip=f"对齐 · {whole}", icon_role="icon", group="para"
        ),
        _value_control(
            items,
            "list_style",
            "列表",
            "list_style",
            tooltip=f"列表 · {whole}",
            wide=True,
            icon_role="icon",
            group="para",
        ),
        _value_control(
            items,
            "text_palette",
            "文字颜色",
            "text_palette",
            tooltip=f"文字颜色 · {whole}",
            icon_role="swatch",
            group="color",
        ),
        _value_control(
            items,
            "fill_palette",
            "底色",
            "fill_palette",
            tooltip=f"底色 · {whole}",
            wide=True,
            icon_role="swatch",
            group="color",
        ),
        ToolbarControl("link", "链接", f"链接 · {whole}", wide=True, icon_role="icon", group="color"),
    ]


def _shape_controls(items: Sequence[object]) -> list[ToolbarControl]:
    controls = [
        _value_control(items, "shape", "形状", "shape", tooltip="切换形状，保留框/文字/样式", icon_role="shape", group="style"),
        _value_control(items, "fill", "填充色", "fill_palette", tooltip="填充色", icon_role="swatch", group="style"),
        _value_control(items, "stroke", "描边色", "stroke_palette", tooltip="描边色", icon_role="swatch", group="style"),
        _value_control(items, "width", "线宽", "stroke_width", tooltip="描边宽度", icon_role="line", group="style"),
        _value_control(items, "dash", "线型", "line_style", tooltip="实线或虚线", icon_role="dash", group="style"),
    ]
    if all(getattr(item, "shape", "") in SHAPE_CORNER_TYPES for item in items):
        controls.append(
            _value_control(
                items, "corner", "圆角", "corner_radius", tooltip="圆角半径", icon_role="icon", group="style"
            )
        )
    controls.append(ToolbarControl("text", "编辑形状内文字", "编辑形状内文字", wide=True, icon_role="icon", group="text"))
    return controls


def _connector_controls(items: Sequence[object]) -> list[ToolbarControl]:
    return [
        _value_control(items, "route", "路径", "route", tooltip="直线或正交折线", icon_role="icon", group="ends"),
        _value_control(items, "start_head", "起点", "start_head", tooltip="起点箭头", icon_role="icon", group="ends"),
        _value_control(items, "end_head", "终点", "end_head", tooltip="终点箭头", icon_role="icon", group="ends"),
        _value_control(items, "color", "颜色", "stroke_palette", tooltip="连接线颜色", icon_role="swatch", group="stroke"),
        _value_control(items, "width", "线宽", "stroke_width", tooltip="线宽", icon_role="line", group="stroke"),
        _value_control(items, "dash", "线型", "line_style", tooltip="实线或虚线", icon_role="dash", group="stroke"),
        ToolbarControl("label", "标签", "编辑整线文字", wide=True, icon_role="icon", group="label"),
    ]


def _stroke_controls(items: Sequence[object]) -> list[ToolbarControl]:
    return [
        _value_control(items, "tool", "笔种", "tool", tooltip="钢笔或荧光笔", icon_role="icon", group="tool"),
        _value_control(items, "color", "颜色", "palette", tooltip="笔画颜色", icon_role="swatch", group="ink"),
        _value_control(items, "width", "线宽", "width_px_100", tooltip="笔画宽度", icon_role="line", group="ink"),
    ]


def _all_have_fill(items: Sequence[object]) -> bool:
    return bool(items) and all(isinstance(item, (ShapeObject, TextObject)) for item in items)


def _all_have_stroke(items: Sequence[object]) -> bool:
    return bool(items) and all(
        isinstance(item, (ShapeObject, ConnectorObject)) for item in items
    )


def _mixed_style_control(
    items: Sequence[object], key: str, label: str, field: str
) -> ToolbarControl:
    return _value_control(items, key, label, field, tooltip=label)


def _value_control(
    items: Sequence[object],
    key: str,
    label: str,
    field: str,
    *,
    tooltip: str | None = None,
    wide: bool = False,
    icon_role: str = "icon",
    group: str = "",
) -> ToolbarControl:
    values = {getattr(item, field, None) for item in items}
    mixed = len(values) > 1
    value = next(iter(values)) if len(values) == 1 else None
    visible = ""
    if icon_role in {"value", "glyph"} and not mixed and value is not None:
        if key == "font_role":
            visible = _FONT_ROLE_LABELS.get(str(value), str(value).title())
        else:
            visible = str(value)
    return ToolbarControl(
        key,
        label,
        tooltip or label,
        mixed=mixed,
        wide=wide,
        icon_role=icon_role,
        value=value,
        visible_text=visible,
        group=group,
    )


def _bool_control(
    items: Sequence[object],
    key: str,
    label: str,
    tooltip: str,
    *,
    icon_role: str = "glyph",
    wide: bool = False,
    group: str = "",
) -> ToolbarControl:
    values = {bool(getattr(item, key, False)) for item in items}
    mixed = len(values) > 1
    checked = next(iter(values)) if len(values) == 1 else False
    return ToolbarControl(
        key,
        label,
        tooltip,
        mixed=mixed,
        checkable=True,
        checked=checked,
        wide=wide,
        icon_role=icon_role,
        value=checked,
        visible_text="" if mixed else label,
        group=group,
    )


def _cycle(options: tuple, current: object):
    if current in options:
        return options[(options.index(current) + 1) % len(options)]
    return options[0]


def _chosen(options: tuple, current: object, value: object):
    """Apply an explicit picker value. True is a no-op, not a silent cycle."""
    if value is True:
        return current if current in options else options[0]
    if value in options:
        return value
    return current if current in options else options[0]


def next_style_changes(item: object, key: str, value: object) -> dict[str, object]:
    """Return typed field changes for one object. Unknown items yield {}."""
    if isinstance(item, TextObject):
        return _next_text_format(item, key, value)
    if isinstance(item, ShapeObject):
        return _next_shape_format(item, key, value)
    if isinstance(item, ConnectorObject):
        return _next_connector_format(item, key, value)
    if isinstance(item, StickyObject):
        return _next_sticky_format(item, key, value)
    if isinstance(item, StrokeObject):
        return _next_stroke_format(item, key, value)
    return {}


def _next_text_format(item: TextObject, key: str, value: object) -> dict[str, object]:
    if key == "font_role":
        chosen = _chosen(_TEXT_FONT_ROLES, item.font_role, value)
        return {} if chosen == item.font_role and value is True else {"font_role": chosen}
    if key == "font_size":
        chosen = _chosen(_TEXT_FONT_SIZES, item.font_size, value)
        return {} if chosen == item.font_size and value is True else {"font_size": chosen}
    if key == "bold":
        return {"bold": bool(value) if isinstance(value, bool) else not item.bold}
    if key == "italic":
        return {"italic": bool(value) if isinstance(value, bool) else not item.italic}
    if key == "underline":
        return {"underline": bool(value) if isinstance(value, bool) else not item.underline}
    if key == "align":
        chosen = _chosen(_TEXT_ALIGNS, item.align, value)
        return {} if chosen == item.align and value is True else {"align": chosen}
    if key == "list_style":
        chosen = _chosen(_TEXT_LISTS, item.list_style, value)
        return {} if chosen == item.list_style and value is True else {"list_style": chosen}
    if key == "text_palette":
        chosen = _chosen(_TEXT_COLORS, item.text_palette, value)
        return {} if chosen == item.text_palette and value is True else {"text_palette": chosen}
    if key in {"fill_palette", "fill"}:
        chosen = _chosen(_TEXT_FILLS, item.fill_palette, value)
        return {} if chosen == item.fill_palette and value is True else {"fill_palette": chosen}
    if key == "link":
        if isinstance(value, str):
            return {"link": value}
        return {"link": None if item.link else "https://"}
    if key == "lock":
        return {"locked": not item.locked}
    return {}


def _next_shape_format(item: ShapeObject, key: str, value: object) -> dict[str, object]:
    if key == "shape":
        if value is True:
            return {}
        chosen = _chosen(CLOSED_SHAPE_TYPES, item.shape, value)
        return {} if chosen == item.shape and value is True else {"shape": chosen}
    if key == "fill":
        if value is True:
            return {}
        chosen = _chosen(SHAPE_FILL_PALETTES, item.fill_palette, value)
        if chosen is None:
            return {"clear_fill": True, "fill_palette": None}
        return {"fill_palette": chosen}
    if key == "stroke":
        if value is True:
            return {}
        return {"stroke_palette": _chosen(SHAPE_STROKE_PALETTES, item.stroke_palette, value)}
    if key == "width":
        if value is True:
            return {}
        return {"stroke_width": _chosen(SHAPE_STROKE_WIDTHS, item.stroke_width, value)}
    if key == "dash":
        if value is True:
            return {}
        return {"line_style": _chosen(SHAPE_LINE_STYLES, item.line_style, value)}
    if key == "corner":
        if item.shape not in SHAPE_CORNER_TYPES:
            return {}
        if value is True:
            return {}
        return {"corner_radius": _chosen(SHAPE_CORNERS, item.corner_radius, value)}
    if key == "lock":
        return {"locked": not item.locked}
    return {}


def _next_connector_format(item: ConnectorObject, key: str, value: object) -> dict[str, object]:
    if key == "route":
        if value is True:
            return {}
        chosen = _chosen(("straight", "elbow"), item.route, value)
        return {"route": chosen}
    if key == "start_head":
        if value is True:
            return {}
        return {"start_head": _chosen(("none", "arrow"), item.start_head, value)}
    if key == "end_head":
        if value is True:
            return {}
        return {"end_head": _chosen(("none", "arrow"), item.end_head, value)}
    if key == "color":
        if value is True:
            return {}
        return {"stroke_palette": _chosen(CONNECTOR_STROKE_PALETTES, item.stroke_palette, value)}
    if key == "width":
        if value is True:
            return {}
        return {"stroke_width": _chosen(CONNECTOR_STROKE_WIDTHS, item.stroke_width, value)}
    if key == "dash":
        if value is True:
            return {}
        return {"line_style": _chosen(CONNECTOR_LINE_STYLES, item.line_style, value)}
    if key == "lock":
        return {"locked": not item.locked}
    return {}


def _next_sticky_format(item: StickyObject, key: str, value: object) -> dict[str, object]:
    if key == "palette":
        if value is True:
            return {}
        return {"palette": _chosen(STICKY_PALETTE_TOKENS, item.palette, value)}
    if key == "shape":
        if value is True:
            return {}
        return {"shape": _chosen(_STICKY_SHAPES, item.shape, value)}
    if key == "font_size":
        if value is True:
            return {}
        return {"font_size": _chosen(_STICKY_FONT_SIZES, item.font_size, value)}
    if key == "lock":
        return {"locked": not item.locked}
    return {}


def _next_stroke_format(item: StrokeObject, key: str, value: object) -> dict[str, object]:
    if key == "tool":
        if value is True:
            return {}
        return {"tool": _chosen(DRAW_INK_SUBTOOLS, item.tool, value)}
    if key in {"color", "palette"}:
        if value is True:
            return {}
        return {"palette": _chosen(CONNECTOR_STROKE_PALETTES, item.palette, value)}
    if key == "width":
        if value is True:
            return {}
        widths = tuple(
            width for width in _STROKE_WIDTHS if STROKE_WIDTH_MIN <= width <= STROKE_WIDTH_MAX
        )
        return {"width_px_100": _chosen(widths, item.width_px_100, value)}
    if key == "lock":
        return {"locked": not item.locked}
    return {}


def object_bounds(item: object) -> tuple[float, float, float, float] | None:
    """Axis-aligned Board box used by align/distribute/nudge. Unknown is None."""
    box = getattr(item, "box", None)
    if box is not None:
        return (float(box.x), float(box.y), float(box.width), float(box.height))
    if isinstance(item, StrokeObject) and item.points:
        xs = [point.x for point in item.points]
        ys = [point.y for point in item.points]
        left, top = min(xs), min(ys)
        return (left, top, max(xs) - left, max(ys) - top)
    if isinstance(item, ConnectorObject):
        xs = (item.start.point.x, item.end.point.x)
        ys = (item.start.point.y, item.end.point.y)
        left, top = min(xs), min(ys)
        return (left, top, max(xs) - left, max(ys) - top)
    return None


def translate_object(item: object, dx: float, dy: float):
    """Move a known unlocked object. Callers skip unknown/locked."""
    from dataclasses import replace as dc_replace
    from mf4_analyzer.ui.ultraview_state import BoardBox, BoardPoint, ConnectorEndpoint

    if isinstance(item, (StickyObject, TextObject, ShapeObject)):
        min_w, min_h = _min_size(item)
        box = clamp_author_box(
            item.box.x + dx,
            item.box.y + dy,
            item.box.width,
            item.box.height,
            min_width=min_w,
            min_height=min_h,
            snap=False,
        )
        return dc_replace(item, box=BoardBox(*box))
    if isinstance(item, StrokeObject):
        points = []
        for point in item.points:
            parsed = clamp_stroke_point((point.x + dx, point.y + dy))
            if parsed is None:
                continue
            points.append(BoardPoint(*parsed))
        if len(points) < 2:
            return item
        return dc_replace(item, points=tuple(points))
    if isinstance(item, ConnectorObject):
        start = clamp_stroke_point((item.start.point.x + dx, item.start.point.y + dy))
        end = clamp_stroke_point((item.end.point.x + dx, item.end.point.y + dy))
        if start is None or end is None:
            return item
        return dc_replace(
            item,
            start=ConnectorEndpoint(BoardPoint(*start), item.start.target),
            end=ConnectorEndpoint(BoardPoint(*end), item.end.target),
        )
    return item


def _min_size(item: object) -> tuple[float, float]:
    if isinstance(item, TextObject):
        return TEXT_MIN_WIDTH, TEXT_MIN_HEIGHT
    if isinstance(item, ShapeObject):
        return SHAPE_MIN_WIDTH, SHAPE_MIN_HEIGHT
    return STICKY_MIN_WIDTH, STICKY_MIN_HEIGHT


def aligned_translation(
    bounds: tuple[float, float, float, float],
    frame: tuple[float, float, float, float],
    alignment: str,
) -> tuple[float, float]:
    x, y, width, height = bounds
    left, top, frame_w, frame_h = frame
    right = left + frame_w
    bottom = top + frame_h
    if alignment == "left":
        return (left - x, 0.0)
    if alignment == "center":
        return (left + frame_w / 2.0 - (x + width / 2.0), 0.0)
    if alignment == "right":
        return (right - width - x, 0.0)
    if alignment == "top":
        return (0.0, top - y)
    if alignment == "middle":
        return (0.0, top + frame_h / 2.0 - (y + height / 2.0))
    if alignment == "bottom":
        return (0.0, bottom - height - y)
    return (0.0, 0.0)


def union_bounds(
    boxes: Sequence[tuple[float, float, float, float]],
) -> tuple[float, float, float, float] | None:
    if not boxes:
        return None
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[0] + box[2] for box in boxes)
    bottom = max(box[1] + box[3] for box in boxes)
    return (left, top, right - left, bottom - top)


def distributed_translation(
    bounds: tuple[float, float, float, float],
    *,
    index: int,
    count: int,
    start: float,
    end: float,
    axis: str,
) -> tuple[float, float]:
    if count <= 1:
        return (0.0, 0.0)
    x, y, width, height = bounds
    center = start + (end - start) * (index / (count - 1))
    if axis == "horizontal":
        return (center - (x + width / 2.0), 0.0)
    return (0.0, center - (y + height / 2.0))
