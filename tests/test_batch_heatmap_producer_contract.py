from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from mf4_analyzer.batch import BatchRunner


def test_order_time_spectro_preserves_analyzer_coverage_metadata(monkeypatch):
    from mf4_analyzer.signal.order_cot import COTOrderAnalyzer

    times = np.asarray([0.25, 0.80, 1.65])
    orders = np.asarray([1.0, 2.0])
    amplitude = np.asarray(
        [
            [11.0, 12.0],
            [21.0, 22.0],
            [31.0, 32.0],
        ]
    )
    metadata = {
        "coverage_start": 0.0,
        "coverage_end": 2.0,
        "window_samples": 64,
    }

    monkeypatch.setattr(
        COTOrderAnalyzer,
        "compute",
        staticmethod(
            lambda *_args, **_kwargs: SimpleNamespace(
                times=times,
                orders=orders,
                amplitude=amplitude,
                metadata=metadata,
            )
        ),
    )

    payload = BatchRunner._compute_order_time_spectro(
        np.ones(128),
        np.full(128, 1200.0),
        np.arange(128, dtype=float) / 100.0,
        100.0,
        {
            "samples_per_rev": 64,
            "nfft": 64,
            "max_order": 2.0,
            "order_res": 1.0,
            "time_res": 0.1,
        },
    )

    np.testing.assert_array_equal(payload.x, times)
    np.testing.assert_array_equal(payload.y, orders)
    np.testing.assert_array_equal(payload.matrix, amplitude)
    assert payload.metadata == metadata
    assert payload.metadata is not metadata


def test_fft_time_spectro_preserves_coverage_while_normalizing_orientation(
    monkeypatch,
):
    from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer

    times = np.asarray([0.25, 0.75, 1.25])
    frequencies = np.asarray([0.0, 50.0])
    # Analyzer-native FFT-vs-Time orientation is (frequency, frame).
    amplitude = np.asarray(
        [
            [11.0, 21.0, 31.0],
            [12.0, 22.0, 32.0],
        ]
    )
    metadata = {
        "coverage_start": 0.0,
        "coverage_end": 1.5,
        "window_samples": 64,
    }

    monkeypatch.setattr(
        SpectrogramAnalyzer,
        "compute",
        staticmethod(
            lambda **_kwargs: SimpleNamespace(
                times=times,
                frequencies=frequencies,
                amplitude=amplitude,
                metadata=metadata,
            )
        ),
    )

    payload = BatchRunner._compute_fft_time_spectro(
        np.ones(128),
        np.arange(128, dtype=float) / 100.0,
        100.0,
        {"nfft": 64, "overlap": 0.5},
        channel_name="sig",
    )

    np.testing.assert_array_equal(payload.x, times)
    np.testing.assert_array_equal(payload.y, frequencies)
    np.testing.assert_array_equal(payload.matrix, amplitude.T)
    assert payload.metadata == metadata
    assert payload.metadata is not metadata
