"""Time-domain View state snapshots and list management.

ViewState records the interactive screen state for a time-domain chart. It is
kept widget-free so it can round-trip through JSON and be reused by future
project persistence.

``checked`` stores composite channel membership for a View. Drawing order is
not stored here: the workspace ``NavigatorOrderState`` sorts checked keys
immediately before a TimeDomain payload is built.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from PyQt5.QtCore import QObject, pyqtSignal

from mf4_analyzer.ui_kit.ticks_math import _DEGENERATE_SPAN_RATIO

from .time_curve_bindings import TimeCurveBinding, parse_curve_bindings
from .view_overlay_state import normalize_cursor_placement, normalize_remarks


X_VIEWPORT_WWT_NATIVE = "wwt_native"
X_VIEWPORT_USER = "user"
X_VIEWPORT_ORDINARY = "ordinary"


@dataclass(frozen=True)
class XViewportIntent:
    """Viewport provenance: current ``ViewState.xlim`` is separate from Home.

    ``source='wwt_native'`` keeps a file-defined home range even after the user
    pans or zooms. Ordinary views leave this ``None``.
    """

    source: str = X_VIEWPORT_ORDINARY
    initial_range: tuple[float, float] | None = None
    home_range: tuple[float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": str(self.source or X_VIEWPORT_ORDINARY),
            "initial_range": (
                list(self.initial_range) if self.initial_range is not None else None
            ),
            "home_range": list(self.home_range) if self.home_range is not None else None,
        }

    @classmethod
    def from_mapping(cls, data: Any) -> "XViewportIntent | None":
        if data is None:
            return None
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            return None
        source = str(data.get("source") or "").strip() or X_VIEWPORT_ORDINARY
        if source not in {
            X_VIEWPORT_WWT_NATIVE, X_VIEWPORT_USER, X_VIEWPORT_ORDINARY,
        }:
            source = X_VIEWPORT_ORDINARY
        initial = _coerce_pair(data.get("initial_range"))
        home = _coerce_pair(data.get("home_range"))
        if source == X_VIEWPORT_ORDINARY and initial is None and home is None:
            return None
        return cls(source=source, initial_range=initial, home_range=home)


def trusted_wwt_native_intent(intent: Any) -> bool:
    parsed = XViewportIntent.from_mapping(intent)
    return (
        parsed is not None
        and parsed.source == X_VIEWPORT_WWT_NATIVE
        and parsed.home_range is not None
    )


# Analysis-section and compatibility default. The real cap is per
# ViewManager instance (``max_views``); time-domain uses
# TIME_DOMAIN_MAX_VIEWS. Narrow bars still degrade via ViewTabBar's
# roomy → compact → overflow path.
MAX_VIEWS = 12
TIME_DOMAIN_MAX_VIEWS = 24  # time-domain workspace only

# Open Color hues, 12 entries so a 12-View section gets pairwise-distinct tab
# dots. Indexes 12–23 cycle the same 12. The FIRST SIX MUST NOT CHANGE in
# value or order: archived projects store the resolved color in
# ViewState.tab_color, so re-ordering them would make View 1-6 of an old file
# disagree with a freshly created one.
_PALETTE = [
    "#2d7ff9", "#e8590c", "#2f9e44", "#9c36b5", "#e03131", "#1098ad",
    "#f08c00", "#c2255c", "#5c940d", "#5f3dc4", "#0ca678", "#495057",
]


def default_view_tab_color(index: int) -> str:
    """Palette color for a View at ``index`` (0-based). Cycles every 12."""
    return _PALETTE[index % len(_PALETTE)]


ChannelKey = tuple[str, str]


def is_reusable_blank_view(state: "ViewState") -> bool:
    """True for an untouched initial time View that import may replace."""
    if state.attached_file_ids or state.checked or state.hidden_channels:
        return False
    if state.curve_bindings or state.remarks or state.cursor_placement:
        return False
    if getattr(state, "hidden_curve_binding_ids", None):
        return False
    if state.xlim is not None or state.ylims:
        return False
    if getattr(state, "x_viewport_intent", None) is not None:
        return False
    if state.cursor_mode != "off" or state.plot_mode != "subplot":
        return False
    if state.overlay_primary is not None:
        return False
    axis_opts = state.axis_opts or {}
    return not any(
        key not in {"tick_density"} and bool(axis_opts.get(key))
        for key in axis_opts
    )


@dataclass
class ViewState:
    name: str
    tab_color: str
    attached_file_ids: list[str] = field(default_factory=list)
    checked: list[ChannelKey] = field(default_factory=list)
    hidden_channels: list[ChannelKey] = field(default_factory=list)
    colors: dict[ChannelKey, str] = field(default_factory=dict)
    plot_mode: str = "subplot"
    cursor_mode: str = "off"
    xlim: tuple[float, float] | None = None
    ylims: dict[str, tuple[float, float]] = field(default_factory=dict)
    overlay_primary: ChannelKey | None = None
    axis_opts: dict[str, Any] = field(default_factory=dict)
    # Appended to preserve the positional constructor contract of older
    # callers while giving persisted TimeDomain views a stable identity.
    view_id: str = field(default_factory=lambda: str(uuid4()))
    remarks: list = field(default_factory=list)
    cursor_placement: dict | None = None
    curve_bindings: list[TimeCurveBinding] = field(default_factory=list)
    hidden_curve_binding_ids: list[str] = field(default_factory=list)
    x_viewport_intent: XViewportIntent | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["attached_file_ids"] = [str(fid) for fid in self.attached_file_ids]
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
        data["remarks"] = normalize_remarks(self.remarks)
        data["cursor_placement"] = normalize_cursor_placement(
            self.cursor_placement, cursor_mode=self.cursor_mode
        )
        data["curve_bindings"] = [
            binding.to_dict() for binding in self.curve_bindings
        ]
        intent = self.x_viewport_intent
        data["x_viewport_intent"] = (
            intent.to_dict() if isinstance(intent, XViewportIntent) else None
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ViewState":
        return cls(
            name=data["name"],
            tab_color=data["tab_color"],
            view_id=str(data.get("view_id") or uuid4()),
            attached_file_ids=[
                str(fid) for fid in data.get("attached_file_ids", [])
            ],
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
                key: pair
                for key, value in data.get("ylims", {}).items()
                if (pair := _coerce_pair(value)) is not None
            },
            overlay_primary=_coerce_optional_channel_key(data.get("overlay_primary")),
            axis_opts=data.get("axis_opts", {}),
            remarks=normalize_remarks(data.get("remarks")),
            cursor_placement=normalize_cursor_placement(
                data.get("cursor_placement"),
                cursor_mode=data.get("cursor_mode", "off"),
            ),
            curve_bindings=parse_curve_bindings(data.get("curve_bindings")),
            hidden_curve_binding_ids=_coerce_id_list(
                data.get("hidden_curve_binding_ids")
            ),
            x_viewport_intent=XViewportIntent.from_mapping(
                data.get("x_viewport_intent")
            ),
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


def _coerce_id_list(value: Any) -> list[str]:
    """Preserve first-seen hidden binding ids; ignore non-iterables and blanks."""
    if value is None or isinstance(value, (str, bytes)):
        return []
    try:
        items = list(value)
    except TypeError:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _coerce_pair(value: Any) -> tuple[float, float] | None:
    """Validate a persisted ``(lo, hi)`` window.

    Illegal / degenerate pairs return ``None`` so restore callers silently
    skip them and fall back to auto-framing. The relative-span gate reuses
    ``ui_kit.ticks_math._DEGENERATE_SPAN_RATIO`` — do not invent a second
    threshold here.
    """
    if value is None:
        return None
    try:
        lo, hi = value
        lo_f = float(lo)
        hi_f = float(hi)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lo_f) and math.isfinite(hi_f)):
        return None
    span = hi_f - lo_f
    magnitude = max(abs(lo_f), abs(hi_f))
    if not (span > magnitude * _DEGENERATE_SPAN_RATIO and span > 0.0):
        return None
    return (lo_f, hi_f)


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
            tab_color=default_view_tab_color(idx),
        )

    def get(self, idx: int) -> ViewState:
        if not self._is_valid_index(idx):
            raise IndexError(idx)
        return self.views[idx]

    def insert_states(
        self,
        states: list[ViewState],
        *,
        reuse_blank: bool,
        active_offset: int = 0,
    ) -> list[int]:
        """Insert ``states`` in one mutation and emit ``views_changed`` once.

        Capacity is checked before any mutation. ``-1`` is never returned for
        a partial insert: either every kept state is committed, or nothing is.
        """
        incoming = list(states or [])
        if not incoming:
            return []
        reusable = 1 if reuse_blank and self.views else 0
        available = self.max_views - len(self.views) + reusable
        if available <= 0:
            return []
        incoming = incoming[:available]
        indexes: list[int] = []
        start = 0
        if reusable:
            self.views[0] = incoming[0]
            indexes.append(0)
            start = 1
        for state in incoming[start:]:
            self.views.append(state)
            indexes.append(len(self.views) - 1)
        self.views_changed.emit()
        if indexes:
            target = indexes[max(0, min(int(active_offset), len(indexes) - 1))]
            if target == self.active:
                self.active_changed.emit(target)
            else:
                self.set_active(target)
        return indexes

    def new_view(self, *, activate: bool = True) -> int:
        """Append a fresh View and, normally, make it active.

        The UI may defer activation by one event-loop turn on a frozen Windows
        build so a native canvas rebuild never runs inside the ``+`` button's
        mouse-release handling.  State-only callers retain the historical
        immediate-activation behaviour by default.
        """
        if len(self.views) >= self.max_views:
            return -1
        idx = len(self.views)
        self.views.append(self._make(idx))
        self.views_changed.emit()
        if activate:
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
        if hasattr(copied, "view_id"):
            copied.view_id = str(uuid4())
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
