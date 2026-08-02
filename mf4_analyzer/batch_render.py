"""Stable public facade for the Qt/pyqtgraph batch image renderer.

The batch runner imports this module lazily at execution time, so importing
``mf4_analyzer.batch`` remains free of Qt side effects.  Renderer internals
live in :mod:`mf4_analyzer.batch_render_qt`; this facade intentionally exports
only the supported product contract.
"""
from __future__ import annotations

from .batch_image_options import BatchRenderOptions
from .batch_render_qt import (
    BatchRenderContext,
    BatchChartDiagnostic,
    BatchSeries,
    BatchStatisticRow,
    BatchTimeFigureSpec,
    render_batch_image,
)


__all__ = [
    "BatchRenderContext",
    "BatchChartDiagnostic",
    "BatchRenderOptions",
    "BatchSeries",
    "BatchStatisticRow",
    "BatchTimeFigureSpec",
    "render_batch_image",
]
