"""Effective-facts DTO for order / COT: shortened auto NFFT and empty input."""
from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.signal.fft import unconstrained_window_nfft
from mf4_analyzer.signal.order import order_facts_from_result
from mf4_analyzer.signal.order_cot import COTOrderAnalyzer, COTParams


def _sweep(n, fs, rpm0=600.0, rpm1=1800.0):
    t = np.arange(n, dtype=float) / fs
    rpm = np.linspace(rpm0, rpm1, n)
    sig = np.sin(2 * np.pi * (rpm / 60.0) * t)
    return t, sig, rpm


def test_auto_nfft_below_unconstrained_target_is_shortened():
    fs = 1000.0
    n = 4000
    t, sig, rpm = _sweep(n, fs)
    order_res = 0.1
    samples_per_rev = 256
    requested = unconstrained_window_nfft(
        samples_per_rev, 1.0 / order_res, floor=256, ceil=16384,
    )
    params = COTParams(
        samples_per_rev=samples_per_rev,
        nfft=256,
        window="hanning",
        max_order=10.0,
        order_res=order_res,
        time_res=0.05,
        fs=fs,
    )
    result = COTOrderAnalyzer.compute(sig, rpm, t, params)
    facts = order_facts_from_result(
        result, rpm,
        n_samples=n,
        order_res_requested=order_res,
        nfft_requested=requested,
    )
    assert facts is not None
    assert facts.nfft == 256
    assert requested is not None and requested > 256
    assert facts.shortened is True
    assert facts.fs == pytest.approx(fs)
    assert facts.order_res == pytest.approx(order_res)
    assert facts.rpm_min is not None and facts.rpm_max is not None
    assert facts.rpm_max >= facts.rpm_min
    assert facts.revolutions > 0


def test_fixed_nfft_matching_compute_is_not_shortened():
    fs = 1000.0
    n = 4000
    t, sig, rpm = _sweep(n, fs)
    params = COTParams(
        samples_per_rev=256,
        nfft=256,
        window="hanning",
        max_order=10.0,
        order_res=0.25,
        time_res=0.05,
        fs=fs,
    )
    result = COTOrderAnalyzer.compute(sig, rpm, t, params)
    facts = order_facts_from_result(
        result, rpm,
        n_samples=n,
        order_res_requested=0.25,
        nfft_requested=256,
    )
    assert facts is not None
    assert facts.shortened is False
    assert facts.nfft == 256
    assert facts.n_samples == n


def test_empty_or_nonfinite_fs_returns_no_facts():
    fs = 1000.0
    n = 4000
    t, sig, rpm = _sweep(n, fs)
    params = COTParams(
        samples_per_rev=256, nfft=256, max_order=10.0, order_res=0.25,
        time_res=0.05, fs=fs,
    )
    result = COTOrderAnalyzer.compute(sig, rpm, t, params)
    assert order_facts_from_result(result, rpm, n_samples=0) is None
    assert order_facts_from_result(None, rpm, n_samples=n) is None
    result.params = COTParams(
        samples_per_rev=256, nfft=256, max_order=10.0, order_res=0.25,
        time_res=0.05, fs=float("nan"),
    )
    # COTParams __post_init__ does not reject fs; the builder must.
    assert order_facts_from_result(result, rpm, n_samples=n) is None
