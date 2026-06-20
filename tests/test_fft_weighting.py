import numpy as np

from mf4_analyzer.signal.fft import FFTAnalyzer
from mf4_analyzer.signal.weighting import a_weighting_gain_linear


def _multi_tone_signal(fs=4096.0, n=4096):
    t = np.arange(n) / fs
    return (
        0.8 * np.sin(2 * np.pi * 50.0 * t)
        + 0.6 * np.sin(2 * np.pi * 1000.0 * t)
        + 0.4 * np.sin(2 * np.pi * 2000.0 * t)
    )


def test_compute_fft_default_matches_explicit_none_weighting():
    sig = _multi_tone_signal()

    f_default, amp_default = FFTAnalyzer.compute_fft(sig, 4096.0, nfft=4096)
    f_none, amp_none = FFTAnalyzer.compute_fft(sig, 4096.0, nfft=4096, weighting='None')

    np.testing.assert_array_equal(f_none, f_default)
    np.testing.assert_allclose(amp_none, amp_default, rtol=0.0, atol=0.0)


def test_compute_fft_applies_a_weighting_to_final_amplitude():
    sig = _multi_tone_signal()

    f_base, amp_base = FFTAnalyzer.compute_fft(sig, 4096.0, nfft=4096, weighting='None')
    f_weighted, amp_weighted = FFTAnalyzer.compute_fft(sig, 4096.0, nfft=4096, weighting='A')

    np.testing.assert_array_equal(f_weighted, f_base)
    np.testing.assert_allclose(
        amp_weighted,
        amp_base * a_weighting_gain_linear(f_base),
        rtol=1e-12,
        atol=1e-12,
    )


def test_compute_psd_matches_weighted_amplitude_squared():
    sig = _multi_tone_signal()

    f_amp, amp_weighted = FFTAnalyzer.compute_fft(sig, 4096.0, nfft=4096, weighting='A')
    f_psd, psd_weighted = FFTAnalyzer.compute_psd(sig, 4096.0, nfft=4096, weighting='A')

    np.testing.assert_array_equal(f_psd, f_amp)
    np.testing.assert_allclose(psd_weighted, amp_weighted ** 2, rtol=1e-12, atol=1e-12)


def test_compute_averaged_fft_applies_a_weighting_to_final_amp_and_psd():
    sig = _multi_tone_signal(n=8192)

    f_base, amp_base, _ = FFTAnalyzer.compute_averaged_fft(
        sig, 4096.0, nfft=1024, overlap=0.5, weighting='None',
    )
    f_weighted, amp_weighted, psd_weighted = FFTAnalyzer.compute_averaged_fft(
        sig, 4096.0, nfft=1024, overlap=0.5, weighting='A',
    )

    gain = a_weighting_gain_linear(f_base)
    np.testing.assert_array_equal(f_weighted, f_base)
    np.testing.assert_allclose(amp_weighted, amp_base * gain, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(psd_weighted, amp_weighted ** 2, rtol=1e-12, atol=1e-12)


def test_compute_peak_hold_fft_applies_a_weighting_to_final_peak():
    sig = _multi_tone_signal(n=8192)

    f_base, peak_base = FFTAnalyzer.compute_peak_hold_fft(
        sig, 4096.0, nfft=1024, overlap=0.5, weighting='None',
    )
    f_weighted, peak_weighted = FFTAnalyzer.compute_peak_hold_fft(
        sig, 4096.0, nfft=1024, overlap=0.5, weighting='A',
    )

    np.testing.assert_array_equal(f_weighted, f_base)
    np.testing.assert_allclose(
        peak_weighted,
        peak_base * a_weighting_gain_linear(f_base),
        rtol=1e-12,
        atol=1e-12,
    )
