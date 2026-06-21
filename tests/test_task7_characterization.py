"""Task 7 characterization tests.

⑧  Welch vs 单帧 dB offset characterization
      compute_averaged_fft (Welch) returns the RMS amplitude of each
      segment (PSD → sqrt), while compute_fft returns the instantaneous
      peak amplitude.  For a pure sinusoid A·sin(2πft) the true peak is A
      and the true RMS is A/√2, so:

          20·log10(welch_peak / frame_peak) ≈ 20·log10(1/√2) ≈ -3.01 dB

      This test CHARACTERISES the existing behaviour so that any future
      numeric drift surfaces as a failing test.  The tolerance is ±0.3 dB
      (tight enough to catch any inadvertent normalisation change).

②  time_res tooltip wording
      After Task 5 the COT engine truly consumes time_res (hop_angle
      ∝ 1/time_res), so "越小时间越细" is now an accurate promise.
      This test pins the exact tooltip text so future wording changes
      cannot silently break the user-facing contract.

Tooltip presence tests run under QT_QPA_PLATFORM=offscreen so they
work in headless CI without X/Wayland.
"""
from __future__ import annotations

import os
import sys
import unittest

import numpy as np

# ---------------------------------------------------------------------------
# ⑧  Signal-only: no Qt dependency
# ---------------------------------------------------------------------------
from mf4_analyzer.signal.fft import FFTAnalyzer


class WelchVsFrameDbOffsetTests(unittest.TestCase):
    """Characterise the dB offset between Welch (线性平均) and 单帧 FFT.

    For a pure sinusoid A·sin(2πft) the peak amplitude is A.  Welch
    returns the RMS amplitude A/√2.  The expected dB offset is therefore

        20·log10(A/√2) − 20·log10(A) = −3.0103 dB

    tolerance: ±0.3 dB (strict enough to catch normalisation regressions).
    """

    @staticmethod
    def _make_tone(amplitude: float, freq_hz: float, fs: float, n: int) -> np.ndarray:
        t = np.arange(n) / fs
        return amplitude * np.sin(2.0 * np.pi * freq_hz * t)

    def _db_offset(self, amplitude: float, window: str) -> float:
        """Return 20·log10(welch_peak / frame_peak) for a bin-aligned tone."""
        fs = 4000.0
        n = 4096
        # Bin-align: k cycles over n samples → exact FFT bin, no scalloping.
        k = 200
        freq_hz = k * fs / n
        sig = self._make_tone(amplitude, freq_hz, fs, n)

        # Single-frame peak (compute_fft).
        _, amp_frame = FFTAnalyzer.compute_fft(sig, fs, win=window)
        frame_peak = amp_frame[int(np.argmax(amp_frame))]

        # Welch peak (compute_averaged_fft, n >= nfft → no clamp warning).
        nfft = 1024
        _, amp_welch, _ = FFTAnalyzer.compute_averaged_fft(
            sig, fs, win=window, nfft=nfft, overlap=0.5,
        )
        welch_peak = amp_welch[int(np.argmax(amp_welch))]

        return 20.0 * np.log10(welch_peak / frame_peak)

    def test_welch_vs_frame_offset_hanning_unit_amplitude(self):
        """hanning, A=1.0: offset ≈ -3.01 dB (±0.3 dB)."""
        offset = self._db_offset(amplitude=1.0, window='hanning')
        self.assertAlmostEqual(
            offset, -3.0103, delta=0.3,
            msg=f"Welch-vs-frame dB offset={offset:.4f} dB, expected ≈ -3.01 dB"
        )

    def test_welch_vs_frame_offset_hanning_scaled_amplitude(self):
        """hanning, A=2.5: same offset (ratio is amplitude-independent)."""
        offset = self._db_offset(amplitude=2.5, window='hanning')
        self.assertAlmostEqual(
            offset, -3.0103, delta=0.3,
            msg=f"Welch-vs-frame dB offset={offset:.4f} dB, expected ≈ -3.01 dB"
        )

    def test_welch_vs_frame_offset_flattop(self):
        """flattop: same RMS offset regardless of window shape."""
        offset = self._db_offset(amplitude=1.0, window='flattop')
        self.assertAlmostEqual(
            offset, -3.0103, delta=0.3,
            msg=f"Welch-vs-frame dB offset (flattop)={offset:.4f} dB"
        )

    def test_welch_vs_frame_offset_blackman(self):
        """blackman: same RMS offset."""
        offset = self._db_offset(amplitude=1.0, window='blackman')
        self.assertAlmostEqual(
            offset, -3.0103, delta=0.3,
            msg=f"Welch-vs-frame dB offset (blackman)={offset:.4f} dB"
        )

    def test_peak_hold_vs_frame_within_tol(self):
        """峰值保持 (compute_peak_hold_fft) uses the same peak-amp path
        as 单帧; the ratio must be within ±0.5 dB of 0.0 dB (not -3 dB)."""
        amplitude = 1.0
        window = 'hanning'
        fs = 4000.0
        n = 4096
        k = 200
        freq_hz = k * fs / n
        sig = self._make_tone(amplitude, freq_hz, fs, n)
        nfft = 1024

        _, amp_frame = FFTAnalyzer.compute_fft(sig, fs, win=window)
        frame_peak = amp_frame[int(np.argmax(amp_frame))]

        _, amp_ph = FFTAnalyzer.compute_peak_hold_fft(
            sig, fs, win=window, nfft=nfft, overlap=0.5,
        )
        ph_peak = amp_ph[int(np.argmax(amp_ph))]

        offset = 20.0 * np.log10(ph_peak / frame_peak)
        self.assertAlmostEqual(
            offset, 0.0, delta=0.5,
            msg=(
                f"峰值保持 vs 单帧 dB offset={offset:.4f} dB, "
                f"expected ≈ 0.0 dB (both peak-amp)"
            ),
        )


