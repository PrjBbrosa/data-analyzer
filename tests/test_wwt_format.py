"""WinWert .wwt 解析：真实样本锚点值 + 合成错误/容错路径。

锚点值来自逆向规格里对 testdoc 样本的人工验证（原始整数 × a 手算），不是
「实现自洽」——改动换算公式/游标走位会在这里翻红。

两批样本：``testdoc/2024_3_17``（8 个 091293 基础文件）、``testdoc/wwt``
（4 个新文件，覆盖 200401 版本、Pars 计算通道重同步、短块限值曲线过滤）。
"""
from __future__ import annotations
import struct
from pathlib import Path

import numpy as np
import pytest

from mf4_analyzer.io.loader import DataLoader

_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = _ROOT / "testdoc" / "2024_3_17"
SAMPLE_DIR_V2 = _ROOT / "testdoc" / "wwt"


def _sample(name, base=SAMPLE_DIR):
    p = base / name
    if not p.exists():
        pytest.skip(f"sample not found: {p}")
    return str(p)


# ---------------------------------------------------------------- 合成文件工具

def _make_header(count, title=b"T", comment=b"C", magic=b"WinWert091293"):
    head = bytearray(0x211)
    head[0:len(magic)] = magic
    head[0x00F:0x00F + len(title)] = title
    head[0x10F:0x10F + len(comment)] = comment
    struct.pack_into("<H", head, 0x20F, count)
    return bytes(head)


def _make_record(tag, n, name=b"ch", unit=b"", a=1.0, b=0.001, c=0.0,
                 payload=b""):
    rec = bytearray(156)
    rec[0:len(tag)] = tag
    struct.pack_into("<IH", rec, 5, n, 0)
    rec[0x1b:0x1b + len(name)] = name
    rec[0x43:0x43 + len(unit)] = unit
    struct.pack_into("<ddd", rec, 0x84, a, b, c)
    return bytes(rec) + payload


# ------------------------------------------------------- 2024_3_17 基础样本

def test_yp_ss_single_group_scaling_and_skipped():
    groups = DataLoader.load_wwt(_sample("YP_SS_X04-CSER_000009.wwt"))
    # 第一个 Zeit 块（n=2293）下只有 n=6 的 Tol_* 公差曲线 → 不产出组
    assert len(groups) == 1
    g = groups[0]
    assert g["label_suffix"] == ""

    t = g["data"]["Time"].to_numpy()
    assert len(t) == 9182
    assert t[1] - t[0] == pytest.approx(0.001)   # fs = 1000 Hz
    assert t[0] == pytest.approx(0.0)

    assert g["channels"] == ["Time", "Md-Lenkrad", "Lenkwinkel",
                             "Druckstückspiel"]
    md = g["data"]["Md-Lenkrad"].to_numpy()
    # 原始 int16 首值 -581 × a=0.0012207
    assert md[0] == pytest.approx(-0.7092, abs=1e-3)
    assert md.min() == pytest.approx(-1.294, abs=1e-3)
    assert md.max() == pytest.approx(3.590, abs=1e-3)
    assert g["units"]["Md-Lenkrad"] == "Nm"

    assert g["data"]["Lenkwinkel"].iloc[0] == pytest.approx(-509.15, abs=1e-2)
    assert g["units"]["Lenkwinkel"] == "°"

    # a=-0.0001 为负：原始 [-535, -285] 翻成正值 [0.0285, 0.0535]
    ds = g["data"]["Druckstückspiel"].to_numpy()
    assert ds.min() == pytest.approx(0.0285, abs=1e-4)
    assert ds.max() == pytest.approx(0.0535, abs=1e-4)
    assert g["units"]["Druckstückspiel"] == "mm"

    smeta = g["source_metadata"]
    assert smeta["source_kind"] == "wwt"
    assert smeta["title"] == "Yoke Play_sensor side"
    assert smeta["winwert_version"] == "091293"
    assert smeta["skipped_channels"] == ["Tol_oben", "Tol_unten", "Tol_x"]
    assert smeta["source_filename"] == "YP_SS_X04-CSER_000009.wwt"

    cmeta = g["channel_metadata"]["Md-Lenkrad"]
    assert cmeta["tag"] == "int1"
    assert cmeta["scale_a"] == pytest.approx(0.0012207, rel=1e-4)
    assert cmeta["unit"] == "Nm"


