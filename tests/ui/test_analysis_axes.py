"""Direct unit tests for the analysis-canvas shared axis/tick/dB layer.

These module-level helpers are shared by the FFT line canvas and the
FFT-vs-Time / Order heatmap canvases. Until now they were only covered
*indirectly*, through a fully built canvas — so a regression in the pure
math surfaced as a confusing canvas-level failure, and the edge cases
(empty input, all-NaN, degenerate ranges) had no coverage at all. This
file pins them directly, per the pg_canvas shared-axes design (D-B3).

These tests were written against ``heatmap_canvas`` — where the symbols
lived before the extraction — and passed there unchanged before the move.
The import below is now re-pointed at ``analysis_axes``; that one-line
change is the whole point of writing them first, since the same
assertions passing on both sides is the evidence the move preserved
behaviour.

Every expectation here was read off the baseline implementation rather
than guessed, so the file is a characterization net: it locks in current
behaviour, including the quirk flagged in ``test_*_current_behaviour``.
"""
import math

import numpy as np
import pyqtgraph as pg
import pytest
from PyQt5.QtGui import QFont

from mf4_analyzer.ui.pg_canvas.analysis_axes import (
    _apply_axis_tick_density,
    _apply_target_bottom_ticks,
    _BOTTOM_TICK_FIT_MEMO_ATTR,
    _apply_neutral_axis_frame,
    _AUTO_CEILING_HEADROOM_DB,
    _AUTO_CEILING_PCT,
    _AUTO_SPAN_DB,
    _auto_db_window,
    _BoundaryGridAxisItem,
    _colorbar_is_dead,
    _finite_data_bounds,
    _finite_float,
    _hide_plot_title,
    _make_analysis_plot,
    _robust_db_ceiling,
    _SLICE_MAX_SPAN_DB,
    _slice_amp_bounds,
    _SmoothImageItem,
    _tick_counts_to_density,
    _visual_padded_bounds,
    time_axis_display_extent,
)


# --------------------------------------------------------------------------
# _finite_float / _finite_data_bounds — the NaN/inf gatekeepers
# --------------------------------------------------------------------------

def test_finite_float_passes_real_numbers_through():
    assert _finite_float(1.5) == 1.5
    assert _finite_float("2.5") == 2.5          # numeric strings are coerced
    assert _finite_float(np.float64(3.0)) == 3.0


def test_finite_float_rejects_uncoercible_and_nonfinite():
    assert _finite_float(None) is None
    assert _finite_float("abc") is None
    assert _finite_float(float("nan")) is None
    assert _finite_float(float("inf")) is None


def test_finite_data_bounds_returns_min_max_of_finite_cells():
    assert _finite_data_bounds(np.array([[1.0, 2.0], [3.0, 4.0]])) == (1.0, 4.0)


def test_finite_data_bounds_ignores_nan_and_inf():
    # inf must not become the upper bound; only finite cells count.
    m = np.array([[1.0, np.inf], [-np.inf, 4.0]])
    assert _finite_data_bounds(m) == (1.0, 4.0)


def test_finite_data_bounds_falls_back_when_nothing_is_finite():
    # No finite data at all → sentinel None (B5: do not invent 0..1).
    assert _finite_data_bounds(np.full((2, 2), np.nan)) is None
    assert _finite_data_bounds(np.array([])) is None


def test_finite_data_bounds_widens_a_degenerate_range():
    # A flat matrix would give hi == lo, which is unusable as an axis range.
    assert _finite_data_bounds(np.full((2, 2), 5.0)) == (5.0, 6.0)


def test_finite_data_bounds_widens_residue_only_span():
    # float64 channel-math residue must not become a 1e-16 colour window (B5).
    from mf4_analyzer.ui_kit.ticks_math import _DEGENERATE_SPAN_RATIO

    lo = 35.0
    hi = lo + lo * _DEGENERATE_SPAN_RATIO * 0.5
    assert _finite_data_bounds(np.array([[lo, hi]])) == (lo, lo + 1.0)


# --------------------------------------------------------------------------
# _colorbar_is_dead — "has the colour window collapsed the image?"
# --------------------------------------------------------------------------

def _gradient_matrix():
    return np.linspace(-80.0, 0.0, 400).reshape(20, 20)


def test_colorbar_is_alive_for_a_window_over_the_data():
    assert _colorbar_is_dead(_gradient_matrix(), -60.0, 0.0) is False


