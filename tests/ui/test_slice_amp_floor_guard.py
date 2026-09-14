"""Slice range validity follows original amplitudes, never a peak cutoff.

Zero source amplitudes may be excluded using their explicit mask, while finite
nonzero deep valleys and compatible calls without masks remain visible.
"""
import numpy as np


def test_slice_amp_bounds_excludes_db_floor_outlier(qapp):
    from mf4_analyzer.ui.pg_canvas import heatmap_canvas as hc

    floor = 20.0 * np.log10(np.finfo(float).tiny)  # ≈ -6153 dB, the DC artifact
    # Real bulk -39..-60 dB plus one dead DC bin floored to ~-6153.
    vals = np.array([floor, -42.0, -55.0, -48.0, -60.0, -39.0])
    lo, hi = hc._slice_amp_bounds(vals, valid_mask=[False, True, True, True, True, True])
    assert hi == -37.95
    assert lo == -61.05


def test_slice_amp_bounds_keeps_real_low_data(qapp):
    from mf4_analyzer.ui.pg_canvas import heatmap_canvas as hc

    # Even a nonzero notch more than 200 dB below the peak must survive.
    vals = np.array([-40.0, -300.0, -50.0])
    lo, hi = hc._slice_amp_bounds(vals)
    assert lo == -313.0
    assert hi == -27.0


def test_slice_amp_bounds_is_nan_inf_safe(qapp):
    from mf4_analyzer.ui.pg_canvas import heatmap_canvas as hc

    floor = 20.0 * np.log10(np.finfo(float).tiny)
    vals = np.array([np.nan, floor, -45.0, np.inf, -55.0])
    lo, hi = hc._slice_amp_bounds(vals, valid_mask=[False, False, True, False, True])
    assert np.isfinite(lo) and np.isfinite(hi)
    assert hi == -44.5
    assert lo == -55.5


def test_slice_amp_bounds_degenerate_returns_none(qapp):
    from mf4_analyzer.ui.pg_canvas import heatmap_canvas as hc

    floor = 20.0 * np.log10(np.finfo(float).tiny)
    # Nothing but invalid source amplitudes is an explicit empty range.
    assert hc._slice_amp_bounds(np.array([floor, floor]), valid_mask=[False, False]) is None
    assert hc._slice_amp_bounds(np.array([floor, floor])) == (floor - 1, floor + 1)
    assert hc._slice_amp_bounds(np.array([])) is None


def test_time_slice_view_ignores_db_floor_dc_bin(qapp):
    """End-to-end on the real canvas path (not just the pure helper).

    A *time* slice (amplitude vs frequency) reads the whole column, so it
    includes the 0 Hz bin. With that DC bin numerically zero (A-weighting gain
    == 0 at f == 0 / de-mean), ``amplitude_to_db`` floors it to ≈ -6153 dB. The
    slice's Y *view* range must still frame the real signal — pre-fix the naive
    ``min`` dragged it down to ≈ -6460 dB (the floor + 5% pad)."""
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas
    from mf4_analyzer.signal.spectrogram import (
        SpectrogramParams, SpectrogramResult)

    freqs = np.linspace(0.0, 500.0, 64)        # freqs[0] == 0.0 (the DC bin)
    times = np.linspace(0.0, 2.0, 10)
    # Real bulk ~0.01..1.0 linear → ~-40..0 dB; DC row exactly 0 → floored.
    amp = np.random.RandomState(3).rand(64, 10).astype(np.float32) + 0.01
    amp[0, :] = 0.0
    r = SpectrogramResult(
        times=times, frequencies=freqs, amplitude=amp,
        params=SpectrogramParams(fs=1000.0, nfft=128),
        channel_name='vib', unit='g', metadata={'frames': 10},
    )
    c = PgHeatmapCanvas(with_slice=True)
    try:
        c.resize(640, 480)
        c.plot_result(r, amplitude_mode='amplitude_db', z_auto=True,
                      db_reference=1.0)
        x0, x1, y0, y1 = c._extents
        c.set_slice_direction('x')             # time slice → amplitude vs freq
        c._select_slice_at((x0 + x1) / 2.0, (y0 + y1) / 2.0)
        (_, _), (ylo, yhi) = c._slice_plot.vb.viewRange()
        assert ylo > -200.0, f"slice Y view dragged to the dB floor: {ylo}"
        assert yhi <= 5.0
    finally:
        c.deleteLater()
