from __future__ import annotations
import numpy as np
import pandas as pd
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
    # 标定生效：MOTOR X 原值 ×2
    np.testing.assert_allclose(
        fast["data"]["MOTOR X"].to_numpy(), acc * 2.0)
    # CAN(全 NaN) 不在通道里
    assert "CAN" not in fast["channels"]
    # 转速注入快组
    assert any("SP" in c for c in fast["channels"])
    # 慢组含 SP 原始
    slow = next(g for g in groups if "1x" in g["label_suffix"])
    np.testing.assert_allclose(slow["data"]["SP"].to_numpy(), spd)
    # 元数据回传
    assert fast["channel_metadata"]["MOTOR X"]["quantity"] == "acceleration"
