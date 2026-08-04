"""Re-export of the shared left-axis metrics helpers.

The canonical home is :mod:`mf4_analyzer.ui_kit.axis_metrics` — see the
module docstring there for why it sits in ``ui_kit`` and not here. This
module exists only so the path named in
``docs/analyzer/plans/2026-08-04-y-axis-tick-label-clipping-design.md``
resolves; add no implementation to it.
"""
from __future__ import annotations

from mf4_analyzer.ui_kit.axis_metrics import (
    TICK_TEXT_PROBE,
    activate_item_layouts,
    axis_tick_font,
    axis_tick_texts,
    left_axis_width_for_ticks,
    pin_left_axes_to_common_width,
)


__all__ = [
    "TICK_TEXT_PROBE",
    "activate_item_layouts",
    "axis_tick_font",
    "axis_tick_texts",
    "left_axis_width_for_ticks",
    "pin_left_axes_to_common_width",
]
