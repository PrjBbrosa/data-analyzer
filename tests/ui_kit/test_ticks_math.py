"""Unit tests for the shared nice-number tick math helpers.

These live in ``mf4_analyzer.ui_kit.ticks_math`` (the lowest UI layer) so
both the Analyzer pyqtgraph canvas and the Cockpit live-card sparklines can
reuse the same graticule math without importing ``ui.*``.
"""
import math

import pytest

from mf4_analyzer.ui_kit.ticks_math import (
    MAX_TICK_SIGNIFICANT_DIGITS,
    _nice_per_div,
    _frame_to_nice,
    _fmt_tick,
    bounded_tick_strings,
    pad_y_extent,
)


def test_nice_per_div_snaps_up():
    assert _nice_per_div(0.7) == 0.8
    assert _nice_per_div(23) == 25


def test_frame_to_nice_returns_n_plus_one_ticks():
    bottom, top, ticks = _frame_to_nice(0.0, 9.7, 4)
    assert len(ticks) == 5 and bottom <= 0.0 and top >= 9.7


def test_fmt_tick_compact():
    assert _fmt_tick(0.0) == "0"
    assert _fmt_tick(1500) == "1500"


# ----------------------------------------------------------------------
# pad_y_extent — 2026-08-09 "纵坐标 35.0000000034 把 canvas 推到右边"
# ----------------------------------------------------------------------
class TestPadYExtent:
    """The residue-only-span collapse, and the behaviours it must not change.

    A channel produced by channel maths is constant in intent but not
    bit-exact, so ``max - min`` is float64 rounding noise rather than a real
    span. Framing Y onto it is what let pyqtgraph emit 18-character tick
    labels; see ``_DEGENERATE_SPAN_RATIO``.
    """

    def test_ordinary_span_is_padded_five_percent_each_side(self):
        assert pad_y_extent(-35.0, 35.0) == pytest.approx((-38.5, 38.5))

    def test_exact_constant_keeps_the_legacy_five_percent_window(self):
        # Behaviour the old inlined ``hi <= lo`` branch had; must be identical
        # or every genuinely constant raw channel re-frames on this change.
        assert pad_y_extent(35.0, 35.0) == pytest.approx((33.25, 36.75))

    def test_constant_zero_opens_to_unit_range(self):
        assert pad_y_extent(0.0, 0.0) == pytest.approx((-1.0, 1.0))

    @pytest.mark.parametrize(
        "value", [35.0, -35.0, 0.5, 4800.0, 1e-3],
    )
    def test_float_residue_span_collapses_to_the_constant_window(self, value):
        """``A*3 - A*2 - A`` and friends: min/max differ by ~1 ULP."""
        lo = math.nextafter(value, -math.inf)
        hi = math.nextafter(value, math.inf)
        assert hi > lo, "precondition: the residue really is a nonzero span"

        got_lo, got_hi = pad_y_extent(lo, hi)

        expected = pad_y_extent(value, value)
        assert (got_lo, got_hi) == pytest.approx(expected)
        # The point of the collapse: the framed span is now a fraction of the
        # VALUE, not of the residue.
        assert got_hi - got_lo == pytest.approx(abs(value) * 0.1, rel=1e-9)

    def test_deliberate_ripple_zoom_is_left_alone(self):
        """A real 1e-5-relative window on a large offset must survive.

        This is the case the ratio must NOT swallow: motor torque sitting at
        35 Nm with 0.001 Nm of ripple is a view users ask for on purpose.
        """
        lo, hi = pad_y_extent(34.9995, 35.0005)
        assert (hi - lo) == pytest.approx(0.0011, rel=1e-9)

    def test_span_just_above_the_ratio_is_not_collapsed(self):
        lo, hi = 35.0, 35.0 + 35.0 * 1e-8
        padded_lo, padded_hi = pad_y_extent(lo, hi)
        assert padded_hi - padded_lo == pytest.approx((hi - lo) * 1.1, rel=1e-6)

    @pytest.mark.parametrize(
        "lo, hi",
        [(float("nan"), 1.0), (0.0, float("inf")), (float("-inf"), 0.0)],
    )
    def test_non_finite_extent_is_returned_untouched(self, lo, hi):
        # Inventing a range here would hide the caller's real problem.
        got_lo, got_hi = pad_y_extent(lo, hi)
        assert (repr(got_lo), repr(got_hi)) == (repr(lo), repr(hi))