def test_sfns_5_merges_identical_time_axes_into_one_group():
    groups = DataLoader.load_wwt(_sample("SFNS_5_X04-CSER_000009.wwt"))
    # 两个 Zeit 块参数相同（n=69600, dt=0.001）→ 合并成一组
    assert len(groups) == 1
    g = groups[0]
    assert g["label_suffix"] == ""
    assert len(g["data"]["Time"]) == 69600
    assert g["channels"] == ["Time", "Weg", "Rack Force", "Rack Travel"]

    weg = g["data"]["Weg"].to_numpy()          # Real：直接存物理值
    assert weg.min() == pytest.approx(-84.5, abs=1e-6)
    assert weg.max() == pytest.approx(84.5, abs=1e-6)

    rf = g["data"]["Rack Force"].to_numpy()
    assert rf.min() == pytest.approx(-3698, abs=1)
    assert rf.max() == pytest.approx(3698, abs=1)

    rt = g["data"]["Rack Travel"].to_numpy()
    assert rt.min() == pytest.approx(-83.4, abs=0.05)
    assert rt.max() == pytest.approx(82.67, abs=0.05)


def test_nltnp_unit_degree_decode_and_float32_channel():
    groups = DataLoader.load_wwt(_sample("NLTNP_X04-CSER_000009.wwt"))
    # 第一个 Zeit 块（1024 Hz）下全是 n=20 的评价曲线 → 只剩一组
    assert len(groups) == 1
    g = groups[0]
    assert len(g["data"]["Time"]) == 53608

    st = g["data"]["Steering torque"].to_numpy()
    assert st.min() == pytest.approx(-4.694, abs=1e-3)
    assert st.max() == pytest.approx(6.670, abs=1e-3)

    # GBK 双字节 A1 E3 ° 替换生效
    assert g["units"]["Steering angle"] == "°"

    ss = g["data"]["Steering speed"].to_numpy()   # Floa = float32
    assert g["channel_metadata"]["Steering speed"]["tag"] == "Floa"
    assert ss.max() == pytest.approx(57.16, abs=0.01)


def test_all_samples_load():
    if not SAMPLE_DIR.exists():
        pytest.skip(f"sample dir not found: {SAMPLE_DIR}")
    samples = sorted(SAMPLE_DIR.glob("*.wwt"))
    assert len(samples) == 8
    for p in samples:
        groups = DataLoader.load_wwt(str(p))
        assert groups
        for g in groups:
            assert g["channels"][0] == "Time"
            assert len(g["channels"]) > 1
            assert len(g["data"]) > 0
            # 多组才有区分后缀
            assert (g["label_suffix"] == "") == (len(groups) == 1)


# ------------------------------------------- 新样本：Pars 重同步 / 200401 版本

def test_servo_drive_stiffness_pars_resync():
    """091293 文件中间夹一条 Pars 计算通道（数据区 500 字节、无长度字段）：
    重同步必须精确恢复边界，其后的 3 条 Floa 通道才解析得出正确值。"""
    groups = DataLoader.load_wwt(
        _sample("Servo drive stiffness_000089.wwt", SAMPLE_DIR_V2))
    assert len(groups) == 1
    g = groups[0]
    t = g["data"]["Time"].to_numpy()
    assert len(t) == 9936
    assert t[1] - t[0] == pytest.approx(0.001)   # fs = 1000 Hz

    assert g["channels"] == [
        "Time", "Wheel input torque", "Rack Force", "Wheel input angle",
        "ID2S09_wRelRotorPosition_xdu16", "ID1S09_TorsionBarTorque_xds16",
        "ID1S09_MotorOutput_xds16"]

    assert g["channel_metadata"]["Wheel input torque"]["scale_a"] == \
        pytest.approx(0.0012207, rel=1e-4)
    wt = g["data"]["Wheel input torque"].to_numpy()
    assert wt[0] == pytest.approx(3.628, abs=1e-3)   # 原始 2972 × 0.0012207

    # Long 通道 a=-0.00625 为负
    cm = g["channel_metadata"]["Wheel input angle"]
    assert cm["tag"] == "Long"
    assert cm["scale_a"] == pytest.approx(-0.00625)
    assert g["data"]["Wheel input angle"].iloc[0] == \
        pytest.approx(-1.91875, abs=1e-5)            # 原始 307 × -0.00625

    # Pars 之后的 Floa 通道：重同步错 1 字节这里就全是垃圾
    mo = g["data"]["ID1S09_MotorOutput_xds16"].to_numpy()
    assert g["channel_metadata"]["ID1S09_MotorOutput_xds16"]["tag"] == "Floa"
    assert mo.min() == pytest.approx(-2.1406, abs=1e-3)
    assert mo.max() == pytest.approx(2.1914, abs=1e-3)

    smeta = g["source_metadata"]
    assert smeta["winwert_version"] == "091293"
    assert smeta["records_declared"] == 8
    assert smeta["records_parsed"] == 8
    assert smeta["skipped_channels"] == ["Spurstangenkraft (公式: abs(k2))"]


