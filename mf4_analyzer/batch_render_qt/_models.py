"""Compatibility exports for the batch renderer's data contract dataclasses."""
from __future__ import annotations

from mf4_analyzer.batch_render_models import (
    BatchChartDiagnostic,
    BatchFrfFigureSpec,
    BatchFrfSeries,
    BatchRenderContext,
    BatchSeries,
    BatchSlicePick,
    BatchSlicePlan,
    BatchStatisticRow,
    BatchTimeFigureSpec,
    plan_heatmap_slice,
)


__all__ = [
    "BatchChartDiagnostic",
    "BatchFrfFigureSpec",
    "BatchFrfSeries",
    "BatchRenderContext",
    "BatchSeries",
    "BatchSlicePick",
    "BatchSlicePlan",
    "BatchStatisticRow",
    "BatchTimeFigureSpec",
    "plan_heatmap_slice",
]
