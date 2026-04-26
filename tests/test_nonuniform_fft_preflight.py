"""Tests for the non-uniform time axis pre-flight check.

T2 (2026-04-26) adds a ``FileData.is_time_axis_uniform()`` predicate so
``do_fft`` / ``do_fft_time`` can route non-uniform inputs through the
rebuild popover BEFORE dispatching the worker. The predicate's tolerance
must mirror :func:`SpectrogramAnalyzer._validate_time_axis` exactly --
otherwise the pre-flight passes input the analyzer would reject (or the
inverse), and the user sees the same loop the fix was meant to remove.

Per the brief, **do not hardcode** the tolerance. The single source of
truth is :data:`mf4_analyzer.signal.spectrogram.DEFAULT_TIME_JITTER_TOLERANCE`,
which the analyzer's ``time_jitter_tolerance`` kwarg also defaults to.

These tests use synthetic numpy arrays only -- no MF4 file, no GUI.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.signal.spectrogram import (
    DEFAULT_TIME_JITTER_TOLERANCE,
    SpectrogramAnalyzer,
)


def _make_file_data(time_array: np.ndarray, fs: float) -> FileData:
    """Build a FileData around an explicit time axis + matching signal.

    FileData's __init__ scans the dataframe for time-like columns; we
    deliberately omit one so the time_array starts as the auto-generated
    arange(N)/fs, then we overwrite it to inject the desired axis.
    """
    n = len(time_array)
    rng = np.random.default_rng(seed=0)
    df = pd.DataFrame({'sig': rng.standard_normal(n)})
    fd = FileData(
        fp='/tmp/synthetic.mf4',
        df=df,
        chs=['sig'],
        units={'sig': ''},
        idx=0,
    )
    fd.time_array = np.asarray(time_array, dtype=float)
    fd.fs = float(fs)
    return fd


class TestIsTimeAxisUniform:
    """Predicate boundaries match SpectrogramAnalyzer._validate_time_axis."""

    def test_perfectly_uniform_axis_returns_true(self):
        fs = 1000.0
        n = 4096
        t = np.arange(n, dtype=float) / fs
        fd = _make_file_data(t, fs)
        assert fd.is_time_axis_uniform() is True

    def test_strongly_nonuniform_axis_returns_false(self):
        # Mimic the user's TLC_TAS_RPS_2ms.mf4: jitter ~2.36, far above 1e-3.
        fs = 500.0
        n = 1024
        t = np.arange(n, dtype=float) / fs
        # Inject ~3x relative jitter on every other dt step.
        t[1::2] += 3.0 / fs
        fd = _make_file_data(t, fs)
        assert fd.is_time_axis_uniform() is False

    def test_nonmonotonic_axis_returns_false(self):
        fs = 1000.0
        t = np.array([0.0, 0.001, 0.0005, 0.002, 0.003], dtype=float)
        fd = _make_file_data(t, fs)
        assert fd.is_time_axis_uniform() is False

    def test_jitter_at_tolerance_boundary_is_uniform(self):
        # Exactly at the threshold (max|dt - 1/fs| / (1/fs) == tolerance)
        # is treated as uniform: the analyzer rejects only when the
        # ratio STRICTLY exceeds tolerance. Mirror that contract.
        fs = 1000.0
        n = 1024
        t = np.arange(n, dtype=float) / fs
        # Push the second-to-last gap up by exactly tolerance * (1/fs).
        bump = DEFAULT_TIME_JITTER_TOLERANCE * (1.0 / fs)
        t[-1] += bump
        fd = _make_file_data(t, fs)
        assert fd.is_time_axis_uniform() is True

    def test_jitter_just_over_tolerance_is_not_uniform(self):
        fs = 1000.0
        n = 1024
        t = np.arange(n, dtype=float) / fs
        # Push it by more than tolerance.
        bump = (DEFAULT_TIME_JITTER_TOLERANCE * 5.0) * (1.0 / fs)
        t[-1] += bump
        fd = _make_file_data(t, fs)
        assert fd.is_time_axis_uniform() is False

    def test_uniformity_uses_current_fs_not_inferred(self):
        # If the user types Fs that does not match the actual dt, the
        # predicate must reject -- this is precisely the bug from the
        # user report: typing the "right-looking" Fs into spin_fs does
        # not magically make a non-uniform axis uniform.
        fs_actual = 1000.0
        n = 512
        t = np.arange(n, dtype=float) / fs_actual
        # User claims fs = 2000 (2x off); the relative jitter against
        # the user's claimed nominal_dt = 1/2000 will be huge.
        fd = _make_file_data(t, fs_actual)
        fd.fs = 2000.0
        assert fd.is_time_axis_uniform() is False

    def test_short_axis_is_treated_as_uniform(self):
        # Axes with < 2 samples cannot have meaningful jitter -- treat as
        # uniform so the pre-flight does not pop a rebuild dialog on an
        # empty / single-sample selection (those paths bail elsewhere on
        # ``len(sig) < 2``).
        fd = _make_file_data(np.array([0.0]), fs=1000.0)
        assert fd.is_time_axis_uniform() is True
        fd2 = _make_file_data(np.array([], dtype=float), fs=1000.0)
        assert fd2.is_time_axis_uniform() is True

    def test_predicate_matches_analyzer_validator_decision(self):
        """Boundary parity with SpectrogramAnalyzer._validate_time_axis.

        The predicate is True iff the analyzer's validator would NOT
        raise. We probe both sides of the threshold and the
        non-monotonic case to lock the contract.
        """
        fs = 1000.0
        n = 256
        cases = []

        # uniform
        t1 = np.arange(n, dtype=float) / fs
        cases.append((t1, True))

        # just over tolerance (analyzer raises)
        t2 = t1.copy()
        t2[-1] += 10.0 * DEFAULT_TIME_JITTER_TOLERANCE * (1.0 / fs)
        cases.append((t2, False))

        # non-monotonic (analyzer raises)
        t3 = t1.copy()
        t3[10], t3[11] = t3[11], t3[10]
        cases.append((t3, False))

        for t, expected_uniform in cases:
            fd = _make_file_data(t, fs)
            assert fd.is_time_axis_uniform() is expected_uniform, (
                f'predicate disagrees with analyzer for case'
            )
            # Cross-check: analyzer's validator agrees.
            try:
                SpectrogramAnalyzer._validate_time_axis(
                    t, fs, DEFAULT_TIME_JITTER_TOLERANCE
                )
                analyzer_accepts = True
            except ValueError:
                analyzer_accepts = False
            assert analyzer_accepts is expected_uniform


class TestSuggestedFs:
    """The pre-flight needs a fallback Fs estimate (median dt)."""

    def test_suggested_fs_from_median_dt(self):
        fs = 500.0
        n = 256
        t = np.arange(n, dtype=float) / fs
        fd = _make_file_data(t, fs)
        # On a uniform axis the suggestion should match fs to within
        # numerical precision.
        suggested = fd.suggested_fs_from_time_axis()
        assert suggested == pytest.approx(fs, rel=1e-9)

    def test_suggested_fs_handles_jittered_axis(self):
        # Non-uniform but with a clear central tendency -- median dt
        # should still recover something close to the nominal fs.
        fs = 1000.0
        n = 1024
        rng = np.random.default_rng(seed=42)
        dt_nominal = 1.0 / fs
        # ~5% jitter, zero-mean
        jitter = rng.uniform(-0.05, 0.05, size=n - 1) * dt_nominal
        dts = dt_nominal + jitter
        t = np.concatenate(([0.0], np.cumsum(dts)))
        fd = _make_file_data(t, fs)
        suggested = fd.suggested_fs_from_time_axis()
        assert suggested == pytest.approx(fs, rel=0.1)

    def test_suggested_fs_falls_back_when_axis_too_short(self):
        # Single-sample / empty axis -> fall back to current fd.fs.
        fd = _make_file_data(np.array([0.0]), fs=1234.0)
        assert fd.suggested_fs_from_time_axis() == pytest.approx(1234.0)
        fd2 = _make_file_data(np.array([], dtype=float), fs=999.0)
        assert fd2.suggested_fs_from_time_axis() == pytest.approx(999.0)


class TestSpectrogramConstantExposure:
    """The shared tolerance constant must be importable."""

    def test_constant_is_a_module_level_float(self):
        from mf4_analyzer.signal import spectrogram

        assert hasattr(spectrogram, 'DEFAULT_TIME_JITTER_TOLERANCE')
        assert isinstance(spectrogram.DEFAULT_TIME_JITTER_TOLERANCE, float)
        assert spectrogram.DEFAULT_TIME_JITTER_TOLERANCE > 0

    def test_compute_default_uses_module_constant(self):
        # The kwarg default on SpectrogramAnalyzer.compute must equal
        # DEFAULT_TIME_JITTER_TOLERANCE so file_data.is_time_axis_uniform
        # and the analyzer agree on the threshold.
        import inspect

        from mf4_analyzer.signal import spectrogram

        sig = inspect.signature(SpectrogramAnalyzer.compute)
        default = sig.parameters['time_jitter_tolerance'].default
        assert default == spectrogram.DEFAULT_TIME_JITTER_TOLERANCE
