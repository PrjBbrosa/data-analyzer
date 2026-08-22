"""Qt-free UltraView board state, legalization, digest, and axis facts.

UltraView is a read-only snapshot Board over five source workspaces. Wave 5
Task 5.2 moved identity, Board/Workspace, author DTOs, and stable constants
into ``mf4_analyzer.ultraview_core.model``. Task 5.3 family 1 moved Board and
workspace mutators into ``mf4_analyzer.ultraview_core.board_ops``. This module
immediately re-exports every moved name so existing ``from
mf4_analyzer.ui.ultraview_state import add_ref`` paths keep working, and
remains the owner of author mutation, payload legalization, presentation
digest, and derived preview status. It must not import Qt, MainWindow,
ChartStack, or analysis compute modules.
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from copy import deepcopy
from dataclasses import replace
from typing import Any, Iterable, Mapping, Sequence

from mf4_analyzer.ultraview_core.model import (
    AXIS_KIND_FREQUENCY,
    AXIS_KIND_ORDER,
    AXIS_KIND_TIME,
    AXIS_KIND_TIME_FREQ,
    COMPARE_FILTER_ALL,
    COMPARE_FILTERS,
    DEFAULT_BOARD_NAME,
    DEFAULT_LAYOUT_ID,
    DEFAULT_PRIMARY_RATIO,
    EQUAL_LAYOUTS,
    FREE_GRID_PRESETS,
    GRID_COLUMNS,
    GRID_MAX_COLUMN_SPAN,
    GRID_MAX_ROW_SPAN,
    GRID_MIN_COLUMN_SPAN,
    GRID_MIN_ROW_SPAN,
    GRID_RESOLUTION,
    HERO_LAYOUTS,
    LAYOUT_MODE_FREE_GRID,
    LAYOUT_MODE_TEMPLATE,
    LAYOUT_SLOTS,
    LEGACY_GRID_COLUMNS,
    LEGACY_MAX_GRID_ROWS,
    MAX_AUTHOR_OBJECTS,
    MAX_AUTHOR_POINTS,
    MAX_BOARD_MEMBERSHIP,
    MAX_GRID_ROWS,
    MAX_PLACED_CARDS,
    MAX_SHAPE_TEXT,
    MAX_STICKY_TEXT,
    MAX_STROKE_POINTS,
    MAX_TEXT_TEXT,
    MAX_UI_BOARDS,
    RATIO_MAX,
    RATIO_MIN,
    RATIO_STEP,
    SAFETY_COLUMN_MAX,
    SAFETY_COLUMN_MIN,
    SAFETY_ROW_MAX,
    SAFETY_ROW_MIN,
    SECTION_AXIS_KIND,
    SECTION_LABELS_EN,
    SECTION_LABELS_ZH,
    SOURCE_SECTIONS,
    STATUS_FRESH,
    STATUS_MISSING,
    STATUS_ORPHANED,
    STATUS_STALE,
    ULTRAVIEW_PAGE_OBJECT_NAME,
    ULTRAVIEW_REF_MIME,
    AnchorTarget,
    AuthorCommon,
    AuthorMutationResult,
    AuthorObject,
    AxisConsistencyFacts,
    BoardBox,
    BoardEditEntry,
    BoardItemKey,
    BoardPlacementSnapshot,
    BoardPoint,
    CardPlacement,
    ConnectorEndpoint,
    ConnectorObject,
    FreeGridPlacement,
    FreeGridRectPlan,
    GridAnchor,
    GridBounds,
    GridRect,
    ObjectPatch,
    PreviewMeta,
    ShapeObject,
    ShapeTextStyle,
    StickyObject,
    StrokeObject,
    TextObject,
    UltraViewBoardState,
    UltraViewRef,
    UltraViewStateError,
    UltraViewWorkspaceState,
    UnknownAuthorObject,
    _author_id,
    base_frame_bounds,
    best_template_for,
    clamp_grid_rect,
    default_board,
    default_workspace,
    grid_rect_in_safety,
    is_hero_layout,
    layout_capacity,
    layout_slots,
    make_ref,
    parse_ref_payload,
    safety_grid_bounds,
)

from mf4_analyzer.ultraview_core.board_ops import (
    active_board,
    add_ref,
    all_refs,
    apply_board_placement,
    apply_free_grid_preset,
    capture_board_placement,
    clamp_ratio,
    create_board,
    delete_board,
    duplicate_board,
    empty_slots,
    first_empty_slot,
    free_grid_default_span,
    free_grid_placement_for,
    free_grid_to_template,
    mark_workspace_mutated,
    membership_set,
    move_to_unplaced,
    nudge_ratio,
    organize_free_grid,
    organized_placements,
    place_free_grid_from_unplaced,
    place_from_unplaced,
    placed_ref_set,
    placement_for,
    plan_free_grid_rects,
    rebind_ref,
    remove_ref,
    rename_board,
    reorder_board,
    replace_free_grid_ref,
    replace_slot,
    resolve_free_grid_insert_rect,
    set_active_board,
    set_free_grid_rect,
    set_free_grid_rects,
    set_layout,
    set_presentation_flags,
    set_ratio,
    set_workspace_preview_sidecar,
    set_workspace_show_card_actions,
    slot_occupant,
    swap_slots,
    template_to_free_grid,
    _append_unplaced,
    _coerce_grid_int,
    _grid_overlaps,
    _legal_grid_rect,
    _sort_placements,
    _take_membership,
    _warn,
)

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

RANGE_ABS_TOL = 1e-9
RANGE_REL_TOL = 1e-6


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
