"""Effective-facts DTO for FFT: clamp, empty input, and freq-axis inference."""
from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.signal.fft import (
    FFTAnalyzer,
    build_fft_effective_facts,
    infer_nfft_from_freq,
)


def test_short_signal_averaged_fft_marks_shortened_and_matches_freq_axis():
    fs = 1000.0
    sig = np.ones(50, dtype=float)
    requested = 256
    freq, _amp, _psd = FFTAnalyzer.compute_averaged_fft(
        sig, fs, "hanning", requested, 0.5,
    )
    facts = build_fft_effective_facts(
        sig, fs,
        window="hanning",
        nfft=requested,
        avg_mode="线性平均",
        overlap=0.5,
        nfft_requested=requested,
        freq=freq,
        min_frames=24,
    )
    assert facts is not None
    assert facts.shortened is True
    assert facts.nfft == infer_nfft_from_freq(freq)
    assert facts.nfft == 2 * len(freq)
    assert facts.nfft < requested
    assert facts.nfft == min(requested, len(sig))
    assert facts.fs == pytest.approx(fs)
    assert facts.df == pytest.approx(fs / facts.nfft)


def test_normal_signal_single_frame_is_not_shortened():
    fs = 1000.0
    sig = np.sin(2 * np.pi * 40.0 * np.arange(2048, dtype=float) / fs)
    freq, _amp = FFTAnalyzer.compute_fft(sig, fs, "hanning", nfft=1024)
    facts = build_fft_effective_facts(
        sig, fs,
        window="hanning",
        nfft=1024,
        avg_mode="单帧",
        overlap=0.0,
        nfft_requested=1024,
        freq=freq,
    )
    assert facts is not None
    assert facts.shortened is False
    assert facts.nfft == 1024
    assert facts.nfft_effective == 1024
    assert facts.df_hz == pytest.approx(facts.df)
    assert facts.nfft == infer_nfft_from_freq(freq)
    assert facts.frames == 1
    assert facts.nfft_policy_version is None


def test_empty_signal_returns_no_facts():
    assert build_fft_effective_facts(
        [], 1000.0, window="hanning", nfft=256,
    ) is None
    assert build_fft_effective_facts(
        np.array([], dtype=float), 1000.0, window="hanning", nfft=256,
    ) is None


def test_nonfinite_or_nonpositive_fs_returns_no_facts():
    sig = np.ones(128, dtype=float)
    assert build_fft_effective_facts(
        sig, float("nan"), window="hanning", nfft=64,
    ) is None
    assert build_fft_effective_facts(
        sig, 0.0, window="hanning", nfft=64,
    ) is None
    assert build_fft_effective_facts(
        sig, -100.0, window="hanning", nfft=64,
    ) is None
    assert infer_nfft_from_freq([]) is None
    assert infer_nfft_from_freq(np.array([], dtype=float)) is None
