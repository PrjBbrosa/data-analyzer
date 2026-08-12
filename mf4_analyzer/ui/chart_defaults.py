"""UI chart chrome defaults shared across chart_stack and pg_canvas.

Kept outside :mod:`mf4_analyzer.ui.chart_stack` so ``pg_canvas.tick_density``
can import the tick-density default without loading ``chart_stack.__init__``
(which pulls canvases and would cycle back into tick_density).
"""
from __future__ import annotations

# Interactive chart default = 「密」preset. View restore / Inspector / canvas
# controllers must share this; batch export keeps its own defaults.
DEFAULT_CHART_TICK_DENSITY = (20, 15)

__all__ = ["DEFAULT_CHART_TICK_DENSITY"]
