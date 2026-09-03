"""Translate WinWert display windows into ordinary time-domain View proposals.

Qt-free except for constructing ``ViewState`` (no widgets). Record identity
comes from ``channel_metadata['record_index']``, never from display labels.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from mf4_analyzer.io.wwt_display import WwtCurveDisplay
from mf4_analyzer.io.wwt_document import WwtDocument, WwtRecord
from mf4_analyzer.ui.time_curve_bindings import TimeCurveBinding, TimeDataRef
from mf4_analyzer.ui.time_xaxis import (
    CHANNEL_MODE,
    PER_SOURCE_NAME,
    CustomXAxisSpec,
)
from mf4_analyzer.ui.view_state import ViewState

_UNIT_SUFFIX = re.compile(r"\s*\[[^\]]*\]\s*$")
_MAX_RECORD_WARN = "duplicate_record_index"


@dataclass(frozen=True)
class RegisteredWwtSources:
    owner_fid: str
    fids: tuple[str, ...]
    record_channels: Mapping[int, tuple[str, str]]
    warnings: tuple[str, ...] = ()
    display_channels: Mapping[tuple[str, str], str] = field(default_factory=dict)


@dataclass(frozen=True)
class WwtViewProposal:
    window_index: int
    state: ViewState
    warnings: tuple[str, ...]


def register_groups_for_test(
    groups: Sequence[Mapping], *, owner_fid: str = "f1"
) -> RegisteredWwtSources:
    """Assign deterministic f1, f2, ... in group order (no Qt widgets)."""
    digits = "".join(ch for ch in owner_fid if ch.isdigit())
    prefix = owner_fid[: len(owner_fid) - len(digits)] or "f"
    start = int(digits or "1")
    fids: list[str] = []
    record_channels: dict[int, tuple[str, str]] = {}
    display_channels: dict[tuple[str, str], str] = {}
    warnings: list[str] = []
    for offset, group in enumerate(groups):
        fid = f"{prefix}{start + offset}"
        fids.append(fid)
        metadata = group.get("channel_metadata") or {}
        for column, meta in metadata.items():
            if not isinstance(meta, Mapping) or "record_index" not in meta:
                continue
            record_index = int(meta["record_index"])
            if record_index in record_channels:
                warnings.append(
                    f"{_MAX_RECORD_WARN}: {record_index}"
                )
                continue
            channel = str(column)
            record_channels[record_index] = (fid, channel)
            display_channels[(fid, channel)] = channel
    return RegisteredWwtSources(
        owner_fid=fids[0] if fids else owner_fid,
        fids=tuple(fids),
        record_channels=record_channels,
        warnings=tuple(warnings),
        display_channels=display_channels,
    )


def build_registered_record_map(
    groups: Sequence[Mapping], fids: Sequence[str]
) -> RegisteredWwtSources:
    if not fids:
        raise ValueError("registered WWT sources require at least one fid")
    record_channels: dict[int, tuple[str, str]] = {}
    display_channels: dict[tuple[str, str], str] = {}
    warnings: list[str] = []
    for fid, group in zip(fids, groups):
        metadata = group.get("channel_metadata") or {}
        display_names = group.get("channel_display_names") or {}
        for column, meta in metadata.items():
            if not isinstance(meta, Mapping) or "record_index" not in meta:
                continue
            record_index = int(meta["record_index"])
            if record_index in record_channels:
                warnings.append(f"{_MAX_RECORD_WARN}: {record_index}")
                continue
            source_fid = str(fid)
            channel = str(column)
            record_channels[record_index] = (source_fid, channel)
            display_channels[(source_fid, channel)] = str(
                display_names.get(column) or channel
            )
    return RegisteredWwtSources(
        owner_fid=str(fids[0]),
        fids=tuple(str(fid) for fid in fids),
        record_channels=record_channels,
        warnings=tuple(warnings),
        display_channels=display_channels,
    )


def attach_wwt_record_store(
    groups: Sequence[dict], document: WwtDocument
) -> None:
    """Share the immutable record tuple on every logical source."""
    from mf4_analyzer.io.wwt_document import (
        attach_wwt_record_store as _attach_store,
    )

    _attach_store(groups, document.records)


def _label_without_unit(label: str) -> str:
    return _UNIT_SUFFIX.sub("", label or "").strip()


def _ylim_key(key: tuple[str, str]) -> str:
    return json.dumps([key[0], key[1]], ensure_ascii=False, separators=(",", ":"))


def _rgb_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{int(rgb[0]) & 0xFF:02x}{int(rgb[1]) & 0xFF:02x}{int(rgb[2]) & 0xFF:02x}"


def _curve_unit(curve: WwtCurveDisplay, records: Sequence[WwtRecord]) -> str:
    if 0 <= curve.record_index < len(records):
        unit = (records[curve.record_index].unit or "").strip()
        if unit:
            return unit
    match = re.search(r"\[([^\]]+)\]\s*$", curve.label or "")
    return (match.group(1) if match else "").strip()


# Axis-compatibility only. Degree sign ≡ ``deg`` as a unit token so
# ``°/s`` shares a slot with ``deg/s``. Display strings stay original.
_DEGREE_SIGN = "\u00b0"


def _norm_unit(unit: str) -> str:
    text = (unit or "").strip().casefold()
    return text.replace(_DEGREE_SIGN, "deg")


def _range_ok(lo: float, hi: float) -> bool:
    return (
        lo == lo and hi == hi  # not NaN
        and abs(lo) != float("inf") and abs(hi) != float("inf")
        and hi > lo
    )


def _record_finite_span(record: WwtRecord | None) -> tuple[float, float] | None:
    if record is None or record.values is None:
        return None
    finite = [
        float(value) for value in record.values
        if value == value and abs(value) != float("inf")
    ]
    if len(finite) < 2:
        return None
    lo, hi = min(finite), max(finite)
    if not (hi > lo):
        return None
    return lo, hi


def _ranges_overlap(left: tuple[float, float], right: tuple[float, float]) -> bool:
    return max(left[0], right[0]) < min(left[1], right[1])


def _initial_xlim(
    x_row, records: Sequence[WwtRecord], *, window_index: int, warnings: list[str],
) -> tuple[float, float] | None:
    """Keep a valid file-specified initial X range without a native mode."""
    initial = None
    if x_row is not None and _range_ok(x_row.lo, x_row.hi):
        initial = (float(x_row.lo), float(x_row.hi))
    elif x_row is not None:
        warnings.append(f"native_x_range_invalid: window {window_index + 1}")
        return None
    if initial is None:
        return None
    span = None
    if 0 <= int(x_row.x_record_index) < len(records):
        span = _record_finite_span(records[x_row.x_record_index])
    if span is not None and not _ranges_overlap(initial, span):
        warnings.append(f"native_x_range_no_overlap: window {window_index + 1}")
        return None
    return initial


def _data_ref(
    record_index: int,
    registered: RegisteredWwtSources,
) -> TimeDataRef:
    mapped = registered.record_channels.get(record_index)
    if mapped is not None:
        fid, channel = mapped
        return TimeDataRef(kind="channel", fid=fid, channel=channel)
    return TimeDataRef(
        kind="wwt_record",
        fid=registered.owner_fid,
        record_index=record_index,
    )


def _compatible_axis(curve: WwtCurveDisplay, owner: WwtCurveDisplay, unit: str, owner_unit: str) -> bool:
    if _norm_unit(unit) != _norm_unit(owner_unit):
        return False
    return curve.lo == owner.lo and curve.hi == owner.hi


def _plan_axes(
    visible: Sequence[WwtCurveDisplay],
    records: Sequence[WwtRecord],
    window_index: int,
) -> tuple[dict[int, str], tuple[str, ...]]:
    """Map visible Y record_index → axis_id."""
    selected = [row for row in visible if row.selected]
    axis_of: dict[int, str] = {}
    warnings: list[str] = []
    owners: list[WwtCurveDisplay] = []
    for row in selected:
        axis_id = f"window-{window_index}-axis-{row.record_index}"
        axis_of[row.record_index] = axis_id
        owners.append(row)
    for row in visible:
        if row.record_index in axis_of:
            continue
        match = None
        for owner in owners:
            if _compatible_axis(
                row,
                owner,
                _curve_unit(row, records),
                _curve_unit(owner, records),
            ):
                match = owner
                break
        if match is not None:
            axis_of[row.record_index] = axis_of[match.record_index]
        else:
            axis_id = f"window-{window_index}-axis-{row.record_index}"
            axis_of[row.record_index] = axis_id
            warnings.append(
                f"hidden_axis: window {window_index + 1} record {row.record_index}"
            )
    return axis_of, tuple(warnings)


def _y_visible_rows(window) -> list[WwtCurveDisplay]:
    rows = list(window.curves)
    y_rows = rows[1:] if rows else []
    return [row for row in y_rows if row.visible]


def visible_y_windows(document) -> list:
    """Structurally valid display windows that contain at least one visible Y."""
    windows = getattr(document, "windows", ()) or ()
    return [window for window in windows if _y_visible_rows(window)]


def _x_axis_opts(ordinary_x_channel: str | None, x_label: str) -> dict:
    """Build one honest View-wide Custom-X spec for ordinary curves only."""
    if ordinary_x_channel:
        return CustomXAxisSpec(
            mode=CHANNEL_MODE,
            resolver=PER_SOURCE_NAME,
            source_fid=None,
            channel=str(ordinary_x_channel),
            label=str(x_label or ""),
        ).to_axis_opts()
    return {"mode": "time", "label": str(x_label or "")}


def _ordinary_channel_record_indexes(
    rows: Sequence[tuple[WwtCurveDisplay, TimeDataRef, TimeDataRef]],
    *,
    preferred_x_channel: str | None = None,
) -> tuple[set[int], str | None]:
    """Classify rows that ordinary TimeDomain data can represent exactly.

    A single View-wide Custom-X spec can only name one channel.  Record-backed
    X/Y stay as exact bindings.  When channel rows contain one exceptional X,
    the WinWert window header is the explicit owner of the normal View-wide X:
    rows matching that channel remain ordinary and only the exception stays an
    exact binding.  If the header cannot prove one owner, heterogeneous channel
    X remains fail-closed as exact bindings.  Axis sharing is intentionally not
    part of this classification: it is a display grouping, not data identity.
    """
    channel_rows = [
        (row, y_ref, x_ref)
        for row, y_ref, x_ref in rows
        if (
            y_ref.kind == "channel"
            and x_ref.kind == "channel"
            and x_ref.channel
            and x_ref.fid == y_ref.fid
        )
    ]
    x_channels = {str(x_ref.channel) for _row, _y_ref, x_ref in channel_rows}
    ordinary_x_channel = None
    if len(x_channels) == 1:
        ordinary_x_channel = next(iter(x_channels))
    else:
        preferred = str(preferred_x_channel or "").strip()
        if preferred in x_channels:
            ordinary_x_channel = preferred
    if ordinary_x_channel is None:
        return set(), None
    ordinary = {
        row.record_index
        for row, _y_ref, x_ref in channel_rows
        if str(x_ref.channel) == ordinary_x_channel
    }
    if not ordinary:
        return set(), None
    return ordinary, ordinary_x_channel


def _ordinary_channel_axis_groups(
    rows: Sequence[tuple[WwtCurveDisplay, TimeDataRef, TimeDataRef]],
    ordinary_records: set[int],
    axis_of: Mapping[int, str],
) -> dict[str, str]:
    """Persist only ordinary channel membership for shared initial Y axes.

    Keys are JSON composite channel identities, matching the other persisted
    ViewState tables.  The mapping has no tick, grid, range, or WWT-policy
    fact; Task 2 restores it through the existing channel-tree axis-group
    owner.  Keep a group whenever its source WWT axis contains more than one
    visible curve, including a record-only sibling, so a mixed curve set has
    enough information to rejoin ordinary and exceptional rows.
    """
    member_counts: dict[str, int] = {}
    for row, _y_ref, _x_ref in rows:
        axis_id = axis_of[row.record_index]
        member_counts[axis_id] = member_counts.get(axis_id, 0) + 1
    groups: dict[str, str] = {}
    for row, y_ref, _x_ref in rows:
        if (
            row.record_index not in ordinary_records
            or not y_ref.fid
            or not y_ref.channel
        ):
            continue
        axis_id = axis_of[row.record_index]
        if member_counts.get(axis_id, 0) < 2:
            continue
        groups[_ylim_key((y_ref.fid, y_ref.channel))] = axis_id
    return groups


def build_wwt_view_proposals(
    document: WwtDocument,
    registered: RegisteredWwtSources,
) -> list[WwtViewProposal]:
    records = document.records
    proposals: list[WwtViewProposal] = []
    shared_warnings = list(registered.warnings)
    for window in document.windows:
        warnings = list(shared_warnings)
        visible = []
        source_visible = _y_visible_rows(window)
        for row in source_visible:
            if row.record_index < 0 or row.record_index >= len(records):
                warnings.append(
                    f"unknown_record: window {window.index + 1} "
                    f"record {row.record_index}"
                )
                warnings.append(
                    f"dropped_curve: window {window.index + 1} "
                    f"record {row.record_index}"
                )
                continue
            if row.factor != 1.0 or row.move != 0.0 or row.log_scale:
                warnings.append(
                    f"unsupported_display: window {window.index + 1} "
                    f"record {row.record_index}"
                )
            if row.representation != 0:
                warnings.append(
                    f"unsupported_representation: window {window.index + 1} "
                    f"record {row.record_index}"
                )
            visible.append(row)
        if not visible:
            # Empty windows (no visible Y) generate nothing and are not
            # dropped_window.  A window whose visible Y rows all failed to
            # bind is a real degradation.
            if source_visible:
                warnings.append(
                    f"dropped_window: window {window.index + 1}"
                )
                for text in warnings:
                    if text not in shared_warnings:
                        shared_warnings.append(text)
            continue
        axis_of, axis_warnings = _plan_axes(visible, records, window.index)
        warnings.extend(axis_warnings)
        x_row = window.curves[0] if window.curves else None
        x_label = x_row.label if x_row is not None else ""
        name = f"WinWert {window.index + 1} · {_label_without_unit(x_label)}"
        xlim = _initial_xlim(
            x_row, records, window_index=window.index, warnings=warnings,
        )
        resolved = [
            (row, _data_ref(row.record_index, registered), _data_ref(row.x_record_index, registered))
            for row in visible
        ]
        ordinary_records, ordinary_x_channel = _ordinary_channel_record_indexes(
            resolved,
            preferred_x_channel=_label_without_unit(x_label),
        )
        channel_axis_groups = _ordinary_channel_axis_groups(
            resolved, ordinary_records, axis_of,
        )
        bindings: list[TimeCurveBinding] = []
        checked: list[tuple[str, str]] = []
        colors: dict[tuple[str, str], str] = {}
        ylims: dict[str, tuple[float, float]] = {}
        for row, y_ref, x_ref in resolved:
            color = _rgb_hex(row.color_rgb)
            axis_id = axis_of[row.record_index]
            y_range = (float(row.lo), float(row.hi)) if _range_ok(row.lo, row.hi) else (0.0, 1.0)
            if not _range_ok(row.lo, row.hi):
                warnings.append(
                    f"auto_range: window {window.index + 1} record {row.record_index}"
                )
            if row.record_index not in ordinary_records:
                bindings.append(
                    TimeCurveBinding(
                        binding_id=f"window-{window.index}-record-{row.record_index}",
                        y_ref=y_ref,
                        x_ref=x_ref,
                        display_name=row.label,
                        unit=_curve_unit(row, records),
                        color=color,
                        axis_id=axis_id,
                        y_range=y_range,
                    )
                )
            if y_ref.kind == "channel" and y_ref.channel:
                key = (y_ref.fid, y_ref.channel)
                if key not in checked:
                    checked.append(key)
                colors[key] = color
                if (
                    row.record_index in ordinary_records
                    and row.selected
                    and _range_ok(row.lo, row.hi)
                ):
                    display_name = registered.display_channels.get(key, key[1])
                    ylims[_ylim_key((key[0], display_name))] = (
                        float(row.lo), float(row.hi)
                    )
        axis_opts = {"x_axis": _x_axis_opts(ordinary_x_channel, x_label)}
        if channel_axis_groups:
            axis_opts["channel_axis_groups"] = channel_axis_groups
        state = ViewState(
            name=name,
            tab_color="",
            attached_file_ids=list(registered.fids),
            checked=checked,
            colors=colors,
            plot_mode="overlay",
            xlim=xlim,
            ylims=ylims,
            axis_opts=axis_opts,
            curve_bindings=bindings,
        )
        proposals.append(
            WwtViewProposal(
                window_index=window.index,
                state=state,
                warnings=tuple(dict.fromkeys(warnings)),
            )
        )
    return proposals
