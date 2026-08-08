"""Y tick labels stay bounded, so a flat computed channel cannot push the plot right.

Reported 2026-08-09: plotting a channel produced by two-channel maths gave Y
tick labels like ``35.0000000034`` — a long run of zeros — and the whole canvas
was shoved to the right. Two independent defects stacked up:

1. **The range.** ``_frame_handle_y`` special-cased only ``hi <= lo``, i.e. a
   RAW channel that is bit-exactly constant. A computed channel (``A*3 - A*2 -
   A``, ``A - B``, ``A/B*B``) is constant in intent but carries ~1e-16 relative
   float64 residue, so ``max > min`` held and Y was auto-framed onto a ~1e-14
   wide window. Fixed by ``ticks_math.pad_y_extent``.

2. **The labels.** pyqtgraph 0.14's ``AxisItem.tickStrings`` derives its decimal
   places from the tick spacing and, for ``0.001 <= |v| < 10000``, formats FIXED
   with no ``%g`` or scientific escape — so a microscopic spacing prints every
   digit of the mantissa. ``pin_left_axes_to_common_width`` then pins EVERY
   subplot row's left axis to the widest requirement (it takes the max and is
   deliberately monotonically non-decreasing), which is how one bad row pushes
   the whole plot area right and never lets it back. Fixed by
   ``GridLabelSlackAxisItem.tickStrings``.

They are tested separately because either one alone still leaves the user
looking at a broken axis: (1) without (2) leaves wheel-zoom and restored project
ranges exposed, (2) without (1) leaves auto-framing choosing a window whose
labels are all the same number.

Assertions are on tick STRINGS and font metrics, never on rendered ink — the Qt
install these were developed against has no font directory, so an offscreen
render carries no text at all (same constraint ``test_stacked_left_axis_metrics``
documents).
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
import pytest
from PyQt5.QtCore import QCoreApplication

from mf4_analyzer.qt_plot_helpers import GridLabelSlackAxisItem
from mf4_analyzer.ui_kit.axis_metrics import (
    axis_tick_texts,
    left_axis_width_for_ticks,
)


_T = np.linspace(0.0, 10.0, 5_000, dtype=np.float64)


def _residue_only_signal(value: float) -> np.ndarray:
    """A channel that is ``value`` everywhere, to within float64 rounding.

    Built the way the Inspector's channel maths builds one rather than by
    hand-perturbing bits, so the residue is the real thing: ``3a - 2a - a`` is
    algebraically zero but each product rounds independently.
    """
    ramp = value + np.sin(_T) * value * 1e-3
    signal = value + (ramp * 3.0 - ramp * 2.0 - ramp)
    assert signal.min() < signal.max(), "precondition: the residue is a real span"
    assert signal.max() - signal.min() < abs(value) * 1e-12, (
        "precondition: and it is only residue"
    )
    return signal


# ----------------------------------------------------------------------
# Defect 2 — the axis class itself
# ----------------------------------------------------------------------
class TestVerticalAxisBoundsItsLabels:

    def _axis(self, orientation="left"):
        return GridLabelSlackAxisItem(orientation=orientation)

    @pytest.mark.parametrize(
        "values, spacing, tag",
        [
            ([-30.0, -20.0, 0.0, 20.0, 30.0], 10.0, "±35 Nm 电机扭矩"),
            ([0.96, 0.98, 1.0, 1.02, 1.04], 0.02, "恒 1 状态量"),
            ([-0.02, 0.0, 0.02, 0.04], 0.02, "±0.04 Nm 摩擦补偿"),
            ([0.0, 240000.0, 480000.0], 1e5, "480 kN 齿条力"),
            ([85.5795, 85.57953, 85.57956], 3e-5, "深缩放时间窗"),
        ],
    )
    def test_ordinary_axes_are_byte_identical_to_pyqtgraph(
        self, qapp, values, spacing, tag,
    ):
        """The parity clause. Left-axis WIDTHS are measured from these strings
        and the batch/GUI render parity guards compare both sides' labels, so
        any drift on a realistic axis would ripple straight into both."""
        ours = self._axis().tickStrings(list(values), 1.0, spacing)
        theirs = pg.AxisItem.tickStrings(self._axis(), list(values), 1.0, spacing)
        assert ours == theirs, tag

    def test_residue_axis_labels_are_bounded(self, qapp):
        values = [34.99999999999999, 35.0, 35.00000000000001]
        spacing = 2e-15

        theirs = pg.AxisItem.tickStrings(self._axis(), list(values), 1.0, spacing)
        assert max(len(text) for text in theirs) == 18, (
            f"precondition: pyqtgraph should still be the long one, got {theirs!r}"
        )

        ours = self._axis().tickStrings(list(values), 1.0, spacing)
        assert max(len(text) for text in ours) <= 4, ours

    def test_horizontal_axis_is_left_to_pyqtgraph(self, qapp):
        """X pays for a long label in a dimension it has to spare, and the
        time-domain X path already backs off on label collision
        (``tick_density._fit_x_tick_labels``) — re-formatting under that fit
        would only change which ticks it selects."""
        values = [34.99999999999999, 35.0, 35.00000000000001]
        spacing = 2e-15
        assert self._axis("bottom").tickStrings(list(values), 1.0, spacing) == \
            pg.AxisItem.tickStrings(self._axis("bottom"), list(values), 1.0, spacing)

    @pytest.mark.parametrize("spacing", [0.0, -1.0])
    def test_unusable_spacing_defers_to_pyqtgraph(self, qapp, spacing):
        """The override is transparent, including in how it fails.

        pyqtgraph's own ``log10(spacing * scale)`` raises on these, so the
        fallback must reproduce that rather than invent labels — a caller that
        reaches here has a broken tick set and swallowing it would hide the
        real fault behind a plausible-looking axis.
        """
        with pytest.raises(ValueError):
            pg.AxisItem.tickStrings(self._axis(), [1.0], 1.0, spacing)
        with pytest.raises(ValueError):
            self._axis().tickStrings([1.0], 1.0, spacing)

    def test_bounded_labels_cost_a_normal_axis_width(self, qapp):
        """The width is the reason any of this matters — 143 px vs ~24 px."""
        residue = self._axis()
        residue.setRange(34.99999999999999, 35.00000000000001)
        ordinary = self._axis()
        ordinary.setRange(-35.0, 35.0)

        assert left_axis_width_for_ticks(residue) <= \
            left_axis_width_for_ticks(ordinary) + 1.0, (
                f"residue axis ticks {axis_tick_texts(residue)!r} still measure "
                f"{left_axis_width_for_ticks(residue):.1f}px against the "
                f"{left_axis_width_for_ticks(ordinary):.1f}px an ordinary "
                f"±35 axis needs"
            )


# ----------------------------------------------------------------------
# Defect 1 — auto-framing, end to end on the real canvas
# ----------------------------------------------------------------------
class TestTimeDomainFlatComputedChannel:

    def _canvas(self, qapp, rows):
        from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

        canvas = TimeDomainCanvasPG()
        canvas.resize(900, 600)
        canvas.show()
        QCoreApplication.processEvents()
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        canvas.reset_view_to_data_extents()
        QCoreApplication.processEvents()
        return canvas

    def _left_axes(self, canvas):
        return [handle._ax("left") for handle in canvas.axes_list]

    def test_flat_computed_channel_gets_a_readable_y_range(self, qapp):
        """Home/查看全部 must frame the VALUE, not its rounding residue."""
        rows = [
            ("mMotorTorq_calc", True, _T, _residue_only_signal(35.0),
             "#e06010", "Nm", "fid-0"),
        ]
        canvas = self._canvas(qapp, rows)
        try:
            lo, hi = canvas.axes_list[0].get_ylim()
            assert hi - lo > 1.0, (
                f"Y framed onto the float residue: [{lo!r}, {hi!r}]"
            )
            assert lo < 35.0 < hi, f"35 Nm fell outside [{lo!r}, {hi!r}]"

            texts = axis_tick_texts(canvas.axes_list[0]._ax("left"))
            assert texts, "no Y ticks at all"
            assert max(len(text) for text in texts) <= 8, texts
        finally:
            canvas.hide()
            canvas.deleteLater()

    def test_flat_row_does_not_widen_its_neighbours_left_axis(self, qapp):
        """The reported symptom: one bad row pushed EVERY row's plot area right.

        ``pin_left_axes_to_common_width`` pins all subplot rows to the widest
        requirement, so this asserts against the same-shaped two-row chart with
        the flat channel replaced by an ordinary one.
        """
        flat = [
            ("mActiveReturnMotorTorq", True, _T, _residue_only_signal(35.0),
             "#e06010", "Nm", "fid-0"),
            ("mFricCompMotTorq", True, _T, np.sin(_T) * 0.03,
             "#404860", "Nm", "fid-1"),
        ]
        ordinary = [
            ("mActiveReturnMotorTorq", True, _T, 35.0 + np.sin(_T) * 0.7,
             "#e06010", "Nm", "fid-0"),
            ("mFricCompMotTorq", True, _T, np.sin(_T) * 0.03,
             "#404860", "Nm", "fid-1"),
        ]

        flat_canvas = self._canvas(qapp, flat)
        try:
            flat_width = max(
                float(axis.width()) for axis in self._left_axes(flat_canvas)
            )
            flat_ticks = axis_tick_texts(flat_canvas.axes_list[0]._ax("left"))
        finally:
            flat_canvas.hide()
            flat_canvas.deleteLater()

        ordinary_canvas = self._canvas(qapp, ordinary)
        try:
            ordinary_width = max(
                float(axis.width()) for axis in self._left_axes(ordinary_canvas)
            )
        finally:
            ordinary_canvas.hide()
            ordinary_canvas.deleteLater()

        assert flat_width <= ordinary_width + 1.0, (
            f"the flat computed channel pinned the left axes to "
            f"{flat_width:.1f}px against {ordinary_width:.1f}px for the same "
            f"chart with an ordinary channel; its ticks are {flat_ticks!r}"
        )

    def test_fit_y_to_visible_x_on_a_flat_window(self, qapp):
        """The second copy of the padding, on the Y-轴自适应 path.

        ``_fit_channel_y_to_visible_x`` slices to the current X window, so a
        channel that is merely flat *there* reaches the same degenerate extent
        even when the full recording is not flat.
        """
        signal = np.where(_T < 5.0, _residue_only_signal(35.0), 35.0 + _T)
        rows = [("mixed", True, _T, signal, "#e06010", "Nm", "fid-0")]
        canvas = self._canvas(qapp, rows)
        try:
            canvas.set_xlim(0.0, 4.0)
            QCoreApplication.processEvents()
            canvas.fit_y_to_visible_x()
            QCoreApplication.processEvents()

            lo, hi = canvas.axes_list[0].get_ylim()
            assert hi - lo > 1.0, (
                f"Y-轴自适应 framed onto the float residue: [{lo!r}, {hi!r}]"
            )
            texts = axis_tick_texts(canvas.axes_list[0]._ax("left"))
            assert max(len(text) for text in texts) <= 8, texts
        finally:
            canvas.hide()
            canvas.deleteLater()

    def test_exactly_constant_channel_is_unchanged(self, qapp):
        """Regression guard on the branch that always worked: a bit-exactly
        constant RAW channel (a status flag, ``Rte_DMS_yActualChar_xdu8``) must
        keep the ±5% window it has always had."""
        rows = [
            ("yActualChar", True, _T, np.ones_like(_T), "#7a3fd0", "", "fid-0"),
        ]
        canvas = self._canvas(qapp, rows)
        try:
            lo, hi = canvas.axes_list[0].get_ylim()
            assert lo < 1.0 < hi
            assert 0.05 < hi - lo < 0.5, f"[{lo!r}, {hi!r}]"
        finally:
            canvas.hide()
            canvas.deleteLater()


# ----------------------------------------------------------------------
# Defect 1, second reachable surface — the FFT/order canvas's 时域预览 row
# ----------------------------------------------------------------------
class TestFftOrderTimePreviewRow:
    """The other place explicit ticks make the label override unreachable.

    ``PgLineCanvas._reframe_time_y_to_grid`` pins the preview row onto a shared
    nice graticule with ``setTicks([[(value, _fmt_tick(value, per_div)), …]])``.
    Explicit ticks bypass ``AxisItem.tickStrings`` entirely, so
    ``GridLabelSlackAxisItem``'s bounding override never runs here — measured on
    a real cocoa render, a residue-only channel produced 19-character labels and
    a 121.2 px left axis against 45.7 px for an ordinary control on the same
    chart. The only lever left is the range: ``_frame_to_nice`` now treats a
    span at or below ``_DEGENERATE_SPAN_RATIO`` of its own magnitude as the
    constant it is, so ``per_div`` never lands near 1e-15 and ``_fmt_tick``
    never has 15 decimals to print.

    The width bound is one-sided on purpose. A collapsed residue channel is
    framed to centre ±50%, whose round numbers (``16``, ``20``, …) are SHORTER
    than an ordinary channel's (``34.96``), so requiring equality would assert a
    coincidence. What the defect was is "much wider"; that is what is bounded.
    """

    def _canvas(self, signal):
        from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas

        canvas = PgLineCanvas()
        canvas.resize(900, 700)
        canvas.show()
        QCoreApplication.processEvents()
        freq = np.linspace(0.0, 500.0, 2000)
        canvas.plot_spectra(
            [{
                "label": "mMotorTorq",
                "freq": freq,
                "amp": 0.8 * np.exp(-freq / 80.0),
                "color": "#7070e0",
                "unit": "Nm",
            }],
            xlim=(0.0, 500.0),
            amp_label="Amplitude (Nm)",
            title="spectrum",
        )
        canvas.plot_time_preview(
            [{"label": "calc", "time": _T, "signal": signal, "color": "#e06010"}],
        )
        QCoreApplication.processEvents()
        # 「Y 轴自适应」 on the preview row — the path that re-frames and
        # re-pins the graticule ticks.
        canvas._fit_y_to_visible_x(canvas._plot_time)
        QCoreApplication.processEvents()
        return canvas

    def _facts(self, signal):
        canvas = self._canvas(signal)
        try:
            axis = canvas._plot_time.getAxis("left")
            return (
                axis_tick_texts(axis),
                left_axis_width_for_ticks(axis),
                tuple(float(v) for v in canvas._plot_time.vb.viewRange()[1]),
            )
        finally:
            canvas.hide()
            canvas.deleteLater()

    def test_residue_channel_does_not_widen_the_preview_left_axis(self, qapp):
        residue_ticks, residue_width, residue_y = self._facts(
            _residue_only_signal(35.0)
        )
        normal_ticks, normal_width, _normal_y = self._facts(
            35.0 + np.sin(_T) * 0.7
        )

        assert normal_ticks, "control chart produced no Y ticks"
        assert residue_ticks, "residue chart produced no Y ticks"
        assert residue_width <= normal_width + 2.0, (
            f"the residue channel pinned the 时域预览 left axis to "
            f"{residue_width:.1f}px against {normal_width:.1f}px for the same "
            f"chart with an ordinary channel; its ticks are {residue_ticks!r}"
        )
        assert max(len(text) for text in residue_ticks) <= 8, residue_ticks

    def test_residue_channel_gets_a_readable_preview_y_range(self, qapp):
        """The range is the actual fix; the width above is its consequence."""
        _ticks, _width, (lo, hi) = self._facts(_residue_only_signal(35.0))
        assert hi - lo > 1.0, f"Y framed onto the float residue: [{lo!r}, {hi!r}]"
        assert lo < 35.0 < hi, f"35 Nm fell outside [{lo!r}, {hi!r}]"
