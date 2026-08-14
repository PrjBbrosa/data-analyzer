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
from dataclasses import dataclass, field
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
# The top-level .tlproj schema stays at 2.  This independent, nested schema
# carries the Board-only evolution so ordinary projects remain readable by the
# rest of the session codec.
ULTRAVIEW_SCHEMA = 3
DIGEST_SCHEMA = 1

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


GRID_COLUMNS = 12
MAX_GRID_ROWS = 48
MAX_PLACED_CARDS = 24
MAX_UI_BOARDS = 20
MAX_BOARD_MEMBERSHIP = 200
GRID_MIN_COLUMN_SPAN = 2
GRID_MAX_COLUMN_SPAN = 12
GRID_MIN_ROW_SPAN = 2
GRID_MAX_ROW_SPAN = 8
LAYOUT_MODE_TEMPLATE = "template"
LAYOUT_MODE_FREE_GRID = "free_grid"
FREE_GRID_PRESETS: dict[str, tuple[int, int]] = {
    "small": (3, 2),
    "standard": (4, 3),
    "wide": (6, 3),
    "tall": (4, 5),
    "large": (6, 6),
    "banner": (12, 4),
}


@dataclass(frozen=True)
class GridRect:
    """Stable, screen-independent card rectangle for P2's controlled grid."""

    column: int
    row: int
    column_span: int
    row_span: int


@dataclass
class FreeGridPlacement:
    ref: UltraViewRef
    rect: GridRect


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
    layout_mode: str = LAYOUT_MODE_TEMPLATE
    free_grid: list[FreeGridPlacement] = field(default_factory=list)
    free_grid_default_size: str = "standard"


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
    )


def default_workspace() -> UltraViewWorkspaceState:
    board = default_board()
    return UltraViewWorkspaceState(active_board_id=board.board_id, boards=[board])


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


def add_ref(board: UltraViewBoardState, ref: UltraViewRef) -> list[str]:
    """Add ``ref`` to the first empty slot, or the tray if the board is full.

    Duplicate membership is a no-op so the caller can locate the existing card.
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
        rect = _first_free_grid_rect(board.free_grid)
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
    board: UltraViewBoardState, ref: UltraViewRef
) -> list[str]:
    """Place a tray ref at the next legal free-grid rect without re-compute."""
    if board.layout_mode != LAYOUT_MODE_FREE_GRID:
        return [_warn("not_free_grid")]
    if ref not in board.unplaced:
        return [_warn("not_unplaced", f"{ref.section}/{ref.view_id}")]
    if len(board.free_grid) >= MAX_PLACED_CARDS:
        return [_warn("grid_full")]
    rect = _first_free_grid_rect(board.free_grid)
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


def _legal_grid_rect(raw: Mapping[str, Any] | GridRect) -> GridRect | None:
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
    col_span = min(GRID_MAX_COLUMN_SPAN, max(GRID_MIN_COLUMN_SPAN, col_span))
    row_span = min(GRID_MAX_ROW_SPAN, max(GRID_MIN_ROW_SPAN, row_span))
    return GridRect(
        min(GRID_COLUMNS - col_span, max(0, column)),
        min(MAX_GRID_ROWS - row_span, max(0, row)),
        col_span,
        row_span,
    )


def _grid_overlaps(left: GridRect, right: GridRect) -> bool:
    return (
        left.column < right.column + right.column_span
        and right.column < left.column + left.column_span
        and left.row < right.row + right.row_span
        and right.row < left.row + left.row_span
    )


def _first_free_grid_rect(
    placements: Sequence[FreeGridPlacement], *, span: tuple[int, int] = (4, 3)
) -> GridRect | None:
    prototype = _legal_grid_rect({"column": 0, "row": 0, "column_span": span[0], "row_span": span[1]})
    if prototype is None:
        return None
    for row in range(MAX_GRID_ROWS - prototype.row_span + 1):
        for column in range(GRID_COLUMNS - prototype.column_span + 1):
            candidate = GridRect(column, row, prototype.column_span, prototype.row_span)
            if not any(_grid_overlaps(candidate, item.rect) for item in placements):
                return candidate
    return None


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
    """Remove fully empty rows while retaining each card's size/order/column."""
    occupied_rows = {
        row
        for item in placements
        for row in range(item.rect.row, item.rect.row + item.rect.row_span)
    }
    empty_before = [
        row for row in range(MAX_GRID_ROWS) if row not in occupied_rows
    ]
    result: list[FreeGridPlacement] = []
    for item in placements:
        shift = sum(1 for row in empty_before if row < item.rect.row)
        rect = item.rect
        result.append(
            FreeGridPlacement(
                item.ref,
                GridRect(rect.column, rect.row - shift, rect.column_span, rect.row_span),
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
    """Frozen conversion map from P0/P1 templates to P2's integer grid."""
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
        return list(maps[layout_id])
    if layout_id == "grid_3x2":
        return [GridRect(col * 4, row * 3, 4, 3) for row in range(2) for col in range(3)]
    if layout_id == "grid_3x3":
        return [GridRect(col * 4, row * 3, 4, 3) for row in range(3) for col in range(3)]
    if layout_id == "grid_4x3":
        return [GridRect(col * 3, row * 3, 3, 3) for row in range(3) for col in range(4)]
    return _template_grid_rects(DEFAULT_LAYOUT_ID)


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
    if schema not in {1, 2, 3}:
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

    seen_refs: set[UltraViewRef] = set()
    if board.layout_mode == LAYOUT_MODE_FREE_GRID:
        free_raw = board_raw.get("free_grid")
        if not isinstance(free_raw, Mapping):
            warnings.append(_warn("missing_free_grid"))
            free_raw = {}
        if free_raw.get("columns", GRID_COLUMNS) != GRID_COLUMNS:
            warnings.append(_warn("grid_columns_normalized"))
        default_size = free_raw.get("default_size")
        if isinstance(default_size, str) and default_size:
            board.free_grid_default_size = default_size
        for item in free_raw.get("placements") or []:
            if not isinstance(item, Mapping):
                warnings.append(_warn("illegal_grid_placement"))
                continue
            ref = parse_ref_payload(item)
            rect = _legal_grid_rect(item)
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

    return board, warnings


def workspace_to_payload(workspace: UltraViewWorkspaceState) -> dict[str, Any]:
    """Serialize the active multi-Board workspace without runtime state."""
    if workspace.opaque_payload is not None:
        return dict(workspace.opaque_payload)
    return {
        "schema": ULTRAVIEW_SCHEMA,
        "workspace": {
            "active_board_id": active_board(workspace).board_id,
            "boards": [_board_payload(board) for board in workspace.boards],
        },
        **({"preview_sidecar": dict(workspace.preview_sidecar)} if workspace.preview_sidecar else {}),
    }


def normalize_workspace_payload(
    payload: Mapping[str, Any] | None,
) -> tuple[UltraViewWorkspaceState, list[str]]:
    """Migrate schema 1/2/3 to one editable workspace, never dropping refs."""
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
