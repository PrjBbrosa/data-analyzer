"""Behavioral contract tests for ``MainWindow._fft_fetch_signal``.

This helper fetches a single FFT source's signal and, when the inspector's
range gate is enabled, masks the signal to ``lo <= t <= hi`` before
returning ``(sig, fs)``. It does NOT return the time axis.

These tests lock the return contract so that removing the dead
``t = t[m]`` reassignment inside the function (its sliced result is never
read; only ``sig = sig[m]`` and ``fd.fs`` reach the return) cannot change
observable behavior. The masked ``sig`` and ``fs`` must be identical
before and after that removal.

Synthetic FileData only -- no MF4 file, no plotting.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.ui.main_window import MainWindow


def _make_file_data(fid_path: str, t: np.ndarray, sig: np.ndarray) -> FileData:
    """Build a FileData whose 'sig' column carries ``sig`` over axis ``t``.

    The dataframe deliberately has no time-like column so FileData's
    auto-detect leaves a generated axis; we then overwrite ``time_array``
    and ``fs`` with the explicit values under test.
    """
    df = pd.DataFrame({'sig': np.asarray(sig, dtype=float)})
    fd = FileData(fp=fid_path, df=df, chs=['sig'], units={'sig': ''}, idx=0)
    fd.time_array = np.asarray(t, dtype=float)
    dt = float(np.median(np.diff(t))) if len(t) > 1 else 1.0
    fd.fs = 1.0 / dt if dt > 0 else 1000.0
    return fd


@pytest.fixture
def win_with_source(qapp):
    """A MainWindow holding one synthetic file keyed by fid=0."""
    w = MainWindow()
    t = np.linspace(0.0, 1.0, 11)          # 0.0, 0.1, ..., 1.0
    sig = np.arange(11, dtype=float) * 10  # 0, 10, 20, ..., 100
    fd = _make_file_data('/tmp/fetch_src.mf4', t, sig)
    w.files[0] = fd
    return w, fd


def test_no_range_returns_full_signal_and_fs(win_with_source, monkeypatch):
    w, fd = win_with_source
    monkeypatch.setattr(w.inspector.top, 'range_enabled', lambda: False)

    sig, fs = w._fft_fetch_signal(0, 'sig')

    np.testing.assert_array_equal(sig, fd.data['sig'].values)
    assert fs == fd.fs


def test_range_enabled_masks_signal_inclusive(win_with_source, monkeypatch):
    w, fd = win_with_source
    # Window [0.25, 0.75] selects samples at t = 0.3, 0.4, 0.5, 0.6, 0.7
    # -> sig values 30, 40, 50, 60, 70.
    monkeypatch.setattr(w.inspector.top, 'range_enabled', lambda: True)
    monkeypatch.setattr(w.inspector.top, 'range_values', lambda: (0.25, 0.75))

    sig, fs = w._fft_fetch_signal(0, 'sig')

    np.testing.assert_array_equal(sig, np.array([30.0, 40.0, 50.0, 60.0, 70.0]))
    assert fs == fd.fs


def test_range_bounds_are_inclusive(win_with_source, monkeypatch):
    w, fd = win_with_source
    # Exact bounds at sample positions must be included (>= / <=).
    monkeypatch.setattr(w.inspector.top, 'range_enabled', lambda: True)
    monkeypatch.setattr(w.inspector.top, 'range_values', lambda: (0.2, 0.4))

    sig, _ = w._fft_fetch_signal(0, 'sig')

    np.testing.assert_array_equal(sig, np.array([20.0, 30.0, 40.0]))


def test_missing_file_returns_none_pair(win_with_source):
    w, _ = win_with_source
    assert w._fft_fetch_signal(999, 'sig') == (None, None)


def test_missing_channel_returns_none_pair(win_with_source):
    w, _ = win_with_source
    assert w._fft_fetch_signal(0, 'nope') == (None, None)
