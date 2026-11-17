"""Pure contracts for TimeDomain channel-backed X axes.

This module deliberately has no Qt dependency.  It is shared by the
Inspector selection, View/project persistence and the TimeDomain payload
builder so those callers cannot grow different interpretations of a custom X
axis.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

import numpy as np

from ..db_reference import normalize_unit


TIME_MODE = "time"
CHANNEL_MODE = "channel"
PER_SOURCE_NAME = "per_source_name"
EXACT_SOURCE = "exact_source"
LABEL_ORIGIN_AUTO = "auto"
LABEL_ORIGIN_USER = "user"

SelectionPayload = tuple[str, str | None, str]


@dataclass(frozen=True)
class CursorXAxisContext:
    """Explicit TimeDomain cursor X-axis identity. Display labels are not keys."""

    mode: str = TIME_MODE
    identity: object = None
    label: str = ""
    unit: str = ""

    @property
    def is_channel(self) -> bool:
        return self.mode == CHANNEL_MODE


@dataclass(frozen=True)
class CustomXAxisSpec:
    """Applied custom-X state, independent of the Inspector draft widgets."""

    mode: str = TIME_MODE
    resolver: str | None = None
    channel: str | None = None
    source_fid: str | None = None
    label: str = ""
    label_origin: str = LABEL_ORIGIN_USER

    @classmethod
    def from_axis_opts(cls, payload: Mapping[str, Any] | None) -> "CustomXAxisSpec":
        """Decode persisted ``axis_opts['x_axis']`` with legacy migration.

        A legacy channel payload has no ``resolver`` and therefore retains its
        historical exact-source meaning.  Unknown or incomplete payloads fail
        closed to the time axis instead of guessing a source.
        """
        values = dict(payload or {})
        mode = str(values.get("mode", TIME_MODE) or TIME_MODE).strip()
        label = str(values.get("label", "") or "")
        if mode != CHANNEL_MODE:
            return cls(mode=TIME_MODE, label=label)

        channel = str(values.get("channel", "") or "").strip()
        if not channel:
            return cls(mode=TIME_MODE, label=label)

        # ``label_origin`` was added after channel-backed X axes shipped.
        # Only legacy payloads lack it, so compatibility inference is confined
        # here.  New apply/capture paths must persist the explicit value.
        raw_origin = str(values.get("label_origin", "") or "").strip()
        if raw_origin in {LABEL_ORIGIN_AUTO, LABEL_ORIGIN_USER}:
            label_origin = raw_origin
        else:
            label_origin = (
                LABEL_ORIGIN_AUTO
                if not label or label == channel
                else LABEL_ORIGIN_USER
            )

        raw_resolver = values.get("resolver")
        resolver = (
            EXACT_SOURCE
            if raw_resolver is None and values.get("fid") is not None
            else str(raw_resolver or "").strip()
        )
        if resolver == PER_SOURCE_NAME:
            return cls(
                mode=CHANNEL_MODE,
                resolver=PER_SOURCE_NAME,
                channel=channel,
                source_fid=None,
                label=label,
                label_origin=label_origin,
            )
        if resolver == EXACT_SOURCE:
            source_fid = str(values.get("fid", "") or "").strip()
            if source_fid:
                return cls(
                    mode=CHANNEL_MODE,
                    resolver=EXACT_SOURCE,
                    channel=channel,
                    source_fid=source_fid,
                    label=label,
                    label_origin=label_origin,
                )
        return cls(mode=TIME_MODE, label=label)

    def to_axis_opts(self) -> dict[str, Any]:
        """Encode the canonical persistence shape from the implementation plan."""
        if (
            self.mode == CHANNEL_MODE
            and self.resolver == PER_SOURCE_NAME
            and self.channel
        ):
            return {
                "mode": CHANNEL_MODE,
                "resolver": PER_SOURCE_NAME,
                "fid": None,
                "channel": str(self.channel),
                "label": str(self.label or ""),
                "label_origin": self.label_origin,
            }
        if (
            self.mode == CHANNEL_MODE
            and self.resolver == EXACT_SOURCE
            and self.source_fid
            and self.channel
        ):
            return {
                "mode": CHANNEL_MODE,
                "resolver": EXACT_SOURCE,
                "fid": str(self.source_fid),
                "channel": str(self.channel),
                "label": str(self.label or ""),
                "label_origin": self.label_origin,
            }
        return {
            "mode": TIME_MODE,
            "resolver": None,
            "fid": None,
            "channel": None,
            "label": str(self.label or ""),
        }


@dataclass(frozen=True)
class TimePlotIssue:
    """One machine-readable, source-specific reason a curve was not plotted."""

    code: str
    source_fid: str
    source_label: str
    target_channel: str
    x_channel: str
    detail: str = ""


@dataclass(frozen=True)
class CustomXResolution:
    """Result of resolving one target curve's channel-backed X array."""

    source_fid: str
    source_label: str
    target_channel: str
    x_channel: str
    ready: bool
    x_values: np.ndarray | None = None
    unit: str = ""
    issue: TimePlotIssue | None = None
    # Acquisition time of the Y samples. Native curves carry their own clock.
    # Legacy tables leave this empty and keep masking on ``time_array``.
    sample_time: np.ndarray | None = None

    @property
    def issue_code(self) -> str | None:
        return self.issue.code if self.issue is not None else None

    @property
    def detail(self) -> str:
        return self.issue.detail if self.issue is not None else ""


