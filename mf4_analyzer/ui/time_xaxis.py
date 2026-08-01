"""Pure contracts for TimeDomain channel-backed X axes.

This module deliberately has no Qt dependency.  It is shared by the
Inspector selection, View/project persistence and the TimeDomain payload
builder so those callers cannot grow different interpretations of a custom X
axis.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

import numpy as np

from ..db_reference import normalize_unit


TIME_MODE = "time"
CHANNEL_MODE = "channel"
PER_SOURCE_NAME = "per_source_name"
EXACT_SOURCE = "exact_source"

SelectionPayload = tuple[str, str | None, str]


@dataclass(frozen=True)
class CustomXAxisSpec:
    """Applied custom-X state, independent of the Inspector draft widgets."""

    mode: str = TIME_MODE
    resolver: str | None = None
    channel: str | None = None
    source_fid: str | None = None
    label: str = ""

    @classmethod
    def from_axis_opts(cls, payload: Mapping[str, Any] | None) -> "CustomXAxisSpec":
        """Decode persisted ``axis_opts['x_axis']`` with legacy migration.

        A legacy channel payload has no ``resolver`` and therefore retains its
        historical exact-source meaning.  Unknown or incomplete payloads fail
        closed to the time axis instead of guessing a source.
        """
        values = dict(payload or {})
        mode = str(values.get("mode", TIME_MODE) or TIME_MODE).strip()
        label = str(values.get("label", "") or "")
        if mode != CHANNEL_MODE:
            return cls(mode=TIME_MODE, label=label)

        channel = str(values.get("channel", "") or "").strip()
        if not channel:
            return cls(mode=TIME_MODE, label=label)

        raw_resolver = values.get("resolver")
        resolver = (
            EXACT_SOURCE
            if raw_resolver is None and values.get("fid") is not None
            else str(raw_resolver or "").strip()
        )
        if resolver == PER_SOURCE_NAME:
            return cls(
                mode=CHANNEL_MODE,
                resolver=PER_SOURCE_NAME,
                channel=channel,
                source_fid=None,
                label=label,
            )
        if resolver == EXACT_SOURCE:
            source_fid = str(values.get("fid", "") or "").strip()
            if source_fid:
                return cls(
                    mode=CHANNEL_MODE,
                    resolver=EXACT_SOURCE,
                    channel=channel,
                    source_fid=source_fid,
                    label=label,
                )
        return cls(mode=TIME_MODE, label=label)

    def to_axis_opts(self) -> dict[str, Any]:
        """Encode the canonical persistence shape from the implementation plan."""
        if (
            self.mode == CHANNEL_MODE
            and self.resolver == PER_SOURCE_NAME
            and self.channel
        ):
            return {
                "mode": CHANNEL_MODE,
                "resolver": PER_SOURCE_NAME,
                "fid": None,
                "channel": str(self.channel),
                "label": str(self.label or ""),
            }
        if (
            self.mode == CHANNEL_MODE
            and self.resolver == EXACT_SOURCE
            and self.source_fid
            and self.channel
        ):
            return {
                "mode": CHANNEL_MODE,
                "resolver": EXACT_SOURCE,
                "fid": str(self.source_fid),
                "channel": str(self.channel),
                "label": str(self.label or ""),
            }
        return {
            "mode": TIME_MODE,
            "resolver": None,
            "fid": None,
            "channel": None,
            "label": str(self.label or ""),
        }


@dataclass(frozen=True)
class TimePlotIssue:
    """One machine-readable, source-specific reason a curve was not plotted."""

    code: str
    source_fid: str
    source_label: str
    target_channel: str
    x_channel: str
    detail: str = ""


@dataclass(frozen=True)
class CustomXResolution:
    """Result of resolving one target curve's channel-backed X array."""

    source_fid: str
    source_label: str
    target_channel: str
    x_channel: str
    ready: bool
    x_values: np.ndarray | None = None
    unit: str = ""
    issue: TimePlotIssue | None = None

    @property
    def issue_code(self) -> str | None:
        return self.issue.code if self.issue is not None else None

    @property
    def detail(self) -> str:
        return self.issue.detail if self.issue is not None else ""


