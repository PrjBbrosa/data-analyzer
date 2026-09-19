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
from typing import Any, Iterable
from uuid import uuid4

from PyQt5.QtCore import QObject, pyqtSignal

from mf4_analyzer.ui_kit.ticks_math import _DEGENERATE_SPAN_RATIO

from .chart_appearance_model import (
    appearance_binding_key,
    appearance_channel_key,
    appearance_group_key,
    normalize_appearance_axis_key,
    parse_appearance_axis_key,
)
from .pinned_cursor_state import (
    PinnedCursorCollection,
    collection_from_dict,
    collection_to_dict,
    duplicate_collection,
    empty_collection,
)
from .time_curve_bindings import TimeCurveBinding, parse_curve_bindings
from .view_overlay_state import normalize_cursor_placement, normalize_remarks


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

_DEFAULT_FILTER_SPEC = {
    "kind": "low",
    "order": 4,
    "cutoff": 100.0,
    "cutoff_lo": 100.0,
    "cutoff_hi": 2000.0,
}
_FILTER_KINDS = frozenset({"low", "high", "band", "bandstop"})


def default_time_filter() -> dict[str, Any]:
    """Fresh time-domain filter intent: off, panel widget defaults kept."""
    return {
        "enabled": False,
        "spec": dict(_DEFAULT_FILTER_SPEC),
        "show_original": True,
        "show_filtered": True,
    }


def normalize_time_filter(value: Any) -> dict[str, Any]:
    """Return a serializable copy of one View's time-domain filter intent."""
    payload = default_time_filter()
    if not isinstance(value, dict):
        return payload
    raw_spec = value.get("spec") if isinstance(value.get("spec"), dict) else {}
    kind = str(raw_spec.get("kind", payload["spec"]["kind"]) or "low")
    if kind not in _FILTER_KINDS:
        kind = "low"
    payload["enabled"] = bool(value.get("enabled", False))
    payload["show_original"] = bool(value.get("show_original", True))
    payload["show_filtered"] = bool(value.get("show_filtered", True))
    payload["spec"] = {
        "kind": kind,
        "order": _coerce_filter_order(raw_spec.get("order")),
        "cutoff": _coerce_filter_float(
            raw_spec.get("cutoff"), payload["spec"]["cutoff"]
        ),
        "cutoff_lo": _coerce_filter_float(
            raw_spec.get("cutoff_lo"), payload["spec"]["cutoff_lo"]
        ),
        "cutoff_hi": _coerce_filter_float(
            raw_spec.get("cutoff_hi"), payload["spec"]["cutoff_hi"]
        ),
    }
    return payload


def is_default_time_filter(value: Any) -> bool:
    return normalize_time_filter(value) == default_time_filter()


def default_chart_appearance() -> dict[str, Any]:
    """Fresh time-domain chart-options appearance: linear, no per-axis overrides."""
    return {
        "x_scale": "linear",
        "axes": {},
        "companion_colors": {},
    }


def normalize_chart_appearance(value: Any) -> dict[str, Any]:
    """Return a serializable copy of one View's chart-options appearance."""
    payload = default_chart_appearance()
    if not isinstance(value, dict):
        return payload
    payload["x_scale"] = _normalize_scale(value.get("x_scale"))
    axes_in = value.get("axes")
    if isinstance(axes_in, dict):
        axes: dict[str, dict[str, Any]] = {}
        for raw_key, raw_spec in axes_in.items():
            key = normalize_appearance_axis_key(raw_key)
            spec = _normalize_axis_appearance_spec(raw_spec)
            if key and spec:
                axes[key] = spec
        payload["axes"] = axes
    colors_in = value.get("companion_colors")
    if isinstance(colors_in, dict):
        colors: dict[str, str] = {}
        for raw_key, color in colors_in.items():
            encoded = _coerce_appearance_channel_color_key(raw_key)
            text = str(color or "").strip()
            if encoded and text:
                colors[encoded] = text
        payload["companion_colors"] = colors
    return payload


def is_default_chart_appearance(value: Any) -> bool:
    return normalize_chart_appearance(value) == default_chart_appearance()


