"""GUI vs batch effective-facts parity for FFT / spectrogram / order."""
from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.batch_compute import (
    compute_fft_dataframe,
    compute_fft_time_spectro,
    compute_order_time_spectro,
    fft_effective_facts_from_compute,
)
from mf4_analyzer.signal.analysis_defaults import DEFAULT_FFT_T_WIN_S
from mf4_analyzer.signal.fft import unconstrained_window_nfft
from mf4_analyzer.signal.order import order_facts_from_result
from mf4_analyzer.signal.spectrogram import spectrogram_facts_from_result
from mf4_analyzer.ui.main_window._fft_mixin import FFTMixin


def _fields(facts):
    return {
        name: getattr(facts, name)
        for name in facts.__dataclass_fields__
        if name not in {"nan_count", "is_constant", "time_axis", "fs_conflict"}
    }


def test_fft_gui_and_batch_facts_match_for_the_same_signal():
    fs = 1000.0
    n = 2048
    sig = np.sin(2 * np.pi * 40.0 * np.arange(n, dtype=float) / fs)
    params = {
        "window": "hanning",
        "nfft": None,
        "nfft_mode": "auto",
        "t_win_s": DEFAULT_FFT_T_WIN_S,
        "avg_mode": "线性平均",
        "avg_overlap": 50,
        "weighting": "None",
    }
    dummy = FFTMixin()
    gui_result = dummy._fft_compute_arrays(sig, fs, params)
    gui_facts = gui_result.effective
    frame = compute_fft_dataframe(sig, fs, params)
    batch_facts = fft_effective_facts_from_compute(
        sig, fs, params, freq=frame["frequency_hz"].to_numpy(),
    )
    assert gui_facts is not None and batch_facts is not None
    assert _fields(gui_facts) == _fields(batch_facts)
    assert gui_facts.nfft == batch_facts.nfft
    assert gui_facts.shortened == batch_facts.shortened


def test_spectrogram_gui_builder_and_batch_metadata_match():
    fs = 1000.0
    n = 2048
    t = np.arange(n, dtype=float) / fs
    sig = np.sin(2 * np.pi * 40.0 * t)
    params = {
        "nfft": 256,
        "window": "hanning",
        "overlap": 0.5,
        "remove_mean": True,
        "weighting": "None",
    }
    spectro = compute_fft_time_spectro(sig, t, fs, params, channel_name="sig")
    payload = dict(spectro.metadata.get("effective_facts") or {})
    # Rebuild from the same producer-shaped result fields.
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult

    result = SpectrogramResult(
        times=spectro.x,
        frequencies=spectro.y,
        amplitude=np.asarray(spectro.matrix, dtype=np.float32).T,
        params=SpectrogramParams(
            fs=fs, nfft=256, window="hanning", overlap=0.5,
        ),
        channel_name="sig",
        metadata=dict(spectro.metadata),
    )
    facts = spectrogram_facts_from_result(
        result, nfft_requested=256, n_samples=n,
    )
    assert facts is not None
    assert payload["nfft"] == facts.nfft
    assert payload["df"] == pytest.approx(facts.df)
    assert payload["frames"] == facts.frames
    assert payload["shortened"] is False


def test_order_gui_builder_and_batch_metadata_match():
    fs = 1000.0
    n = 4000
    t = np.arange(n, dtype=float) / fs
    rpm = np.linspace(600.0, 1800.0, n)
    sig = np.sin(2 * np.pi * (rpm / 60.0) * t)
    params = {
        "nfft": 256,
        "window": "hanning",
        "max_order": 10.0,
        "order_res": 0.25,
        "time_res": 0.05,
        "samples_per_rev": 256,
        "weighting": "None",
    }
    spectro = compute_order_time_spectro(sig, rpm, t, fs, params)
    payload = dict(spectro.metadata.get("effective_facts") or {})
    from mf4_analyzer.signal.order_cot import COTParams, COTResult

    result = COTResult(
        times=spectro.x,
        orders=spectro.y,
        amplitude=np.asarray(spectro.matrix),
        params=COTParams(
            samples_per_rev=256, nfft=256, window="hanning",
            max_order=10.0, order_res=0.25, time_res=0.05, fs=fs,
        ),
        metadata=dict(spectro.metadata),
    )
    facts = order_facts_from_result(
        result, rpm, n_samples=n,
        order_res_requested=0.25, nfft_requested=256,
    )
    assert facts is not None
    assert payload["nfft"] == facts.nfft
    assert payload["order_res"] == pytest.approx(facts.order_res)
    assert payload["shortened"] is False
    assert unconstrained_window_nfft(256, 1.0 / 0.25, floor=256, ceil=16384) >= 256
