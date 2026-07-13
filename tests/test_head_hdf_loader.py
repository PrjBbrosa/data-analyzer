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


def test_channel_metadata_db_reference_defaults_to_empty_when_absent(tmp_path):
    """A channel with no 'dB reference' header line loads with
    ``channel_metadata[ch]['db_reference'] == ''`` rather than a missing key
    or a crash -- the Task 5 ``ChannelReferenceFacts`` adapter (signal-
    processing db-reference-defaults spec §8) treats this as 'no metadata',
    not an error, and falls through to catalog resolution safely."""
    n = 4
    p = write_head_hdf(
        tmp_path / "nodbref.hdf", n_scans=n, delta=1.0, start_of_data=2048,
        channels=[
            {"name": "ACC", "factor": 1, "quantity": "acceleration",
             "unit": "m/s^2", "calibration": 1.0,
             "samples": np.arange(n, dtype=float)},
        ])
    groups = DataLoader.load_hdf(str(p))
    g = groups[0]
    assert g["channel_metadata"]["ACC"]["db_reference"] == ""


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


def test_duplicate_truncated_channel_names_are_disambiguated_not_overwritten(tmp_path):
    """HEAD 的 ``name str`` 被截断到 16 字符会让物理上不同的通道塌成同名。

    回归（v1-latent，真实文件 260417-ripple 实测）：``load_hdf`` 过去用
    ``data[c.name] = s`` 当 DataFrame 键，同名后者静默覆盖前者——4 个
    ``Com_Motor_Torque`` 里唯一有真数据的那个被一条全 0 通道盖掉，用户在
    慢轨看到的扭矩是全 0。去重后：同组内每个物理通道保留一个唯一列名，
    units / channel_metadata 同步跟到新键，真实数据不再丢失。
    """
    n = 6
    zeros = np.zeros(n)
    real = np.array([-4.22, 3.1, -2.0, 4.62, 0.5, -1.0])   # 唯一有真数据
    dup = lambda s: {"name": "Com_Motor_Torque", "factor": 1,
                     "quantity": "torque", "unit": "Nm",
                     "calibration": 1.0, "samples": s}
    p = write_head_hdf(
        tmp_path / "dup.hdf", n_scans=n, delta=1.0, start_of_data=4096,
        channels=[dup(zeros.copy()), dup(real), dup(zeros.copy())])
    groups = DataLoader.load_hdf(str(p))
    g = next(g for g in groups if "1x" in g["label_suffix"])
    signal_cols = [c for c in g["channels"] if c != "Time"]
    # 3 个物理通道 → 3 个不同列名，无覆盖
    assert len(signal_cols) == 3
    assert len(set(signal_cols)) == 3
    # 真实扭矩数据没被全 0 覆盖：某列能还原 real
    df = g["data"]
    assert any(np.allclose(df[c].to_numpy(), real) for c in signal_cols)
    # 去重列的 units / channel_metadata 同步存在（不留悬空键）
    for c in signal_cols:
        assert c in g["units"]
        assert c in g["channel_metadata"]
        assert g["channel_metadata"][c]["quantity"] == "torque"


def test_unique_channel_names_keep_their_exact_name(tmp_path):
    """无碰撞时通道列名保持原样（去重只对真正重复的名字生效）。"""
    n = 4
    p = write_head_hdf(
        tmp_path / "uniq.hdf", n_scans=n, delta=1.0, start_of_data=2048,
        channels=[
            {"name": "Com_Motor_Torque", "factor": 1, "quantity": "torque",
             "unit": "Nm", "calibration": 1.0, "samples": np.arange(n, dtype=float)},
            {"name": "Com_TAS_Angle (C", "factor": 1, "quantity": "angle",
             "unit": "deg", "calibration": 1.0, "samples": np.arange(n, dtype=float)},
        ])
    groups = DataLoader.load_hdf(str(p))
    g = next(g for g in groups if "1x" in g["label_suffix"])
    assert "Com_Motor_Torque" in g["channels"]
    assert "Com_TAS_Angle (C" in g["channels"]