def test_colorbar_is_dead_when_window_sits_off_the_data():
    # Every cell clamps to one end → flat single-colour image.
    assert _colorbar_is_dead(_gradient_matrix(), 50.0, 60.0) is True


def test_colorbar_is_dead_for_degenerate_and_inverted_windows():
    assert _colorbar_is_dead(_gradient_matrix(), 5.0, 5.0) is True
    assert _colorbar_is_dead(_gradient_matrix(), 0.0, -60.0) is True


def test_colorbar_is_not_dead_without_data_to_judge():
    # No matrix / no finite cells → nothing to nudge the user about.
    assert _colorbar_is_dead(None, -60.0, 0.0) is False
    assert _colorbar_is_dead(np.full((4, 4), np.nan), -1.0, 1.0) is False


# --------------------------------------------------------------------------
# _robust_db_ceiling / _auto_db_window — the absolute-dB auto colour window
# --------------------------------------------------------------------------

def test_robust_db_ceiling_is_the_99th_percentile():
    values = np.arange(100, dtype=float)
    assert _robust_db_ceiling(values) == pytest.approx(98.01)
    assert _robust_db_ceiling(values) == pytest.approx(
        float(np.percentile(values, _AUTO_CEILING_PCT))
    )


def test_robust_db_ceiling_ignores_a_lone_transient_peak():
    # The whole point: one bright spike must not drag the window up and
    # bury the informative bulk below the floor.
    spiky = np.concatenate([np.full(999, -50.0), np.array([100.0])])
    assert float(np.nanmax(spiky)) == 100.0        # what nanmax would have picked
    assert _robust_db_ceiling(spiky) == pytest.approx(-50.0)


def test_robust_db_ceiling_honours_an_explicit_percentile():
    assert _robust_db_ceiling(np.arange(100, dtype=float), 50.0) == pytest.approx(49.5)


def test_robust_db_ceiling_falls_back_when_nothing_is_finite():
    # No finite cells → sentinel None (B5), not an invented 1.0.
    assert _robust_db_ceiling(np.full((4, 4), np.nan)) is None


def test_auto_db_window_caps_a_short_tail_at_the_finite_max():
    # arange tail is under 1 dB, so the 5 dB headroom must not open empty scale.
    values = np.arange(100, dtype=float)
    anchor = _robust_db_ceiling(values, _AUTO_CEILING_PCT)
    vmin, vmax = _auto_db_window(values)
    assert vmin == pytest.approx(anchor - _AUTO_SPAN_DB)
    assert vmax == pytest.approx(float(np.max(values)))
    assert (vmin, vmax) == pytest.approx((68.01, 99.0))


def test_auto_db_window_headroom_does_not_lift_the_floor():
    # One transient sits far above the percentile. Ceiling gains 5 dB;
    # the floor stays 30 dB below the percentile, not below the new ceiling.
    spiky = np.concatenate([np.full(999, -50.0), np.array([100.0])])
    anchor = _robust_db_ceiling(spiky, _AUTO_CEILING_PCT)
    vmin, vmax = _auto_db_window(spiky)
    assert anchor == pytest.approx(-50.0)
    assert vmin == pytest.approx(anchor - _AUTO_SPAN_DB)
    assert vmax == pytest.approx(anchor + _AUTO_CEILING_HEADROOM_DB)
    assert vmax < float(np.max(spiky))


def test_auto_db_window_default_span_is_30_db():
    assert _AUTO_SPAN_DB == 30.0
    assert _AUTO_CEILING_PCT == 99.0
    assert _AUTO_CEILING_HEADROOM_DB == 5.0


def test_batch_finite_auto_db_limits_match_the_shared_window():
    from mf4_analyzer.batch_render_qt._builder import (
        _EMPTY_DB_LEVEL,
        _auto_db_color_limits,
    )

    values = np.array([-80.0, -40.0, -10.0, 5.0, 40.0, np.nan])
    assert _auto_db_color_limits(values) == pytest.approx(_auto_db_window(values))
    empty = _auto_db_color_limits(np.array([np.nan, np.inf]))
    assert empty == pytest.approx((
        _EMPTY_DB_LEVEL - _AUTO_SPAN_DB,
        _EMPTY_DB_LEVEL,
    ))
    assert _auto_db_window(np.array([np.nan, np.inf])) is None


def test_auto_db_window_on_an_all_zero_matrix():
    # Degenerate but common (a freshly zeroed buffer): ceiling 0, span below.
    assert _auto_db_window(np.zeros((8, 8))) == pytest.approx((-30.0, 0.0))