def selection_payload(spec: CustomXAxisSpec) -> SelectionPayload | None:
    """Return the Inspector's tagged triple for an applied channel spec."""
    if spec.mode != CHANNEL_MODE or not spec.channel:
        return None
    if spec.resolver == PER_SOURCE_NAME:
        return (PER_SOURCE_NAME, None, str(spec.channel))
    if spec.resolver == EXACT_SOURCE and spec.source_fid:
        return (EXACT_SOURCE, str(spec.source_fid), str(spec.channel))
    return None


def spec_from_selection(
    payload: object,
    *,
    label: str = "",
    label_origin: str = LABEL_ORIGIN_USER,
) -> CustomXAxisSpec:
    """Decode one tagged Inspector triple, failing closed to ``time``."""
    if not isinstance(payload, (tuple, list)) or len(payload) != 3:
        return CustomXAxisSpec(mode=TIME_MODE, label=str(label or ""))
    resolver, source_fid, channel = payload
    channel = str(channel or "").strip()
    if resolver == PER_SOURCE_NAME and source_fid is None and channel:
        return CustomXAxisSpec(
            mode=CHANNEL_MODE,
            resolver=PER_SOURCE_NAME,
            channel=channel,
            source_fid=None,
            label=str(label or ""),
            label_origin=label_origin,
        )
    if resolver == EXACT_SOURCE and source_fid and channel:
        return CustomXAxisSpec(
            mode=CHANNEL_MODE,
            resolver=EXACT_SOURCE,
            channel=channel,
            source_fid=str(source_fid),
            label=str(label or ""),
            label_origin=label_origin,
        )
    return CustomXAxisSpec(mode=TIME_MODE, label=str(label or ""))


def channel_unit(source: object, channel: str) -> str:
    """Return a channel unit, preferring metadata over the legacy unit map."""
    metadata = (getattr(source, "channel_metadata", None) or {}).get(
        channel, {}
    ) or {}
    return str(
        metadata.get("unit")
        or (getattr(source, "channel_units", None) or {}).get(channel, "")
        or ""
    ).strip()


def _source_label(source: object, fid: str) -> str:
    return str(
        getattr(source, "short_name", "")
        or getattr(source, "filename", "")
        or fid
    )


def _column(source: object, channel: str) -> object | None:
    data = getattr(source, "data", None)
    if data is None:
        return None
    columns = getattr(data, "columns", data)
    try:
        if channel not in columns:
            return None
        return data[channel]
    except (KeyError, TypeError):
        return None


