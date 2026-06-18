"""Tests for the pure axis-hit detection helper used by all 4 canvases.

TimeDomainCanvas and PlotCanvas tests that drove mpl-internal event dispatch
(canvas.callbacks.process, MouseEvent, fig.bbox) were removed when those
classes were retired in Phase D (2026-06-18).  The pg-based equivalents are
covered in tests/ui/test_pg_timedomain_canvas.py.
"""
import pytest
from matplotlib.figure import Figure


def _build_fig_with_axes():
    fig = Figure(figsize=(8, 6), dpi=100)
    ax = fig.add_subplot(111)
    ax.plot([0, 1, 2], [0, 1, 4])
    fig.canvas.draw()  # ensure renderer + bbox available
    return fig, ax


def test_find_axis_hit_x_label_region():
    from mf4_analyzer.ui._axis_interaction import find_axis_for_dblclick
    fig, ax = _build_fig_with_axes()
    bbox = ax.get_window_extent()
    # 30 px below the axes bottom -- inside the 45 px gutter
    hit_ax, axis = find_axis_for_dblclick(
        fig, x_px=(bbox.x0 + bbox.x1) / 2, y_px=bbox.y0 - 30, margin=45,
    )
    assert hit_ax is ax
    assert axis == 'x'


def test_find_axis_hit_y_label_region():
    from mf4_analyzer.ui._axis_interaction import find_axis_for_dblclick
    fig, ax = _build_fig_with_axes()
    bbox = ax.get_window_extent()
    hit_ax, axis = find_axis_for_dblclick(
        fig, x_px=bbox.x0 - 30, y_px=(bbox.y0 + bbox.y1) / 2, margin=45,
    )
    assert hit_ax is ax
    assert axis == 'y'


def test_find_axis_no_hit_returns_none():
    from mf4_analyzer.ui._axis_interaction import find_axis_for_dblclick
    fig, ax = _build_fig_with_axes()
    bbox = ax.get_window_extent()
    # Center of the axes -- far from any edge
    hit_ax, axis = find_axis_for_dblclick(
        fig, x_px=(bbox.x0 + bbox.x1) / 2, y_px=(bbox.y0 + bbox.y1) / 2,
        margin=45,
    )
    assert hit_ax is None
    assert axis is None


# M9 retired the matplotlib SpectrogramCanvas (FFT-vs-Time moved to
# PgHeatmapCanvas with_slice=True). Its three axis-dblclick ->
# edit_chart_options_dialog tests drove matplotlib MouseEvent through
# canvas.callbacks.process on _ax_spec/_ax_slice gridspec axes -- a
# matplotlib-only event surface with no equivalent on the pyqtgraph
# canvas, so they were removed rather than stubbed (see
# pyqt-ui/2026-05-28-mpl-event-coupled-tests-survive-renderer-swap).
#
# Phase D (2026-06-18): TimeDomainCanvas and PlotCanvas dblclick/hover tests
# (test_timedomain_canvas_dblclick_opens_chart_options_from_axis_gutter,
# test_timedomain_canvas_dblclick_inside_axes_opens_chart_options,
# test_timedomain_canvas_hover_axis_changes_cursor,
# test_plot_canvas_dblclick_uses_chart_options_helper,
# test_plot_canvas_hover_axis,
# test_plot_canvas_hover_short_circuit_during_drag) removed with the classes.
