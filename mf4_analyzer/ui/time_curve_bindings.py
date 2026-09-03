"""Generic per-curve X/Y data bindings for time-domain views.

Bindings are UI-neutral: they identify arrays by composite fid/channel or by a
read-only WWT record store on the owner FileData. The canvas never imports
``mf4_analyzer.io.wwt_*``.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from typing import AbstractSet, Any, Iterable, Literal, Mapping, Sequence

import numpy as np

from .time_xaxis import (
    CHANNEL_MODE,
    EXACT_SOURCE,
    PER_SOURCE_NAME,
    CustomXAxisSpec,
    resolve_custom_xaxis,
)

_CHANNEL = "channel"
_WWT_RECORD = "wwt_record"


@dataclass(frozen=True)
class TimePlotIssue:
    code: str
    detail: str
    binding_id: str | None = None


@dataclass
class BoundTimePlotResult:
    """Resolved TimeDomain rows plus the channel keys a binding declared.

    Three-value unpacking yields ``(rows, issues, claimed_channel_keys)`` so
    callers that skip ordinary Time-Y by the third item keep using claimed,
    not only successful, keys.
    """

    rows: list
    issues: list[TimePlotIssue]
    claimed_channel_keys: set[tuple[str, str]]
    successful_channel_keys: set[tuple[str, str]]

    def __iter__(self):
        yield self.rows
        yield self.issues
        yield self.claimed_channel_keys


@dataclass(frozen=True)
class TimeDataRef:
    kind: Literal["channel", "wwt_record"]
    fid: str
    channel: str | None = None
    record_index: int | None = None

    def __post_init__(self) -> None:
        kind = str(self.kind)
        if kind == _CHANNEL:
            if (not self.fid or not self.channel
                    or self.record_index is not None):
                raise ValueError("channel ref requires fid/channel only")
            return
        if kind == _WWT_RECORD:
            if (not self.fid or self.record_index is None
                    or self.channel is not None):
                raise ValueError("wwt_record ref requires fid/record_index only")
            return
        raise ValueError(f"unknown TimeDataRef kind: {self.kind!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "fid": self.fid,
            "channel": self.channel,
            "record_index": self.record_index,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TimeDataRef":
        kind = str(data["kind"])
        record_index = data.get("record_index")
        return cls(
            kind=kind,  # type: ignore[arg-type]
            fid=str(data.get("fid") or ""),
            channel=None if data.get("channel") is None else str(data["channel"]),
            record_index=None if record_index is None else int(record_index),
        )


@dataclass(frozen=True)
class TimeCurveBinding:
    binding_id: str
    y_ref: TimeDataRef
    x_ref: TimeDataRef
    display_name: str
    unit: str
    color: str
    axis_id: str
    y_range: tuple[float, float]
    # Compatibility-only decode fields.  New bindings never produce them and
    # payload generation deliberately does not consume them as display policy.
    y_tick_interval: float | None = None
    y_grid_interval: float | None = None
    line_width_mm: float = 0.0
    line_style: str = "line"

    def to_dict(self) -> dict[str, Any]:
        data = {
            "binding_id": self.binding_id,
            "y_ref": self.y_ref.to_dict(),
            "x_ref": self.x_ref.to_dict(),
            "display_name": self.display_name,
            "unit": self.unit,
            "color": self.color,
            "axis_id": self.axis_id,
            "y_range": [self.y_range[0], self.y_range[1]],
        }
        if self.y_tick_interval is not None:
            data["y_tick_interval"] = self.y_tick_interval
        if self.y_grid_interval is not None:
            data["y_grid_interval"] = self.y_grid_interval
        if self.line_width_mm:
            data["line_width_mm"] = self.line_width_mm
        if self.line_style != "line":
            data["line_style"] = self.line_style
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TimeCurveBinding":
        y_range = data["y_range"]
        lo, hi = float(y_range[0]), float(y_range[1])
        return cls(
            binding_id=str(data["binding_id"]),
            y_ref=TimeDataRef.from_dict(data["y_ref"]),
            x_ref=TimeDataRef.from_dict(data["x_ref"]),
            display_name=str(data.get("display_name") or ""),
            unit=str(data.get("unit") or ""),
            color=str(data.get("color") or ""),
            axis_id=str(data.get("axis_id") or ""),
            y_range=(lo, hi),
            y_tick_interval=_optional_float(data.get("y_tick_interval")),
            y_grid_interval=_optional_float(data.get("y_grid_interval")),
            line_width_mm=float(data.get("line_width_mm") or 0.0),
            line_style=str(data.get("line_style") or "line"),
        )


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def parse_curve_bindings(raw: Any) -> list[TimeCurveBinding]:
    """Best-effort decode; malformed items are dropped, never crash."""
    if not raw:
        return []
    out: list[TimeCurveBinding] = []
    if not isinstance(raw, (list, tuple)):
        return out
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        try:
            out.append(TimeCurveBinding.from_dict(item))
        except (TypeError, ValueError, KeyError, IndexError):
            continue
    return out


def remap_curve_bindings(
    bindings: Sequence[TimeCurveBinding] | Sequence[Mapping[str, Any]],
    fid_map: Mapping[str, str],
) -> list[TimeCurveBinding]:
    """Rewrite both X and Y owner fids. Drop the binding if either is absent."""
    out: list[TimeCurveBinding] = []
    for binding in bindings or ():
        if not isinstance(binding, TimeCurveBinding):
            try:
                binding = TimeCurveBinding.from_dict(binding)
            except (TypeError, ValueError, KeyError, IndexError):
                continue
        if binding.x_ref.fid not in fid_map or binding.y_ref.fid not in fid_map:
            continue
        out.append(
            TimeCurveBinding(
                binding_id=binding.binding_id,
                y_ref=_remap_ref(binding.y_ref, fid_map),
                x_ref=_remap_ref(binding.x_ref, fid_map),
                display_name=binding.display_name,
                unit=binding.unit,
                color=binding.color,
                axis_id=binding.axis_id,
                y_range=binding.y_range,
                y_tick_interval=binding.y_tick_interval,
                y_grid_interval=binding.y_grid_interval,
                line_width_mm=binding.line_width_mm,
                line_style=binding.line_style,
            )
        )
    return out


def _remap_ref(ref: TimeDataRef, fid_map: Mapping[str, str]) -> TimeDataRef:
    return TimeDataRef(
        kind=ref.kind,
        fid=fid_map[ref.fid],
        channel=ref.channel,
        record_index=ref.record_index,
    )


def filter_curve_bindings(
    bindings: Sequence[TimeCurveBinding] | None,
    *,
    removed_fids: Iterable[str] = (),
    removed_channels: Iterable[tuple[str, str]] = (),
) -> list[TimeCurveBinding]:
    removed_fid_set = {str(fid) for fid in removed_fids}
    removed_ch = {
        (str(fid), str(channel)) for fid, channel in removed_channels
    }
    out: list[TimeCurveBinding] = []
    for binding in bindings or ():
        if (
            str(binding.x_ref.fid) in removed_fid_set
            or str(binding.y_ref.fid) in removed_fid_set
        ):
            continue
        if _channel_removed(binding.x_ref, removed_ch):
            continue
        if _channel_removed(binding.y_ref, removed_ch):
            continue
        out.append(binding)
    return out


def prune_hidden_curve_binding_ids(
    hidden_ids: Iterable[str] | None,
    bindings: Sequence[TimeCurveBinding] | None,
) -> list[str]:
    """Drop hidden ids whose bindings no longer exist; keep first-seen order."""
    live = {str(binding.binding_id) for binding in bindings or ()}
    out: list[str] = []
    seen: set[str] = set()
    for item in hidden_ids or ():
        text = str(item)
        if not text or text not in live or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _channel_removed(ref: TimeDataRef, removed: set[tuple[str, str]]) -> bool:
    if ref.kind != _CHANNEL or not ref.channel:
        return False
    return (str(ref.fid), str(ref.channel)) in removed


def collect_dropped_binding_refs(
    bindings: Sequence[Any],
    fid_map: Mapping[str, str],
    *,
    view_id: str,
) -> list[tuple]:
    dropped: list[tuple] = []
    for item in bindings or ():
        try:
            binding = (
                item if isinstance(item, TimeCurveBinding)
                else TimeCurveBinding.from_dict(item)
            )
        except (TypeError, ValueError, KeyError, IndexError):
            continue
        if binding.x_ref.fid not in fid_map:
            dropped.append((view_id, binding.x_ref.fid, "binding:x"))
        if binding.y_ref.fid not in fid_map:
            dropped.append((view_id, binding.y_ref.fid, "binding:y"))
    return dropped


def _record_index_in_store(store: Any, record_index: int) -> bool:
    """True when ``record_index`` names a catalog slot, not necessarily values."""
    try:
        index = int(record_index)
    except (TypeError, ValueError):
        return False
    if store is None:
        return False
    if isinstance(store, Mapping):
        return index in store or str(index) in store
    if isinstance(store, (tuple, list)):
        return 0 <= index < len(store)
    records = getattr(store, "records", None)
    if records is not None:
        return 0 <= index < len(records)
    return _store_values(store, index) is not None


def _wwt_record_present(files: Mapping[str, Any], ref: TimeDataRef) -> bool:
    if getattr(ref, "kind", None) != _WWT_RECORD:
        return True
    if ref.record_index is None:
        return False
    owner = _owner_file(files, str(ref.fid or ""))
    if owner is None:
        return False
    metadata = getattr(owner, "source_metadata", None) or {}
    store = metadata.get("wwt_record_store") if isinstance(metadata, Mapping) else None
    return _record_index_in_store(store, int(ref.record_index))


def drop_missing_wwt_record_bindings(
    bindings: Sequence[TimeCurveBinding] | None,
    files: Mapping[str, Any],
    *,
    view_id: str = "",
) -> tuple[list[TimeCurveBinding], list[tuple]]:
    """Drop wwt_record bindings whose record_index is absent after files load.

    ``remap_curve_bindings`` only rewrites/drops fids. Ghost catalog indices
    must be removed against the live ``wwt_record_store`` so restore cannot
    project a tree row for a record that does not exist.
    """
    kept: list[TimeCurveBinding] = []
    dropped: list[tuple] = []
    for binding in bindings or ():
        missing = False
        for role, ref in (("x", binding.x_ref), ("y", binding.y_ref)):
            if getattr(ref, "kind", None) != _WWT_RECORD:
                continue
            if _wwt_record_present(files, ref):
                continue
            dropped.append(
                (view_id, str(ref.fid or ""), f"binding:record:{role}")
            )
            missing = True
        if not missing:
            kept.append(binding)
    return kept, dropped


def migrate_legacy_channel_bindings(state: Any, files: Mapping[str, Any]) -> list[str]:
    """Move provably ordinary legacy bindings onto the normal View contract.

    This is intentionally a post-load migration: ``ViewState.from_dict`` and
    ``project_io`` only have serialized identities, whereas proving that an
    old binding is equivalent to normal Custom-X needs live columns and the
    active resolver.  Any missing, record-backed, heterogeneous, non-finite,
    or otherwise unprovable row stays as its exact binding.
    """
    bindings = list(getattr(state, "curve_bindings", None) or ())
    if not bindings:
        return []
    axis_opts = getattr(state, "axis_opts", None)
    if not isinstance(axis_opts, dict):
        return []
    x_spec = CustomXAxisSpec.from_axis_opts(axis_opts.get("x_axis"))
    if (
        x_spec.mode != CHANNEL_MODE
        or x_spec.resolver not in {PER_SOURCE_NAME, EXACT_SOURCE}
        or not x_spec.channel
    ):
        return []

    candidates: list[TimeCurveBinding] = []
    kept: list[TimeCurveBinding] = []
    for binding in bindings:
        if _binding_is_normal_custom_x_equivalent(binding, files, x_spec):
            candidates.append(binding)
        else:
            kept.append(binding)
    # The ordinary checked model has one row per composite Y identity.  Leave
    # duplicate or mixed-X legacy bindings exact: moving only one would make a
    # retained binding claim that ordinary row, while moving both would silently
    # collapse two legacy curves into one.
    retained_channel_y = {
        _channel_key(binding.y_ref)
        for binding in kept
        if _channel_key(binding.y_ref) is not None
    }
    candidate_counts: dict[tuple[str, str], int] = {}
    for binding in candidates:
        key = _channel_key(binding.y_ref)
        assert key is not None
        candidate_counts[key] = candidate_counts.get(key, 0) + 1
    migrated: list[TimeCurveBinding] = []
    for binding in candidates:
        key = _channel_key(binding.y_ref)
        assert key is not None
        if key in retained_channel_y or candidate_counts[key] != 1:
            kept.append(binding)
        else:
            migrated.append(binding)
    if not migrated:
        return []

    checked = list(getattr(state, "checked", None) or ())
    checked_keys = {(str(fid), str(channel)) for fid, channel in checked}
    colors = dict(getattr(state, "colors", None) or {})
    ylims = dict(getattr(state, "ylims", None) or {})
    groups = _channel_axis_groups(axis_opts.get("channel_axis_groups"))
    migrated_axis_ids: set[str] = set()
    for binding in migrated:
        assert binding.y_ref.channel is not None
        key = (str(binding.y_ref.fid), str(binding.y_ref.channel))
        if key not in checked_keys:
            checked.append(key)
            checked_keys.add(key)
        if binding.color:
            colors.setdefault(key, binding.color)
        _preserve_binding_ylim(ylims, binding, files)
        if binding.axis_id:
            groups[_encode_channel_key(key)] = binding.axis_id
            migrated_axis_ids.add(str(binding.axis_id))

    # A persisted map carries normal Navigator members only.  A migrated
    # ordinary binding must not manufacture a one-member group unless a
    # retained exact binding or another persisted normal member proves the
    # same axis still has a partner.
    group_counts = Counter(groups.values())
    retained_axis_counts = Counter(
        str(binding.axis_id)
        for binding in kept
        if str(binding.axis_id or "").strip()
    )
    singleton_migrations = {
        axis_id for axis_id in migrated_axis_ids
        if group_counts[axis_id] + retained_axis_counts[axis_id] < 2
    }
    if singleton_migrations:
        groups = {
            key: axis_id for key, axis_id in groups.items()
            if axis_id not in singleton_migrations
        }

    state.checked = checked
    state.colors = colors
    state.ylims = ylims
    state.curve_bindings = kept
    state.hidden_curve_binding_ids = prune_hidden_curve_binding_ids(
        getattr(state, "hidden_curve_binding_ids", None), kept,
    )
    if groups:
        axis_opts["channel_axis_groups"] = groups
    else:
        axis_opts.pop("channel_axis_groups", None)
    state.axis_opts = axis_opts
    return [binding.binding_id for binding in migrated]


def prune_channel_axis_groups_for_live_files(
    state: Any,
    files: Mapping[str, Any],
) -> None:
    """Remove persisted group members whose reloaded channel no longer exists."""
    axis_opts = getattr(state, "axis_opts", None)
    if not isinstance(axis_opts, dict):
        return
    groups = _channel_axis_groups(axis_opts.get("channel_axis_groups"))
    live = {}
    for key, axis_id in groups.items():
        try:
            fid, channel = json.loads(key)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        source = files.get(str(fid))
        data = getattr(source, "data", None)
        columns = getattr(data, "columns", ())
        try:
            present = str(channel) in columns
        except TypeError:
            present = False
        if present:
            live[key] = axis_id
    if live:
        axis_opts["channel_axis_groups"] = live
    else:
        axis_opts.pop("channel_axis_groups", None)
    state.axis_opts = axis_opts


def _binding_is_normal_custom_x_equivalent(
    binding: TimeCurveBinding,
    files: Mapping[str, Any],
    x_spec: CustomXAxisSpec,
) -> bool:
    """True only when normal Custom-X resolves the exact legacy arrays."""
    if binding.x_ref.kind != _CHANNEL or binding.y_ref.kind != _CHANNEL:
        return False
    if not binding.x_ref.channel or not binding.y_ref.channel:
        return False
    if x_spec.resolver == PER_SOURCE_NAME:
        if (
            binding.x_ref.fid != binding.y_ref.fid
            or binding.x_ref.channel != x_spec.channel
        ):
            return False
    elif x_spec.resolver == EXACT_SOURCE:
        if (
            binding.x_ref.fid != x_spec.source_fid
            or binding.x_ref.channel != x_spec.channel
        ):
            return False
    else:
        return False

    binding_x, binding_y, issue = resolve_time_curve_binding(binding, files)
    if issue is not None or binding_x is None or binding_y is None:
        return False
    resolved = resolve_custom_xaxis(
        target_fid=binding.y_ref.fid,
        target_channel=binding.y_ref.channel,
        files=files,
        spec=x_spec,
    )
    if not resolved.ready or resolved.x_values is None:
        return False
    normal_y, normal_y_issue = resolve_time_data_ref(binding.y_ref, files)
    if normal_y_issue is not None or normal_y is None:
        return False
    # Normal Custom-X removes non-finite X entries before drawing.  Preserve
    # exact binding data when that would alter cardinality or array positions.
    try:
        if not np.isfinite(resolved.x_values).all():
            return False
    except TypeError:
        return False
    return (
        _arrays_equal(binding_x, resolved.x_values)
        and _arrays_equal(binding_y, normal_y)
    )


def _arrays_equal(left: np.ndarray, right: np.ndarray) -> bool:
    if left.shape != right.shape:
        return False
    try:
        return bool(np.array_equal(left, right, equal_nan=True))
    except TypeError:
        return bool(np.array_equal(left, right))


def _channel_axis_groups(value: Any) -> dict[str, str]:
    """Keep valid composite-key group entries while a migration appends one."""
    if not isinstance(value, Mapping):
        return {}
    groups: dict[str, str] = {}
    for raw_key, raw_axis_id in value.items():
        if not isinstance(raw_key, str):
            continue
        try:
            key = json.loads(raw_key)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(key, (list, tuple)) or len(key) != 2:
            continue
        fid = str(key[0] or "").strip()
        channel = str(key[1] or "").strip()
        axis_id = str(raw_axis_id or "").strip()
        if fid and channel and axis_id:
            groups[_encode_channel_key((fid, channel))] = axis_id
    return groups


def _encode_channel_key(key: tuple[str, str]) -> str:
    return json.dumps([key[0], key[1]], ensure_ascii=False, separators=(",", ":"))


def _preserve_binding_ylim(
    ylims: dict[str, Any],
    binding: TimeCurveBinding,
    files: Mapping[str, Any],
) -> None:
    try:
        lo, hi = (float(binding.y_range[0]), float(binding.y_range[1]))
    except (IndexError, TypeError, ValueError):
        return
    if not (math.isfinite(lo) and math.isfinite(hi) and hi > lo):
        return
    assert binding.y_ref.channel is not None
    source = files.get(binding.y_ref.fid)
    display_name = binding.y_ref.channel
    prefix = getattr(source, "get_prefixed_channel", None)
    if callable(prefix):
        try:
            display_name = str(prefix(binding.y_ref.channel))
        except (KeyError, TypeError, ValueError):
            return
    ylims.setdefault(
        _encode_channel_key((str(binding.y_ref.fid), display_name)),
        (lo, hi),
    )


def _as_1d(values: Any) -> np.ndarray | None:
    array = np.asarray(values)
    if array.ndim != 1:
        return None
    return array


def _owner_file(files: Mapping[str, Any], fid: str) -> Any | None:
    if not fid:
        return None
    return files.get(fid)


def _store_values(store: Any, record_index: int) -> np.ndarray | None:
    if store is None:
        return None
    item = None
    if isinstance(store, Mapping):
        item = store.get(record_index)
        if item is None:
            item = store.get(str(record_index))
    elif isinstance(store, (tuple, list)):
        if 0 <= record_index < len(store):
            item = store[record_index]
    else:
        getter = getattr(store, "get", None)
        if callable(getter):
            item = getter(record_index)
        else:
            records = getattr(store, "records", None)
            if records is not None and 0 <= record_index < len(records):
                item = records[record_index]
    if item is None:
        return None
    values = getattr(item, "values", item)
    return _as_1d(values)


def resolve_time_data_ref(
    ref: TimeDataRef, files: Mapping[str, Any]
) -> tuple[np.ndarray | None, TimePlotIssue | None]:
    """Return a one-dimensional view, or a structured issue and no array."""
    owner = _owner_file(files, ref.fid)
    if owner is None:
        return None, TimePlotIssue("missing_owner", ref.fid)
    if ref.kind == _CHANNEL:
        data = getattr(owner, "data", None)
        channel = ref.channel
        if data is None or channel is None or channel not in getattr(data, "columns", ()):
            return None, TimePlotIssue(
                "missing_channel", f"{ref.fid}:{channel}"
            )
        values = _as_1d(data[channel])
        if values is None:
            return None, TimePlotIssue(
                "missing_channel", f"{ref.fid}:{channel}"
            )
        return values, None
    metadata = getattr(owner, "source_metadata", None) or {}
    store = metadata.get("wwt_record_store") if isinstance(metadata, Mapping) else None
    values = _store_values(store, int(ref.record_index))
    if values is None:
        return None, TimePlotIssue(
            "missing_record", f"{ref.fid}:{ref.record_index}"
        )
    return values, None


def resolve_time_curve_binding(
    binding: TimeCurveBinding, files: Mapping[str, Any]
) -> tuple[np.ndarray | None, np.ndarray | None, TimePlotIssue | None]:
    x_values, x_issue = resolve_time_data_ref(binding.x_ref, files)
    if x_issue is not None:
        return None, None, TimePlotIssue(
            x_issue.code, x_issue.detail, binding.binding_id
        )
    y_values, y_issue = resolve_time_data_ref(binding.y_ref, files)
    if y_issue is not None:
        return None, None, TimePlotIssue(
            y_issue.code, y_issue.detail, binding.binding_id
        )
    assert x_values is not None and y_values is not None
    if int(x_values.shape[0]) != int(y_values.shape[0]):
        return None, None, TimePlotIssue(
            "unaligned",
            f"{int(x_values.shape[0])},{int(y_values.shape[0])}",
            binding.binding_id,
        )
    return x_values, y_values, None


def _apply_acquisition_mask(
    x_values: np.ndarray,
    y_values: np.ndarray,
    owner: Any,
    range_lo: float | None,
    range_hi: float | None,
) -> tuple[np.ndarray, np.ndarray]:
    if range_lo is None or range_hi is None:
        return x_values, y_values
    time_axis = getattr(owner, "time_array", None)
    if time_axis is None:
        return x_values, y_values
    time_axis = np.asarray(time_axis)
    if time_axis.shape != y_values.shape:
        return x_values, y_values
    mask = (time_axis >= range_lo) & (time_axis <= range_hi)
    return x_values[mask], y_values[mask]


def _channel_key(ref: TimeDataRef) -> tuple[str, str] | None:
    if ref.kind != _CHANNEL or not ref.channel:
        return None
    return (ref.fid, ref.channel)


def bound_time_plot_rows(
    bindings: Sequence[TimeCurveBinding],
    files: Mapping[str, Any],
    *,
    range_lo: float | None = None,
    range_hi: float | None = None,
    checked_channel_keys: AbstractSet[tuple[str, str]] | None = None,
    channel_colors: Mapping[tuple[str, str], str] | None = None,
    hidden_binding_ids: AbstractSet[str] | Iterable[str] | None = None,
) -> BoundTimePlotResult:
    """Resolve bindings to TimeDomain row tuples in binding order.

    A channel-backed Y is claimed before X/Y resolve so a failed or
    unchecked binding cannot fall back to a normal Time-Y curve.
    ``checked_channel_keys=None`` skips Navigator gating.
    """
    rows: list = []
    issues: list[TimePlotIssue] = []
    claimed: set[tuple[str, str]] = set()
    successful: set[tuple[str, str]] = set()
    hidden = {str(item) for item in (hidden_binding_ids or ())}
    for binding in bindings or ():
        if (
            binding.y_ref.kind == _WWT_RECORD
            and str(binding.binding_id) in hidden
        ):
            continue
        y_key = _channel_key(binding.y_ref)
        if y_key is not None:
            claimed.add(y_key)
            if (
                checked_channel_keys is not None
                and y_key not in checked_channel_keys
            ):
                continue
        x_values, y_values, issue = resolve_time_curve_binding(binding, files)
        if issue is not None:
            issues.append(issue)
            continue
        assert x_values is not None and y_values is not None
        native_xy = (
            binding.x_ref.kind == _WWT_RECORD
            or binding.y_ref.kind == _WWT_RECORD
        )
        owner_fid = binding.y_ref.fid
        owner = files.get(owner_fid)
        if not native_xy and owner is not None:
            x_values, y_values = _apply_acquisition_mask(
                x_values, y_values, owner, range_lo, range_hi
            )
        meta = {"axis_group": binding.axis_id}
        if y_key is not None:
            successful.add(y_key)
        color = binding.color
        if y_key is not None and channel_colors is not None:
            color = str(channel_colors.get(y_key) or color)
        row_name = binding.display_name
        if y_key is not None:
            # Canvas/View range identity follows the same raw/prefixed channel
            # name contract as ordinary Navigator rows.  The WinWert display
            # label may contain a unit suffix and is presentation-only; using
            # it here prevents the imported ``(fid, channel)`` Y range from
            # restoring and leaves the axis at the placeholder 0..1 frame.
            row_name = y_key[1]
            prefix = getattr(owner, "get_prefixed_channel", None)
            if callable(prefix):
                row_name = str(prefix(y_key[1]))
        rows.append((
            row_name,
            True,
            x_values,
            y_values,
            color,
            binding.unit,
            owner_fid,
            meta,
        ))
    return BoundTimePlotResult(
        rows=rows,
        issues=issues,
        claimed_channel_keys=claimed,
        successful_channel_keys=successful,
    )