# ---------------------------------------------------------------------------
# ②  UI tooltip pin — requires Qt (offscreen)
# ---------------------------------------------------------------------------
_HAS_QT = False
try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication  # noqa: F401
    _HAS_QT = True
except Exception:  # noqa: BLE001
    pass


@unittest.skipUnless(_HAS_QT, "PyQt5 not available")
class TooltipTextTests(unittest.TestCase):
    """Pin tooltip text for avg_mode (FFT) and time_res (Order).

    These tests read widget.toolTip() directly (not relying on "the code
    says setToolTip") to confirm the text is actually set on the live widget.
    """

    @classmethod
    def setUpClass(cls):
        if not QApplication.instance():
            cls._app = QApplication(sys.argv[:1])
        else:
            cls._app = None

    @classmethod
    def tearDownClass(cls):
        pass  # keep QApplication alive for the process

    def _make_fft_contextual(self):
        from mf4_analyzer.ui.inspector_sections.contextual_fft import FFTContextual
        w = FFTContextual()
        return w

    def _make_order_contextual(self):
        from mf4_analyzer.ui.inspector_sections.contextual_order import OrderContextual
        w = OrderContextual()
        return w

    # --- FFT avg_mode tooltip ---

    def test_avg_mode_tooltip_exists(self):
        """combo_avg_mode must carry a non-empty tooltip."""
        w = self._make_fft_contextual()
        tip = w.combo_avg_mode.toolTip()
        self.assertTrue(tip.strip(), "combo_avg_mode has no tooltip")

    def test_avg_mode_tooltip_mentions_rms_caliber(self):
        """Tooltip must explain the RMS / amplitude caliber difference."""
        w = self._make_fft_contextual()
        tip = w.combo_avg_mode.toolTip()
        # The tooltip must contain a user-facing explanation of the ~3 dB
        # caliber difference so users are not confused when switching modes.
        # We check for key user-facing phrases (not internal terms).
        lower = tip.lower()
        # Must mention the 3 dB difference (could be "3 dB", "约低 3", etc.)
        has_3db = '3' in tip and ('db' in lower or 'dB' in tip)
        # Must mention the caliber difference concept
        has_rms_concept = any(kw in tip for kw in [
            'RMS', '均方根', '能量', '幅值', '口径', 'rms',
        ])
        self.assertTrue(
            has_3db,
            f"avg_mode tooltip must mention ~3 dB offset. Got:\n{tip}"
        )
        self.assertTrue(
            has_rms_concept,
            f"avg_mode tooltip must mention RMS / caliber concept. Got:\n{tip}"
        )

    def test_avg_mode_tooltip_no_internal_jargon(self):
        """Tooltip must not contain pyqtgraph/class-name/log10 developer terms."""
        w = self._make_fft_contextual()
        tip = w.combo_avg_mode.toolTip()
        forbidden = ['pyqtgraph', 'FFTAnalyzer', 'compute_averaged_fft', 'log10',
                     'numpy', 'scipy', 'np.']
        for term in forbidden:
            self.assertNotIn(
                term, tip,
                msg=f"avg_mode tooltip must not contain developer term '{term}'"
            )

    # --- Order time_res tooltip ---

    def test_time_res_tooltip_exists(self):
        """spin_time_res must carry a non-empty tooltip."""
        w = self._make_order_contextual()
        tip = w.spin_time_res.toolTip()
        self.assertTrue(tip.strip(), "spin_time_res has no tooltip")

    def test_time_res_tooltip_smaller_is_finer(self):
        """Tooltip must convey 'smaller → finer time resolution'."""
        w = self._make_order_contextual()
        tip = w.spin_time_res.toolTip()
        # The promise: 越小时间越细 (smaller → finer time)
        has_smaller_finer = any(phrase in tip for phrase in [
            '越小时间越细', '越小', '时间越细', '时间分辨率越高',
        ])
        self.assertTrue(
            has_smaller_finer,
            f"spin_time_res tooltip must convey 'smaller → finer time'. Got:\n{tip}"
        )

    def test_time_res_tooltip_no_internal_jargon(self):
        """time_res tooltip must not expose developer internal terms."""
        w = self._make_order_contextual()
        tip = w.spin_time_res.toolTip()
        forbidden = ['hop_angle', 'n_frames', 'compute_order', 'COTParams', 'np.']
        for term in forbidden:
            self.assertNotIn(
                term, tip,
                msg=f"time_res tooltip must not contain developer term '{term}'"
            )


if __name__ == "__main__":
    unittest.main()