def selection_payload(spec: CustomXAxisSpec) -> SelectionPayload | None:
    """Return the Inspector's tagged triple for an applied channel spec."""
    if spec.mode != CHANNEL_MODE or not spec.channel:
        return None
    if spec.resolver == PER_SOURCE_NAME:
        return (PER_SOURCE_NAME, None, str(spec.channel))
    if spec.resolver == EXACT_SOURCE and spec.source_fid:
        return (EXACT_SOURCE, str(spec.source_fid), str(spec.channel))
    return None


def spec_from_selection(
    payload: object,
    *,
    label: str = "",
) -> CustomXAxisSpec:
    """Decode one tagged Inspector triple, failing closed to ``time``."""
    if not isinstance(payload, (tuple, list)) or len(payload) != 3:
        return CustomXAxisSpec(mode=TIME_MODE, label=str(label or ""))
    resolver, source_fid, channel = payload
    channel = str(channel or "").strip()
    if resolver == PER_SOURCE_NAME and source_fid is None and channel:
        return CustomXAxisSpec(
            mode=CHANNEL_MODE,
            resolver=PER_SOURCE_NAME,
            channel=channel,
            source_fid=None,
            label=str(label or ""),
        )
    if resolver == EXACT_SOURCE and source_fid and channel:
        return CustomXAxisSpec(
            mode=CHANNEL_MODE,
            resolver=EXACT_SOURCE,
            channel=channel,
            source_fid=str(source_fid),
            label=str(label or ""),
        )
    return CustomXAxisSpec(mode=TIME_MODE, label=str(label or ""))


def channel_unit(source: object, channel: str) -> str:
    """Return a channel unit, preferring metadata over the legacy unit map."""
    metadata = (getattr(source, "channel_metadata", None) or {}).get(
        channel, {}
    ) or {}
    return str(
        metadata.get("unit")
        or (getattr(source, "channel_units", None) or {}).get(channel, "")
        or ""
    ).strip()


def _source_label(source: object, fid: str) -> str:
    return str(
        getattr(source, "short_name", "")
        or getattr(source, "filename", "")
        or fid
    )


def _column(source: object, channel: str) -> object | None:
    data = getattr(source, "data", None)
    if data is None:
        return None
    columns = getattr(data, "columns", data)
    try:
        if channel not in columns:
            return None
        return data[channel]
    except (KeyError, TypeError):
        return None


def _one_dimensional_array(values: object, *, numeric: bool) -> np.ndarray | None:
    try:
        if hasattr(values, "to_numpy"):
            values = values.to_numpy(copy=False)
        array = np.asarray(values, dtype=float if numeric else None)
    except (TypeError, ValueError):
        return None
    if array.ndim != 1:
        return None
    return array


def _failed_resolution(
    *,
    code: str,
    target_fid: str,
    source_label: str,
    target_channel: str,
    x_channel: str,
    detail: str,
    unit: str = "",
) -> CustomXResolution:
    issue = TimePlotIssue(
        code=code,
        source_fid=target_fid,
        source_label=source_label,
        target_channel=target_channel,
        x_channel=x_channel,
        detail=detail,
    )
    return CustomXResolution(
        source_fid=target_fid,
        source_label=source_label,
        target_channel=target_channel,
        x_channel=x_channel,
        ready=False,
        unit=unit,
        issue=issue,
    )


