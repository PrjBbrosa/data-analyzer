"""UI chart chrome defaults shared across chart_stack and pg_canvas.

Kept outside :mod:`mf4_analyzer.ui.chart_stack` so ``pg_canvas.tick_density``
can import the tick-density default without loading ``chart_stack.__init__``
(which pulls canvases and would cycle back into tick_density).
"""
from __future__ import annotations

from mf4_analyzer.batch_render_style import (
    DEFAULT_TICK_DENSITY_X,
    DEFAULT_TICK_DENSITY_Y,
)

# Interactive chart default = 「密」preset. View restore / Inspector / canvas
# controllers share this pair with batch export — no GUI↔batch fork.
DEFAULT_CHART_TICK_DENSITY = (DEFAULT_TICK_DENSITY_X, DEFAULT_TICK_DENSITY_Y)

__all__ = ["DEFAULT_CHART_TICK_DENSITY"]
