"""Qt-free chart-appearance identity and snapshot DTOs.

Codec helpers here are the single source for ``appearance_channel_key`` /
``appearance_group_key`` / ``appearance_binding_key``. ``view_state`` re-exports
them so persisted View payloads keep the same import path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


APPEARANCE_REF_KEY = "appearance_ref"

KIND_CHANNEL = "channel"
KIND_BINDING = "binding"
KIND_COMPANION = "companion"
KIND_GROUP = "g"
KIND_AXIS_CHANNEL = "ch"
KIND_AXIS_BINDING = "b"

REASON_MISSING_IDENTITY = "missing-identity"
REASON_AMBIGUOUS_IDENTITY = "ambiguous-identity"
REASON_UNKNOWN_HANDLE = "unknown-handle"
REASON_MERGED_CURVE_KEY = "merged-curve-key"
REASON_EMPTY_KEY = "empty-key"


def appearance_channel_key(fid: Any, channel: Any) -> str:
    return json.dumps(
        ["ch", str(fid), str(channel)],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def appearance_group_key(group_id: Any) -> str:
    return json.dumps(
        ["g", str(group_id)],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def appearance_binding_key(binding_id: Any) -> str:
    return json.dumps(
        ["b", str(binding_id)],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def appearance_companion_color_key(fid: Any, channel: Any) -> str:
    """Runtime recolor identity for a filter companion. Not a persisted axis key."""
    fid_s = str(fid or "").strip()
    channel_s = str(channel or "").strip()
    if not fid_s or not channel_s:
        return ""
    return json.dumps(
        [KIND_COMPANION, fid_s, channel_s],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def normalize_appearance_axis_key(value: Any) -> str:
    """Canonical JSON key for a chart-options axis identity."""
    raw = value
    if isinstance(value, str):
        try:
            raw = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return ""
    if not isinstance(raw, (list, tuple)) or not raw:
        return ""
    kind = str(raw[0] or "")
    if kind == KIND_AXIS_CHANNEL and len(raw) >= 3:
        fid = str(raw[1] or "").strip()
        channel = str(raw[2] or "").strip()
        if fid and channel:
            return appearance_channel_key(fid, channel)
        return ""
    if kind == KIND_GROUP and len(raw) >= 2:
        group_id = str(raw[1] or "").strip()
        return appearance_group_key(group_id) if group_id else ""
    if kind == KIND_AXIS_BINDING and len(raw) >= 2:
        binding_id = str(raw[1] or "").strip()
        return appearance_binding_key(binding_id) if binding_id else ""
    return ""


def parse_appearance_axis_key(value: Any) -> tuple[str, ...] | None:
    key = normalize_appearance_axis_key(value)
    if not key:
        return None
    try:
        parsed = json.loads(key)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, list) or not parsed:
        return None
    return tuple(str(part) for part in parsed)


def parse_appearance_color_key(value: Any) -> tuple[str, ...] | None:
    """Parse a typed recolor identity: persisted axis key or companion source."""
    parsed = parse_appearance_axis_key(value)
    if parsed is not None:
        return parsed
    raw = value
    if isinstance(value, str):
        try:
            raw = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return None
    if str(raw[0] or "") != KIND_COMPANION:
        return None
    fid = str(raw[1] or "").strip()
    channel = str(raw[2] or "").strip()
    if not fid or not channel:
        return None
    return (KIND_COMPANION, fid, channel)


def channel_appearance_ref(fid: Any, channel: Any) -> dict[str, str]:
    return {
        "kind": KIND_CHANNEL,
        "fid": str(fid),
        "channel": str(channel),
    }


def binding_appearance_ref(binding_id: Any) -> dict[str, str]:
    return {
        "kind": KIND_BINDING,
        "binding_id": str(binding_id),
    }


def companion_appearance_ref(fid: Any, channel: Any) -> dict[str, str]:
    return {
        "kind": KIND_COMPANION,
        "fid": str(fid),
        "channel": str(channel),
    }


@dataclass(frozen=True)
class AppearanceRef:
    """Stable appearance identity carried on an 8th-item row meta dict."""

    kind: str
    fid: str = ""
    channel: str = ""
    binding_id: str = ""

    def encoded_key(self) -> str:
        if self.kind == KIND_CHANNEL and self.fid and self.channel:
            return appearance_channel_key(self.fid, self.channel)
        if self.kind == KIND_BINDING and self.binding_id:
            return appearance_binding_key(self.binding_id)
        return ""

    def fingerprint(self) -> tuple[str, str, str, str]:
        return (self.kind, self.fid, self.channel, self.binding_id)

    def source_pair(self) -> tuple[str, str] | None:
        if self.kind != KIND_COMPANION:
            return None
        if not self.fid or not self.channel:
            return None
        return (self.fid, self.channel)

    def to_dict(self) -> dict[str, str]:
        payload = {"kind": self.kind}
        if self.fid:
            payload["fid"] = self.fid
        if self.channel:
            payload["channel"] = self.channel
        if self.binding_id:
            payload["binding_id"] = self.binding_id
        return payload


def parse_appearance_ref(value: Any) -> AppearanceRef | None:
    """Return a validated identity, or None when the payload is absent/invalid."""
    raw = value
    if isinstance(value, Mapping) and APPEARANCE_REF_KEY in value:
        raw = value.get(APPEARANCE_REF_KEY)
    if not isinstance(raw, Mapping):
        return None
    kind = str(raw.get("kind") or "").strip()
    fid = str(raw.get("fid") or "").strip()
    channel = str(raw.get("channel") or "").strip()
    binding_id = str(raw.get("binding_id") or "").strip()
    if kind == KIND_CHANNEL:
        if not fid or not channel:
            return None
        return AppearanceRef(kind=KIND_CHANNEL, fid=fid, channel=channel)
    if kind == KIND_BINDING:
        if not binding_id:
            return None
        return AppearanceRef(kind=KIND_BINDING, binding_id=binding_id)
    if kind == KIND_COMPANION:
        if not fid or not channel:
            return None
        return AppearanceRef(kind=KIND_COMPANION, fid=fid, channel=channel)
    return None


def appearance_ref_fingerprint(meta: Any) -> tuple[str, ...]:
    ref = parse_appearance_ref(meta)
    if ref is None:
        return ()
    return ref.fingerprint()


def attach_appearance_ref(meta: Mapping[str, Any] | None, ref: Mapping[str, Any]) -> dict[str, Any]:
    """Copy ``meta`` and set the optional appearance identity without dropping keys."""
    payload = dict(meta or {})
    payload[APPEARANCE_REF_KEY] = dict(ref)
    return payload


@dataclass(frozen=True)
class ChartAppearanceTarget:
    """Resolved axis identity, or an unavailable result with an explicit reason."""

    available: bool
    reason: str
    encoded_key: str = ""
    kind: str = ""
    fid: str = ""
    channel: str = ""
    binding_id: str = ""
    group_id: str = ""

    def __post_init__(self) -> None:
        if self.available and not str(self.encoded_key or "").strip():
            object.__setattr__(self, "available", False)
            object.__setattr__(self, "encoded_key", "")
            object.__setattr__(
                self,
                "reason",
                self.reason or REASON_EMPTY_KEY,
            )
        if not self.available:
            object.__setattr__(self, "encoded_key", "")


def available_channel_target(fid: Any, channel: Any) -> ChartAppearanceTarget:
    fid_s = str(fid or "").strip()
    channel_s = str(channel or "").strip()
    key = appearance_channel_key(fid_s, channel_s) if fid_s and channel_s else ""
    return ChartAppearanceTarget(
        available=True,
        reason="",
        encoded_key=key,
        kind=KIND_AXIS_CHANNEL,
        fid=fid_s,
        channel=channel_s,
    )


def available_group_target(group_id: Any) -> ChartAppearanceTarget:
    gid = str(group_id or "").strip()
    key = appearance_group_key(gid) if gid else ""
    return ChartAppearanceTarget(
        available=True,
        reason="",
        encoded_key=key,
        kind=KIND_GROUP,
        group_id=gid,
    )


def available_binding_target(binding_id: Any) -> ChartAppearanceTarget:
    bid = str(binding_id or "").strip()
    key = appearance_binding_key(bid) if bid else ""
    return ChartAppearanceTarget(
        available=True,
        reason="",
        encoded_key=key,
        kind=KIND_AXIS_BINDING,
        binding_id=bid,
    )


def unavailable_target(reason: str) -> ChartAppearanceTarget:
    text = str(reason or "").strip() or REASON_MISSING_IDENTITY
    return ChartAppearanceTarget(available=False, reason=text, encoded_key="")


def target_from_ref(ref: AppearanceRef) -> ChartAppearanceTarget:
    if ref.kind == KIND_CHANNEL:
        return available_channel_target(ref.fid, ref.channel)
    if ref.kind == KIND_BINDING:
        return available_binding_target(ref.binding_id)
    return unavailable_target(REASON_MISSING_IDENTITY)


@dataclass(frozen=True)
class ChartAppearanceSnapshot:
    target: ChartAppearanceTarget
    x_scale: str
    y_scale: str
    title: str
    y_label: str
    grid: bool
    xlabel: str
    owns_xlabel: bool
    shares_x: bool


@dataclass(frozen=True)
class ResolvedAxisAppearance:
    """Already-resolved axis spec. ``handle`` is a live axis, never persisted."""

    handle: Any
    spec: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedChartAppearance:
    x_scale: str | None = None
    axes: tuple[ResolvedAxisAppearance, ...] = ()


def _normalize_scale(value: Any) -> str:
    return "log" if value == "log" else "linear"


def normalize_resolved_chart_appearance(value: Any) -> ResolvedChartAppearance:
    """Accept the dataclass, a mapping, or ``[(handle, spec), ...]``."""
    if isinstance(value, ResolvedChartAppearance):
        return value
    if value is None:
        return ResolvedChartAppearance()
    if isinstance(value, Mapping):
        x_scale = value.get("x_scale")
        if x_scale is not None:
            x_scale = _normalize_scale(x_scale)
        axes_in = value.get("axes") or ()
        axes: list[ResolvedAxisAppearance] = []
        for item in axes_in:
            if isinstance(item, ResolvedAxisAppearance):
                axes.append(item)
                continue
            if isinstance(item, Mapping) and "handle" in item:
                spec = dict(item.get("spec") or {})
                for field_name in ("title", "y_label", "y_scale", "grid"):
                    if field_name in item and field_name not in spec:
                        spec[field_name] = item[field_name]
                axes.append(ResolvedAxisAppearance(handle=item.get("handle"), spec=spec))
                continue
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                axes.append(ResolvedAxisAppearance(handle=item[0], spec=dict(item[1] or {})))
        return ResolvedChartAppearance(x_scale=x_scale, axes=tuple(axes))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        axes = []
        for item in value:
            if isinstance(item, ResolvedAxisAppearance):
                axes.append(item)
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                axes.append(ResolvedAxisAppearance(handle=item[0], spec=dict(item[1] or {})))
        return ResolvedChartAppearance(axes=tuple(axes))
    return ResolvedChartAppearance()


def iter_resolved_axis_specs(
    value: Any,
) -> Iterable[tuple[Any, dict[str, Any]]]:
    resolved = normalize_resolved_chart_appearance(value)
    for item in resolved.axes:
        if item.handle is None:
            continue
        yield item.handle, dict(item.spec or {})