def _one_dimensional_array(values: object, *, numeric: bool) -> np.ndarray | None:
    try:
        if hasattr(values, "to_numpy"):
            values = values.to_numpy(copy=False)
        array = np.asarray(values, dtype=float if numeric else None)
    except (TypeError, ValueError):
        return None
    if array.ndim != 1:
        return None
    return array


def _failed_resolution(
    *,
    code: str,
    target_fid: str,
    source_label: str,
    target_channel: str,
    x_channel: str,
    detail: str,
    unit: str = "",
) -> CustomXResolution:
    issue = TimePlotIssue(
        code=code,
        source_fid=target_fid,
        source_label=source_label,
        target_channel=target_channel,
        x_channel=x_channel,
        detail=detail,
    )
    return CustomXResolution(
        source_fid=target_fid,
        source_label=source_label,
        target_channel=target_channel,
        x_channel=x_channel,
        ready=False,
        unit=unit,
        issue=issue,
    )


def resolve_custom_xaxis(
    *,
    target_fid: str,
    target_channel: str,
    files: Mapping[str, object],
    spec: CustomXAxisSpec,
) -> CustomXResolution:
    """Resolve one target curve's X array under the fixed resolver semantics.

    ``per_source_name`` looks up the X channel in ``target_fid``.
    ``exact_source`` always reads ``spec.source_fid`` and never substitutes a
    same-named channel from the target source.
    """
    target_fid = str(target_fid)
    target_channel = str(target_channel)
    target_source = files.get(target_fid)
    target_label = _source_label(target_source, target_fid) if target_source else target_fid
    x_channel = str(spec.channel or "")

    if target_source is None:
        return _failed_resolution(
            code="missing_target_source",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail="目标数据源已不存在",
        )
    x_fid = target_fid if spec.resolver == PER_SOURCE_NAME else spec.source_fid
    x_source = files.get(str(x_fid)) if x_fid is not None else None
    if _is_native_file(target_source) or _is_native_file(x_source):
        return _resolve_native_custom_x(
            target_fid=target_fid,
            target_channel=target_channel,
            target_source=target_source,
            target_label=target_label,
            x_channel=x_channel,
            x_source=x_source,
            spec=spec,
        )

    y_values = _one_dimensional_array(
        _column(target_source, target_channel), numeric=False
    )
    if y_values is None:
        return _failed_resolution(
            code="missing_target_channel",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail="目标通道已不存在或不是一维数据",
        )

    if spec.mode != CHANNEL_MODE or spec.resolver not in {
        PER_SOURCE_NAME,
        EXACT_SOURCE,
    }:
        return _failed_resolution(
            code="invalid_xaxis_spec",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail="横坐标选择无效",
        )

    x_fid = target_fid if spec.resolver == PER_SOURCE_NAME else spec.source_fid
    x_source = files.get(str(x_fid)) if x_fid is not None else None
    if x_source is None:
        return _failed_resolution(
            code="missing_x_source",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail="横坐标数据源已不存在",
        )

    raw_x = _column(x_source, x_channel)
    if raw_x is None:
        return _failed_resolution(
            code="missing_x_channel",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail=f"缺少横坐标通道 {x_channel}",
        )
    x_values = _one_dimensional_array(raw_x, numeric=True)
    unit = channel_unit(x_source, x_channel)
    if x_values is None:
        return _failed_resolution(
            code="non_finite_x",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail="横坐标通道不是可绘制的一维数值",
            unit=unit,
        )
    if len(x_values) != len(y_values):
        return _failed_resolution(
            code="unaligned",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail=f"X/Y 长度不一致（{len(x_values)}/{len(y_values)}）",
            unit=unit,
        )
    if not np.isfinite(x_values).any():
        return _failed_resolution(
            code="non_finite_x",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail="横坐标通道没有有限数值",
            unit=unit,
        )

    return CustomXResolution(
        source_fid=target_fid,
        source_label=target_label,
        target_channel=target_channel,
        x_channel=x_channel,
        ready=True,
        x_values=x_values,
        unit=unit,
    )


