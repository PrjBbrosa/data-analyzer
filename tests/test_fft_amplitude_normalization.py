"""Expected-value tests for `FFTAnalyzer.compute_fft` amplitude normalization.

The implementation under test (at ``MF4 Data Analyzer V1.py`` line 247) does:

    amp = 2 * np.abs(fft_r[:nh]) / n / np.mean(w)

The claim is that dividing by ``np.mean(w)`` restores amplitude lost to the
window taper so that a pure sinusoid of true amplitude ``A`` shows up with
recovered peak amplitude ~= ``A`` in the one-sided spectrum.

These tests feed known pure tones (with a bin-aligned frequency so coherent
gain is exact and no scalloping loss applies) through ``compute_fft`` with
various windows and confirm the recovered peak is within 1% of the true
amplitude.

The test does NOT import the main module at module scope, because that file
imports PyQt5 / matplotlib Qt5Agg / asammdf / mdfreader. To keep this unit
test isolated from the UI stack, we extract the ``FFTAnalyzer`` class body
from the source file via ``ast`` and ``exec`` it in a minimal namespace that
only exposes ``numpy``. This preserves the exact source code under test.
"""

from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_FILE = REPO_ROOT / "MF4 Data Analyzer V1.py"


def _load_fft_analyzer():
    """Return the `FFTAnalyzer` class from the main source file.

    We parse the source with `ast`, find the `FFTAnalyzer` ClassDef node,
    unparse it, and exec it in a namespace containing only `numpy as np`.
    This avoids importing PyQt5 / matplotlib / asammdf at test time.
    """
    source = MAIN_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    class_node = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "FFTAnalyzer":
            class_node = node
            break
    if class_node is None:
        raise RuntimeError("FFTAnalyzer class not found in main source file")
    class_src = ast.unparse(class_node)
    namespace: dict = {"np": np}
    exec(class_src, namespace)
    return namespace["FFTAnalyzer"]


FFTAnalyzer = _load_fft_analyzer()


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


if __name__ == "__main__":
    unittest.main()