def test_auto_db_window_keeps_its_span_when_nothing_is_finite():
    assert _auto_db_window(np.full((4, 4), np.nan)) is None


# --------------------------------------------------------------------------
# _slice_amp_bounds — robust Y view range for the slice curve
# --------------------------------------------------------------------------

def test_slice_amp_bounds_empty_and_constants():
    assert _slice_amp_bounds(np.array([])) is None
    assert _slice_amp_bounds(np.full(5, np.nan)) is None
    assert _slice_amp_bounds(np.array([3.0])) == (2.0, 4.0)
    assert _slice_amp_bounds(np.array([7.0, 7.0])) == (6.0, 8.0)


def test_slice_amp_bounds_preserves_small_finite_spread():
    lo, hi = 35.0, 35.00001
    bounds = _slice_amp_bounds(np.array([lo, hi]))
    assert bounds[0] < lo and bounds[1] > hi


def test_slice_amp_bounds_spans_normal_data():
    assert _slice_amp_bounds(np.array([-60.0, -40.0, -50.0])) == (-61.0, -39.0)


def test_slice_amp_bounds_ignores_inf():
    assert _slice_amp_bounds(np.array([np.inf, -10.0, -20.0])) == (-20.5, -9.5)


def test_slice_amp_bounds_excludes_only_explicit_invalid_sources():
    floor = 20.0 * np.log10(np.finfo(float).tiny)
    values = np.array([floor, -40.0, -60.0, -50.0])
    assert _slice_amp_bounds(values, valid_mask=[False, True, True, True]) == (-61.0, -39.0)
    assert _slice_amp_bounds(values)[0] < floor


def test_slice_amp_bounds_keeps_a_bin_at_old_span_limit():
    assert _SLICE_MAX_SPAN_DB == 200.0  # compatibility constant only
    assert _slice_amp_bounds(np.array([0.0, -200.0])) == (-210.0, 10.0)


def test_slice_amp_bounds_preserves_deeper_nonzero_valleys():
    assert _slice_amp_bounds(np.array([0.0, -300.0, -30.0])) == (-315.0, 15.0)


# --------------------------------------------------------------------------
# _visual_padded_bounds — the tiny Home/View-All display margin
# --------------------------------------------------------------------------

def test_visual_padded_bounds_adds_a_small_symmetric_margin():
    assert _visual_padded_bounds(0.0, 100.0) == pytest.approx((-1.5, 101.5))


def test_visual_padded_bounds_honours_an_explicit_fraction():
    assert _visual_padded_bounds(0.0, 100.0, fraction=0.1) == pytest.approx((-10.0, 110.0))


def test_visual_padded_bounds_works_on_a_negative_interval():
    assert _visual_padded_bounds(-50.0, -10.0) == pytest.approx((-50.6, -9.4))


def test_visual_padded_bounds_passes_degenerate_input_through():
    # lo == hi and inverted ranges have no span to pad → returned unchanged.
    assert _visual_padded_bounds(5.0, 5.0) == (5.0, 5.0)
    assert _visual_padded_bounds(10.0, 0.0) == (10.0, 0.0)


def test_visual_padded_bounds_passes_nonfinite_input_through():
    lo, hi = _visual_padded_bounds(float("nan"), 1.0)
    assert np.isnan(lo) and hi == 1.0


# --------------------------------------------------------------------------
# time_axis_display_extent — three resolution paths, in priority order
# --------------------------------------------------------------------------

class _Params:
    """Stand-in for SpectrogramParams (only fs/nfft are read)."""

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


_CENTERS = np.array([0.5, 1.0, 1.5, 2.0])


def test_time_axis_extent_prefers_metadata_coverage():
    # Analyzer coverage wins even when params could compute a window.
    assert time_axis_display_extent(
        _CENTERS,
        params=_Params(fs=1000.0, nfft=1001),
        metadata={'coverage_start': 0.0, 'coverage_end': 3.0},
    ) == (0.0, 3.0)


def test_time_axis_extent_ignores_unusable_metadata():
    # hi <= lo, or a half-filled coverage pair, falls through to params.
    inverted = time_axis_display_extent(
        _CENTERS,
        params=_Params(fs=1000.0, nfft=1001),
        metadata={'coverage_start': 5.0, 'coverage_end': 1.0},
    )
    partial = time_axis_display_extent(
        _CENTERS,
        params=_Params(fs=1000.0, nfft=1001),
        metadata={'coverage_start': 0.0},
    )
    assert inverted == pytest.approx((0.0, 2.5))
    assert partial == pytest.approx((0.0, 2.5))


