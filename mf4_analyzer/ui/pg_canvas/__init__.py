"""Decomposed helpers for the pyqtgraph time-domain canvas.

``TimeDomainCanvasPG`` now lives in ``mf4_analyzer.ui.pg_canvas.canvas``.
The legacy ``mf4_analyzer.ui.pg_canvases`` module re-exports the moved names
so existing imports keep working.
"""

from .frf_canvas import PgFrfCanvas

__all__ = ["PgFrfCanvas"]
