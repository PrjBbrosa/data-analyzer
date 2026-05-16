import numpy as np

from mf4_analyzer.signal.fft import FFTAnalyzer


def test_fft_known_100hz_tone_peak_and_amplitude():
    fs = 1024.0
    n = 4096
    t = np.arange(n) / fs
    amplitude = 2.5
    sig = amplitude * np.sin(2 * np.pi * 100.0 * t)

    freq, amp = FFTAnalyzer.compute_fft(sig, fs, win="hanning", nfft=n)

    peak_idx = int(np.argmax(amp))
    assert abs(freq[peak_idx] - 100.0) < 1e-9
    assert abs(amp[peak_idx] - amplitude) < 0.01