def test_time_axis_extent_expands_by_half_the_analysis_window():
    # half_window = (nfft - 1) / (2 * fs) = 1000 / 2000 = 0.5
    assert time_axis_display_extent(
        _CENTERS, params=_Params(fs=1000.0, nfft=1001),
    ) == pytest.approx((0.0, 2.5))


def test_time_axis_extent_clamps_a_nonnegative_start_to_zero():
    # 0.5 - 0.5 = 0.0 exactly here; with a wider window it would go negative
    # and still be clamped, because time cannot start before zero.
    assert time_axis_display_extent(
        np.array([0.0, 1.0]), params=_Params(fs=1000.0, nfft=1001),
    ) == pytest.approx((0.0, 1.5))


def test_time_axis_extent_falls_back_to_frame_spacing():
    # Unusable fs/nfft → half the first/last gap on each side.
    for params in (
        _Params(fs=1000.0, nfft=1),      # nfft <= 1
        _Params(fs=None, nfft=1001),     # no sample rate
        _Params(fs=1000.0, nfft='xx'),   # uncoercible nfft
    ):
        assert time_axis_display_extent(
            _CENTERS, params=params,
        ) == pytest.approx((0.25, 2.25))


def test_time_axis_extent_keeps_a_negative_start_unclamped():
    # The clamp only applies when the first center is already >= 0.
    assert time_axis_display_extent(
        np.array([-1.0, 0.0, 1.0]), params=_Params(fs=0.0, nfft=0),
    ) == pytest.approx((-1.5, 1.5))


def test_time_axis_extent_degenerates_to_a_point_for_one_center():
    assert time_axis_display_extent(
        np.array([2.0]), params=_Params(fs=0.0, nfft=0),
    ) == (2.0, 2.0)


def test_time_axis_extent_filters_nonfinite_centers():
    assert time_axis_display_extent(
        np.array([np.nan, 1.0, 2.0]), params=_Params(fs=0.0, nfft=0),
    ) == pytest.approx((0.5, 2.5))


def test_time_axis_extent_uses_fallback_only_when_there_are_no_centers():
    assert time_axis_display_extent(np.array([]), fallback=(1.0, 9.0)) == (1.0, 9.0)
    assert time_axis_display_extent(np.array([])) == (0.0, 0.0)
    # Metadata still outranks the fallback.
    assert time_axis_display_extent(
        np.array([]),
        metadata={'coverage_start': 2.0, 'coverage_end': 4.0},
        fallback=(1.0, 9.0),
    ) == (2.0, 4.0)


def test_time_axis_extent_params_none_raises_current_behaviour():
    """Characterization of a latent bug — NOT an endorsement.

    ``params`` is declared ``params=None``, but the nfft read uses the
    two-argument ``getattr(params, 'nfft')`` (no default) while the guard
    around it only catches ``(TypeError, ValueError)``. So the documented
    default blows up with ``AttributeError`` for any non-empty ``times``.
    Every production caller passes real params, which is why this has gone
    unnoticed. Pinned here so the move cannot change it silently; fixing it
    is deliberately out of scope for the extraction (record, don't fix).
    """
    with pytest.raises(AttributeError):
        time_axis_display_extent(_CENTERS)

    # The empty-times path skips the faulty read, so it survives params=None.
    assert time_axis_display_extent(np.array([]), fallback=(1.0, 2.0)) == (1.0, 2.0)


# --------------------------------------------------------------------------
# _tick_counts_to_density  <->  _apply_axis_tick_density round trip
# --------------------------------------------------------------------------

def test_tick_counts_to_density_uses_the_documented_divisors():
    # x_n/10, y_n/6 — the time-domain canvas convention.
    assert _tick_counts_to_density(10, 10) == pytest.approx((1.0, 10 / 6.0))
    assert _tick_counts_to_density(12, 8) == pytest.approx((1.2, 8 / 6.0))


def test_tick_counts_to_density_clamps_both_ends():
    assert _tick_counts_to_density(1, 1) == (0.35, 0.35)          # low clamp
    assert _tick_counts_to_density(100, 100) == (3.0, 3.0)        # high clamp
    assert _tick_counts_to_density(3, 3) == pytest.approx((0.35, 0.5))
    assert _tick_counts_to_density(30, 20) == (3.0, 3.0)


