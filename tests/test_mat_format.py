"""MATLAB .mat 解析：真实样本锚点 + 可移植合成 oracle + 错误路径。

真实锚点来自 scipy 对注册样本 ``exporttowwt/175rpm_-45deg-270tighten.mat``
的分析——改动变量筛选 / 时间轴识别 / 分组会在这里翻红。默认套件跑合成
数值/时间轴，不依赖客户文件。额外语料不得靠 glob 改变默认工作量。
"""
from __future__ import annotations

import pytest
import numpy as np

from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.io.loader import DataLoader
from tests.realfile_corpus import CorpusSupplyError, resolve_realfile_sample


def _mat_sample():
    try:
        return resolve_realfile_sample("mat-175rpm-tighten")
    except CorpusSupplyError as exc:
        if exc.optional:
            pytest.skip(str(exc))
        pytest.fail(str(exc))


def test_mat_synthetic_time_axis_and_numeric_oracles(tmp_path):
    from scipy.io import savemat

    n = 1000
    dt = 0.002
    t = np.arange(n, dtype=np.float64) * dt
    torque = 3.5 * t + 0.25
    angle = np.sin(2 * np.pi * 4.0 * t)
    path = tmp_path / "synth.mat"
    savemat(str(path), {"t": t, "Torque": torque, "Angle": angle})

    groups = DataLoader.load_mat(str(path))
    assert len(groups) == 1
    g = groups[0]
    assert g["label_suffix"] == ""
    assert "Time" in g["channels"]
    assert "t" not in g["channels"]
    signal_cols = [c for c in g["channels"] if c != "Time"]
    assert set(signal_cols) == {"Torque", "Angle"}
    got_t = g["data"]["Time"].to_numpy()
    np.testing.assert_allclose(got_t, t, rtol=0, atol=0)
    assert got_t[1] - got_t[0] == pytest.approx(dt)
    np.testing.assert_allclose(g["data"]["Torque"].to_numpy(), torque, rtol=0, atol=0)
    np.testing.assert_allclose(g["data"]["Angle"].to_numpy(), angle, rtol=0, atol=0)
    fd = FileData(
        str(path), g["data"], g["channels"], g["units"], 0,
        source_metadata=g["source_metadata"],
        channel_metadata=g["channel_metadata"],
        label_suffix=g["label_suffix"],
    )
    assert fd._time_source == "column"
    assert fd.fs == pytest.approx(1.0 / dt, rel=1e-9)
    assert len(fd.time_array) == n


def test_mat_single_group_five_channels_anchors():
    entry, path = _mat_sample()
    groups = DataLoader.load_mat(str(path))
    assert len(groups) == 1
    g = groups[0]
    assert g["label_suffix"] == ""

    anchors = {name: tuple(vals) for name, vals in entry["anchors"].items()}
    assert "Time" in g["channels"]
    assert "t" not in g["channels"]
    signal_cols = [c for c in g["channels"] if c != "Time"]
    assert len(signal_cols) == 5
    assert set(signal_cols) == set(anchors)

    t = g["data"]["Time"].to_numpy()
    assert len(t) == entry["sample_count"]
    assert t[0] == pytest.approx(0.0)
    assert t[-1] == pytest.approx(entry["t_end"], abs=1e-3)
    assert t[1] - t[0] == pytest.approx(entry["dt"], abs=1e-6)

    for col, (first, vmin, vmax) in anchors.items():
        v = g["data"][col].to_numpy()
        assert v[0] == pytest.approx(first, rel=1e-3, abs=1e-4), f"{col} first"
        assert v.min() == pytest.approx(vmin, rel=1e-3, abs=1e-4), f"{col} min"
        assert v.max() == pytest.approx(vmax, rel=1e-3), f"{col} max"
        assert g["units"][col] == ""

    smeta = g["source_metadata"]
    assert smeta["source_kind"] == "mat"
    assert smeta["source_filename"] == path.name
    assert smeta["skipped_vars"] == []
    assert smeta["mat_version"]

    assert g["channel_metadata"]["A1___angle"]["mat_variable"] == "A1___angle"


def test_mat_end_to_end_filedata_column_time_source():
    entry, path = _mat_sample()
    groups = DataLoader.load_mat(str(path))
    g = groups[0]
    fd = FileData(str(path), g["data"], g["channels"], g["units"], 0,
                  source_metadata=g["source_metadata"],
                  channel_metadata=g["channel_metadata"],
                  label_suffix=g["label_suffix"])
    assert fd._time_source == "column"
    assert fd.fs == pytest.approx(1000.0, rel=1e-6)
    ta = fd.time_array
    assert ta is not None and len(ta) == entry["sample_count"]
    diffs = np.diff(ta)
    np.testing.assert_allclose(diffs, diffs[0], rtol=1e-6)


def test_non_mat_content_rejected(tmp_path):
    p = tmp_path / "junk.mat"
    p.write_bytes(b"this is definitely not a MAT file\n" * 8)
    with pytest.raises(ValueError, match="无法读取 .mat"):
        DataLoader.load_mat(str(p))
