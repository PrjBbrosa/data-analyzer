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
        results.append(ReplayResult("applied", None, name, entry))
    return results


def apply_unlogged(fd, new_channels, removed_channels):
    """Session-only channel writes that have no replayable recipe."""
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
