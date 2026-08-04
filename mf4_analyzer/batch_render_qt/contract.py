"""Stable slice-render contract surface consumed by the batch runner.

Acceptance item 11 requires the exported workbook to reproduce the *drawn*
slice curve exactly, so ``batch.py`` reaches into the Qt renderer for the
grid-snapping decision (``plan_heatmap_slice``), the amplitude-scale decision
(``render_in_db``) and the accompanying labels/warnings rather than keeping a
second implementation that could drift from what the chart actually drew.
Implementations stay where they already live (``_builder`` / ``_page`` /
``mf4_analyzer.batch_render_models``); this module only assigns public names
and an ``__all__`` to six of them.

This is the batch runner's stable contract face for slicing (design D5) --
adding, removing, renaming or resignaturing any of the six names below must
be reflected in ``batch.py:_load_slice_render_contract``, which is this
module's sole caller.
"""
from __future__ import annotations

from ..batch_render_models import plan_heatmap_slice
from ._builder import (
    _linear_amplitude_label as linear_amplitude_label,
    _render_in_db as render_in_db,
    _slice_clamp_warning as slice_clamp_warning,
)
from ._page import _DEFAULT_METHOD as default_method_labels
from ._page import effective_fact_items


__all__ = [
    "default_method_labels",
    "effective_fact_items",
    "linear_amplitude_label",
    "plan_heatmap_slice",
    "render_in_db",
    "slice_clamp_warning",
]
