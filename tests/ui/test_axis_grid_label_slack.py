"""D2 regression — switching the Y grid on must not delete the edge Y ticks.

Defect (reproduced with bare pyqtgraph, zero project code):

    y range [0, 1], left axis, grid OFF -> ['0', '0.25', '0.5', '0.75', '1']
    y range [0, 1], left axis, grid ON  -> ['0.25', '0.5', '0.75']

``AxisItem.boundingRect`` early-returns ``geometry | linkedViewRect`` whenever
the axis is linked to a view and ``self.grid is not False``
(pyqtgraph 0.14, AxisItem.py:956-961). That branch skips the ``m = 15`` px of
vertical slack the *other* branch applies — slack that exists precisely so a
vertical axis may carry labels that "extend above and below the length of the
axis" (AxisItem.py:66-69). ``generateDrawSpecs`` then rejects any tick label
whose rect is not wholly inside the bounding rect
(``if br & rect != rect: continue``, AxisItem.py:1688-1692). The first and last
labels are centred ON the axis ends, so half of each pokes out — and they are
not clipped, they are DROPPED. Every chart in this app enables the left grid,
so every chart could be missing its top and bottom Y tick value.

These tests observe ``generateDrawSpecs``' textSpecs and ``boundingRect``
geometry. They never assert on rendered pixels: the defect is a geometry
filter, not an ink problem, and the offscreen Qt used here may have no fonts
at all.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
import pytest

from mf4_analyzer.qt_plot_helpers import show_major_grid_left_bottom_only


# Explicit ticks + a generously pinned width keep exactly ONE variable in play:
# the vertical slack. The tick STRINGS are fixed (independent of pyqtgraph's
# automatic tick selection, SI prefixes and tick density), and 200 px is far
# wider than any of them needs, so no label can be dropped for a HORIZONTAL
# reason — that is the separate pinned-width defect (D1). Vertical geometry is
# not measured from glyphs, so this holds on a fontless Qt too.
_TICKS = [[(0.0, "0"), (0.25, "0.25"), (0.5, "0.5"), (0.75, "0.75"), (1.0, "1")]]
_TICK_STRINGS = [text for _value, text in _TICKS[0]]
_AXIS_WIDTH = 200.0


@pytest.fixture
def drawn_labels(monkeypatch):
    """Return a reader for the tick strings pyqtgraph actually emitted.

    ``generateDrawSpecs`` is where the labels last exist as text and where the
    boundingRect filter under test lives, so its ``textSpecs`` are the direct,
    pixel-free evidence of a dropped label.
    """
    original = pg.AxisItem.generateDrawSpecs

    def _recording(self, painter):
        out = original(self, painter)
        if out is not None:
            self._recorded_tick_labels = [spec[2] for spec in out[2]]
        return out

    monkeypatch.setattr(pg.AxisItem, "generateDrawSpecs", _recording)
    return lambda axis: getattr(axis, "_recorded_tick_labels", None)


def _drive_left_axis(qapp, widget, plot):
    """Pin ticks/width/range on ``plot``'s left axis, then force a real paint."""
    axis = plot.getAxis("left")
    axis.setTicks(_TICKS)
    axis.setWidth(_AXIS_WIDTH)
    view = plot.getViewBox()
    view.setYRange(0.0, 1.0, padding=0.0)
    view.setXRange(0.0, 1.0, padding=0.0)
    widget.show()
    qapp.processEvents()
    # grab() drives paint() -> generateDrawSpecs(), which is what the recorder
    # hooks. The returned image is never inspected.
    widget.grab()
    qapp.processEvents()
    return axis


def _assert_edge_ticks_survive(axis, drawn):
    labels = drawn(axis)
    assert labels is not None, "axis never painted; nothing to assert on"
    assert axis.grid is not False, "precondition: this axis must carry a grid"
    assert labels == _TICK_STRINGS, (
        "grid-enabled left axis dropped tick labels "
        f"{[t for t in _TICK_STRINGS if t not in labels]}; drawn={labels}"
    )


# --------------------------------------------------------------- time domain
def test_time_domain_subplot_left_axis_keeps_edge_ticks_with_grid(
    qapp, drawn_labels
):
    """Time-domain canvas (``PgTimeDomainCanvas._add_plot_item``)."""
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(720, 460)
    try:
        plot = canvas._add_plot_item(row=0, col=0)
        axis = _drive_left_axis(qapp, canvas, plot)
        _assert_edge_ticks_survive(axis, drawn_labels)
    finally:
        canvas.deleteLater()
        qapp.processEvents()


