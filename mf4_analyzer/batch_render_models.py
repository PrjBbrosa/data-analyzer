"""Public immutable data contracts for Qt batch rendering.

This module intentionally sits outside :mod:`mf4_analyzer.batch_render_qt`:
pure spooling and DTO code (``batch_series_spool``, ``batch.py``) needs these
dataclasses without pulling in the Qt renderer package (design D4).
``batch_render_qt/_models.py`` re-exports everything here for the renderer
package's internal ``from ._models import ...`` call sites.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np

from .batch_statistics import BatchChartDiagnostic, BatchStatisticRow


#: Upper bound on slice positions per page (design D9). The main heatmap
#: saturates first: four marker lines already crowd the image.
MAX_SLICE_POSITIONS = 4


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
class BatchFrfSeries:
    """One raw directional FRF series prepared for a report figure."""

    frequency_hz: np.ndarray
    transfer: np.ndarray
    coherence: np.ndarray
    label: str
    source_display_name: str = ""
    input_channel: str = ""
    output_channel: str = ""
    input_unit: str = ""
    output_unit: str = ""
    effective_facts: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        frequency = np.asarray(self.frequency_hz, dtype=np.float64)
        transfer = np.asarray(self.transfer)
        coherence = np.asarray(self.coherence, dtype=np.float64)
        if frequency.ndim != 1 or transfer.ndim != 1 or coherence.ndim != 1:
            raise ValueError("BatchFrfSeries arrays must be one-dimensional")
        if not (frequency.size == transfer.size == coherence.size):
            raise ValueError("BatchFrfSeries arrays must have equal lengths")
        if frequency.size == 0:
            raise ValueError("BatchFrfSeries arrays must not be empty")
        if not np.iscomplexobj(transfer):
            raise ValueError("BatchFrfSeries transfer must be complex")
        if np.any(~np.isfinite(frequency)) or np.any(frequency < 0.0):
            raise ValueError("BatchFrfSeries frequency must be finite and non-negative")
        if frequency.size > 1 and np.any(np.diff(frequency) <= 0.0):
            raise ValueError("BatchFrfSeries frequency must be strictly increasing")
        finite_real = np.isfinite(transfer.real)
        finite_imag = np.isfinite(transfer.imag)
        if np.any(np.isinf(transfer.real)) or np.any(np.isinf(transfer.imag)):
            raise ValueError("BatchFrfSeries transfer must not contain infinity")
        if not np.array_equal(finite_real, finite_imag):
            raise ValueError(
                "BatchFrfSeries transfer real/imag finite masks must match"
            )
        finite_coherence = np.isfinite(coherence)
        if np.any(np.isinf(coherence)):
            raise ValueError("BatchFrfSeries coherence must not contain infinity")
        if np.any((coherence[finite_coherence] < 0.0) | (coherence[finite_coherence] > 1.0)):
            raise ValueError("BatchFrfSeries finite coherence must lie in [0, 1]")
        label = str(self.label or "").strip()
        if not label:
            raise ValueError("BatchFrfSeries label must not be empty")
        input_channel = str(self.input_channel or "").strip()
        output_channel = str(self.output_channel or "").strip()
        if bool(input_channel) != bool(output_channel):
            raise ValueError("BatchFrfSeries identity requires both input and output")
        if input_channel and input_channel == output_channel:
            raise ValueError("BatchFrfSeries input and output must differ")
        frequency = frequency.copy()
        transfer = np.asarray(transfer, dtype=np.complex128).copy()
        coherence = coherence.copy()
        for array in (frequency, transfer, coherence):
            array.setflags(write=False)
        object.__setattr__(self, "frequency_hz", frequency)
        object.__setattr__(self, "transfer", transfer)
        object.__setattr__(self, "coherence", coherence)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "source_display_name", str(self.source_display_name or ""))
        object.__setattr__(self, "input_channel", input_channel)
        object.__setattr__(self, "output_channel", output_channel)
        object.__setattr__(self, "input_unit", str(self.input_unit or "").strip())
        object.__setattr__(self, "output_unit", str(self.output_unit or "").strip())
        object.__setattr__(
            self, "effective_facts",
            MappingProxyType({
                str(key): _freeze_fact_value(value)
                for key, value in dict(self.effective_facts).items()
            }),
        )


@dataclass(frozen=True)
class BatchFrfFigureSpec:
    """Pure-data specification for a three-panel FRF report page."""

    series: tuple[BatchFrfSeries, ...]
    magnitude_scale: str = "db"
    frequency_scale: str = "log"
    phase_mode: str = "unwrapped"
    coherence_threshold: float = 0.8
    fade_low_coherence: bool = True

    def __post_init__(self) -> None:
        series = tuple(self.series)
        if not series or not all(isinstance(item, BatchFrfSeries) for item in series):
            raise TypeError(
                "BatchFrfFigureSpec series must contain BatchFrfSeries"
            )
        magnitude_scale = str(self.magnitude_scale).strip().lower()
        frequency_scale = str(self.frequency_scale).strip().lower()
        phase_mode = str(self.phase_mode).strip().lower()
        if magnitude_scale not in {"db", "linear"}:
            raise ValueError("BatchFrfFigureSpec magnitude_scale must be db or linear")
        if frequency_scale not in {"log", "linear"}:
            raise ValueError("BatchFrfFigureSpec frequency_scale must be log or linear")
        if phase_mode not in {"unwrapped", "wrapped"}:
            raise ValueError("BatchFrfFigureSpec phase_mode must be unwrapped or wrapped")
        threshold = float(self.coherence_threshold)
        if not np.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
            raise ValueError("BatchFrfFigureSpec coherence_threshold must lie in [0, 1]")
        object.__setattr__(self, "series", series)
        object.__setattr__(self, "magnitude_scale", magnitude_scale)
        object.__setattr__(self, "frequency_scale", frequency_scale)
        object.__setattr__(self, "phase_mode", phase_mode)
        object.__setattr__(self, "coherence_threshold", threshold)
        object.__setattr__(self, "fade_low_coherence", bool(self.fade_low_coherence))


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


@dataclass(frozen=True)
class BatchSlicePick:
    """One resolved slice position: where the user aimed, where it landed."""

    index: int
    value: float
    requested: float
    clamped: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "index", int(self.index))
        object.__setattr__(self, "value", float(self.value))
        object.__setattr__(self, "requested", float(self.requested))
        object.__setattr__(self, "clamped", bool(self.clamped))


@dataclass(frozen=True)
class BatchSlicePlan:
    """Every slice a heatmap page will draw, already snapped to the grid.

    ``axis`` names the *fixed* dimension, matching the recipe field:

    ``"time"``
        A fixed instant. The curve is amplitude vs frequency/order, so it reads
        along the matrix' Y coordinates and the main image gets vertical
        marker lines.
    ``"y"``
        A fixed frequency/order. The curve is amplitude vs time, so it reads
        along the matrix' X coordinates and the marker lines are horizontal.
    """

    axis: str = "time"
    picks: tuple[BatchSlicePick, ...] = ()
    merged: int = 0

    def __post_init__(self) -> None:
        axis = str(self.axis).strip().lower()
        object.__setattr__(self, "axis", axis if axis in {"time", "y"} else "time")
        object.__setattr__(self, "picks", tuple(self.picks))
        object.__setattr__(self, "merged", int(self.merged))

    @property
    def enabled(self) -> bool:
        return bool(self.picks)

    @property
    def clamped_picks(self) -> tuple[BatchSlicePick, ...]:
        return tuple(pick for pick in self.picks if pick.clamped)


def _slice_positions(params: Mapping[str, Any] | None) -> tuple[str, list[float]]:
    """Read ``params['slice']`` defensively into ``(axis, positions)``."""
    spec = (params or {}).get("slice")
    if not isinstance(spec, Mapping) or not bool(spec.get("enabled", False)):
        return "time", []
    axis = str(spec.get("axis", "time") or "time").strip().lower()
    if axis not in {"time", "y"}:
        axis = "time"
    raw = spec.get("positions", ())
    if not isinstance(raw, (tuple, list)):
        return axis, []
    positions: list[float] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, (int, float, np.floating, np.integer)):
            continue
        number = float(item)
        if np.isfinite(number):
            positions.append(number)
    return axis, positions


def plan_heatmap_slice(x_values, y_values, params) -> BatchSlicePlan:
    """Resolve recipe slice positions against a heatmap's own coordinates.

    Each requested position snaps to the nearest grid center, exactly as the
    single-file canvas' ``_seed_slice`` does (``argmin(|coords - value|)``), so
    the exported curve is a real matrix column/row and never an interpolation.

    A position outside the file's data range is *clamped* to the nearest edge
    rather than failing (design D12): a batch that mixes a 30 s file with a
    ``t=45 s`` recipe must still produce a page. Clamping can make two requests
    land on the same cell, so the picks are de-duplicated afterwards and the
    number of dropped requests is reported in :attr:`BatchSlicePlan.merged`
    (design D13).
    """
    axis, positions = _slice_positions(params)
    if not positions:
        return BatchSlicePlan(axis=axis)
    source = x_values if axis == "time" else y_values
    coords = np.asarray(source, dtype=float)
    finite = np.flatnonzero(np.isfinite(coords))
    if finite.size == 0:
        return BatchSlicePlan(axis=axis)
    low = float(np.min(coords[finite]))
    high = float(np.max(coords[finite]))
    picks: list[BatchSlicePick] = []
    seen: set[int] = set()
    merged = 0
    for requested in positions[:MAX_SLICE_POSITIONS]:
        index = int(finite[int(np.argmin(np.abs(coords[finite] - requested)))])
        if index in seen:
            merged += 1
            continue
        seen.add(index)
        picks.append(
            BatchSlicePick(
                index=index,
                value=float(coords[index]),
                requested=requested,
                clamped=not (low <= requested <= high),
            )
        )
    return BatchSlicePlan(axis=axis, picks=tuple(picks), merged=merged)


__all__ = [
    "BatchChartDiagnostic", "BatchFrfFigureSpec", "BatchFrfSeries",
    "BatchRenderContext", "BatchSeries",
    "BatchSlicePick", "BatchSlicePlan", "BatchStatisticRow",
    "BatchTimeFigureSpec", "MAX_SLICE_POSITIONS", "plan_heatmap_slice",
]