def prune_chart_appearance(
    value: Any,
    *,
    removed_fids: Iterable[Any] | None = None,
    removed_channels: Iterable[Any] | None = None,
    kept_channels: Iterable[Any] | None = None,
    live_group_ids: Iterable[Any] | None = None,
    live_binding_ids: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Drop appearance keys whose channel/file/group/binding identity is gone."""
    appearance = normalize_chart_appearance(value)
    removed_fid_set = {str(fid) for fid in (removed_fids or ())}
    removed_channel_set = {
        (str(item[0]), str(item[1]))
        for item in (removed_channels or ())
        if isinstance(item, (list, tuple)) and len(item) >= 2
    }
    kept_channel_set = None
    if kept_channels is not None:
        kept_channel_set = {
            (str(item[0]), str(item[1]))
            for item in kept_channels
            if isinstance(item, (list, tuple)) and len(item) >= 2
        }
    live_groups = (
        {str(gid) for gid in live_group_ids}
        if live_group_ids is not None else None
    )
    live_bindings = (
        {str(bid) for bid in live_binding_ids}
        if live_binding_ids is not None else None
    )

    def _keep_channel(fid: str, channel: str) -> bool:
        pair = (str(fid), str(channel))
        if pair[0] in removed_fid_set:
            return False
        if pair in removed_channel_set:
            return False
        if kept_channel_set is not None and pair not in kept_channel_set:
            return False
        return True

    axes: dict[str, dict[str, Any]] = {}
    for key, spec in appearance["axes"].items():
        parsed = parse_appearance_axis_key(key)
        if parsed is None:
            continue
        kind = parsed[0]
        if kind == "ch":
            if len(parsed) < 3 or not _keep_channel(parsed[1], parsed[2]):
                continue
        elif kind == "g":
            if live_groups is not None and parsed[1] not in live_groups:
                continue
        elif kind == "b":
            if live_bindings is not None and parsed[1] not in live_bindings:
                continue
        else:
            continue
        axes[key] = spec
    appearance["axes"] = axes

    companion: dict[str, str] = {}
    for key, color in appearance["companion_colors"].items():
        try:
            fid, channel = _decode_channel_key(key)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if _keep_channel(fid, channel):
            companion[key] = color
    appearance["companion_colors"] = companion
    return appearance


def remap_chart_appearance(value: Any, fid_map: dict[str, str]) -> dict[str, Any]:
    """Rewrite file ids inside a persisted chart-appearance payload."""
    appearance = normalize_chart_appearance(value)
    axes: dict[str, dict[str, Any]] = {}
    for key, spec in appearance["axes"].items():
        parsed = parse_appearance_axis_key(key)
        if parsed is None:
            continue
        kind = parsed[0]
        if kind == "ch":
            if len(parsed) < 3 or parsed[1] not in fid_map:
                continue
            axes[appearance_channel_key(fid_map[parsed[1]], parsed[2])] = spec
        else:
            axes[key] = spec
    companion: dict[str, str] = {}
    for key, color in appearance["companion_colors"].items():
        try:
            fid, channel = _decode_channel_key(key)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if fid in fid_map:
            companion[_encode_channel_key((fid_map[fid], channel))] = color
    appearance["axes"] = axes
    appearance["companion_colors"] = companion
    return appearance


def inherit_chart_appearance_for_group_change(
    value: Any,
    prev_groups: Any,
    new_groups: Any,
) -> dict[str, Any]:
    """Copy y_scale/grid between member and group keys on merge/split."""
    appearance = normalize_chart_appearance(value)
    prev = _normalize_channel_axis_groups(prev_groups)
    new = _normalize_channel_axis_groups(new_groups)
    axes = dict(appearance["axes"])

    def _members(groups: dict[str, str], gid: str) -> list[ChannelKey]:
        out: list[ChannelKey] = []
        for raw_key, axis_id in groups.items():
            if str(axis_id) != str(gid):
                continue
            try:
                out.append(_decode_channel_key(raw_key))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return out

    prev_gids = {str(gid) for gid in prev.values()}
    new_gids = {str(gid) for gid in new.values()}
    for gid in prev_gids - new_gids:
        gkey = appearance_group_key(gid)
        gspec = axes.pop(gkey, {}) or {}
        inherit = {
            key: gspec[key]
            for key in ("y_scale", "grid")
            if key in gspec
        }
        if not inherit:
            continue
        for fid, channel in _members(prev, gid):
            ckey = appearance_channel_key(fid, channel)
            spec = dict(axes.get(ckey) or {})
            for key, item in inherit.items():
                spec.setdefault(key, item)
            axes[ckey] = spec
    for gid in new_gids:
        members = _members(new, gid)
        if len(members) < 2:
            continue
        gkey = appearance_group_key(gid)
        if gkey in axes:
            continue
        scales = []
        grids = []
        for fid, channel in members:
            spec = axes.get(appearance_channel_key(fid, channel)) or {}
            if "y_scale" in spec:
                scales.append(_normalize_scale(spec.get("y_scale")))
            if "grid" in spec:
                grids.append(bool(spec["grid"]))
        gspec: dict[str, Any] = {}
        if scales and all(item == scales[0] for item in scales):
            gspec["y_scale"] = scales[0]
        if grids and all(item == grids[0] for item in grids):
            gspec["grid"] = grids[0]
        if gspec:
            axes[gkey] = gspec
    appearance["axes"] = axes
    return appearance


def _normalize_scale(value: Any) -> str:
    return "log" if value == "log" else "linear"


def _normalize_axis_appearance_spec(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    spec: dict[str, Any] = {}
    if "title" in value:
        spec["title"] = str(value.get("title") or "")
    if "y_label" in value:
        spec["y_label"] = str(value.get("y_label") or "")
    if "y_scale" in value:
        spec["y_scale"] = _normalize_scale(value.get("y_scale"))
    if "grid" in value:
        spec["grid"] = bool(value.get("grid"))
    return spec


def _coerce_appearance_channel_color_key(value: Any) -> str:
    if isinstance(value, str):
        try:
            fid, channel = _decode_channel_key(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return ""
        return _encode_channel_key((fid, channel))
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return _encode_channel_key((str(value[0]), str(value[1])))
    return ""


def is_reusable_blank_view(state: "ViewState") -> bool:
    """True for an untouched initial time View that import may replace."""
    if state.attached_file_ids or state.checked or state.hidden_channels:
        return False
    if state.curve_bindings or state.remarks or state.cursor_placement:
        return False
    if getattr(getattr(state, "pinned_cursors", None), "records", ()):
        return False
    if getattr(state, "hidden_curve_binding_ids", None):
        return False
    if state.xlim is not None or state.ylims:
        return False
    if state.cursor_mode != "off" or state.plot_mode != "subplot":
        return False
    if state.overlay_primary is not None:
        return False
    if not is_default_time_filter(getattr(state, "time_filter", None)):
        return False
    if not is_default_chart_appearance(getattr(state, "chart_appearance", None)):
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
    time_filter: dict[str, Any] = field(default_factory=default_time_filter)
    chart_appearance: dict[str, Any] = field(
        default_factory=default_chart_appearance
    )
    # Last for positional-compat. Optional; missing JSON → empty collection.
    pinned_cursors: PinnedCursorCollection = field(default_factory=empty_collection)

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
        data["axis_opts"] = _normalize_axis_opts(self.axis_opts)
        data["time_filter"] = normalize_time_filter(self.time_filter)
        data["chart_appearance"] = normalize_chart_appearance(
            self.chart_appearance
        )
        data["pinned_cursors"] = collection_to_dict(self.pinned_cursors)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ViewState":
        axis_opts = _normalize_axis_opts(data.get("axis_opts"))
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
            axis_opts=axis_opts,
            remarks=normalize_remarks(data.get("remarks")),
            cursor_placement=normalize_cursor_placement(
                data.get("cursor_placement"),
                cursor_mode=data.get("cursor_mode", "off"),
            ),
            curve_bindings=parse_curve_bindings(data.get("curve_bindings")),
            hidden_curve_binding_ids=_coerce_id_list(
                data.get("hidden_curve_binding_ids")
            ),
            time_filter=normalize_time_filter(data.get("time_filter")),
            chart_appearance=normalize_chart_appearance(
                data.get("chart_appearance")
            ),
            pinned_cursors=collection_from_dict(data.get("pinned_cursors")),
        )


def _normalize_axis_opts(value: Any) -> dict[str, Any]:
    """Return serializable ordinary View axis state only.

    ``native_ticks`` and either location of ``x_viewport_intent`` belonged to
    the retired WWT display policy.  They remain accepted in old JSON, but are
    removed at the ViewState boundary so no later capture/save can reactivate
    them.  ``channel_axis_groups`` is the one View-owned WWT-era fact that
    remains: it describes ordinary channel membership only, never cadence or
    range policy.
    """
    if not isinstance(value, dict):
        return {}
    axis_opts = dict(value)
    axis_opts.pop("native_ticks", None)
    axis_opts.pop("x_viewport_intent", None)
    groups = _normalize_channel_axis_groups(axis_opts.get("channel_axis_groups"))
    if groups:
        axis_opts["channel_axis_groups"] = groups
    else:
        axis_opts.pop("channel_axis_groups", None)
    return axis_opts


def _normalize_channel_axis_groups(value: Any) -> dict[str, str]:
    """Validate/canonicalize persisted ``[fid, channel] -> axis_id`` maps."""
    if not isinstance(value, dict):
        return {}
    groups: dict[str, str] = {}
    for raw_key, raw_axis_id in value.items():
        key = raw_key
        if isinstance(raw_key, str):
            try:
                key = json.loads(raw_key)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        if not isinstance(key, (list, tuple)) or len(key) != 2:
            continue
        fid = str(key[0] or "").strip()
        channel = str(key[1] or "").strip()
        axis_id = str(raw_axis_id or "").strip()
        if not fid or not channel or not axis_id:
            continue
        groups[_encode_channel_key((fid, channel))] = axis_id
    return groups


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


def _coerce_filter_order(value: Any) -> int:
    try:
        order = int(value)
    except (TypeError, ValueError):
        return 4
    if order not in {2, 4, 6, 8}:
        return 4
    return order


def _coerce_filter_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(number):
        return float(default)
    return number


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


def _remint_pinned_cursors(state: Any) -> None:
    """Give a duplicated View/pane fresh pin scope_id and record UUIDs."""
    collection = getattr(state, "pinned_cursors", None)
    if collection is not None:
        state.pinned_cursors = duplicate_collection(collection)
    for pane in getattr(state, "panes", None) or ():
        pane_collection = getattr(pane, "pinned_cursors", None)
        if pane_collection is not None:
            pane.pinned_cursors = duplicate_collection(pane_collection)


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

    def reset_to_single_default(self) -> tuple[str, ...]:
        """Replace every View with a fresh default empty View 1.

        Used when the workspace becomes empty so leftover View skeletons
        (purged channel tables, stale ``axis_opts``) cannot survive into the
        next file load. Replacement avoids filtering composite-key tables
        in place. Returns the stable ids that disappeared so section hosts
        can clean caches without a second walk of the old list.
        """
        removed = tuple(str(view.view_id) for view in self.views)
        old_split = self.split_with
        self.views = [self._make(0)]
        self.active = 0
        self.split_with = None
        self._split_pairs = {}
        self.views_changed.emit()
        if old_split is not None:
            self.split_changed.emit(None)
        # Always emit so the host re-projects even when the index stays 0.
        self.active_changed.emit(0)
        return removed

    def reset_to_defaults_preserving_ids(self, ids) -> tuple[str, ...]:
        """Reset selected stable View slots to fresh defaults in one mutation.

        ``ids`` is ordered by the caller's surviving external references.
        The replacement states deliberately retain only those identities;
        stale source state, split pairs, and the prior active selection cannot
        leak into the empty workspace.  An empty or invalid selection follows
        the established one-default reset contract.
        """
        preserved_ids: list[str] = []
        seen: set[str] = set()
        for raw_id in ids or ():
            view_id = str(raw_id or "").strip()
            if view_id and view_id not in seen:
                preserved_ids.append(view_id)
                seen.add(view_id)
        if not preserved_ids:
            return self.reset_to_single_default()

        removed = tuple(
            str(view.view_id) for view in self.views
            if str(view.view_id) not in seen
        )
        old_split = self.split_with
        self.views = [self._make(index) for index in range(len(preserved_ids))]
        for state, view_id in zip(self.views, preserved_ids):
            state.view_id = view_id
        self.active = 0
        self.split_with = None
        self._split_pairs = {}
        self.views_changed.emit()
        if old_split is not None:
            self.split_changed.emit(None)
        # As in ``reset_to_single_default``, an explicit emission forces the
        # host to project the fresh active slot even when its index stayed 0.
        self.active_changed.emit(0)
        return removed

    def retain_only_view(self, view_id: str) -> tuple[str, ...]:
        """Keep the exact View object identified by ``view_id``.

        Fail closed: a missing/stale id is a zero-mutation no-op. Observers
        never see an empty View list. Split pairs that pointed at a removed
        View are dropped in the same transaction. Returns removed ids.
        """
        keep = None
        keep_idx = -1
        target = str(view_id or "")
        if not target:
            return ()
        for idx, view in enumerate(self.views):
            if str(view.view_id) == target:
                keep = view
                keep_idx = idx
                break
        if keep is None:
            return ()
        if len(self.views) == 1:
            return ()
        removed = tuple(
            str(view.view_id) for view in self.views if view is not keep
        )
        old_split = self.split_with
        old_active = self.active
        self.views = [keep]
        self.active = 0
        self.split_with = None
        self._split_pairs = {}
        self.views_changed.emit()
        if old_split is not None:
            self.split_changed.emit(None)
        if old_active != 0 or keep_idx != 0:
            self.active_changed.emit(0)
        return removed

    def reset_view_to_default(
        self, idx: int, *, preserve_view_id: bool = True, emit: bool = True,
    ) -> bool:
        """Replace one View's contents without deleting its stable slot.

        Partial file close uses this when a formerly source-backed View becomes
        empty.  Keeping ``view_id`` preserves any UltraView reference while a
        fresh state removes the old imported name, axes, ranges, filters,
        bindings, remarks, and cursor intent that would contaminate a later
        attachment.
        """
        if not self._is_valid_index(idx):
            return False
        previous = self.views[idx]
        fresh = self._make(idx)
        if preserve_view_id:
            fresh.view_id = previous.view_id
        self.views[idx] = fresh
        if emit:
            self.views_changed.emit()
        return True

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
        _remint_pinned_cursors(copied)
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
