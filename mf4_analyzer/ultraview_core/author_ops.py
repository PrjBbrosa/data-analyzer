"""Qt-free UltraView author mutation and mixed Board-edit apply.

Wave 5 Task 5.3 family 2. Live author mutators write ``Board.author_objects``
in memory. Payload legalize (``normalize_board_payload``) stays in
``mf4_analyzer.ui.ultraview_state`` until Task 5.4. This module must not
import Qt, ``mf4_analyzer.ui``, chart_stack, MainWindow, compositor, or
Card Fit.
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from typing import Any, Iterable, Mapping, Sequence

from .board_ops import apply_board_placement
from .model import (
    MAX_AUTHOR_OBJECTS,
    MAX_AUTHOR_POINTS,
    AnchorTarget,
    AuthorMutationResult,
    AuthorObject,
    BoardBox,
    BoardEditEntry,
    BoardPlacementSnapshot,
    BoardPoint,
    CardPlacement,
    ConnectorEndpoint,
    ConnectorObject,
    FreeGridPlacement,
    ObjectPatch,
    ShapeObject,
    ShapeTextStyle,
    StickyObject,
    StrokeObject,
    TextObject,
    UltraViewBoardState,
    UltraViewStateError,
    UnknownAuthorObject,
    _author_id,
    parse_ref_payload,
)

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
            corner_radius=raw.get("corner_radius", 0),
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
            text=raw.get("text", ""),
            text_style=_shape_text_style_from_payload(raw.get("text_style")),
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
            "corner_radius": item.corner_radius,
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
            "text": item.text, "text_style": item.text_style.to_dict(),
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
