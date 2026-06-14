"""Expected-value tests for `FFTAnalyzer.compute_fft` amplitude normalization.

The implementation under test (now at ``mf4_analyzer/signal/fft.py``) does:

    amp = 2 * np.abs(fft_r[:nh]) / n / np.mean(w)

The claim is that dividing by ``np.mean(w)`` restores amplitude lost to the
window taper so that a pure sinusoid of true amplitude ``A`` shows up with
recovered peak amplitude ~= ``A`` in the one-sided spectrum.

These tests feed known pure tones (with a bin-aligned frequency so coherent
gain is exact and no scalloping loss applies) through ``compute_fft`` with
various windows and confirm the recovered peak is within 1% of the true
amplitude.

We import ``FFTAnalyzer`` directly from ``mf4_analyzer.signal.fft``. The
signal subpackage is, by design, free of PyQt5 / matplotlib / asammdf
dependencies (enforced by the companion guard test
``test_signal_no_gui_import.py``), so this direct import keeps the unit
test isolated from the UI stack.
"""

from __future__ import annotations

import unittest
import warnings

import numpy as np

from mf4_analyzer.signal.fft import FFTAnalyzer, get_analysis_window


class FFTAmplitudeNormalizationTests(unittest.TestCase):
    """Peak amplitude of a pure tone should equal the true amplitude.

    We use a bin-aligned frequency (integer number of cycles over the record)
    so the tone falls exactly on an FFT bin — this eliminates scalloping
    loss and makes the recovered amplitude exact to within numerical noise
    plus window spectral leakage sidelobe bleed into the peak bin (which is
    tiny for smooth windows at bin center).
    """

    @staticmethod
    def _make_tone(amplitude: float, freq_hz: float, fs: float, n: int) -> np.ndarray:
        t = np.arange(n) / fs
        return amplitude * np.sin(2 * np.pi * freq_hz * t)

    def _assert_peak_matches(self, amplitude: float, window: str, tol: float = 0.01) -> None:
        fs = 1000.0
        n = 4096
        # Bin-align: freq = k * fs / n for integer k. Pick k=200 -> 48.828125 Hz
        # well away from DC, Nyquist, and any nonlinearity artefacts.
        k = 200
        freq_hz = k * fs / n
        sig = self._make_tone(amplitude, freq_hz, fs, n)

        f, amp = FFTAnalyzer.compute_fft(sig, fs, win=window)

        # Peak bin should sit at index k (one-sided spectrum).
        peak_idx = int(np.argmax(amp))
        self.assertEqual(
            peak_idx,
            k,
            msg=(
                f"[window={window}] peak bin {peak_idx} != expected {k}; "
                f"peak freq={f[peak_idx]:.4f} Hz vs true {freq_hz:.4f} Hz"
            ),
        )

        recovered = amp[peak_idx]
        rel_err = abs(recovered - amplitude) / amplitude
        self.assertLess(
            rel_err,
            tol,
            msg=(
                f"[window={window}] recovered peak={recovered:.6f} vs true "
                f"A={amplitude:.6f} (rel_err={rel_err:.4%}, tol={tol:.2%})"
            ),
        )

    def test_hanning_recovers_unit_amplitude_within_1pct(self):
        self._assert_peak_matches(amplitude=1.0, window="hanning", tol=0.01)

    def test_hanning_recovers_scaled_amplitude_within_1pct(self):
        # Non-unit amplitude — verifies linearity of the scaling.
        self._assert_peak_matches(amplitude=3.7, window="hanning", tol=0.01)

    def test_hamming_recovers_unit_amplitude_within_1pct(self):
        self._assert_peak_matches(amplitude=1.0, window="hamming", tol=0.01)

    def test_blackman_recovers_unit_amplitude_within_1pct(self):
        self._assert_peak_matches(amplitude=1.0, window="blackman", tol=0.01)

    def test_dc_offset_is_removed_and_does_not_bias_peak(self):
        """A large DC offset must not change the recovered AC peak amplitude.

        `compute_fft` subtracts the mean before windowing, so a DC offset
        should be invisible in the one-sided spectrum at the tone bin.
        """
        fs = 1000.0
        n = 4096
        k = 200
        freq_hz = k * fs / n
        amplitude = 1.0
        dc = 50.0
        sig = dc + self._make_tone(amplitude, freq_hz, fs, n)

        f, amp = FFTAnalyzer.compute_fft(sig, fs, win="hanning")

        peak_idx = int(np.argmax(amp))
        self.assertEqual(peak_idx, k)
        rel_err = abs(amp[peak_idx] - amplitude) / amplitude
        self.assertLess(
            rel_err,
            0.01,
            msg=f"DC offset leaked into peak: recovered={amp[peak_idx]:.6f}",
        )

    def test_zero_padding_does_not_change_peak_amplitude(self):
        """When `nfft > n`, the normalization still divides by `n` and
        `np.mean(w)` (window of length n). Verify the peak amplitude at the
        (possibly interpolated) tone bin is still within 1% of true A.
        """
        fs = 1000.0
        n = 2048
        # Choose tone frequency aligned with the ORIGINAL record length n
        # (bin-aligned in the pre-padded sense). The padded FFT will still
        # have a bin at exactly this frequency when nfft is a multiple of n.
        k = 100
        freq_hz = k * fs / n
        amplitude = 1.0
        sig = self._make_tone(amplitude, freq_hz, fs, n)

        nfft = 4 * n  # zero-pad to 4x
        f, amp = FFTAnalyzer.compute_fft(sig, fs, win="hanning", nfft=nfft)

        # Frequency resolution is now fs/nfft; the tone should land at
        # bin k * (nfft/n) = 4k in the padded spectrum.
        expected_bin = k * (nfft // n)
        peak_idx = int(np.argmax(amp))
        self.assertEqual(
            peak_idx,
            expected_bin,
            msg=f"peak bin {peak_idx} != expected {expected_bin} after zero-padding",
        )
        rel_err = abs(amp[peak_idx] - amplitude) / amplitude
        self.assertLess(
            rel_err,
            0.01,
            msg=(
                f"Zero-padded peak={amp[peak_idx]:.6f} vs true A={amplitude:.6f} "
                f"(rel_err={rel_err:.4%})"
            ),
        )


class WelchShortSignalTests(unittest.TestCase):
    """``compute_averaged_fft`` (Welch / 线性平均) must produce a real
    spectrum when the signal is shorter than ``nfft``.

    Regression for the bug where ``n < nfft`` made ``compute_averaged_fft``
    return an all-zero amplitude curve (a flat line glued to 0): the loop
    body's ``if end > n: break`` fired before any segment was accumulated,
    so ``psd_sum`` stayed all zeros and ``amp = sqrt(0)``.

    Per docs/lessons-learned/signal-processing/2026-05-19-branch-reached-is-not-behavior-correct.md
    these tests do NOT settle for an "amp is not all zero" branch check.
    They drive a known single tone and assert the recovered spectrum has
    its peak at the expected bin and the peak amplitude matches an
    independently computed single-frame Welch reference (and the closed-form
    RMS amplitude ``A / sqrt(2)``) to tolerance, plus the freq/amp arrays are
    self-consistent at length ``effective_nfft // 2`` where
    ``effective_nfft = min(nfft, n)``.
    """

    @staticmethod
    def _welch_single_frame_reference(sig, fs, win, eff):
        """Single-segment Welch amplitude over the whole (length-``eff``)
        signal, computed independently of the implementation under test.

        Mirrors ``compute_averaged_fft``'s own math (mean-removed segment,
        windowed full FFT, one-sided ``[:eff//2]`` slice, PSD ``* 2`` /
        ``w_sum**2``, ``amp = sqrt(psd)``) for a single n_segments==1 frame,
        which is exactly what the clamped (effective_nfft == n) path reduces
        to. This is the equivalent single-frame reference the spectrum must
        match.
        """
        w = get_analysis_window(win, eff)
        w_sum = np.sum(w)
        seg = sig[:eff] - np.mean(sig[:eff])
        fft_r = np.fft.fft(seg * w)
        psd = np.abs(fft_r[:eff // 2]) ** 2 / 1 / (w_sum ** 2) * 2.0
        return np.sqrt(psd)

    def _assert_short_signal_spectrum(self, n, nfft=1024, amplitude=2.0, win="hanning"):
        fs = 1000.0
        eff = min(nfft, n)  # effective_nfft == n in the short-signal regime
        # Bin-align the tone to the EFFECTIVE length so the peak sits on an
        # exact bin (no scalloping); k chosen well away from DC/Nyquist.
        k = 40
        freq_hz = k * fs / eff
        t = np.arange(n) / fs
        sig = amplitude * np.sin(2 * np.pi * freq_hz * t)

        with self.assertWarnsRegex(UserWarning, "frequency resolution"):
            freq, amp, psd = FFTAnalyzer.compute_averaged_fft(
                sig, fs, win=win, nfft=nfft, overlap=0.5,
            )

        # (1) Self-consistent, correct length: clamped to effective_nfft.
        expected_len = eff // 2
        self.assertEqual(
            len(freq), expected_len,
            msg=f"[n={n}] len(freq)={len(freq)} != effective_nfft//2={expected_len}",
        )
        self.assertEqual(
            len(amp), expected_len,
            msg=f"[n={n}] len(amp)={len(amp)} != effective_nfft//2={expected_len}",
        )

        # (2) Peak sits at the expected bin (not a flat zero line).
        peak_idx = int(np.argmax(amp))
        self.assertEqual(
            peak_idx, k,
            msg=(
                f"[n={n}] peak bin {peak_idx} != expected {k}; "
                f"amp.max()={amp.max():.6e} amp.sum()={amp.sum():.6e}"
            ),
        )

        # (3) Peak amplitude matches the independent single-frame Welch
        #     reference AND the closed-form RMS amplitude A/sqrt(2).
        ref = self._welch_single_frame_reference(sig, fs, win, eff)
        np.testing.assert_allclose(
            amp, ref, rtol=1e-9, atol=1e-9,
            err_msg=f"[n={n}] amp does not match single-frame Welch reference",
        )
        rms = amplitude / np.sqrt(2.0)
        rel_err = abs(amp[peak_idx] - rms) / rms
        self.assertLess(
            rel_err, 0.01,
            msg=(
                f"[n={n}] recovered RMS peak={amp[peak_idx]:.6f} vs expected "
                f"A/sqrt(2)={rms:.6f} (rel_err={rel_err:.4%})"
            ),
        )

        # psd is the squared amplitude convention returned alongside.
        np.testing.assert_allclose(
            amp, np.sqrt(psd), rtol=1e-9, atol=1e-12,
            err_msg=f"[n={n}] amp != sqrt(psd)",
        )

    def test_n_500_shorter_than_nfft_1024(self):
        self._assert_short_signal_spectrum(n=500, nfft=1024)

    def test_n_1000_shorter_than_nfft_1024(self):
        self._assert_short_signal_spectrum(n=1000, nfft=1024)

    def test_tiny_signal_returns_finite_zero_spectrum(self):
        """n in {0,1,2,3} must yield finite zero arrays, never NaN."""
        fs = 100.0
        for n in (0, 1, 2, 3):
            sig = np.ones(n)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                freq, amp, psd = FFTAnalyzer.compute_averaged_fft(
                    sig, fs, win="hanning", nfft=1024, overlap=0.5,
                )
            self.assertTrue(np.all(np.isfinite(amp)), f"n={n}: non-finite amp")
            self.assertTrue(np.all(np.isfinite(psd)), f"n={n}: non-finite psd")
            self.assertEqual(amp.shape, freq.shape)
            self.assertEqual(psd.shape, freq.shape)
            self.assertTrue(np.all(amp == 0.0), f"n={n}: expected zero amp")
            self.assertTrue(np.all(psd == 0.0), f"n={n}: expected zero psd")

    def test_short_signal_warns_about_resolution_clamp(self):
        fs = 1000.0
        sig = np.ones(500)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            FFTAnalyzer.compute_averaged_fft(sig, fs, win="hanning", nfft=1024)

        self.assertTrue(
            any(issubclass(w.category, UserWarning) for w in caught),
            "expected a UserWarning for Welch resolution clamp",
        )


if __name__ == "__main__":
    unittest.main()
