"""Qt-free UltraView board state, legalization, digest, and axis facts.

UltraView is a read-only snapshot Board over five source workspaces. Wave 5
Task 5.2 moved identity, Board/Workspace, author DTOs, and stable constants
into ``mf4_analyzer.ultraview_core.model``. Task 5.3 family 1 moved Board and
workspace mutators into ``mf4_analyzer.ultraview_core.board_ops``. Family 2
moved live author mutators into ``mf4_analyzer.ultraview_core.author_ops``.
Family 4 moved presentation/filter/axis facts into
``mf4_analyzer.ultraview_core.presentation``. This module immediately
re-exports every moved name so existing ``from
mf4_analyzer.ui.ultraview_state import add_ref`` paths keep working, and
remains the owner of payload legalization and presentation digest. It must
not import Qt, MainWindow, ChartStack, or analysis compute modules.
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from copy import deepcopy
from dataclasses import replace
from typing import Any, Mapping, Sequence

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

from mf4_analyzer.ultraview_core.author_ops import (
    apply_author_patches,
    apply_board_edit_entry,
    author_object_to_payload,
    board_edit_entry_byte_cost,
    create_author_object,
    delete_author_objects,
    reorder_author_object,
    set_author_locked,
    update_author_object,
    _RECOGNIZED_AUTHOR_KINDS,
    _anchor_target_from_payload,
    _author_index,
    _author_mutation,
    _author_object_from_payload,
    _author_object_id,
    _author_objects_valid,
    _author_patch_candidate,
    _author_warning,
    _box_from_payload,
    _clone_author_objects,
    _endpoint_from_payload,
    _payload_equal,
    _placement_snapshot_payload,
    _point_from_payload,
    _recognized_author_object_from_payload,
    _shape_text_style_from_payload,
)

from mf4_analyzer.ultraview_core.presentation import (
    RANGE_ABS_TOL,
    RANGE_REL_TOL,
    axis_consistency_facts,
    card_matches_compare_filter,
    derive_preview_status,
    normalize_unit,
    ranges_close,
    section_search_haystack,
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