def test_u_can_200401_version_short_block_and_pars():
    """200401 版魔数但布局与 091293 相同 → 正常解析；首块 Zeit n=15 的
    Grenze/SKL 限值曲线整块过滤；4 条 Pars 计算通道（各 500 字节）重同步。

    注意：走读实测该文件恰好 32 条记录（= count 声明数）落在尾块上——两处
    「1156 字节 Pars」实为「500 字节 Pars + 紧随的第二条 156+500 Pars 记录」
    （后者有完整独立记录头：名字/单位/min-max/公式都不同），故
    records_parsed=32 且 4 条 Pars 各自进 skipped。
    """
    groups = DataLoader.load_wwt(
        _sample("U-Can_EO3_000089.wwt", SAMPLE_DIR_V2))
    assert len(groups) == 1
    g = groups[0]
    t = g["data"]["Time"].to_numpy()
    assert len(t) == 20075
    assert t[1] - t[0] == pytest.approx(0.001)   # fs = 1000 Hz

    assert g["channels"] == [
        "Time", "Wheel input torque", "Rack Force", "Battary Current",
        "Current", "Wheel input angle", "Sensor torque",
        "Motor ouput torque (1ms)"]

    smeta = g["source_metadata"]
    assert smeta["winwert_version"] == "200401"
    assert smeta["records_declared"] == 32
    assert smeta["records_parsed"] == 32

    skipped = smeta["skipped_channels"]
    # 首块 15 点 Grenze/SKL 全在 skipped（短块整体过滤，含 n 匹配的）
    for name in ("Grenze 1 Md(x)", "SKL Grenze 1", "Grenze 2 Md(x)",
                 "SKL Grenze 2"):
        assert name in skipped
    # 4 条 Pars 计算通道，名字附公式
    assert "Spurstangenkraft (公式: abs(k20))" in skipped
    assert "Diff. Moment (公式: -(k19-(-k26)))" in skipped
    assert ("|Abtrieb - mech. Krafteinleitung| "
            "(公式: abs(k51-(k52*0.85/(0.01787512/2))/1000))") in skipped
    assert ("|Theor. F_Spust. min| "
            "(公式: abs(k51-(k52*0.85/(0.01787512/2))/1000))") in skipped

    # 重同步正确性的数值旁证：Pars 之后的两条 Floa 通道解析出合理物理值
    st = g["data"]["Sensor torque"].to_numpy()
    assert st.min() == pytest.approx(-11.556, abs=1e-2)
    assert st.max() == pytest.approx(12.066, abs=1e-2)


def test_all_v2_samples_load():
    if not SAMPLE_DIR_V2.exists():
        pytest.skip(f"sample dir not found: {SAMPLE_DIR_V2}")
    samples = sorted(SAMPLE_DIR_V2.glob("*.wwt"))
    assert len(samples) == 4
    for p in samples:
        groups = DataLoader.load_wwt(str(p))
        assert groups
        for g in groups:
            assert g["channels"][0] == "Time"
            assert len(g["channels"]) > 1
            assert g["source_metadata"]["winwert_version"]


# ------------------------------------------------------ 合成容错/错误路径

def test_unlisted_version_with_compatible_layout_parses(tmp_path):
    """版本白名单已放宽：任意 WinWert* 版本号 + 合法布局 → 正常解析。"""
    n = 200
    vals = np.arange(n, dtype=np.float64)
    body = _make_record(b"Zeit", n, name=b"Time", unit=b"s")
    body += _make_record(b"Real", n, name=b"Weg", unit=b"mm",
                         payload=vals.tobytes())
    p = tmp_path / "anyver.wwt"
    p.write_bytes(_make_header(2, magic=b"WinWert150793") + body)
    groups = DataLoader.load_wwt(str(p))
    assert len(groups) == 1
    assert groups[0]["source_metadata"]["winwert_version"] == "150793"
    np.testing.assert_allclose(groups[0]["data"]["Weg"].to_numpy(), vals)


def test_incompatible_layout_reports_version(tmp_path):
    """布局真不同的版本：第一条记录就是未知标签且扫不到合法记录头 →
    报错并带上版本号提示布局不兼容。"""
    p = tmp_path / "old.wwt"
    p.write_bytes(_make_header(2, magic=b"WinWert251192")
                  + bytes(range(1, 32)) * 20)   # 垃圾布局（无合法记录头）
    with pytest.raises(ValueError, match="251192"):
        DataLoader.load_wwt(str(p))


def test_non_winwert_file_rejected(tmp_path):
    p = tmp_path / "junk.wwt"
    p.write_bytes(b"\x89PNG not a wwt at all" + b"\0" * 0x300)
    with pytest.raises(ValueError, match="不是有效的 WWT"):
        DataLoader.load_wwt(str(p))


