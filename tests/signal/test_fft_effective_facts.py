"""Effective-facts DTO for FFT: owner length, padding, empty input."""
from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.batch_compute import (
    compute_fft_dataframe,
    fft_effective_facts_from_compute,
)
from mf4_analyzer.signal.fft import (
    FFTAnalyzer,
    build_fft_effective_facts,
    infer_nfft_from_freq,
)


def test_short_signal_averaged_fft_marks_shortened_from_compute_owner():
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
    assert facts.nfft == min(requested, len(sig)) == 50
    assert facts.window_samples == 50
    assert facts.fs == pytest.approx(fs)
    assert facts.df == pytest.approx(fs / facts.nfft)
    assert facts.df == pytest.approx(freq[1] - freq[0])


@pytest.mark.parametrize("n_samples", [63, 64, 129, 3553])
def test_fixed_average_facts_use_odd_or_even_owner_length(n_samples):
    fs = 1000.0
    requested = 4096
    sig = np.ones(n_samples, dtype=float)
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
    )
    assert facts.nfft == n_samples
    assert facts.df == pytest.approx(fs / n_samples)
    assert facts.df == pytest.approx(freq[1] - freq[0])
    assert facts.window_samples == n_samples
    assert facts.window_s == pytest.approx(n_samples / fs)
    inferred = infer_nfft_from_freq(freq)
    if n_samples % 2:
        assert inferred != n_samples


@pytest.mark.parametrize("avg_mode", ["单帧", "峰值保持"])
def test_fixed_zero_pad_keeps_real_window_not_nfft_duration(avg_mode):
    fs = 1000.0
    requested = 4096
    sig = np.ones(1000, dtype=float)
    facts = build_fft_effective_facts(
        sig, fs,
        window="hanning",
        nfft=requested,
        avg_mode=avg_mode,
        overlap=0.5,
        nfft_requested=requested,
    )
    assert facts.nfft == requested
    assert facts.window_samples == 1000
    assert facts.window_s == pytest.approx(1.0)
    assert facts.df == pytest.approx(fs / requested)
    assert facts.shortened is False
    payload = facts.to_canonical_dict()
    assert payload["nfft_effective"] == 4096
    assert payload["window_samples"] == 1000
    assert payload["window_s"] == pytest.approx(1.0)


def test_unpadded_single_frame_window_matches_nfft():
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
    assert facts.window_samples == 1024
    assert facts.window_s == pytest.approx(1024 / fs)
    assert facts.df_hz == pytest.approx(facts.df)
    assert facts.nfft == infer_nfft_from_freq(freq)
    assert facts.frames == 1


def test_explicit_odd_fft_length_is_not_rounded_from_freq_axis():
    fs = 1000.0
    nfft = 3553
    sig = np.ones(8000, dtype=float)
    freq, _amp, _psd = FFTAnalyzer.compute_averaged_fft(
        sig, fs, "hanning", nfft, 0.5,
    )
    facts = build_fft_effective_facts(
        sig, fs,
        window="hanning",
        nfft=nfft,
        avg_mode="线性平均",
        overlap=0.5,
        nfft_requested=nfft,
        freq=freq,
    )
    assert facts.nfft == 3553
    assert infer_nfft_from_freq(freq) == 3552
    assert facts.df == pytest.approx(fs / 3553)
    assert facts.df == pytest.approx(freq[1] - freq[0])


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


def _fixed_fft_params(avg_mode, nfft=4096):
    return {
        "window": "hanning",
        "nfft": nfft,
        "nfft_mode": "fixed",
        "avg_mode": avg_mode,
        "avg_overlap": 50,
        "weighting": "None",
    }


@pytest.mark.parametrize("n_samples", [63, 64, 129, 3553])
def test_batch_producer_odd_average_facts_match_axis(n_samples):
    fs = 1000.0
    sig = np.ones(n_samples, dtype=float)
    params = _fixed_fft_params("线性平均")
    frame = compute_fft_dataframe(sig, fs, params)
    freq = frame["frequency_hz"].to_numpy()
    facts = frame.attrs["effective_facts"]
    rebuilt = fft_effective_facts_from_compute(sig, fs, params, freq)
    assert facts.nfft == rebuilt.nfft == n_samples
    assert facts.df == pytest.approx(fs / n_samples)
    assert facts.df == pytest.approx(freq[1] - freq[0])
    assert facts.window_s == pytest.approx(n_samples / fs)
    assert facts.to_canonical_dict()["nfft_effective"] == n_samples


@pytest.mark.parametrize("avg_mode", ["单帧", "峰值保持"])
def test_batch_producer_zero_pad_window_is_real_observation(avg_mode):
    fs = 1000.0
    sig = np.ones(1000, dtype=float)
    params = _fixed_fft_params(avg_mode)
    frame = compute_fft_dataframe(sig, fs, params)
    freq = frame["frequency_hz"].to_numpy()
    facts = frame.attrs["effective_facts"]
    assert facts.nfft_effective == 4096
    assert facts.window_samples == 1000
    assert facts.window_s == pytest.approx(1.0)
    assert facts.df == pytest.approx(fs / 4096)
    assert freq[1] - freq[0] == pytest.approx(facts.df)
    assert facts.window_s != pytest.approx(4096 / fs)
