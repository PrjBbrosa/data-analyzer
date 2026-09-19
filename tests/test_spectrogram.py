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
from unittest.mock import patch

import numpy as np
import pytest

from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer, SpectrogramParams

# Product default float32 amplitude ceiling (64 MiB), asserted independently of
# the private ``_MAX_AMPLITUDE_BYTES`` name so renaming cannot hide a change.
_DEFAULT_AMPLITUDE_CEILING_BYTES = 64 * 1024 * 1024

# Retained empty/short/nonfinite/dtype/shape/time-alignment cases while the
# 5e6-sample memory fixture is replaced by a compact high-overlap request:
#   empty / 2-D / length mismatch → test_rejects_empty_mismatched_and_2d_signal
#   short (< nfft)               → test_rejects_signal_shorter_than_nfft
#   time-alignment (jitter)      → test_rejects_nonuniform_time_axis
#   dtype (float32 amplitude)    → asserted on the required-budget accept path
# Non-finite time samples remain covered by the non-uniform axis reject (NaN
# dt is not a strictly-increasing uniform axis). Precise small FRF tests live
# in tests/test_frf.py and are not rewritten here.


def _stft_hop(window_length, overlap):
    """Integer hop from overlap fraction: hop = floor(L * (1 - overlap))."""
    hop = int(int(window_length) * (1.0 - float(overlap)))
    if hop <= 0:
        raise ValueError("overlap leaves no positive hop")
    return hop


def _stft_frames_covering_end(n_samples, window_length, hop):
    """Complete STFT frames including an end-covering tail if needed.

    Regular starts are 0, hop, 2*hop, ... while start + L <= N. If the last
    sample would otherwise sit past the last regular window, one extra frame
    starts at N - L. This is the coverage contract locked by
    test_tail_frame_covers_requested_time_end, not a copy of the analyzer.
    """
    last = int(n_samples) - int(window_length)
    if last < 0 or hop <= 0:
        return 0
    n_regular = last // hop + 1
    if (n_regular - 1) * hop != last:
        return n_regular + 1
    return n_regular


def _predicted_amplitude_bytes(n_samples, nfft, overlap):
    """Independent float32 spectrogram matrix size: (nfft//2 + 1) * frames * 4."""
    hop = _stft_hop(nfft, overlap)
    frames = _stft_frames_covering_end(n_samples, nfft, hop)
    freq_bins = int(nfft) // 2 + 1
    return freq_bins * frames * 4, frames, freq_bins, hop


def _compact_default_ceiling_oversize():
    """Smallest hop-1 request whose predicted bytes exceed the 64 MiB default.

    nfft=4096, overlap so hop=1, frames = floor(ceiling / bytes_per_frame) + 1.
    Input length is ~12k samples, not 5e6.
    """
    nfft = 4096
    overlap = 1.0 - 1.0 / nfft
    freq_bins = nfft // 2 + 1
    bytes_per_frame = freq_bins * 4
    frames = _DEFAULT_AMPLITUDE_CEILING_BYTES // bytes_per_frame + 1
    n_samples = nfft + frames - 1  # hop 1, last start is on the regular grid
    predicted, derived_frames, derived_bins, hop = _predicted_amplitude_bytes(
        n_samples, nfft, overlap,
    )
    assert hop == 1
    assert derived_frames == frames
    assert derived_bins == freq_bins
    assert predicted == frames * bytes_per_frame
    assert predicted > _DEFAULT_AMPLITUDE_CEILING_BYTES
    return n_samples, nfft, overlap, predicted, frames


class _AllocationStandin:
    """Refuse large spectrogram allocations so a deleted budget guard cannot OOM."""

    def __init__(self, max_bytes=256_000):
        self.max_bytes = int(max_bytes)
        self.empty_calls = []
        self.fft_calls = 0
        self._real_empty = np.empty

    def empty(self, shape, dtype=float, *args, **kwargs):
        self.empty_calls.append((tuple(shape), np.dtype(dtype)))
        n_bytes = int(np.prod(shape)) * np.dtype(dtype).itemsize
        if n_bytes > self.max_bytes:
            raise AssertionError(
                f"stand-in blocked {n_bytes} byte allocation shape={shape}"
            )
        return self._real_empty(shape, dtype=dtype, *args, **kwargs)

    def one_sided_amplitude(self, *args, **kwargs):
        self.fft_calls += 1
        raise AssertionError("stand-in blocked one_sided_amplitude / FFT")


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

    def test_tail_frame_covers_requested_time_end(self):
        fs = 50.0
        nfft = 512
        duration = 71.02
        t = np.arange(int(duration * fs) + 1) / fs
        sig = np.sin(2 * np.pi * 3 * t)
        params = SpectrogramParams(fs=fs, nfft=nfft, window='hanning', overlap=0.8)

        result = SpectrogramAnalyzer.compute(sig, t, params, channel_name='tail', unit='')

        half_window = (nfft - 1) / (2.0 * fs)
        self.assertAlmostEqual(
            float(result.times[-1] + half_window),
            float(t[-1]),
            places=9,
        )
        self.assertAlmostEqual(float(result.metadata['coverage_start']), float(t[0]), places=9)
        self.assertAlmostEqual(float(result.metadata['coverage_end']), float(t[-1]), places=9)

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
        n_samples, nfft, overlap, predicted, _frames = _compact_default_ceiling_oversize()
        fs = 50_000.0
        params = SpectrogramParams(fs=fs, nfft=nfft, window='hanning', overlap=overlap)
        sig = np.zeros(n_samples, dtype=float)
        t = np.arange(n_samples) / fs
        standin = _AllocationStandin()
        with patch('mf4_analyzer.signal.spectrogram.np.empty', standin.empty), patch(
            'mf4_analyzer.signal.spectrogram.one_sided_amplitude',
            standin.one_sided_amplitude,
        ):
            with self.assertRaisesRegex(ValueError, 'memory ceiling'):
                SpectrogramAnalyzer.compute(sig, t, params, 'huge', '')
        self.assertGreater(predicted, _DEFAULT_AMPLITUDE_CEILING_BYTES)
        self.assertEqual(standin.empty_calls, [])
        self.assertEqual(standin.fft_calls, 0)


