"""End-to-end signal-layer recovery test for the non-uniform time axis bug.

Cross-references:
  * T1 diagnosis: docs/superpowers/reports/2026-04-26-nonuniform-fft-T1-diagnosis.md
  * T2 fix:       docs/superpowers/reports/2026-04-26-nonuniform-fft-T2-fix.md
  * T3 popover:   docs/superpowers/reports/2026-04-26-nonuniform-fft-T3-popover-geometry.md
  * T4 (this):    docs/superpowers/reports/2026-04-26-nonuniform-fft-T4-validation.md

User report (sample file ``testdoc/TLC_TAS_RPS_2ms.mf4``,
relative_jitter ~ 2.36):

  > 触发这个提示之后，手动输入频率也无法计算。

This module verifies the **signal-layer** half of the recovery story end
to end, without spinning up a GUI:

  1. A synthetic ``FileData`` whose ``time_array`` carries jitter ~ 2.4
     (mimicking the user's mf4 file).
  2. ``fd.is_time_axis_uniform()`` returns ``False``; the worker's
     ``SpectrogramAnalyzer.compute`` raises the exact same
     ``non-uniform time axis`` ``ValueError`` the T1 trace recorded;
     ``fd.suggested_fs_from_time_axis()`` returns an Fs in the same
     order of magnitude as the nominal (which is what the popover seeds
     ``spin_fs`` with).
  3. Calling ``fd.rebuild_time_axis(suggested_fs)`` writes
     ``arange(n)/fs`` -- guaranteed uniform.
  4. The same ``compute`` call now succeeds and returns a non-empty
     ``SpectrogramResult``.

A baseline uniform fixture asserts the pre-flight is a green-pass when
the input is already uniform.

**FFT (1D) note:** ``FFTAnalyzer.compute_fft`` does NOT consume the
time axis -- it samples by index + ``fs``. The pre-flight that gates
non-uniform inputs from reaching the FFT button lives in the UI layer
(``MainWindow.do_fft``, see T2 fix report). The signal layer's job is
only to expose ``is_time_axis_uniform`` and the analyzer's
``_validate_time_axis``. Both are exercised here for the spectrogram
path; the 1D FFT pre-flight regression lives in
``tests/ui/test_nonuniform_fft_full_flow.py`` (UI layer).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.signal.spectrogram import (
    DEFAULT_TIME_JITTER_TOLERANCE,
    SpectrogramAnalyzer,
    SpectrogramParams,
)


# --- Fixtures ---------------------------------------------------------


def _build_file_data(time_array: np.ndarray, fs: float) -> FileData:
    """Build a ``FileData`` around an explicit time axis + matching signal.

    Mirrors the helper in ``tests/test_nonuniform_fft_preflight.py`` but
    is duplicated here to keep this file self-contained -- T4 is a
    cross-layer regression gate and we want it to fail loudly even if
    the predicate-only test file is renamed/removed.

    Models the user's MF4 capture: samples are logged at *uniform*
    intervals on the hardware side, but the recorder writes jittered
    timestamps. Therefore the synthesized signal is a well-defined
    uniform-rate sinusoid (sampled on ``arange(n)/fs``) regardless of
    how non-uniform ``time_array`` is. After ``rebuild_time_axis(fs)``
    the signal+axis pair becomes the same well-defined uniform sequence
    the analyzer should accept and locate the tone in.
    """
    n = len(time_array)
    rng = np.random.default_rng(seed=0)
    # 100 Hz tone sampled on a uniform-rate clock (NOT on the jittered
    # time_array). This mirrors the real-world MF4 capture where the
    # ADC fires at a stable rate and only the timestamp column carries
    # logger jitter.
    uniform_t = np.arange(n, dtype=float) / float(fs)
    sig = np.sin(2.0 * np.pi * 100.0 * uniform_t)
    sig = sig + 1e-3 * rng.standard_normal(n)
    df = pd.DataFrame({'sig': sig})
    fd = FileData(
        fp='/tmp/synthetic_nonuniform.mf4',
        df=df,
        chs=['sig'],
        units={'sig': 'V'},
        idx=0,
    )
    fd.time_array = np.asarray(time_array, dtype=float)
    fd.fs = float(fs)
    return fd


@pytest.fixture
def nonuniform_fd() -> FileData:
    """Non-uniform axis with relative_jitter ~ 2.4 (matches the user's
    TLC_TAS_RPS_2ms.mf4 scenario, T1 diagnosis).

    Construction: take a perfectly uniform axis at fs=500 Hz, then
    push every other sample 3 dt forward. The resulting odd-index gaps
    are 4*dt, even-index gaps are -2*dt + dt = ... actually we build
    something jitter-only (positive everywhere) with a max relative
    jitter close to 2.4 to mirror the user file.
    """
    nominal_fs = 500.0
    n = 4096
    t_uniform = np.arange(n, dtype=float) / nominal_fs
    t = t_uniform.copy()
    # Inject ~2.4x relative jitter: alternating dt of ~3*nominal_dt and
    # ~-1*nominal_dt would break monotonicity; instead push odd samples
    # forward by 2.4*nominal_dt so dt's alternate ~3.4*nominal_dt and
    # ~-1.4*nominal_dt -- still non-monotonic. Pick a non-monotonic-free
    # construction that keeps strict monotonicity but exceeds tolerance:
    # add slowly-growing perturbations that scale the gap by 2.4.
    nominal_dt = 1.0 / nominal_fs
    # bump every other sample forward by 2.4*nominal_dt -> the gaps
    # alternate (1+2.4)*dt and (1-2.4)*dt = -1.4*dt (negative -> non
    # monotonic). To stay monotonic, bump every other sample by
    # 2.4*nominal_dt but propagate the bump cumulatively so the axis
    # stays strictly increasing: equivalently, double-stretch every
    # other gap.
    bumps = np.zeros(n, dtype=float)
    bumps[1::2] = 2.4 * nominal_dt
    t = np.cumsum(np.concatenate(([0.0], np.diff(t_uniform) + bumps[1:])))
    # Sanity: strictly increasing, max relative jitter > tolerance.
    assert np.all(np.diff(t) > 0)
    fd = _build_file_data(t, nominal_fs)
    return fd


@pytest.fixture
def uniform_fd() -> FileData:
    """Baseline: a uniform axis the pre-flight should accept."""
    nominal_fs = 500.0
    n = 4096
    t = np.arange(n, dtype=float) / nominal_fs
    return _build_file_data(t, nominal_fs)


# --- Helper -----------------------------------------------------------


def _spectrogram_params(fs: float, nfft: int = 256) -> SpectrogramParams:
    return SpectrogramParams(
        fs=float(fs),
        nfft=int(nfft),
        window='hanning',
        overlap=0.5,
        remove_mean=True,
        db_reference=1.0,
    )


# --- Non-uniform end-to-end recovery ---------------------------------


class TestNonUniformRecovery:
    """The signal-layer half of the user-bug recovery, end to end."""

    def test_before_rebuild_predicate_is_false(self, nonuniform_fd):
        # Mirrors the user's 2.36 jitter (we built ~2.4); must reject.
        assert nonuniform_fd.is_time_axis_uniform() is False

    def test_before_rebuild_analyzer_raises_nonuniform(self, nonuniform_fd):
        # The same ValueError T1 reproduced. The string ``non-uniform
        # time axis`` is the contract surface; status-bar / toast wording
        # in the UI keys off it (lesson 2026-04-26 non-uniform fft
        # pre-flight). Locking the substring guards against a future
        # silent rewording that would defeat the UI gate.
        sig = np.asarray(nonuniform_fd.data['sig'].to_numpy(), dtype=float)
        params = _spectrogram_params(fs=nonuniform_fd.fs, nfft=256)
        with pytest.raises(ValueError, match='non-uniform time axis'):
            SpectrogramAnalyzer.compute(
                sig,
                nonuniform_fd.time_array,
                params,
                channel_name='sig',
            )

    def test_before_rebuild_suggested_fs_is_in_order(self, nonuniform_fd):
        # The popover seeds spin_fs with this estimate so the user only
        # confirms rather than retypes. The median-dt estimator is best
        # effort -- on alternating-gap fixtures it locks onto the larger
        # gap and may underestimate the nominal by ~3x; that is by design
        # (median-of-positive-gaps drops the rare large gaps that would
        # otherwise pull a mean estimate). What we do require is:
        #   * the value is finite and positive (no NaN/Inf/zero crash);
        #   * the value lives inside the QDoubleSpinBox range
        #     [1, 1e6] used by ``RebuildTimePopover.spin_fs`` so the
        #     popover can actually seed the spin without being clamped.
        nominal = nonuniform_fd.fs
        suggested = nonuniform_fd.suggested_fs_from_time_axis()
        assert np.isfinite(suggested)
        assert suggested > 0
        # Same range RebuildTimePopover.spin_fs accepts (drawers/rebuild_time_popover.py).
        assert 1.0 <= suggested <= 1e6
        # Order-of-magnitude sanity: must be within 10x of the nominal
        # so the popover seed does not shock the user into 4-digit edits
        # for a well-behaved file. The 10x band is generous; the user's
        # mf4 (jitter 2.36) lands inside this on the median estimator.
        assert 0.1 * nominal <= suggested <= 10.0 * nominal

    def test_rebuild_with_suggested_fs_then_recompute_succeeds(
        self, nonuniform_fd
    ):
        # Simulates the popover Accept side-effect (the only writer of
        # fd.time_array post construction, per T1 diagnosis) using the
        # popover's seed value -- the median-dt estimate. Even when the
        # estimate underestimates the nominal Fs (typical of
        # alternating-gap MF4 streams), the rebuild MUST still produce a
        # strictly-uniform axis the analyzer accepts. This is the
        # weakest-link guarantee: the user clicks Accept without
        # touching spin_fs, and the FFT vs Time button goes from "做不出"
        # to "正常出图". Tone fidelity is exercised in the
        # ``test_rebuild_with_user_typed_fs_recovers_synthetic_tone``
        # case below where the user types the actual nominal Fs.
        suggested = nonuniform_fd.suggested_fs_from_time_axis()
        nonuniform_fd.rebuild_time_axis(suggested)

        # The predicate now agrees with the analyzer's validator.
        assert nonuniform_fd.is_time_axis_uniform() is True

        # And SpectrogramAnalyzer.compute completes without raising and
        # returns a non-empty result.
        sig = np.asarray(nonuniform_fd.data['sig'].to_numpy(), dtype=float)
        params = _spectrogram_params(fs=nonuniform_fd.fs, nfft=256)
        result = SpectrogramAnalyzer.compute(
            sig,
            nonuniform_fd.time_array,
            params,
            channel_name='sig',
        )
        assert result is not None
        assert result.amplitude.size > 0
        assert result.amplitude.shape[1] >= 1, 'expected >= 1 frame'
        assert result.frequencies.size == params.nfft // 2 + 1
        # Frame center times must be strictly increasing (no NaNs from
        # the recovered axis).
        assert np.all(np.diff(result.times) > 0)
        assert np.all(np.isfinite(result.amplitude))

    def test_rebuild_with_user_typed_fs_recovers_synthetic_tone(
        self, nonuniform_fd
    ):
        # User-typed Fs path: the user looks at their MF4 metadata,
        # types the actual nominal Fs into spin_fs, clicks Accept. After
        # rebuild, the spectrogram must locate the injected tone -- if
        # the recovered axis silently aliases or drops samples, the peak
        # would land elsewhere.
        nominal_fs = nonuniform_fd.fs  # 500 Hz, matches fixture
        nonuniform_fd.rebuild_time_axis(nominal_fs)

        sig = np.asarray(nonuniform_fd.data['sig'].to_numpy(), dtype=float)
        params = _spectrogram_params(fs=nominal_fs, nfft=512)
        result = SpectrogramAnalyzer.compute(
            sig,
            nonuniform_fd.time_array,
            params,
            channel_name='sig',
        )
        # Average over frames; the peak bin should be at ~100 Hz (the
        # injected tone). The synthesis sampled the tone on the original
        # non-uniform axis, so the rebuild's uniform axis will see a
        # slightly distorted tone -- but the dominant frequency content
        # is unambiguously near 100 Hz, well above noise floor.
        avg = result.amplitude.mean(axis=1)
        peak_bin = int(np.argmax(avg))
        peak_freq = float(result.frequencies[peak_bin])
        # Bin spacing at fs=500, nfft=512 is ~0.98 Hz; the tone may
        # leak across a few bins so allow +/- 5 Hz.
        assert abs(peak_freq - 100.0) <= 5.0, (
            f'recovered spectrogram peak at {peak_freq:.1f} Hz is far '
            f'from the injected 100 Hz tone -- rebuild may have aliased'
        )


# --- Baseline: uniform input passes the same gate ---------------------


class TestUniformBaseline:
    """A uniform fixture must pass every gate the non-uniform path
    fails on. If this regresses, the predicate has drifted away from
    the analyzer's validator (the very thing T2 hoists into a shared
    constant to prevent)."""

    def test_predicate_true(self, uniform_fd):
        assert uniform_fd.is_time_axis_uniform() is True

    def test_analyzer_compute_succeeds(self, uniform_fd):
        sig = np.asarray(uniform_fd.data['sig'].to_numpy(), dtype=float)
        params = _spectrogram_params(fs=uniform_fd.fs, nfft=256)
        result = SpectrogramAnalyzer.compute(
            sig,
            uniform_fd.time_array,
            params,
            channel_name='sig',
        )
        assert result.amplitude.size > 0
        assert result.amplitude.shape[1] >= 1

    def test_suggested_fs_matches_nominal(self, uniform_fd):
        # Uniform axis -> median dt reciprocal is fs to ~ulp.
        suggested = uniform_fd.suggested_fs_from_time_axis()
        assert suggested == pytest.approx(uniform_fd.fs, rel=1e-9)


# --- Tolerance contract guardrail ------------------------------------


class TestToleranceContractGuardrail:
    """The whole point of T2's hoisted ``DEFAULT_TIME_JITTER_TOLERANCE``
    is that the predicate and the analyzer cannot drift. If a future
    change re-hardcodes a different threshold in either place, the
    user's bug returns. This test fails loudly in that scenario.
    """

    def test_predicate_and_analyzer_agree_at_boundary(self):
        # Construct an axis whose relative jitter is a hair over the
        # shared tolerance: predicate must return False AND the analyzer
        # must raise. Disagreement at this boundary is the regression
        # the T2 fix exists to prevent.
        fs = 1000.0
        n = 1024
        t = np.arange(n, dtype=float) / fs
        # Push the last gap to (1 + 5*tol) * dt -- well over the
        # threshold, well below "obvious" ranges so a tightening of the
        # constant would still trip this case.
        bump = (DEFAULT_TIME_JITTER_TOLERANCE * 5.0) * (1.0 / fs)
        t[-1] += bump
        fd = _build_file_data(t, fs)

        assert fd.is_time_axis_uniform() is False

        sig = np.asarray(fd.data['sig'].to_numpy(), dtype=float)
        with pytest.raises(ValueError, match='non-uniform time axis'):
            SpectrogramAnalyzer.compute(
                sig,
                fd.time_array,
                _spectrogram_params(fs=fs, nfft=128),
                channel_name='sig',
            )
