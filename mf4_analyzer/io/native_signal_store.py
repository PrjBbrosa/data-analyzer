"""Immutable native axis/channel store.

No Qt and no MDF handle. Callers hand in arrays; this module freezes them,
keeps each clock's identity, and serves readonly views.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json

import numpy as np


_NUMERIC_KINDS = set("biufc")
_AXIS_KINDS = frozenset({"time", "angle", "distance", "index"})
_CONVERSIONS = frozenset({"identity", "library", "enum", "unsupported"})
_SUPPORT = frozenset({"numeric", "enum", "unsupported"})
_LEDGER_KINDS = ("raw", "time", "physical", "validity")


class NativeContractError(ValueError):
    """The native store was built or addressed against its contract."""


class SourceClosedError(RuntimeError):
    """The store was closed. Sample buffers are no longer readable."""


@dataclass(frozen=True)
class SamplingFacts:
    status: str
    fs_hz: float | None
    axis_kind: str
    axis_unit: str
    basis: str

    @property
    def state(self):
        """Alias used by the native fidelity contract."""
        return self.status

    @property
    def fs(self):
        """Alias used by the native fidelity contract."""
        return self.fs_hz


@dataclass(frozen=True)
class SegmentFact:
    index: int
    start: int
    stop: int
    monotonic: bool
    has_duplicate_time: bool
    has_nonfinite_time: bool


@dataclass(frozen=True)
class PhysicalKey:
    source_id: str
    group: int
    index: int
    parent: tuple = ()
    coordinates: tuple = ()

    @property
    def token(self) -> str:
        payload = json.dumps(
            {
                "coordinates": list(self.coordinates),
                "group": self.group,
                "index": self.index,
                "parent": list(self.parent),
                "source": self.source_id,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
        return f"phys:{digest}"


@dataclass(frozen=True)
class AxisSpec:
    axis_id: str
    clock_source: str
    kind: str
    unit: str
    values: object
    fs_status: str | None = None
    fs_hz: float | None = None


@dataclass(frozen=True)
class ChannelSpec:
    group: int
    index: int
    original_name: str
    axis_id: str
    raw: object
    unit: str = ""
    physical: object | None = None
    validity: object | None = None
    conversion: str = "identity"
    support_status: str = "numeric"
    parent: tuple = ()
    coordinates: tuple = ()


@dataclass(frozen=True)
class AxisRecord:
    axis_id: str
    clock_source: str
    kind: str
    unit: str
    values: np.ndarray
    segments: tuple
    sampling: SamplingFacts


@dataclass(frozen=True)
class ChannelRecord:
    physical_key: PhysicalKey
    public_name: str
    original_name: str
    unit: str
    axis_id: str
    raw: np.ndarray
    physical: np.ndarray
    validity: np.ndarray | None
    conversion: str
    support_status: str
    sample_count: int


def build_segments(values) -> tuple:
    """Split a master into monotonic runs. Order and duplicates stay put."""
    array = np.asarray(values)
    n = int(array.shape[0])
    if n == 0:
        return ()
    if n == 1:
        nonfinite = not bool(np.isfinite(array[0]))
        return (SegmentFact(
            0, 0, 1, monotonic=not nonfinite,
            has_duplicate_time=False, has_nonfinite_time=nonfinite,
        ),)

    segments = []
    start = 0
    duplicate = False

    def close(stop):
        nonlocal start, duplicate
        if stop <= start:
            return
        nonfinite = stop == start + 1 and not bool(np.isfinite(array[start]))
        segments.append(SegmentFact(
            index=len(segments),
            start=start,
            stop=stop,
            monotonic=not nonfinite,
            has_duplicate_time=bool(duplicate),
            has_nonfinite_time=nonfinite,
        ))
        start = stop
        duplicate = False

    i = 1
    while i < n:
        prev = array[i - 1]
        cur = array[i]
        prev_ok = bool(np.isfinite(prev))
        cur_ok = bool(np.isfinite(cur))
        if not prev_ok or not cur_ok or cur < prev:
            close(i)
            i += 1
            continue
        if cur == prev:
            duplicate = True
        i += 1
    close(n)
    return tuple(segments)


def _require_text(value, name):
    if type(value) is not str or not value:
        raise NativeContractError(f"{name} 必须是非空字符串")
    return value


def _require_int(value, name):
    if type(value) is not int:
        raise NativeContractError(f"{name} 必须是 int")
    return value


def _tuple_path(value, name):
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    raise NativeContractError(f"{name} 必须是 tuple")


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


def _sampling(kind, unit, values, fs_status, fs_hz):
    if kind != "time":
        if fs_status not in (None, "unknown"):
            raise NativeContractError("非时间轴不能声明采样率")
        return SamplingFacts("unknown", None, kind, unit, "non_time_axis")
    if fs_status == "estimated":
        fs = _positive_fs(fs_hz)
        if fs is None:
            raise NativeContractError("estimated Fs 必须是有限正数")
        return SamplingFacts("estimated", fs, "time", unit, "declared_estimate")
    if fs_status == "known":
        fs = _positive_fs(fs_hz)
        if fs is None:
            raise NativeContractError("known Fs 必须是有限正数")
        return SamplingFacts("known", fs, "time", unit, "declared")
    if fs_status == "unknown":
        return SamplingFacts("unknown", None, "time", unit, "declared_unknown")
    if fs_status is not None:
        raise NativeContractError(f"fs_status {fs_status!r} 无效")
    n = int(values.shape[0])
    if n == 0:
        return SamplingFacts("unknown", None, "time", unit, "empty")
    if n == 1:
        return SamplingFacts("unknown", None, "time", unit, "single_point")
    dt0 = None
    for index in range(1, n):
        prev = values[index - 1]
        cur = values[index]
        if not bool(np.isfinite(prev)) or not bool(np.isfinite(cur)):
            return SamplingFacts("unknown", None, "time", unit, "nonfinite")
        dt = cur - prev
        if dt <= 0:
            return SamplingFacts("unknown", None, "time", unit, "not_strictly_uniform")
        if dt0 is None:
            dt0 = dt
        elif dt != dt0:
            return SamplingFacts("unknown", None, "time", unit, "not_strictly_uniform")
    return SamplingFacts("known", float(1.0 / float(dt0)), "time", unit, "uniform_timestamps")


def _freeze(value, *, name, cache, copy_always=False):
    if isinstance(value, np.ndarray) and not copy_always:
        cached = cache.get(id(value))
        if cached is not None:
            return cached
    array = np.asarray(value)
    if array.ndim != 1:
        raise NativeContractError(f"{name} 必须是一维数组")
    if array.dtype.hasobject or array.dtype.kind not in _NUMERIC_KINDS:
        raise NativeContractError(f"{name} 的 dtype {array.dtype} 不是数值")
    if copy_always or array.flags.writeable or not isinstance(value, np.ndarray):
        frozen = np.array(array, copy=True)
    else:
        frozen = array
    frozen.setflags(write=False)
    if isinstance(value, np.ndarray) and not copy_always:
        cache[id(value)] = frozen
    return frozen


def _unique_nbytes(arrays):
    seen = set()
    total = 0
    for array in arrays:
        if array is None:
            continue
        pointer = int(array.__array_interface__["data"][0])
        key = (pointer, int(array.nbytes), array.dtype.str)
        if key in seen:
            continue
        seen.add(key)
        total += int(array.nbytes)
    return total


def _revision(source_id, axes, channels):
    digest = hashlib.sha256()
    digest.update(b"mf4-native-store-v1\n")
    digest.update(source_id.encode("utf-8"))
    for axis in axes:
        digest.update(b"\naxis\n")
        digest.update(axis.axis_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(axis.clock_source.encode("utf-8"))
        digest.update(b"\0")
        digest.update(axis.kind.encode("utf-8"))
        digest.update(b"\0")
        digest.update(axis.unit.encode("utf-8"))
        digest.update(b"\0")
        digest.update(axis.sampling.status.encode("utf-8"))
        digest.update(b"\0")
        fs = "none" if axis.sampling.fs_hz is None else repr(axis.sampling.fs_hz)
        digest.update(fs.encode("utf-8"))
        digest.update(axis.values.dtype.str.encode("utf-8"))
        digest.update(axis.values.tobytes())
    for channel in channels:
        key = channel.physical_key
        digest.update(b"\nchannel\n")
        digest.update(channel.public_name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(key.group).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(key.index).encode("utf-8"))
        digest.update(b"\0")
        digest.update(repr(key.parent).encode("utf-8"))
        digest.update(b"\0")
        digest.update(repr(key.coordinates).encode("utf-8"))
        digest.update(b"\0")
        digest.update(channel.conversion.encode("utf-8"))
        digest.update(b"\0")
        digest.update(channel.support_status.encode("utf-8"))
        digest.update(channel.raw.dtype.str.encode("utf-8"))
        digest.update(channel.raw.tobytes())
        if channel.physical is not channel.raw:
            digest.update(channel.physical.dtype.str.encode("utf-8"))
            digest.update(channel.physical.tobytes())
        if channel.validity is None:
            digest.update(b"-")
        else:
            digest.update(channel.validity.tobytes())
    return digest.hexdigest()


def _disambiguate_repeated_public_names(public, renamed):
    """Qualify every display name that still belongs to more than one channel.

    ``assign_mf4_public_signal_names`` only renames the public Time column.
    Two measurements can share another original name. Transport and lookup
    must not collapse them.
    """
    counts = {}
    for name in public.values():
        counts[name] = counts.get(name, 0) + 1
    if all(count == 1 for count in counts.values()):
        return public, renamed
    taken = set(public.values())
    renamed = list(renamed)
    for occurrence, name in list(public.items()):
        if counts[name] == 1:
            continue
        candidate = f"{name} [{occurrence[0]}:{occurrence[1]}]"
        suffix = 2
        while candidate in taken:
            candidate = f"{name} [{occurrence[0]}:{occurrence[1]}] [{suffix}]"
            suffix += 1
        taken.add(candidate)
        public[occurrence] = candidate
        renamed.append({
            "original": name,
            "renamed": candidate,
            "physical_occurrence": [occurrence[0], occurrence[1]],
        })
    renamed.sort(key=lambda item: (
        item["physical_occurrence"][0],
        item["physical_occurrence"][1],
        item["renamed"],
    ))
    return public, renamed


class NativeSignalStore:
    """One MF4 logical source: axes, channels, and a content revision."""

    def __init__(self, source_id, axes, channels, renamed):
        self.source_id = source_id
        self._axes = tuple(axes)
        self._channels = tuple(channels)
        self._renamed = tuple(renamed)
        self.revision = _revision(source_id, self._axes, self._channels)
        self._closed = False
        self._reindex()

    @classmethod
    def build(cls, source_id, axes, channels):
        source_id = _require_text(source_id, "source_id")
        axis_records, axis_by_id = cls._build_axes(axes)
        channel_records, renamed = cls._build_channels(
            source_id, channels, axis_by_id,
        )
        return cls(source_id, axis_records, channel_records, renamed)

    @classmethod
    def _build_axes(cls, axes):
        if not isinstance(axes, Sequence) or isinstance(axes, (str, bytes)):
            raise NativeContractError("axes 必须是 AxisSpec 序列")
        cache = {}
        records = []
        by_id = {}
        for spec in axes:
            if not isinstance(spec, AxisSpec):
                raise TypeError("轴必须是 AxisSpec")
            axis_id = _require_text(spec.axis_id, "axis_id")
            clock = _require_text(spec.clock_source, "clock_source")
            if spec.kind not in _AXIS_KINDS:
                raise NativeContractError(f"未知轴种类 {spec.kind!r}")
            if type(spec.unit) is not str:
                raise NativeContractError("轴单位必须是字符串")
            if axis_id in by_id:
                raise NativeContractError(f"重复的 axis_id {axis_id!r}")
            values = _freeze(spec.values, name=f"轴 {axis_id}", cache=cache)
            sampling = _sampling(
                spec.kind, spec.unit, values, spec.fs_status, spec.fs_hz,
            )
            record = AxisRecord(
                axis_id=axis_id,
                clock_source=clock,
                kind=spec.kind,
                unit=spec.unit,
                values=values,
                segments=build_segments(values),
                sampling=sampling,
            )
            records.append(record)
            by_id[axis_id] = record
        return tuple(records), by_id

    @classmethod
    def _build_channels(cls, source_id, channels, axis_by_id):
        if not isinstance(channels, Sequence) or isinstance(channels, (str, bytes)):
            raise NativeContractError("channels 必须是 ChannelSpec 序列")
        from .loader import assign_mf4_public_signal_names

        specs = []
        seen = set()
        cache = {}
        for spec in channels:
            if not isinstance(spec, ChannelSpec):
                raise TypeError("通道必须是 ChannelSpec")
            group = _require_int(spec.group, "group")
            index = _require_int(spec.index, "index")
            if group < 0 or index < 0:
                raise NativeContractError("group/index 不能为负")
            occurrence = (group, index)
            if occurrence in seen:
                raise NativeContractError(
                    f"同一物理 occurrence {occurrence} 不能生成第二份通道"
                )
            seen.add(occurrence)
            specs.append((spec, occurrence))
        public, renamed = assign_mf4_public_signal_names(
            (spec.original_name, occurrence) for spec, occurrence in specs
        )
        public, renamed = _disambiguate_repeated_public_names(public, renamed)
        records = []
        for spec, occurrence in specs:
            axis = axis_by_id.get(spec.axis_id)
            if axis is None:
                raise NativeContractError(f"通道引用了未知轴 {spec.axis_id!r}")
            name = _require_text(spec.original_name, "original_name")
            if spec.conversion not in _CONVERSIONS:
                raise NativeContractError(f"未知转换 {spec.conversion!r}")
            if spec.support_status not in _SUPPORT:
                raise NativeContractError(f"未知支持状态 {spec.support_status!r}")
            if type(spec.unit) is not str:
                raise NativeContractError("通道单位必须是字符串")
            parent = _tuple_path(spec.parent, "parent")
            coordinates = _tuple_path(spec.coordinates, "coordinates")
            raw = _freeze(spec.raw, name=f"通道 {name} raw", cache=cache)
            axis_n = int(axis.values.shape[0])
            raw_n = int(raw.shape[0])
            if raw_n != axis_n:
                raise NativeContractError(
                    f"通道 {name!r} 长度 {raw_n} 与轴 {axis.axis_id!r} 长度 {axis_n} "
                    "不一致，不能用 min 截短"
                )
            physical = cls._physical_array(spec, raw, cache, name)
            validity = cls._validity_array(spec.validity, raw_n, cache, name)
            cls._check_conversion(spec, raw, physical)
            key = PhysicalKey(
                source_id=source_id,
                group=occurrence[0],
                index=occurrence[1],
                parent=parent,
                coordinates=coordinates,
            )
            records.append(ChannelRecord(
                physical_key=key,
                public_name=public[occurrence],
                original_name=name,
                unit=spec.unit,
                axis_id=axis.axis_id,
                raw=raw,
                physical=physical,
                validity=validity,
                conversion=spec.conversion,
                support_status=spec.support_status,
                sample_count=raw_n,
            ))
        return tuple(records), tuple(renamed)

    @staticmethod
    def _physical_array(spec, raw, cache, name):
        if spec.conversion == "identity":
            if spec.physical is None:
                return raw
            physical = _freeze(spec.physical, name=f"通道 {name} physical", cache=cache)
            if physical is not raw:
                raise NativeContractError(
                    f"通道 {name!r} 的 identity 转换必须引用同一 raw buffer"
                )
            return physical
        if spec.conversion == "library":
            if spec.physical is None:
                raise NativeContractError(f"通道 {name!r} 的 library 转换缺少 physical")
            physical = _freeze(spec.physical, name=f"通道 {name} physical", cache=cache)
            if physical is raw:
                raise NativeContractError(
                    f"通道 {name!r} 的 library 转换需要独立的 physical buffer"
                )
            if int(physical.shape[0]) != int(raw.shape[0]):
                raise NativeContractError(
                    f"通道 {name!r} physical 长度 {physical.shape[0]} 与 raw 长度 "
                    f"{raw.shape[0]} 不一致，不能用 min 截短"
                )
            return physical
        if spec.physical is not None:
            raise NativeContractError(
                f"通道 {name!r} 的 {spec.conversion} 不能带连续 physical"
            )
        return raw

    @staticmethod
    def _validity_array(validity, raw_n, cache, name):
        if validity is None:
            return None
        frozen = _freeze(validity, name=f"通道 {name} validity", cache=cache)
        if int(frozen.shape[0]) != raw_n:
            raise NativeContractError(
                f"通道 {name!r} validity 长度 {frozen.shape[0]} 与 raw 长度 {raw_n} "
                "不一致，不能用 min 截短"
            )
        return frozen

    @staticmethod
    def _check_conversion(spec, raw, physical):
        if spec.conversion == "enum" and spec.support_status != "enum":
            raise NativeContractError("enum 转换的支持状态必须是 enum")
        if spec.conversion == "unsupported" and spec.support_status != "unsupported":
            raise NativeContractError("unsupported 转换的支持状态必须是 unsupported")
        if spec.conversion in {"identity", "library"} and spec.support_status != "numeric":
            raise NativeContractError("数值转换的支持状态必须是 numeric")
        if spec.conversion == "identity" and physical is not raw:
            raise NativeContractError("identity 转换不能另存 physical")

    def _reindex(self):
        self._by_axis = {axis.axis_id: axis for axis in self._axes}
        self._by_public = {}
        self._by_token = {}
        self._by_occurrence = {}
        originals = {}
        for channel in self._channels:
            self._by_public[channel.public_name] = channel
            self._by_token[channel.physical_key.token] = channel
            occurrence = (channel.physical_key.group, channel.physical_key.index)
            self._by_occurrence[occurrence] = channel
        for entry in self._renamed:
            if not isinstance(entry, Mapping):
                continue
            original = str(entry.get("original") or "")
            renamed = str(entry.get("renamed") or "")
            channel = self._by_public.get(renamed)
            if channel is None or not original:
                continue
            originals.setdefault(original, []).append(channel)
        self._by_original = originals

    def _ensure_open(self):
        if self._closed:
            raise SourceClosedError(f"native 来源 {self.source_id} 已关闭")

    @property
    def closed(self):
        return self._closed

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._axes = ()
        self._channels = ()
        self._by_axis = {}
        self._by_public = {}
        self._by_token = {}
        self._by_occurrence = {}
        self._by_original = {}

    def axis(self, axis_id):
        self._ensure_open()
        try:
            return self._by_axis[axis_id]
        except KeyError:
            raise NativeContractError(f"未知轴 {axis_id!r}") from None

    def channel(self, key):
        self._ensure_open()
        return self._resolve(key)

    def _resolve(self, key):
        if isinstance(key, PhysicalKey):
            found = self._by_token.get(key.token)
            if found is None or found.physical_key != key:
                raise NativeContractError(f"物理键 {key.token} 不在来源 {self.source_id}")
            return found
        if isinstance(key, tuple) and len(key) == 2 and type(key[0]) is int and type(key[1]) is int:
            found = self._by_occurrence.get((key[0], key[1]))
            if found is None:
                raise NativeContractError(f"物理 occurrence {key} 不在来源 {self.source_id}")
            return found
        if type(key) is not str:
            raise TypeError(f"通道键类型不受支持: {type(key).__name__}")
        if key in self._by_public:
            return self._by_public[key]
        if key.startswith("phys:"):
            found = self._by_token.get(key)
            if found is None:
                raise NativeContractError(f"物理键 {key} 不在来源 {self.source_id}")
            return found
        matches = self._by_original.get(key, ())
        if len(matches) == 1:
            return matches[0]
        names = tuple(self._by_public)
        if len(matches) > 1:
            raise NativeContractError(
                f"显示名 {key!r} 对应多个已知映射，不能自动选择；已有 {names}"
            )
        raise NativeContractError(
            f"通道 {key!r} 不是精确公开名或唯一已知映射；已有 {names}"
        )

    def channels(self):
        """Physical records. Display names are not an identity."""
        self._ensure_open()
        return self._channels

    def public_names(self):
        self._ensure_open()
        return tuple(channel.public_name for channel in self._channels)

    def renamed_channels(self):
        self._ensure_open()
        return self._renamed

    def units(self):
        self._ensure_open()
        return {channel.public_name: channel.unit for channel in self._channels}

    def channel_metadata(self):
        self._ensure_open()
        metadata = {}
        for channel in self._channels:
            key = channel.physical_key
            metadata[channel.public_name] = {
                "physical_occurrence": (key.group, key.index),
                "physical_key": key.token,
                "unit": channel.unit,
                "axis_id": channel.axis_id,
                "support_status": channel.support_status,
                "parent": key.parent,
                "coordinates": key.coordinates,
            }
        return metadata

    def axis_ids(self):
        self._ensure_open()
        return tuple(axis.axis_id for axis in self._axes)

    def sample_counts(self):
        self._ensure_open()
        return {channel.public_name: channel.sample_count for channel in self._channels}

    def owned_arrays(self):
        self._ensure_open()
        found = []
        seen = set()
        candidates = [axis.values for axis in self._axes]
        for channel in self._channels:
            candidates.append(channel.raw)
            if channel.physical is not channel.raw:
                candidates.append(channel.physical)
            if channel.validity is not None:
                candidates.append(channel.validity)
        for array in candidates:
            marker = id(array)
            if marker in seen:
                continue
            seen.add(marker)
            found.append(array)
        return tuple(found)

    def byte_ledger(self):
        """Bytes of raw, time, extra physical, and validity. Shared buffers once."""
        self._ensure_open()
        raw_ids = {id(channel.raw) for channel in self._channels}
        physical = [
            channel.physical for channel in self._channels
            if channel.physical is not channel.raw and id(channel.physical) not in raw_ids
        ]
        return {
            "raw": _unique_nbytes(channel.raw for channel in self._channels),
            "time": _unique_nbytes(axis.values for axis in self._axes),
            "physical": _unique_nbytes(physical),
            "validity": _unique_nbytes(
                channel.validity for channel in self._channels
                if channel.validity is not None
            ),
        }

    def report_lifecycle(self, budget):
        """Tell a budget the four buffer kinds. Does not call reserve."""
        ledger = self.byte_ledger()
        return tuple(
            budget.record_lifecycle(ledger[kind], kind=kind, label=f"native {kind}")
            for kind in _LEDGER_KINDS
        )

    def with_derived_channel(self, *, original_name, group, index, axis_id, raw,
                             unit="", physical=None, validity=None,
                             conversion="identity", support_status="numeric",
                             parent=(), coordinates=()):
        """Return a new store. Axis buffers are shared; the new samples are a copy."""
        self._ensure_open()
        spec = ChannelSpec(
            group=group,
            index=index,
            original_name=original_name,
            axis_id=axis_id,
            raw=np.array(np.asarray(raw), copy=True),
            unit=unit,
            physical=None if physical is None else np.array(np.asarray(physical), copy=True),
            validity=None if validity is None else np.array(np.asarray(validity), copy=True),
            conversion=conversion,
            support_status=support_status,
            parent=parent,
            coordinates=coordinates,
        )
        kept = [
            ChannelSpec(
                group=channel.physical_key.group,
                index=channel.physical_key.index,
                original_name=channel.original_name,
                axis_id=channel.axis_id,
                raw=channel.raw,
                unit=channel.unit,
                physical=None if channel.physical is channel.raw else channel.physical,
                validity=channel.validity,
                conversion=channel.conversion,
                support_status=channel.support_status,
                parent=channel.physical_key.parent,
                coordinates=channel.physical_key.coordinates,
            )
            for channel in self._channels
        ]
        # Declared known/estimated must survive. Inferred status is recomputed.
        rebuilt = []
        for axis in self._axes:
            status = None
            fs_hz = None
            if axis.sampling.basis in {"declared", "declared_estimate", "declared_unknown"}:
                status = axis.sampling.status
                fs_hz = axis.sampling.fs_hz
            rebuilt.append(AxisSpec(
                axis.axis_id, axis.clock_source, axis.kind, axis.unit, axis.values,
                fs_status=status, fs_hz=fs_hz,
            ))
        return type(self).build(self.source_id, rebuilt, [*kept, spec])
