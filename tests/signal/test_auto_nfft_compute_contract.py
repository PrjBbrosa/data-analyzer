"""Compute-layer contract for practical Auto-NFFT: grid, padding, frames, M9."""
from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.signal import (
    AutoNfftBlockedError,
    canonical_spectrogram_frame_starts,
    nfft_facts_signature,
    nfft_facts_signature_from_decision,
    raise_if_auto_nfft_blocked,
    resolve_auto_nfft,
)
from mf4_analyzer.signal.analysis_defaults import AUTO_NFFT_POLICY_VERSION
from mf4_analyzer.signal.fft import FFTAnalyzer, build_fft_effective_facts
from mf4_analyzer.signal.spectrogram import (
    SpectrogramAnalyzer,
    SpectrogramParams,
    spectrogram_facts_from_result,
)


def test_averaged_fft_4096_grid_and_bin_aligned_tone():
    fs = 1000.0
    nfft = 4096
    n = 60000
    tone_hz = 256 * fs / nfft
    t = np.arange(n, dtype=float) / fs
    sig = np.sin(2.0 * np.pi * tone_hz * t)
    freq, amp, _psd = FFTAnalyzer.compute_averaged_fft(
        sig, fs, "hanning", nfft, 0.5,
    )
    assert freq.shape == amp.shape
    assert freq.shape[0] == nfft // 2
    df = fs / nfft
    assert freq[1] == pytest.approx(df)
    peak_bin = int(np.argmax(amp[1:])) + 1
    assert peak_bin == 256
    assert freq[peak_bin] == pytest.approx(tone_hz)


def test_auto_does_not_zero_pad_short_record_to_4096():
    fs = 1000.0
    n = 3000
    decision = resolve_auto_nfft(fs, n, 1.5, 0.5, purpose="fft_segmented")
    assert decision.requested_nfft == 4096
    assert decision.effective_nfft == 2048
    sig = np.sin(2.0 * np.pi * 40.0 * np.arange(n, dtype=float) / fs)
    freq, _amp, _psd = FFTAnalyzer.compute_averaged_fft(
        sig, fs, "hanning", int(decision.effective_nfft), 0.5,
    )
    assert 2 * len(freq) == 2048
    facts = build_fft_effective_facts(
        sig, fs,
        window="hanning",
        nfft=decision.effective_nfft,
        avg_mode="线性平均",
        overlap=0.5,
        nfft_requested=decision.requested_nfft,
        freq=freq,
        nfft_mode="auto",
        decision=decision,
    )
    assert facts.window_s == pytest.approx(2048 / fs)
    assert facts.nfft_effective == 2048
    assert facts.df_hz == pytest.approx(fs / 2048)
    assert facts.nfft is facts.nfft_effective or facts.nfft == facts.nfft_effective


@pytest.mark.parametrize("n_samples", [3552, 3553])
def test_single_frame_auto_keeps_whole_selection_including_odd(n_samples):
    fs = 1000.0
    sig = np.sin(2.0 * np.pi * 40.0 * np.arange(n_samples, dtype=float) / fs)
    freq, amp = FFTAnalyzer.compute_fft(sig, fs, "hanning", nfft=None)
    assert len(sig) == n_samples
    assert freq.shape[0] == n_samples // 2
    facts = build_fft_effective_facts(
        sig, fs,
        window="hanning",
        nfft=None,
        avg_mode="单帧",
        nfft_requested=n_samples,
        nfft_mode="auto",
    )
    assert facts.nfft == n_samples
    assert facts.nfft_effective == n_samples
    assert facts.df_hz == pytest.approx(fs / n_samples)
    assert facts.frames == 1
    assert facts.nfft_policy_version is None
    assert facts.nfft_preferred is None
    payload = facts.to_canonical_dict()
    assert payload["nfft_effective"] == n_samples
    assert payload["nfft"] == n_samples
    assert payload["df_hz"] == payload["df"]


def test_min_frames_no_longer_marks_unclamped_nfft_shortened():
    fs = 1000.0
    sig = np.zeros(10000, dtype=float)
    facts = build_fft_effective_facts(
        sig, fs,
        window="hanning",
        nfft=4096,
        avg_mode="线性平均",
        overlap=0.5,
        nfft_requested=4096,
        min_frames=24,
        nfft_mode="fixed",
    )
    assert facts.frames == 3
    assert facts.nfft == 4096
    assert facts.shortened is False
    assert facts.nfft_status is None


