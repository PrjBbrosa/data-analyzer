import numpy as np
from mf4_analyzer.signal.order_cot import COTOrderAnalyzer, COTParams


def _synth_constant_rpm_with_2nd_order(fs=1000.0, dur=10.0, rpm_const=600.0,
                                        order_amp=1.0, noise=0.05):
    """Build a signal with constant RPM and a pure 2nd-order ripple."""
    rng = np.random.default_rng(0)
    t = np.arange(int(fs * dur)) / fs
    rpm = np.full_like(t, rpm_const)
    fpo = rpm_const / 60.0
    f_order2 = 2 * fpo  # 20Hz at 600RPM
    sig = order_amp * np.sin(2 * np.pi * f_order2 * t) + noise * rng.standard_normal(len(t))
    return t, sig, rpm


def test_cot_constant_rpm_resolves_order_2_cleanly():
    t, sig, rpm = _synth_constant_rpm_with_2nd_order()
    p = COTParams(samples_per_rev=256, nfft=1024, max_order=10.0,
                  order_res=0.05, time_res=0.5)
    res = COTOrderAnalyzer.compute(sig, rpm, t, p)

    # Find order 2 column
    o2_idx = int(np.argmin(np.abs(res.orders - 2.0)))
    o2_col = res.amplitude[:, o2_idx]
    o15_col = res.amplitude[:, int(np.argmin(np.abs(res.orders - 1.5)))]
    o25_col = res.amplitude[:, int(np.argmin(np.abs(res.orders - 2.5)))]

    # Order 2 should be at least 10x larger than neighbors at order 1.5 / 2.5
    assert o2_col.mean() > 10 * o15_col.mean(), \
        f"COT failed to isolate order 2: o2={o2_col.mean():.4f} o15={o15_col.mean():.4f}"
    assert o2_col.mean() > 10 * o25_col.mean()


def _synth_swept_rpm_with_2nd_order(fs=1000.0, dur=10.0, rpm_lo=300.0, rpm_hi=900.0,
                                     order_amp=1.0, noise=0.05):
    """Linearly sweeping RPM with a true 2nd-order ripple riding on top."""
    rng = np.random.default_rng(0)
    t = np.arange(int(fs * dur)) / fs
    rpm = rpm_lo + (rpm_hi - rpm_lo) * (t / dur)
    omega = 2 * np.pi * rpm / 60.0  # rad/s instantaneous shaft frequency
    # 2nd order means phase = 2 * cumtrapz(omega)
    phase2 = 2 * np.concatenate([[0.0], np.cumsum(omega[:-1]) * (t[1] - t[0])])
    sig = order_amp * np.sin(phase2) + noise * rng.standard_normal(len(t))
    return t, sig, rpm


def test_cot_swept_rpm_still_isolates_order_2():
    t, sig, rpm = _synth_swept_rpm_with_2nd_order()
    p = COTParams(samples_per_rev=256, nfft=1024, max_order=10.0,
                  order_res=0.05, time_res=0.5)
    res = COTOrderAnalyzer.compute(sig, rpm, t, p)

    o2_idx = int(np.argmin(np.abs(res.orders - 2.0)))
    o2_col = res.amplitude[:, o2_idx]
    # Order 2 should still dominate after sweep (the whole point of COT)
    assert o2_col.mean() > 0.3, \
        f"Sweep COT failed: order 2 mean={o2_col.mean():.4f}"
    # And dominate over neighbors
    o15 = res.amplitude[:, int(np.argmin(np.abs(res.orders - 1.5)))].mean()
    assert o2_col.mean() > 5 * o15


def test_cot_returns_orders_starting_at_order_res():
    t, sig, rpm = _synth_constant_rpm_with_2nd_order()
    p = COTParams(samples_per_rev=256, nfft=1024, max_order=8.0,
                  order_res=0.1, time_res=0.5)
    res = COTOrderAnalyzer.compute(sig, rpm, t, p)
    assert np.isclose(res.orders[0], 0.1)
    assert res.orders[-1] <= 8.0


def test_cot_handles_zero_rpm_segment():
    """Signal with a 1-second flat-zero RPM segment should not crash and
    should not produce NaN amplitudes."""
    t, sig, rpm = _synth_constant_rpm_with_2nd_order(dur=5.0)
    rpm[1000:2000] = 0.0  # 1 second of zero RPM
    p = COTParams(samples_per_rev=256, nfft=512, max_order=10.0,
                  order_res=0.1, time_res=0.5, min_rpm_floor=10.0)
    res = COTOrderAnalyzer.compute(sig, rpm, t, p)
    assert np.all(np.isfinite(res.amplitude))


def test_cot_params_validation():
    import pytest
    with pytest.raises(ValueError):
        COTParams(samples_per_rev=0, nfft=1024, max_order=10.0,
                  order_res=0.1, time_res=0.5)
    with pytest.raises(ValueError):
        COTParams(samples_per_rev=256, nfft=0, max_order=10.0,
                  order_res=0.1, time_res=0.5)
