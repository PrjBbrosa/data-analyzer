"""TDD tests for Task 1: dB conversion convergence to single helper.

Test plan:
  A) Helper semantics — nail SpectrogramAnalyzer.amplitude_to_db contract.
  B) Floor divergence — tiny vs 1e-12 floor produce different minimums.
  C) Caller guard — max(ref, 1e-12) makes ref<=0 safe for callers.
  D) Parity / call-site wiring — after refactor each call site routes
     through the helper (monkeypatch spy = RED before, GREEN after).
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer


# ---------------------------------------------------------------------------
# A: Helper semantics (these pass before AND after — they nail the contract)
# ---------------------------------------------------------------------------

class HelperSemanticsTests(unittest.TestCase):
    """A) Characterise the authority helper."""

    def test_normal_amplitude_dB(self):
        """20*log10(2.0 / 1.0) == ~6.02 dB."""
        result = SpectrogramAnalyzer.amplitude_to_db(np.array([2.0]))
        self.assertAlmostEqual(float(result[0]), 20.0 * np.log10(2.0), places=10)

    def test_amplitude_with_reference(self):
        """20*log10(0.5 / 0.5) == 0 dB."""
        result = SpectrogramAnalyzer.amplitude_to_db(np.array([0.5]), reference=0.5)
        self.assertAlmostEqual(float(result[0]), 0.0, places=10)

    def test_sub_floor_amplitude_clamps_to_tiny(self):
        """Amplitude below tiny should floor to tiny, producing ~-6153 dB (not -240)."""
        tiny = np.finfo(float).tiny
        # Very small amplitude: zero-like
        result = SpectrogramAnalyzer.amplitude_to_db(np.array([0.0]))
        expected_db = 20.0 * np.log10(tiny / 1.0)  # ~-6153 dB
        self.assertAlmostEqual(float(result[0]), expected_db, places=1)
        # Must NOT be the 1e-12 floor value (~-240 dB)
        db_1e12_floor = 20.0 * np.log10(1e-12 / 1.0)  # ~-240 dB
        self.assertNotAlmostEqual(float(result[0]), db_1e12_floor, places=1)

    def test_floor_is_tiny_not_1e12(self):
        """For amplitude=1e-20 (below 1e-12 but above tiny), floor is tiny."""
        result_tiny = SpectrogramAnalyzer.amplitude_to_db(np.array([1e-20]))
        # 1e-20 < 1e-12 so a 1e-12 floor would clip it to 1e-12 giving ~-240 dB
        # but tiny floor clips to tiny (~2.2e-308) giving ~-6153 dB
        # So results must differ from the 1e-12-clipped version
        db_1e12_clip = 20.0 * np.log10(1e-12)
        self.assertLess(float(result_tiny[0]), db_1e12_clip)

    def test_ref_zero_raises(self):
        """Reference <= 0 must raise."""
        with self.assertRaises(ValueError):
            SpectrogramAnalyzer.amplitude_to_db(np.array([1.0]), reference=0.0)

    def test_ref_negative_raises(self):
        """Negative reference must raise."""
        with self.assertRaises(ValueError):
            SpectrogramAnalyzer.amplitude_to_db(np.array([1.0]), reference=-1.0)


# ---------------------------------------------------------------------------
# B: Floor divergence — semantic difference between tiny and 1e-12 floor
# ---------------------------------------------------------------------------

class FloorDivergenceTests(unittest.TestCase):
    """B) Confirm tiny != 1e-12 floor, so the convergence changes sub-floor output."""

    def test_floors_differ_by_over_5000_dB(self):
        tiny = np.finfo(float).tiny
        db_tiny = 20.0 * np.log10(tiny)  # ~-6153 dB
        db_1e12 = 20.0 * np.log10(1e-12)  # ~-240 dB
        self.assertGreater(db_1e12 - db_tiny, 5000.0)

    def test_in_range_amplitude_parity(self):
        """For amp > 1e-12, old 1e-12 clip and new tiny floor give identical results."""
        amps = np.array([1.0, 0.5, 1e-6, 1e-11, 1e-12])
        tiny = np.finfo(float).tiny
        # Old formula (1e-12 clip)
        old = 20.0 * np.log10(np.clip(amps, 1e-12, None) / 1.0)
        # New helper
        new = SpectrogramAnalyzer.amplitude_to_db(amps, reference=1.0)
        # For amp >= 1e-12 they must agree to within 1e-6 dB
        # (note: 1e-12 itself is >= 1e-12 so clip=identity, helper=clip to tiny=1e-12)
        in_range = amps >= 1e-12
        np.testing.assert_allclose(old[in_range], new[in_range], atol=1e-6)


# ---------------------------------------------------------------------------
# C: Caller guard — max(ref, 1e-12) ensures helper never sees ref<=0
# ---------------------------------------------------------------------------

class CallerGuardTests(unittest.TestCase):
    """C) With the guard, callers with ref<=0 still get finite dB."""

    def test_guard_makes_zero_ref_safe(self):
        """max(0.0, 1e-12) = 1e-12 > 0, so helper returns finite value."""
        safe_ref = max(0.0, 1e-12)
        result = SpectrogramAnalyzer.amplitude_to_db(np.array([1.0]), reference=safe_ref)
        self.assertTrue(np.isfinite(result[0]))

    def test_guard_makes_negative_ref_safe(self):
        """max(-5.0, 1e-12) = 1e-12 > 0."""
        safe_ref = max(-5.0, 1e-12)
        result = SpectrogramAnalyzer.amplitude_to_db(np.array([1.0]), reference=safe_ref)
        self.assertTrue(np.isfinite(result[0]))


# ---------------------------------------------------------------------------
# D: Parity / call-site wiring — RED before refactor, GREEN after
#
# Strategy: monkeypatch SpectrogramAnalyzer.amplitude_to_db with a spy;
# assert the spy is called when the production path runs.
# Before refactor = spy call count stays 0 → RED.
# After refactor  = spy called ≥ 1 → GREEN.
# ---------------------------------------------------------------------------

class BatchWriteImageUsesHelperTests(unittest.TestCase):
    """D1) batch._write_image dB path must route through the helper."""

    def _make_spectro(self):
        from mf4_analyzer.batch import _Spectro2D
        x = np.array([0.0, 1.0, 2.0])
        y = np.array([100.0, 200.0])
        matrix = np.array([[0.5, 0.8], [1.2, 0.3], [2.0, 1.5]])
        return _Spectro2D(x, y, matrix, 'time_s', 'frequency_hz')

    def test_batch_write_image_fft_time_db_calls_helper(self, tmp_path=None):
        """_write_image in fft_time+dB mode must call SpectrogramAnalyzer.amplitude_to_db."""
        import tempfile, os
        from mf4_analyzer.batch import BatchRunner
        from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer

        call_count = {'n': 0}
        orig = SpectrogramAnalyzer.amplitude_to_db

        def spy(amplitude, reference=1.0):
            call_count['n'] += 1
            return orig(amplitude, reference)

        spectro = self._make_spectro()
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, 'out.png')
            with patch.object(SpectrogramAnalyzer, 'amplitude_to_db', spy):
                BatchRunner._write_image(
                    ('fft_time', spectro), out,
                    params={'amplitude_mode': 'amplitude_db',
                            'db_reference': 1.0,
                            'z_auto': True},
                )
            self.assertGreater(
                call_count['n'], 0,
                "batch._write_image fft_time+dB path did not call "
                "SpectrogramAnalyzer.amplitude_to_db; still using inline formula"
            )

    def test_batch_write_image_order_time_db_calls_helper(self):
        """_write_image in order_time+dB mode must call SpectrogramAnalyzer.amplitude_to_db."""
        import tempfile, os
        from mf4_analyzer.batch import BatchRunner
        from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer

        call_count = {'n': 0}
        orig = SpectrogramAnalyzer.amplitude_to_db

        def spy(amplitude, reference=1.0):
            call_count['n'] += 1
            return orig(amplitude, reference)

        spectro = self._make_spectro()
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, 'out.png')
            with patch.object(SpectrogramAnalyzer, 'amplitude_to_db', spy):
                BatchRunner._write_image(
                    ('order_time', spectro), out,
                    params={'amplitude_mode': 'amplitude_db',
                            'db_reference': 1.0,
                            'z_auto': True},
                )
            self.assertGreater(
                call_count['n'], 0,
                "batch._write_image order_time+dB path did not call "
                "SpectrogramAnalyzer.amplitude_to_db; still using inline formula"
            )


class FFTMixinAmplitudeToDbDelegatesTests(unittest.TestCase):
    """D2) _fft_mixin._amplitude_to_db must delegate to SpectrogramAnalyzer.amplitude_to_db."""

    def test_fft_mixin_static_delegates_to_helper(self):
        """FFTMixin._amplitude_to_db must internally call SpectrogramAnalyzer.amplitude_to_db."""
        from mf4_analyzer.ui.main_window._fft_mixin import FFTMixin
        from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer

        call_count = {'n': 0}
        orig = SpectrogramAnalyzer.amplitude_to_db

        def spy(amplitude, reference=1.0):
            call_count['n'] += 1
            return orig(amplitude, reference)

        amp = np.array([1.0, 0.5, 2.0])
        with patch.object(SpectrogramAnalyzer, 'amplitude_to_db', spy):
            result = FFTMixin._amplitude_to_db(amp, 1.0)

        self.assertGreater(
            call_count['n'], 0,
            "FFTMixin._amplitude_to_db did not delegate to "
            "SpectrogramAnalyzer.amplitude_to_db; still using inline np.log10"
        )

    def test_fft_mixin_output_matches_helper_in_range(self):
        """For in-range amplitudes, _amplitude_to_db output matches helper within 1e-6 dB."""
        from mf4_analyzer.ui.main_window._fft_mixin import FFTMixin

        amp = np.array([1.0, 0.5, 1e-5])
        ref = 1.0
        old_result = FFTMixin._amplitude_to_db(amp, ref)
        expected = SpectrogramAnalyzer.amplitude_to_db(amp, reference=max(ref, 1e-12))
        np.testing.assert_allclose(old_result, expected, atol=1e-6)


class OrderMixinDbConversionTests(unittest.TestCase):
    """D3) Order mixin dB conversion parity.

    The order mixin's inline code lives inside an instance method that requires Qt,
    so we verify the mathematical transformation rather than wiring.
    We confirm that for in-range amplitudes (amp > 1e-12) the order mixin's
    old formula and the helper produce < 1e-6 dB difference.
    """

    def test_order_inline_matches_helper_for_in_range_data(self):
        """OLD: np.clip(m,1e-12,None)/ref  vs  NEW helper — must differ <1e-6 dB."""
        amps = np.array([[1.0, 0.5], [2.0, 3.0]])
        db_ref = 1.0

        # Old order mixin formula
        old = 20.0 * np.log10(np.clip(amps, 1e-12, None) / db_ref)
        # New helper formula
        new = SpectrogramAnalyzer.amplitude_to_db(amps, reference=max(db_ref, 1e-12))

        np.testing.assert_allclose(old, new, atol=1e-6,
                                   err_msg="Order mixin old formula diverges from helper "
                                           "for in-range data — refactor cannot change results")

    def test_order_db_ref_guard_behaviour(self):
        """After refactor, max(ref,1e-12) guard produces same result for valid ref."""
        amps = np.array([1.0, 0.5])
        db_ref = 2.0  # some non-default reference

        # Guarded call
        result = SpectrogramAnalyzer.amplitude_to_db(amps, reference=max(db_ref, 1e-12))
        expected = 20.0 * np.log10(amps / db_ref)
        np.testing.assert_allclose(result, expected, atol=1e-10)


if __name__ == '__main__':
    unittest.main()
