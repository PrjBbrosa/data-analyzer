"""Unified read for a native store or one legacy table.

Continuous selections stay slices. A full-length boolean mask is not built,
and raw integers are not cast to float64.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

import numpy as np

from .channel_frame import frame_get_column
from .file_data import JobSourceHold, SourceClosedError, resolve_saved_signal_name
from .native_signal_store import (
    NativeContractError,
    SamplingFacts,
    build_segments,
)


class SignalAccessError(ValueError):
    """A read_signal request has a determined rejection."""


@dataclass(frozen=True)
class TimeSpan:
    """Inclusive time window, located on the original samples."""

    start: float
    stop: float


@dataclass(frozen=True)
class IndexSpan:
    """Half-open sample-index window. Indexes stay in record order."""

    start: int
    stop: int


@dataclass(frozen=True)
class SignalSeries:
    time: np.ndarray
    values: np.ndarray
    validity: np.ndarray | None
    segments: tuple
    unit: str
    sampling: SamplingFacts
    revision: str
    physical_key: object
    public_name: str
    representation: str
    source_id: str
    index_start: int | None
    index_stop: int | None
    sample_index: np.ndarray | None

    @property
    def invalidation_bits(self):
        """Invalidation mask. True marks a sample the source flagged invalid."""
        return self.validity


def read_signal(
    source, channel_key, span=None, representation="physical", segment=None,
    *, neighbor_halo=0,
):
    """Return one channel's time, values, validity, and sampling facts.

    ``neighbor_halo`` keeps that many samples outside a time span so alignment
    can see the bracketing points. The output of a later resample still has to
    stay inside the requested coverage; this only widens the read.
    """
    file_data = source.file_data if isinstance(source, JobSourceHold) else source
    if getattr(file_data, "source_closed", False):
        raise SourceClosedError("来源已关闭")
    if representation not in {"physical", "raw"}:
        raise SignalAccessError(
            f"representation {representation!r} 不可用，只能是 physical 或 raw"
        )
    if type(neighbor_halo) is not int or isinstance(neighbor_halo, bool) or neighbor_halo < 0:
        raise SignalAccessError("neighbor_halo 必须是非负 int")
    store = getattr(file_data, "native_store", None)
    if store is not None:
        return _read_native(
            file_data, store, channel_key, span, representation, segment,
            neighbor_halo,
        )
    return _read_legacy(
        file_data, channel_key, span, representation, segment, neighbor_halo,
    )


def _read_native(file_data, store, channel_key, span, representation, segment, neighbor_halo=0):
    try:
        channel = store.channel(channel_key)
    except NativeContractError as exc:
        raise SignalAccessError(str(exc)) from exc
    if channel.support_status == "unsupported" or channel.conversion == "unsupported":
        raise SignalAccessError(
            f"通道 {channel.public_name!r} 不受支持，不能发布截短后的数值"
        )
    if representation == "physical" and (
        channel.support_status == "enum" or channel.conversion == "enum"
    ):
        raise SignalAccessError(
            f"通道 {channel.public_name!r} 的枚举文本不是连续物理值，不能当作 physical"
        )
    axis = store.axis(channel.axis_id)
    values = channel.raw if representation == "raw" else channel.physical
    return _assemble(
        time=axis.values,
        values=values,
        validity=channel.validity,
        segments=axis.segments,
        span=span,
        segment=segment,
        unit=channel.unit,
        sampling=axis.sampling,
        revision=store.revision,
        physical_key=channel.physical_key,
        public_name=channel.public_name,
        representation=representation,
        source_id=store.source_id,
        neighbor_halo=neighbor_halo,
    )


def known_sampling_hz(file_data, channel):
    """Known Fs for one channel. Native files have no file-level substitute."""
    if getattr(file_data, "is_native", False):
        try:
            series = read_signal(file_data, channel, representation="raw")
        except (SignalAccessError, SourceClosedError, TypeError, ValueError):
            return None
        sampling = series.sampling
        if sampling.status != "known" or sampling.fs_hz is None:
            return None
        return float(sampling.fs_hz)
    try:
        fs = float(file_data.fs)
    except (TypeError, ValueError, AttributeError):
        return None
    if not np.isfinite(fs) or fs <= 0:
        return None
    return fs


def channel_in_source(file_data, channel) -> bool:
    """True when ``channel`` is a real column or native public name."""
    if getattr(file_data, "is_native", False):
        store = getattr(file_data, "native_store", None)
        if store is None:
            return False
        try:
            store.channel(channel)
        except NativeContractError:
            return False
        return True
    data = getattr(file_data, "data", None)
    return data is not None and channel in getattr(data, "columns", ())


def channel_time_values(file_data, channel, *, representation="physical"):
    """Return ``(time, values, fs_or_none)`` without a legacy axis fallback."""
    if getattr(file_data, "is_native", False):
        series = read_signal(file_data, channel, representation=representation)
        fs = None
        if series.sampling.status == "known" and series.sampling.fs_hz is not None:
            fs = float(series.sampling.fs_hz)
        return series.time, series.values, fs
    if not channel_in_source(file_data, channel):
        raise SignalAccessError(f"通道 {channel!r} 不在来源中")
    values = frame_get_column(file_data.data, channel)
    axis = getattr(file_data, "time_array", None)
    return axis, np.asarray(values), known_sampling_hz(file_data, channel)


def _read_legacy(file_data, channel_key, span, representation, segment, neighbor_halo=0):
    if representation != "physical" and representation != "raw":
        raise SignalAccessError(
            f"representation {representation!r} 不可用，只能是 physical 或 raw"
        )
    name = _legacy_name(file_data, channel_key)
    time = np.asarray(file_data.time_array)
    column = np.asarray(frame_get_column(file_data.data, name))
    if time.ndim != 1 or column.ndim != 1:
        raise SignalAccessError(f"通道 {name!r} 不是一维序列")
    if int(time.shape[0]) != int(column.shape[0]):
        raise SignalAccessError(
            f"通道 {name!r} 长度 {column.shape[0]} 与时间轴长度 {time.shape[0]} "
            "不一致，不能用 min 截短"
        )
    units = getattr(file_data, "channel_units", {}) or {}
    unit = "" if units.get(name) is None else str(units.get(name))
    return _assemble(
        time=time,
        values=column,
        validity=None,
        segments=build_segments(time),
        span=span,
        segment=segment,
        unit=unit,
        sampling=_legacy_sampling(file_data),
        revision=_legacy_revision(file_data, name, time, column),
        physical_key=None,
        public_name=name,
        representation=representation,
        source_id=str(getattr(file_data, "filepath", "") or ""),
        neighbor_halo=neighbor_halo,
    )


def _legacy_name(file_data, key):
    if isinstance(key, tuple) and len(key) == 2 and type(key[0]) is int and type(key[1]) is int:
        hits = []
        metadata = getattr(file_data, "channel_metadata", {}) or {}
        for name, facts in metadata.items():
            if not isinstance(facts, dict):
                continue
            occurrence = facts.get("physical_occurrence")
            if (
                isinstance(occurrence, (list, tuple))
                and len(occurrence) == 2
                and int(occurrence[0]) == key[0]
                and int(occurrence[1]) == key[1]
            ):
                hits.append(str(name))
        if len(hits) == 1 and hits[0] in set(file_data.get_signal_channels()):
            return hits[0]
        raise SignalAccessError(f"物理 occurrence {key} 不是唯一已知映射")
    if type(key) is not str:
        raise TypeError(f"通道键类型不受支持: {type(key).__name__}")
    resolved = resolve_saved_signal_name(file_data, key)
    if resolved is None:
        names = list(file_data.get_signal_channels())
        raise SignalAccessError(
            f"通道 {key!r} 不是精确公开名或唯一已知映射；已有 {names}"
        )
    return resolved


def _positive_fs(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number) or number <= 0:
        return None
    return number


def _legacy_sampling(file_data):
    meta = getattr(file_data, "source_metadata", {}) or {}
    kind = str(meta.get("source_kind") or "")
    source = str(getattr(file_data, "_time_source", "") or "")
    axis_unit = ""
    explicit = meta.get("time_column")
    units = getattr(file_data, "channel_units", {}) or {}
    if isinstance(explicit, str) and explicit in units and units.get(explicit):
        axis_unit = str(units.get(explicit))
    if meta.get("fs_estimated"):
        return SamplingFacts(
            "estimated", _positive_fs(file_data.fs), "time", axis_unit, "legacy_estimated",
        )
    if kind in {"csv", "excel", "ascii", "tdms"} and "verified_sample_rate" in meta:
        fs = _positive_fs(meta.get("verified_sample_rate"))
        if fs is None:
            return SamplingFacts("unknown", None, "time", axis_unit, "legacy_verified_unknown")
        return SamplingFacts("known", fs, "time", axis_unit, "legacy_verified")
    if source in {"generated", "auto"}:
        return SamplingFacts("unknown", None, "time", axis_unit, "legacy_generated")
    time = file_data.time_array
    n = 0 if time is None else len(time)
    fs = _positive_fs(file_data.fs)
    if source in {"column", "audio", "manual"} and fs is not None and n >= 2:
        return SamplingFacts("known", fs, "time", axis_unit, f"legacy_{source}")
    return SamplingFacts("unknown", None, "time", axis_unit, "legacy_unspecified")


def _legacy_revision(file_data, name, time, values):
    digest = hashlib.sha256()
    digest.update(b"legacy-signal-v1\n")
    digest.update(str(getattr(file_data, "filepath", "")).encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(name).encode("utf-8"))
    digest.update(np.asarray(time).tobytes())
    digest.update(np.asarray(values).tobytes())
    return digest.hexdigest()


def _assemble(*, time, values, validity, segments, span, segment, unit, sampling,
              revision, physical_key, public_name, representation, source_id,
              neighbor_halo=0):
    chosen = _choose_segment(segments, segment)
    index = _select(time, segments, chosen, span, neighbor_halo)
    part_time = _take(time, index)
    part_values = _take(values, index)
    part_validity = None if validity is None else _take(validity, index)
    if isinstance(index, slice):
        index_start = 0 if index.start is None else int(index.start)
        index_stop = int(index.stop)
        sample_index = None
        covered = _overlapping(segments, index_start, index_stop)
    else:
        index_start = None
        index_stop = None
        sample_index = index
        if index.size == 0:
            covered = ()
        else:
            covered = _overlapping(segments, int(index[0]), int(index[-1]) + 1)
    return SignalSeries(
        time=part_time,
        values=part_values,
        validity=part_validity,
        segments=covered,
        unit=unit,
        sampling=sampling,
        revision=revision,
        physical_key=physical_key,
        public_name=public_name,
        representation=representation,
        source_id=source_id,
        index_start=index_start,
        index_stop=index_stop,
        sample_index=sample_index,
    )


def _choose_segment(segments, segment):
    if segment is None:
        return segments
    if type(segment) is not int:
        raise TypeError("segment 必须是 int")
    if segment < 0 or segment >= len(segments):
        raise SignalAccessError(
            f"segment {segment} 超出范围，共有 {len(segments)} 段"
        )
    return (segments[segment],)


def _select(time, segments, chosen, span, neighbor_halo=0):
    n = int(np.asarray(time).shape[0])
    halo = int(neighbor_halo or 0)
    if span is None:
        if len(chosen) == len(segments):
            return slice(0, n)
        if len(chosen) == 1:
            return slice(chosen[0].start, chosen[0].stop)
        return _merge_ranges([(item.start, item.stop) for item in chosen])
    if isinstance(span, IndexSpan):
        if type(span.start) is not int or type(span.stop) is not int:
            raise TypeError("IndexSpan 的端点必须是 int")
        if span.start < 0 or span.stop < 0:
            raise SignalAccessError("样本序号不能为负")
        if span.stop < span.start:
            raise SignalAccessError("IndexSpan.stop 小于 start")
        start = min(span.start, n)
        stop = min(span.stop, n)
        if halo:
            start = max(0, start - halo)
            stop = min(n, stop + halo)
        if len(chosen) != len(segments):
            bounds = [(item.start, item.stop) for item in chosen]
            return _merge_ranges(_intersect_ranges(bounds, start, stop))
        return slice(start, stop)
    start, stop = _time_bounds(span)
    ranges = []
    for item in chosen:
        if item.has_nonfinite_time:
            continue
        part = time[item.start:item.stop]
        left = int(np.searchsorted(part, start, side="left"))
        right = int(np.searchsorted(part, stop, side="right"))
        if halo:
            left = max(0, left - halo)
            right = min(int(part.shape[0]), right + halo)
        if right > left:
            ranges.append((item.start + left, item.start + right))
    return _merge_ranges(ranges)


def _time_bounds(span):
    if isinstance(span, TimeSpan):
        start, stop = span.start, span.stop
    elif isinstance(span, tuple) and len(span) == 2:
        start, stop = span
    else:
        raise TypeError(f"span 类型不受支持: {type(span).__name__}")
    try:
        start_f = float(start)
        stop_f = float(stop)
    except (TypeError, ValueError) as exc:
        raise TypeError("时间范围必须是两个实数") from exc
    if not np.isfinite(start_f) or not np.isfinite(stop_f) or start_f > stop_f:
        raise SignalAccessError("时间范围必须是有限且 start <= stop")
    return start_f, stop_f


def _intersect_ranges(ranges, start, stop):
    kept = []
    for item_start, item_stop in ranges:
        lo = max(item_start, start)
        hi = min(item_stop, stop)
        if hi > lo:
            kept.append((lo, hi))
    return kept


def _merge_ranges(ranges):
    if not ranges:
        return slice(0, 0)
    merged = [[ranges[0][0], ranges[0][1]]]
    for start, stop in ranges[1:]:
        if start == merged[-1][1]:
            merged[-1][1] = stop
        else:
            merged.append([start, stop])
    if len(merged) == 1:
        return slice(merged[0][0], merged[0][1])
    pieces = [np.arange(start, stop, dtype=np.int64) for start, stop in merged]
    index = np.concatenate(pieces)
    index.setflags(write=False)
    return index


def _take(array, index):
    part = array[index]
    if isinstance(index, np.ndarray) or part.flags.writeable:
        part = np.array(part, copy=True)
        part.setflags(write=False)
    return part


def _overlapping(segments, start, stop):
    return tuple(
        item for item in segments
        if item.stop > start and item.start < stop
    )