@pytest.mark.parametrize("x_n,y_n", [(3, 3), (10, 10), (30, 20), (12, 8)])
def test_density_survives_the_round_trip_onto_real_axes(qapp, x_n, y_n):
    """Counts → density → axis must land exactly, with no drift."""
    x_d, y_d = _tick_counts_to_density(x_n, y_n)
    bottom = pg.AxisItem(orientation='bottom')
    left = pg.AxisItem(orientation='left')

    _apply_axis_tick_density(bottom, x_d)
    _apply_axis_tick_density(left, y_d)

    assert bottom._tickDensity == pytest.approx(x_d)
    assert left._tickDensity == pytest.approx(y_d)


def test_apply_axis_tick_density_clears_pinned_ticks_and_subgrid(qapp):
    axis = pg.AxisItem(orientation='bottom')
    axis.setTicks([[(0.0, "0"), (1.0, "1")], []])
    assert axis._tickLevels is not None

    _apply_axis_tick_density(axis, 1.0)

    # Explicit ticks are released so density can take over again, and the
    # minor sub-grid stays off (major-only, matching the time-domain grid).
    assert axis._tickLevels is None
    assert axis.style['maxTickLevel'] == 0


def test_apply_axis_tick_density_tolerates_a_failing_set_ticks(qapp):
    """A setTicks that raises must not abort the density update."""
    class _BrokenAxis(pg.AxisItem):
        def setTicks(self, *args, **kwargs):
            raise RuntimeError("boom")

    axis = _BrokenAxis(orientation='bottom')
    _apply_axis_tick_density(axis, 1.25)
    assert axis._tickDensity == pytest.approx(1.25)


# --------------------------------------------------------------------------
# _make_analysis_plot / _apply_neutral_axis_frame / _hide_plot_title
# --------------------------------------------------------------------------

def test_make_analysis_plot_installs_boundary_grid_axes(qapp):
    glw = pg.GraphicsLayoutWidget()
    plot = _make_analysis_plot(glw, 0, 0, pg.ViewBox())

    # left+bottom carry the grid, so they get the boundary-suppressing axis;
    # top/right are plain frame lines and stay stock AxisItems.
    assert isinstance(plot.getAxis('left'), _BoundaryGridAxisItem)
    assert isinstance(plot.getAxis('bottom'), _BoundaryGridAxisItem)
    assert not isinstance(plot.getAxis('top'), _BoundaryGridAxisItem)
    assert not isinstance(plot.getAxis('right'), _BoundaryGridAxisItem)


def test_apply_neutral_axis_frame_clears_the_viewbox_border(qapp):
    """The frame must be composed from axes only — no ViewBox border on top.

    pg 0.14 stores a NoPen QPen for setBorder(None), so ViewBox.paint still
    enters its border branch; the private value has to be cleared too.
    """
    glw = pg.GraphicsLayoutWidget()
    plot = _make_analysis_plot(glw, 0, 0, pg.ViewBox())

    _apply_neutral_axis_frame(plot)

    assert plot.getViewBox().border is None


def test_apply_neutral_axis_frame_sets_major_only_grid_and_mute_top_right(qapp):
    glw = pg.GraphicsLayoutWidget()
    plot = _make_analysis_plot(glw, 0, 0, pg.ViewBox())

    _apply_neutral_axis_frame(plot)

    for side in ('left', 'bottom'):
        assert plot.getAxis(side).style['maxTickLevel'] == 0
    for side in ('top', 'right'):
        axis = plot.getAxis(side)
        assert axis.style['showValues'] is False
        assert axis.style['tickLength'] == 0


def test_hide_plot_title_collapses_the_title_row(qapp):
    glw = pg.GraphicsLayoutWidget()
    plot = _make_analysis_plot(glw, 0, 0, pg.ViewBox())

    _hide_plot_title(plot)

    label = plot.titleLabel
    assert label.isVisible() is False
    assert label.maximumHeight() == 0


# --------------------------------------------------------------------------
# _SmoothImageItem — the interpolation-hint toggle
# --------------------------------------------------------------------------

def test_smooth_image_item_defaults_to_no_smoothing(qapp):
    assert _SmoothImageItem().smooth_transform_enabled() is False


def test_smooth_image_item_toggles_and_coerces_to_bool(qapp):
    item = _SmoothImageItem()

    item.set_smooth_transform(True)
    assert item.smooth_transform_enabled() is True
    item.set_smooth_transform(True)              # idempotent, no-op early out
    assert item.smooth_transform_enabled() is True

    item.set_smooth_transform(0)                 # falsy → coerced to False
    assert item.smooth_transform_enabled() is False


