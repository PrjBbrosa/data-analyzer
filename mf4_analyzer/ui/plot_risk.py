"""Pure risk estimator for dense time-domain overlay plots."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

import numpy as np


class PlotRiskLevel(str, Enum):
    OK = "ok"
    WARNING = "warning"
    DANGER = "danger"


OVERLAY_WARN_CHANNELS = 4
OVERLAY_DANGER_CHANNELS = 8
OVERLAY_WARN_SERIES = 6
OVERLAY_DANGER_SERIES = 10
OVERLAY_WARN_SAMPLES = 1_000_000
OVERLAY_DANGER_SAMPLES = 5_000_000
FILTER_WARN_SAMPLES = 750_000
FILTER_DANGER_SAMPLES = 2_000_000


@dataclass(frozen=True)
class PlotRisk:
    level: PlotRiskLevel
    channel_count: int
    series_count: int
    sample_total: int
    max_channel_samples: int
    filter_enabled: bool
    reasons: tuple[str, ...]

    @property
    def is_warning(self) -> bool:
        return self.level in {PlotRiskLevel.WARNING, PlotRiskLevel.DANGER}


def estimate_time_overlay_risk(
    *,
    checked: Sequence[tuple],
    files: Mapping[object, object],
    mode: str,
    time_range: tuple[float, float] | None,
    filter_enabled: bool,
    show_original: bool,
    show_filtered: bool,
) -> PlotRisk:
    if mode != "overlay":
        return PlotRisk(
            level=PlotRiskLevel.OK,
            channel_count=0,
            series_count=0,
            sample_total=0,
            max_channel_samples=0,
            filter_enabled=bool(filter_enabled),
            reasons=(),
        )

    kept = _kept_channels(checked, files)
    sample_cache: dict[int, int] = {}
    per_channel_samples = [
        _count_time_samples(fd, time_range, sample_cache) for fd, _ch in kept
    ]
    channel_count = len(kept)
    sample_total = int(sum(per_channel_samples))
    max_channel_samples = max(per_channel_samples, default=0)
    effective_filter_enabled = bool(filter_enabled)
    series_per_channel = _series_per_channel(
        filter_enabled=effective_filter_enabled,
        show_original=show_original,
        show_filtered=show_filtered,
    )
    series_count = channel_count * series_per_channel

    level = PlotRiskLevel.OK
    reasons: list[str] = []

    level = _add_threshold_reason(
        value=channel_count,
        warn=OVERLAY_WARN_CHANNELS,
        danger=OVERLAY_DANGER_CHANNELS,
        warning_text=f"叠加通道较多：{channel_count} 个通道，可能影响交互流畅度。",
        danger_text=f"叠加通道过多：{channel_count} 个通道，建议减少后再绘图。",
        current=level,
        reasons=reasons,
    )
    level = _add_threshold_reason(
        value=series_count,
        warn=OVERLAY_WARN_SERIES,
        danger=OVERLAY_DANGER_SERIES,
        warning_text=f"叠加曲线较多：预计绘制 {series_count} 条曲线。",
        danger_text=f"叠加曲线过多：预计绘制 {series_count} 条曲线。",
        current=level,
        reasons=reasons,
    )
    level = _add_threshold_reason(
        value=sample_total,
        warn=OVERLAY_WARN_SAMPLES,
        danger=OVERLAY_DANGER_SAMPLES,
        warning_text=f"叠加样本量较大：当前范围约 {sample_total:,} 点。",
        danger_text=f"叠加样本量过大：当前范围约 {sample_total:,} 点。",
        current=level,
        reasons=reasons,
    )

    if effective_filter_enabled:
        level = _add_threshold_reason(
            value=sample_total,
            warn=FILTER_WARN_SAMPLES,
            danger=FILTER_DANGER_SAMPLES,
            warning_text=f"滤波叠加样本量较大：当前范围约 {sample_total:,} 点。",
            danger_text=f"滤波叠加样本量过大：当前范围约 {sample_total:,} 点。",
            current=level,
            reasons=reasons,
        )

    return PlotRisk(
        level=level,
        channel_count=channel_count,
        series_count=series_count,
        sample_total=sample_total,
        max_channel_samples=max_channel_samples,
        filter_enabled=effective_filter_enabled,
        reasons=tuple(reasons),
    )


def _kept_channels(
    checked: Sequence[tuple], files: Mapping[object, object]
) -> list[tuple[object, object]]:
    kept = []
    for item in checked:
        if len(item) < 2:
            continue
        fid, ch = item[0], item[1]
        fd = files.get(fid)
        if fd is None:
            continue
        columns = getattr(getattr(fd, "data", None), "columns", ())
        if ch not in columns:
            continue
        kept.append((fd, ch))
    return kept


def _series_per_channel(
    *, filter_enabled: bool, show_original: bool, show_filtered: bool
) -> int:
    if not filter_enabled:
        return 1
    visible = int(bool(show_filtered)) + int(bool(show_original))
    return max(1, visible)


def _count_time_samples(
    fd: object,
    time_range: tuple[float, float] | None,
    sample_cache: dict[int, int],
) -> int:
    time_axis = getattr(fd, "time_array", None)
    if time_axis is None:
        return 0
    cache_key = id(time_axis)
    cached = sample_cache.get(cache_key)
    if cached is not None:
        return cached

    if time_range is None:
        count = len(time_axis)
    else:
        count = _count_in_range(time_axis, time_range)
    sample_cache[cache_key] = int(count)
    return int(count)


def _count_in_range(
    time_axis: object,
    time_range: tuple[float, float],
) -> int:
    lo, hi = sorted((float(time_range[0]), float(time_range[1])))
    times = np.asarray(time_axis, dtype=float)
    if times.ndim != 1:
        times = times.ravel()
    if times.size == 0:
        return 0

    if _is_monotonic_increasing(times):
        left = int(np.searchsorted(times, lo, side="left"))
        right = int(np.searchsorted(times, hi, side="right"))
        return max(0, right - left)
    if _is_monotonic_decreasing(times):
        ascending = times[::-1]
        left = int(np.searchsorted(ascending, lo, side="left"))
        right = int(np.searchsorted(ascending, hi, side="right"))
        return max(0, right - left)

    mask = (times >= lo) & (times <= hi)
    return int(np.count_nonzero(mask))


def _is_monotonic_increasing(values: np.ndarray) -> bool:
    return values.size < 2 or bool(np.all(values[1:] >= values[:-1]))


def _is_monotonic_decreasing(values: np.ndarray) -> bool:
    return values.size < 2 or bool(np.all(values[1:] <= values[:-1]))


def _add_threshold_reason(
    *,
    value: int,
    warn: int,
    danger: int,
    warning_text: str,
    danger_text: str,
    current: PlotRiskLevel,
    reasons: list[str],
) -> PlotRiskLevel:
    if value > danger:
        reasons.append(danger_text)
        return PlotRiskLevel.DANGER
    if value > warn:
        reasons.append(warning_text)
        if current is PlotRiskLevel.OK:
            return PlotRiskLevel.WARNING
    return current
