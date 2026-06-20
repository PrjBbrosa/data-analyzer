import numpy as np

from mf4_analyzer.signal.order_cot import COTOrderAnalyzer, COTParams
from mf4_analyzer.signal.weighting import a_weighting_gain_linear


def _constant_rpm_order_signal(fs=1000.0, dur=10.0, rpm_const=600.0):
    t = np.arange(int(fs * dur)) / fs
    rpm = np.full_like(t, rpm_const)
    shaft_hz = rpm_const / 60.0
    sig = (
        1.0 * np.sin(2 * np.pi * 2.0 * shaft_hz * t)
        + 0.4 * np.sin(2 * np.pi * 5.0 * shaft_hz * t)
    )
    return t, sig, rpm


def test_cot_params_default_weighting_is_none():
    params = COTParams()

    assert params.weighting == 'None'


def test_cot_applies_a_weighting_using_order_frequency_per_frame():
    rpm_const = 600.0
    t, sig, rpm = _constant_rpm_order_signal(rpm_const=rpm_const)
    base_params = COTParams(
        samples_per_rev=256,
        nfft=1024,
        max_order=8.0,
        order_res=0.25,
        time_res=0.5,
        min_rpm_floor=10.0,
    )
    weighted_params = COTParams(
        samples_per_rev=256,
        nfft=1024,
        max_order=8.0,
        order_res=0.25,
        time_res=0.5,
        min_rpm_floor=10.0,
        weighting='A',
    )

    base = COTOrderAnalyzer.compute(sig, rpm, t, base_params)
    weighted = COTOrderAnalyzer.compute(sig, rpm, t, weighted_params)

    gain = a_weighting_gain_linear(base.orders * rpm_const / 60.0)
    np.testing.assert_array_equal(weighted.orders, base.orders)
    np.testing.assert_array_equal(weighted.times, base.times)
    np.testing.assert_allclose(
        weighted.amplitude,
        base.amplitude * gain[np.newaxis, :],
        rtol=1e-12,
        atol=1e-12,
    )
    assert weighted.params.weighting == 'A'
