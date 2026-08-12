"""Colour constants for the batch report's heatmap slice overlay.

Two families, one per slice dimension (design §5.3). Only one family is ever
used on a single page; keeping both lets a reader who is flipping through
several exports tell "the spectrum at one instant" (warm) from "one
frequency's history" (cool) without reading the axis titles.

The warm family's lead colour (``#dc2626``) is deliberately *not identical*
to the interactive canvas marker (``#e03131`` in
``ui/pg_canvas/heatmap_canvas.py``). Batch needs a CIE76 delta-E floor of
>= 25 across the multi-slice family; pinning the lead slot to the canvas
hex would collapse that distinguishability budget. Spec §5-2 leaves this
colour fork in place until a product colour decision lands — do not "fix"
the docstring by aligning the hexes without that decision.

Both tuples are exactly :data:`MAX_SLICE_POSITIONS` long — the position count
is capped at the same number by ``batch_validation``, so indexing never has to
wrap.
"""
from __future__ import annotations

from ..batch_render_models import MAX_SLICE_POSITIONS


#: ``axis="time"`` — a fixed instant, curve = amplitude vs frequency/order.
#:
#: Design D-B4 (2026-08-03 acceptance follow-up). Chosen so every pairwise
#: CIELAB CIE76 delta-E within the family is >= 25 (min pair here is 32.8,
#: ``#dc2626`` vs ``#f97316``) — see the design doc for the full matrix.
#: ``#ea580c`` (the original design candidate for slot 2) was swapped for
#: ``#f97316``: it sat only 23.3 delta-E from ``#dc2626``, below the
#: distinguishability bar.
SLICE_WARM: tuple[str, ...] = ("#dc2626", "#f97316", "#a16207", "#be185d")

#: ``axis="y"`` — a fixed frequency/order, curve = amplitude vs time.
#:
#: Design D-B4. Min pairwise delta-E is 26.9 (``#0891b2`` vs ``#0f766e``).
#: ``#4338ca`` (the original design candidate for slot 3) was swapped for
#: ``#6d28d9``: it sat only 21.0 delta-E from ``#2563eb`` — the same
#: too-close-to-blue defect that made the *previous* palette's
#: ``#2563eb``/``#4f46e5`` pair unreadable in the first place.
SLICE_COOL: tuple[str, ...] = ("#2563eb", "#0891b2", "#6d28d9", "#0f766e")


def slice_palette(axis: str) -> tuple[str, ...]:
    """Return the colour family for a slice ``axis`` (``"time"`` or ``"y"``)."""
    return SLICE_WARM if str(axis).strip().lower() == "time" else SLICE_COOL


__all__ = [
    "MAX_SLICE_POSITIONS",
    "SLICE_COOL",
    "SLICE_WARM",
    "slice_palette",
]
