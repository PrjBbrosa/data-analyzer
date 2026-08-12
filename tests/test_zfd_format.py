"""ZFGE2 .zfd 解析（ZwickRoell/TestRunPRO）：真实样本锚点 + 端到端 + 错误路径。

锚点值来自逆向规格里对 ``testdoc/wwt/end of travel_1.zfd`` 的人工验证——改动
marker 发现 / 数据起点偏移 / float32 解码会在这里翻红。
"""
from __future__ import annotations
from pathlib import Path

import numpy as np
import pytest

from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.io.loader import DataLoader

_ROOT = Path(__file__).resolve().parent.parent
SAMPLE = _ROOT / "testdoc" / "wwt" / "end of travel_1.zfd"


def _sample():
    if not SAMPLE.exists():
        pytest.skip(f"sample not found: {SAMPLE}")
    return str(SAMPLE)


# marker 名字/单位 -> (first, min, max)
_ANCHORS = {
    "Szyl 1": ("mm", -83.773, -83.773, 76.897),      # A2（首列保原名）
    "Fcyl 1": ("kN", -0.00055, -0.069, 66.799),
    "U_Batt": ("V", 13.714, 13.249, 17.648),
    "Szyl 1 [E5]": ("mm", -83.761, -83.85, 78.087),  # E5 消歧列
    "I_Battary": ("", -0.066, -0.215, -0.0011),
    "travel": ("mm", 83.177, -82.369, 83.177),
    "travel speed": ("", 1.378, 0.351, 377.29),
}


def test_zfd_single_group_seven_channels_anchors():
    groups = DataLoader.load_zfd(_sample())
    assert len(groups) == 1
    g = groups[0]
    assert g["label_suffix"] == ""

    # 时间轴 1000 Hz / 7487 点
    t = g["data"]["Time"].to_numpy()
    assert len(t) == 7487
    assert t[0] == pytest.approx(0.0)
    assert t[1] - t[0] == pytest.approx(0.001)     # fs = 1000 Hz

    signal_cols = [c for c in g["channels"] if c != "Time"]
    assert len(signal_cols) == 7                    # 正好 7 个通道

    # 两个 Szyl 1 都在（消歧后不同列名）
    assert "Szyl 1" in g["channels"]
    assert "Szyl 1 [E5]" in g["channels"]

    for col, (unit, first, vmin, vmax) in _ANCHORS.items():
        assert col in g["channels"], col
        v = g["data"][col].to_numpy()
        assert v[0] == pytest.approx(first, abs=1e-2), f"{col} first"
        assert v.min() == pytest.approx(vmin, abs=1e-2), f"{col} min"
        assert v.max() == pytest.approx(vmax, abs=1e-2), f"{col} max"
        assert g["units"][col] == unit, f"{col} unit"

    smeta = g["source_metadata"]
    assert smeta["source_kind"] == "zfd"
    assert smeta["title"] == "End of Travel"
    assert "TestRunPRO Data V15532" in smeta["version"]
    assert smeta["source_filename"] == "end of travel_1.zfd"
    assert smeta["fs_estimated"] is False          # dt 真实读到

    # channel_metadata 存 marker id / 单位 / 显示范围
    cm = g["channel_metadata"]["travel"]
    assert cm["marker_id"] == "E17"
    assert cm["unit"] == "mm"
    assert "display_min" in cm and "display_max" in cm
    assert g["channel_metadata"]["Szyl 1 [E5]"]["marker_id"] == "E5"


def test_zfd_end_to_end_filedata_uniform_time_axis():
    groups = DataLoader.load_zfd(_sample())
    g = groups[0]
    fd = FileData(_sample(), g["data"], g["channels"], g["units"], 0,
                  source_metadata=g["source_metadata"],
                  channel_metadata=g["channel_metadata"],
                  label_suffix=g["label_suffix"])
    ta = fd.time_array
    assert ta is not None and len(ta) == 7487
    # 均匀时间轴
    diffs = np.diff(ta)
    np.testing.assert_allclose(diffs, diffs[0], rtol=1e-9)
    assert diffs[0] == pytest.approx(0.001)
    assert fd.fs == pytest.approx(1000.0, rel=1e-6)


def test_non_zfge2_magic_rejected(tmp_path):
    p = tmp_path / "junk.zfd"
    p.write_bytes(b"NOTZF\nfoo\nbar\n" + b"\x00" * 200)
    with pytest.raises(ValueError, match="不是有效的 ZFD"):
        DataLoader.load_zfd(str(p))


def _write_minimal_zfd(path: Path, *, dt: float, count: int = 8,
                       values=None, name: str = "temp", unit: str = "C",
                       marker: str = "E1") -> Path:
    """Construct a one-channel ZFGE2 file with an explicit first-channel dt.

    Layout matches ``zfd_format``: text header, then
    ``float64 dt + u16×3 pre-header + marker/unit lines + pad + disp + f32[count]``.
    """
    import struct

    samples = list(range(count)) if values is None else list(values)
    if len(samples) != count:
        raise ValueError("values length must equal count")
    header = b"ZFGE2\nTestRunPRO Data V1\nSlow Sample\n~\n"
    pre = struct.pack("<dHHH", float(dt), 4, int(count), 0)
    marker_line = f"{marker}: {name}\n".encode("latin-1")
    unit_line = f"{unit}\n".encode("latin-1")
    pad = b"\x00\x00"
    disp = struct.pack("<dd", float(min(samples)), float(max(samples)))
    body = np.asarray(samples, dtype="<f4").tobytes()
    path.write_bytes(header + pre + marker_line + unit_line + pad + disp + body)
    return path


def test_zfd_slow_sample_dt_two_seconds_keeps_half_hz(tmp_path):
    """A4: dt=2.0 (0.5 Hz) must not be crushed into the 1 kHz estimate."""
    p = _write_minimal_zfd(tmp_path / "slow.zfd", dt=2.0, count=5,
                           values=[1.0, 2.0, 3.0, 4.0, 5.0])
    groups = DataLoader.load_zfd(str(p))
    assert len(groups) == 1
    g = groups[0]
    t = g["data"]["Time"].to_numpy()
    assert len(t) == 5
    assert t[1] - t[0] == pytest.approx(2.0)
    assert g["source_metadata"]["fs_estimated"] is False
    fd = FileData(str(p), g["data"], g["channels"], g["units"], 0,
                  source_metadata=g["source_metadata"])
    assert fd.fs == pytest.approx(0.5, rel=1e-9)


def test_zfd_dt_above_hour_falls_back_to_estimated_1khz(tmp_path):
    """A4: absurd dt (>3600 s) still uses the documented 1 kHz estimate."""
    p = _write_minimal_zfd(tmp_path / "absurd.zfd", dt=7200.0, count=4)
    groups = DataLoader.load_zfd(str(p))
    g = groups[0]
    t = g["data"]["Time"].to_numpy()
    assert t[1] - t[0] == pytest.approx(0.001)
    assert g["source_metadata"]["fs_estimated"] is True
