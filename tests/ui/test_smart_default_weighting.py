import inspect
import wave
from types import SimpleNamespace

import numpy as np
import pytest


def _fake_file(*, fs=48_000.0, audio=False):
    def _is_audio_source():
        return audio

    return SimpleNamespace(
        fs=fs,
        channel_units={"audio": "", "sig": "V"},
        is_audio_source=_is_audio_source,
    )


def _all_weightings(win):
    return {
        "fft": win.inspector.fft_ctx.get_params()["weighting"],
        "fft_time": win.inspector.fft_time_ctx.get_params()["weighting"],
        "order": win.inspector.order_ctx.get_params()["weighting"],
    }


def test_audio_signal_selection_enables_a_weighting_for_fft_and_order_paths(
    qapp, qtbot
):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.files["audio"] = _fake_file(audio=True)

    win._on_inspector_signal_changed("fft", ("audio", "audio"))
    assert _all_weightings(win) == {"fft": "A", "fft_time": "A", "order": "A"}

    for ctx in (
        win.inspector.fft_ctx,
        win.inspector.fft_time_ctx,
        win.inspector.order_ctx,
    ):
        ctx.set_weighting_default("None")

    win._on_inspector_signal_changed("order", ("audio", "audio"))
    assert _all_weightings(win) == {"fft": "A", "fft_time": "A", "order": "A"}


def test_audio_signal_selection_enables_a_weighting_for_fft_time_path(
    qapp, qtbot
):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.files["audio"] = _fake_file(audio=True)

    win._on_fft_time_signal_changed(("audio", "audio"))

    assert _all_weightings(win) == {"fft": "A", "fft_time": "A", "order": "A"}


def test_audio_source_builtin_presets_keep_a_weighting_across_all_sections(
    qapp, qtbot
):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.files["audio"] = _fake_file(audio=True)

    win._on_inspector_signal_changed("fft", ("audio", "audio"))

    contexts = (
        win.inspector.fft_ctx,
        win.inspector.fft_time_ctx,
        win.inspector.order_ctx,
    )
    for ctx in contexts:
        for slot in ctx.preset_bar.SLOTS:
            ctx.preset_bar._load(slot)
            assert ctx.get_params()["weighting"] == "A"


def test_non_audio_signal_selection_leaves_weighting_untouched(qapp, qtbot):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.files["plain"] = _fake_file(audio=False)

    win.inspector.fft_ctx.set_weighting_default("None")
    win.inspector.fft_time_ctx.set_weighting_default("A")
    win.inspector.order_ctx.set_weighting_default("None")

    win._on_inspector_signal_changed("fft", ("plain", "sig"))
    assert _all_weightings(win) == {
        "fft": "None",
        "fft_time": "A",
        "order": "None",
    }

    win._on_fft_time_signal_changed(("plain", "sig"))
    assert _all_weightings(win) == {
        "fft": "None",
        "fft_time": "A",
        "order": "None",
    }


def _write_mono_wav(path, fs, samples):
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(fs)
        handle.writeframes(pcm.tobytes())


def test_load_one_registers_wav_as_audio_source_with_fs(qapp, qtbot, tmp_path):
    pytest.importorskip("av")
    from mf4_analyzer.io import DataLoader, FileData
    from mf4_analyzer.ui.main_window import MainWindow

    if not hasattr(DataLoader, "load_audio_video"):
        pytest.skip("DataLoader.load_audio_video is not merged yet")
    if "fs" not in inspect.signature(FileData).parameters:
        pytest.skip("FileData(fs=...) is not merged yet")
    if not hasattr(FileData, "is_audio_source"):
        pytest.skip("FileData.is_audio_source() is not merged yet")

    fs = 48_000
    n = 2_400
    t = np.arange(n, dtype=float) / fs
    path = tmp_path / "tone.wav"
    _write_mono_wav(path, fs, 0.25 * np.sin(2 * np.pi * 1000 * t))

    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(str(path))

    assert len(win.files) == 1
    fd = next(iter(win.files.values()))
    assert fd.is_audio_source() is True
    assert fd.fs == pytest.approx(float(fs))
    assert "audio" in fd.channels
    assert _all_weightings(win) == {"fft": "A", "fft_time": "A", "order": "A"}
