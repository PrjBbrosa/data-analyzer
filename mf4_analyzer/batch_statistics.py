"""GUI-free time-chart statistics and hysteresis diagnostics."""
from __future__ import annotations

from dataclasses import dataclass
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


def _direction_runs(x: np.ndarray) -> list[tuple[int, int, int]]:
    """Return meaningful direction runs as ``(sign, first_edge, last_edge)``."""
    if x.size < 2:
        return []
    scale = max(1.0, float(np.max(np.abs(x))), float(np.ptp(x)))
    tol = max(1e-12, 1e-9 * scale)
    signs = np.sign(np.diff(x))
    signs[np.abs(np.diff(x)) <= tol] = 0
    raw: list[list[int]] = []
    for edge, value in enumerate(signs):
        sign = int(value)
        if not sign:
            continue
        if raw and raw[-1][0] == sign:
            raw[-1][2] = edge
        else:
            raw.append([sign, edge, edge])
    # A direction fragment shorter than three finite sample points has fewer
    # than two edges.  It is noise, not a physical branch/reversal.
    changed = True
    while changed and len(raw) > 1:
        changed = False
        for index, run in enumerate(tuple(raw)):
            if run[2] - run[1] + 1 >= 2:
                continue
            if 0 < index < len(raw) - 1 and raw[index - 1][0] == raw[index + 1][0]:
                raw[index - 1][2] = raw[index + 1][2]
                del raw[index:index + 2]
            else:
                del raw[index]
            changed = True
            break
    return [tuple(item) for item in raw]


def _series_rows(item: StatisticSeriesInput, *, mode, lo, hi):
    finite = np.isfinite(item.x) & np.isfinite(item.y)
    x = item.x[finite]
    y = item.y[finite]
    if mode == "custom" and lo is not None and hi is not None:
        selected = (x >= lo) & (x <= hi)
        x, y = x[selected], y[selected]
    runs = _direction_runs(x)
    if len(runs) > 2:
        return (), "multiple_reversals", False
    if len(runs) == 2:
        pivot = runs[1][1]
        slices = ((slice(0, pivot + 1), runs[0][0]), (slice(pivot, None), runs[1][0]))
        hysteresis = True
    else:
        slices = ((slice(None), 0),)
        hysteresis = False
    rows = []
    for index, (subset, sign) in enumerate(slices, start=1):
        branch_x, branch_y = x[subset], y[subset]
        count = int(branch_x.size)
        if count:
            min_index = int(np.argmin(branch_y))
            max_index = int(np.argmax(branch_y))
            minimum, maximum = float(branch_y[min_index]), float(branch_y[max_index])
            mean = float(np.mean(branch_y))
            row_x_min, row_x_max = float(np.min(branch_x)), float(np.max(branch_x))
            argmin_x, argmax_x = float(branch_x[min_index]), float(branch_x[max_index])
        else:
            minimum = maximum = mean = row_x_min = row_x_max = argmin_x = argmax_x = None
        direction = "X↑" if sign > 0 else "X↓" if sign < 0 else ""
        rows.append(BatchStatisticRow(
            series_key=item.series_key, family_key=item.family_key,
            label=item.label, variant=item.variant, panel=item.panel,
            branch_label=(f"路径 {index} · {direction}" if hysteresis else "全程"),
            direction=direction, sample_count=count, x_min=row_x_min, x_max=row_x_max,
            minimum=minimum, maximum=maximum, mean=mean,
            argmin_x=argmin_x, argmax_x=argmax_x,
        ))
    return tuple(rows), "", hysteresis


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
        results.append((transformed, *_series_rows(transformed, mode=mode, lo=lo, hi=hi)))
    diagnostics = []
    panels = tuple(dict.fromkeys(item.panel for item, *_rest in results))
    for panel in panels:
        panel_results = [entry for entry in results if entry[0].panel == panel]
        if any(reason == "multiple_reversals" for _item, _rows, reason, _h in panel_results):
            diagnostics.append(BatchChartDiagnostic(
                code="chart_statistics.multiple_x_reversals", panel=panel,
                message="当前曲线检测到多次 X 方向反转，无法确定唯一升程/回程。",
                suggestion="请缩小统计区间或拆分数据后重新运行。",
            ))
            continue
        families = {
            item.family_key or item.series_key
            for item, _rows, _reason, hysteresis in panel_results if hysteresis
        }
        if len(families) >= 2:
            diagnostics.append(BatchChartDiagnostic(
                code="chart_statistics.multiple_hysteresis_overlay", panel=panel,
                message="当前图叠加了多个滞回曲线，无法可靠对应升程/回程统计。",
                suggestion="请改用“分屏”或“每项独立”后重新运行。",
            ))
    blocked_panels = {item.panel for item in diagnostics}
    rows = tuple(
        row for _item, planned, _reason, _hysteresis in results
        if _item.panel not in blocked_panels for row in planned
    )
    return BatchChartStatisticsPlan(rows=rows, diagnostics=tuple(diagnostics))


__all__ = [
    "BatchChartDiagnostic", "BatchChartStatisticsPlan", "BatchStatisticRow",
    "CANONICAL_METRICS", "StatisticSeriesInput", "display_x", "plan_chart_statistics",
]
