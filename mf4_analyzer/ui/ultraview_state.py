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
ULTRAVIEW_SCHEMA = 1
DIGEST_SCHEMA = 1

LAYOUT_SLOTS: dict[str, tuple[str, ...]] = {
    "split_horizontal": ("left", "right"),
    "split_vertical": ("top", "bottom"),
    "grid_2x2": ("tl", "tr", "bl", "br"),
    "hero_left_4": ("primary", "aux_0", "aux_1", "aux_2"),
    "hero_top_4": ("primary", "aux_0", "aux_1", "aux_2"),
    "grid_3x2": ("r0c0", "r0c1", "r0c2", "r1c0", "r1c1", "r1c2"),
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
    return [p.ref for p in board.placements] + list(board.unplaced)


def placed_ref_set(board: UltraViewBoardState) -> set[UltraViewRef]:
    return {p.ref for p in board.placements}


def membership_set(board: UltraViewBoardState) -> set[UltraViewRef]:
    return set(all_refs(board))


def placement_for(board: UltraViewBoardState, ref: UltraViewRef) -> CardPlacement | None:
    for placement in board.placements:
        if placement.ref == ref:
            return placement
    return None


def slot_occupant(board: UltraViewBoardState, slot_id: str) -> UltraViewRef | None:
    for placement in board.placements:
        if placement.slot_id == slot_id:
            return placement.ref
    return None


def empty_slots(board: UltraViewBoardState) -> list[str]:
    occupied = {p.slot_id for p in board.placements}
    return [slot for slot in layout_slots(board.layout_id) if slot not in occupied]


def first_empty_slot(board: UltraViewBoardState) -> str | None:
    slots = empty_slots(board)
    return slots[0] if slots else None


def _warn(code: str, detail: str = "") -> str:
    return f"{code}: {detail}" if detail else code


def _remove_ref_everywhere(board: UltraViewBoardState, ref: UltraViewRef) -> None:
    board.placements = [p for p in board.placements if p.ref != ref]
    board.unplaced = [item for item in board.unplaced if item != ref]


def _append_unplaced(board: UltraViewBoardState, ref: UltraViewRef) -> None:
    if ref not in board.unplaced and placement_for(board, ref) is None:
        board.unplaced.append(ref)


def _place(board: UltraViewBoardState, slot_id: str, ref: UltraViewRef) -> None:
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


def set_layout(board: UltraViewBoardState, layout_id: str) -> list[str]:
    warnings: list[str] = []
    if layout_id not in LAYOUT_SLOTS:
        warnings.append(_warn("unknown_layout", str(layout_id)))
        layout_id = DEFAULT_LAYOUT_ID
    ordered_refs = [p.ref for p in board.placements]
    new_slots = layout_slots(layout_id)
    board.layout_id = layout_id
    board.placements = []
    overflow = ordered_refs[len(new_slots):]
    for slot, ref in zip(new_slots, ordered_refs):
        board.placements.append(CardPlacement(slot_id=slot, ref=ref))
    for ref in overflow:
        _append_unplaced(board, ref)
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


def board_to_payload(board: UltraViewBoardState) -> dict[str, Any]:
    return {
        "schema": ULTRAVIEW_SCHEMA,
        "board": {
            "board_id": board.board_id,
            "name": board.name,
            "layout_id": board.layout_id,
            "primary_ratio": board.primary_ratio,
            "show_titles": bool(board.show_titles),
            "show_sources": bool(board.show_sources),
            "placements": [
                {
                    "slot_id": p.slot_id,
                    "section": p.ref.section,
                    "view_id": p.ref.view_id,
                }
                for p in board.placements
            ],
            "unplaced": [ref.to_dict() for ref in board.unplaced],
        },
    }


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

    schema = payload.get("schema", ULTRAVIEW_SCHEMA)
    board_raw = payload.get("board", payload if "layout_id" in payload else None)
    if schema != ULTRAVIEW_SCHEMA:
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

    layout_id = board_raw.get("layout_id", DEFAULT_LAYOUT_ID)
    if layout_id not in LAYOUT_SLOTS:
        warnings.append(_warn("unknown_layout", repr(layout_id)))
        layout_id = DEFAULT_LAYOUT_ID
    board.layout_id = layout_id
    warnings.extend(set_ratio(board, board_raw.get("primary_ratio", DEFAULT_PRIMARY_RATIO)))
    board.show_titles = bool(board_raw.get("show_titles", True))
    board.show_sources = bool(board_raw.get("show_sources", True))

    seen_refs: set[UltraViewRef] = set()
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
            if ref not in seen_refs:
                _append_unplaced(board, ref)
                seen_refs.add(ref)
            else:
                warnings.append(_warn("duplicate_ref", f"{ref.section}/{ref.view_id}"))
            continue
        if slot_id in seen_slots:
            warnings.append(_warn("duplicate_slot", str(slot_id)))
            if ref not in seen_refs:
                _append_unplaced(board, ref)
                seen_refs.add(ref)
            continue
        if ref in seen_refs:
            warnings.append(_warn("duplicate_ref", f"{ref.section}/{ref.view_id}"))
            continue
        seen_slots.add(slot_id)
        seen_refs.add(ref)
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
        if ref in seen_refs:
            warnings.append(_warn("duplicate_ref", f"{ref.section}/{ref.view_id}"))
            continue
        seen_refs.add(ref)
        board.unplaced.append(ref)

    return board, warnings


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
