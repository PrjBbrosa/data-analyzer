from __future__ import annotations
import numpy as np
import pandas as pd
import pytest
from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.io.loader import DataLoader
from tests._helpers.head_hdf_factory import write_head_hdf


def test_filedata_carries_metadata(tmp_path):
    df = pd.DataFrame({"Time": [0.0, 1.0, 2.0], "L": [1.0, 2.0, 3.0]})
    fd = FileData(
        str(tmp_path / "x.hdf"), df, list(df.columns), {"L": "Pa"}, 0,
        source_metadata={"recording_date": "17.04.2026", "scan_mode": "x"},
        channel_metadata={"L": {"quantity": "sound pressure",
                                "db_reference": "2e-005", "calibration": 104.0}},
        label_suffix="24x")
    assert fd.source_metadata["recording_date"] == "17.04.2026"
    assert fd.channel_metadata["L"]["db_reference"] == "2e-005"
    assert fd.label_suffix == "24x"
    assert "24x" in fd.short_name


def test_filedata_backcompat_no_metadata(tmp_path):
    df = pd.DataFrame({"Time": [0.0, 1.0], "L": [1.0, 2.0]})
    fd = FileData(str(tmp_path / "y.hdf"), df, list(df.columns), {}, 0)
    assert fd.source_metadata == {}
    assert fd.channel_metadata == {}


def test_load_hdf_groups_by_factor_and_drops_nan(tmp_path):
    n = 4
    acc = np.arange(n * 2, dtype=float)            # factor 2 -> 24x 模拟组
    spd = np.array([100., 110., 120., 130.])       # factor 1 -> 慢组
    nanch = None                                    # factor 2 全 NaN -> 丢弃
    p = write_head_hdf(
        tmp_path / "g.hdf", n_scans=n, delta=1.0, start_of_data=4096,
        channels=[
            {"name": "MOTOR X", "factor": 2, "quantity": "acceleration",
             "unit": "m/s^2", "calibration": 2.0, "samples": acc},
            {"name": "SP", "factor": 1, "quantity": "speed of rotation",
             "unit": "deg/s", "calibration": 1.0, "samples": spd},
            {"name": "CAN", "factor": 2, "quantity": "raw", "unit": "",
             "calibration": 1.0, "samples": nanch},
        ])
    groups = DataLoader.load_hdf(str(p))
    factors = sorted(g["label_suffix"] for g in groups)
    # 全 NaN 的 factor-2 CAN 被丢；但 MOTOR X 也是 factor-2 -> 该组仍在
    assert any("2x" in s for s in factors)
    assert any("1x" in s for s in factors)
    fast = next(g for g in groups if "2x" in g["label_suffix"])
    # calibration 一律不乘：HEAD FLOAT32 样本本身已是物理工程值，
    # MOTOR X 保持原始（即便 calibration=2.0）
    np.testing.assert_allclose(
        fast["data"]["MOTOR X"].to_numpy(), acc)
    # calibration 仍作为元数据保留
    assert fast["channel_metadata"]["MOTOR X"]["calibration"] == 2.0
    # CAN(全 NaN) 不在通道里
    assert "CAN" not in fast["channels"]
    # 转速注入快组
    assert any("SP" in c for c in fast["channels"])
    # 慢组含 SP 原始
    slow = next(g for g in groups if "1x" in g["label_suffix"])
    np.testing.assert_allclose(slow["data"]["SP"].to_numpy(), spd)
    # 元数据回传
    assert fast["channel_metadata"]["MOTOR X"]["quantity"] == "acceleration"


def test_calibration_not_applied_as_gain(tmp_path):
    """calibration≠1 的通道加载后幅值=原始幅值（不被 calibration 放大）。"""
    n = 8
    # 转向扫角风格：原始 ±几百度，calibration 是大数（旧 bug 会乘到荒唐量级）
    raw = np.linspace(-264.0, 694.0, n)
    p = write_head_hdf(
        tmp_path / "cal.hdf", n_scans=n, delta=1.0, start_of_data=2048,
        channels=[
            {"name": "Com_TAS_Angle (C", "factor": 1, "quantity": "angle",
             "unit": "deg", "calibration": 117.40169830693, "samples": raw},
        ])
    groups = DataLoader.load_hdf(str(p))
    g = next(g for g in groups if "1x" in g["label_suffix"])
    loaded = g["data"]["Com_TAS_Angle (C"].to_numpy()
    np.testing.assert_allclose(loaded, raw)
    # 量级合理：~700 级，不是 8e4
    assert np.abs(loaded).max() < 1e3
    # calibration 仍保留为元数据
    assert g["channel_metadata"]["Com_TAS_Angle (C"]["calibration"] == \
        pytest.approx(117.40169830693)


def test_calibration_zero_channel_preserved_not_zeroed(tmp_path):
    """calibration=0 的通道加载后非全零、等于原始（旧 bug 会 ×0 抹零）。"""
    n = 8
    raw = np.linspace(-311.0, 295.0, n)   # 真实非零原始数据
    p = write_head_hdf(
        tmp_path / "calzero.hdf", n_scans=n, delta=1.0, start_of_data=2048,
        channels=[
            {"name": "Com_RPS_Speed (C", "factor": 1, "quantity": "angle",
             "unit": "deg", "calibration": 0.0, "samples": raw},
        ])
    groups = DataLoader.load_hdf(str(p))
    g = next(g for g in groups if "1x" in g["label_suffix"])
    assert "Com_RPS_Speed (C" in g["channels"]
    loaded = g["data"]["Com_RPS_Speed (C"].to_numpy()
    np.testing.assert_allclose(loaded, raw)
    assert np.any(loaded != 0)
    assert g["channel_metadata"]["Com_RPS_Speed (C"]["calibration"] == 0.0


def test_groups_build_multiple_filedata(tmp_path):
    n = 4
    p = write_head_hdf(
        tmp_path / "m.hdf", n_scans=n, delta=1.0, start_of_data=2048,
        channels=[
            {"name": "MOTOR X", "factor": 2, "quantity": "acceleration",
             "unit": "m/s^2", "calibration": 1.0,
             "samples": np.arange(n * 2, dtype=float)},
            {"name": "SP", "factor": 1, "quantity": "speed of rotation",
             "unit": "deg/s", "calibration": 1.0,
             "samples": np.array([1., 2., 3., 4.])},
        ])
    groups = DataLoader.load_hdf(str(p))
    fds = [FileData(str(p), g["data"], g["channels"], g["units"], i,
                    source_metadata=g["source_metadata"],
                    channel_metadata=g["channel_metadata"],
                    label_suffix=g["label_suffix"]) for i, g in enumerate(groups)]
    assert len(fds) == 2
    suffixes = {fd.label_suffix for fd in fds}
    assert suffixes == {"2x", "1x"}
    fast = next(fd for fd in fds if fd.label_suffix == "2x")
    # 快组 fs = 1/period, period = delta*max_factor/factor = 1*2/2 = 1 -> fs≈1
    assert fast.fs > 0
    assert fast.channel_metadata["MOTOR X"]["quantity"] == "acceleration"
