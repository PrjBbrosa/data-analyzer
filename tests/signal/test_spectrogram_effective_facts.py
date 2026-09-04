"""Effective-facts DTO for spectrogram: shortened auto NFFT and empty input."""
from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.signal.fft import unconstrained_window_nfft
from mf4_analyzer.signal.spectrogram import (
    SpectrogramAnalyzer,
    SpectrogramParams,
    spectrogram_facts_from_result,
)


def _tone(n, fs, freq=40.0):
    t = np.arange(n, dtype=float) / fs
    return t, np.sin(2 * np.pi * freq * t)


def test_auto_nfft_shorter_than_unconstrained_window_is_shortened():
    fs = 1000.0
    n = 200
    t, sig = _tone(n, fs)
    t_win_s = 1.5
    requested = unconstrained_window_nfft(fs, t_win_s)
    assert requested is not None and requested > 64
    params = SpectrogramParams(fs=fs, nfft=64, window="hanning", overlap=0.5)
    result = SpectrogramAnalyzer.compute(sig, t, params, channel_name="sig")
    facts = spectrogram_facts_from_result(
        result, nfft_requested=requested, n_samples=n,
    )
    assert facts is not None
    assert facts.shortened is True
    assert facts.nfft == 64
    assert facts.nfft < requested
    assert facts.fs == pytest.approx(fs)
    assert facts.df == pytest.approx(fs / 64)
    assert facts.frames == result.metadata["frames"]
    assert facts.window_s == pytest.approx(64 / fs)


def test_fixed_nfft_matching_compute_is_not_shortened():
    fs = 1000.0
    n = 1024
    t, sig = _tone(n, fs)
    params = SpectrogramParams(fs=fs, nfft=256, window="hanning", overlap=0.5)
    result = SpectrogramAnalyzer.compute(sig, t, params, channel_name="sig")
    facts = spectrogram_facts_from_result(
        result, nfft_requested=256, n_samples=n,
    )
    assert facts is not None
    assert facts.shortened is False
    assert facts.nfft == 256
    assert facts.n_samples == n


def test_empty_or_missing_result_returns_no_facts():
    fs = 1000.0
    t, sig = _tone(256, fs)
    params = SpectrogramParams(fs=fs, nfft=64, window="hanning", overlap=0.5)
    result = SpectrogramAnalyzer.compute(sig, t, params, channel_name="sig")
    assert spectrogram_facts_from_result(result, n_samples=0) is None
    assert spectrogram_facts_from_result(None, n_samples=256) is None
