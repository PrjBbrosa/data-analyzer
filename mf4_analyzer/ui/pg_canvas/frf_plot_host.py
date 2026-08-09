"""Shared plot-surface host for stacked system-identification charts.

FRF owns the response curves and their data semantics.  This module owns the
common pyqtgraph surface contract used by the other analysis canvases: framed
axes, modifier-aware ViewBoxes, linked X navigation and axis-width alignment.
Keeping that chrome here prevents FRF from becoming a second, divergent canvas
implementation every time the analysis plotting contract evolves.
"""
from __future__ import annotations

from PyQt5.QtCore import QTimer

from .analysis_axes import _apply_neutral_axis_frame, _make_analysis_plot
from ._shared import show_major_grid_left_bottom_only
from .viewbox import _ModifierWheelViewBox, _WheelDeltaGraphicsLayoutWidget
from mf4_analyzer.ui_kit.axis_metrics import (
    activate_item_layouts,
    left_axis_width_for_ticks,
    pin_left_axes_to_common_width,
)


class FrfStackedPlotHost:
    """Build and align the three FRF analysis rows for one owner canvas."""

    def __init__(self, owner):
        self._owner = owner
        self.widget = _WheelDeltaGraphicsLayoutWidget(owner, owner_canvas=owner)
        self.widget.setBackground("#ffffff")
        self.widget.ci.setContentsMargins(2, 2, 2, 2)
        self.widget.ci.setSpacing(2)
        self.plots = tuple(
            _make_analysis_plot(
                self.widget, row, 0, _ModifierWheelViewBox(owner_canvas=owner),
                frf_bottom_axis=True,
            )
            for row in range(3)
        )
        self._alignment_pending = False
        for plot in self.plots:
            _apply_neutral_axis_frame(plot)
            show_major_grid_left_bottom_only(plot, alpha=0.28)

        # Keep a real one-pixel bottom frame on the upper rows.  ``hideAxis``
        # removes that side of the rectangle completely, which was the visible
        # missing-border regression in FRF.
        for plot in self.plots[:-1]:
            axis = plot.getAxis("bottom")
            axis.setStyle(showValues=False, tickLength=0, maxTickLevel=0)
            axis.setHeight(1)
            axis.setLabel("")

        self.plots[1].setXLink(self.plots[0])
        self.plots[2].setXLink(self.plots[0])

    def schedule_alignment(self) -> None:
        if self._alignment_pending:
            return
        self._alignment_pending = True
        QTimer.singleShot(0, self.reset_alignment)

    def _left_axes(self):
        return [plot.getAxis("left") for plot in self.plots]

    def _layout_owners(self):
        return [self.widget.ci, *self.plots]

    def prepare_alignment(self) -> None:
        for axis in self._left_axes():
            try:
                axis.setWidth(None)
            except (RuntimeError, TypeError):
                pass
        activate_item_layouts(self._layout_owners())

    def reset_alignment(self) -> None:
        self._alignment_pending = False
        self.prepare_alignment()
        pin_left_axes_to_common_width(
            self._left_axes(), layout_owners=self._layout_owners()
        )

    def layout_metrics(self) -> dict:
        widths = []
        for axis in self._left_axes():
            try:
                widths.append(max(
                    float(left_axis_width_for_ticks(axis)), float(axis.width())
                ))
            except (RuntimeError, TypeError):
                pass
        return {"left_axis_width": max(widths) if widths else 0.0}

    def apply_alignment(self, *, left_axis_width: float) -> None:
        for axis in self._left_axes():
            try:
                axis.setWidth(float(left_axis_width))
            except (RuntimeError, TypeError):
                pass
        activate_item_layouts(self._layout_owners())
