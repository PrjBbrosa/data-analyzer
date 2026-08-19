"""Qt-free author create/update/delete. Returns patch + named warning."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Iterable

from mf4_analyzer.ui.ultraview_state import (
    MAX_AUTHOR_POINTS,
    MAX_SHAPE_TEXT,
    MAX_STROKE_POINTS,
    MAX_TEXT_TEXT,
    SAFETY_COLUMN_MAX,
    SAFETY_COLUMN_MIN,
    SAFETY_ROW_MAX,
    SAFETY_ROW_MIN,
    AnchorTarget,
    AuthorMutationResult,
    BoardBox,
    BoardPoint,
    ConnectorEndpoint,
    ConnectorObject,
    ObjectPatch,
    ShapeObject,
    ShapeTextStyle,
    StickyObject,
    StrokeObject,
    TextObject,
    UltraViewRef,
    UltraViewStateError,
    UnknownAuthorObject,
    apply_author_patches,
    author_object_to_payload,
    create_author_object,
    delete_author_objects,
    update_author_object,
    _author_object_from_payload,
)

from .author_geometry import box_anchor_point, clamp_stroke_point, simplify_stroke
from .author_style import normalize_font_role, normalize_ink_palette
from .author_selection import (
    ALIGNMENTS,
    DISTRIBUTE_AXES,
    Z_ORDER_DIRECTIONS,
    aligned_translation,
    distributed_translation,
    is_locked,
    is_unknown,
    item_id,
    next_style_changes,
    object_bounds,
    translate_object,
    union_bounds,
)
from .author_tools import (
    CONNECTOR_HEADS,
    CONNECTOR_LINE_STYLES,
    CONNECTOR_STROKE_WIDTHS,
    AuthorAlignIntent,
    AuthorBatchStyleIntent,
    AuthorClipboardPayload,
    AuthorCreateIntent,
    AuthorDeleteIntent,
    AuthorDistributeIntent,
    AuthorDuplicateIntent,
    AuthorLockIntent,
    AuthorNudgeIntent,
    AuthorPasteIntent,
    AuthorUpdateIntent,
    AuthorZOrderIntent,
    ConnectorCreateIntent,
    ConnectorUpdateIntent,
    DRAW_INK_SUBTOOLS,
    SelectionDeleteIntent,
    SelectionNudgeIntent,
    SHAPE_CORNERS,
    SHAPE_LINE_STYLES,
    SHAPE_STROKE_WIDTHS,
    STROKE_WIDTH_MAX,
    STROKE_WIDTH_MIN,
    ShapeCreateIntent,
    ShapeUpdateIntent,
    StrokeCreateIntent,
    StrokeUpdateIntent,
    TextCreateIntent,
    TextUpdateIntent,
    connector_style_from_type,
    default_shape_corner,
    new_author_object_id,
    normalize_closed_shape,
    normalize_connector_type,
)

_WARNING_COPY = {
    "invalid_text_link": "链接仅支持 http/https",
    "text_too_long": "文字已达 6000 字上限",
    "illegal_author_object": "作者对象无效，未写入",
    "illegal_author_box": "文字框尺寸无效，未写入",
    "unsupported_author_kind": "该作者工具尚未接入",
    "author_object_missing": "找不到要修改的对象",
    "unknown_author_object": "未知作者对象未修改",
    "connector_target_lost": "连接目标已移除，端点已固定",
    "stroke_too_short": "笔画太短，未写入",
    "stroke_board_point_limit": "全板笔画点数已达 60000 上限",
    "stroke_truncated": "笔画已截断至剩余点数上限",
    "stroke_sample_limit": "笔画点数已达上限，已结束当前笔画",
}


def warning_copy(code: str) -> str:
    """Return user-visible copy for a named mutation warning."""
    return _WARNING_COPY.get(str(code), str(code))


def apply_author_create(board, intent) -> AuthorMutationResult:
    """Build one typed object and apply it. Programming errors propagate."""
    if isinstance(intent, TextCreateIntent):
        return _create_text(board, intent)
    if isinstance(intent, ShapeCreateIntent):
        return _create_shape(board, intent)
    if isinstance(intent, ConnectorCreateIntent):
        return _create_connector(board, intent)
    if isinstance(intent, StrokeCreateIntent):
        return _create_stroke(board, intent)
    if isinstance(intent, AuthorCreateIntent):
        if intent.kind == "sticky":
            return _create_sticky(board, intent)
        return _warning("unsupported_author_kind")
    raise TypeError(f"unsupported create intent {type(intent).__name__}")


def apply_author_update(board, intent) -> AuthorMutationResult:
    """Patch one persisted object. Illegal user input is a named warning."""
    if isinstance(intent, TextUpdateIntent):
        return _with_connector_resolve(board, _update_text(board, intent), intent.object_id)
    if isinstance(intent, ShapeUpdateIntent):
        return _with_connector_resolve(board, _update_shape(board, intent), intent.object_id)
    if isinstance(intent, ConnectorUpdateIntent):
        return _update_connector(board, intent)
    if isinstance(intent, StrokeUpdateIntent):
        return _update_stroke(board, intent)
    if isinstance(intent, AuthorUpdateIntent):
        return _with_connector_resolve(board, _update_sticky(board, intent), intent.object_id)
    raise TypeError(f"unsupported update intent {type(intent).__name__}")


def apply_author_delete(board, intent, *, lost_card_refs=()) -> AuthorMutationResult:
    if not isinstance(intent, AuthorDeleteIntent):
        raise TypeError(f"unsupported delete intent {type(intent).__name__}")
    wanted = tuple(str(object_id) for object_id in intent.object_ids)
    if not any(item_id(item) in wanted for item in board.author_objects):
        return delete_author_objects(board, intent.object_ids)
    replacements, warnings = _planned_connector_replacements(
        board,
        lost_author_ids=set(wanted),
        lost_card_refs=set(lost_card_refs or ()),
    )
    replacements = {
        object_id: item
        for object_id, item in replacements.items()
        if object_id not in wanted
    }
    return _apply_replacements_and_deletes(
        board,
        replacements=replacements,
        delete_ids=wanted,
        extra_warnings=warnings,
    )


def normalize_text_link(link: object) -> tuple[str | None, str | None]:
    """Return ``(link, warning)``. Only ``http/https`` URLs are accepted."""
    if link is None:
        return None, None
    text = str(link).strip()
    if not text:
        return None, None
    lowered = text.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return text, None
    return None, "invalid_text_link"


def _create_sticky(board, intent: AuthorCreateIntent) -> AuthorMutationResult:
    box = _checked_box(intent.box)
    if box is None:
        return _warning("illegal_author_box")
    try:
        item = StickyObject(
            str(intent.object_id),
            "sticky",
            box=BoardBox(*box),
            text=str(intent.text or ""),
            palette=str(intent.palette or "yellow"),
        )
    except UltraViewStateError:
        return _warning("illegal_author_object")
    return create_author_object(board, item)


def _create_text(board, intent: TextCreateIntent) -> AuthorMutationResult:
    box = _checked_box(intent.box)
    if box is None:
        return _warning("illegal_author_box")
    text = str(intent.text or "")
    if len(text) > MAX_TEXT_TEXT:
        return _warning("text_too_long")
    link, link_warning = normalize_text_link(intent.link)
    if link_warning:
        return _warning(link_warning)
    try:
        item = TextObject(
            str(intent.object_id),
            "text",
            box=BoardBox(*box),
            text=text,
            font_role=normalize_font_role(intent.font_role),
            font_size=_clamp_font_size(intent.font_size),
            bold=bool(intent.bold),
            italic=bool(intent.italic),
            underline=bool(intent.underline),
            align=_normalize_align(intent.align),
            list_style=_normalize_list(intent.list_style),
            text_palette=str(intent.text_palette or "ink"),
            fill_palette=intent.fill_palette,
            opacity=_clamp_opacity(intent.opacity),
            link=link,
        )
    except UltraViewStateError:
        return _warning("illegal_author_object")
    return create_author_object(board, item)


def _update_sticky(board, intent: AuthorUpdateIntent) -> AuthorMutationResult:
    current = _find(board, intent.object_id)
    if not isinstance(current, StickyObject):
        return _warning("author_object_missing")
    box = current.box
    if intent.box is not None:
        checked = _checked_box(intent.box)
        if checked is None:
            return _warning("illegal_author_box")
        box = BoardBox(*checked)
    try:
        item = replace(
            current,
            box=box,
            text=current.text if intent.text is None else str(intent.text),
            palette=current.palette if intent.palette is None else str(intent.palette),
            locked=current.locked if intent.locked is None else bool(intent.locked),
            font_size=current.font_size if intent.font_size is None else intent.font_size,
            shape=current.shape if intent.shape is None else str(intent.shape),
        )
    except UltraViewStateError:
        return _warning("illegal_author_object")
    return update_author_object(board, intent.object_id, item)


def _update_text(board, intent: TextUpdateIntent) -> AuthorMutationResult:
    current = _find(board, intent.object_id)
    if not isinstance(current, TextObject):
        return _warning("author_object_missing")
    box = current.box
    if intent.box is not None:
        checked = _checked_box(intent.box)
        if checked is None:
            return _warning("illegal_author_box")
        box = BoardBox(*checked)
    text = current.text if intent.text is None else str(intent.text)
    if len(text) > MAX_TEXT_TEXT:
        return _warning("text_too_long")
    link = current.link
    if intent.clear_link:
        link = None
    elif intent.link is not None:
        link, link_warning = normalize_text_link(intent.link)
        if link_warning:
            return _warning(link_warning)
    try:
        item = replace(
            current,
            box=box,
            text=text,
            font_role=current.font_role
            if intent.font_role is None
            else normalize_font_role(intent.font_role),
            font_size=current.font_size
            if intent.font_size is None
            else _clamp_font_size(intent.font_size),
            bold=current.bold if intent.bold is None else bool(intent.bold),
            italic=current.italic if intent.italic is None else bool(intent.italic),
            underline=current.underline if intent.underline is None else bool(intent.underline),
            align=current.align if intent.align is None else _normalize_align(intent.align),
            list_style=current.list_style
            if intent.list_style is None
            else _normalize_list(intent.list_style),
            text_palette=current.text_palette
            if intent.text_palette is None
            else str(intent.text_palette),
            fill_palette=current.fill_palette
            if intent.fill_palette is None
            else intent.fill_palette,
            opacity=current.opacity
            if intent.opacity is None
            else _clamp_opacity(intent.opacity),
            link=link,
            locked=current.locked if intent.locked is None else bool(intent.locked),
        )
    except UltraViewStateError:
        return _warning("illegal_author_object")
    return update_author_object(board, intent.object_id, item)


def _create_shape(board, intent: ShapeCreateIntent) -> AuthorMutationResult:
    box = _checked_box(intent.box)
    if box is None:
        return _warning("illegal_author_box")
    shape = normalize_closed_shape(intent.shape)
    if shape is None:
        return _warning("unsupported_author_kind")
    text = str(intent.text or "")
    if len(text) > MAX_SHAPE_TEXT:
        return _warning("text_too_long")
    try:
        item = ShapeObject(
            str(intent.object_id),
            "shape",
            locked=bool(intent.locked),
            box=BoardBox(*box),
            shape=shape,
            text=text,
            fill_palette=intent.fill_palette,
            stroke_palette=normalize_ink_palette(intent.stroke_palette),
            stroke_width=_clamp_shape_width(intent.stroke_width),
            line_style=_normalize_line_style(intent.line_style),
            corner_radius=_normalize_corner(
                intent.corner_radius, default=default_shape_corner(shape)
            ),
        )
    except UltraViewStateError:
        return _warning("illegal_author_object")
    return create_author_object(board, item)


def _update_shape(board, intent: ShapeUpdateIntent) -> AuthorMutationResult:
    current = _find(board, intent.object_id)
    if not isinstance(current, ShapeObject):
        return _warning("author_object_missing")
    box = current.box
    if intent.box is not None:
        checked = _checked_box(intent.box)
        if checked is None:
            return _warning("illegal_author_box")
        box = BoardBox(*checked)
    text = current.text if intent.text is None else str(intent.text)
    if len(text) > MAX_SHAPE_TEXT:
        return _warning("text_too_long")
    shape = current.shape
    if intent.shape is not None:
        next_shape = normalize_closed_shape(intent.shape)
        if next_shape is None:
            return _warning("unsupported_author_kind")
        shape = next_shape
    fill_palette = current.fill_palette
    if intent.clear_fill:
        fill_palette = None
    elif intent.fill_palette is not None:
        fill_palette = None if intent.fill_palette is False else intent.fill_palette
        if fill_palette == "transparent":
            fill_palette = None
    try:
        item = replace(
            current,
            box=box,
            shape=shape,
            text=text,
            fill_palette=fill_palette,
            stroke_palette=current.stroke_palette
            if intent.stroke_palette is None
            else normalize_ink_palette(intent.stroke_palette),
            stroke_width=current.stroke_width
            if intent.stroke_width is None
            else _clamp_shape_width(intent.stroke_width),
            line_style=current.line_style
            if intent.line_style is None
            else _normalize_line_style(intent.line_style),
            corner_radius=current.corner_radius
            if intent.corner_radius is None
            else _normalize_corner(intent.corner_radius, default=current.corner_radius),
            locked=current.locked if intent.locked is None else bool(intent.locked),
            text_style=current.text_style
            if isinstance(current.text_style, ShapeTextStyle)
            else ShapeTextStyle(),
        )
    except UltraViewStateError:
        return _warning("illegal_author_object")
    return update_author_object(board, intent.object_id, item)


def _find(board, object_id: str):
    wanted = str(object_id or "")
    for item in board.author_objects:
        if item_id(item) == wanted:
            return item
    return None


def _checked_box(box: object) -> tuple[float, float, float, float] | None:
    if not isinstance(box, tuple) or len(box) != 4:
        return None
    try:
        return (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
    except (TypeError, ValueError):
        return None


def _clamp_font_size(value: object) -> int:
    try:
        size = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 14
    return min(72, max(8, size))


def _clamp_opacity(value: object) -> int:
    try:
        opacity = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 100
    return min(100, max(0, opacity))


def _normalize_align(value: object) -> str:
    checked = str(value or "left")
    return checked if checked in {"left", "center", "right"} else "left"


def _normalize_list(value: object) -> str:
    checked = str(value or "none")
    return checked if checked in {"none", "bullet", "number"} else "none"


def _clamp_shape_width(value: object) -> int:
    try:
        width = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1
    if width in SHAPE_STROKE_WIDTHS:
        return width
    return min(8, max(1, width))


def _normalize_line_style(value: object) -> str:
    checked = str(value or "solid")
    return checked if checked in SHAPE_LINE_STYLES else "solid"


def _normalize_corner(value: object, *, default: int) -> int:
    if value is None:
        return default if default in SHAPE_CORNERS else 0
    try:
        corner = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default if default in SHAPE_CORNERS else 0
    return corner if corner in SHAPE_CORNERS else default if default in SHAPE_CORNERS else 0


def _warning(code: str) -> AuthorMutationResult:
    return AuthorMutationResult((), (code,))


def _create_connector(board, intent: ConnectorCreateIntent) -> AuthorMutationResult:
    kind = normalize_connector_type(intent.connector_type)
    if kind is None:
        return _warning("unsupported_author_kind")
    text = str(intent.text or "")
    if len(text) > MAX_SHAPE_TEXT:
        return _warning("text_too_long")
    start = _checked_point(intent.start)
    end = _checked_point(intent.end)
    if start is None or end is None:
        return _warning("illegal_author_object")
    style = connector_style_from_type(kind)
    route = intent.route or style["route"]
    if route not in {"straight", "elbow"}:
        return _warning("unsupported_author_kind")
    start_target = _checked_target(intent.start_target)
    end_target = _checked_target(intent.end_target)
    try:
        item = ConnectorObject(
            str(intent.object_id),
            "connector",
            locked=bool(intent.locked),
            start=ConnectorEndpoint(BoardPoint(*start), start_target),
            end=ConnectorEndpoint(BoardPoint(*end), end_target),
            route=route,
            elbow_bias=intent.elbow_bias,
            line_style=_normalize_connector_line(intent.line_style),
            stroke_palette=normalize_ink_palette(intent.stroke_palette),
            stroke_width=_clamp_shape_width(intent.stroke_width),
            start_head=_normalize_head(intent.start_head, style["start_head"]),
            end_head=_normalize_head(intent.end_head, style["end_head"]),
            text=text,
        )
    except UltraViewStateError:
        return _warning("illegal_author_object")
    resolved = _resolved_connector(board, item)
    return create_author_object(board, resolved)


def _create_stroke(board, intent: StrokeCreateIntent) -> AuthorMutationResult:
    tool = str(intent.tool or "")
    if tool not in DRAW_INK_SUBTOOLS:
        return _warning("illegal_author_object")
    points = _normalized_stroke_points(intent.points)
    if len(points) < 2:
        return _warning("stroke_too_short")
    warnings: list[str] = []
    if len(points) > MAX_STROKE_POINTS:
        points = simplify_stroke(points, tolerance=0.0, max_points=MAX_STROKE_POINTS)
        warnings.append("stroke_truncated")
    remaining = MAX_AUTHOR_POINTS - _board_stroke_point_count(board)
    if remaining < 2:
        return _warning("stroke_board_point_limit")
    if len(points) > remaining:
        points = simplify_stroke(points, tolerance=0.0, max_points=remaining)
        warnings.append("stroke_truncated")
        if len(points) < 2:
            return _warning("stroke_board_point_limit")
    try:
        item = StrokeObject(
            str(intent.object_id),
            "stroke",
            locked=bool(intent.locked),
            points=tuple(BoardPoint(x, y) for x, y in points),
            tool=tool,
            palette=normalize_ink_palette(intent.palette),
            width_px_100=_clamp_stroke_width(intent.width_px_100),
        )
    except UltraViewStateError:
        return _warning("illegal_author_object")
    result = create_author_object(board, item)
    if not result.changed:
        code = result.warnings[0] if result.warnings else "stroke_board_point_limit"
        if code == "author_object_limit":
            return _warning("stroke_board_point_limit")
        return result
    if warnings:
        return AuthorMutationResult(result.patches, result.warnings + tuple(warnings))
    return result


def _normalized_stroke_points(points: object) -> tuple[tuple[float, float], ...]:
    if not isinstance(points, (list, tuple)):
        return ()
    cleaned: list[tuple[float, float]] = []
    for point in points:
        parsed = clamp_stroke_point(point if not hasattr(point, "x") else (point.x, point.y))
        if parsed is None:
            continue
        if not cleaned or parsed != cleaned[-1]:
            cleaned.append(parsed)
    return tuple(cleaned)


def _board_stroke_point_count(board) -> int:
    total = 0
    for item in getattr(board, "author_objects", ()):
        if isinstance(item, StrokeObject):
            total += len(item.points)
    return total


def _clamp_stroke_width(value: object) -> int:
    try:
        width = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 2
    return min(STROKE_WIDTH_MAX, max(STROKE_WIDTH_MIN, width))


def _update_connector(board, intent: ConnectorUpdateIntent) -> AuthorMutationResult:
    current = _find(board, intent.object_id)
    if not isinstance(current, ConnectorObject):
        return _warning("author_object_missing")
    text = current.text if intent.text is None else str(intent.text)
    if len(text) > MAX_SHAPE_TEXT:
        return _warning("text_too_long")
    start_point = current.start.point
    if intent.start is not None:
        checked = _checked_point(intent.start)
        if checked is None:
            return _warning("illegal_author_object")
        start_point = BoardPoint(*checked)
    end_point = current.end.point
    if intent.end is not None:
        checked = _checked_point(intent.end)
        if checked is None:
            return _warning("illegal_author_object")
        end_point = BoardPoint(*checked)
    start_target = current.start.target
    if intent.clear_start_target:
        start_target = None
    elif intent.start_target is not None:
        start_target = _checked_target(intent.start_target)
    end_target = current.end.target
    if intent.clear_end_target:
        end_target = None
    elif intent.end_target is not None:
        end_target = _checked_target(intent.end_target)
    style = current.text_style if isinstance(current.text_style, ShapeTextStyle) else ShapeTextStyle()
    try:
        item = replace(
            current,
            start=ConnectorEndpoint(start_point, start_target),
            end=ConnectorEndpoint(end_point, end_target),
            route=current.route if intent.route is None else str(intent.route),
            elbow_bias=current.elbow_bias if intent.elbow_bias is None else intent.elbow_bias,
            line_style=current.line_style
            if intent.line_style is None
            else _normalize_connector_line(intent.line_style),
            stroke_palette=current.stroke_palette
            if intent.stroke_palette is None
            else normalize_ink_palette(intent.stroke_palette),
            stroke_width=current.stroke_width
            if intent.stroke_width is None
            else _clamp_shape_width(intent.stroke_width),
            start_head=current.start_head
            if intent.start_head is None
            else _normalize_head(intent.start_head, current.start_head),
            end_head=current.end_head
            if intent.end_head is None
            else _normalize_head(intent.end_head, current.end_head),
            text=text,
            locked=current.locked if intent.locked is None else bool(intent.locked),
            text_style=ShapeTextStyle(
                font_size=style.font_size if intent.font_size is None else _clamp_font_size(intent.font_size),
                bold=style.bold,
                italic=style.italic,
                underline=style.underline,
                align=style.align if intent.align is None else _normalize_align(intent.align),
                text_palette=style.text_palette
                if intent.text_palette is None
                else str(intent.text_palette),
            ),
        )
    except UltraViewStateError:
        return _warning("illegal_author_object")
    return update_author_object(board, intent.object_id, _resolved_connector(board, item))


def re_resolve_connector_endpoints(
    board,
    *,
    lost_card_refs: Iterable[UltraViewRef] | None = None,
    lost_author_ids: Iterable[str] | None = None,
    apply: bool = True,
) -> AuthorMutationResult:
    """Re-resolve or freeze connector endpoints. One warning per newly detached line."""
    replacements, warnings = _planned_connector_replacements(
        board,
        lost_card_refs=set(lost_card_refs or ()),
        lost_author_ids={str(item) for item in (lost_author_ids or ())},
    )
    if not apply:
        return AuthorMutationResult((), tuple(warnings)) if not replacements else AuthorMutationResult(
            _patches_for_replacements(board, replacements), tuple(warnings)
        )
    if not replacements:
        return AuthorMutationResult((), tuple(warnings))
    return _apply_replacements_and_deletes(
        board, replacements=replacements, delete_ids=(), extra_warnings=warnings
    )


def _with_connector_resolve(board, mutation: AuthorMutationResult, object_id: str) -> AuthorMutationResult:
    extra = re_resolve_connector_endpoints(board)
    if not extra.changed:
        return mutation
    return AuthorMutationResult(mutation.patches + extra.patches, mutation.warnings + extra.warnings)


def _planned_connector_replacements(
    board,
    *,
    lost_card_refs: set | None = None,
    lost_author_ids: set | None = None,
) -> tuple[dict[str, ConnectorObject], tuple[str, ...]]:
    lost_cards = set(lost_card_refs or ())
    lost_authors = {str(item) for item in (lost_author_ids or ())}
    replacements: dict[str, ConnectorObject] = {}
    warnings: list[str] = []
    for item in board.author_objects:
        if not isinstance(item, ConnectorObject) or item.object_id in lost_authors:
            continue
        resolved, lost = _resolve_connector_pair(
            board, item, lost_cards=lost_cards, lost_authors=lost_authors
        )
        if lost:
            warnings.append("connector_target_lost")
        if resolved != item:
            replacements[item.object_id] = resolved
    return replacements, tuple(warnings)


def _resolve_connector_pair(
    board,
    item: ConnectorObject,
    *,
    lost_cards: set,
    lost_authors: set,
) -> tuple[ConnectorObject, bool]:
    start, start_lost = _resolve_endpoint(
        board, item.start, item.end.point, lost_cards=lost_cards, lost_authors=lost_authors
    )
    end, end_lost = _resolve_endpoint(
        board, item.end, start.point, lost_cards=lost_cards, lost_authors=lost_authors
    )
    if start == item.start and end == item.end:
        return item, False
    return replace(item, start=start, end=end), bool(start_lost or end_lost)


def _resolved_connector(board, item: ConnectorObject) -> ConnectorObject:
    resolved, _lost = _resolve_connector_pair(
        board, item, lost_cards=set(), lost_authors=set()
    )
    return resolved


def _resolve_endpoint(
    board,
    endpoint: ConnectorEndpoint,
    other: BoardPoint,
    *,
    lost_cards: set,
    lost_authors: set,
) -> tuple[ConnectorEndpoint, bool]:
    target = endpoint.target
    if target is None:
        return endpoint, False
    if _target_is_lost(target, lost_cards=lost_cards, lost_authors=lost_authors):
        return ConnectorEndpoint(endpoint.point, None), True
    box = _target_box(board, target)
    if box is None:
        return endpoint, False
    point = box_anchor_point(box, target.anchor, (other.x, other.y))
    if point is None:
        return endpoint, False
    resolved = ConnectorEndpoint(BoardPoint(*point), target)
    return resolved, False


def _target_is_lost(target: AnchorTarget, *, lost_cards: set, lost_authors: set) -> bool:
    if target.kind == "author":
        return str(target.object_id) in lost_authors
    return target.card in lost_cards


def _target_box(board, target: AnchorTarget) -> tuple[float, float, float, float] | None:
    if target.kind == "author":
        item = _find(board, str(target.object_id or ""))
        box = getattr(item, "box", None)
        if box is None:
            return None
        return (float(box.x), float(box.y), float(box.width), float(box.height))
    for placement in getattr(board, "free_grid", ()):
        if placement.ref == target.card:
            rect = placement.rect
            return (
                float(rect.column),
                float(rect.row),
                float(rect.column_span),
                float(rect.row_span),
            )
    return None


def _apply_replacements_and_deletes(
    board,
    *,
    replacements: dict[str, object],
    delete_ids: Iterable[str],
    extra_warnings: tuple[str, ...] = (),
) -> AuthorMutationResult:
    delete_set = {str(object_id) for object_id in delete_ids}
    final: list[object] = []
    for item in board.author_objects:
        object_id = str(getattr(item, "object_id", "") or "")
        if object_id in delete_set:
            continue
        final.append(replacements.get(object_id, item))
    if final == list(board.author_objects):
        return AuthorMutationResult((), extra_warnings)
    patches = _diff_author_objects(board.author_objects, final, delete_set)
    if not patches:
        return AuthorMutationResult((), extra_warnings)
    if not apply_author_patches(board, patches, forward=True):
        return AuthorMutationResult((), extra_warnings + ("illegal_author_object",))
    return AuthorMutationResult(patches, extra_warnings)


def _diff_author_objects(original, final, delete_set: set[str]) -> tuple[ObjectPatch, ...]:
    original_index = {
        str(getattr(item, "object_id", "") or ""): index
        for index, item in enumerate(original)
    }
    final_index = {
        str(getattr(item, "object_id", "") or ""): index
        for index, item in enumerate(final)
    }
    patches: list[ObjectPatch] = []
    for item in original:
        object_id = str(getattr(item, "object_id", "") or "")
        before = author_object_to_payload(item)
        if object_id in delete_set:
            patches.append(ObjectPatch(object_id, before, None, original_index[object_id], None))
            continue
        after_item = final[final_index[object_id]]
        after = author_object_to_payload(after_item)
        if after == before:
            continue
        patches.append(
            ObjectPatch(
                object_id,
                before,
                after,
                original_index[object_id],
                final_index[object_id],
            )
        )
    return tuple(patches)


def _patches_for_replacements(board, replacements: dict[str, object]) -> tuple[ObjectPatch, ...]:
    return _diff_author_objects(board.author_objects, [
        replacements.get(str(getattr(item, "object_id", "") or ""), item)
        for item in board.author_objects
    ], set())


def _checked_point(value: object) -> tuple[float, float] | None:
    if not isinstance(value, tuple) or len(value) != 2:
        return None
    try:
        x = float(value[0])
        y = float(value[1])
    except (TypeError, ValueError):
        return None
    x = min(max(x, float(SAFETY_COLUMN_MIN)), float(SAFETY_COLUMN_MAX) - 0.25)
    y = min(max(y, float(SAFETY_ROW_MIN)), float(SAFETY_ROW_MAX) - 0.25)
    return (x, y)


def _checked_target(value: object) -> AnchorTarget | None:
    if value is None:
        return None
    if isinstance(value, AnchorTarget):
        return value
    return None


def _normalize_connector_line(value: object) -> str:
    checked = str(value or "solid")
    return checked if checked in CONNECTOR_LINE_STYLES else "solid"


def _normalize_head(value: object, default: str) -> str:
    checked = default if value is None else str(value)
    return checked if checked in CONNECTOR_HEADS else default


def _update_stroke(board, intent: StrokeUpdateIntent) -> AuthorMutationResult:
    current = _find(board, intent.object_id)
    if not isinstance(current, StrokeObject):
        return _warning("author_object_missing")
    points = current.points
    if intent.points is not None:
        parsed = _normalized_stroke_points(intent.points)
        if len(parsed) < 2:
            return _warning("stroke_too_short")
        points = tuple(BoardPoint(x, y) for x, y in parsed)
    try:
        item = replace(
            current,
            points=points,
            tool=current.tool if intent.tool is None else str(intent.tool),
            palette=current.palette
            if intent.palette is None
            else normalize_ink_palette(intent.palette),
            width_px_100=current.width_px_100
            if intent.width_px_100 is None
            else _clamp_stroke_width(intent.width_px_100),
            locked=current.locked if intent.locked is None else bool(intent.locked),
        )
    except UltraViewStateError:
        return _warning("illegal_author_object")
    return update_author_object(board, intent.object_id, item)


def apply_author_intent(board, intent) -> AuthorMutationResult:
    """Dispatch any typed author intent through one mutation helper."""
    if isinstance(intent, AuthorBatchStyleIntent):
        return apply_author_batch_style(board, intent.object_ids, intent.key, intent.value)
    if isinstance(intent, AuthorAlignIntent):
        return apply_author_align(board, intent.object_ids, intent.alignment)
    if isinstance(intent, AuthorDistributeIntent):
        return apply_author_distribute(board, intent.object_ids, intent.axis)
    if isinstance(intent, AuthorDuplicateIntent):
        return apply_author_duplicate(board, intent.object_ids)
    if isinstance(intent, AuthorLockIntent):
        return apply_author_lock(board, intent.object_ids, locked=intent.locked)
    if isinstance(intent, AuthorZOrderIntent):
        return apply_author_z_order(board, intent.object_ids, intent.direction)
    if isinstance(intent, AuthorNudgeIntent):
        return apply_author_nudge(board, intent.object_ids, intent.dx, intent.dy)
    if isinstance(intent, AuthorPasteIntent):
        return paste_author_objects(board, intent.payload, dx=intent.dx, dy=intent.dy)
    if isinstance(intent, SelectionNudgeIntent):
        return apply_author_nudge(board, intent.author_ids, intent.dx, intent.dy)
    if isinstance(intent, SelectionDeleteIntent):
        return apply_author_delete(board, AuthorDeleteIntent(intent.author_ids))
    if isinstance(
        intent,
        (AuthorCreateIntent, TextCreateIntent, ShapeCreateIntent, ConnectorCreateIntent, StrokeCreateIntent),
    ):
        return apply_author_create(board, intent)
    if isinstance(intent, AuthorDeleteIntent):
        return apply_author_delete(board, intent)
    return apply_author_update(board, intent)


def apply_author_batch_style(board, object_ids: Iterable[str], key: str, value: object) -> AuthorMutationResult:
    wanted = tuple(str(object_id) for object_id in object_ids)
    reference = None
    for object_id in wanted:
        item = _find(board, object_id)
        if item is None or is_unknown(item) or is_locked(item):
            continue
        reference = item
        break
    if reference is None:
        return AuthorMutationResult()
    canonical = next_style_changes(reference, key, value)
    if not canonical:
        return AuthorMutationResult()
    staged = list(board.author_objects)
    for index, item in enumerate(staged):
        if item_id(item) not in wanted or is_unknown(item) or is_locked(item):
            continue
        staged[index] = _apply_style_fields(item, canonical)
    return _commit_staged(board, staged)


def apply_author_align(board, object_ids: Iterable[str], alignment: str) -> AuthorMutationResult:
    if alignment not in ALIGNMENTS:
        return _warning("illegal_author_object")
    wanted = {str(object_id) for object_id in object_ids}
    movable = [
        item
        for item in board.author_objects
        if item_id(item) in wanted and not is_unknown(item) and not is_locked(item)
    ]
    boxes = [object_bounds(item) for item in movable]
    boxes = [box for box in boxes if box is not None]
    frame = union_bounds(boxes)
    if frame is None or len(movable) < 2:
        return AuthorMutationResult()
    staged = list(board.author_objects)
    for index, item in enumerate(staged):
        if item_id(item) not in wanted or is_unknown(item) or is_locked(item):
            continue
        bounds = object_bounds(item)
        if bounds is None:
            continue
        dx, dy = aligned_translation(bounds, frame, alignment)
        if dx == 0.0 and dy == 0.0:
            continue
        staged[index] = translate_object(item, dx, dy)
    staged = _resolve_staged_connectors(board, staged)
    return _commit_staged(board, staged)


def apply_author_distribute(board, object_ids: Iterable[str], axis: str) -> AuthorMutationResult:
    if axis not in DISTRIBUTE_AXES:
        return _warning("illegal_author_object")
    wanted = {str(object_id) for object_id in object_ids}
    movable = [
        item
        for item in board.author_objects
        if item_id(item) in wanted and not is_unknown(item) and not is_locked(item)
    ]
    records = []
    for item in movable:
        bounds = object_bounds(item)
        if bounds is None:
            continue
        center = bounds[0] + bounds[2] / 2.0 if axis == "horizontal" else bounds[1] + bounds[3] / 2.0
        records.append((center, item, bounds))
    if len(records) < 3:
        return AuthorMutationResult()
    records.sort(key=lambda row: (row[0], item_id(row[1])))
    start = records[0][0]
    end = records[-1][0]
    by_id = {item_id(item): (item, bounds, index) for index, (_center, item, bounds) in enumerate(records)}
    staged = list(board.author_objects)
    for index, item in enumerate(staged):
        oid = item_id(item)
        if oid not in by_id:
            continue
        _current, bounds, order = by_id[oid]
        dx, dy = distributed_translation(
            bounds, index=order, count=len(records), start=start, end=end, axis=axis
        )
        if dx == 0.0 and dy == 0.0:
            continue
        staged[index] = translate_object(item, dx, dy)
    staged = _resolve_staged_connectors(board, staged)
    return _commit_staged(board, staged)


def apply_author_duplicate(board, object_ids: Iterable[str], *, dx: float = 1.0, dy: float = 1.0) -> AuthorMutationResult:
    payload = copy_author_objects(board, object_ids, include_locked=False)
    if not payload.objects:
        return AuthorMutationResult()
    return paste_author_objects(board, payload, dx=dx, dy=dy)


def apply_author_lock(board, object_ids: Iterable[str], *, locked: bool | None = None) -> AuthorMutationResult:
    wanted = {str(object_id) for object_id in object_ids}
    known = [
        item
        for item in board.author_objects
        if item_id(item) in wanted and not is_unknown(item)
    ]
    if not known:
        return AuthorMutationResult()
    if locked is None:
        locked = not all(is_locked(item) for item in known)
    staged = list(board.author_objects)
    for index, item in enumerate(staged):
        if item_id(item) not in wanted or is_unknown(item):
            continue
        if bool(item.locked) == bool(locked):
            continue
        try:
            staged[index] = replace(item, locked=bool(locked))
        except (TypeError, UltraViewStateError):
            continue
    return _commit_staged(board, staged)


def apply_author_z_order(board, object_ids: Iterable[str], direction: str) -> AuthorMutationResult:
    if direction not in Z_ORDER_DIRECTIONS:
        return _warning("illegal_author_object")
    wanted = {str(object_id) for object_id in object_ids}
    staged = list(board.author_objects)
    selected = [item for item in staged if item_id(item) in wanted and not is_unknown(item)]
    if not selected:
        return AuthorMutationResult()
    selected_ids = {item_id(item) for item in selected}
    if direction == "front":
        rest = [item for item in staged if item_id(item) not in selected_ids]
        staged = rest + [item for item in staged if item_id(item) in selected_ids]
    elif direction == "back":
        rest = [item for item in staged if item_id(item) not in selected_ids]
        staged = [item for item in staged if item_id(item) in selected_ids] + rest
    elif direction == "forward":
        for index in range(len(staged) - 2, -1, -1):
            if item_id(staged[index]) in selected_ids and item_id(staged[index + 1]) not in selected_ids:
                staged[index], staged[index + 1] = staged[index + 1], staged[index]
    elif direction == "backward":
        for index in range(1, len(staged)):
            if item_id(staged[index]) in selected_ids and item_id(staged[index - 1]) not in selected_ids:
                staged[index], staged[index - 1] = staged[index - 1], staged[index]
    return _commit_staged(board, staged)


def apply_author_nudge(board, object_ids: Iterable[str], dx: float, dy: float) -> AuthorMutationResult:
    wanted = {str(object_id) for object_id in object_ids}
    if dx == 0.0 and dy == 0.0:
        return AuthorMutationResult()
    staged = list(board.author_objects)
    for index, item in enumerate(staged):
        if item_id(item) not in wanted or is_unknown(item) or is_locked(item):
            continue
        staged[index] = translate_object(item, dx, dy)
    staged = _resolve_staged_connectors(board, staged)
    return _commit_staged(board, staged)


def copy_author_objects(
    board,
    object_ids: Iterable[str],
    *,
    include_locked: bool = True,
) -> AuthorClipboardPayload:
    wanted = {str(object_id) for object_id in object_ids}
    copied: list[dict] = []
    for item in board.author_objects:
        oid = item_id(item)
        if oid not in wanted or is_unknown(item):
            continue
        if not include_locked and is_locked(item):
            continue
        copied.append(author_object_to_payload(item))
    return AuthorClipboardPayload(tuple(copied))


def paste_author_objects(
    board,
    payload: AuthorClipboardPayload,
    *,
    dx: float = 1.0,
    dy: float = 1.0,
) -> AuthorMutationResult:
    if not payload.objects:
        return AuthorMutationResult()
    id_map = {
        str(raw.get("id") or ""): new_author_object_id()
        for raw in payload.objects
        if str(raw.get("id") or "")
    }
    existing = {item_id(item) for item in board.author_objects}
    placed_cards = {item.ref for item in getattr(board, "free_grid", ())}
    staged = list(board.author_objects)
    for raw in payload.objects:
        copied = deepcopy(dict(raw))
        old_id = str(copied.get("id") or "")
        new_id = id_map.get(old_id) or new_author_object_id()
        copied["id"] = new_id
        copied = _remap_payload_targets(copied, id_map, existing, placed_cards)
        try:
            item = _author_object_from_payload(copied)
        except (TypeError, UltraViewStateError):
            continue
        if is_unknown(item):
            continue
        item = translate_object(item, dx, dy)
        staged.append(item)
    staged = _resolve_staged_connectors(board, staged)
    return _commit_staged(board, staged)


def _remap_payload_targets(
    raw: dict,
    id_map: dict[str, str],
    existing_authors: set[str],
    placed_cards: set,
) -> dict:
    for end in ("start", "end"):
        endpoint = raw.get(end)
        if not isinstance(endpoint, dict):
            continue
        target = endpoint.get("target")
        if not isinstance(target, dict):
            continue
        if target.get("kind") == "author":
            old = str(target.get("object_id") or "")
            if old in id_map:
                target = dict(target)
                target["object_id"] = id_map[old]
                endpoint = dict(endpoint)
                endpoint["target"] = target
                raw[end] = endpoint
            elif old not in existing_authors:
                endpoint = dict(endpoint)
                endpoint["target"] = None
                raw[end] = endpoint
        elif target.get("kind") == "card":
            card = target.get("card") or {}
            ref = None
            try:
                ref = UltraViewRef(str(card.get("section") or ""), str(card.get("view_id") or ""))
            except (TypeError, UltraViewStateError):
                ref = None
            if ref is None or ref not in placed_cards:
                endpoint = dict(endpoint)
                endpoint["target"] = None
                raw[end] = endpoint
    return raw


def _apply_style_fields(item, changes: dict[str, object]):
    kwargs: dict[str, object] = {}
    for field, value in changes.items():
        if field == "clear_fill":
            if value:
                kwargs["fill_palette"] = None
            continue
        if hasattr(type(item), field) or hasattr(item, field):
            kwargs[field] = value
    if not kwargs:
        return item
    try:
        return replace(item, **kwargs)
    except (TypeError, UltraViewStateError):
        return item


class _BoardShim:
    def __init__(self, board, objects) -> None:
        self.author_objects = objects
        self.free_grid = getattr(board, "free_grid", ())


def _resolve_staged_connectors(board, staged: list) -> list:
    shim = _BoardShim(board, staged)
    resolved = list(staged)
    for index, item in enumerate(resolved):
        if not isinstance(item, ConnectorObject):
            continue
        next_item, _lost = _resolve_connector_pair(
            shim, item, lost_cards=set(), lost_authors=set()
        )
        resolved[index] = next_item
    return resolved


def _commit_staged(board, staged: list, extra_warnings: tuple[str, ...] = ()) -> AuthorMutationResult:
    original = list(board.author_objects)
    if staged == original:
        return AuthorMutationResult((), extra_warnings)
    orig_ids = [item_id(item) for item in original]
    staged_ids = [item_id(item) for item in staged]
    orig_index = {oid: index for index, oid in enumerate(orig_ids)}
    staged_index = {oid: index for index, oid in enumerate(staged_ids)}
    patches: list[ObjectPatch] = []
    for item, oid in zip(original, orig_ids):
        before = author_object_to_payload(item)
        if oid not in staged_index:
            patches.append(ObjectPatch(oid, before, None, orig_index[oid], None))
            continue
        after = author_object_to_payload(staged[staged_index[oid]])
        if after == before and staged_index[oid] == orig_index[oid]:
            continue
        patches.append(
            ObjectPatch(oid, before, after, orig_index[oid], staged_index[oid])
        )
    for item, oid in zip(staged, staged_ids):
        if oid in orig_index:
            continue
        after = author_object_to_payload(item)
        patches.append(ObjectPatch(oid, None, after, None, staged_index[oid]))
    if not patches:
        return AuthorMutationResult((), extra_warnings)
    if not apply_author_patches(board, tuple(patches), forward=True):
        return AuthorMutationResult((), extra_warnings + ("illegal_author_object",))
    return AuthorMutationResult(tuple(patches), extra_warnings)