def resolve_custom_xaxis(
    *,
    target_fid: str,
    target_channel: str,
    files: Mapping[str, object],
    spec: CustomXAxisSpec,
) -> CustomXResolution:
    """Resolve one target curve's X array under the fixed resolver semantics.

    ``per_source_name`` looks up the X channel in ``target_fid``.
    ``exact_source`` always reads ``spec.source_fid`` and never substitutes a
    same-named channel from the target source.
    """
    target_fid = str(target_fid)
    target_channel = str(target_channel)
    target_source = files.get(target_fid)
    target_label = _source_label(target_source, target_fid) if target_source else target_fid
    x_channel = str(spec.channel or "")

    if target_source is None:
        return _failed_resolution(
            code="missing_target_source",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail="目标数据源已不存在",
        )
    y_values = _one_dimensional_array(
        _column(target_source, target_channel), numeric=False
    )
    if y_values is None:
        return _failed_resolution(
            code="missing_target_channel",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail="目标通道已不存在或不是一维数据",
        )

    if spec.mode != CHANNEL_MODE or spec.resolver not in {
        PER_SOURCE_NAME,
        EXACT_SOURCE,
    }:
        return _failed_resolution(
            code="invalid_xaxis_spec",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail="横坐标选择无效",
        )

    x_fid = target_fid if spec.resolver == PER_SOURCE_NAME else spec.source_fid
    x_source = files.get(str(x_fid)) if x_fid is not None else None
    if x_source is None:
        return _failed_resolution(
            code="missing_x_source",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail="横坐标数据源已不存在",
        )

    raw_x = _column(x_source, x_channel)
    if raw_x is None:
        return _failed_resolution(
            code="missing_x_channel",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail=f"缺少横坐标通道 {x_channel}",
        )
    x_values = _one_dimensional_array(raw_x, numeric=True)
    unit = channel_unit(x_source, x_channel)
    if x_values is None:
        return _failed_resolution(
            code="non_finite_x",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail="横坐标通道不是可绘制的一维数值",
            unit=unit,
        )
    if len(x_values) != len(y_values):
        return _failed_resolution(
            code="unaligned",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail=f"X/Y 长度不一致（{len(x_values)}/{len(y_values)}）",
            unit=unit,
        )
    if not np.isfinite(x_values).any():
        return _failed_resolution(
            code="non_finite_x",
            target_fid=target_fid,
            source_label=target_label,
            target_channel=target_channel,
            x_channel=x_channel,
            detail="横坐标通道没有有限数值",
            unit=unit,
        )

    return CustomXResolution(
        source_fid=target_fid,
        source_label=target_label,
        target_channel=target_channel,
        x_channel=x_channel,
        ready=True,
        x_values=x_values,
        unit=unit,
    )


def apply_unit_cohort(
    resolutions: Sequence[CustomXResolution],
) -> tuple[CustomXResolution, ...]:
    """Keep the largest normalized-unit cohort, preserving stable order.

    Equal-sized cohorts are resolved by first appearance in ``resolutions``.
    Empty units are ordinary normalized facts, not a wildcard.
    """
    groups: dict[str, list[int]] = {}
    for index, result in enumerate(resolutions):
        if result.ready:
            groups.setdefault(normalize_unit(result.unit), []).append(index)
    if not groups:
        return tuple(resolutions)

    selected_unit = max(groups, key=lambda key: len(groups[key]))
    selected = set(groups[selected_unit])
    output = []
    for index, result in enumerate(resolutions):
        if not result.ready or index in selected:
            output.append(result)
            continue
        issue = TimePlotIssue(
            code="x_unit_incompatible",
            source_fid=result.source_fid,
            source_label=result.source_label,
            target_channel=result.target_channel,
            x_channel=result.x_channel,
            detail=(
                f"横坐标单位 {result.unit or '空'} 与当前共享坐标轴不兼容"
            ),
        )
        output.append(
            replace(result, ready=False, x_values=None, issue=issue)
        )
    return tuple(output)


__all__ = [
    "CHANNEL_MODE",
    "EXACT_SOURCE",
    "PER_SOURCE_NAME",
    "TIME_MODE",
    "CustomXAxisSpec",
    "CustomXResolution",
    "SelectionPayload",
    "TimePlotIssue",
    "apply_unit_cohort",
    "channel_unit",
    "resolve_custom_xaxis",
    "selection_payload",
    "spec_from_selection",
]
