"""GUI Welch clamping keeps visible facts without duplicate runtime warnings."""

import warnings

import numpy as np
import pytest

from mf4_analyzer.signal.fft import FFTAnalyzer
from mf4_analyzer.ui.main_window._fft_mixin import FFTMixin


PARAMS = {
    "window": "hanning",
    "nfft": 2048,
    "avg_mode": "线性平均",
    "avg_overlap": 50,
}


@pytest.mark.parametrize("n_samples", [0, 1, 1280, 1281, 4096])
def test_gui_welch_uses_real_segment_without_duplicate_warning(n_samples):
    fs = 1000.0
    sig = np.sin(2 * np.pi * 40 * np.arange(n_samples) / fs)
    if 0 < n_samples < PARAMS["nfft"]:
        with pytest.warns(UserWarning, match="frequency resolution clamped"):
            expected = FFTAnalyzer.compute_averaged_fft(sig, fs, nfft=2048)
    else:
        expected = FFTAnalyzer.compute_averaged_fft(sig, fs, nfft=2048)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = FFTMixin()._fft_compute_arrays(sig, fs, PARAMS)

    assert not caught
    for actual, reference in zip(result, expected):
        np.testing.assert_array_equal(actual, reference)
    if n_samples == 0:
        assert result.effective is None
        return
    facts = result.effective
    actual_nfft = min(2048, n_samples)
    assert facts.nfft_requested == 2048
    assert facts.nfft == actual_nfft
    assert facts.df == pytest.approx(fs / actual_nfft)
    assert facts.window_s == pytest.approx(actual_nfft / fs)
    assert facts.shortened == (n_samples < 2048)
    if len(result[0]) > 1:
        assert facts.df == pytest.approx(result[0][1] - result[0][0])


def test_gui_welch_does_not_hide_unrelated_analyzer_warning(monkeypatch):
    compute = FFTAnalyzer.compute_averaged_fft

    def warning_compute(*args, **kwargs):
        warnings.warn("unrelated analyzer warning", UserWarning)
        return compute(*args, **kwargs)

    monkeypatch.setattr(FFTAnalyzer, "compute_averaged_fft", warning_compute)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        FFTMixin()._fft_compute_arrays(np.ones(1281), 1000.0, PARAMS)
    assert [str(item.message) for item in caught] == ["unrelated analyzer warning"]


def test_real_short_signal_result_reaches_fft_facts_card(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTContextual

    result = FFTMixin()._fft_compute_arrays(np.ones(1281), 1000.0, PARAMS)
    ctx = FFTContextual()
    qtbot.addWidget(ctx)
    ctx.set_effective_facts(result.effective, ())

    assert "2048 → 1281" in ctx.effective_facts_text()
    assert f"{1000 / 1281:g} Hz" in ctx.effective_facts_text()
    assert "请求 NFFT 2048，仅能提供 1281" in ctx.effective_warnings_text()
    assert ctx.lbl_effective_facts.isVisibleTo(ctx)
    assert ctx.lbl_effective_warnings.isVisibleTo(ctx)


def test_zero_padded_single_frame_facts_keep_real_window(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTContextual

    params = {
        "window": "hanning",
        "nfft": 4096,
        "avg_mode": "单帧",
        "avg_overlap": 0,
    }
    result = FFTMixin()._fft_compute_arrays(np.ones(1000), 1000.0, params)
    facts = result.effective
    assert facts.nfft == 4096
    assert facts.window_samples == 1000
    assert facts.window_s == pytest.approx(1.0)
    assert facts.df == pytest.approx(1000.0 / 4096.0)

    ctx = FFTContextual()
    qtbot.addWidget(ctx)
    ctx.set_effective_facts(facts, ())
    text = ctx.effective_facts_text()
    assert "频率 bin 间隔 Δf" in text
    assert "1 s" in text
    assert "4.096" not in text
    assert "1000 → 4096" in text
