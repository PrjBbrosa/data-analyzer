"""Generic per-curve X/Y data bindings for time-domain views.

Bindings are UI-neutral: they identify arrays by composite fid/channel or by a
read-only WWT record store on the owner FileData. The canvas never imports
``mf4_analyzer.io.wwt_*``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AbstractSet, Any, Iterable, Literal, Mapping, Sequence

import numpy as np

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
    y_tick_interval: float | None
    y_grid_interval: float | None
    line_width_mm: float
    line_style: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "y_ref": self.y_ref.to_dict(),
            "x_ref": self.x_ref.to_dict(),
            "display_name": self.display_name,
            "unit": self.unit,
            "color": self.color,
            "axis_id": self.axis_id,
            "y_range": [self.y_range[0], self.y_range[1]],
            "y_tick_interval": self.y_tick_interval,
            "y_grid_interval": self.y_grid_interval,
            "line_width_mm": self.line_width_mm,
            "line_style": self.line_style,
        }

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
        meta = {
            "axis_group": binding.axis_id,
            "line_width_mm": binding.line_width_mm,
        }
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
