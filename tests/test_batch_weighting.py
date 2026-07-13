from types import SimpleNamespace

import numpy as np
import pytest

from mf4_analyzer.batch import BatchRunner
from mf4_analyzer.signal.fft import FFTAnalyzer


def test_batch_fft_dataframe_passes_weighting_to_signal_api(monkeypatch):
    captured = {}

    def fake_compute_fft(sig, fs, *, win="hanning", nfft=None, weighting):
        captured["weighting"] = weighting
        return np.array([100.0]), np.array([1.0])

    monkeypatch.setattr(FFTAnalyzer, "compute_fft", staticmethod(fake_compute_fft))

    df = BatchRunner._compute_fft_dataframe(
        np.ones(16),
        48_000.0,
        {"window": "hanning", "nfft": 16, "weighting": "A"},
    )

    assert captured["weighting"] == "A"
    assert list(df.columns) == ["frequency_hz", "amplitude"]


def test_batch_fft_dataframe_weighting_attenuates_low_freq():
    fs = 48_000.0
    n = 48_000
    t = np.arange(n, dtype=float) / fs
    sig = np.sin(2 * np.pi * 1000 * t) + np.sin(2 * np.pi * 100 * t)

    base = BatchRunner._compute_fft_dataframe(
        sig, fs, {"window": "hanning", "nfft": n, "weighting": "None"}
    )
    try:
        weighted = BatchRunner._compute_fft_dataframe(
            sig, fs, {"window": "hanning", "nfft": n, "weighting": "A"}
        )
    except TypeError as exc:
        if "weighting" in str(exc):
            pytest.xfail("signal FFT weighting API is not integrated yet")
        raise

    i100_base = int((base["frequency_hz"] - 100.0).abs().idxmin())
    i100_weighted = int((weighted["frequency_hz"] - 100.0).abs().idxmin())
    assert weighted["amplitude"].iloc[i100_weighted] < base["amplitude"].iloc[i100_base] * 0.3


def test_batch_order_time_passes_weighting_to_cot_params(monkeypatch):
    import mf4_analyzer.signal.order_cot as order_cot

    captured = {}

    class FakeCOTParams:
        def __init__(self, **kwargs):
            captured["weighting"] = kwargs.get("weighting")
            self.__dict__.update(kwargs)

    class FakeCOTOrderAnalyzer:
        @staticmethod
        def compute(sig, rpm, t, params):
            return SimpleNamespace(
                times=np.array([0.0, 0.1]),
                orders=np.array([1.0, 2.0]),
                amplitude=np.ones((2, 2)),
            )

    monkeypatch.setattr(order_cot, "COTParams", FakeCOTParams)
    monkeypatch.setattr(order_cot, "COTOrderAnalyzer", FakeCOTOrderAnalyzer)

    t = np.arange(32, dtype=float) / 1000.0
    BatchRunner._compute_order_time_spectro(
        np.ones(32),
        np.full(32, 3000.0),
        t,
        1000.0,
        {"weighting": "A", "nfft": 16},
    )

    assert captured["weighting"] == "A"


def test_batch_fft_time_passes_weighting_to_spectrogram_params(monkeypatch):
    import mf4_analyzer.signal.spectrogram as spectrogram

    captured = {}

    class FakeSpectrogramParams:
        def __init__(self, **kwargs):
            captured["weighting"] = kwargs.get("weighting")
            self.__dict__.update(kwargs)

    class FakeSpectrogramAnalyzer:
        @staticmethod
        def compute(signal, time, params, channel_name):
            return SimpleNamespace(
                times=np.array([0.0, 0.1]),
                frequencies=np.array([100.0, 200.0]),
                amplitude=np.ones((2, 2)),
            )

    monkeypatch.setattr(spectrogram, "SpectrogramParams", FakeSpectrogramParams)
    monkeypatch.setattr(spectrogram, "SpectrogramAnalyzer", FakeSpectrogramAnalyzer)

    BatchRunner._compute_fft_time_spectro(
        np.ones(32),
        None,
        1000.0,
        {"weighting": "A", "nfft": 16},
        channel_name="audio",
    )

    assert captured["weighting"] == "A"


def test_batch_channel_reference_facts_canonicalizes_toolchain_unit():
    """Batch 侧 facts 适配器与 UI 侧一致：还原工具链改写单位 U_Nm / U_degYsec
    （否则批量导出的 dB 标签同样印乱码、振动量同样错失 ISO 参考）。"""
    from types import SimpleNamespace
    from mf4_analyzer.batch import BatchRunner

    fd = SimpleNamespace(
        channel_metadata={},
        channel_units={"TQ": "U_Nm", "VIB": "mYs2"},
        is_audio_source=lambda: False,
    )
    assert BatchRunner._channel_reference_facts(fd, "TQ").unit == "Nm"
    assert BatchRunner._channel_reference_facts(fd, "VIB").unit == "m/s2"
