from __future__ import annotations

import numpy as np

from mf4_analyzer.signal.order import OrderAnalyzer


def test_order_track_recovers_bin_aligned_tone_amplitude():
    fs = 2048.0
    nfft = 2048
    n = nfft * 3
    target_order = 2.0
    rpm = np.full(n, 2880.0)
    freq_per_order = rpm[0] / 60.0
    tone_freq = target_order * freq_per_order
    amplitude = 2.5
    t = np.arange(n, dtype=float) / fs
    sig = amplitude * np.sin(2 * np.pi * tone_freq * t)

    _, order_amp = OrderAnalyzer.extract_order_track(
        sig,
        rpm,
        fs,
        target=target_order,
        nfft=nfft,
    )

    assert order_amp.size > 0
    assert np.isclose(np.median(order_amp), amplitude, rtol=0.03)
