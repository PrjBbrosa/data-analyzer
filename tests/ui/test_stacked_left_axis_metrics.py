"""D1 regression: the FFT/order and heatmap left-axis pins must fit their ticks.

Both ``PgLineCanvas`` and ``PgHeatmapCanvas`` stack two plots and pin their
left ``AxisItem``s to one width so the rows share a left edge. A pin that is
narrower than the tick strings does not clip them — ``generateDrawSpecs``
discards each label whose text rect does not fit the axis bounding rect
(``if br & rect != rect: continue``), so an over-narrow pin silently deletes
whole tick labels. Two ways that used to happen:

* ``line_canvas``: ``_unify_stacked_left_axes`` measured ``axis.width()`` right
  after ``prepare_split_layout_alignment`` released the pin with
  ``setWidth(None)``, but ``_activate_graphics_layout`` only activated
  ``glw.ci.layout``. The axis cell is sized by its owning PlotItem's layout, so
  the release never reached realized geometry and ``width()`` handed back the
  width that was already pinned — a fixed point of itself. Plotting a 0-0.8 Nm
  spectrum then a 0-480000 N one left the axis at 62.4px against the 101.4px
  its labels needed, and only ``'0'`` survived.
* ``heatmap_canvas``: its activator already walked the sub-layouts, so a
  release-and-remeasure did work *after* a paint. Before the first paint of a
  new tick set (the ``singleShot(0)`` alignment hops in
  ``_deferred_first_show_align`` and ``AnalysisSectionPage``'s layout sync both
  land there) ``AxisItem.textWidth`` is still pyqtgraph's constructor default
  of 30, so the "natural" width it measured was a lie and the map's Y axis drew
  *nothing at all*.

Both are answered by measuring the tick strings with ``QFontMetricsF``
(``ui_kit.axis_metrics``), which is independent of paint history.

Everything is asserted against ``generateDrawSpecs``' textSpecs and font
metrics. Never assert rendered ink: the Qt install on the box these cases were
developed on has no font directory, so offscreen renders carry no text at all.

Covers items 2 and 3 of section 6.1 in
``docs/analyzer/plans/2026-08-04-y-axis-tick-label-clipping-design.md``.

Scope note — the *interior* tick labels are the ones asserted drawn. A separate
defect (D2 in the same design doc) drops the extreme labels of any grid-enabled
left axis because ``AxisItem.boundingRect`` returns early on the grid branch and
never adds its +/-15px vertical slack. That is orthogonal to the width problem
under test here, so the endpoints are deliberately excluded.
"""
import numpy as np
import pyqtgraph as pg
import pytest
from PyQt5.QtCore import QCoreApplication

from mf4_analyzer.ui_kit.axis_metrics import (
    axis_tick_texts,
    left_axis_width_for_ticks,
)


# Realized geometry and font metrics are both floats; a sub-pixel shortfall is
# not the bug under test (dropping a label takes whole pixels of shortfall).
_EPS = 0.5

_FREQ = np.linspace(0.0, 500.0, 2000, dtype=np.float64)


@pytest.fixture
def drawn_left_labels(monkeypatch):
    """Report the tick strings pyqtgraph actually emitted for a left axis.

    ``generateDrawSpecs`` is where the drop happens, and its third return
    element is the list of ``(rect, flags, text)`` specs that survived the fit
    check — the only trustworthy "what got drawn" signal available without
    inspecting pixels.
    """
    original = pg.AxisItem.generateDrawSpecs

    def _recording(self, p):
        out = original(self, p)
        if out is not None and self.orientation == "left":
            self._recorded_tick_texts = [spec[2] for spec in out[2]]
        return out

    monkeypatch.setattr(pg.AxisItem, "generateDrawSpecs", _recording)
    return lambda axis: getattr(axis, "_recorded_tick_texts", None)