def apply_unit_cohort(
    resolutions: Sequence[CustomXResolution],
) -> tuple[CustomXResolution, ...]:
    """Keep the largest normalized-unit cohort, preserving stable order.

    Equal-sized cohorts are resolved by first appearance in ``resolutions``.
    Empty units are ordinary normalized facts, not a wildcard.
    """
    groups: dict[str, list[int]] = {}
    for index, result in enumerate(resolutions):
        if result.ready:
            groups.setdefault(normalize_unit(result.unit), []).append(index)
    if not groups:
        return tuple(resolutions)

    selected_unit = max(groups, key=lambda key: len(groups[key]))
    selected = set(groups[selected_unit])
    output = []
    for index, result in enumerate(resolutions):
        if not result.ready or index in selected:
            output.append(result)
            continue
        issue = TimePlotIssue(
            code="x_unit_incompatible",
            source_fid=result.source_fid,
            source_label=result.source_label,
            target_channel=result.target_channel,
            x_channel=result.x_channel,
            detail=(
                f"横坐标单位 {result.unit or '空'} 与当前共享坐标轴不兼容"
            ),
        )
        output.append(
            replace(result, ready=False, x_values=None, issue=issue)
        )
    return tuple(output)


def _is_native_file(source) -> bool:
    return getattr(source, "native_store", None) is not None


def _axis_id(source, channel: str):
    metadata = (getattr(source, "channel_metadata", None) or {}).get(channel) or {}
    if not isinstance(metadata, Mapping):
        return None
    axis_id = metadata.get("axis_id")
    return str(axis_id) if axis_id else None


def _times_prove_relationship(y_series, x_series, y_source, x_source, y_name, x_name) -> bool:
    """Same clock, or pointwise-equal timestamps. Equal length is not proof."""
    y_axis = _axis_id(y_source, y_name)
    x_axis = _axis_id(x_source, x_name)
    if y_source is x_source and y_axis and y_axis == x_axis:
        return True
    y_time = np.asarray(y_series.time)
    x_time = np.asarray(x_series.time)
    if y_time.shape != x_time.shape:
        return False
    return bool(np.array_equal(y_time, x_time))


def _resolve_native_custom_x(
    *,
    target_fid,
    target_channel,
    target_source,
    target_label,
    x_channel,
    x_source,
    spec,
):
    from ..io.file_data import SourceClosedError
    from ..io.signal_access import SignalAccessError, read_signal

    if spec.mode != CHANNEL_MODE or spec.resolver not in {PER_SOURCE_NAME, EXACT_SOURCE}:
        return _failed_resolution(
            code="invalid_xaxis_spec",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail="横坐标选择无效",
        )
    if x_source is None:
        return _failed_resolution(
            code="missing_x_source",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail="横坐标数据源已不存在",
        )
    try:
        y_series = read_signal(target_source, target_channel)
    except (SignalAccessError, SourceClosedError, TypeError):
        return _failed_resolution(
            code="missing_target_channel",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail="目标通道已不存在或不是一维数据",
        )
    try:
        x_series = read_signal(x_source, x_channel)
    except (SignalAccessError, SourceClosedError, TypeError):
        return _failed_resolution(
            code="missing_x_channel",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail=f"缺少横坐标通道 {x_channel}",
        )
    unit = str(x_series.unit or "")
    if int(x_series.values.shape[0]) != int(y_series.values.shape[0]):
        return _failed_resolution(
            code="unaligned",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail=(
                f"X/Y 长度不一致（{x_series.values.shape[0]}/{y_series.values.shape[0]}）"
            ),
            unit=unit,
        )
    if not _times_prove_relationship(
        y_series, x_series, target_source, x_source, target_channel, x_channel,
    ):
        return _failed_resolution(
            code="time_relationship_required",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail="点数相同不能证明同步，需要显式时间关系",
            unit=unit,
        )
    x_values = np.asarray(x_series.values)
    if x_values.dtype.kind not in "biufc" or not np.isfinite(np.asarray(x_values, dtype=float)).any():
        return _failed_resolution(
            code="non_finite_x",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail="横坐标通道没有有限数值",
            unit=unit,
        )
    return CustomXResolution(
        source_fid=target_fid,
        source_label=target_label,
        target_channel=target_channel,
        x_channel=x_channel,
        ready=True,
        x_values=x_values,
        unit=unit,
        sample_time=np.asarray(y_series.time),
    )


