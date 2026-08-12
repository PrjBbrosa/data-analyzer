"""Numeric contract tests for the NumPy-only FRF core."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import warnings

import numpy as np
import pytest

from mf4_analyzer.signal.frf import (
    FrfParams,
    FrfRequestPlan,
    compute_frf,
    get_frf_window,
    magnitude_db,
    magnitude_linear,
    plan_frf_request,
    phase_unwrapped_deg,
    phase_wrapped_deg,
)


def test_signal_package_reexports_the_frf_contract():
    from mf4_analyzer import signal

    assert signal.FrfParams is FrfParams
    assert signal.compute_frf is compute_frf


def _two_segment_pair(scale: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    # With periodic Hann(4)=[0,.5,1,.5], this segment becomes [0,0,-1,0].
    segment = scale * np.array([1.0, 0.0, -1.0, 0.0])
    x = np.tile(segment, 2)
    return x, 2.0 * x


def _basic_params(**changes) -> FrfParams:
    values = {
        "estimator": "h1",
        "t_win_s": 0.5,
        "overlap": 0.0,
        "window": "hanning",
        "detrend": "none",
    }
    values.update(changes)
    return FrfParams(**values)


def test_params_defaults_are_the_compute_contract():
    params = FrfParams()
    assert params == FrfParams(
        estimator="h1",
        t_win_s=2.0,
        overlap=0.5,
        nfft_mode="auto",
        nfft=None,
        window="hanning",
        periodic_window=True,
        detrend="constant",
    )
    with pytest.raises(FrozenInstanceError):
        params.estimator = "h2"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"estimator": "h3"}, "estimator"),
        ({"t_win_s": 0.0}, "t_win_s"),
        ({"t_win_s": np.inf}, "t_win_s"),
        ({"overlap": -0.1}, "overlap"),
        ({"overlap": 1.0}, "overlap"),
        ({"overlap": np.nan}, "overlap"),
        ({"nfft_mode": "other"}, "nfft_mode"),
        ({"nfft_mode": "manual", "nfft": None}, "nfft"),
        ({"nfft_mode": "manual", "nfft": 8.0}, "nfft"),
        ({"nfft_mode": "manual", "nfft": True}, "nfft"),
        ({"nfft_mode": "auto", "nfft": 8}, "nfft"),
        ({"window": "rectangle"}, "window"),
        ({"periodic_window": "yes"}, "periodic_window"),
        ({"detrend": "linear"}, "detrend"),
    ],
)
def test_params_reject_invalid_values(change, message):
    with pytest.raises(ValueError, match=message):
        FrfParams(**change)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("hanning", np.array([0.0, 0.5, 1.0, 0.5])),
        ("hann", np.array([0.0, 0.5, 1.0, 0.5])),
        ("hamming", np.array([0.08, 0.54, 1.0, 0.54])),
    ],
)
def test_periodic_window_has_explicit_hand_checked_samples(name, expected):
    np.testing.assert_allclose(get_frf_window(name, 4), expected, atol=1e-15)


@pytest.mark.parametrize("name", ["blackman", "bartlett"])
def test_periodic_numpy_windows_are_symmetric_n_plus_one_without_tail(name):
    generator = getattr(np, name)
    np.testing.assert_array_equal(
        get_frf_window(name, 8),
        generator(9)[:-1],
    )


def test_periodic_kaiser_uses_beta_14_and_n_plus_one_without_tail():
    np.testing.assert_array_equal(
        get_frf_window("kaiser", 8),
        np.kaiser(9, 14.0)[:-1],
    )


def test_periodic_false_keeps_the_existing_symmetric_window_semantics():
    np.testing.assert_array_equal(
        get_frf_window("hanning", 8, periodic=False),
        np.hanning(8),
    )


@pytest.mark.parametrize(
    "name", ["hanning", "hamming", "blackman", "bartlett", "kaiser", "flattop"]
)
@pytest.mark.parametrize("periodic", [True, False])
def test_all_single_sample_windows_are_exactly_one(name, periodic):
    np.testing.assert_array_equal(
        get_frf_window(name, 1, periodic=periodic),
        np.ones(1, dtype=np.float64),
    )


@pytest.mark.parametrize(
    ("which", "values", "message"),
    [
        ("input", np.array([]), "input.*empty"),
        ("output", np.array([]), "output.*empty"),
        ("input", np.ones((2, 2)), "input.*one-dimensional"),
        ("output", np.ones((2, 2)), "output.*one-dimensional"),
        ("input", np.array([True, False]), "input.*bool"),
        ("output", np.array([True, False]), "output.*bool"),
        ("input", np.array([1 + 1j, 2 + 0j]), "input.*complex"),
        ("output", np.array([1 + 1j, 2 + 0j]), "output.*complex"),
        ("input", np.array([1.0, np.nan]), "input.*non-finite"),
        ("output", np.array([1.0, np.inf]), "output.*non-finite"),
    ],
)
def test_input_contract_rejects_invalid_arrays(which, values, message):
    x = np.ones(8)
    y = np.ones(8)
    if which == "input":
        x = values
    else:
        y = values
    with pytest.raises(ValueError, match=message):
        compute_frf(x, y, fs=8.0, params=_basic_params())


def test_input_contract_never_truncates_unequal_signals():
    with pytest.raises(ValueError, match="same length"):
        compute_frf(np.ones(8), np.ones(7), fs=8.0, params=_basic_params())


@pytest.mark.parametrize("fs", [0.0, -1.0, np.inf, np.nan, True])
def test_input_contract_rejects_invalid_sampling_rate(fs):
    with pytest.raises(ValueError, match="fs"):
        compute_frf(np.ones(8), np.ones(8), fs=fs, params=_basic_params())


def test_time_axes_must_be_supplied_as_a_pair():
    t = np.arange(8, dtype=float) / 8.0
    with pytest.raises(ValueError, match="input_time and output_time"):
        compute_frf(
            np.ones(8), np.ones(8), fs=8.0, params=_basic_params(), input_time=t
        )


def test_time_axes_must_match_signal_lengths():
    t = np.arange(7, dtype=float) / 8.0
    with pytest.raises(ValueError, match="input_time.*same length"):
        compute_frf(
            np.ones(8),
            np.ones(8),
            fs=8.0,
            params=_basic_params(),
            input_time=t,
            output_time=t,
        )


def test_single_sample_time_axis_has_an_actionable_short_axis_error():
    t = np.array([0.0])
    with pytest.raises(ValueError, match="input_time.*at least 2 samples"):
        compute_frf(
            np.ones(1),
            np.ones(1),
            fs=8.0,
            params=_basic_params(),
            input_time=t,
            output_time=t,
        )


def test_time_axes_must_be_strictly_increasing_and_uniform():
    x, y = _two_segment_pair()
    non_monotonic = np.array([0.0, 0.125, 0.25, 0.20, 0.5, 0.625, 0.75, 0.875])
    with pytest.raises(ValueError, match="input_time.*strictly increasing"):
        compute_frf(
            x,
            y,
            fs=8.0,
            params=_basic_params(),
            input_time=non_monotonic,
            output_time=non_monotonic,
        )

    jittered = np.arange(8, dtype=float) / 8.0
    jittered[4:] += 1e-2
    with pytest.raises(ValueError, match="input_time.*relative_jitter"):
        compute_frf(
            x,
            y,
            fs=8.0,
            params=_basic_params(),
            input_time=jittered,
            output_time=jittered,
        )


def test_input_and_output_time_axes_must_match_point_for_point():
    x, y = _two_segment_pair()
    input_time = np.arange(8, dtype=float) / 8.0
    output_time = input_time + 1e-3
    with pytest.raises(ValueError, match="time axes.*maximum difference"):
        compute_frf(
            x,
            y,
            fs=8.0,
            params=_basic_params(),
            input_time=input_time,
            output_time=output_time,
        )


def test_timebase_facts_record_real_axis_and_measured_jitter():
    x, y = _two_segment_pair()
    t = 10.0 + np.arange(8, dtype=float) / 8.0
    result = compute_frf(
        x,
        y,
        fs=8.0,
        params=_basic_params(),
        input_time=t,
        output_time=t.copy(),
    )
    assert result.effective.time_start == 10.0
    assert result.effective.time_end == 10.875
    assert result.effective.max_time_jitter == pytest.approx(0.0, abs=1e-14)
    assert result.effective.max_time_difference == 0.0


def test_segment_length_below_two_is_rejected_before_window_scaling():
    params = FrfParams(t_win_s=0.01, overlap=0.0)
    with pytest.raises(ValueError, match="segment length.*at least 2"):
        compute_frf(np.ones(8), np.ones(8), fs=8.0, params=params)


def test_zero_window_energy_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "mf4_analyzer.signal.frf.get_frf_window",
        lambda *_args, **_kwargs: np.zeros(4),
    )
    with pytest.raises(ValueError, match="window energy"):
        compute_frf(np.ones(8), np.ones(8), fs=8.0, params=_basic_params())


def test_fewer_than_two_full_segments_is_rejected_without_shortening_window():
    params = FrfParams(t_win_s=1.0, overlap=0.0, detrend="none")
    with pytest.raises(ValueError, match="at least 2 complete segments"):
        compute_frf(np.ones(12), np.ones(12), fs=8.0, params=params)


def test_request_plan_is_the_public_single_source_for_effective_fft_shape():
    params = FrfParams(
        t_win_s=0.5,
        overlap=0.25,
        window="hanning",
        detrend="none",
    )

    plan = plan_frf_request(n_samples=12, fs=8.0, params=params)

    assert plan == FrfRequestPlan(
        requested_nperseg=4,
        nperseg=4,
        noverlap=1,
        hop=3,
        nfft=4,
        frequency_bins=3,
        segments=3,
        complex_temporary_bytes=192,
    )
    result = compute_frf(
        np.arange(12, dtype=float),
        np.arange(12, dtype=float) * 2.0,
        fs=8.0,
        params=params,
    )
    assert result.effective.requested_nperseg == plan.requested_nperseg
    assert result.effective.nperseg == plan.nperseg
    assert result.effective.noverlap == plan.noverlap
    assert result.effective.hop == plan.hop
    assert result.effective.nfft == plan.nfft
    assert result.effective.segments == plan.segments


def test_manual_nfft_rejects_more_than_64_mib_of_complex_temporaries():
    params = _basic_params(nfft_mode="manual", nfft=4_194_304)
    with pytest.raises(ValueError, match="temporary complex.*64 MiB"):
        compute_frf(np.ones(8), np.ones(8), fs=8.0, params=params)


def test_complex_temporary_budget_counts_fft_and_cross_product_buffers(monkeypatch):
    def must_not_reach_fft(*_args, **_kwargs):
        raise AssertionError("memory preflight must run before allocating FFT buffers")

    monkeypatch.setattr(np.fft, "rfft", must_not_reach_fft)
    params = _basic_params(nfft_mode="manual", nfft=2_097_152)
    with pytest.raises(ValueError, match="temporary complex.*64 MiB"):
        compute_frf(np.ones(8), np.ones(8), fs=8.0, params=params)


def test_two_or_three_segments_compute_with_low_stability_warning():
    x, y = _two_segment_pair()
    result = compute_frf(x, y, fs=8.0, params=_basic_params())
    assert result.effective.segments == 2
    assert any("statistical stability" in warning for warning in result.warnings)


def test_full_segment_policy_ignores_incomplete_tail():
    x, y = _two_segment_pair()
    baseline = compute_frf(x, y, fs=8.0, params=_basic_params())
    tailed = compute_frf(
        np.append(x, 12345.0),
        np.append(y, -67890.0),
        fs=8.0,
        params=_basic_params(),
    )
    assert tailed.effective.segments == baseline.effective.segments == 2
    np.testing.assert_array_equal(tailed.pxx, baseline.pxx)
    np.testing.assert_array_equal(tailed.pyy, baseline.pyy)
    np.testing.assert_array_equal(tailed.pxy, baseline.pxy)


def test_hand_checked_even_nfft_psd_csd_h1_and_coherence():
    x, y = _two_segment_pair()
    result = compute_frf(x, y, fs=8.0, params=_basic_params())

    np.testing.assert_array_equal(result.frequencies, np.array([0.0, 2.0, 4.0]))
    np.testing.assert_allclose(result.pxx, np.array([1 / 12, 1 / 6, 1 / 12]))
    np.testing.assert_allclose(result.pyy, np.array([1 / 3, 2 / 3, 1 / 3]))
    np.testing.assert_allclose(result.pxy, np.array([1 / 6, 1 / 3, 1 / 6]))
    np.testing.assert_allclose(result.transfer, 2.0 + 0.0j)
    np.testing.assert_allclose(result.coherence, 1.0)
    assert result.effective.nperseg == 4
    assert result.effective.nfft == 4
    assert result.effective.noverlap == 0
    assert result.effective.hop == 4
    assert result.effective.df == 2.0


def test_hand_checked_odd_nfft_doubles_last_positive_bin():
    x, y = _two_segment_pair()
    result = compute_frf(
        x,
        y,
        fs=8.0,
        params=_basic_params(nfft_mode="manual", nfft=5),
    )
    np.testing.assert_allclose(result.pxx, np.array([1 / 12, 1 / 6, 1 / 6]))


def test_h2_uses_pyy_over_conjugate_pxy():
    x, y = _two_segment_pair()
    result = compute_frf(
        x,
        y,
        fs=8.0,
        params=_basic_params(estimator="h2"),
    )
    np.testing.assert_allclose(result.transfer, 2.0 + 0.0j)


def test_negative_gain_has_unit_magnitude_and_180_degree_phase():
    x, _ = _two_segment_pair()
    result = compute_frf(x, -x, fs=8.0, params=_basic_params())
    np.testing.assert_allclose(magnitude_linear(result.transfer), 1.0)
    phase = phase_wrapped_deg(result.transfer)
    np.testing.assert_allclose(np.abs(phase), 180.0)


def test_integer_delay_has_negative_phase_slope_at_excited_bin():
    fs = 128.0
    frequency = 16.0
    delay_samples = 2
    samples = np.arange(512)
    x = np.sin(2 * np.pi * frequency * samples / fs)
    y = np.sin(2 * np.pi * frequency * (samples - delay_samples) / fs)
    result = compute_frf(
        x,
        y,
        fs=fs,
        params=FrfParams(
            t_win_s=1.0,
            overlap=0.5,
            window="hanning",
            detrend="none",
        ),
    )
    bin_index = int(np.flatnonzero(result.frequencies == frequency)[0])
    assert phase_wrapped_deg(result.transfer)[bin_index] == pytest.approx(-90.0)
    assert magnitude_linear(result.transfer)[bin_index] == pytest.approx(1.0)


@pytest.mark.parametrize("estimator", ["h1", "h2"])
@pytest.mark.parametrize("scale", [1e-12, 1.0, 1e12])
def test_relative_denominator_threshold_is_invariant_to_common_signal_scale(
    scale, estimator
):
    x, y = _two_segment_pair(scale)
    result = compute_frf(
        x,
        y,
        fs=8.0,
        params=_basic_params(estimator=estimator),
    )
    np.testing.assert_allclose(result.transfer, 2.0 + 0.0j, rtol=1e-12, atol=0.0)
    np.testing.assert_allclose(result.coherence, 1.0, rtol=1e-12, atol=0.0)
    assert result.effective.invalid_bins == 0


def test_spectral_overflow_is_observable_instead_of_returning_inf():
    from mf4_analyzer.signal.frf import FrfSpectralOverflow

    segment = 1e308 * np.array([1.0, 0.0, -1.0, 0.0])
    x = np.tile(segment, 2)
    y = x.copy()
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        with pytest.raises(FrfSpectralOverflow, match="spectral accumulation overflow"):
            compute_frf(x, y, fs=8.0, params=_basic_params())
    assert issubclass(FrfSpectralOverflow, ValueError)


@pytest.mark.parametrize("estimator", ["h1", "h2"])
def test_transfer_overflow_bins_become_nan_without_discarding_coherence(estimator):
    # Both spectra and the cross spectrum remain finite, but y/x=1e310 is
    # outside float64. The task stays usable because coherence is scale-free.
    shape = np.tile(np.array([1.0, 0.0, -1.0, 0.0]), 2)
    x = 1e-160 * shape
    y = 1e150 * shape
    result = compute_frf(
        x,
        y,
        fs=8.0,
        params=_basic_params(estimator=estimator),
    )

    assert np.isfinite(result.pxx).all()
    assert np.isfinite(result.pyy).all()
    assert np.isfinite(result.pxy.real).all()
    assert np.isfinite(result.pxy.imag).all()
    assert not np.isinf(result.transfer.real).any()
    assert not np.isinf(result.transfer.imag).any()
    assert np.isnan(result.transfer.real).all()
    assert np.isnan(result.transfer.imag).all()
    assert not np.isinf(magnitude_linear(result.transfer)).any()
    assert not np.isinf(magnitude_db(result.transfer)).any()
    assert np.isfinite(result.coherence).all()
    assert np.all(result.coherence >= 0.0)
    assert np.all(result.coherence <= 1.0)
    assert result.effective.invalid_bins == result.frequencies.size
    assert any(
        "transfer overflow" in warning and "marked invalid" in warning
        for warning in result.warnings
    )


def test_zero_excitation_returns_nan_not_inf_and_reports_invalid_bins():
    result = compute_frf(
        np.zeros(8),
        np.ones(8),
        fs=8.0,
        params=_basic_params(),
    )
    assert not np.isinf(result.transfer.real).any()
    assert not np.isinf(result.transfer.imag).any()
    assert np.isnan(result.transfer.real).all()
    assert np.isnan(result.coherence).all()
    assert result.effective.invalid_bins == result.frequencies.size
    assert any("invalid" in warning for warning in result.warnings)


def test_coherence_is_bounded_for_seeded_noisy_data():
    rng = np.random.default_rng(20260808)
    x = rng.standard_normal(4096)
    y = 0.75 * x + 0.2 * rng.standard_normal(4096)
    result = compute_frf(
        x,
        y,
        fs=1024.0,
        params=FrfParams(t_win_s=0.25, overlap=0.5),
    )
    valid = np.isfinite(result.coherence)
    assert valid.any()
    assert np.all(result.coherence[valid] >= 0.0)
    assert np.all(result.coherence[valid] <= 1.0)


def test_display_helpers_preserve_nan_gaps_and_do_not_mutate_transfer():
    angles = np.deg2rad(np.array([170.0, -170.0, np.nan, 170.0, -170.0]))
    transfer = np.exp(1j * angles)
    transfer[2] = np.nan + 1j * np.nan
    before = transfer.copy()

    np.testing.assert_allclose(magnitude_linear(transfer)[[0, 1, 3, 4]], 1.0)
    assert np.isnan(magnitude_db(transfer)[2])
    assert np.isfinite(magnitude_db(np.array([0.0 + 0.0j]))).all()
    np.testing.assert_allclose(
        phase_unwrapped_deg(transfer),
        np.array([170.0, 190.0, np.nan, 170.0, 190.0]),
        equal_nan=True,
        atol=1e-12,
    )
    np.testing.assert_array_equal(transfer, before)


def test_result_arrays_have_stable_dtype_shape_and_read_only_contract():
    x, y = _two_segment_pair()
    result = compute_frf(x, y, fs=8.0, params=_basic_params())
    arrays = (
        result.frequencies,
        result.pxx,
        result.pyy,
        result.pxy,
        result.transfer,
        result.coherence,
    )
    assert all(array.ndim == 1 for array in arrays)
    assert len({array.shape for array in arrays}) == 1
    assert result.frequencies.dtype == np.float64
    assert result.pxx.dtype == np.float64
    assert result.pyy.dtype == np.float64
    assert result.coherence.dtype == np.float64
    assert result.pxy.dtype == np.complex128
    assert result.transfer.dtype == np.complex128
    assert all(not array.flags.writeable for array in arrays)


def test_cancel_is_polled_per_segment_and_stops_without_final_progress():
    from mf4_analyzer.signal.frf import FrfCancelled

    x = np.tile(np.array([1.0, 0.0, -1.0, 0.0]), 20)
    y = 2.0 * x
    polls = 0
    progress_calls: list[tuple[int, int]] = []

    def cancel_check() -> bool:
        nonlocal polls
        polls += 1
        return polls >= 3

    with pytest.raises(FrfCancelled, match="FRF computation cancelled"):
        compute_frf(
            x,
            y,
            fs=8.0,
            params=_basic_params(),
            cancel_check=cancel_check,
            progress=lambda current, total: progress_calls.append((current, total)),
        )
    assert polls == 3
    assert not progress_calls or progress_calls[-1][0] < progress_calls[-1][1]
    # Subclass of RuntimeError so older adapters that catch RuntimeError still see it.
    assert issubclass(FrfCancelled, RuntimeError)


def test_progress_is_monotonic_throttled_and_finishes_at_total():
    x = np.tile(np.array([1.0, 0.0, -1.0, 0.0]), 120)
    y = 2.0 * x
    calls: list[tuple[int, int]] = []
    result = compute_frf(
        x,
        y,
        fs=8.0,
        params=_basic_params(),
        progress=lambda current, total: calls.append((current, total)),
    )
    assert calls[-1] == (result.effective.segments, result.effective.segments)
    assert calls == sorted(set(calls))
    assert len(calls) <= 51
