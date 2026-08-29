"""Qt-free UltraView board/workspace CRUD and placement operations.

Wave 5 Task 5.3 family 1. Mutators write Board/Workspace in memory. This
module must not import Qt, ``mf4_analyzer.ui``, chart_stack, MainWindow,
compositor, or Card Fit. Payload legalize/migration lives in
``mf4_analyzer.ultraview_core.serialization``.
"""
from __future__ import annotations

import math
import uuid
from copy import deepcopy
from typing import Any, Mapping, Sequence

from .model import (
    DEFAULT_BOARD_NAME,
    DEFAULT_LAYOUT_ID,
    DEFAULT_PRIMARY_RATIO,
    FREE_GRID_PRESETS,
    GRID_COLUMNS,
    GRID_RESOLUTION,
    LAYOUT_MODE_FREE_GRID,
    LAYOUT_MODE_TEMPLATE,
    LAYOUT_SLOTS,
    MAX_BOARD_MEMBERSHIP,
    MAX_GRID_ROWS,
    MAX_PLACED_CARDS,
    MAX_UI_BOARDS,
    RATIO_MAX,
    RATIO_MIN,
    RATIO_STEP,
    SAFETY_COLUMN_MAX,
    SAFETY_COLUMN_MIN,
    SAFETY_ROW_MAX,
    SAFETY_ROW_MIN,
    AuthorObject,
    BoardPlacementSnapshot,
    CardPlacement,
    FreeGridPlacement,
    FreeGridRectPlan,
    GridAnchor,
    GridRect,
    UltraViewBoardState,
    UltraViewRef,
    UltraViewWorkspaceState,
    clamp_grid_rect,
    default_board,
    layout_slots,
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


def _clone_author_objects(items: Sequence[AuthorObject]) -> list[AuthorObject]:
    """Isolate author payloads so a Board duplicate cannot alias nested state.

    Recognized author objects are frozen dataclasses; unknown objects carry a
    mutable ``raw`` mapping. ``deepcopy`` keeps the same isolation the payload
    round-trip provided, without importing the 5.4 codec from ``ultraview_state``.
    """
    return deepcopy(list(items))


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


def plan_free_grid_rects(
    board: UltraViewBoardState,
    updates: Sequence[tuple[UltraViewRef, GridRect]],
) -> FreeGridRectPlan:
    """Validate several free-grid moves without writing. Overflow is not clamped."""
    if board.layout_mode != LAYOUT_MODE_FREE_GRID:
        return FreeGridRectPlan((), (_warn("not_free_grid"),))
    if not updates:
        return FreeGridRectPlan()
    by_ref = {item.ref: item for item in board.free_grid}
    proposed: dict[UltraViewRef, GridRect] = {}
    for ref, rect in updates:
        if ref not in by_ref:
            return FreeGridRectPlan(
                (), (_warn("unknown_ref", f"{ref.section}/{ref.view_id}"),)
            )
        legal = _legal_grid_rect(rect)
        if legal is None or legal != rect:
            return FreeGridRectPlan((), (_warn("invalid_grid_rect"),))
        proposed[ref] = legal
    new_rects = {
        item.ref: proposed.get(item.ref, item.rect) for item in board.free_grid
    }
    items = tuple(new_rects.items())
    for index, (_ref_a, rect_a) in enumerate(items):
        for _ref_b, rect_b in items[index + 1 :]:
            if _grid_overlaps(rect_a, rect_b):
                return FreeGridRectPlan((), (_warn("grid_collision"),))
    return FreeGridRectPlan(tuple(proposed.items()))


def set_free_grid_rects(
    board: UltraViewBoardState,
    updates: Sequence[tuple[UltraViewRef, GridRect]],
) -> list[str]:
    """Apply several free-grid moves atomically. Overflow is not clamped."""
    plan = plan_free_grid_rects(board, updates)
    if plan.warnings:
        return list(plan.warnings)
    proposed = dict(plan.proposed)
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


def apply_native_layout(board: UltraViewBoardState, plan) -> list[str]:
    """Apply a native layout plan in one Board mutation. No dirty/refresh."""
    from .native_layout import NativeLayoutPlan

    if not isinstance(plan, NativeLayoutPlan):
        return [_warn("invalid_native_plan")]
    warnings = list(plan.warnings)
    if board.layout_mode != LAYOUT_MODE_FREE_GRID:
        template_to_free_grid(board)
    members = membership_set(board)
    remaining_membership = MAX_BOARD_MEMBERSHIP - len(members)
    remaining_placed = MAX_PLACED_CARDS - len(board.free_grid)
    for ref, rect in plan.placed:
        if ref in members:
            warnings.append("duplicate_ref")
            continue
        if remaining_membership <= 0:
            warnings.append("membership_limit")
            continue
        if remaining_placed <= 0:
            warnings.append("placed_limit")
            _append_unplaced(board, ref)
            remaining_membership -= 1
            members.add(ref)
            continue
        if any(_grid_overlaps(rect, item.rect) for item in board.free_grid):
            warnings.append(_warn("grid_collision"))
            _append_unplaced(board, ref)
            remaining_membership -= 1
            members.add(ref)
            continue
        board.free_grid.append(FreeGridPlacement(ref, rect))
        members.add(ref)
        remaining_membership -= 1
        remaining_placed -= 1
    for ref in plan.unplaced:
        if ref in members:
            continue
        if remaining_membership <= 0:
            warnings.append("membership_limit")
            continue
        _append_unplaced(board, ref)
        members.add(ref)
        remaining_membership -= 1
    return warnings


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
