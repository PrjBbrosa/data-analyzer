"""Per-source channel-edit log: record, compress, and replay.

The log stores how a derived channel was computed, never its samples.
Replay runs against whatever arrays the loader just produced.

Sessions currently have no interactive time-axis rebuild. ``d/dt``, ``∫dt``
and any expression that reads ``t`` therefore stay consistent with the values
shown at creation. A future time-axis edit must recompute every recipe that
reads the axis; otherwise the on-screen samples and the next project reopen
will disagree.
"""
from __future__ import annotations

import logging
import hashlib
import json

import numpy as np

from ..signal.channel_recipe import (
    DeriveEntry,
    RecipeError,
    RemoveEntry,
    entry_from_dict,
    evaluate_derive,
)

logger = logging.getLogger(__name__)

REASON_TEXT = {
    "missing_input": "输入通道不存在",
    "name_taken_loader": "输出名已被加载器通道占用",
    "name_taken": "输出名已被占用",
    "length_mismatch": "长度不符",
    "time_unavailable": "时间轴不可用",
    "non_numeric": "非数值输入",
    "expression_error": "表达式错误",
    "expression_all_invalid": "表达式结果全部无效",
    "upstream_skipped": "依赖的上游配方被跳过",
    "unrecognized": "条目无法识别",
    "cross_clock": "跨时钟：请指定目标轴、对齐方法和段。当前未应用",
    "known_gap": "已知缺口不能跨接。请选择段后再计算",
    "source_changed": "来源已变化。请按当前物理通道重新确认后再计算",
    "identity_unresolved": "物理通道不在当前来源，不能按显示名替补",
    "unapplied": "配方保持未应用",
    "alignment_unfrozen": "对齐方法尚未冻结，保持未应用",
    "byte_limit": "派生副本超过字节预算，未创建通道",
    "integer_precision": "整数样本不能精确表示为 float64，未创建通道",
}


class ReplayResult:
    def __init__(self, status, reason, channel, entry):
        self.status = status
        self.reason = reason
        self.channel = channel
        self.entry = entry

    @property
    def applied(self) -> bool:
        return self.status == "applied"


def _reason(code, detail=""):
    text = REASON_TEXT.get(code, REASON_TEXT["unrecognized"])
    if detail and code == "expression_error":
        return f"{text}: {detail}"
    return text


def _columns(frame):
    columns = getattr(frame, "columns", ())
    return list(columns)


def _assign(fd, name, values, unit):
    fd.data[name] = np.asarray(values, dtype=float)
    if name not in list(fd.channels):
        fd.channels.append(name)
    units = getattr(fd, "channel_units", None)
    if isinstance(units, dict):
        units[name] = "" if unit is None else str(unit)


def _drop(fd, name):
    if name in _columns(fd.data):
        fd.data = fd.data.drop(columns=[name])
    channels = getattr(fd, "channels", None)
    if isinstance(channels, list) and name in channels:
        channels.remove(name)
    units = getattr(fd, "channel_units", None)
    if isinstance(units, dict):
        units.pop(name, None)


def _ephemeral(fd):
    names = getattr(fd, "session_ephemeral_channels", None)
    if names is None:
        names = set()
        fd.session_ephemeral_channels = names
    return names


class ChannelEditLog:
    """Ordered derive / remove entries for one logical source."""

    def __init__(self, entries=None):
        self.entries = []
        for entry in entries or ():
            parsed = entry if isinstance(entry, (DeriveEntry, RemoveEntry)) else entry_from_dict(entry)
            self.entries.append(parsed)

    def to_json(self) -> list:
        return [entry.to_dict() for entry in self.entries]

    def active_derive(self, name):
        index = self._derive_index(str(name))
        if index is None:
            return None
        return self.entries[index]

    def record_derive(self, entry):
        if not isinstance(entry, DeriveEntry):
            entry = entry_from_dict(entry)
        if not isinstance(entry, DeriveEntry):
            raise RecipeError("unrecognized")
        self.entries.append(entry)
        return entry

    def record_remove(self, names):
        """Drop an unused derive entry; otherwise append a remove.

        Names are processed sinks-first, so deleting a derived channel and the
        channel it was built from in one step removes both recipes when
        nothing else still reads them.
        """
        targets = []
        seen = set()
        for name in names or ():
            text = str(name).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            targets.append(text)
        if not targets:
            return None
        remaining = set(targets)
        ordered = []
        while remaining:
            sinks = [
                name for name in targets
                if name in remaining and not self._blocked_by_remaining(name, remaining)
            ]
            if not sinks:
                ordered.extend(name for name in targets if name in remaining)
                break
            for name in sinks:
                remaining.discard(name)
                ordered.append(name)
        dropped = []
        removed = []
        for name in ordered:
            index = self._derive_index(name)
            if index is not None and not self._used_after(name, index):
                del self.entries[index]
                dropped.append(name)
            else:
                removed.append(name)
        if not removed:
            return None
        entry = RemoveEntry(tuple(removed))
        self.entries.append(entry)
        return entry

    def _derive_index(self, name):
        found = None
        for index, entry in enumerate(self.entries):
            if isinstance(entry, DeriveEntry) and entry.name == name:
                found = index
            elif isinstance(entry, RemoveEntry) and name in entry.names:
                found = None
        return found

    def _blocked_by_remaining(self, name, remaining):
        index = self._derive_index(name)
        if index is None:
            return False
        for other in remaining:
            if other == name:
                continue
            other_index = self._derive_index(other)
            if other_index is None or other_index <= index:
                continue
            other_entry = self.entries[other_index]
            if isinstance(other_entry, DeriveEntry) and name in other_entry.inputs():
                return True
        return False

    def _used_after(self, name, index):
        for entry in self.entries[index + 1:]:
            if isinstance(entry, DeriveEntry) and name in entry.inputs():
                return True
        return False


