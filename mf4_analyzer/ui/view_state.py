"""Time-domain View state snapshots and list management.

ViewState records the interactive screen state for a time-domain chart. It is
kept widget-free so it can round-trip through JSON and be reused by future
project persistence.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from PyQt5.QtCore import QObject, pyqtSignal

# Default per-manager View cap. The real cap is per ViewManager instance
# (``max_views``); this stays the module-level default so the analysis sections
# (fft / fft_time / order) and every existing caller keep the historical 6.
MAX_VIEWS = 6

# Open Color hues, 12 entries so a 12-View section gets pairwise-distinct tab
# dots via ``_PALETTE[idx % len(_PALETTE)]``. The FIRST SIX MUST NOT CHANGE in
# value or order: archived projects store the resolved color in
# ViewState.tab_color, so re-ordering them would make View 1-6 of an old file
# disagree with a freshly created one.
_PALETTE = [
    "#2d7ff9", "#e8590c", "#2f9e44", "#9c36b5", "#e03131", "#1098ad",
    "#f08c00", "#c2255c", "#5c940d", "#5f3dc4", "#0ca678", "#495057",
]


ChannelKey = tuple[str, str]


@dataclass
class ViewState:
    name: str
    tab_color: str
    checked: list[ChannelKey] = field(default_factory=list)
    hidden_channels: list[ChannelKey] = field(default_factory=list)
    colors: dict[ChannelKey, str] = field(default_factory=dict)
    plot_mode: str = "subplot"
    cursor_mode: str = "off"
    xlim: tuple[float, float] | None = None
    ylims: dict[str, tuple[float, float]] = field(default_factory=dict)
    overlay_primary: ChannelKey | None = None
    axis_opts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["checked"] = [list(key) for key in self.checked]
        data["hidden_channels"] = [list(key) for key in self.hidden_channels]
        data["colors"] = {
            _encode_channel_key(key): value for key, value in self.colors.items()
        }
        data["xlim"] = list(self.xlim) if self.xlim is not None else None
        data["ylims"] = {key: list(value) for key, value in self.ylims.items()}
        data["overlay_primary"] = (
            list(self.overlay_primary) if self.overlay_primary is not None else None
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ViewState":
        return cls(
            name=data["name"],
            tab_color=data["tab_color"],
            checked=[_coerce_channel_key(key) for key in data.get("checked", [])],
            hidden_channels=[
                _coerce_channel_key(key)
                for key in data.get("hidden_channels", [])
            ],
            colors={
                _decode_channel_key(key): value
                for key, value in data.get("colors", {}).items()
            },
            plot_mode=data.get("plot_mode", "subplot"),
            cursor_mode=data.get("cursor_mode", "off"),
            xlim=_coerce_pair(data.get("xlim")),
            ylims={
                key: _coerce_pair(value) for key, value in data.get("ylims", {}).items()
            },
            overlay_primary=_coerce_optional_channel_key(data.get("overlay_primary")),
            axis_opts=data.get("axis_opts", {}),
        )


def _encode_channel_key(key: ChannelKey) -> str:
    fid, channel = key
    return json.dumps([fid, channel], ensure_ascii=False, separators=(",", ":"))


def _decode_channel_key(value: str) -> ChannelKey:
    return _coerce_channel_key(json.loads(value))


def _coerce_channel_key(value: Any) -> ChannelKey:
    fid, channel = value
    return (str(fid), str(channel))


def _coerce_optional_channel_key(value: Any) -> ChannelKey | None:
    if value is None:
        return None
    return _coerce_channel_key(value)


def _coerce_pair(value: Any) -> tuple[float, float] | None:
    if value is None:
        return None
    lo, hi = value
    return (lo, hi)


class ViewManager(QObject):
    views_changed = pyqtSignal()
    active_changed = pyqtSignal(int)
    split_changed = pyqtSignal(object)

    def __init__(
        self,
        parent: QObject | None = None,
        state_factory=None,
        *,
        max_views: int = MAX_VIEWS,
    ):
        super().__init__(parent)
        # Keyword-only: existing call sites pass `parent` (and `state_factory`)
        # positionally, so the cap must never take a positional slot.
        self.max_views = int(max_views)
        self._state_factory = state_factory or ViewState
        self.views: list = [self._make(0)]
        self.active = 0
        self.split_with: int | None = None
        self._split_pairs: dict[int, int] = {}

    def _make(self, idx: int):
        return self._state_factory(
            name=f"View {idx + 1}",
            tab_color=_PALETTE[idx % len(_PALETTE)],
        )

    def get(self, idx: int) -> ViewState:
        if not self._is_valid_index(idx):
            raise IndexError(idx)
        return self.views[idx]

    def new_view(self) -> int:
        if len(self.views) >= self.max_views:
            return -1
        idx = len(self.views)
        self.views.append(self._make(idx))
        self.views_changed.emit()
        self.set_active(idx)
        return idx

    def delete_view(self, idx: int) -> None:
        if len(self.views) <= 1 or not self._is_valid_index(idx):
            return

        old_split = self.split_with
        old_active = self.active
        pairs = self._snapshot_pairs_by_object()
        del self.views[idx]

        if self.active >= len(self.views):
            self.active = len(self.views) - 1
        elif self.active > idx:
            self.active -= 1

        self._restore_pairs_by_object(pairs)

        self.views_changed.emit()
        if self.split_with != old_split:
            self.split_changed.emit(self.split_with)
        if idx <= old_active:
            self.active_changed.emit(self.active)

    def duplicate(self, idx: int) -> int:
        if len(self.views) >= self.max_views or not self._is_valid_index(idx):
            return -1

        pairs = self._snapshot_pairs_by_object()
        active_state = self.views[self.active]
        source = self.views[idx]
        copied = type(source).from_dict(source.to_dict())
        copied.name = f"{source.name} 副本"
        self.views.insert(idx + 1, copied)
        self.active = self._index_of_state(active_state)
        self._restore_pairs_by_object(pairs)
        self.views_changed.emit()
        self.set_active(idx + 1)
        return idx + 1

    def rename(self, idx: int, name: str) -> None:
        if not self._is_valid_index(idx):
            return
        self.views[idx].name = (name or "").strip() or "未命名"
        self.views_changed.emit()

    def set_color(self, idx: int, hex_color: str) -> None:
        if not self._is_valid_index(idx):
            return
        self.views[idx].tab_color = hex_color
        self.views_changed.emit()

    def reorder(self, from_idx: int, to_idx: int) -> None:
        if (
            from_idx == to_idx
            or not self._is_valid_index(from_idx)
            or not self._is_valid_index(to_idx)
        ):
            return

        old_split = self.split_with
        active_state = self.views[self.active]
        pairs = self._snapshot_pairs_by_object()
        item = self.views.pop(from_idx)
        self.views.insert(to_idx, item)
        self.active = self._index_of_state(active_state)
        self._restore_pairs_by_object(pairs)
        self.views_changed.emit()
        if self.split_with != old_split:
            self.split_changed.emit(self.split_with)

    def set_active(self, idx: int) -> None:
        if not self._is_valid_index(idx) or idx == self.active:
            return
        self.active = idx
        self._set_active_split_from_pairs()
        self.active_changed.emit(idx)

    def set_split(self, idx: int | None) -> None:
        if idx is None:
            self.clear_split_for(self.active)
            return
        if idx == self.active or not self._is_valid_index(idx):
            return
        if self._split_pairs.get(self.active) == idx:
            return

        old_split = self.split_with
        self._split_pairs.pop(self.active, None)
        self._split_pairs[self.active] = idx
        self._set_active_split_from_pairs()
        if self.split_with != old_split:
            self.split_changed.emit(self.split_with)

    def clear_split_for(self, idx: int | None = None, *, emit: bool = True) -> None:
        target = self.active if idx is None else idx
        if not self._is_valid_index(target):
            return

        old_split = self.split_with
        self._split_pairs.pop(target, None)
        for host, source in list(self._split_pairs.items()):
            if source == target:
                self._split_pairs.pop(host, None)
        self._set_active_split_from_pairs()
        if emit and self.split_with != old_split:
            self.split_changed.emit(self.split_with)

    def partner_for(self, idx: int) -> int | None:
        if not self._is_valid_index(idx):
            return None
        partner = self._split_pairs.get(idx)
        if partner is None or not self._is_valid_index(partner):
            return None
        return partner

    def _set_active_split_from_pairs(self) -> None:
        self.split_with = self.partner_for(self.active)

    def _snapshot_pairs_by_object(self) -> list[tuple[ViewState, ViewState]]:
        out: list[tuple[ViewState, ViewState]] = []
        for host, source in self._split_pairs.items():
            if self._is_valid_index(host) and self._is_valid_index(source):
                out.append((self.views[host], self.views[source]))
        return out

    def _restore_pairs_by_object(
        self, pairs: list[tuple[ViewState, ViewState]]
    ) -> None:
        self._split_pairs = {}
        for host_state, source_state in pairs:
            host = self._index_of_state(host_state)
            source = self._index_of_state(source_state)
            if host >= 0 and source >= 0:
                self._split_pairs[host] = source
        self._set_active_split_from_pairs()

    def _index_of_state(self, state: ViewState) -> int:
        for idx, candidate in enumerate(self.views):
            if candidate is state:
                return idx
        return -1

    def _is_valid_index(self, idx: int) -> bool:
        return 0 <= idx < len(self.views)
