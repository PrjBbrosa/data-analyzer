import numpy as np

from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer, SpectrogramParams
from mf4_analyzer.signal.weighting import a_weighting_gain_linear


def _spectrogram_signal(fs=2048.0, n=4096):
    t = np.arange(n) / fs
    sig = (
        1.0 * np.sin(2 * np.pi * 64.0 * t)
        + 0.5 * np.sin(2 * np.pi * 1000.0 * t)
    )
    return t, sig


def test_spectrogram_params_default_weighting_is_none():
    params = SpectrogramParams(fs=2048.0, nfft=512)

    assert params.weighting == 'None'


def test_spectrogram_applies_a_weighting_by_frequency_row_after_frames():
    t, sig = _spectrogram_signal()
    base_params = SpectrogramParams(fs=2048.0, nfft=512, window='hanning', overlap=0.5)
    weighted_params = SpectrogramParams(
        fs=2048.0,
        nfft=512,
        window='hanning',
        overlap=0.5,
        weighting='A',
    )

    base = SpectrogramAnalyzer.compute(sig, t, base_params, channel_name='tone', unit='V')
    weighted = SpectrogramAnalyzer.compute(sig, t, weighted_params, channel_name='tone', unit='V')

    np.testing.assert_array_equal(weighted.frequencies, base.frequencies)
    np.testing.assert_array_equal(weighted.times, base.times)
    np.testing.assert_allclose(
        weighted.amplitude,
        base.amplitude * a_weighting_gain_linear(base.frequencies)[:, np.newaxis],
        rtol=5e-7,
        atol=1e-12,
    )
    assert weighted.params.weighting == 'A'