# --------------------------------------------------------------------------
# _apply_target_bottom_ticks — parity with the frozen pre-memo algorithm.
# Use identical live metrics on both paths, rather than one OS's tick table.
# The same cases run at DPR 1 / 1.25 / 1.5 / 2 (F1 memo, F2 pruning).
# --------------------------------------------------------------------------

_FROZEN_BOTTOM_TICK_DPRS = (1.0, 1.25, 1.5, 2.0)

def _fixed4_tick_strings(values, scale, spacing):
    factor = float(scale)
    return [format(float(value) * factor, ".4g") for value in values]


_BOTTOM_TICK_CASES = tuple(
    (lo, hi, width, target, formatter)
    for lo, hi in ((0.0, 7.162), (0.0, 30.0), (-12.5, 80.0), (0.0001, 0.025), (0.0, 1000000.0), (35.0, 35.02), (-2500.0, -3.0))
    for width in (80.0, 137.5, 320.0, 505.0, 1000.0, 2000.0)
    for target in (3, 8, 10, 16)
    for formatter in ("default", "fixed4")
)


class _TickView:
    def __init__(self, lo, hi, y_lo=0.0, y_hi=1.0):
        self.lo = lo
        self.hi = hi
        self.y_lo = y_lo
        self.y_hi = y_hi

    def viewRange(self):
        return [(self.lo, self.hi), (self.y_lo, self.y_hi)]


class _TickOwner:
    def __init__(self, dpr=1.0, visible=True):
        self.dpr = dpr
        self.visible = visible

    def isVisible(self):
        return self.visible

    def devicePixelRatioF(self):
        return float(self.dpr)


def _install_bottom_formatter(axis, formatter):
    if formatter == "fixed4":
        axis.tickStrings = _fixed4_tick_strings
    elif "tickStrings" in axis.__dict__:
        del axis.tickStrings


def _pinned_bottom_ticks(axis):
    levels = getattr(axis, "_tickLevels", None)
    if not levels or not levels[0]:
        return None
    return tuple((float(value), str(text)) for value, text in levels[0])


def _apply_frozen_case(axis, view, owner, params):
    lo, hi, width, target, formatter = params
    view.lo = lo
    view.hi = hi
    axis.resize(float(width), 30)
    _install_bottom_formatter(axis, formatter)
    return _apply_target_bottom_ticks(axis, view, target, owner)


def _reference_bottom_ticks(params):
    from tests._helpers.analysis_tick_reference import reference_bottom_ticks

    lo, hi, width, target, formatter = params
    axis = _BoundaryGridAxisItem(orientation="bottom")
    try:
        axis.resize(width, 30)
        _install_bottom_formatter(axis, formatter)
        ok = reference_bottom_ticks(axis, _TickView(lo, hi), target, _TickOwner())
        return _pinned_bottom_ticks(axis) if ok else None
    finally:
        axis.deleteLater()


def test_target_bottom_ticks_match_frozen_grid_across_dpr(qapp):
    """336 fits × 4 DPRs match the original algorithm under the same font."""
    assert len(_BOTTOM_TICK_CASES) == 336
    assert len(set(_BOTTOM_TICK_CASES)) == 336
    assert _FROZEN_BOTTOM_TICK_DPRS == (1.0, 1.25, 1.5, 2.0)
    axis = _BoundaryGridAxisItem(orientation="bottom")
    view = _TickView(0.0, 1.0)
    owner = _TickOwner()
    try:
        for params in _BOTTOM_TICK_CASES:
            expected = _reference_bottom_ticks(params)
            for dpr in _FROZEN_BOTTOM_TICK_DPRS:
                owner.dpr = dpr
                ok = _apply_frozen_case(axis, view, owner, params)
                if expected is None:
                    assert ok is False, params
                    continue
                assert ok is True, (params, dpr)
                got = _pinned_bottom_ticks(axis)
                assert got == expected, (params, dpr, got, expected)
    finally:
        axis.deleteLater()


def test_extreme_narrow_bottom_ticks_still_thin(qapp):
    """width < target*8 keeps the thinned ladder; pruning must not drop it."""
    params = (0.0, 30.0, 80.0, 16, "default")
    expected = _reference_bottom_ticks(params)
    assert expected is not None and 3 <= len(expected) < 16
    assert 80.0 < 16 * 8.0
    axis = _BoundaryGridAxisItem(orientation="bottom")
    try:
        ok = _apply_frozen_case(axis, _TickView(0.0, 1.0), _TickOwner(), params)
        assert ok is True
        assert _pinned_bottom_ticks(axis) == expected
    finally:
        axis.deleteLater()