class SpectrogramParamsContractTests(unittest.TestCase):
    """SpectrogramParams is the single authority for the FFT-vs-Time COMPUTE
    parameter set. db_reference is a display-only dB normalisation reference —
    SpectrogramAnalyzer.compute never reads it — so it must NOT live on the
    dataclass (otherwise changing it invalidates the cache key for a recompute
    that produces a byte-identical amplitude matrix)."""

    def test_db_reference_is_not_a_field(self):
        import dataclasses
        names = {f.name for f in dataclasses.fields(SpectrogramParams)}
        self.assertNotIn('db_reference', names)

    def test_construction_rejects_db_reference_kwarg(self):
        with self.assertRaises(TypeError):
            SpectrogramParams(fs=1000.0, nfft=256, db_reference=2.0)

    def test_every_field_is_consumed_by_compute(self):
        """Each SpectrogramParams field must be an actual compute input.

        Guard against re-introducing a display-only field. The set of
        compute-relevant fields is fixed by the algorithm (fs, nfft, window,
        overlap, remove_mean, weighting); any new field added without a
        matching consumer in compute() is a contract violation.
        """
        import dataclasses
        names = {f.name for f in dataclasses.fields(SpectrogramParams)}
        self.assertEqual(
            names,
            {'fs', 'nfft', 'window', 'overlap', 'remove_mean', 'weighting'},
        )


def _small_budget_scene():
    """Tiny spectrogram whose predicted byte count is known independently.

    nfft=32, overlap=0.5 → hop=16; n=80 → last start=48 is on the grid,
    so 4 frames and no extra tail. bytes = 17 bins * 4 frames * 4 = 272.
    """
    nfft = 32
    overlap = 0.5
    n_samples = 80
    fs = 1000.0
    predicted, frames, freq_bins, hop = _predicted_amplitude_bytes(
        n_samples, nfft, overlap,
    )
    assert hop == 16
    assert frames == 4
    assert freq_bins == 17
    assert predicted == 272
    sig = np.sin(2.0 * np.pi * 5.0 * np.arange(n_samples) / fs)
    t = np.arange(n_samples) / fs
    params = SpectrogramParams(fs=fs, nfft=nfft, window='hanning', overlap=overlap)
    return sig, t, params, predicted, frames, freq_bins


@pytest.mark.parametrize(
    ("budget_delta", "should_reject"),
    [(-1, True), (0, False), (1, False)],
)
def test_memory_budget_at_required_minus_equal_plus_one(budget_delta, should_reject):
    sig, t, params, required, frames, freq_bins = _small_budget_scene()
    ceiling = required + budget_delta
    if should_reject:
        standin = _AllocationStandin()
        with patch('mf4_analyzer.signal.spectrogram.np.empty', standin.empty), patch(
            'mf4_analyzer.signal.spectrogram.one_sided_amplitude',
            standin.one_sided_amplitude,
        ):
            with pytest.raises(ValueError, match='memory ceiling'):
                SpectrogramAnalyzer.compute(
                    sig, t, params, 'budget', '', max_amplitude_bytes=ceiling,
                )
        assert standin.empty_calls == []
        assert standin.fft_calls == 0
        return

    result = SpectrogramAnalyzer.compute(
        sig, t, params, 'budget', '', max_amplitude_bytes=ceiling,
    )
    assert result.amplitude.dtype == np.float32
    assert result.amplitude.shape == (freq_bins, frames)
    assert int(result.amplitude.nbytes) == required


def test_memory_budget_ge_instead_of_gt_is_caught_at_equality():
    """Equality must be allowed. A ``>=`` ceiling would reject this same request."""
    sig, t, params, required, _frames, _bins = _small_budget_scene()
    result = SpectrogramAnalyzer.compute(
        sig, t, params, 'eq', '', max_amplitude_bytes=required,
    )
    assert int(result.amplitude.nbytes) == required

    def reject_if_ge(estimated, ceiling):
        if estimated >= int(ceiling):
            raise ValueError('memory ceiling exceeded')

    with pytest.raises(ValueError, match='memory ceiling'):
        reject_if_ge(required, required)


def test_rejects_empty_mismatched_and_2d_signal():
    params = SpectrogramParams(fs=1000.0, nfft=32, window='hanning', overlap=0.5)
    with pytest.raises(ValueError):
        SpectrogramAnalyzer.compute(np.array([]), np.array([]), params, 'empty', '')
    with pytest.raises(ValueError, match='one-dimensional'):
        SpectrogramAnalyzer.compute(
            np.ones((64, 2)), np.arange(64) / 1000.0, params, 'shape', '',
        )
    with pytest.raises(ValueError, match='same length'):
        SpectrogramAnalyzer.compute(
            np.ones(64), np.arange(63) / 1000.0, params, 'mismatch', '',
        )


if __name__ == "__main__":
    unittest.main()
