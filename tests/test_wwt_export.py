"""任意来源 → WWT 导出门面的产品契约（clean-room 与模板两条路）。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mf4_analyzer.io import wwt_display as disp
from mf4_analyzer.io.loader import DataLoader
from mf4_analyzer.io.wwt_export import (
    MODE_CLEANROOM,
    MODE_TEMPLATE,
    WwtExportError,
    default_display_trailer_path,
    export_wwt,
)

_ROOT = Path(__file__).resolve().parent.parent
_TRAILER_ASSET = _ROOT / "assets" / "wwt" / "winwert_display_trailer.bin"
_TEMPLATE = _ROOT / "assets" / "wwt" / "winwert_export_template.wwt"


@pytest.fixture(autouse=True)
def _require_assets():
    if not _TRAILER_ASSET.is_file():
        pytest.skip("bundled WinWert display trailer missing")


def _series(n=600, dt=0.002):
    t = np.arange(n, dtype=np.float64) * dt
    return t, {
        "Steering torque": 6.5 * np.sin(2 * np.pi * 1.5 * t),
        "Steering angle": 450.0 * np.cos(2 * np.pi * 0.4 * t),
    }, {"Steering torque": "Nm", "Steering angle": "°"}


def test_default_trailer_asset_resolves():
    assert default_display_trailer_path() == _TRAILER_ASSET


def test_cleanroom_keeps_native_length_and_exact_values(tmp_path):
    t, channels, units = _series()
    out = tmp_path / "native.wwt"
    result = export_wwt(out, t, channels, units=units, title="T", comment="C")

    assert result.mode == MODE_CLEANROOM
    assert result.sample_count == len(t)
    assert result.resampled is False and result.quantized is False
    assert result.channel_count == 2

    loaded = DataLoader.load_wwt(str(out))[0]
    assert len(loaded["data"]) == len(t)
    for name, values in channels.items():
        np.testing.assert_allclose(
            loaded["data"][name].to_numpy(), values, rtol=0, atol=0
        )
    assert loaded["units"]["Steering angle"] == "°"
    got_t = loaded["data"]["Time"].to_numpy()
    assert got_t[0] == pytest.approx(t[0])
    assert got_t[-1] == pytest.approx(t[-1])


def test_cleanroom_writes_time_domain_display(tmp_path):
    t, channels, units = _series()
    out = tmp_path / "display.wwt"
    export_wwt(out, t, channels, units=units)

    rows = disp.read_curve_table(out.read_bytes())
    assert len(rows) == len(channels) + 1
    assert all(r["x_curve"] == 0 for r in rows), "每条曲线都要按时间显示"
    assert rows[0]["label"] == "Time [s]"
    assert (rows[0]["lo"], rows[0]["hi"]) == (
        pytest.approx(t[0]), pytest.approx(t[-1])
    )
    assert [r["label"] for r in rows[1:]] == [
        "Steering torque [Nm]", "Steering angle [°]"
    ]
    for i, (row, values) in enumerate(zip(rows[1:], channels.values()), start=1):
        assert row["visible"] == 1
        assert row["lo"] == pytest.approx(float(values.min()))
        assert row["hi"] == pytest.approx(float(values.max()))
        assert row["plot_k"] > 0, "绘图比例要跟着量程同步，否则首帧会挤成一条"
        assert row["ticks"] == 0.0, "刻度交给 WinWert 自动，否则首帧轴布局错位"
        assert (row["color_index"], row["color_rgb"]) == disp.palette_color(i)


def test_cleanroom_gives_every_channel_its_own_colour(tmp_path):
    """回归：所有曲线都从同一原型复制，不单独配色就会全是红色。"""
    n = 300
    t = np.arange(n, dtype=np.float64) * 0.001
    channels = {f"Ch{i + 1}": float(i + 1) * np.sin(t) for i in range(6)}
    out = tmp_path / "colours.wwt"
    export_wwt(out, t, channels, units={k: "Nm" for k in channels})

    rows = disp.read_curve_table(out.read_bytes())
    colours = [(r["color_index"], r["color_rgb"]) for r in rows[1:]]
    assert len(set(colours)) == len(colours), f"曲线颜色重复: {colours}"
    # 与 WinWert 自己的导出同序：curve1..6 → 序号 1..6
    assert [c[0] for c in colours] == [1, 2, 3, 4, 5, 6]


def test_cleanroom_stamps_own_text_and_drops_template_annotations(tmp_path):
    t, channels, units = _series()
    out = tmp_path / "text.wwt"
    export_wwt(out, t, channels, units=units,
               title="TraceLab export", comment="from CSV")

    data = out.read_bytes()
    text = disp.read_display_text(data[disp.find_trailer(data):])
    assert text["title"] == "TraceLab export"
    assert text["comment"] == "from CSV"
    assert text["annotations"] == ["", "", "", ""], "不许继承别人的台架/规范文本"
    meta = DataLoader.load_wwt(str(out))[0]["source_metadata"]
    assert meta["title"] == "TraceLab export"
    assert meta["comment"] == "from CSV"


def test_cleanroom_accepts_more_channels_than_template_slots(tmp_path):
    n = 300
    t = np.arange(n, dtype=np.float64) * 0.001
    channels = {f"Ch{i + 1}": float(i + 1) * np.sin(t) for i in range(10)}
    out = tmp_path / "many.wwt"
    result = export_wwt(out, t, channels, units={k: "Nm" for k in channels})

    assert result.channel_count == 10
    loaded = DataLoader.load_wwt(str(out))[0]
    assert [c for c in loaded["channels"] if c != "Time"] == list(channels)
    rows = disp.read_curve_table(out.read_bytes())
    assert len(rows) == 11 and all(r["x_curve"] == 0 for r in rows)


def test_cleanroom_refuses_short_source(tmp_path):
    t = np.arange(50, dtype=np.float64) * 0.001
    with pytest.raises(WwtExportError, match="100"):
        export_wwt(tmp_path / "short.wwt", t, {"a": np.sin(t)})


def test_cleanroom_auto_resamples_uneven_time_axis(tmp_path):
    """Irregular source axes are common; export must not force manual rebuild."""
    t = np.concatenate([
        np.arange(200, dtype=np.float64) * 0.001,
        0.2 + np.arange(200, dtype=np.float64) * 0.004,
    ])
    y = np.sin(t)
    out = tmp_path / "jitter.wwt"
    result = export_wwt(out, t, {"a": y})
    assert result.resampled is True
    assert result.sample_count == len(t)
    loaded = DataLoader.load_wwt(str(out))[0]
    got_t = loaded["data"]["Time"].to_numpy()
    assert got_t[0] == pytest.approx(t[0])
    assert got_t[-1] == pytest.approx(t[-1])
    # Equidistant after export.
    assert np.allclose(np.diff(got_t), got_t[1] - got_t[0])
    assert "已重采样" in result.summary

def test_cleanroom_refuses_length_mismatch(tmp_path):
    t = np.arange(200, dtype=np.float64) * 0.001
    with pytest.raises(WwtExportError, match="长度"):
        export_wwt(tmp_path / "bad.wwt", t, {"a": np.zeros(199)})


def test_cleanroom_refuses_empty_selection(tmp_path):
    t = np.arange(200, dtype=np.float64) * 0.001
    with pytest.raises(WwtExportError, match="至少"):
        export_wwt(tmp_path / "empty.wwt", t, {})


def test_missing_trailer_asset_reports_packaging_problem(tmp_path):
    t, channels, _ = _series()
    with pytest.raises(WwtExportError, match="assets/wwt"):
        export_wwt(tmp_path / "x.wwt", t, channels,
                   trailer_path=tmp_path / "nope.bin")


def test_template_mode_still_available(tmp_path):
    if not _TEMPLATE.is_file():
        pytest.skip("bundled WWT export template missing")
    t, channels, units = _series()
    out = tmp_path / "template.wwt"
    result = export_wwt(out, t, channels, units=units, mode=MODE_TEMPLATE)

    assert result.mode == MODE_TEMPLATE
    assert result.quantized is True
    assert result.resampled is True
    assert result.sample_count != len(t), "模板路径把点数钉在模板长度上"
    rows = disp.read_curve_table(out.read_bytes())
    assert all(r["x_curve"] == 0 for r in rows)


def test_unknown_mode_rejected(tmp_path):
    t, channels, _ = _series()
    with pytest.raises(WwtExportError, match="模式"):
        export_wwt(tmp_path / "x.wwt", t, channels, mode="nope")


def test_result_summary_reads_naturally(tmp_path):
    t, channels, units = _series()
    result = export_wwt(tmp_path / "s.wwt", t, channels, units=units)
    assert result.summary == f"2 通道 · {len(t)} 点"