def _peek_derive_name(item):
    if isinstance(item, DeriveEntry):
        return item.name
    if isinstance(item, dict) and item.get("op") == "derive":
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _lookup(fd, name):
    if name not in _columns(fd.data):
        raise RecipeError("missing_input")
    series = fd.data[name]
    to_numpy = getattr(series, "to_numpy", None)
    try:
        if callable(to_numpy):
            try:
                return to_numpy(dtype=float, copy=True)
            except TypeError:
                return np.asarray(to_numpy(), dtype=float)
        values = getattr(series, "values", series)
        return np.asarray(values, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RecipeError("non_numeric") from exc


def _is_native(fd) -> bool:
    return bool(getattr(fd, "is_native", False) and getattr(fd, "native_store", None) is not None)


def _ensure_catalog(fd):
    return fd.logical_channels, fd.logical_hidden


def _segment_count(series) -> int:
    return len(tuple(getattr(series, "segments", ()) or ()))


def _invalid_mask(series):
    validity = getattr(series, "validity", None)
    if validity is None:
        return None
    return np.asarray(validity, dtype=bool)


def _too_wide_integer(values) -> bool:
    from ..signal.numeric_precision import integers_exact_in_float64
    return not integers_exact_in_float64(values)


def _native_series(fd, name, representation, segment, staged):
    from .signal_access import SignalAccessError, read_signal

    try:
        if staged and name in staged:
            from .signal_access import read_logical_channel
            record = staged[name]
            if not isinstance(record, dict) or "time" not in record:
                raise RecipeError("time_unavailable")
            series = read_logical_channel(record, segment=segment, representation=representation)
        else:
            series = read_signal(
                fd, name, representation=representation or "physical", segment=segment,
            )
    except SignalAccessError as exc:
        if "segment" in str(exc):
            raise RecipeError("known_gap", str(exc)) from exc
        raise RecipeError("missing_input", str(exc)) from exc
    values = series.values
    if _too_wide_integer(values):
        raise RecipeError("integer_precision")
    return series, _invalid_mask(series), _segment_count(series), series.public_name


def _axis_of(fd, name, staged):
    if staged and name in staged:
        return staged[name]["axis_id"]
    if name in fd.logical_channels:
        return fd.logical_channels[name]["axis_id"]
    return fd.native_store.channel(name).axis_id


def evaluate_native_channel(fd, entry, staged=None):
    """Return one complete, immutable recipe result, for staging or replay."""
    from ..signal.channel_recipe import derive_from_dict
    from .native_signal_store import NativeContractError, build_segments
    from ..analysis_signal_prepare import DEFAULT_PREPARE_BYTE_LIMIT, preflight_prepare

    if not isinstance(entry, DeriveEntry):
        entry = derive_from_dict(entry)
    if entry.apply_status == "unapplied":
        raise RecipeError("unapplied")
    store = fd.native_store
    if entry.source_revision and entry.source_revision != store.revision:
        raise RecipeError("source_changed")
    for token in entry.input_tokens or ():
        try:
            store.channel(token)
        except NativeContractError as exc:
            raise RecipeError("identity_unresolved") from exc
    representation = entry.representation or "physical"
    names = list(dict.fromkeys(entry.inputs()))
    if not names:
        raise RecipeError("time_unavailable")
    inputs = {name: _native_series(fd, name, representation, entry.segment, staged)[0]
              for name in names}
    first = inputs[names[0]]
    axis_id = _axis_of(fd, names[0], staged)
    if entry.kind != "single":
        if entry.method not in {None, "direct"}:
            raise RecipeError("alignment_unfrozen")
        if entry.method != "direct" or any(_axis_of(fd, name, staged) != axis_id for name in names):
            raise RecipeError("cross_clock")
    for series in inputs.values():
        if series.values.ndim != 1 or series.values.shape != first.time.shape:
            raise RecipeError("length_mismatch")
        if not np.array_equal(series.time, first.time):
            raise RecipeError("cross_clock")
    # Reuse the native prepare admission policy before recipe copies. Existing
    # applied/staged results consume the same bounded working-set allowance.
    retained = {id(record[key]): record[key].nbytes
                for record in (*fd.logical_channels.values(), *(staged or {}).values())
                for key in ("time", "values", "validity") if record[key] is not None}
    decision = preflight_prepare(sample_count=len(first.time), copies=4 + len(inputs),
                                byte_limit=DEFAULT_PREPARE_BYTE_LIMIT - sum(retained.values()))
    if not decision["admitted"]:
        raise RecipeError("byte_limit")
    invalid = np.zeros(first.time.shape, dtype=bool)
    for series in inputs.values():
        invalid |= ~np.isfinite(series.values)
        if series.validity is not None:
            if series.validity.shape != series.values.shape:
                raise RecipeError("length_mismatch")
            invalid |= series.validity
    neighborhood = entry.kind == "single" and entry.fn in {"derivative", "integral", "moving_avg"}
    if neighborhood and (len(first.segments) > 1 or invalid.any()):
        raise RecipeError("known_gap")
    def lookup(name):
        series = inputs[name]
        if invalid.any():
            values = np.array(series.values, dtype=float, copy=True)
            values[invalid] = np.nan
            return values
        return series.values
    produced = evaluate_derive(entry, first.time, lookup)
    if produced.shape != first.time.shape:
        raise RecipeError("length_mismatch")
    invalid |= ~np.isfinite(produced)
    if invalid.any():
        produced[invalid] = np.nan
    produced.setflags(write=False)
    invalid.setflags(write=False)
    payload = {"recipe": entry.to_dict(), "inputs": [s.revision for s in inputs.values()],
               "axis": axis_id, "policy": "native-derived-1"}
    revision = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    # A segment result has its own extent even when it inherits the source clock.
    if entry.segment is not None:
        axis_id = f"{axis_id}:segment:{entry.segment}"
    return dict(time=first.time, values=produced, validity=invalid if invalid.any() else None,
                segments=build_segments(first.time), unit=entry.unit, axis_id=axis_id,
                representation=representation, sampling=first.sampling, revision=revision,
                physical_key=("derived", entry.name), public_name=entry.name,
                source_id=store.source_id)


def evaluate_native_entry(fd, entry, staged=None):
    """Compatibility result; native staging retains evaluate_native_channel's DTO."""
    result = evaluate_native_channel(fd, entry, staged)
    return result["values"], result["time"], result["axis_id"], result["representation"]


def _hide_name(fd, name):
    catalog, hidden = _ensure_catalog(fd)
    catalog.pop(name, None)
    fd.channel_units.pop(name, None)
    store = fd.native_store
    if name in set(store.public_names()):
        hidden.add(name)
    _ephemeral(fd).discard(name)


def _replay_native(fd, items) -> list:
    from ..signal.channel_recipe import DeriveEntry, RemoveEntry

    catalog, _hidden = _ensure_catalog(fd)
    created = set()
    skipped_outputs = set()
    results = []
    for item in items:
        try:
            entry = item if isinstance(item, (DeriveEntry, RemoveEntry)) else entry_from_dict(item)
        except RecipeError:
            name = _peek_derive_name(item)
            if name:
                skipped_outputs.add(name)
            reason = _reason("unrecognized")
            logger.warning("channel edit skipped: %s (%s)", name or "<unknown>", reason)
            results.append(ReplayResult("skipped", reason, name, None))
            continue
        if isinstance(entry, RemoveEntry):
            for name in entry.names:
                _hide_name(fd, name)
                created.discard(name)
            results.append(ReplayResult("applied", None, ", ".join(entry.names), entry))
            continue
        name = entry.name
        upstream = [item_name for item_name in entry.inputs() if item_name in skipped_outputs]
        if upstream:
            skipped_outputs.add(name)
            reason = _reason("upstream_skipped")
            logger.warning("channel edit skipped: %s (%s)", name, reason)
            results.append(ReplayResult("skipped", reason, name, entry))
            continue
        if name in catalog or (
            name in set(fd.native_store.public_names()) and name not in fd.logical_hidden
        ):
            skipped_outputs.add(name)
            reason = _reason("name_taken")
            logger.warning("channel edit skipped: %s (%s)", name, reason)
            results.append(ReplayResult("skipped", reason, name, entry))
            continue
        try:
            record = evaluate_native_channel(fd, entry)
        except RecipeError as exc:
            skipped_outputs.add(name)
            reason = _reason(exc.code, str(exc) if exc.code == "expression_error" else "")
            logger.warning("channel edit skipped: %s (%s)", name, reason)
            results.append(ReplayResult("skipped", reason, name, entry))
            continue
        catalog[name] = record
        fd.channel_units[name] = entry.unit
        created.add(name)
        skipped_outputs.discard(name)
        results.append(ReplayResult("applied", None, name, entry))
    return results


def replay(fd, entries) -> list:
    """Apply ``entries`` to ``fd`` and return one result per entry.

    Programming errors propagate. Data errors become a skipped result and
    do not stop later entries.
    """
    if isinstance(entries, ChannelEditLog):
        items = list(entries.entries)
    elif isinstance(entries, (list, tuple)):
        items = list(entries)
    else:
        logger.warning("channel edit skipped: <unknown> (%s)", _reason("unrecognized"))
        return [ReplayResult("skipped", _reason("unrecognized"), None, None)]

    if _is_native(fd):
        return _replay_native(fd, items)

    original = set(_columns(fd.data))
    created = set()
    released = set()
    skipped_outputs = set()
    results = []
    for item in items:
        try:
            entry = item if isinstance(item, (DeriveEntry, RemoveEntry)) else entry_from_dict(item)
        except RecipeError:
            name = _peek_derive_name(item)
            if name:
                skipped_outputs.add(name)
            reason = _reason("unrecognized")
            logger.warning("channel edit skipped: %s (%s)", name or "<unknown>", reason)
            results.append(ReplayResult("skipped", reason, name, None))
            continue
        if isinstance(entry, RemoveEntry):
            for name in entry.names:
                _drop(fd, name)
                _ephemeral(fd).discard(name)
                created.discard(name)
                released.add(name)
            results.append(ReplayResult("applied", None, ", ".join(entry.names), entry))
            continue
        name = entry.name
        upstream = [item_name for item_name in entry.inputs() if item_name in skipped_outputs]
        if upstream:
            skipped_outputs.add(name)
            reason = _reason("upstream_skipped")
            logger.warning("channel edit skipped: %s (%s)", name, reason)
            results.append(ReplayResult("skipped", reason, name, entry))
            continue
        if name in _columns(fd.data):
            skipped_outputs.add(name)
            # A loader column still occupying the name is not the same conflict
            # as a column this replay already deleted and then created.
            code = (
                "name_taken_loader"
                if name in original and name not in released and name not in created
                else "name_taken"
            )
            reason = _reason(code)
            logger.warning("channel edit skipped: %s (%s)", name, reason)
            results.append(ReplayResult("skipped", reason, name, entry))
            continue
        try:
            values = evaluate_derive(entry, getattr(fd, "time_array", None), lambda key: _lookup(fd, key))
        except RecipeError as exc:
            skipped_outputs.add(name)
            reason = _reason(exc.code, str(exc) if exc.code == "expression_error" else "")
            logger.warning("channel edit skipped: %s (%s)", name, reason)
            results.append(ReplayResult("skipped", reason, name, entry))
            continue
        width = len(fd.data)
        if values.size != width:
            skipped_outputs.add(name)
            reason = _reason("length_mismatch")
            logger.warning("channel edit skipped: %s (%s)", name, reason)
            results.append(ReplayResult("skipped", reason, name, entry))
            continue
        _assign(fd, name, values, entry.unit)
        _ephemeral(fd).discard(name)
        created.add(name)
        # A later generation of this name can recover independently of the
        # failed generation. Only subsequent consumers see the recovery.
        skipped_outputs.discard(name)
        results.append(ReplayResult("applied", None, name, entry))
    return results


def apply_unlogged(fd, new_channels, removed_channels):
    """Session-only channel writes that have no replayable recipe."""
    if _is_native(fd):
        if new_channels:
            # Values alone cannot establish a native time/quality identity.
            raise RecipeError("time_unavailable")
        for name in removed_channels or ():
            _hide_name(fd, name)
        return
    ephemeral = _ephemeral(fd)
    for name, payload in (new_channels or {}).items():
        values, unit = payload
        _assign(fd, name, values, unit)
        ephemeral.add(name)
    for name in removed_channels or ():
        _drop(fd, name)
        ephemeral.discard(name)


def fold_entries(log: ChannelEditLog, entries):
    """Merge one dialog session into the source log, compressing removes."""
    if isinstance(entries, ChannelEditLog):
        entries = entries.entries
    for entry in entries or ():
        parsed = entry if isinstance(entry, (DeriveEntry, RemoveEntry)) else entry_from_dict(entry)
        if isinstance(parsed, DeriveEntry):
            log.record_derive(parsed)
        else:
            log.record_remove(parsed.names)
    return log
