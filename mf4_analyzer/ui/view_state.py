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

MAX_VIEWS = 6
_PALETTE = ["#2d7ff9", "#e8590c", "#2f9e44", "#9c36b5", "#e03131", "#1098ad"]


ChannelKey = tuple[str, str]


@dataclass
class ViewState:
    name: str
    tab_color: str
    checked: list[ChannelKey] = field(default_factory=list)
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

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.views: list[ViewState] = [self._make(0)]
        self.active = 0
        self.split_with: int | None = None

    def _make(self, idx: int) -> ViewState:
        return ViewState(
            name=f"View {idx + 1}",
            tab_color=_PALETTE[idx % len(_PALETTE)],
        )

    def get(self, idx: int) -> ViewState:
        if not self._is_valid_index(idx):
            raise IndexError(idx)
        return self.views[idx]

    def new_view(self) -> int:
        if len(self.views) >= MAX_VIEWS:
            return -1
        idx = len(self.views)
        self.views.append(self._make(idx))
        self.views_changed.emit()
        self.set_active(idx)
        return idx

    def delete_view(self, idx: int) -> None:
        if len(self.views) <= 1 or not self._is_valid_index(idx):
            return

        old_active = self.active
        del self.views[idx]

        if self.active >= len(self.views):
            self.active = len(self.views) - 1
        elif self.active > idx:
            self.active -= 1

        split_cleared = self.split_with is not None
        self.split_with = None

        self.views_changed.emit()
        if split_cleared:
            self.split_changed.emit(None)
        if idx <= old_active:
            self.active_changed.emit(self.active)

    def duplicate(self, idx: int) -> int:
        if len(self.views) >= MAX_VIEWS or not self._is_valid_index(idx):
            return -1

        active_state = self.views[self.active]
        source = self.views[idx]
        copied = ViewState.from_dict(source.to_dict())
        copied.name = f"{source.name} 副本"
        self.views.insert(idx + 1, copied)
        self.active = self.views.index(active_state)
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

        active_state = self.views[self.active]
        split_state = (
            self.views[self.split_with] if self.split_with is not None else None
        )
        item = self.views.pop(from_idx)
        self.views.insert(to_idx, item)
        self.active = self.views.index(active_state)
        self.split_with = self.views.index(split_state) if split_state is not None else None
        self.views_changed.emit()

    def set_active(self, idx: int) -> None:
        if not self._is_valid_index(idx) or idx == self.active:
            return
        self.active = idx
        if self.split_with is not None:
            self.split_with = None
            self.split_changed.emit(None)
        self.active_changed.emit(idx)

    def set_split(self, idx: int | None) -> None:
        if idx == self.split_with:
            return
        if idx is not None and (idx == self.active or not self._is_valid_index(idx)):
            return
        self.split_with = idx
        self.split_changed.emit(idx)

    def _is_valid_index(self, idx: int) -> bool:
        return 0 <= idx < len(self.views)
