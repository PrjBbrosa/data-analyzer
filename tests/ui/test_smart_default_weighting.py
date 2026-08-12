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
            if slot in (1, 2, 3):
                assert "weighting" not in ctx.preset_bar._builtins[slot]["params"]


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


def test_a8_audio_weighting_none_survives_analysis_view_switch(qapp, qtbot):
    """A8: stored weighting=None must survive apply onto an audio source.

    Echoing an audio channel while restoring an analysis View historically
    re-ran the audio A-weighting default and overwrote weighting=None in the
    live Inspector (fan-out to sibling sections) while AnalysisViewState kept
    None — UI/state fork, later capture solidifies A. Loading audio outside
    the apply window must still default to A (covered elsewhere).
    """
    import numpy as np
    import pandas as pd

    from mf4_analyzer.io.file_data import FileData
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    t = np.linspace(0.0, 0.05, 2400)
    df = pd.DataFrame(
        {
            "audio": 0.1 * np.sin(2 * np.pi * 440.0 * t),
            "sig": np.zeros(2400, dtype=float),
        }
    )
    fd = FileData(
        "tone.wav",
        df,
        ["audio", "sig"],
        {"audio": "", "sig": "V"},
        fs=48_000.0,
    )
    fd.is_audio_source = lambda: True
    win.files["audio"] = fd

    win.toolbar._set_mode("fft_time")
    qtbot.wait(10)
    mgr = win.analysis_managers["fft_time"]
    win._on_analysis_new("fft_time")
    qtbot.wait(10)
    assert len(mgr.views) == 2

    v0, v1 = mgr.get(0), mgr.get(1)
    for view in (v0, v1):
        view.attached_file_ids = ["audio"]
    v0.params = dict(win.inspector.fft_time_ctx.current_params())
    v0.params["weighting"] = "None"
    v0.panes[0].sources = [("audio", "audio")]
    v1.params = dict(win.inspector.fft_time_ctx.current_params())
    v1.params["weighting"] = "A"
    v1.panes[0].sources = [("audio", "sig")]

    # Land on the non-audio View first so switching onto v0 re-echoes audio.
    win._on_analysis_view_switched("fft_time", 1, render=False)
    qtbot.wait(10)
    for ctx in (
        win.inspector.fft_ctx,
        win.inspector.fft_time_ctx,
        win.inspector.order_ctx,
    ):
        ctx.set_weighting_default("None")
    v0.params["weighting"] = "None"

    win._on_analysis_view_switched("fft_time", 0, render=False)
    qtbot.wait(10)

    assert v0.params.get("weighting") == "None"
    assert win.inspector.fft_time_ctx.get_params()["weighting"] == "None"
    assert _all_weightings(win) == {
        "fft": "None",
        "fft_time": "None",
        "order": "None",
    }

    # Product semantic: outside the apply window, picking audio still sets A.
    win._on_fft_time_signal_changed(("audio", "audio"))
    assert _all_weightings(win) == {"fft": "A", "fft_time": "A", "order": "A"}
