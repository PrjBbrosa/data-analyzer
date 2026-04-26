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


def test_current_single_fft_preset_handles_auto_nfft(tmp_path):
    """preset 中 nfft='自动' 应被当作 None 处理（与 inspector 控件一致）。"""
    fd = _make_file(tmp_path)
    preset = AnalysisPreset.from_current_single(
        name="auto nfft",
        method="fft",
        signal=(1, "sig"),
        params={"fs": 1024.0, "window": "hanning", "nfft": "自动"},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")
    assert result.status == "done"
    assert result.items[0].data_path is not None


def test_matrix_to_long_dataframe_vectorize_shape(tmp_path):
    from mf4_analyzer.batch import _matrix_to_long_dataframe
    x = np.arange(5, dtype=float)
    y = np.arange(3, dtype=float) * 0.1
    matrix = np.arange(15, dtype=float).reshape(5, 3)
    df = _matrix_to_long_dataframe(x, y, matrix, x_name='time', y_name='order')
    assert len(df) == 15
    assert list(df.columns) == ['time', 'order', 'amplitude']
    # 前三行：x=0, y∈{0, 0.1, 0.2}
    assert df.iloc[0]['time'] == 0.0
    assert df.iloc[2]['amplitude'] == 2.0
    # 第 4 行：x=1, y=0
    assert df.iloc[3]['time'] == 1.0
    assert df.iloc[3]['amplitude'] == 3.0


def test_analysis_preset_replace_after_frozen_removed(tmp_path):
    """`AnalysisPreset` 去 frozen 后，`dataclasses.replace` 必须继续工作
    （`BatchSheet.get_preset` 依赖此行为）。"""
    from dataclasses import replace
    fd = _make_file(tmp_path)
    p = AnalysisPreset.from_current_single(
        name="orig", method="fft", signal=(1, "sig"),
        params={"fs": 1024.0, "nfft": 1024},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    p2 = replace(p, outputs=BatchOutput(export_data=False, export_image=True))
    assert p2.outputs.export_image is True
    assert p2.outputs.export_data is False
    assert p2.name == "orig"
    assert p.outputs.export_data is True   # 原 preset 不被修改


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


def test_batch_order_time_csv_shape(tmp_path):
    fd = _make_file(tmp_path)
    preset = AnalysisPreset.free_config(
        name="order time batch",
        method="order_time",
        signal_pattern="sig",
        rpm_channel="rpm",
        params={"fs": 1024.0, "nfft": 512, "max_order": 5.0,
                "order_res": 0.5, "time_res": 0.05},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")
    assert result.status == "done"
    df = pd.read_csv(result.items[0].data_path)
    assert list(df.columns) == ["time_s", "order", "amplitude"]
    assert len(df) > 0
