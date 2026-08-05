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
import numpy as np
import pyqtgraph as pg
import pytest

from mf4_analyzer.ui.pg_canvas.analysis_axes import (
    _apply_axis_tick_density,
    _apply_neutral_axis_frame,
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
    # No finite data at all → a usable unit range rather than NaN bounds.
    assert _finite_data_bounds(np.full((2, 2), np.nan)) == (0.0, 1.0)
    assert _finite_data_bounds(np.array([])) == (0.0, 1.0)


def test_finite_data_bounds_widens_a_degenerate_range():
    # A flat matrix would give hi == lo, which is unusable as an axis range.
    assert _finite_data_bounds(np.full((2, 2), 5.0)) == (5.0, 6.0)


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
    # Delegates to _finite_data_bounds()[1] → the 1.0 of its (0.0, 1.0).
    assert _robust_db_ceiling(np.full((4, 4), np.nan)) == 1.0


def test_auto_db_window_is_a_fixed_span_below_the_robust_ceiling():
    values = np.arange(100, dtype=float)
    vmin, vmax = _auto_db_window(values)
    assert vmax == pytest.approx(_robust_db_ceiling(values, _AUTO_CEILING_PCT))
    assert vmax - vmin == pytest.approx(_AUTO_SPAN_DB)
    assert (vmin, vmax) == pytest.approx((68.01, 98.01))


def test_auto_db_window_default_span_is_30_db():
    assert _AUTO_SPAN_DB == 30.0
    assert _AUTO_CEILING_PCT == 99.0


def test_auto_db_window_on_an_all_zero_matrix():
    # Degenerate but common (a freshly zeroed buffer): ceiling 0, span below.
    assert _auto_db_window(np.zeros((8, 8))) == pytest.approx((-30.0, 0.0))


def test_auto_db_window_keeps_its_span_when_nothing_is_finite():
    vmin, vmax = _auto_db_window(np.full((4, 4), np.nan))
    assert (vmin, vmax) == pytest.approx((-29.0, 1.0))
    assert vmax - vmin == pytest.approx(_AUTO_SPAN_DB)


# --------------------------------------------------------------------------
# _slice_amp_bounds — robust Y view range for the slice curve
# --------------------------------------------------------------------------

def test_slice_amp_bounds_returns_none_without_finite_spread():
    assert _slice_amp_bounds(np.array([])) is None
    assert _slice_amp_bounds(np.full(5, np.nan)) is None
    assert _slice_amp_bounds(np.array([3.0])) is None        # single value
    assert _slice_amp_bounds(np.array([7.0, 7.0])) is None   # flat → hi <= lo


def test_slice_amp_bounds_spans_normal_data():
    assert _slice_amp_bounds(np.array([-60.0, -40.0, -50.0])) == (-60.0, -40.0)


def test_slice_amp_bounds_ignores_inf():
    assert _slice_amp_bounds(np.array([np.inf, -10.0, -20.0])) == (-20.0, -10.0)


def test_slice_amp_bounds_drops_bins_below_the_max_span():
    # The DC bin floored to ~-6153 dB must not crush the real -40..-60 band.
    floor = 20.0 * np.log10(np.finfo(float).tiny)
    assert floor < -6000.0
    assert _slice_amp_bounds(np.array([floor, -40.0, -60.0, -50.0])) == (-60.0, -40.0)


def test_slice_amp_bounds_keeps_a_bin_exactly_at_the_span_limit():
    # The cut is `>= hi - _SLICE_MAX_SPAN_DB`, so the boundary bin survives.
    assert _SLICE_MAX_SPAN_DB == 200.0
    assert _slice_amp_bounds(np.array([0.0, -200.0])) == (-200.0, 0.0)


def test_slice_amp_bounds_drops_a_bin_just_past_the_span_limit():
    assert _slice_amp_bounds(np.array([0.0, -200.0001, -30.0])) == (-30.0, 0.0)


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