# --------------------------------------------- FFT / order / heatmap canvases
def test_analysis_plot_left_axis_keeps_edge_ticks_with_grid(qapp, drawn_labels):
    """Analysis canvases (``_make_analysis_plot`` -> ``_BoundaryGridAxisItem``).

    Covers the FFT/order line canvas and both heatmap plots, which all build
    their PlotItems through this one factory.
    """
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import _make_analysis_plot

    widget = pg.GraphicsLayoutWidget()
    widget.resize(720, 460)
    try:
        plot = _make_analysis_plot(widget, 0, 0, pg.ViewBox())
        show_major_grid_left_bottom_only(plot, alpha=0.25)
        axis = _drive_left_axis(qapp, widget, plot)
        _assert_edge_ticks_survive(axis, drawn_labels)
    finally:
        widget.deleteLater()
        qapp.processEvents()


# -------------------------------------------------------------- batch export
def test_batch_export_left_axis_keeps_edge_ticks_with_grid(qapp, drawn_labels):
    """Batch PNG export (``_SceneBuilder._new_plot``).

    The exported image is a real product surface, and it enables the same
    left/bottom grid, so it loses the same two tick values.
    """
    from mf4_analyzer.batch_image_options import BatchRenderOptions
    from mf4_analyzer.batch_render_qt import BatchSeries, BatchTimeFigureSpec
    from mf4_analyzer.batch_render_qt._builder import build_batch_scene

    x = np.linspace(0.0, 1.0, 201)
    spec = BatchTimeFigureSpec(
        series=(BatchSeries(x=x, y=x.copy(), label="curve", unit="Nm"),),
        layout="overlay",
    )
    scene = build_batch_scene(
        ("time", spec),
        options=BatchRenderOptions(width_px=900, height_px=600),
    )
    try:
        scene.show_and_settle()
        qapp.processEvents()
        plot = scene.plots[0]
        axis = _drive_left_axis(qapp, scene.widget, plot)
        _assert_edge_ticks_survive(axis, drawn_labels)
    finally:
        scene.close()
        qapp.processEvents()


# ------------------------------------------------------- boundingRect contract
def test_grid_branch_keeps_the_same_vertical_slack_as_the_plain_branch(qapp):
    """The two boundingRect branches must agree on vertical slack.

    This is the root contract; the label assertions above are its user-visible
    consequence. ``_make_analysis_plot`` is used because it hands back a plot
    whose grid is still OFF, so both branches can be measured on one axis.
    """
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import _make_analysis_plot

    widget = pg.GraphicsLayoutWidget()
    widget.resize(720, 460)
    try:
        plot = _make_analysis_plot(widget, 0, 0, pg.ViewBox())
        widget.show()
        qapp.processEvents()
        widget.grab()
        qapp.processEvents()
        axis = plot.getAxis("left")
        assert axis.grid is False, "precondition: grid starts off"
        without_grid = axis.boundingRect()
        geometry = axis.mapRectFromParent(axis.geometry())
        # pyqtgraph's own non-grid slack, for reference: 15 px each way.
        assert without_grid.top() == pytest.approx(geometry.top() - 15.0)
        assert without_grid.bottom() == pytest.approx(geometry.bottom() + 15.0)

        show_major_grid_left_bottom_only(plot, alpha=0.25)
        qapp.processEvents()
        widget.grab()
        qapp.processEvents()
        assert axis.grid is not False
        with_grid = axis.boundingRect()
        assert with_grid.top() <= geometry.top() - 15.0 + 1e-6, (
            "grid branch lost the top slack -> the topmost tick label is dropped"
        )
        assert with_grid.bottom() >= geometry.bottom() + 15.0 - 1e-6, (
            "grid branch lost the bottom slack -> the last tick label is dropped"
        )
    finally:
        widget.deleteLater()
        qapp.processEvents()


def test_bottom_axis_bounding_rect_is_left_exactly_as_pyqtgraph_built_it(qapp):
    """Negative control: horizontal axes must NOT be inflated.

    A top/bottom axis is built with ``hideOverlappingLabels = True`` (m = 0),
    so its grid branch loses nothing and must stay byte-identical to the stock
    ``geometry | linkedViewRect`` union.
    """
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import _make_analysis_plot

    widget = pg.GraphicsLayoutWidget()
    widget.resize(720, 460)
    try:
        plot = _make_analysis_plot(widget, 0, 0, pg.ViewBox())
        show_major_grid_left_bottom_only(plot, alpha=0.25)
        widget.show()
        qapp.processEvents()
        widget.grab()
        qapp.processEvents()
        axis = plot.getAxis("bottom")
        assert axis.grid is not False
        linked = axis.linkedView()
        expected = axis.mapRectFromParent(axis.geometry()) | linked.mapRectToItem(
            axis, linked.boundingRect()
        )
        assert axis.boundingRect() == expected
    finally:
        widget.deleteLater()
        qapp.processEvents()
