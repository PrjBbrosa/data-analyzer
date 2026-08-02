"""Public immutable data contracts for Qt batch rendering."""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np

from ..batch_statistics import BatchChartDiagnostic, BatchStatisticRow


def _freeze_fact_value(value: Any):
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_fact_value(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_fact_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_fact_value(item) for item in value)
    return value


@dataclass(frozen=True)
class BatchRenderContext:
    """Human-facing task identity and effective facts shown on a report page."""

    source_display_name: str = ""
    group: str | int | None = None
    channel: str = ""
    unit: str = ""
    method: str = ""
    task_id: str = ""
    effective_facts: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "effective_facts",
            MappingProxyType(
                {
                    str(key): _freeze_fact_value(value)
                    for key, value in dict(self.effective_facts).items()
                }
            ),
        )


@dataclass(frozen=True)
class BatchSeries:
    """One prepared time-domain curve for a batch figure."""

    x: np.ndarray
    y: np.ndarray
    label: str
    unit: str = ""
    x_unit: str = "s"
    linestyle: str = "-"
    panel: int = 0
    family_key: str = ""
    series_key: str = ""
    variant: str = ""

    def __post_init__(self) -> None:
        x_values = np.asarray(self.x, dtype=float)
        y_values = np.asarray(self.y, dtype=float)
        if x_values.ndim != 1 or y_values.ndim != 1:
            raise ValueError("BatchSeries x and y must be one-dimensional")
        if x_values.size != y_values.size:
            raise ValueError("BatchSeries x and y must have equal lengths")
        if (
            isinstance(self.panel, bool)
            or not isinstance(self.panel, (int, np.integer))
            or self.panel < 0
        ):
            raise ValueError("BatchSeries panel must be a non-negative int")
        if self.linestyle not in {"-", "--"}:
            raise ValueError("BatchSeries linestyle must be '-' or '--'")
        object.__setattr__(self, "x", x_values)
        object.__setattr__(self, "y", y_values)
        object.__setattr__(self, "panel", int(self.panel))


@dataclass(frozen=True)
class BatchTimeFigureSpec:
    """Pure data specification for a grouped time-domain report plot."""

    series: tuple[BatchSeries, ...]
    layout: str = "overlay"
    x_source: str = "time"
    x_origin: str = "zero"
    x_label: str = "Time (s)"
    panel_titles: tuple[str, ...] = ()
    statistics: tuple[BatchStatisticRow, ...] = ()
    diagnostics: tuple[BatchChartDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        series = tuple(self.series)
        if not all(isinstance(item, BatchSeries) for item in series):
            raise TypeError("BatchTimeFigureSpec series must contain BatchSeries")
        if self.layout not in {"overlay", "subplot"}:
            raise ValueError("BatchTimeFigureSpec layout must be overlay or subplot")
        if self.x_source not in {"time", "channel"}:
            raise ValueError("BatchTimeFigureSpec x_source must be time or channel")
        if self.x_origin not in {"zero", "absolute"}:
            raise ValueError("BatchTimeFigureSpec x_origin must be zero or absolute")
        object.__setattr__(self, "series", series)
        object.__setattr__(self, "panel_titles", tuple(self.panel_titles))
        if not all(isinstance(item, BatchStatisticRow) for item in self.statistics):
            raise TypeError("BatchTimeFigureSpec statistics must contain BatchStatisticRow")
        if not all(isinstance(item, BatchChartDiagnostic) for item in self.diagnostics):
            raise TypeError("BatchTimeFigureSpec diagnostics must contain BatchChartDiagnostic")
        object.__setattr__(self, "statistics", tuple(self.statistics))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


__all__ = [
    "BatchChartDiagnostic", "BatchRenderContext", "BatchSeries",
    "BatchStatisticRow", "BatchTimeFigureSpec",
]