def test_nonround_bottom_ticks_stay_on_the_half_step(qapp):
    params = (0.0, 7.162, 505.0, 10, "default")
    expected = _reference_bottom_ticks(params)
    assert expected is not None
    # Font widths may choose integer ticks; both lie on the half-step grid.
    assert all(value * 2 == round(value * 2) for value, _text in expected)
    axis = _BoundaryGridAxisItem(orientation="bottom")
    try:
        ok = _apply_frozen_case(axis, _TickView(0.0, 1.0), _TickOwner(), params)
        assert ok is True
        assert _pinned_bottom_ticks(axis) == expected
    finally:
        axis.deleteLater()


def _spy_axis(width=505.0):
    axis = _BoundaryGridAxisItem(orientation="bottom")
    axis.resize(width, 30)
    calls = {"n": 0}
    original = axis.tickStrings

    def spy(values, scale, spacing):
        calls["n"] += 1
        return original(values, scale, spacing)

    axis.tickStrings = spy
    return axis, calls


def test_bottom_tick_memo_skips_refit_and_prune_skips_strings(qapp):
    axis, calls = _spy_axis(505.0)
    view = _TickView(0.0, 7.162)
    owner = _TickOwner(dpr=1.0)
    try:
        assert _apply_target_bottom_ticks(axis, view, 10, owner) is True
        first = calls["n"]
        # Unpruned enumeration called tickStrings 18 times on this input.
        assert 0 < first < 18
        assert hasattr(axis, _BOTTOM_TICK_FIT_MEMO_ATTR)
        calls["n"] = 0
        assert _apply_target_bottom_ticks(axis, view, 10, owner) is True
        assert calls["n"] == 0
        assert _pinned_bottom_ticks(axis) == _reference_bottom_ticks(
            (0.0, 7.162, 505.0, 10, "default")
        )

        # A failed fit is remembered too: the second call does not enumerate.
        view.lo, view.hi = 0.0, 30.0
        axis.resize(80.0, 30)
        calls["n"] = 0
        assert _apply_target_bottom_ticks(axis, view, 3, owner) is False
        assert calls["n"] > 0
        calls["n"] = 0
        assert _apply_target_bottom_ticks(axis, view, 3, owner) is False
        assert calls["n"] == 0
    finally:
        axis.deleteLater()


def test_bottom_tick_memo_recomputes_when_the_key_changes(qapp, monkeypatch):
    axis, calls = _spy_axis(505.0)
    view = _TickView(0.0, 7.162)
    owner = _TickOwner(dpr=1.0)
    try:
        assert _apply_target_bottom_ticks(axis, view, 10, owner) is True

        def assert_refit(mutate):
            calls["n"] = 0
            mutate()
            assert _apply_target_bottom_ticks(axis, view, 10, owner) is True
            assert calls["n"] > 0, mutate

        assert_refit(lambda: setattr(view, "hi", math.nextafter(view.hi, math.inf)))
        # Put the range back, then change one field at a time from a warm cache.
        view.hi = 7.162
        assert _apply_target_bottom_ticks(axis, view, 10, owner) is True
        calls["n"] = 0
        assert _apply_target_bottom_ticks(axis, view, 10, owner) is True
        assert calls["n"] == 0

        # Y range is not an input. Exact same X floats must hit.
        calls["n"] = 0
        view.y_lo, view.y_hi = -4.0, 9.0
        assert _apply_target_bottom_ticks(axis, view, 10, owner) is True
        assert calls["n"] == 0
        other = _TickView(0.0, 7.162)
        assert _apply_target_bottom_ticks(axis, other, 10, owner) is True
        assert calls["n"] == 0

        calls["n"] = 0
        axis.resize(640.0, 30)
        assert _apply_target_bottom_ticks(axis, other, 10, owner) is True
        assert calls["n"] > 0
        axis.resize(505.0, 30)
        assert _apply_target_bottom_ticks(axis, other, 10, owner) is True

        calls["n"] = 0
        owner.dpr = 1.25
        assert _apply_target_bottom_ticks(axis, other, 10, owner) is True
        assert calls["n"] > 0
        owner.dpr = 1.5
        calls["n"] = 0
        assert _apply_target_bottom_ticks(axis, other, 10, owner) is True
        assert calls["n"] > 0
        owner.dpr = 2.0
        calls["n"] = 0
        assert _apply_target_bottom_ticks(axis, other, 10, owner) is True
        assert calls["n"] > 0
        owner.dpr = 1.0
        calls["n"] = 0
        assert _apply_target_bottom_ticks(axis, other, 10, owner) is True
        assert calls["n"] > 0

        calls["n"] = 0
        assert _apply_target_bottom_ticks(axis, other, 12, owner) is True
        assert calls["n"] > 0
        calls["n"] = 0
        assert _apply_target_bottom_ticks(axis, other, 10, owner) is True
        assert calls["n"] > 0

        calls["n"] = 0
        axis.setLabel("Torque")
        width_after_label = float(axis.size().width())
        if width_after_label != 505.0:
            axis.resize(505.0, 30)
        assert _apply_target_bottom_ticks(axis, other, 10, owner) is True
        assert calls["n"] == 0
        memo_key = getattr(axis, _BOTTOM_TICK_FIT_MEMO_ATTR)[0]
        assert "Torque" not in repr(memo_key)

        def bigger_font(_point_size=9.0):
            font = QFont("DejaVu Sans")
            font.setPointSizeF(28.0)
            return font

        monkeypatch.setattr(
            "mf4_analyzer.ui.pg_canvas.analysis_axes._pg_chart_font",
            bigger_font,
        )
        calls["n"] = 0
        _apply_target_bottom_ticks(axis, other, 10, owner)
        assert calls["n"] > 0
        monkeypatch.undo()

        calls["n"] = 0

        def other_formatter(values, scale, spacing):
            calls["n"] += 1
            return [format(float(value), ".6g") for value in values]

        axis.tickStrings = other_formatter
        _apply_target_bottom_ticks(axis, other, 10, owner)
        assert calls["n"] > 0

        calls["n"] = 0
        axis.setLogMode(True)
        if float(axis.size().width()) != 505.0:
            axis.resize(505.0, 30)
        _apply_target_bottom_ticks(axis, other, 10, owner)
        assert calls["n"] > 0

        calls["n"] = 0
        axis.scale = 2.0
        _apply_target_bottom_ticks(axis, other, 10, owner)
        assert calls["n"] > 0
    finally:
        axis.deleteLater()


