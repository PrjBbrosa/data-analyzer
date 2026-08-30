"""GUI-free time-chart statistics and hysteresis diagnostics."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

import numpy as np

from mf4_analyzer.signal.custom_x_paths import analyze_custom_x_paths


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


def format_chart_diagnostic_warning(diagnostic: BatchChartDiagnostic | Mapping[str, Any]) -> str:
    """Render a statistics diagnostic for Batch warnings / UI surfaces.

    Passes the human ``message`` + ``suggestion`` (not the machine ``code``)
    so preview/run humanizers do not have to invent a colon prefix.
    """
    if isinstance(diagnostic, BatchChartDiagnostic):
        message = str(diagnostic.message or "").strip()
        suggestion = str(diagnostic.suggestion or "").strip()
        code = str(diagnostic.code or "").strip()
    else:
        message = str(diagnostic.get("message") or "").strip()
        suggestion = str(diagnostic.get("suggestion") or "").strip()
        code = str(diagnostic.get("code") or "").strip()
    text = " ".join(part for part in (message, suggestion) if part)
    return text or code


@dataclass(frozen=True)
class BatchChartStatisticsPlan:
    rows: tuple[BatchStatisticRow, ...] = ()
    diagnostics: tuple[BatchChartDiagnostic, ...] = ()


def _configuration(config) -> tuple[bool, str, float | None, float | None]:
    if not isinstance(config, dict) or not bool(config.get("enabled", False)):
        return False, "full", None, None
    mode = str(config.get("range_mode", "full") or "full").strip().lower()
    if mode != "custom":
        return True, "full", None, None
    try:
        lo, hi = float(config["x_min"]), float(config["x_max"])
    except (KeyError, TypeError, ValueError):
        return True, "custom_unavailable", None, None
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return True, "custom_unavailable", None, None
    return True, "custom", lo, hi


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

    x_range = (
        (selected_lo, selected_hi)
        if selected_lo is not None and selected_hi is not None
        else None
    )
    planned = analyze_custom_x_paths(item.x, item.y, x_range=x_range)
    contributions = planned.contributions
    major = planned.accepted
    if not contributions:
        return _single_row(item, np.asarray([], dtype=float), np.asarray([], dtype=float)), "", False, 0
    if not major:
        x = np.concatenate(tuple(entry.x for entry in contributions))
        y = np.concatenate(tuple(entry.y for entry in contributions))
        return _single_row(item, x, y), "", False, 0
    if len(major) == 1:
        entry = major[0]
        return _single_row(item, entry.x, entry.y), "", False, 1
    if planned.unique_pair:
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
    if mode == "custom_unavailable":
        # Requested a custom range but the bounds are missing/non-finite.
        # Fail closed like `multiple_x_reversals`: a red diagnostic and no
        # rows, instead of silently falling back to the full-range statistics
        # the user did not ask for (design D-D2).
        panels = tuple(dict.fromkeys(item.panel for item in series))
        diagnostics = tuple(
            BatchChartDiagnostic(
                code="chart_statistics.custom_range_unavailable", panel=panel,
                message="图内统计设为自定义区间，但区间上下限缺失或无效，未按全时段静默改算。",
                suggestion="请在图内统计设置里填写完整的自定义区间上下限，或改用“全时段”。",
            )
            for panel in panels
        )
        return BatchChartStatisticsPlan(diagnostics=diagnostics)
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
    "CANONICAL_METRICS", "StatisticSeriesInput", "display_x",
    "format_chart_diagnostic_warning", "plan_chart_statistics",
]
