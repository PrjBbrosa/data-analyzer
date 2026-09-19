"""Qt-free pinned-cursor INTENT model.

Persists reproducible pin intent (coordinates, owner identity, bindings,
full/mini, expanded/collapsed state, safe-rect anchor). Does not store HTML,
widgets, arrays,
screenshots, derived numeric samples, or runtime caches. Must not import
Qt, pyqtgraph, or ``cursor_display_model`` Sample DTOs.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


PAYLOAD_VERSION = 1

PIN_MODES = frozenset({"single", "dual"})
PIN_DOMAINS = frozenset({"time", "channel", "frequency", "frf"})
PIN_PRESENTATIONS = frozenset({"full", "mini"})
_H_EDGES = frozenset({"left", "right"})
_V_EDGES = frozenset({"top", "bottom"})

# Tight enough that two points which format to the same 3-decimal text stay
# distinct, while JSON/IEEE round-trips of one physical value still match.
_COORD_REL_TOL = 1e-12
_COORD_ABS_TOL = 1e-15

REASON_UNKNOWN_PAYLOAD_VERSION = "unknown_payload_version"
REASON_INVALID_RECORD = "invalid_record"
REASON_INVALID_COLLECTION = "invalid_collection"
REASON_DUPLICATE_RECORD_ID = "duplicate_record_id"
REASON_DUPLICATE_ORDINAL = "duplicate_ordinal"
REASON_INVALID_RECORD_ID = "invalid_record_id"
REASON_INVALID_ORDINAL = "invalid_ordinal"
REASON_INVALID_MODE = "invalid_mode"
REASON_INVALID_DOMAIN = "invalid_domain"
REASON_BOOL_COORD = "bool_coord"
REASON_NON_FINITE_COORD = "non_finite_coord"
REASON_MISSING_COORD = "missing_coord"
REASON_INCOMPLETE_DUAL = "incomplete_dual"
REASON_INVALID_BINDINGS = "invalid_bindings"
REASON_INVALID_AXIS_IDENTITY = "invalid_axis_identity"
REASON_INVALID_PANEL_EXPANDED = "invalid_panel_expanded"


@dataclass(frozen=True)
class PinnedCursorBinding:
    """Captured curve identity. Display names, colors, and P numbers are not identity."""

    fid: str
    channel: str
    binding_id: str = ""
    role: str = ""

    def to_dict(self) -> dict[str, str]:
        data = {"fid": self.fid, "channel": self.channel}
        if self.binding_id:
            data["binding_id"] = self.binding_id
        if self.role:
            data["role"] = self.role
        return data


@dataclass(frozen=True)
class PinnedCursorAnchor:
    """Placement relative to the owner safe-rect. Never screen pixels or DPR."""

    h_edge: str = "right"
    v_edge: str = "top"
    nx: float = 1.0
    ny: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "h_edge": self.h_edge,
            "v_edge": self.v_edge,
            "nx": self.nx,
            "ny": self.ny,
        }


DEFAULT_ANCHOR = PinnedCursorAnchor()


@dataclass(frozen=True)
class PinnedCursorIntent:
    record_id: str
    ordinal: int
    mode: str
    domain: str
    x: float | None = None
    ax: float | None = None
    bx: float | None = None
    x_unit: str = ""
    axis_identity: tuple[str, str] | None = None
    bindings: tuple[PinnedCursorBinding, ...] = ()
    presentation: str = "full"
    panel_expanded: bool = False
    anchor: PinnedCursorAnchor = field(default_factory=PinnedCursorAnchor)
    payload_version: int = PAYLOAD_VERSION


@dataclass(frozen=True)
class PinnedCursorCollection:
    scope_id: str
    records: tuple[PinnedCursorIntent, ...] = ()
    next_ordinal: int = 1
    payload_version: int = PAYLOAD_VERSION

    @property
    def version(self) -> int:
        return self.payload_version


@dataclass(frozen=True)
class DroppedPinnedCursor:
    reason: str
    index: int | None = None
    detail: str = ""


def empty_collection() -> PinnedCursorCollection:
    """Mint a new empty collection with a fresh scope_id."""
    return PinnedCursorCollection(
        scope_id=_new_uuid(),
        records=(),
        next_ordinal=1,
        payload_version=PAYLOAD_VERSION,
    )


def clear_collection(
    collection: PinnedCursorCollection | None = None,
) -> PinnedCursorCollection:
    """Drop all records. Keep scope_id and next_ordinal when an owner is given."""
    if collection is None:
        return empty_collection()
    return replace(collection, records=())


def collection_to_dict(collection: PinnedCursorCollection | None) -> dict[str, Any]:
    if collection is None:
        collection = empty_collection()
    return {
        "payload_version": int(collection.payload_version),
        "scope_id": collection.scope_id,
        "next_ordinal": int(collection.next_ordinal),
        "records": [_intent_to_dict(item) for item in collection.records],
    }


def collection_from_dict(raw: Any) -> PinnedCursorCollection:
    """Decode an optional persisted field. Missing/illegal → empty collection."""
    collection, dropped = normalize_collection(raw)
    for item in dropped:
        logger.warning(
            "dropped pinned cursor record (%s) at index %s: %s",
            item.reason,
            item.index,
            item.detail,
        )
    return collection


def normalize_collection(
    raw: Any,
) -> tuple[PinnedCursorCollection, tuple[DroppedPinnedCursor, ...]]:
    """Return a legal collection. Bad pins are dropped one-by-one with diagnostics."""
    if isinstance(raw, PinnedCursorCollection):
        raw = collection_to_dict(raw)
    if raw is None:
        return empty_collection(), ()
    if not isinstance(raw, Mapping):
        return empty_collection(), (
            DroppedPinnedCursor(
                reason=REASON_INVALID_COLLECTION,
                detail=type(raw).__name__,
            ),
        )

    version = _read_payload_version(raw)
    scope_id = _uuid_str(raw.get("scope_id")) or _new_uuid()
    if version != PAYLOAD_VERSION:
        return (
            PinnedCursorCollection(
                scope_id=scope_id,
                records=(),
                next_ordinal=1,
                payload_version=PAYLOAD_VERSION,
            ),
            (
                DroppedPinnedCursor(
                    reason=REASON_UNKNOWN_PAYLOAD_VERSION,
                    detail=repr(raw.get("payload_version", raw.get("version"))),
                ),
            ),
        )

    dropped: list[DroppedPinnedCursor] = []
    records: list[PinnedCursorIntent] = []
    seen_ids: set[str] = set()
    seen_ordinals: set[int] = set()
    raw_records = raw.get("records")
    if raw_records is None:
        raw_records = ()
    elif not isinstance(raw_records, Sequence) or isinstance(
        raw_records, (str, bytes, bytearray)
    ):
        dropped.append(
            DroppedPinnedCursor(
                reason=REASON_INVALID_RECORD,
                detail="records is not a sequence",
            )
        )
        raw_records = ()

    for index, item in enumerate(raw_records):
        intent, error = _parse_intent(item, index=index)
        if error is not None:
            dropped.append(error)
            continue
        assert intent is not None
        if intent.record_id in seen_ids:
            dropped.append(
                DroppedPinnedCursor(
                    reason=REASON_DUPLICATE_RECORD_ID,
                    index=index,
                    detail=intent.record_id,
                )
            )
            continue
        if intent.ordinal in seen_ordinals:
            dropped.append(
                DroppedPinnedCursor(
                    reason=REASON_DUPLICATE_ORDINAL,
                    index=index,
                    detail=str(intent.ordinal),
                )
            )
            continue
        seen_ids.add(intent.record_id)
        seen_ordinals.add(intent.ordinal)
        records.append(intent)

    next_ordinal = _coerce_positive_int(raw.get("next_ordinal"))
    floor = (max(seen_ordinals) + 1) if seen_ordinals else 1
    if next_ordinal is None or next_ordinal < floor:
        next_ordinal = floor

    collection = PinnedCursorCollection(
        scope_id=scope_id,
        records=tuple(records),
        next_ordinal=next_ordinal,
        payload_version=PAYLOAD_VERSION,
    )
    return collection, tuple(dropped)


def coords_equal(a: Any, b: Any) -> bool:
    """Compare finite physical coordinates. Bool is not a coordinate."""
    if a is None and b is None:
        return True
    left = _finite_float(a)
    right = _finite_float(b)
    if left is None or right is None:
        return False
    return math.isclose(
        left, right, rel_tol=_COORD_REL_TOL, abs_tol=_COORD_ABS_TOL,
    )


def capture_identity(intent: PinnedCursorIntent) -> tuple[Any, ...]:
    """Duplicate-P key: mode, domain, axis, binding set, physical coords.

    Excludes ordinal, UUID, full/mini, anchor, and formatted text.
    """
    axis = intent.axis_identity
    bindings = frozenset(
        (item.fid, item.channel, item.binding_id, item.role)
        for item in intent.bindings
    )
    if intent.mode == "dual":
        coords: tuple[Any, ...] = (intent.ax, intent.bx)
    else:
        coords = (intent.x,)
    return (intent.mode, intent.domain, axis, bindings, coords)


def captures_equal(left: PinnedCursorIntent, right: PinnedCursorIntent) -> bool:
    """True when two intents are the same physical capture (coords via isclose)."""
    a = capture_identity(left)
    b = capture_identity(right)
    if a[:4] != b[:4]:
        return False
    return all(coords_equal(x, y) for x, y in zip(a[4], b[4], strict=True))


def remap_collection_fids(
    collection: PinnedCursorCollection,
    fid_map: Mapping[Any, Any] | None,
) -> PinnedCursorCollection:
    """Rewrite known fids; drop unknown fids (do not rebind by display name)."""
    mapping = fid_map if isinstance(fid_map, Mapping) else {}
    records = []
    for item in collection.records:
        remapped = _remap_intent_fids(item, mapping)
        if remapped is not None:
            records.append(remapped)
    return replace(collection, records=tuple(records))


def duplicate_collection(
    collection: PinnedCursorCollection,
) -> PinnedCursorCollection:
    """Remint scope_id and every record_id. Local ordinals are kept."""
    records = tuple(
        replace(item, record_id=_new_uuid()) for item in collection.records
    )
    return replace(collection, scope_id=_new_uuid(), records=records)


def next_record(
    collection: PinnedCursorCollection,
    intent_without_id: PinnedCursorIntent | Mapping[str, Any],
) -> tuple[PinnedCursorCollection, PinnedCursorIntent]:
    """Assign a new record_id and the next ordinal, then append."""
    parsed, error = _parse_intent(
        intent_without_id, index=None, require_identity=False,
    )
    if parsed is None:
        reason = error.reason if error is not None else REASON_INVALID_RECORD
        detail = error.detail if error is not None else ""
        raise ValueError(f"invalid pinned cursor intent ({reason}): {detail}")
    ordinal = _next_ordinal(collection)
    intent = replace(
        parsed,
        record_id=_new_uuid(),
        ordinal=ordinal,
        payload_version=PAYLOAD_VERSION,
    )
    collection = replace(
        collection,
        records=collection.records + (intent,),
        next_ordinal=ordinal + 1,
    )
    return collection, intent


def remove_record(
    collection: PinnedCursorCollection,
    record_id: str,
) -> PinnedCursorCollection:
    """Remove one record. Ordinals are not reused."""
    target = str(record_id)
    kept = tuple(item for item in collection.records if item.record_id != target)
    if len(kept) == len(collection.records):
        return collection
    return replace(collection, records=kept)


def _intent_to_dict(intent: PinnedCursorIntent) -> dict[str, Any]:
    data: dict[str, Any] = {
        "payload_version": int(intent.payload_version),
        "record_id": intent.record_id,
        "ordinal": int(intent.ordinal),
        "mode": intent.mode,
        "domain": intent.domain,
        "x_unit": intent.x_unit,
        "bindings": [item.to_dict() for item in intent.bindings],
        "presentation": intent.presentation,
        "anchor": intent.anchor.to_dict(),
    }
    if intent.mode == "dual":
        data["ax"] = intent.ax
        data["bx"] = intent.bx
    else:
        data["x"] = intent.x
    if intent.axis_identity is not None:
        data["axis_identity"] = [intent.axis_identity[0], intent.axis_identity[1]]
    if intent.panel_expanded is True:
        data["panel_expanded"] = True
    return data


def _parse_intent(
    raw: Any,
    *,
    index: int | None,
    require_identity: bool = True,
) -> tuple[PinnedCursorIntent | None, DroppedPinnedCursor | None]:
    if isinstance(raw, PinnedCursorIntent):
        raw = _intent_to_dict(raw)
    if not isinstance(raw, Mapping):
        return None, DroppedPinnedCursor(
            reason=REASON_INVALID_RECORD,
            index=index,
            detail=type(raw).__name__,
        )

    version = _read_payload_version(raw)
    if version != PAYLOAD_VERSION:
        return None, DroppedPinnedCursor(
            reason=REASON_UNKNOWN_PAYLOAD_VERSION,
            index=index,
            detail=repr(raw.get("payload_version", raw.get("version"))),
        )

    mode = raw.get("mode")
    if mode not in PIN_MODES:
        return None, DroppedPinnedCursor(
            reason=REASON_INVALID_MODE, index=index, detail=repr(mode),
        )
    domain = raw.get("domain")
    if domain not in PIN_DOMAINS:
        return None, DroppedPinnedCursor(
            reason=REASON_INVALID_DOMAIN, index=index, detail=repr(domain),
        )

    coord_error = _coord_error(raw, mode=str(mode), index=index)
    if coord_error is not None:
        return None, coord_error

    axis, axis_error = _parse_axis_identity(raw.get("axis_identity"), index=index)
    if axis_error is not None:
        return None, axis_error

    bindings, bindings_error = _parse_bindings(raw.get("bindings"), index=index)
    if bindings_error is not None:
        return None, bindings_error
    if not bindings:
        return None, DroppedPinnedCursor(
            reason=REASON_INVALID_BINDINGS,
            index=index,
            detail="pinned cursor requires at least one binding",
        )

    if require_identity:
        record_id = _uuid_str(raw.get("record_id"))
        if record_id is None:
            return None, DroppedPinnedCursor(
                reason=REASON_INVALID_RECORD_ID,
                index=index,
                detail=repr(raw.get("record_id")),
            )
        ordinal = _coerce_positive_int(raw.get("ordinal"))
        if ordinal is None:
            return None, DroppedPinnedCursor(
                reason=REASON_INVALID_ORDINAL,
                index=index,
                detail=repr(raw.get("ordinal")),
            )
    else:
        record_id = _uuid_str(raw.get("record_id")) or _new_uuid()
        ordinal = _coerce_positive_int(raw.get("ordinal")) or 1

    presentation = raw.get("presentation")
    if presentation not in PIN_PRESENTATIONS:
        presentation = "full"

    return (
        PinnedCursorIntent(
            record_id=record_id,
            ordinal=ordinal,
            mode=str(mode),
            domain=str(domain),
            x=_finite_float(raw.get("x")) if mode == "single" else None,
            ax=_finite_float(raw.get("ax")) if mode == "dual" else None,
            bx=_finite_float(raw.get("bx")) if mode == "dual" else None,
            x_unit=str(raw.get("x_unit") or ""),
            axis_identity=axis,
            bindings=bindings,
            presentation=str(presentation),
            panel_expanded=_parse_panel_expanded(raw, index=index),
            anchor=_parse_anchor(raw.get("anchor")),
            payload_version=PAYLOAD_VERSION,
        ),
        None,
    )


def _coord_error(
    raw: Mapping[str, Any], *, mode: str, index: int | None,
) -> DroppedPinnedCursor | None:
    if mode == "single":
        status = _coord_status(raw.get("x"))
        if status == "ok":
            return None
        reason = {
            "bool": REASON_BOOL_COORD,
            "missing": REASON_MISSING_COORD,
            "non_finite": REASON_NON_FINITE_COORD,
        }[status]
        return DroppedPinnedCursor(
            reason=reason, index=index, detail="x",
        )

    ax_status = _coord_status(raw.get("ax"))
    bx_status = _coord_status(raw.get("bx"))
    for name, status in (("ax", ax_status), ("bx", bx_status)):
        if status == "bool":
            return DroppedPinnedCursor(
                reason=REASON_BOOL_COORD, index=index, detail=name,
            )
        if status == "non_finite":
            return DroppedPinnedCursor(
                reason=REASON_NON_FINITE_COORD, index=index, detail=name,
            )
    if ax_status != "ok" or bx_status != "ok":
        return DroppedPinnedCursor(
            reason=REASON_INCOMPLETE_DUAL,
            index=index,
            detail="dual pins require finite ax and bx",
        )
    return None


def _coord_status(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if value is None:
        return "missing"
    if _finite_float(value) is None:
        return "non_finite"
    return "ok"


def _parse_panel_expanded(raw: Mapping[str, Any], *, index: int | None) -> bool:
    """Read the optional display intent without coercing truthy payload values."""
    if "panel_expanded" not in raw:
        return False
    value = raw.get("panel_expanded")
    if isinstance(value, bool):
        return value
    logger.warning(
        "normalized pinned cursor %s at index %s to false: %s",
        REASON_INVALID_PANEL_EXPANDED,
        index,
        type(value).__name__,
    )
    return False


def _parse_axis_identity(
    value: Any, *, index: int | None,
) -> tuple[tuple[str, str] | None, DroppedPinnedCursor | None]:
    if value is None:
        return None, None
    parsed = _composite_two_tuple(value)
    if parsed is None:
        return None, DroppedPinnedCursor(
            reason=REASON_INVALID_AXIS_IDENTITY,
            index=index,
            detail=type(value).__name__,
        )
    return parsed, None


def _parse_bindings(
    value: Any, *, index: int | None,
) -> tuple[tuple[PinnedCursorBinding, ...], DroppedPinnedCursor | None]:
    if value is None:
        return (), None
    # A mapping is never a binding list — do not flatten via dict(...).
    if isinstance(value, Mapping) or isinstance(value, (str, bytes, bytearray)):
        return (), DroppedPinnedCursor(
            reason=REASON_INVALID_BINDINGS,
            index=index,
            detail=type(value).__name__,
        )
    if not isinstance(value, Sequence):
        return (), DroppedPinnedCursor(
            reason=REASON_INVALID_BINDINGS,
            index=index,
            detail=type(value).__name__,
        )
    out: list[PinnedCursorBinding] = []
    for item in value:
        binding = _parse_binding(item)
        if binding is not None:
            out.append(binding)
    return tuple(out), None


def _parse_binding(value: Any) -> PinnedCursorBinding | None:
    if isinstance(value, PinnedCursorBinding):
        if not value.fid or not value.channel:
            return None
        return value
    fid = channel = binding_id = role = None
    if isinstance(value, Mapping):
        fid = value.get("fid")
        channel = value.get("channel")
        binding_id = value.get("binding_id") or ""
        role = value.get("role") or ""
    elif (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and len(value) == 2
    ):
        fid, channel = value
        binding_id = ""
        role = ""
    else:
        return None
    if fid is None or channel is None:
        return None
    fid_s = str(fid)
    channel_s = str(channel)
    if not fid_s or not channel_s:
        return None
    return PinnedCursorBinding(
        fid=fid_s,
        channel=channel_s,
        binding_id=str(binding_id or ""),
        role=str(role or ""),
    )


def _parse_anchor(value: Any) -> PinnedCursorAnchor:
    if isinstance(value, PinnedCursorAnchor):
        return value
    if not isinstance(value, Mapping):
        return DEFAULT_ANCHOR
    h_edge = value.get("h_edge")
    if h_edge not in _H_EDGES:
        h_edge = DEFAULT_ANCHOR.h_edge
    v_edge = value.get("v_edge")
    if v_edge not in _V_EDGES:
        v_edge = DEFAULT_ANCHOR.v_edge
    nx = _finite_float(value.get("nx"))
    ny = _finite_float(value.get("ny"))
    if nx is None:
        nx = DEFAULT_ANCHOR.nx
    if ny is None:
        ny = DEFAULT_ANCHOR.ny
    return PinnedCursorAnchor(
        h_edge=str(h_edge), v_edge=str(v_edge), nx=nx, ny=ny,
    )


def _composite_two_tuple(value: Any) -> tuple[str, str] | None:
    """Return ``(fid, channel)``. Mappings are not a source identity."""
    if isinstance(value, Mapping):
        return None
    if isinstance(value, (str, bytes, bytearray)):
        return None
    if not isinstance(value, Sequence) or len(value) != 2:
        return None
    fid, channel = value
    if fid is None or channel is None:
        return None
    fid_s = str(fid)
    channel_s = str(channel)
    if not fid_s or not channel_s:
        return None
    return (fid_s, channel_s)


def _remap_intent_fids(
    intent: PinnedCursorIntent,
    fid_map: Mapping[Any, Any],
) -> PinnedCursorIntent | None:
    axis = intent.axis_identity
    if axis is not None:
        if axis[0] not in fid_map:
            return None
        axis = (str(fid_map[axis[0]]), axis[1])
    bindings = tuple(
        replace(item, fid=str(fid_map[item.fid]))
        for item in intent.bindings
        if item.fid in fid_map
    )
    if not bindings:
        return None
    return replace(intent, axis_identity=axis, bindings=bindings)


def _next_ordinal(collection: PinnedCursorCollection) -> int:
    used = [item.ordinal for item in collection.records]
    floor = (max(used) + 1) if used else 1
    current = collection.next_ordinal if collection.next_ordinal >= 1 else 1
    return max(current, floor)


def _read_payload_version(raw: Mapping[str, Any]) -> int | None:
    if "payload_version" in raw:
        value = raw.get("payload_version")
    elif "version" in raw:
        value = raw.get("version")
    else:
        return PAYLOAD_VERSION
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number != int(number):
        return None
    return int(number)


def _coerce_positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number != int(number):
        return None
    parsed = int(number)
    return parsed if parsed >= 1 else None


def _finite_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _uuid_str(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return str(UUID(value.strip()))
    except (TypeError, ValueError):
        return None


def _new_uuid() -> str:
    return str(uuid4())


__all__ = [
    "DEFAULT_ANCHOR",
    "DroppedPinnedCursor",
    "PAYLOAD_VERSION",
    "PIN_DOMAINS",
    "PIN_MODES",
    "PIN_PRESENTATIONS",
    "PinnedCursorAnchor",
    "PinnedCursorBinding",
    "PinnedCursorCollection",
    "PinnedCursorIntent",
    "capture_identity",
    "captures_equal",
    "clear_collection",
    "collection_from_dict",
    "collection_to_dict",
    "coords_equal",
    "duplicate_collection",
    "empty_collection",
    "next_record",
    "normalize_collection",
    "remap_collection_fids",
    "remove_record",
]