def test_unknown_tag_resyncs_to_next_record(tmp_path):
    """未知标签 + 后面跟着结构合法的记录：重同步跳过（进 skipped），后续
    通道必须以正确边界解析出原值。"""
    n = 200
    vals = np.linspace(-5.0, 5.0, n)
    body = _make_record(b"Zeit", n, name=b"Time", unit=b"s")
    body += _make_record(b"Wxyz", n, name=b"Mystery",
                         payload=b"\x01" * 37)    # 37 字节未知数据
    body += _make_record(b"Real", n, name=b"Weg", unit=b"mm",
                         payload=vals.tobytes())
    p = tmp_path / "resync.wwt"
    p.write_bytes(_make_header(3) + body)
    groups = DataLoader.load_wwt(str(p))
    assert len(groups) == 1
    g = groups[0]
    np.testing.assert_allclose(g["data"]["Weg"].to_numpy(), vals)
    assert g["source_metadata"]["skipped_channels"] == ["Mystery"]
    assert g["source_metadata"]["records_parsed"] == 3


def test_unknown_tag_without_resync_target_rejected(tmp_path):
    """未知标签且其后扫不到任何合法记录头/尾块 → 硬错误（报标签）。
    绝不能猜元素大小继续走：错一次游标全错位。"""
    n = 200
    body = _make_record(b"Zeit", n, name=b"Time", unit=b"s")
    body += _make_record(b"Wxyz", n, name=b"Bad")
    p = tmp_path / "badtag.wwt"
    p.write_bytes(_make_header(2) + body)
    with pytest.raises(ValueError, match="Wxyz"):
        DataLoader.load_wwt(str(p))


def test_trailer_before_declared_count_stops_walk(tmp_path):
    """count 声明数不可靠：尾块提前出现即收尾，records_parsed < declared。"""
    n = 200
    vals = np.arange(n, dtype=np.float64)
    body = _make_record(b"Zeit", n, name=b"Time", unit=b"s")
    body += _make_record(b"Real", n, name=b"Weg", unit=b"mm",
                         payload=vals.tobytes())
    body += b"DatenFenste2\x00" + b"\x9a" * 40    # 显示配置尾块
    p = tmp_path / "early.wwt"
    p.write_bytes(_make_header(5, magic=b"WinWert200401") + body)
    groups = DataLoader.load_wwt(str(p))
    assert len(groups) == 1
    smeta = groups[0]["source_metadata"]
    assert smeta["records_declared"] == 5
    assert smeta["records_parsed"] == 2
    np.testing.assert_allclose(groups[0]["data"]["Weg"].to_numpy(), vals)


def test_short_zeit_block_filtered_as_curve_definitions(tmp_path):
    """Zeit n < 100 的块整体是限值/评价曲线：即便通道 n 与 Zeit 匹配也全部
    跳过、不产组。"""
    n_curve, n_ts = 15, 200
    vals = np.arange(n_ts, dtype=np.float64)
    body = _make_record(b"Zeit", n_curve, name=b"Zeit", unit=b"s")
    body += _make_record(b"Real", n_curve, name=b"Grenze 1 Md(x)", unit=b"Nm",
                         payload=np.zeros(n_curve).tobytes())
    body += _make_record(b"Zeit", n_ts, name=b"Time", unit=b"s")
    body += _make_record(b"Real", n_ts, name=b"Weg", unit=b"mm",
                         payload=vals.tobytes())
    p = tmp_path / "short.wwt"
    p.write_bytes(_make_header(4) + body)
    groups = DataLoader.load_wwt(str(p))
    assert len(groups) == 1
    g = groups[0]
    assert g["channels"] == ["Time", "Weg"]
    assert g["source_metadata"]["skipped_channels"] == ["Grenze 1 Md(x)"]


def test_truncated_data_region_rejected(tmp_path):
    # count=2：Zeit(n=10) + Real(n=10) 但只给 5 个 double → 数据区越界
    n = 10
    body = _make_record(b"Zeit", n, name=b"Zeit", unit=b"s")
    body += _make_record(b"Real", n, name=b"Weg", unit=b"mm",
                         payload=struct.pack("<5d", *range(5)))
    p = tmp_path / "trunc.wwt"
    p.write_bytes(_make_header(2) + body)
    with pytest.raises(ValueError, match="截断"):
        DataLoader.load_wwt(str(p))


def test_truncated_record_header_rejected(tmp_path):
    p = tmp_path / "trunc2.wwt"
    p.write_bytes(_make_header(1) + b"\0" * 20)   # 记录头不足 156 字节
    with pytest.raises(ValueError, match="截断"):
        DataLoader.load_wwt(str(p))
