"""Imported gaps are displayable, but must not become successful spectra."""
import numpy as np
import pytest

from mf4_analyzer.signal.fft import FFTAnalyzer
from mf4_analyzer.signal.order_cot import COTOrderAnalyzer, COTParams
from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer, SpectrogramParams


def _compute(kind, values, time):
    if kind == "fft":
        return FFTAnalyzer.compute_fft(values, 1024, nfft=128)[1]
    if kind == "average":
        return FFTAnalyzer.compute_averaged_fft(values, 1024, nfft=128)[1]
    if kind == "peak":
        return FFTAnalyzer.compute_peak_hold_fft(values, 1024, nfft=128)[1]
    if kind == "spectrogram":
        return SpectrogramAnalyzer.compute(values, time, SpectrogramParams(1024, 128), "A").amplitude
    if kind == "order":
        return COTOrderAnalyzer.compute(values, np.full(values.size, 1200.), time,
                                       COTParams(nfft=128, fs=1024)).amplitude
    from mf4_analyzer.batch_compute import compute_fft_dataframe
    return compute_fft_dataframe(values, 1024, {"nfft": 128})["amplitude"].to_numpy()


@pytest.mark.parametrize("kind", ["fft", "average", "peak", "spectrogram", "order", "batch_fft"])
@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_selected_gap_is_rejected_even_in_an_unused_frame_tail(kind, bad):
    time = np.arange(1025) / 1024
    values = np.sin(2 * np.pi * 32 * time)
    values[-1] = bad
    with pytest.raises(ValueError, match="non-finite"):
        _compute(kind, values, time)


@pytest.mark.parametrize("kind", ["fft", "average", "peak", "spectrogram", "order", "batch_fft"])
def test_finite_selected_interval_of_a_gapped_source_remains_computable(kind):
    time = np.arange(1025) / 1024
    values = np.sin(2 * np.pi * 32 * time)
    values[-1] = np.nan
    result = _compute(kind, values[:-1], time[:-1])
    assert result.size
    assert np.isfinite(result).all()


@pytest.mark.parametrize("kind", ["spectrogram", "order"])
def test_nonfinite_time_is_never_accepted_as_uniform(kind):
    time = np.arange(1024) / 1024
    values = np.sin(2 * np.pi * 32 * time)
    time[100] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        _compute(kind, values, time)


def test_cot_nonfinite_rpm_is_not_a_valid_order_reference():
    time = np.arange(1024) / 1024
    rpm = np.full(1024, 1200.)
    rpm[100] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        COTOrderAnalyzer.compute(np.sin(time), rpm, time, COTParams(nfft=128, fs=1024))