@dataclass(frozen=True)
class NativeCursorReading:
    """One native cursor answer. Values come from the raw series, not an envelope."""

    status: str
    value: float | None = None
    sample_time: float | None = None
    delta_s: float | None = None
    record_indices: tuple = ()
    text: str = ""


def _none_reading() -> NativeCursorReading:
    return NativeCursorReading(status="none", text="无数据")


def _record_index(position, index_base, sample_index) -> int:
    if sample_index is not None:
        return int(sample_index[position])
    return int(index_base) + int(position)


def _series_arrays(series):
    time = np.asarray(series.time)
    values = np.asarray(series.values)
    validity = getattr(series, "validity", None)
    if validity is not None:
        validity = np.asarray(validity, dtype=bool)
    segments = tuple(getattr(series, "segments", ()) or ())
    if not segments and int(time.shape[0]):
        from ..io.native_signal_store import build_segments

        segments = build_segments(time)
    index_base = getattr(series, "index_start", None)
    if index_base is None:
        index_base = 0
    return time, values, validity, segments, int(index_base), getattr(series, "sample_index", None)


def _value_invalid(position, values, validity) -> bool:
    if validity is not None and bool(validity[position]):
        return True
    try:
        return not bool(np.isfinite(values[position]))
    except (TypeError, ValueError):
        return True


def _distance_tie(left, right, query) -> bool:
    tol = max(1e-12, 1e-9 * max(1.0, abs(query)))
    return abs(left - right) <= tol


def _format_delta(delta: float) -> str:
    if abs(delta) < 1.0:
        millis = delta * 1000.0
        if abs(millis - round(millis)) <= 1e-6:
            return f"Δt={int(round(millis))}ms"
        return f"Δt={millis:.4g}ms"
    return f"Δt={delta:.4g}s"


def _format_stamp(sample_time: float) -> str:
    return f"{sample_time:.3f}s"


def _segment_candidates(time, values, validity, segment, query):
    if segment.has_nonfinite_time or segment.stop <= segment.start:
        return []
    part = time[segment.start:segment.stop]
    if int(part.shape[0]) == 0 or not np.isfinite(part[0]) or not np.isfinite(part[-1]):
        return []
    lo = float(part[0])
    hi = float(part[-1])
    if query < lo or query > hi:
        return []
    if int(part.shape[0]) == 1:
        index = segment.start
        if query == lo and not _value_invalid(index, values, validity):
            return [index]
        return []
    right = int(np.searchsorted(part, query, side="left"))
    neighbors = []
    if right < int(part.shape[0]):
        neighbors.append(segment.start + right)
    if right > 0:
        neighbors.append(segment.start + right - 1)
    exact = [
        index for index in neighbors
        if np.isfinite(time[index]) and float(time[index]) == query
    ]
    if exact:
        anchor = exact[0]
        stamp = time[anchor]
        cursor = anchor
        while cursor > segment.start and time[cursor - 1] == stamp:
            cursor -= 1
        found = []
        while cursor < segment.stop and time[cursor] == stamp:
            if np.isfinite(time[cursor]) and not _value_invalid(cursor, values, validity):
                found.append(cursor)
            cursor += 1
        return found
    usable = []
    for index in neighbors:
        if not np.isfinite(time[index]) or _value_invalid(index, values, validity):
            continue
        usable.append(index)
    return usable