def test_format_dropped_channels_notice():
    """被丢通道（非 FLOAT32 / 全 NaN）汇总成给用户看的提示；空列表→空串，
    UI 据此决定是否弹提示。之前 dropped_channels 只存在 metadata、UI 零暴露。"""
    from mf4_analyzer.io.loader import format_dropped_channels_notice
    assert format_dropped_channels_notice([]) == ""
    assert format_dropped_channels_notice(None) == ""
    one = format_dropped_channels_notice(
        [{"name": "CAN 1@SQuadriga", "reason": "non-FLOAT32: UINT32"}])
    assert "CAN 1@SQuadriga" in one
    assert "1" in one
    many = format_dropped_channels_notice([
        {"name": "A", "reason": "non-FLOAT32: UINT32"},
        {"name": "B", "reason": "all-NaN"},
    ])
    assert "2" in many


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
    # 快组 fs = 1/period, period = delta*per_scan/factor = 1*3/2 = 1.5 -> fs≈0.67
    assert fast.fs > 0
    assert fast.channel_metadata["MOTOR X"]["quantity"] == "acceleration"


def test_time_axis_scales_by_total_floats_per_scan_not_max_factor(tmp_path):
    """时间轴绝对尺度 = delta × Σfactor（per_scan），不是 max_factor。

    回归：旧公式 period = delta × max_factor/factor 把时长压短 Σfactor/max_factor
    倍（真实文件实测应 ~50 s / 48 kHz，旧公式给 ~9 s / 129.5 kHz）。用 factor 分布
    {4,1,1}（Σfactor=6 ≠ max_factor=4）的合成文件钉死每通道周期与跨组总时长——
    没有这条断言，旧的「自洽于公式」用例放过了 5.4× 的绝对尺度错误。
    """
    n = 100
    delta = 1e-3
    p = write_head_hdf(
        tmp_path / "rate.hdf", n_scans=n, delta=delta, start_of_data=4096,
        channels=[
            {"name": "ACC", "factor": 4, "quantity": "acceleration",
             "unit": "m/s^2", "calibration": 1.0,
             "samples": np.arange(n * 4, dtype=float)},
            {"name": "T1", "factor": 1, "quantity": "temperature",
             "unit": "degC", "calibration": 1.0,
             "samples": np.arange(n, dtype=float) + 1.0},
            {"name": "T2", "factor": 1, "quantity": "temperature",
             "unit": "degC", "calibration": 1.0,
             "samples": np.arange(n, dtype=float) + 2.0},
        ])
    groups = DataLoader.load_hdf(str(p))
    per_scan = 4 + 1 + 1             # = 6（≠ max_factor 4）
    scan_period = delta * per_scan   # 一个 scan = 6 ms
    total = n * scan_period          # 跨组总时长 = 0.6 s

    fast = next(g for g in groups if g["label_suffix"] == "4x")
    slow = next(g for g in groups if g["label_suffix"] == "1x")
    tf = fast["data"]["Time"].to_numpy()
    ts = slow["data"]["Time"].to_numpy()

    # 每通道周期 = scan_period / factor（旧 max_factor 公式会给 fast=1ms、slow=4ms）
    assert (tf[1] - tf[0]) == pytest.approx(scan_period / 4)   # 1.5 ms, fs≈667 Hz
    assert (ts[1] - ts[0]) == pytest.approx(scan_period / 1)   # 6 ms,   fs≈167 Hz
    # 两组覆盖同一总时长（末样本 = total − 一个该通道周期）
    assert tf[-1] == pytest.approx(total - scan_period / 4)
    assert ts[-1] == pytest.approx(total - scan_period / 1)
    # per_scan 落入 source_metadata 供对标 HEAD Companion
    assert fast["source_metadata"]["per_scan"] == per_scan
