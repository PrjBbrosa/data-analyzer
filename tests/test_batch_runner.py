from __future__ import annotations

import numpy as np
import pandas as pd

from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
from mf4_analyzer.io import FileData


def _make_file(tmp_path, fs=1024.0):
    n = 2048
    t = np.arange(n, dtype=float) / fs
    rpm = np.full(n, 3072.0)
    sig = np.sin(2 * np.pi * 102.4 * t)
    df = pd.DataFrame({"Time": t, "sig": sig, "rpm": rpm})
    path = tmp_path / "sample.csv"
    df.to_csv(path, index=False)
    return FileData(path, df, list(df.columns), {}, idx=0)


def test_current_single_fft_preset_exports_data(tmp_path):
    fd = _make_file(tmp_path)
    preset = AnalysisPreset.from_current_single(
        name="current fft",
        method="fft",
        signal=(1, "sig"),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert len(result.items) == 1
    assert result.items[0].data_path is not None
    data = pd.read_csv(result.items[0].data_path)
    assert list(data.columns) == ["frequency_hz", "amplitude"]


def test_current_single_fft_preset_exports_image(tmp_path):
    fd = _make_file(tmp_path)
    preset = AnalysisPreset.from_current_single(
        name="current fft image",
        method="fft",
        signal=(1, "sig"),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
        outputs=BatchOutput(export_data=False, export_image=True),
    )

    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert result.items[0].image_path is not None
    assert result.items[0].image_path.endswith(".png")


def test_free_config_order_track_preset_selects_matching_signals(tmp_path):
    fd = _make_file(tmp_path)
    preset = AnalysisPreset.free_config(
        name="track all sig",
        method="order_track",
        signal_pattern="sig",
        rpm_channel="rpm",
        params={"fs": 1024.0, "target_order": 2.0, "nfft": 1024},
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert len(result.items) == 1
    data = pd.read_csv(result.items[0].data_path)
    assert list(data.columns) == ["rpm", "amplitude"]
