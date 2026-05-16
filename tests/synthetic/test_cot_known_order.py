import numpy as np

from mf4_analyzer.signal.order_cot import COTOrderAnalyzer, COTParams


def test_cot_known_second_order_dominates_neighbors():
    fs = 1000.0
    duration = 20.0
    t = np.arange(int(fs * duration)) / fs
    rpm = np.full_like(t, 600.0)
    shaft_hz = 600.0 / 60.0
    sig = np.sin(2 * np.pi * 2.0 * shaft_hz * t)
    params = COTParams(
        samples_per_rev=256,
        nfft=1024,
        max_order=5.0,
        order_res=0.05,
        time_res=0.1,
        fs=fs,
    )

    result = COTOrderAnalyzer.compute(sig, rpm, t, params)

    order2_idx = int(np.argmin(np.abs(result.orders - 2.0)))
    order15_idx = int(np.argmin(np.abs(result.orders - 1.5)))
    order25_idx = int(np.argmin(np.abs(result.orders - 2.5)))
    order2 = result.amplitude[:, order2_idx].mean()
    order15 = result.amplitude[:, order15_idx].mean()
    order25 = result.amplitude[:, order25_idx].mean()

    assert order2 > 5.0 * order15
    assert order2 > 5.0 * order25