def test_bottom_tick_memo_is_per_axis_and_hidden_owner_does_not_replay(qapp):
    first, first_calls = _spy_axis(505.0)
    second, second_calls = _spy_axis(505.0)
    view = _TickView(0.0, 7.162)
    owner = _TickOwner(visible=True)
    try:
        assert _apply_target_bottom_ticks(first, view, 10, owner) is True
        assert _apply_target_bottom_ticks(second, view, 10, owner) is True
        memo = getattr(first, _BOTTOM_TICK_FIT_MEMO_ATTR)
        assert getattr(second, _BOTTOM_TICK_FIT_MEMO_ATTR) is not memo
        key, applied, _frozen = memo
        assert applied is True
        setattr(
            first,
            _BOTTOM_TICK_FIT_MEMO_ATTR,
            (key, True, ((1.0, "NOPE"), (2.0, "NOPE"), (3.0, "NOPE"))),
        )
        first_calls["n"] = 0
        second_calls["n"] = 0
        assert _apply_target_bottom_ticks(first, view, 10, owner) is True
        assert first_calls["n"] == 0
        assert _pinned_bottom_ticks(first) == (
            (1.0, "NOPE"), (2.0, "NOPE"), (3.0, "NOPE"),
        )
        assert _apply_target_bottom_ticks(second, view, 10, owner) is True
        assert second_calls["n"] == 0
        assert _pinned_bottom_ticks(second) == _reference_bottom_ticks(
            (0.0, 7.162, 505.0, 10, "default")
        )

        owner.visible = False
        styled = {"n": 0}
        original_set_ticks = first.setTicks

        def spy_set_ticks(ticks):
            styled["n"] += 1
            return original_set_ticks(ticks)

        first.setTicks = spy_set_ticks
        first_calls["n"] = 0
        assert _apply_target_bottom_ticks(first, view, 10, owner) is False
        assert first_calls["n"] == 0
        assert styled["n"] == 0

        # Range moved while hidden. Showing again must fit the new range.
        view.hi = 20.0
        owner.visible = True
        first_calls["n"] = 0
        assert _apply_target_bottom_ticks(first, view, 10, owner) is True
        assert first_calls["n"] > 0
        values = [value for value, _text in _pinned_bottom_ticks(first)]
        assert min(values) >= 0.0
        assert max(values) <= 20.0
    finally:
        first.deleteLater()
        second.deleteLater()
