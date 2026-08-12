"""A6: spectrogram time-axis rebuild returns auditable warnings."""
from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.batch_compute import (
    suggest_fs_from_time_axis,
    uniform_time_axis_for_spectrogram,
)


def test_uniform_time_axis_for_spectrogram_returns_rebuild_warning():
    fs = 500.0
    n = 128
    nominal_dt = 1.0 / fs
    dts = np.resize(np.array([1.2 * nominal_dt, 0.8 * nominal_dt]), n - 1)
    time = np.concatenate(([0.0], np.cumsum(dts)))
    rebuilt_fs = float(suggest_fs_from_time_axis(time, fs))

    new_time, new_fs, warnings = uniform_time_axis_for_spectrogram(time, fs, n)

    assert new_fs == pytest.approx(rebuilt_fs)
    assert new_fs != pytest.approx(fs)
    np.testing.assert_allclose(new_time, np.arange(n, dtype=float) / rebuilt_fs)
    assert len(warnings) == 1
    assert "自动重建" in warnings[0]
    assert "relative_jitter=" in warnings[0]
    assert f"Fs={rebuilt_fs:g}" in warnings[0]


def test_uniform_time_axis_for_spectrogram_uniform_input_has_empty_warnings():
    fs = 1000.0
    time = np.arange(64, dtype=float) / fs
    new_time, new_fs, warnings = uniform_time_axis_for_spectrogram(time, fs, 64)
    np.testing.assert_allclose(new_time, time)
    assert new_fs == pytest.approx(fs)
    assert warnings == ()
