"""Regressions for the two visual defects reported on the 2026-08-04 build.

Both were introduced (or exposed) by the Y-tick-label fix in ``c26406fc`` and
both are geometry, not ink, so everything here is asserted against the specs
pyqtgraph actually hands to ``drawPicture``.

1. "上下两个图的数字有重叠" — restoring the dropped end-of-range Y tick labels
   (``GridLabelSlackAxisItem.boundingRect``) was only half the job. pyqtgraph
   centres a tick label ON its tick, and the first/last tick sits exactly on
   the end of the axis whenever the view range ends on a tick. Stacked subplot
   rows are ~5 px apart, so the upper row's ``-1.0`` and the lower row's
   ``1.0`` were drawn on top of each other. Before the slack was restored both
   were simply missing, which is why nothing caught it.

2. "每个图左边框多了一条竖线" — the time-domain canvas draws a ``vb.setBorder``
   frame AND lets its axes stroke their own lines. pyqtgraph 0.14 pushes the
   axis line one pixel outwards (``left_offset = -1.0`` etc. in
   ``generateDrawSpecs``), so the pair separates into two strokes; on a Retina
   display that is two device-pixel columns with a white one between them.

Note on the recorder: it hooks ``drawPicture``, NOT ``generateDrawSpecs``. Our
AxisItem subclasses post-process what ``super().generateDrawSpecs`` returns, so
a ``generateDrawSpecs`` hook would capture the un-post-processed specs and
happily pass on the broken output. ``drawPicture`` receives the final ones.
"""
from __future__ import annotations

import pyqtgraph as pg
import pytest


# Explicit ticks whose first and last values sit exactly on the view range
# ends — that is the configuration that puts half a label outside the axis.
# A generously pinned width keeps the horizontal (D1) defect out of play.
_TICKS = [[(-1.0, "-1.0"), (-0.5, "-0.5"), (0.0, "0"),
           (0.5, "0.5"), (1.0, "1.0")]]
_TICK_STRINGS = [text for _value, text in _TICKS[0]]
_AXIS_WIDTH = 200.0

# Realized geometry is float; sub-pixel slop is not the defect under test.
_EPS = 0.5


@pytest.fixture
def painted(monkeypatch):
    """Return a reader for the specs an axis last handed to ``drawPicture``."""
    original = pg.AxisItem.drawPicture

    def _recording(self, painter, axis_spec, tick_specs, text_specs):
        self._painted_specs = (axis_spec, list(tick_specs), list(text_specs))
        return original(self, painter, axis_spec, tick_specs, text_specs)

    monkeypatch.setattr(pg.AxisItem, "drawPicture", _recording)
    return lambda axis: getattr(axis, "_painted_specs", None)


def _pin_edge_ticks(plot):
    axis = plot.getAxis("left")
    axis.setTicks(_TICKS)
    axis.setWidth(_AXIS_WIDTH)
    view = plot.getViewBox()
    view.setYRange(-1.0, 1.0, padding=0.0)
    view.setXRange(0.0, 1.0, padding=0.0)
    return axis


def _settle(qapp, widget):
    widget.show()
    qapp.processEvents()
    # grab() drives paint() -> generateDrawSpecs() -> drawPicture().
    widget.grab()
    qapp.processEvents()


def _label_rects(axis, painted):
    specs = painted(axis)
    assert specs is not None, "axis never painted; nothing to assert on"
    return {text: rect for rect, _flags, text in specs[2]}


def _stacked_time_domain_canvas(qapp):
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(720, 600)
    plots = [canvas._add_plot_item(row=row, col=0) for row in (0, 1)]
    for plot in plots:
        _pin_edge_ticks(plot)
    _settle(qapp, canvas)
    return canvas, plots


