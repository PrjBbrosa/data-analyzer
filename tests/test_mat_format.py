"""MATLAB .mat 解析：真实样本锚点 + 端到端 + 错误路径。

锚点值来自 scipy 对 ``testdoc/175rpm_-45deg-270tighten.mat`` 的分析——改动变量
筛选 / 时间轴识别 / 分组会在这里翻红。
"""
from __future__ import annotations
from pathlib import Path

import numpy as np
import pytest

from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.io.loader import DataLoader

_ROOT = Path(__file__).resolve().parent.parent
SAMPLE = _ROOT / "testdoc" / "175rpm_-45deg-270tighten.mat"


def _sample():
    if not SAMPLE.exists():
        pytest.skip(f"sample not found: {SAMPLE}")
    return str(SAMPLE)


# 通道 -> (first, min, max)
_ANCHORS = {
    "A1___angle": (-0.043936, -0.043936, 44100.0),
    "A2___Load_Torque": (1.8551, -0.00037216, 70.0),
    "E1___M_Lsp_1": (0.068359, -4.0137, 4.1113),
    "E3___Load_Torque": (1.5625, -73.34, 73.047),
    "E17__angle": (-0.043945, -120.23, 44220.0),
}


def test_mat_single_group_five_channels_anchors():
    groups = DataLoader.load_mat(_sample())
    assert len(groups) == 1
    g = groups[0]
    assert g["label_suffix"] == ""

    # Time 存在，t 变量不作为信号列
    assert "Time" in g["channels"]
    assert "t" not in g["channels"]
    signal_cols = [c for c in g["channels"] if c != "Time"]
    assert len(signal_cols) == 5
    assert set(signal_cols) == set(_ANCHORS)

    # 时间轴 1000 Hz / 284988 点，均匀
    t = g["data"]["Time"].to_numpy()
    assert len(t) == 284988
    assert t[0] == pytest.approx(0.0)
    assert t[-1] == pytest.approx(284.987, abs=1e-3)
    assert t[1] - t[0] == pytest.approx(0.001, abs=1e-6)

    for col, (first, vmin, vmax) in _ANCHORS.items():
        v = g["data"][col].to_numpy()
        assert v[0] == pytest.approx(first, rel=1e-3, abs=1e-4), f"{col} first"
        assert v.min() == pytest.approx(vmin, rel=1e-3, abs=1e-4), f"{col} min"
        assert v.max() == pytest.approx(vmax, rel=1e-3), f"{col} max"
        assert g["units"][col] == ""

    smeta = g["source_metadata"]
    assert smeta["source_kind"] == "mat"
    assert smeta["source_filename"] == "175rpm_-45deg-270tighten.mat"
    assert smeta["skipped_vars"] == []
    assert smeta["mat_version"]      # 非空（v4）

    assert g["channel_metadata"]["A1___angle"]["mat_variable"] == "A1___angle"


def test_mat_end_to_end_filedata_column_time_source():
    groups = DataLoader.load_mat(_sample())
    g = groups[0]
    fd = FileData(_sample(), g["data"], g["channels"], g["units"], 0,
                  source_metadata=g["source_metadata"],
                  channel_metadata=g["channel_metadata"],
                  label_suffix=g["label_suffix"])
    assert fd._time_source == "column"      # Time 列被识别
    assert fd.fs == pytest.approx(1000.0, rel=1e-6)
    ta = fd.time_array
    assert ta is not None and len(ta) == 284988
    diffs = np.diff(ta)
    np.testing.assert_allclose(diffs, diffs[0], rtol=1e-6)


def test_non_mat_content_rejected(tmp_path):
    p = tmp_path / "junk.mat"
    p.write_bytes(b"this is definitely not a MAT file\n" * 8)
    with pytest.raises(ValueError, match="无法读取 .mat"):
        DataLoader.load_mat(str(p))
