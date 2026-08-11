"""模板原地改写路径（``wwt_inplace``）的契约。

显示块字段本身由 ``test_wwt_display.py`` 看守；这里只管「写进真实骨架的槽位」
这条路特有的问题：槽位分配、重采样、量化槽位重新标定、显示配置同步。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mf4_analyzer.io import wwt_display as disp
from mf4_analyzer.io.loader import DataLoader
from mf4_analyzer.io.wwt_inplace import (
    WwtInplaceError,
    convert_to_wwt,
    default_export_template,
    list_measurement_slots,
    primary_measurement_slots,
    resample_series,
    write_wwt_inplace,
)

_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE = _ROOT / "assets" / "wwt" / "winwert_export_template.wwt"
_LEGACY = _ROOT / "testdoc" / "wwt" / "YP_SS_000089.wwt"


@pytest.fixture
def template():
    if not _TEMPLATE.is_file():
        pytest.skip("bundled WWT export template missing")
    return _TEMPLATE


def test_default_template_resolves_and_has_slots(template):
    assert default_export_template() == template
    slots = list_measurement_slots(template)
    assert len(slots) >= 3
    assert len({s["n"] for s in slots}) == 1


def test_convert_csv_like_series_roundtrips_tracelab(template, tmp_path):
    n_src = 500
    t = np.arange(n_src, dtype=np.float64) * 0.002
    torque = np.sin(2 * np.pi * 4.0 * t)
    rpm = 600.0 + 2000.0 * t / t[-1]
    out = tmp_path / "from_csv.wwt"
    result = convert_to_wwt(
        out,
        t,
        {"Steering torque": torque, "Motor speed": rpm},
        units={"Steering torque": "Nm", "Motor speed": "rpm"},
        template_path=template,
    )
    assert result.resampled is True
    assert result.channel_count == 2
    loaded = DataLoader.load_wwt(str(out))[0]
    assert "Steering torque" in loaded["channels"]
    assert "Motor speed" in loaded["channels"]
    assert len(loaded["data"]) == result.template_n
    # Time span preserved after resample.
    got_t = loaded["data"]["Time"].to_numpy()
    assert got_t[0] == pytest.approx(t[0])
    assert got_t[-1] == pytest.approx(t[-1])


def test_convert_forces_time_domain_display(template, tmp_path):
    """模板 X 引用指向角度/转子位置，导出必须改成时域。"""
    import struct

    from mf4_analyzer.io.wwt_inplace import _REC_XKANAL_OFF, _iter_records

    n = 300
    t = np.arange(n, dtype=np.float64) * 0.005
    out = tmp_path / "time_axis.wwt"
    result = convert_to_wwt(
        out,
        t,
        {"Steering torque": np.sin(t), "Motor speed": np.cos(t)},
        units={"Steering torque": "Nm", "Motor speed": "rpm"},
        template_path=template,
    )
    assert result.time_axis is True
    data = out.read_bytes()
    rows = disp.read_curve_table(data)
    assert rows and all(r["x_curve"] == 0 for r in rows)
    assert rows[0]["label"] == "Time [s]"
    assert (rows[0]["lo"], rows[0]["hi"]) == (
        pytest.approx(t[0]), pytest.approx(t[-1])
    )
    for rec in _iter_records(data, include_unknown=True):
        (hdr_x,) = struct.unpack_from("<H", data, rec.rec_off + _REC_XKANAL_OFF)
        assert hdr_x == 0
    loaded = DataLoader.load_wwt(str(out))[0]
    assert "Steering torque" in loaded["channels"]


def test_convert_can_keep_template_axis(template, tmp_path):
    n = 300
    t = np.arange(n, dtype=np.float64) * 0.005
    out = tmp_path / "template_axis.wwt"
    result = convert_to_wwt(
        out, t, {"ch": np.sin(t)}, template_path=template, time_axis=False,
    )
    assert result.time_axis is False
    xs = {r["x_curve"] for r in disp.read_curve_table(out.read_bytes())[1:]}
    assert xs - {0}, "time_axis=False 应保留模板原有的 X 轴绑定"


def test_convert_labels_written_curves_and_hides_the_rest(template, tmp_path):
    """写入的曲线拿到自己的标签与量程；没写入的模板曲线取消勾选。"""
    from mf4_analyzer.io.wwt_inplace import _iter_records

    n = 300
    t = np.arange(n, dtype=np.float64) * 0.005
    y = 1234.0 + 500.0 * np.sin(t)
    out = tmp_path / "labels.wwt"
    convert_to_wwt(
        out, t, {"Rack Force": y}, units={"Rack Force": "N"},
        template_path=template,
    )
    data = out.read_bytes()
    rec = next(r for r in _iter_records(data, include_unknown=True)
               if r.name == "Rack Force")
    rows = {r["curve"]: r for r in disp.read_curve_table(data)}
    mine = rows[rec.index]
    assert mine["label"] == "Rack Force [N]"
    assert mine["lo"] == pytest.approx(float(y.min()))
    assert mine["hi"] == pytest.approx(float(y.max()))
    assert mine["visible"] == 1
    assert mine["ticks"] == 0.0, "刻度交给 WinWert 自动"
    assert (mine["color_index"], mine["color_rgb"]) == disp.palette_color(1)
    others = [r for c, r in rows.items() if c not in (0, rec.index)]
    assert others and all(r["visible"] == 0 for r in others)


def test_convert_keeps_layout_constants(template, tmp_path):
    """轴范围改了，绘图比例与轴原点都必须同步。

    比例漏改 → WinWert 首帧把数据挤成左边一条细带；原点漏改 → 下限为负的
    曲线首帧只画出正半边（两者都实测过）。
    """
    from mf4_analyzer.io.wwt_inplace import _iter_records

    tpl = _TEMPLATE.read_bytes()
    tpl_trailer = disp.find_trailer(tpl)
    count = disp.declared_record_count(tpl, tpl_trailer)
    layout = disp.layout_constants(tpl, tpl_trailer, range(1, count))
    assert layout.plot_k_x and layout.plot_k_y
    assert layout.origin_c_x is not None and layout.origin_c_y is not None

    n = 400
    t = np.arange(n, dtype=np.float64) * 0.01
    out = tmp_path / "scale.wwt"
    convert_to_wwt(
        out, t, {"Rack Force": 900.0 * np.sin(t)}, units={"Rack Force": "N"},
        template_path=template,
    )
    data = out.read_bytes()
    rows = {r["curve"]: r for r in disp.read_curve_table(data)}
    rec = next(r for r in _iter_records(data, include_unknown=True)
               if r.name == "Rack Force")

    assert rows[0]["plot_k"] == pytest.approx(layout.plot_k_x, rel=1e-9)
    assert rows[rec.index]["plot_k"] == pytest.approx(layout.plot_k_y, rel=1e-9)
    for curve, const in ((0, layout.origin_c_x), (rec.index, layout.origin_c_y)):
        row = rows[curve]
        expected = -(row["hi"] * row["scale"]) - const
        assert row["origin"] == pytest.approx(expected, rel=1e-9)


def test_convert_rescales_quantized_slots(template, tmp_path):
    """大量程通道写进 int16/int32 槽位不能被模板缩放系数削掉。

    回归：Servo 模板的 int16 槽位标定到 ±32，直接写 ±450° 的转向角会被
    静默截断成 ±32（2026-08-11 实测）。
    """
    n = 400
    t = np.arange(n, dtype=np.float64) * 0.002
    angle = 450.0 * np.sin(2 * np.pi * 1.5 * t)
    torque = 6.5 * np.cos(2 * np.pi * 3.0 * t)
    out = tmp_path / "wide_range.wwt"
    convert_to_wwt(
        out, t, {"Steering angle": angle, "Steering torque": torque},
        units={"Steering angle": "°", "Steering torque": "Nm"},
        template_path=template,
    )
    got = DataLoader.load_wwt(str(out))[0]["data"]
    for name, src in (("Steering angle", angle), ("Steering torque", torque)):
        ref = np.interp(
            np.linspace(0.0, 1.0, len(got)), np.linspace(0.0, 1.0, n), src
        )
        span = float(src.max() - src.min())
        err = float(np.max(np.abs(got[name].to_numpy() - ref)))
        assert err < span / 10000.0, f"{name} 量化误差 {err} 过大（量程 {span}）"


def test_convert_scrubs_template_footer_text(template, tmp_path):
    """模板路径也要清掉继承的页脚（台架 / 试验规范 / 操作员）。"""
    src_text = disp.read_display_text(
        _TEMPLATE.read_bytes()[disp.find_trailer(_TEMPLATE.read_bytes()):]
    )
    assert any(src_text["annotations"]), "模板本身应当带页脚文本，否则用例无意义"

    n = 300
    t = np.arange(n, dtype=np.float64) * 0.005
    out = tmp_path / "scrub.wwt"
    convert_to_wwt(out, t, {"ch": np.sin(t)}, template_path=template,
                   title="TraceLab", comment="converted")
    data = out.read_bytes()
    got = disp.read_display_text(data[disp.find_trailer(data):])
    assert got["annotations"] == ["", "", "", ""]
    assert got["title"] == "TraceLab" and got["comment"] == "converted"
    assert got["editor"] == "TraceLab"


def test_convert_rejects_too_many_channels(template, tmp_path):
    slots = list_measurement_slots(template)
    n = 200
    t = np.arange(n, dtype=np.float64) * 0.001
    too_many = {f"ch{i}": np.zeros(n) for i in range(len(slots) + 1)}
    with pytest.raises(WwtInplaceError, match="最多可导出"):
        convert_to_wwt(tmp_path / "bad.wwt", t, too_many, template_path=template)


def test_inplace_on_legacy_template_still_works(tmp_path):
    if not _LEGACY.is_file():
        pytest.skip("legacy testdoc template missing")
    slots = primary_measurement_slots(_LEGACY)
    n = slots[0].n
    t = np.arange(n, dtype=np.float64) * 0.001
    y = np.sin(t)
    out = tmp_path / "legacy.wwt"
    write_wwt_inplace(
        _LEGACY,
        out,
        {"Steering torque": y},
        units={"Steering torque": "Nm"},
        time=t,
        match_by_name=False,
        slots=slots[:1],
    )
    loaded = DataLoader.load_wwt(str(out))[0]
    assert "Steering torque" in loaded["channels"]


def test_resample_series_length():
    t = np.linspace(0.0, 1.0, 50)
    y = np.sin(2 * np.pi * t)
    t2, y2 = resample_series(t, y, 200)
    assert len(t2) == 200 and len(y2) == 200
    assert t2[0] == pytest.approx(0.0)
    assert t2[-1] == pytest.approx(1.0)
