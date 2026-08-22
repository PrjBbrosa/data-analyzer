"""Qt-free UltraView schema legalize, migration, and payload codec.

Wave 5 Task 5.4. Owns schema 1–5 round-trip, future opaque passthrough, and
the Board-payload hasher ``presentation_digest``. Author object encode/decode
helpers stay in :mod:`mf4_analyzer.ultraview_core.author_ops`; this module
imports them rather than copying. Legacy rect lift uses
``board_ops._scale_legacy_grid_rect`` so live ``template_to_free_grid`` and
payload migration share one rounding path.

This module must not import Qt, ``mf4_analyzer.ui``, chart_stack, MainWindow,
compositor, or Card Fit. Capture ``_digest_leaf`` stays on
``UltraViewCaptureCoordinator``.
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from copy import deepcopy
from dataclasses import replace
from typing import Any, Mapping, Sequence

from .author_ops import (
    _RECOGNIZED_AUTHOR_KINDS,
    _recognized_author_object_from_payload,
    author_object_to_payload,
)
from .board_ops import (
    _append_unplaced,
    _coerce_grid_int,
    _grid_overlaps,
    _legal_grid_rect,
    _scale_legacy_grid_rect,
    _sort_placements,
    _take_membership,
    _warn,
    active_board,
    placed_ref_set,
    set_ratio,
)
from .model import (
    DEFAULT_LAYOUT_ID,
    DEFAULT_PRIMARY_RATIO,
    GRID_COLUMNS,
    LAYOUT_MODE_FREE_GRID,
    LAYOUT_MODE_TEMPLATE,
    LAYOUT_SLOTS,
    LEGACY_GRID_COLUMNS,
    MAX_AUTHOR_OBJECTS,
    MAX_AUTHOR_POINTS,
    MAX_PLACED_CARDS,
    MAX_UI_BOARDS,
    SOURCE_SECTIONS,
    AuthorObject,
    CardPlacement,
    ConnectorEndpoint,
    ConnectorObject,
    FreeGridPlacement,
    GridRect,
    ShapeObject,
    StickyObject,
    StrokeObject,
    TextObject,
    UltraViewBoardState,
    UltraViewRef,
    UltraViewStateError,
    UltraViewWorkspaceState,
    UnknownAuthorObject,
    _author_id,
    default_board,
    default_workspace,
    layout_slots,
    parse_ref_payload,
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
    return _scale_legacy_grid_rect(legal)


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