# ------------------------------------------------- 1. end labels stay in-row
def test_edge_tick_labels_stay_inside_their_own_axis(qapp, painted):
    """Every label an axis draws must fit within that axis's own span.

    This is the containment contract; the cross-row assertion below is its
    user-visible consequence. Asserted per row so a failure names the row.
    """
    canvas, plots = _stacked_time_domain_canvas(qapp)
    try:
        for index, plot in enumerate(plots):
            axis = plot.getAxis("left")
            rects = _label_rects(axis, painted)
            # Guard against passing vacuously: the labels this is about are
            # exactly the ones the grid branch used to drop.
            assert sorted(rects) == sorted(_TICK_STRINGS), (
                f"row {index}: expected every tick label to be drawn, got "
                f"{sorted(rects)}"
            )
            bounds = axis.mapRectFromParent(axis.geometry())
            for text, rect in rects.items():
                assert rect.top() >= bounds.top() - _EPS, (
                    f"row {index}: label {text!r} overhangs the top of its "
                    f"axis by {bounds.top() - rect.top():.1f}px"
                )
                assert rect.bottom() <= bounds.bottom() + _EPS, (
                    f"row {index}: label {text!r} overhangs the bottom of its "
                    f"axis by {rect.bottom() - bounds.bottom():.1f}px"
                )
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_stacked_subplot_rows_never_overlap_each_others_labels(qapp, painted):
    """The reported symptom: ``-1.0`` and ``1.0`` drawn on top of each other.

    Compared in SCENE coordinates — the two axes have their own local frames,
    and the overlap only exists once both are placed in the shared layout.
    """
    canvas, plots = _stacked_time_domain_canvas(qapp)
    try:
        upper, lower = (plot.getAxis("left") for plot in plots)
        upper_rects = _label_rects(upper, painted)
        lower_rects = _label_rects(lower, painted)

        upper_scene = {t: upper.mapRectToScene(r) for t, r in upper_rects.items()}
        lower_scene = {t: lower.mapRectToScene(r) for t, r in lower_rects.items()}

        # Precondition: the rows really are stacked with a gap too small to
        # hold two half-labels, otherwise this test proves nothing.
        upper_bottom = max(r.bottom() for r in upper_scene.values())
        lower_top = min(r.top() for r in lower_scene.values())
        assert upper_bottom < lower_top, (
            f"upper row's lowest label reaches y={upper_bottom:.1f}, lower "
            f"row's highest starts at y={lower_top:.1f} — they overlap"
        )

        for upper_text, upper_rect in upper_scene.items():
            for lower_text, lower_rect in lower_scene.items():
                assert not upper_rect.intersects(lower_rect), (
                    f"upper row's {upper_text!r} overlaps lower row's "
                    f"{lower_text!r}: {upper_rect} vs {lower_rect}"
                )
    finally:
        canvas.deleteLater()
        qapp.processEvents()


# ---------------------------------------------- 2. axis line sits ON the border
def _axis_line_scene(axis, painted):
    specs = painted(axis)
    assert specs is not None, "axis never painted; nothing to assert on"
    _pen, p1, p2 = specs[0]
    return axis.mapToScene(p1), axis.mapToScene(p2)


def test_bordered_plot_draws_one_stroke_per_shared_edge(qapp, painted):
    """Time-domain canvas: the axis lines must land on the ViewBox border.

    ``_add_plot_item`` gives every subplot a ``vb.setBorder`` frame, so the
    left/bottom axis lines are duplicates of it. They have to coincide, or the
    plot shows a doubled edge.
    """
    canvas, plots = _stacked_time_domain_canvas(qapp)
    try:
        plot = plots[0]
        view = plot.getViewBox()
        assert view.border is not None, "precondition: this plot has a border"
        frame = view.mapRectToScene(view.rect())

        left_p1, left_p2 = _axis_line_scene(plot.getAxis("left"), painted)
        for point in (left_p1, left_p2):
            assert point.x() == pytest.approx(frame.left(), abs=_EPS), (
                f"left axis line at x={point.x():.2f} but the ViewBox border "
                f"is at x={frame.left():.2f} — two strokes, one edge"
            )

        bottom = plot.getAxis("bottom")
        if bottom.isVisible():
            bottom_p1, bottom_p2 = _axis_line_scene(bottom, painted)
            for point in (bottom_p1, bottom_p2):
                assert point.y() == pytest.approx(frame.bottom(), abs=_EPS), (
                    f"bottom axis line at y={point.y():.2f} but the ViewBox "
                    f"border is at y={frame.bottom():.2f}"
                )
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_borderless_analysis_plot_keeps_pyqtgraph_axis_line_placement(
    qapp, painted
):
    """Negative control: the analysis canvases must not move.

    They compose their frame out of four axis lines and clear the ViewBox
    border instead (``_apply_neutral_axis_frame``), so there is nothing to
    double up with — and nudging only left+bottom would skew the frame by a
    pixel on two sides. The alignment is gated on a painted border precisely
    so this path is untouched.
    """
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import (
        _apply_neutral_axis_frame,
        _make_analysis_plot,
    )
    from mf4_analyzer.qt_plot_helpers import (
        _linked_view_paints_border,
        show_major_grid_left_bottom_only,
    )

    widget = pg.GraphicsLayoutWidget()
    widget.resize(720, 460)
    try:
        plot = _make_analysis_plot(widget, 0, 0, pg.ViewBox())
        _apply_neutral_axis_frame(plot)
        show_major_grid_left_bottom_only(plot, alpha=0.25)
        _pin_edge_ticks(plot)
        _settle(qapp, widget)

        axis = plot.getAxis("left")
        assert not _linked_view_paints_border(axis), (
            "precondition: analysis plots must not paint a ViewBox border"
        )
        view = plot.getViewBox()
        frame = view.mapRectToScene(view.rect())
        p1, _p2 = _axis_line_scene(axis, painted)
        # pyqtgraph's own placement: one pixel outside the view rect.
        assert p1.x() == pytest.approx(frame.left() - 1.0, abs=_EPS), (
            "borderless analysis plot's left axis line moved; the frame it "
            "composes from four axes is no longer the one pyqtgraph built"
        )
    finally:
        widget.deleteLater()
        qapp.processEvents()
