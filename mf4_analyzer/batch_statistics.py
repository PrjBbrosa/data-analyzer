"""GUI-free time-chart statistics and hysteresis diagnostics."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

import numpy as np


CANONICAL_METRICS = ("max", "min", "mean")


def display_x(values, *, x_source: str, x_origin: str) -> np.ndarray:
    """Apply the report X transform without changing physical sample pairing."""
    result = np.asarray(values, dtype=float)
    if str(x_source) == "time" and str(x_origin) == "zero" and result.size:
        return result - result[0]
    return result


@dataclass(frozen=True)
class StatisticSeriesInput:
    x: np.ndarray
    y: np.ndarray
    series_key: str = ""
    family_key: str = ""
    label: str = ""
    variant: str = ""
    panel: int = 0

    def __post_init__(self) -> None:
        x = np.asarray(self.x, dtype=float)
        y = np.asarray(self.y, dtype=float)
        if x.ndim != 1 or y.ndim != 1 or x.size != y.size:
            raise ValueError("statistics X/Y must be aligned one-dimensional arrays")
        object.__setattr__(self, "x", x)
        object.__setattr__(self, "y", y)


@dataclass(frozen=True)
class BatchStatisticRow:
    series_key: str
    family_key: str
    label: str
    variant: str
    panel: int
    branch_label: str
    direction: str
    sample_count: int
    x_min: float | None
    x_max: float | None
    minimum: float | None
    maximum: float | None
    mean: float | None
    argmin_x: float | None
    argmax_x: float | None


@dataclass(frozen=True)
class BatchChartDiagnostic:
    code: str
    severity: str = "error"
    title: str = "ERROR · 图内统计未生成"
    message: str = ""
    suggestion: str = ""
    panel: int = 0


@dataclass(frozen=True)
class BatchChartStatisticsPlan:
    rows: tuple[BatchStatisticRow, ...] = ()
    diagnostics: tuple[BatchChartDiagnostic, ...] = ()


@dataclass(frozen=True)
class _IndexSpan:
    start: int
    stop: int


@dataclass(frozen=True)
class _TurnPolicy:
    turn_distance: float
    min_support: int


@dataclass(frozen=True)
class _MajorLeg:
    start: int
    end: int
    direction: int
    policy: _TurnPolicy | None


@dataclass(frozen=True)
class _RangeContribution:
    x: np.ndarray
    y: np.ndarray
    direction: int
    policy: _TurnPolicy | None

    @property
    def sample_count(self) -> int:
        return int(self.x.size)

    @property
    def travel(self) -> float:
        return float(np.ptp(self.x)) if self.x.size else 0.0


def _configuration(config) -> tuple[bool, str, float | None, float | None]:
    if not isinstance(config, dict) or not bool(config.get("enabled", False)):
        return False, "full", None, None
    mode = str(config.get("range_mode", "full") or "full").strip().lower()
    if mode != "custom":
        return True, "full", None, None
    try:
        lo, hi = float(config["x_min"]), float(config["x_max"])
    except (KeyError, TypeError, ValueError):
        return True, "custom", None, None
    return True, "custom", lo, hi


def _acquisition_segments(x: np.ndarray, y: np.ndarray) -> tuple[_IndexSpan, ...]:
    """Split finite samples without joining across acquisition gaps."""
    finite = np.isfinite(x) & np.isfinite(y)
    spans: list[_IndexSpan] = []
    start: int | None = None
    for index, present in enumerate(finite):
        if present and start is None:
            start = index
        elif not present and start is not None:
            spans.append(_IndexSpan(start, index))
            start = None
    if start is not None:
        spans.append(_IndexSpan(start, int(x.size)))
    return tuple(spans)


def _turn_policy(x: np.ndarray) -> _TurnPolicy | None:
    """Derive a reversal threshold from the complete acquisition segment."""
    steps = np.abs(np.diff(x))
    steps = steps[np.isfinite(steps) & (steps > 0.0)]
    data_span = float(np.ptp(x)) if x.size else 0.0
    if not steps.size or not np.isfinite(data_span) or data_span <= 0.0:
        return None
    q50 = float(np.median(steps))
    q95 = float(np.percentile(steps, 95))
    turn_distance = min(
        max(4.0 * q95, 0.005 * data_span),
        0.10 * data_span,
    )
    min_support = int(min(64, max(3, math.ceil(turn_distance / max(q50, 1e-12)))))
    return _TurnPolicy(turn_distance=turn_distance, min_support=min_support)


def _raw_legs(x: np.ndarray, policy: _TurnPolicy) -> list[list[int]]:
    """Confirm turns from sustained displacement, not adjacent dx signs."""
    if not x.size:
        return []
    legs: list[list[int]] = []
    start = 0
    direction = 0
    extremum_index = 0
    extremum_value = float(x[0])
    reversal_samples = 0
    for index in range(1, int(x.size)):
        value = float(x[index])
        if direction == 0:
            if value != extremum_value:
                direction = 1 if value > extremum_value else -1
                extremum_index = index
                extremum_value = value
                reversal_samples = 0
            continue
        if direction * (value - extremum_value) > 0.0:
            extremum_index = index
            extremum_value = value
            reversal_samples = 0
            continue
        reversal_samples += 1
        if (
            direction * (extremum_value - value) >= policy.turn_distance
            and reversal_samples >= policy.min_support
        ):
            legs.append([start, extremum_index, direction])
            start = extremum_index
            direction = -direction
            extremum_index = index
            extremum_value = value
            reversal_samples = 0
    legs.append([start, int(x.size) - 1, direction])
    return legs


def _merge_short_legs(
    legs: list[list[int]], x: np.ndarray, policy: _TurnPolicy,
) -> tuple[_MajorLeg, ...]:
    """Iteratively absorb incomplete lead-in, tail, and turn residues."""
    changed = True
    while changed and len(legs) > 1:
        changed = False
        for index, (start, end, _direction) in enumerate(tuple(legs)):
            if abs(float(x[end]) - float(x[start])) >= policy.turn_distance:
                continue
            if (
                0 < index < len(legs) - 1
                and legs[index - 1][2] == legs[index + 1][2]
            ):
                legs[index - 1][1] = legs[index + 1][1]
                del legs[index:index + 2]
            elif index == 0:
                legs[1][0] = legs[0][0]
                del legs[0]
            else:
                legs[index - 1][1] = legs[index][1]
                del legs[index]
            changed = True
            break
    merged = []
    for start, end, _direction in legs:
        delta = float(x[end]) - float(x[start])
        direction = 1 if delta > 0.0 else -1 if delta < 0.0 else 0
        merged.append(_MajorLeg(start, end, direction, policy))
    return tuple(merged)


def _clip_major_leg(
    leg: _MajorLeg, x: np.ndarray, y: np.ndarray, lo: float | None, hi: float | None,
) -> _RangeContribution | None:
    leg_x = x[leg.start:leg.end + 1]
    leg_y = y[leg.start:leg.end + 1]
    if lo is not None and hi is not None:
        selected = (leg_x >= lo) & (leg_x <= hi)
        leg_x, leg_y = leg_x[selected], leg_y[selected]
    if not leg_x.size:
        return None
    return _RangeContribution(leg_x, leg_y, leg.direction, leg.policy)


def _major_contributions(
    contributions: Sequence[_RangeContribution],
) -> tuple[_RangeContribution, ...]:
    """Keep only range visits that have enough support to be physical paths."""
    if not contributions:
        return ()
    maximum_travel = max(item.travel for item in contributions)
    travel_floor = 0.5 * maximum_travel
    return tuple(
        item for item in contributions
        if (
            item.policy is not None
            and item.sample_count >= item.policy.min_support
            and item.travel >= travel_floor
        )
    )


def _statistic_row(
    item: StatisticSeriesInput, x: np.ndarray, y: np.ndarray, *, index: int, sign: int,
    hysteresis: bool,
) -> BatchStatisticRow:
    count = int(x.size)
    if count:
        min_index = int(np.argmin(y))
        max_index = int(np.argmax(y))
        minimum, maximum = float(y[min_index]), float(y[max_index])
        mean = float(np.mean(y))
        row_x_min, row_x_max = float(np.min(x)), float(np.max(x))
        argmin_x, argmax_x = float(x[min_index]), float(x[max_index])
    else:
        minimum = maximum = mean = row_x_min = row_x_max = argmin_x = argmax_x = None
    direction = "X↑" if sign > 0 else "X↓" if sign < 0 else ""
    return BatchStatisticRow(
        series_key=item.series_key, family_key=item.family_key,
        label=item.label, variant=item.variant, panel=item.panel,
        branch_label=(f"路径 {index} · {direction}" if hysteresis else "全程"),
        direction=direction, sample_count=count, x_min=row_x_min, x_max=row_x_max,
        minimum=minimum, maximum=maximum, mean=mean,
        argmin_x=argmin_x, argmax_x=argmax_x,
    )


def _single_row(item: StatisticSeriesInput, x: np.ndarray, y: np.ndarray) -> tuple[BatchStatisticRow, ...]:
    return (_statistic_row(item, x, y, index=1, sign=0, hysteresis=False),)


def _series_rows(item: StatisticSeriesInput, *, mode, lo, hi, x_source: str):
    selected_lo, selected_hi = (lo, hi) if mode == "custom" and lo is not None and hi is not None else (None, None)
    if str(x_source) != "channel":
        finite = np.isfinite(item.x) & np.isfinite(item.y)
        x, y = item.x[finite], item.y[finite]
        if selected_lo is not None and selected_hi is not None:
            selected = (x >= selected_lo) & (x <= selected_hi)
            x, y = x[selected], y[selected]
        return _single_row(item, x, y), "", False, 0

    contributions: list[_RangeContribution] = []
    for segment in _acquisition_segments(item.x, item.y):
        segment_x = item.x[segment.start:segment.stop]
        segment_y = item.y[segment.start:segment.stop]
        policy = _turn_policy(segment_x)
        if policy is None:
            legs = (_MajorLeg(0, int(segment_x.size) - 1, 0, None),)
        else:
            legs = _merge_short_legs(_raw_legs(segment_x, policy), segment_x, policy)
        for leg in legs:
            clipped = _clip_major_leg(leg, segment_x, segment_y, selected_lo, selected_hi)
            if clipped is not None:
                contributions.append(clipped)

    if not contributions:
        return _single_row(item, np.asarray([], dtype=float), np.asarray([], dtype=float)), "", False, 0
    major = _major_contributions(contributions)
    if not major:
        x = np.concatenate(tuple(entry.x for entry in contributions))
        y = np.concatenate(tuple(entry.y for entry in contributions))
        return _single_row(item, x, y), "", False, 0
    if len(major) == 1:
        entry = major[0]
        return _single_row(item, entry.x, entry.y), "", False, 1
    if len(major) == 2 and major[0].direction * major[1].direction < 0:
        rows = tuple(
            _statistic_row(item, entry.x, entry.y, index=index, sign=entry.direction, hysteresis=True)
            for index, entry in enumerate(major, start=1)
        )
        return rows, "", True, 2
    return (), "multiple_reversals", False, len(major)


def plan_chart_statistics(
    series: Sequence[StatisticSeriesInput], config, *, x_source: str, x_origin: str,
) -> BatchChartStatisticsPlan:
    """Plan stats from full drawable arrays before display-envelope thinning."""
    enabled, mode, lo, hi = _configuration(config)
    if not enabled:
        return BatchChartStatisticsPlan()
    results = []
    for item in series:
        transformed = StatisticSeriesInput(
            x=display_x(item.x, x_source=x_source, x_origin=x_origin), y=item.y,
            series_key=item.series_key, family_key=item.family_key, label=item.label,
            variant=item.variant, panel=item.panel,
        )
        results.append((
            transformed,
            *_series_rows(transformed, mode=mode, lo=lo, hi=hi, x_source=x_source),
        ))
    diagnostics = []
    panels = tuple(dict.fromkeys(item.panel for item, *_rest in results))
    for panel in panels:
        panel_results = [entry for entry in results if entry[0].panel == panel]
        reversal_counts = [
            count for _item, _rows, reason, _h, count in panel_results
            if reason == "multiple_reversals"
        ]
        if reversal_counts:
            diagnostics.append(BatchChartDiagnostic(
                code="chart_statistics.multiple_x_reversals", panel=panel,
                message=(
                    f"当前统计区间识别到 {max(reversal_counts)} 条有效 X 路径，"
                    "无法确定唯一升程/回程。"
                ),
                suggestion="请缩小统计区间或拆分数据后重新运行。",
            ))
            continue
        families = {
            item.family_key or item.series_key
            for item, _rows, _reason, hysteresis, _count in panel_results if hysteresis
        }
        if len(families) >= 2:
            diagnostics.append(BatchChartDiagnostic(
                code="chart_statistics.multiple_hysteresis_overlay", panel=panel,
                message="当前图叠加了多个滞回曲线，无法可靠对应升程/回程统计。",
                suggestion="请改用“分屏”或“每项独立”后重新运行。",
            ))
    blocked_panels = {item.panel for item in diagnostics}
    rows = tuple(
        row for _item, planned, _reason, _hysteresis, _count in results
        if _item.panel not in blocked_panels for row in planned
    )
    return BatchChartStatisticsPlan(rows=rows, diagnostics=tuple(diagnostics))


__all__ = [
    "BatchChartDiagnostic", "BatchChartStatisticsPlan", "BatchStatisticRow",
    "CANONICAL_METRICS", "StatisticSeriesInput", "display_x", "plan_chart_statistics",
]