# ----------------------------------------------------------------------
# _frame_to_nice — same 2026-08-09 defect, one layer further in
# ----------------------------------------------------------------------
class TestFrameToNiceDegenerateSpan:
    """The graticule framer has to make the same judgement ``pad_y_extent`` does.

    ``pad_y_extent`` guards the pyqtgraph auto-range path, but the two places
    that pin ticks EXPLICITLY — the batch report's ``settle_nice`` and the
    FFT/order canvas's 时域预览 row (``_reframe_time_y_to_grid``) — hand a raw
    ``min``/``max`` straight to ``_frame_to_nice`` and then format every label
    against the resulting per-division step. Explicit ``setTicks`` bypasses
    ``AxisItem.tickStrings``, so the label-bounding override cannot rescue them;
    the only thing that can is refusing to divide a residue span in the first
    place.

    A residue span divided into ``n`` parts gives a step near 1e-15, and
    ``_fmt_tick`` faithfully prints every digit that step implies — hence the
    reported ``'34.9999999999992'`` and a left axis demanding 136 px.
    """

    DIVISIONS = 6

    def _labels(self, bottom, top, ticks):
        per_div = (top - bottom) / self.DIVISIONS
        return [_fmt_tick(value, per_div) for value in ticks]

    @pytest.mark.parametrize("value", [35.0, -35.0, 0.5, 4800.0, 1e-3])
    def test_residue_span_frames_exactly_like_the_constant_it_is(self, value):
        """``A*3 - A*2 - A`` must land on the window ``A`` itself would get.

        Asserted against ``_frame_to_nice(value, value, n)`` rather than a
        hand-written window: the point of the change is that residue inputs
        now take the branch bit-exact constants have always taken, so the
        reference is that branch's own output.
        """
        lo = math.nextafter(value, -math.inf)
        hi = math.nextafter(value, math.inf)
        assert hi > lo, "precondition: the residue really is a nonzero span"

        bottom, top, ticks = _frame_to_nice(lo, hi, self.DIVISIONS)
        ref_bottom, ref_top, ref_ticks = _frame_to_nice(
            value, value, self.DIVISIONS
        )

        assert (bottom, top) == pytest.approx((ref_bottom, ref_top))
        assert ticks == pytest.approx(ref_ticks)
        assert bottom < value < top, f"{value} fell outside [{bottom!r}, {top!r}]"
        # The whole defect in one number: the framed window is a fraction of
        # the VALUE now, not of its rounding residue.
        assert top - bottom >= max(abs(value), 1.0)

    @pytest.mark.parametrize("value", [35.0, -35.0, 0.5, 4800.0, 1e-3])
    def test_residue_span_labels_stay_short(self, value):
        """What the user sees. ``_fmt_tick`` derives its decimals from the
        per-division step, so this is the assertion that actually tracks the
        136 px left axis back to its cause."""
        bottom, top, ticks = _frame_to_nice(
            math.nextafter(value, -math.inf),
            math.nextafter(value, math.inf),
            self.DIVISIONS,
        )
        labels = self._labels(bottom, top, ticks)
        assert max(len(text) for text in labels) <= 8, labels

    @pytest.mark.parametrize(
        "lo, hi, tag",
        [
            (-35.0, 35.0, "±35 Nm 电机扭矩"),
            (0.0, 480000.0, "480 kN 齿条力"),
            (-0.04, 0.04, "±0.04 Nm 摩擦补偿"),
            (34.9995, 35.0005, "35 Nm 上的 1e-5 相对纹波窗"),
            (35.0, 35.0 + 35.0 * 1e-8, "刚好在比例阈值之上"),
            (1000.0, 1000.7, "大偏置上的真实小量程"),
        ],
    )
    def test_a_real_span_is_still_framed_around_itself(self, lo, hi, tag):
        """Nothing that carries information may be swallowed by the ratio.

        Two properties together say "not collapsed": the framed window still
        contains the input, and it is still TIGHT around it. The degenerate
        branch always opens to at least ``max(|centre|, 1)``, so any collapse
        of these inputs would blow the second bound by orders of magnitude
        (the 1e-5 ripple window would go from 0.0012 wide to 35 wide).
        """
        bottom, top, ticks = _frame_to_nice(lo, hi, self.DIVISIONS)
        assert bottom <= lo and top >= hi, tag
        assert top - bottom <= (hi - lo) * 2.0, tag
        assert len(ticks) == self.DIVISIONS + 1, tag

    def test_an_ordinary_axis_keeps_its_exact_previous_framing(self):
        """One byte-level lock, so "tight enough" above cannot drift silently."""
        bottom, top, ticks = _frame_to_nice(-35.0, 35.0, 6)
        assert (bottom, top) == pytest.approx((-36.0, 36.0))
        assert ticks == pytest.approx(
            [-36.0, -24.0, -12.0, 0.0, 12.0, 24.0, 36.0]
        )

    def test_all_zero_input_is_unchanged(self):
        """At zero magnitude the ratio threshold IS zero, so the new test
        degenerates to the old ``span <= 0`` and this branch cannot have
        moved — a bit-exactly constant zero channel keeps its ±0.5 window."""
        bottom, top, ticks = _frame_to_nice(0.0, 0.0, 6)
        assert (bottom, top) == pytest.approx((-0.6, 0.6))
        assert len(ticks) == 7

    @pytest.mark.parametrize(
        "lo, hi",
        [
            (float("nan"), 1.0),
            (0.0, float("inf")),
            (float("-inf"), float("inf")),
        ],
    )
    def test_non_finite_input_still_lands_on_the_finite_fallback(self, lo, hi):
        """The non-finite leg has to keep short-circuiting ahead of the ratio,
        or a nan/inf magnitude poisons the comparison and the function returns
        a nan graticule instead of the unit window it falls back to today."""
        bottom, top, ticks = _frame_to_nice(lo, hi, 6)
        assert math.isfinite(bottom) and math.isfinite(top)
        assert (bottom, top) == pytest.approx((-0.6, 0.6))
        assert all(math.isfinite(value) for value in ticks)


