import numpy as np
import pytest
from mf4_analyzer.signal.filters import (
    FilterSpec, butter_magnitude, nyquist_guard, apply,
)


def test_lowpass_magnitude_is_3db_at_cutoff():
    f = np.array([0.0, 100.0, 1e9])
    m = butter_magnitude(f, FilterSpec('low', order=4, cutoff=100.0))
    assert m[0] == pytest.approx(1.0, abs=1e-6)          # DC passes
    assert m[1] == pytest.approx(1.0 / np.sqrt(2), abs=1e-6)  # -3 dB at fc
    assert m[2] < 1e-6                                    # far above cut → ~0


def test_highpass_is_lowpass_complement_at_cutoff():
    f = np.array([0.0, 100.0, 1e9])
    m = butter_magnitude(f, FilterSpec('high', order=4, cutoff=100.0))
    assert m[0] == pytest.approx(0.0, abs=1e-9)           # DC blocked
    assert m[1] == pytest.approx(1.0 / np.sqrt(2), abs=1e-6)
    assert m[2] == pytest.approx(1.0, abs=1e-3)


def test_lowpass_attenuates_high_keeps_low():
    fs = 2000.0
    t = np.arange(0, 2.0, 1.0 / fs)
    low = np.sin(2 * np.pi * 10 * t)
    high = np.sin(2 * np.pi * 400 * t)
    y = apply(low + high, FilterSpec('low', order=6, cutoff=50.0), fs)
    # low component preserved, high component crushed
    assert np.corrcoef(y, low)[0, 1] > 0.99
    assert np.std(y - low) < 0.15


def test_bandpass_passes_mid_rejects_out():
    fs = 4000.0
    t = np.arange(0, 2.0, 1.0 / fs)
    spec = FilterSpec('band', order=6, cutoff_lo=80.0, cutoff_hi=300.0)
    mid = apply(np.sin(2 * np.pi * 150 * t), spec, fs)
    lo = apply(np.sin(2 * np.pi * 10 * t), spec, fs)
    hi = apply(np.sin(2 * np.pi * 900 * t), spec, fs)
    assert np.std(mid) > 0.6
    assert np.std(lo) < 0.1 and np.std(hi) < 0.1


def test_bandstop_rejects_mid():
    fs = 4000.0
    t = np.arange(0, 2.0, 1.0 / fs)
    spec = FilterSpec('bandstop', order=6, cutoff_lo=80.0, cutoff_hi=300.0)
    assert np.std(apply(np.sin(2 * np.pi * 150 * t), spec, fs)) < 0.1


def test_zero_phase_no_time_shift():
    fs = 2000.0
    t = np.arange(0, 2.0, 1.0 / fs)
    x = np.sin(2 * np.pi * 5 * t)
    y = apply(x, FilterSpec('low', order=4, cutoff=50.0), fs)
    # cross-correlation peak at lag 0 → no phase shift
    xc = np.correlate(y - y.mean(), x - x.mean(), mode='same')
    assert abs(np.argmax(xc) - len(x) // 2) <= 1


def test_multirate_uses_channel_fs():
    spec = FilterSpec('low', order=4, cutoff=1000.0)
    for fs in (5400.0, 129500.0):
        t = np.arange(0, 0.5, 1.0 / fs)
        y = apply(np.sin(2 * np.pi * 100 * t), spec, fs)  # 100 Hz << 1 kHz
        assert np.std(y) > 0.6  # low tone passes at both rates


def test_nyquist_guard_clamps_and_messages():
    spec = FilterSpec('low', order=4, cutoff=9999.0)
    clamped, msg = nyquist_guard(spec, fs=1000.0)
    assert clamped.cutoff < 500.0 and msg is not None


def test_low_cutoff_on_high_fs_not_clamped_up():
    # High-fs vibration channel (e.g. 129.5 kHz accel), 50 Hz low-pass for
    # low-frequency analysis must NOT be lifted by a nyquist-proportional floor.
    spec = FilterSpec('low', cutoff=50.0)
    clamped, msg = nyquist_guard(spec, fs=129500.0)
    assert clamped.cutoff == 50.0
    assert msg is None


def test_cutoff_above_nyquist_still_clamped():
    nyq = 500.0
    spec = FilterSpec('low', order=4, cutoff=9999.0)
    clamped, msg = nyquist_guard(spec, fs=1000.0)
    assert clamped.cutoff < nyq          # below nyquist
    assert clamped.cutoff > nyq - 1.0    # only just below (high upper clamp)
    assert msg is not None


def test_band_lo_ge_hi_raises():
    with pytest.raises(ValueError):
        nyquist_guard(FilterSpec('band', cutoff_lo=300.0, cutoff_hi=100.0), fs=4000.0)


def test_nan_positions_preserved():
    fs = 1000.0
    t = np.arange(0, 1.0, 1.0 / fs)
    x = np.sin(2 * np.pi * 5 * t)
    x[100:110] = np.nan
    y = apply(x, FilterSpec('low', order=4, cutoff=50.0), fs)
    assert np.all(np.isnan(y[100:110]))
    assert np.isfinite(y[0]) and np.isfinite(y[-1])


def test_lowpass_preserves_constant_signal_exactly():
    x = np.ones(4096, dtype=float)

    y = apply(x, FilterSpec('low', order=4, cutoff=100.0), fs=1000.0)

    np.testing.assert_array_equal(y, x)


def test_highpass_rejects_constant_signal_exactly():
    x = np.ones(4096, dtype=float)

    y = apply(x, FilterSpec('high', order=4, cutoff=100.0), fs=1000.0)

    np.testing.assert_array_equal(y, np.zeros_like(x))


@pytest.mark.parametrize(
    "spec",
    [
        FilterSpec("low", order=2, cutoff=42.0),
        FilterSpec("high", order=4, cutoff=55.0),
        FilterSpec("band", order=6, cutoff_lo=12.0, cutoff_hi=345.0),
        FilterSpec("bandstop", order=8, cutoff_lo=20.0, cutoff_hi=220.0),
    ],
)
def test_filter_spec_dict_roundtrip(spec):
    assert FilterSpec.from_dict(spec.to_dict()) == spec


def test_filter_spec_from_dict_defaults_missing_fields():
    assert FilterSpec.from_dict({"kind": "low", "cutoff": 80}) == FilterSpec(
        "low", order=4, cutoff=80.0
    )