def _settle(canvas):
    """Drain queued layout work and force one paint.

    The recorded textSpecs only exist after a paint, and ``grab()`` is the
    cheapest way to demand one offscreen.
    """
    QCoreApplication.processEvents()
    canvas.grab()
    QCoreApplication.processEvents()


def _interior_tick_texts(axis):
    """Tick strings excluding the numerically smallest and largest.

    The endpoints belong to D2 (grid-branch ``boundingRect``), not to the
    width defect under test; excluding them keeps this test's verdict about
    the pin alone.
    """
    levels = [
        (float(value), str(text))
        for level in (getattr(axis, "_tickLevels", None) or [])
        for value, text in level
        if str(text)
    ]
    if levels:
        lo = min(value for value, _ in levels)
        hi = max(value for value, _ in levels)
        return [text for value, text in levels if lo < value < hi]
    texts = axis_tick_texts(axis)
    return texts[1:-1]


def _assert_axis_fits_its_ticks(axis, drawn_left_labels, *, tag):
    needed = left_axis_width_for_ticks(axis)
    realized = float(axis.width())
    assert realized + _EPS >= needed, (
        f"{tag}: left axis pinned to {realized:.1f}px but its tick strings "
        f"{axis_tick_texts(axis)!r} need {needed:.1f}px"
    )
    drawn = drawn_left_labels(axis)
    assert drawn is not None, f"{tag}: axis never painted"
    interior = _interior_tick_texts(axis)
    assert interior, f"{tag}: no interior ticks to check ({axis_tick_texts(axis)!r})"
    missing = [text for text in interior if text not in drawn]
    assert not missing, (
        f"{tag}: pyqtgraph dropped tick labels {missing!r}; drawn={drawn!r} "
        f"width={realized:.1f}px need={needed:.1f}px"
    )


# ----------------------------------------------------------------------
# item 2 — FFT / order line canvas
# ----------------------------------------------------------------------
def _line_canvas():
    from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas

    canvas = PgLineCanvas()
    canvas.resize(900, 600)
    canvas.show()
    QCoreApplication.processEvents()
    return canvas


def _plot_spectrum(canvas, peak, unit):
    canvas.plot_spectra(
        [{
            "label": "spectrum", "freq": _FREQ,
            "amp": peak * np.exp(-_FREQ / 80.0),
            "color": "#7070e0", "unit": unit,
        }],
        xlim=(0.0, 500.0), amp_label=f"Amplitude ({unit})", title="spectrum",
    )
    _settle(canvas)
    canvas.reset_split_layout_alignment()
    _settle(canvas)


def test_line_canvas_left_axis_grows_for_a_wider_spectrum(qapp, drawn_left_labels):
    """Section 6.1 item 2: a 0-0.8 pin must not survive a 0-480000 spectrum.

    The narrow spectrum runs first precisely so a too-narrow pin is already in
    place; that is the real sequence (steering torque, then rack force).
    """
    canvas = _line_canvas()
    try:
        _plot_spectrum(canvas, 0.8, "Nm")
        pinned_narrow = float(canvas._plot_amp.getAxis("left").width())

        _plot_spectrum(canvas, 480000.0, "N")

        axis = canvas._plot_amp.getAxis("left")
        assert float(axis.width()) > pinned_narrow, (
            f"left axis never grew past the narrow-spectrum pin "
            f"{pinned_narrow:.1f}px; ticks are now {axis_tick_texts(axis)!r}"
        )
        _assert_axis_fits_its_ticks(axis, drawn_left_labels, tag="amp row")
    finally:
        canvas.hide()
        canvas.deleteLater()