def _choose_hits(time, hits, query):
    if not hits:
        return []
    distances = [abs(float(time[index]) - query) for index in hits]
    best = min(distances)
    tied = [
        index for index, distance in zip(hits, distances)
        if _distance_tie(distance, best, query)
    ]
    earliest = min(float(time[index]) for index in tied)
    chosen = [
        index for index in tied
        if _distance_tie(float(time[index]), earliest, query)
    ]
    chosen.sort()
    return chosen


def _reading_for(time, values, chosen, query, index_base, sample_index, *, status):
    indices = tuple(
        _record_index(index, index_base, sample_index) for index in chosen
    )
    if status == "multiple" or (
        len(chosen) > 1 and float(time[chosen[0]]) == float(time[chosen[-1]])
    ):
        parts = [
            f"{float(values[index]):.6g} @ {_format_stamp(float(time[index]))} 序号 {record}"
            for index, record in zip(chosen, indices)
        ]
        return NativeCursorReading(
            status="multiple",
            record_indices=indices,
            text="；".join(parts),
        )
    index = chosen[0]
    sample_time = float(time[index])
    value = float(values[index])
    delta = sample_time - float(query)
    return NativeCursorReading(
        status="sample",
        value=value,
        sample_time=sample_time,
        delta_s=delta,
        record_indices=(indices[0],),
        text=f"{value:.6g} @ {_format_stamp(sample_time)}，{_format_delta(delta)}",
    )


def query_native_cursor(series, query_time, *, mode="nearest") -> NativeCursorReading:
    """Nearest raw sample, or an explicitly requested linear interpolation.

    Equal distance keeps the earlier sample. Outside coverage, inside an
    invalid sample, or off a single point, the answer is no data.
    """
    if mode not in {"nearest", "linear"}:
        raise ValueError("mode 只能是 nearest 或 linear")
    try:
        query = float(query_time)
    except (TypeError, ValueError):
        return _none_reading()
    if not np.isfinite(query):
        return _none_reading()
    time, values, validity, segments, index_base, sample_index = _series_arrays(series)
    if mode == "linear":
        return _query_linear(
            time, values, validity, segments, query, index_base, sample_index,
        )
    hits = []
    for segment in segments:
        hits.extend(_segment_candidates(time, values, validity, segment, query))
    chosen = _choose_hits(time, hits, query)
    if not chosen:
        return _none_reading()
    return _reading_for(
        time, values, chosen, query, index_base, sample_index, status="nearest",
    )


def _query_linear(time, values, validity, segments, query, index_base, sample_index):
    exact = []
    for segment in segments:
        exact.extend(_segment_candidates(time, values, validity, segment, query))
    exact = [index for index in exact if float(time[index]) == query]
    if exact:
        return _reading_for(
            time, values, _choose_hits(time, exact, query), query,
            index_base, sample_index, status="nearest",
        )
    for segment in segments:
        if segment.has_nonfinite_time or segment.stop - segment.start < 2:
            continue
        part = time[segment.start:segment.stop]
        if not np.isfinite(part[0]) or not np.isfinite(part[-1]):
            continue
        if query <= float(part[0]) or query >= float(part[-1]):
            continue
        right = int(np.searchsorted(part, query, side="left"))
        if right <= 0 or right >= int(part.shape[0]):
            continue
        right_index = segment.start + right
        left_index = right_index - 1
        if _value_invalid(left_index, values, validity) or _value_invalid(right_index, values, validity):
            continue
        if any(
            _value_invalid(index, values, validity)
            for index in range(left_index + 1, right_index)
        ):
            continue
        left_time = float(time[left_index])
        right_time = float(time[right_index])
        if not (left_time < query < right_time):
            continue
        span = right_time - left_time
        frac = (query - left_time) / span
        value = float(values[left_index]) + (float(values[right_index]) - float(values[left_index])) * frac
        return NativeCursorReading(
            status="interpolated",
            value=value,
            sample_time=query,
            delta_s=0.0,
            record_indices=(
                _record_index(left_index, index_base, sample_index),
                _record_index(right_index, index_base, sample_index),
            ),
            text=f"≈{value:.6g} @ {_format_stamp(query)}，线性插值",
        )
    return _none_reading()


