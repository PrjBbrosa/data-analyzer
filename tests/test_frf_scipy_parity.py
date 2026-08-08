"""Optional SciPy reference checks for the NumPy-only FRF implementation."""

from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.signal.frf import FrfParams, compute_frf, get_frf_window


scipy_signal = pytest.importorskip("scipy.signal")


@pytest.mark.parametrize(
    "name",
    ["hanning", "hann", "hamming", "blackman", "bartlett", "kaiser", "flattop"],
)
def test_all_exposed_periodic_windows_match_scipy_fftbins_true(name):
    scipy_name = "hann" if name in {"hanning", "hann"} else name
    scipy_spec = ("kaiser", 14.0) if name == "kaiser" else scipy_name
    expected = scipy_signal.get_window(scipy_spec, 31, fftbins=True)
    np.testing.assert_allclose(
        get_frf_window(name, 31, periodic=True),
        expected,
        rtol=1e-13,
        atol=1e-15,
    )


@pytest.mark.parametrize(
    "name", ["hanning", "hamming", "blackman", "bartlett", "kaiser", "flattop"]
)
@pytest.mark.parametrize("periodic", [True, False])
def test_all_single_sample_windows_match_scipy(name, periodic):
    scipy_name = "hann" if name == "hanning" else name
    scipy_spec = ("kaiser", 14.0) if name == "kaiser" else scipy_name
    expected = scipy_signal.get_window(scipy_spec, 1, fftbins=periodic)
    np.testing.assert_array_equal(
        get_frf_window(name, 1, periodic=periodic),
        expected,
    )


@pytest.mark.parametrize("estimator", ["h1", "h2"])
@pytest.mark.parametrize("nfft", [256, 257])
def test_seeded_psd_csd_transfer_and_coherence_match_explicit_scipy_reference(
    estimator, nfft
):
    rng = np.random.default_rng(20260808)
    x = rng.standard_normal(4096)
    y = np.empty_like(x)
    y[0] = 0.0
    y[1:] = 0.8 * x[1:] + 0.25 * x[:-1]
    fs = 1024.0
    nperseg = 256
    noverlap = 128
    window = get_frf_window("hanning", nperseg)
    detrend = "constant"

    params = FrfParams(
        estimator=estimator,
        t_win_s=nperseg / fs,
        overlap=noverlap / nperseg,
        nfft_mode="manual",
        nfft=nfft,
        window="hanning",
        detrend=detrend,
    )
    result = compute_frf(x, y, fs=fs, params=params)

    common = dict(
        fs=fs,
        window=window,
        nperseg=nperseg,
        noverlap=noverlap,
        nfft=nfft,
        detrend=detrend,
        return_onesided=True,
        scaling="density",
        axis=-1,
    )
    frequencies, pxx = scipy_signal.welch(x, **common)
    _, pyy = scipy_signal.welch(y, **common)
    _, pxy = scipy_signal.csd(x, y, **common)
    _, coherence = scipy_signal.coherence(
        x,
        y,
        fs=fs,
        window=window,
        nperseg=nperseg,
        noverlap=noverlap,
        nfft=nfft,
        detrend=detrend,
        axis=-1,
    )
    transfer = pxy / pxx if estimator == "h1" else pyy / np.conjugate(pxy)

    valid = np.isfinite(result.transfer)
    assert valid.any()
    np.testing.assert_allclose(result.frequencies, frequencies, rtol=0.0, atol=0.0)
    np.testing.assert_allclose(result.pxx, pxx, rtol=1e-10, atol=1e-12)
    np.testing.assert_allclose(result.pyy, pyy, rtol=1e-10, atol=1e-12)
    np.testing.assert_allclose(result.pxy, pxy, rtol=1e-10, atol=1e-12)
    np.testing.assert_allclose(
        result.transfer[valid], transfer[valid], rtol=1e-10, atol=1e-12
    )
    np.testing.assert_allclose(
        result.coherence[np.isfinite(result.coherence)],
        coherence[np.isfinite(result.coherence)],
        rtol=1e-10,
        atol=1e-12,
    )
