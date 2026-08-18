"""Workspace-level file and channel order. Qt-free.

``FileNavigator`` and the channel tree are projections of this owner. Plot
order is derived here; ``ViewState`` does not store a parallel plot_order.
"""
from __future__ import annotations

from typing import Iterable, Sequence


Placement = str
BEFORE = "before"
AFTER = "after"
_PLACEMENTS = frozenset({BEFORE, AFTER})


def _as_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _unique_texts(values: Iterable) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values or ():
        text = _as_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _sequence(value) -> list:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [value]
    if isinstance(value, Iterable):
        return list(value)
    return [value]


def _relocate_item(items: list[str], item: str, target: str, placement: str) -> list[str] | None:
    if placement not in _PLACEMENTS or item == target:
        return None
    try:
        source_at = items.index(item)
        target_at = items.index(target)
    except ValueError:
        return None
    remaining = list(items)
    remaining.pop(source_at)
    if source_at < target_at:
        target_at -= 1
    insert_at = target_at if placement == BEFORE else target_at + 1
    if insert_at == source_at:
        return None
    remaining.insert(insert_at, item)
    return remaining


class NavigatorOrderState:
    """Single owner of workspace file-block order and per-fid channel order."""

    def __init__(self) -> None:
        self._file_fids: list[str] = []
        self._channel_order_by_fid: dict[str, list[str]] = {}

    def file_fids(self) -> tuple[str, ...]:
        return tuple(self._file_fids)

    def channel_order(self, fid) -> tuple[str, ...]:
        return tuple(self._channel_order_by_fid.get(_as_text(fid), ()))

    def channel_order_by_fid(self) -> dict[str, list[str]]:
        return {fid: list(channels) for fid, channels in self._channel_order_by_fid.items()}

    def register_file(self, fid, channels: Sequence | None = None) -> bool:
        key = _as_text(fid)
        if not key:
            return False
        if key in self._channel_order_by_fid or key in self._file_fids:
            return False
        self._file_fids.append(key)
        self._channel_order_by_fid[key] = _unique_texts(channels or ())
        return True

    def refresh_channels(self, fid, channels: Sequence | None = None) -> None:
        key = _as_text(fid)
        if not key:
            return
        loader = _unique_texts(channels or ())
        if key not in self._channel_order_by_fid:
            self.register_file(key, loader)
            return
        live = set(loader)
        kept = [name for name in self._channel_order_by_fid[key] if name in live]
        kept_set = set(kept)
        kept.extend(name for name in loader if name not in kept_set)
        self._channel_order_by_fid[key] = kept

    def apply_channel_order(self, fid, saved_order: Sequence | None = None) -> None:
        key = _as_text(fid)
        if not key or key not in self._channel_order_by_fid:
            return
        current = list(self._channel_order_by_fid[key])
        current_set = set(current)
        restored = [name for name in _unique_texts(saved_order or ()) if name in current_set]
        restored_set = set(restored)
        restored.extend(name for name in current if name not in restored_set)
        self._channel_order_by_fid[key] = restored

    def move_channel_among_visible(
        self,
        fid,
        channel,
        target_channel,
        placement: Placement,
        visible_channels: Sequence | None = None,
    ) -> bool:
        """Reorder among ``visible_channels``; keep hidden names in place."""
        key = _as_text(fid)
        source = _as_text(channel)
        target = _as_text(target_channel)
        if not key or not source or not target:
            return False
        full = list(self._channel_order_by_fid.get(key, ()))
        visible = set(_unique_texts(visible_channels or ()))
        visible_seq = [name for name in full if name in visible]
        relocated = _relocate_item(visible_seq, source, target, placement)
        if relocated is None:
            return False
        nxt = iter(relocated)
        woven = [next(nxt) if name in visible else name for name in full]
        if woven == full:
            return False
        self._channel_order_by_fid[key] = woven
        return True

    def remove_fid(self, fid) -> None:
        key = _as_text(fid)
        if not key:
            return
        self._file_fids = [item for item in self._file_fids if item != key]
        self._channel_order_by_fid.pop(key, None)

    def set_file_order(self, fids) -> None:
        """Replace file-block order, appending any registered fids that were omitted."""
        known = set(self._channel_order_by_fid)
        desired = [fid for fid in _unique_texts(fids) if fid in known]
        extras = [fid for fid in self._file_fids if fid not in set(desired)]
        self._file_fids = desired + extras

    def move_file_block(self, fids, target, placement: Placement) -> bool:
        if placement not in _PLACEMENTS:
            return False
        current = list(self._file_fids)
        wanted = set(_unique_texts(_sequence(fids)))
        block = [fid for fid in current if fid in wanted]
        if not block:
            return False
        target_ids = [fid for fid in _unique_texts(_sequence(target)) if fid in current]
        if not target_ids:
            return False
        remaining = [fid for fid in current if fid not in wanted]
        remaining_index = {fid: idx for idx, fid in enumerate(remaining)}
        anchors = [fid for fid in target_ids if fid in remaining_index]
        if not anchors:
            return False
        if placement == BEFORE:
            insert_at = remaining_index[anchors[0]]
        else:
            insert_at = remaining_index[anchors[-1]] + 1
        proposed = remaining[:insert_at] + block + remaining[insert_at:]
        if proposed == current:
            return False
        self._file_fids = proposed
        return True

    def move_channel(self, fid, channel, target_channel, placement: Placement) -> bool:
        key = _as_text(fid)
        source = _as_text(channel)
        target = _as_text(target_channel)
        if not key or not source or not target:
            return False
        current = list(self._channel_order_by_fid.get(key, ()))
        relocated = _relocate_item(current, source, target, placement)
        if relocated is None:
            return False
        self._channel_order_by_fid[key] = relocated
        return True

    def order_checked(self, checked: Sequence | None = None) -> list[tuple]:
        entries: list[tuple[str, str, tuple]] = []
        seen: set[tuple[str, str]] = set()
        for raw in checked or ():
            parsed = _parse_checked_entry(raw)
            if parsed is None:
                continue
            fid, channel, identity = parsed
            key = (fid, channel)
            if key in seen:
                continue
            seen.add(key)
            entries.append((fid, channel, identity))

        grouped: dict[str, list[tuple[str, tuple]]] = {}
        for fid, channel, identity in entries:
            grouped.setdefault(fid, []).append((channel, identity))

        ordered: list[tuple] = []
        consumed: set[str] = set()
        for fid in self._file_fids:
            consumed.add(fid)
            ordered.extend(_order_fid_entries(grouped.get(fid, ()), self._channel_order_by_fid.get(fid, ())))
        for fid, _channel, _identity in entries:
            if fid in consumed:
                continue
            consumed.add(fid)
            ordered.extend(_order_fid_entries(grouped.get(fid, ()), self._channel_order_by_fid.get(fid, ())))
        return ordered


def _parse_checked_entry(raw) -> tuple[str, str, tuple] | None:
    if raw is None or isinstance(raw, (str, bytes)):
        return None
    try:
        fid = _as_text(raw[0])
        channel = _as_text(raw[1])
    except (TypeError, IndexError, KeyError):
        return None
    if not fid or not channel:
        return None
    extra = tuple(raw[2:]) if len(raw) > 2 else ()
    identity = (fid, channel, *extra)
    return fid, channel, identity


def _order_fid_entries(
    group: Sequence[tuple[str, tuple]],
    channel_order: Sequence[str],
) -> list[tuple]:
    rank = {name: idx for idx, name in enumerate(channel_order)}
    known = [item for item in group if item[0] in rank]
    unknown = [item for item in group if item[0] not in rank]
    known.sort(key=lambda item: rank[item[0]])
    return [identity for _channel, identity in known + unknown]