def native_sample_statistics(series, time_range=None) -> dict:
    """Valid-sample statistics. Invalid samples and the display envelope are ignored."""
    time, values, validity, _segments, _base, _sample_index = _series_arrays(series)
    values_f = np.asarray(values, dtype=float)
    time_f = np.asarray(time, dtype=float)
    invalid = np.zeros(values_f.shape, dtype=bool)
    if validity is not None:
        invalid |= validity
    invalid |= ~np.isfinite(values_f)
    valid = np.isfinite(time_f) & ~invalid
    if time_range is not None:
        lo, hi = time_range
        window = (time_f >= float(lo)) & (time_f <= float(hi))
        invalid_count = int(np.count_nonzero(invalid & window))
        valid = valid & window
    else:
        invalid_count = int(np.count_nonzero(invalid))
    unit = str(getattr(series, "unit", "") or "")
    name = str(getattr(series, "public_name", "") or "")
    valid_count = int(np.count_nonzero(valid))
    result = {
        "min": None,
        "max": None,
        "mean": None,
        "rms": None,
        "std": None,
        "p2p": None,
        "unit": unit,
        "display_label": name,
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "coverage": None,
        "weighting": "有效样本",
    }
    if valid_count == 0:
        return result
    samples = values_f[valid]
    stamps = time_f[valid]
    result.update({
        "min": float(np.min(samples)),
        "max": float(np.max(samples)),
        "mean": float(np.mean(samples)),
        "rms": float(np.sqrt(np.mean(samples * samples))),
        "std": float(np.std(samples)),
        "p2p": float(np.ptp(samples)),
        "coverage": (float(np.min(stamps)), float(np.max(stamps))),
    })
    return result


def acquisition_span(file_data):
    """Union of locatable time clocks. Non-time axes are not converted into seconds."""
    store = getattr(file_data, "native_store", None)
    if store is None:
        time_axis = getattr(file_data, "time_array", None)
        if time_axis is None or len(time_axis) == 0:
            return None
        array = np.asarray(time_axis, dtype=float)
        finite = array[np.isfinite(array)]
        if finite.size == 0:
            return None
        return (float(finite[0]), float(finite[-1]))
    lo = None
    hi = None
    for axis_id in store.axis_ids():
        axis = store.axis(axis_id)
        if str(axis.sampling.axis_kind) != "time":
            continue
        array = np.asarray(axis.values)
        if array.size == 0 or array.dtype.kind not in "biufc":
            continue
        finite_mask = np.isfinite(array)
        if not bool(np.any(finite_mask)):
            continue
        finite = array[finite_mask]
        axis_lo = float(np.min(finite))
        axis_hi = float(np.max(finite))
        lo = axis_lo if lo is None else min(lo, axis_lo)
        hi = axis_hi if hi is None else max(hi, axis_hi)
    if lo is None or hi is None:
        return None
    return (lo, hi)


def native_catalog_line(file_data) -> str:
    """Channel count, raw sample total, and rate wording. Does not scan sample values."""
    store = file_data.native_store
    counts = store.sample_counts()
    total = int(sum(int(value) for value in counts.values()))
    known = []
    unknown = False
    for axis_id in store.axis_ids():
        sampling = store.axis(axis_id).sampling
        if str(sampling.axis_kind) != "time":
            continue
        if sampling.status == "known" and sampling.fs_hz:
            rate = float(sampling.fs_hz)
            if not any(abs(rate - item) <= 1e-6 for item in known):
                known.append(rate)
        else:
            unknown = True
    if len(known) > 1 or (known and unknown):
        rate_text = "多种采样率"
    elif len(known) == 1:
        rate_text = f"{known[0]:g} Hz"
    else:
        rate_text = "采样率未知"
    return f"{len(counts)} 通道 · {total} 样本 · {rate_text}"


