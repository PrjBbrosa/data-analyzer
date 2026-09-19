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


def _butterworth_lowpass_gain(freq_hz, cutoff_hz, order):
    """Analytic |H(f)| for an analog Butterworth low-pass (not the FFT mask)."""
    ratio = float(freq_hz) / float(cutoff_hz)
    return 1.0 / np.sqrt(1.0 + ratio ** (2 * int(order)))


def _rms(values):
    arr = np.asarray(values, dtype=float)
    return float(np.sqrt(np.mean(np.square(arr))))


def _trim_reflection_pad_transient(values):
    """Drop the edge region that zero-phase FFT filtering cannot make exact.

    ``apply`` odd-reflects about ``pad = min(n-1, max(16, n//10))`` samples so
    circular convolution does not wrap the record onto itself, then trims back
    to the original length. The interior after a matching 10% (floor 16)
    discard is the steady-state region where a long sinusoid should match
    analytic |H(f)|. Residual error is spectral leakage on the padded FFT
    length (the sine is integer-period on the unpadded record, not on the
    padded one) plus leftover pad transients — not an extra tolerance knob.
    """
    n = int(np.asarray(values).size)
    trim = min(n - 1, max(16, n // 10))
    return np.asarray(values, dtype=float)[trim:n - trim]


def _sine(fs, freq_hz, duration_s=0.5):
    t = np.arange(0, duration_s, 1.0 / fs)
    return np.sin(2.0 * np.pi * freq_hz * t)


def _measured_gain(apply_fn, spec, fs, freq_hz):
    x = _sine(fs, freq_hz)
    y = apply_fn(x, spec, fs)
    x_mid = _trim_reflection_pad_transient(x)
    y_mid = _trim_reflection_pad_transient(y)
    return _rms(y_mid) / _rms(x_mid)


def _assert_multirate_channel_fs(apply_fn):
    """Passband, cutoff, and stopband oracles at two real channel rates.

    Physical cutoff is 1 kHz. Both rates keep Nyquist above a 2 kHz stopband
    tone (Nyquist(5400 Hz) = 2700 Hz), so the same physical frequencies are
    valid at both fs. A hardcoded fs scales every DFT bin by fs_used/fs_true
    and cannot satisfy cutoff + stopband at both rates. Returning the raw
    input satisfies the 100 Hz passband but fails cutoff/stopband gain.
    """
    spec = FilterSpec('low', order=4, cutoff=1000.0)
    passband_hz = 100.0
    cutoff_hz = 1000.0
    stopband_hz = 2000.0
    # 5% relative covers padded-FFT leakage after 10% edge trim and is well
    # below the 29% gap between |H(fc)| = 1/sqrt(2) and an unfiltered sine.
    # Stopband uses an absolute floor so a tiny expected gain does not inflate
    # relative error; unfiltered gain is ~1 vs |H(2 kHz)| ≈ 0.062.
    rel = 0.05
    stop_abs = 0.02
    for fs in (5400.0, 129500.0):
        x_pass = _sine(fs, passband_hz)
        y_pass = apply_fn(x_pass, spec, fs)
        assert np.std(y_pass) > 0.6, f"100 Hz passband lost at fs={fs}"

        pass_gain = _measured_gain(apply_fn, spec, fs, passband_hz)
        cut_gain = _measured_gain(apply_fn, spec, fs, cutoff_hz)
        stop_gain = _measured_gain(apply_fn, spec, fs, stopband_hz)
        assert pass_gain == pytest.approx(
            _butterworth_lowpass_gain(passband_hz, spec.cutoff, spec.order),
            rel=rel,
        ), f"passband gain {pass_gain} at fs={fs}"
        assert cut_gain == pytest.approx(
            _butterworth_lowpass_gain(cutoff_hz, spec.cutoff, spec.order),
            rel=rel,
        ), f"cutoff gain {cut_gain} at fs={fs}"
        assert stop_gain == pytest.approx(
            _butterworth_lowpass_gain(stopband_hz, spec.cutoff, spec.order),
            rel=rel,
            abs=stop_abs,
        ), f"stopband gain {stop_gain} at fs={fs}"


def test_multirate_uses_channel_fs():
    _assert_multirate_channel_fs(apply)


def test_multirate_catches_hardcoded_fs_injection():
    def apply_hardcoded_fs(sig, spec, fs):
        del fs
        return apply(sig, spec, 5400.0)

    with pytest.raises(AssertionError):
        _assert_multirate_channel_fs(apply_hardcoded_fs)


def test_multirate_catches_unfiltered_passthrough_injection():
    def apply_unfiltered(sig, spec, fs):
        del spec, fs
        return np.asarray(sig, dtype=float).copy()

    with pytest.raises(AssertionError):
        _assert_multirate_channel_fs(apply_unfiltered)


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