def test_line_canvas_unify_is_monotonic_and_sufficient(qapp):
    """Back-to-back unification settles on a width that fits, and never shrinks.

    The monotonicity clause alone has no teeth against the old code (a frozen
    pin is trivially monotone); the sufficiency clause is the one that bites.
    """
    canvas = _line_canvas()
    try:
        # Narrow first, so the sufficiency clause has something to catch: on a
        # canvas that only ever saw wide labels the old code happened to land
        # on a wide enough pin by accident.
        _plot_spectrum(canvas, 0.8, "Nm")
        _plot_spectrum(canvas, 480000.0, "N")
        axes = canvas._alignment_left_axes()

        canvas._unify_stacked_left_axes()
        _settle(canvas)
        first = [float(axis.width()) for axis in axes]

        canvas._unify_stacked_left_axes()
        _settle(canvas)
        second = [float(axis.width()) for axis in axes]

        for index, (before, after) in enumerate(zip(first, second)):
            assert after + _EPS >= before, (
                f"row {index}: second unify narrowed the left axis "
                f"{before:.1f}px -> {after:.1f}px"
            )
        for index, (axis, width) in enumerate(zip(axes, first)):
            needed = left_axis_width_for_ticks(axis)
            assert width + _EPS >= needed, (
                f"row {index}: unify settled on {width:.1f}px, below the "
                f"{needed:.1f}px its tick strings {axis_tick_texts(axis)!r} need"
            )
    finally:
        canvas.hide()
        canvas.deleteLater()


# ----------------------------------------------------------------------
# item 3 — spectrogram / order heatmap canvas
# ----------------------------------------------------------------------
def _heatmap_canvas():
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas

    canvas = PgHeatmapCanvas(with_slice=True)
    canvas.resize(900, 600)
    canvas.show()
    QCoreApplication.processEvents()
    return canvas


_MATRIX = np.random.default_rng(0).random((200, 120)) * -60.0


def test_heatmap_canvas_left_axis_fits_ticks_pinned_before_first_paint(
    qapp, drawn_left_labels,
):
    """Section 6.1 item 3, pre-first-paint variant.

    No paint between ``plot_or_update_heatmap`` and the alignment, mirroring
    the ``QTimer.singleShot(0, ...)`` hops that drive alignment in the real
    app. ``AxisItem.textWidth`` is still 30 there, so a width read back from
    realized geometry under-reports and every Frequency label was dropped.
    """
    canvas = _heatmap_canvas()
    try:
        canvas.plot_or_update_heatmap(
            _MATRIX, (0.0, 30.0), (0.0, 480000.0),
            x_label="Time (s)", y_label="Frequency (Hz)", title="spectrogram",
        )
        canvas.reset_split_layout_alignment()
        _settle(canvas)

        _assert_axis_fits_its_ticks(
            canvas._plot.getAxis("left"), drawn_left_labels, tag="map row")
    finally:
        canvas.hide()
        canvas.deleteLater()


def test_heatmap_canvas_left_axis_grows_for_a_wider_y_range(
    qapp, drawn_left_labels,
):
    """Section 6.1 item 3: an order map's narrow pin must not survive a
    frequency map's five-digit labels on the same canvas."""
    canvas = _heatmap_canvas()
    try:
        canvas.plot_or_update_heatmap(
            _MATRIX, (0.0, 30.0), (0.0, 0.8),
            x_label="Time (s)", y_label="Order", title="order map",
        )
        canvas.reset_split_layout_alignment()
        _settle(canvas)
        pinned_narrow = float(canvas._plot.getAxis("left").width())

        canvas.plot_or_update_heatmap(
            _MATRIX, (0.0, 30.0), (0.0, 480000.0),
            x_label="Time (s)", y_label="Frequency (Hz)", title="spectrogram",
        )
        canvas.reset_split_layout_alignment()
        _settle(canvas)

        axis = canvas._plot.getAxis("left")
        assert float(axis.width()) > pinned_narrow, (
            f"left axis never grew past the order-map pin {pinned_narrow:.1f}px; "
            f"ticks are now {axis_tick_texts(axis)!r}"
        )
        _assert_axis_fits_its_ticks(axis, drawn_left_labels, tag="map row")
    finally:
        canvas.hide()
        canvas.deleteLater()