def channel_sample_count(file_data, channel=None):
    """Precomputed native count, or the legacy table length. Never scans values."""
    store = getattr(file_data, "native_store", None)
    if store is not None:
        counts = store.sample_counts()
        if channel is None:
            return int(sum(int(value) for value in counts.values()))
        return int(counts.get(channel, 0))
    data = getattr(file_data, "data", None)
    if data is None:
        return 0
    return int(len(data))


def display_samples(series):
    """Line arrays. The raw series is returned unchanged when nothing breaks.

    Invalid samples and reset boundaries become NaN gaps. A one-point curve
    asks for a marker. This copy exists only when the line must break.
    """
    time = np.asarray(series.time)
    values = np.asarray(series.values)
    count = int(time.shape[0])
    validity = getattr(series, "validity", None)
    invalid = np.zeros(count, dtype=bool)
    if validity is not None:
        invalid |= np.asarray(validity, dtype=bool)
    try:
        numeric = np.asarray(values, dtype=float)
        invalid |= ~np.isfinite(numeric)
    except (TypeError, ValueError):
        numeric = None
    finite_time = np.isfinite(np.asarray(time, dtype=float)) if count else np.zeros(0, dtype=bool)
    point_marker = bool(count) and int(np.count_nonzero(finite_time & ~invalid)) == 1
    segments = tuple(getattr(series, "segments", ()) or ())
    cuts = [int(segment.stop) for segment in segments[:-1]] if len(segments) > 1 else []
    if not bool(np.any(invalid)) and not cuts:
        return time, values, point_marker, False
    if numeric is None:
        numeric = np.asarray(values, dtype=float)
    broken_y = np.array(numeric, dtype=float, copy=True)
    broken_y[invalid] = np.nan
    broken_t = np.array(np.asarray(time, dtype=float), copy=True)
    if not cuts:
        return broken_t, broken_y, point_marker, True
    cut_at = set(cuts)
    out_t = []
    out_y = []
    for index in range(count):
        if index in cut_at:
            out_t.append(np.nan)
            out_y.append(np.nan)
        out_t.append(broken_t[index])
        out_y.append(broken_y[index])
    return (
        np.asarray(out_t, dtype=float),
        np.asarray(out_y, dtype=float),
        point_marker,
        True,
    )


@dataclass(frozen=True)
class NativeQuery:
    """Plot-time handle. Arrays are store views. ``closed`` is checked before a read."""

    series: object
    revision: str
    display_time: object
    display_values: object
    point_marker: bool
    has_break: bool
    closed: object

    def is_closed(self) -> bool:
        try:
            return bool(self.closed())
        except (AttributeError, ReferenceError, RuntimeError):
            return True


def make_native_query(file_data, series) -> NativeQuery:
    display_time, display_values, point_marker, has_break = display_samples(series)
    source = file_data

    def _closed(owner=source):
        return bool(getattr(owner, "source_closed", False))

    return NativeQuery(
        series=series,
        revision=str(series.revision),
        display_time=display_time,
        display_values=display_values,
        point_marker=point_marker,
        has_break=has_break,
        closed=_closed,
    )


__all__ = [
    "CHANNEL_MODE",
    "EXACT_SOURCE",
    "PER_SOURCE_NAME",
    "TIME_MODE",
    "CursorXAxisContext",
    "CustomXAxisSpec",
    "CustomXResolution",
    "NativeCursorReading",
    "NativeQuery",
    "SelectionPayload",
    "TimePlotIssue",
    "acquisition_span",
    "apply_unit_cohort",
    "channel_sample_count",
    "channel_unit",
    "display_samples",
    "make_native_query",
    "native_catalog_line",
    "native_sample_statistics",
    "query_native_cursor",
    "resolve_custom_xaxis",
    "selection_payload",
    "spec_from_selection",
]
