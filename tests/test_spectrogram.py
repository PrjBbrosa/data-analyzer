"""Algorithm tests for `mf4_analyzer.signal.spectrogram.SpectrogramAnalyzer`.

These tests are part of the FFT-vs-Time 2D spectrogram feature (see
`docs/superpowers/specs/2026-04-25-fft-vs-time-2d-design.md`). They lock
the analyzer's amplitude normalization, frame center times, time-axis
jitter rejection, the shared window helper presets (Hann + Flat Top),
and the 64 MB float32 memory ceiling.

The signal subpackage is GUI-free; these tests import the analyzer
directly and never touch PyQt5/matplotlib.
"""

from __future__ import annotations

import unittest

import numpy as np

from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer, SpectrogramParams


class SpectrogramAnalyzerTests(unittest.TestCase):
    def test_bin_aligned_tone_amplitude(self):
        fs = 1000.0
        nfft = 1024
        t = np.arange(4096) / fs
        freq_hz = 125.0  # bin-aligned: k=128 of nfft=1024 at fs=1000
        amp_true = 2.5
        sig = amp_true * np.sin(2 * np.pi * freq_hz * t)
        params = SpectrogramParams(fs=fs, nfft=nfft, window='hanning', overlap=0.5)

        result = SpectrogramAnalyzer.compute(sig, t, params, channel_name='tone', unit='V')

        peak_idx = int(np.argmax(result.amplitude[:, 0]))
        self.assertAlmostEqual(result.frequencies[peak_idx], freq_hz, places=6)
        self.assertLess(abs(result.amplitude[peak_idx, 0] - amp_true) / amp_true, 0.03)

    def test_two_tone_frequency_bins(self):
        # Two bin-aligned tones: 1.0 @ 64 Hz, 0.5 @ 192 Hz on a Hann
        # window. Hann's first sidelobe leaks ~0.5 of the dominant tone
        # into bins 63 and 65, which match the 0.5 peak at bin 192 in
        # raw magnitude. We therefore pick peaks under a minimum-bin
        # separation rule so adjacent leakage cannot crowd out the
        # genuine second tone — this mirrors how a peak-finder would
        # surface the two distinct tones.
        fs = 1024.0
        nfft = 1024
        t = np.arange(4096) / fs
        sig = 1.0 * np.sin(2 * np.pi * 64 * t) + 0.5 * np.sin(2 * np.pi * 192 * t)
        params = SpectrogramParams(fs=fs, nfft=nfft, window='hanning', overlap=0.5)

        result = SpectrogramAnalyzer.compute(sig, t, params, channel_name='two', unit='V')

        column = result.amplitude[:, 0].copy()
        # Pick the dominant peak, then mask a +/- 4-bin window around it
        # before picking the second peak. 4 bins comfortably covers
        # Hann's main + first sidelobe contribution at bin-aligned
        # input.
        peak1 = int(np.argmax(column))
        guard = 4
        column[max(0, peak1 - guard): peak1 + guard + 1] = -np.inf
        peak2 = int(np.argmax(column))
        peak_freqs = sorted([round(float(result.frequencies[peak1])),
                             round(float(result.frequencies[peak2]))])
        self.assertEqual(peak_freqs, [64, 192])

    def test_burst_time_localization(self):
        # Burst from t=2.0s to t=3.0s, fs=1000, nfft=500, hop=250.
        # Frame centers fall at t[start] + (nfft-1)/(2*fs) = t[start] + 0.2495.
        # Frames straddling the burst boundary contain ~half the burst,
        # so threshold at 25% of peak energy is a robust separator
        # between "frame fully inside burst", "frame straddling boundary",
        # and "frame entirely outside burst".
        fs = 1000.0
        nfft = 500
        t = np.arange(5000) / fs
        sig = np.zeros_like(t)
        active = (t >= 2.0) & (t < 3.0)
        sig[active] = np.sin(2 * np.pi * 80 * t[active])
        params = SpectrogramParams(fs=fs, nfft=nfft, window='hanning', overlap=0.5)

        result = SpectrogramAnalyzer.compute(sig, t, params, channel_name='burst', unit='V')

        freq_idx = int(np.argmin(np.abs(result.frequencies - 80)))
        energy = result.amplitude[freq_idx, :]
        active_frames = result.times[energy > 0.25 * np.max(energy)]
        self.assertGreaterEqual(float(active_frames.min()), 1.75)
        self.assertLessEqual(float(active_frames.max()), 3.25)

    def test_db_conversion(self):
        amp = np.array([[1.0, 10.0]])
        db = SpectrogramAnalyzer.amplitude_to_db(amp, reference=1.0)
        self.assertAlmostEqual(float(db[0, 0]), 0.0, places=6)
        self.assertAlmostEqual(float(db[0, 1]), 20.0, places=6)

    def test_frame_center_times(self):
        fs = 100.0
        nfft = 20
        t = np.arange(100) / fs
        sig = np.sin(2 * np.pi * 5 * t)
        params = SpectrogramParams(fs=fs, nfft=nfft, window='hanning', overlap=0.5)

        result = SpectrogramAnalyzer.compute(sig, t, params, channel_name='time', unit='')

        self.assertAlmostEqual(float(result.times[0]), (nfft - 1) / (2 * fs), places=9)
        self.assertAlmostEqual(float(result.times[1] - result.times[0]), 0.1, places=9)

    def test_rejects_signal_shorter_than_nfft(self):
        params = SpectrogramParams(fs=1000.0, nfft=1024, window='hanning', overlap=0.5)
        with self.assertRaisesRegex(ValueError, 'shorter than nfft'):
            SpectrogramAnalyzer.compute(np.ones(100), np.arange(100) / 1000.0, params, 'short', '')

    def test_rejects_nonuniform_time_axis(self):
        fs = 1000.0
        t = np.arange(2048) / fs
        t[1000] += 0.01
        sig = np.sin(2 * np.pi * 100 * t)
        params = SpectrogramParams(fs=fs, nfft=512, window='hanning', overlap=0.5)
        with self.assertRaisesRegex(ValueError, 'non-uniform'):
            SpectrogramAnalyzer.compute(sig, t, params, 'jitter', '')

    def test_window_preset_hann_and_flattop(self):
        # Lock both presets so a future scipy upgrade or an accidental
        # alias rewrite cannot silently change normalization.
        fs = 1000.0
        nfft = 1024
        t = np.arange(4096) / fs
        amp_true = 1.7
        # Bin-aligned: hann reaches ~1% of true amp at the bin.
        bin_aligned = 200 * fs / nfft  # 195.3125 Hz
        sig = amp_true * np.sin(2 * np.pi * bin_aligned * t)

        for win, tol in (('hanning', 0.02), ('flattop', 0.01)):
            params = SpectrogramParams(fs=fs, nfft=nfft, window=win, overlap=0.5)
            result = SpectrogramAnalyzer.compute(sig, t, params, 'tone', 'V')
            peak = float(np.max(result.amplitude[:, 0]))
            self.assertLess(abs(peak - amp_true) / amp_true, tol, msg=f'window={win}')

    def test_memory_ceiling_blocks_oversized_request(self):
        # Construct a request that would build a > 64 MB float32 matrix
        # (e.g. nfft=8192, overlap=0.99, signal length ~= 5e6 samples).
        nfft = 8192
        n = 5_000_000
        fs = 50_000.0
        params = SpectrogramParams(fs=fs, nfft=nfft, window='hanning', overlap=0.99)
        sig = np.zeros(n, dtype=float)
        t = np.arange(n) / fs
        with self.assertRaisesRegex(ValueError, 'memory ceiling'):
            SpectrogramAnalyzer.compute(sig, t, params, 'huge', '')


if __name__ == "__main__":
    unittest.main()