# ----------------------------------------------------------------------
# bounded_tick_strings
# ----------------------------------------------------------------------
class TestBoundedTickStrings:
    """Byte-identical to pyqtgraph everywhere except on noise digits.

    The parity clause is the load-bearing one: ``ui_kit.axis_metrics`` sizes
    left axes from these strings and the batch/GUI render parity guards
    compare what both sides draw, so a formatting change on an ordinary
    engineering axis would ripple straight into both.
    """

    def _pyqtgraph_reference(self, values, scale, spacing):
        """pyqtgraph 0.14 ``AxisItem.tickStrings``, transcribed.

        Transcribed rather than called so this stays a pure test — importing
        pyqtgraph here would drag Qt into the ``ui_kit`` unit suite. The
        end-to-end equivalence against the real AxisItem is asserted in
        ``tests/ui/test_y_axis_label_length.py``.
        """
        places = max(0, math.ceil(-math.log10(spacing * scale)))
        out = []
        for value in values:
            scaled = value * scale
            if abs(scaled) < .001 or abs(scaled) >= 10000:
                out.append("%g" % scaled)
            else:
                out.append(("%%0.%df" % places) % scaled)
        return out

    @pytest.mark.parametrize(
        "values, spacing, tag",
        [
            ([-30.0, -20.0, 0.0, 20.0, 30.0], 10.0, "±35 Nm 电机扭矩"),
            ([0.96, 0.98, 1.0, 1.02, 1.04], 0.02, "恒 1 状态量"),
            ([-0.02, 0.0, 0.02, 0.04], 0.02, "±0.04 Nm 摩擦补偿"),
            ([0.0, 240000.0, 480000.0], 1e5, "480 kN 齿条力"),
            ([85.5795, 85.57953, 85.57956], 3e-5, "深缩放时间窗"),
            ([1000.00001, 1000.00002], 1e-5, "1e-8 相对分辨率（预算边界内）"),
            ([1.2e-4, 2.4e-4], 1.2e-4, "小量走 %g 分支"),
        ],
    )
    def test_matches_pyqtgraph_on_every_realistic_axis(self, values, spacing, tag):
        assert bounded_tick_strings(values, 1.0, spacing) == \
            self._pyqtgraph_reference(values, 1.0, spacing), tag

    def test_float_residue_axis_stops_printing_noise_digits(self):
        """The reported defect, at the formatting layer.

        pyqtgraph has no exit from its fixed-point branch, so it prints every
        digit of the mantissa; 18 characters measure ~143 px against the
        ~24 px a plain ``-35`` needs, and that width gets pinned onto every
        subplot row.
        """
        values = [34.99999999999999, 35.0, 35.00000000000001]
        spacing = 2e-15

        reference = self._pyqtgraph_reference(values, 1.0, spacing)
        assert max(len(text) for text in reference) == 18, (
            f"precondition: pyqtgraph should still be the long one, got {reference!r}"
        )

        bounded = bounded_tick_strings(values, 1.0, spacing)
        assert bounded == ["35", "35", "35"]

    @pytest.mark.parametrize(
        "value, spacing",
        [
            (35.000000000000007, 2e-15),
            (1000.00000001, 1e-8),
            (9999.000000001, 1e-9),
            (0.0012345678901234, 1e-16),
        ],
    )
    def test_never_exceeds_the_significant_digit_budget(self, value, spacing):
        (text,) = bounded_tick_strings([value], 1.0, spacing)
        # Leading zeros are placeholders, not significant digits: 0.00123456789
        # carries nine, and its length is bounded by that, not by the budget.
        mantissa = text.split("e")[0].lstrip("-").replace(".", "")
        assert len(mantissa.lstrip("0")) <= MAX_TICK_SIGNIFICANT_DIGITS, text

    def test_scale_factor_is_applied_like_pyqtgraph(self):
        # pyqtgraph feeds autoSIPrefixScale * scale through; the branch
        # thresholds are evaluated on the SCALED value, not the raw one.
        assert bounded_tick_strings([0.035], 1000.0, 0.01) == \
            self._pyqtgraph_reference([0.035], 1000.0, 0.01)

    def test_non_finite_values_do_not_raise(self):
        assert bounded_tick_strings(
            [float("nan"), float("inf"), 1.0], 1.0, 0.5
        ) == ["nan", "inf", "1.0"]

    @pytest.mark.parametrize("spacing", [0.0, -1.0, float("nan")])
    def test_unusable_spacing_raises_for_the_caller_to_fall_back(self, spacing):
        # GridLabelSlackAxisItem.tickStrings catches these and defers to
        # pyqtgraph rather than inventing labels.
        with pytest.raises((ValueError, OverflowError)):
            bounded_tick_strings([1.0], 1.0, spacing)