def test_nfft_facts_signature_separates_same_effective_different_intent():
    fs = 1000.0
    n = 3000
    d_short = resolve_auto_nfft(fs, n, 1.5, 0.5, purpose="fft_segmented")
    d_long = resolve_auto_nfft(fs, n, 8.0, 0.5, purpose="fft_segmented")
    assert d_short.effective_nfft == d_long.effective_nfft == 2048
    assert d_short.requested_nfft == 4096
    assert d_long.requested_nfft == 8192
    sig_short = nfft_facts_signature_from_decision(
        d_short, t_win_s=1.5, policy_version=AUTO_NFFT_POLICY_VERSION,
    )
    sig_long = nfft_facts_signature_from_decision(
        d_long, t_win_s=8.0, policy_version=AUTO_NFFT_POLICY_VERSION,
    )
    assert sig_short != sig_long
    auto_sig = nfft_facts_signature(
        nfft_mode="auto",
        policy_version=AUTO_NFFT_POLICY_VERSION,
        t_win_s=1.5,
        duration_target=d_short.duration_target_nfft,
        requested_nfft=4096,
        effective_nfft=4096,
        n_samples=60000,
        status="normal",
        degraded=False,
        reasons=d_short.reasons,
    )
    fixed_sig = nfft_facts_signature(
        nfft_mode="fixed",
        requested_nfft=4096,
        effective_nfft=4096,
        n_samples=60000,
    )
    assert auto_sig != fixed_sig
    assert fixed_sig[1] is None


def test_blocked_decision_becomes_user_data_error():
    decision = resolve_auto_nfft(1000.0, 32, 1.5, 0.5, purpose="fft_segmented")
    with pytest.raises(AutoNfftBlockedError) as caught:
        raise_if_auto_nfft_blocked(decision)
    assert caught.value.decision is decision
    assert caught.value.decision.effective_nfft is None
    ok = resolve_auto_nfft(1000.0, 60000, 1.5, 0.5, purpose="fft_segmented")
    assert raise_if_auto_nfft_blocked(ok) is ok


def test_spectrogram_starts_match_neutral_owner_and_metadata_frames():
    fs = 1000.0
    n = 10000
    nfft = 4096
    overlap = 0.5
    t = np.arange(n, dtype=float) / fs
    sig = np.sin(2.0 * np.pi * 40.0 * t)
    params = SpectrogramParams(fs=fs, nfft=nfft, overlap=overlap)
    result = SpectrogramAnalyzer.compute(sig, t, params, channel_name="sig")
    starts = canonical_spectrogram_frame_starts(n, nfft, overlap)
    assert result.metadata["frames"] == len(starts)
    assert np.array_equal(
        SpectrogramAnalyzer._frame_starts(n, nfft, result.metadata["hop"]),
        starts,
    )
    centers = t[starts] + (nfft - 1) / (2.0 * fs)
    assert np.allclose(result.times, centers)
    facts = spectrogram_facts_from_result(
        result, nfft_requested=4096, n_samples=n, nfft_mode="auto",
        decision=resolve_auto_nfft(fs, n, 1.5, overlap, purpose="fft_time"),
    )
    assert facts.nfft_effective == nfft
    assert facts.df_hz == pytest.approx(fs / nfft)
    assert facts.to_canonical_dict()["nfft"] == nfft


def _burst_and_sweep(n=60000, fs=1000.0, seed=20260905):
    t = np.arange(n, dtype=float) / fs
    burst = np.zeros(n, dtype=float)
    mask = (t >= 20.0) & (t < 20.25)
    burst[mask] = np.sin(2.0 * np.pi * 100.0 * t[mask])
    sweep = np.sin(2.0 * np.pi * (20.0 + (80.0 / 59.999) * t) * t)
    rng = np.random.default_rng(seed)
    noise = 0.01 * rng.standard_normal(n)
    return t, burst + noise, sweep + noise


def test_burst_windows_without_overlap_have_no_burst_bin_energy():
    fs = 1000.0
    nfft = 4096
    overlap = 0.5
    t, burst, _sweep = _burst_and_sweep()
    params = SpectrogramParams(fs=fs, nfft=nfft, overlap=overlap)
    auto_result = SpectrogramAnalyzer.compute(burst, t, params, channel_name="burst")
    fixed_result = SpectrogramAnalyzer.compute(burst, t, params, channel_name="burst")
    assert np.allclose(auto_result.amplitude, fixed_result.amplitude)
    starts = canonical_spectrogram_frame_starts(burst.size, nfft, overlap)
    burst_interval = (20.0, 20.25)
    freq = auto_result.frequencies
    bin_100 = int(np.argmin(np.abs(freq - 100.0)))
    peak_energy = float(np.max(auto_result.amplitude[bin_100]))
    floor = 0.05 * peak_energy
    for i, start in enumerate(starts):
        win_start = float(t[int(start)])
        win_end = float(t[int(start) + nfft - 1])
        intersects = not (win_end < burst_interval[0] or win_start >= burst_interval[1])
        if not intersects:
            assert auto_result.amplitude[bin_100, i] < floor


def test_peak_hold_compute_is_not_render_peak_trace():
    from mf4_analyzer.signal.envelope import build_peak_trace

    fs = 1000.0
    n = 8192
    sig = np.sin(2.0 * np.pi * 40.0 * np.arange(n, dtype=float) / fs)
    freq, peak = FFTAnalyzer.compute_peak_hold_fft(
        sig, fs, win="hanning", nfft=2048, overlap=0.5,
    )
    render_x, render_y = build_peak_trace(
        freq, peak, xlim=(float(freq[0]), float(freq[-1])), pixel_width=64,
    )
    assert render_x.shape[0] <= freq.shape[0]
    assert peak.shape == freq.shape
