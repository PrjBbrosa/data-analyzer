"""``DatenFenste2`` 显示块的字段契约。

字段语义来自 WinWert「曲线设置」对话框截图的逐行比对，并由 WinWert 自己写的
``.mat`` 导出文件交叉印证；台账见
``docs/analyzer/specs/2026-08-11-wwt-export-dual-compat-spec.md``。
红了先看那份文档，别直接放宽断言。
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from mf4_analyzer.io import wwt_display as disp

_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE = _ROOT / "assets" / "wwt" / "winwert_export_template.wwt"
_TRAILER_ASSET = _ROOT / "assets" / "wwt" / "winwert_display_trailer.bin"


@pytest.fixture
def template_bytes() -> bytes:
    if not _TEMPLATE.is_file():
        pytest.skip("bundled WWT export template missing")
    return _TEMPLATE.read_bytes()


@pytest.fixture
def trailer_asset() -> bytes:
    if not _TRAILER_ASSET.is_file():
        pytest.skip("bundled WinWert display trailer missing")
    return _TRAILER_ASSET.read_bytes()


def test_curve_table_decodes_real_template(template_bytes):
    rows = disp.read_curve_table(template_bytes)
    assert len(rows) >= 4
    assert rows[0]["label"], "曲线 0 是 X 轴行，必须有标签"
    # 绘图比例常数：轴跨度 × +52 在文件内按方向恒定
    assert rows[0]["plot_k"] > 0
    ys = [r["plot_k"] for r in rows[1:] if r["plot_k"] > 0]
    assert ys and max(ys) - min(ys) < 1e-6 * max(ys)


def test_template_x_axis_is_not_time(template_bytes):
    """前置事实：模板本身是「Y vs 转子位置」，所以导出必须改 X 引用。"""
    xs = {r["x_curve"] for r in disp.read_curve_table(template_bytes)[1:]}
    assert xs - {0}, "模板应当带有非时间的 X 引用（否则相关用例失去意义）"


def test_write_curve_syncs_ticks_and_plot_scale(template_bytes):
    data = bytearray(template_bytes)
    trailer = disp.find_trailer(bytes(data))
    before = disp.read_curve(bytes(data), trailer, 1)
    k = before["plot_k"]
    assert k > 0

    disp.write_curve(data, trailer, 1, label="X [Nm]", lo=-5.0, hi=15.0,
                     x_curve=0, visible=True, plot_k=k)
    row = disp.read_curve(bytes(data), trailer, 1)
    assert row["label"] == "X [Nm]"
    assert (row["lo"], row["hi"]) == (-5.0, 15.0)
    assert row["x_curve"] == 0 and row["visible"] == 1
    assert row["ticks"] == pytest.approx(2.0)      # 20 / 10 → nice step
    assert row["grid"] == pytest.approx(1.0)
    assert row["plot_k"] == pytest.approx(k, rel=1e-9), "绘图比例必须守恒"


def test_write_curve_ignores_out_of_range_curve(template_bytes):
    """极简尾块装不下曲线表；越界要静默跳过，不能炸掉导出。"""
    data = bytearray(b"DatenFenste2\0" + b"\0" * 200)
    disp.write_curve(data, 0, 5, label="x", lo=0.0, hi=1.0)
    assert bytes(data) == b"DatenFenste2\0" + b"\0" * 200


def test_force_time_axis_zeroes_every_curve(template_bytes):
    data = bytearray(template_bytes)
    trailer = disp.find_trailer(bytes(data))
    count = disp.declared_record_count(bytes(data), trailer)
    disp.force_time_axis(data, trailer, list(range(count)), 0.0, 12.5)

    rows = disp.read_curve_table(bytes(data))
    assert all(r["x_curve"] == 0 for r in rows), "每条曲线都要指向时间"
    assert struct.unpack_from("<H", data, trailer + disp.GLOBAL_X_OFF)[0] == 0
    assert rows[0]["label"] == "Time [s]"
    assert (rows[0]["lo"], rows[0]["hi"]) == (0.0, 12.5)


def test_rebuild_display_trailer_resizes_curve_table(template_bytes):
    src = template_bytes[disp.find_trailer(template_bytes):]
    src_records = disp.declared_record_count(src, 0)

    spec = [("A [Nm]", -2.0, 2.0), ("B [°]", -450.0, 450.0),
            ("C [rpm]", 0.0, 3000.0)]
    out = disp.rebuild_display_trailer(src, spec, 0.0, 12.5)

    assert disp.declared_record_count(out, 0) == len(spec) + 1
    assert struct.unpack_from("<H", out, disp.GLOBAL_X_OFF)[0] == 0
    # 表体按记录数伸缩，其余段整体搬运
    delta = (len(spec) + 1 - src_records) * disp.CURVE_STRIDE
    assert len(out) == len(src) + delta
    tail = disp.CURVE_BASE + (len(spec) + 1) * disp.CURVE_STRIDE
    assert out[tail:] == src[disp.CURVE_BASE + src_records * disp.CURVE_STRIDE:]

    rows = disp.read_curve_table(out, 0)
    assert rows[0]["label"] == "Time [s]"
    assert (rows[0]["lo"], rows[0]["hi"]) == (0.0, 12.5)
    for row, (label, lo, hi) in zip(rows[1:], spec):
        assert row["label"] == label
        assert (row["lo"], row["hi"]) == (lo, hi)
        assert row["x_curve"] == 0 and row["visible"] == 1
        assert row["plot_k"] == pytest.approx(rows[1]["plot_k"], rel=1e-9)


def test_rebuild_display_trailer_grows_past_template_slots(template_bytes):
    """通道数可以超过模板记录数——曲线表按需增长。"""
    src = template_bytes[disp.find_trailer(template_bytes):]
    spec = [(f"Ch{i} [Nm]", -float(i + 1), float(i + 1)) for i in range(12)]
    out = disp.rebuild_display_trailer(src, spec, 0.0, 1.0)
    rows = disp.read_curve_table(out, 0)
    assert len(rows) == len(spec) + 1
    assert [r["label"] for r in rows[1:]] == [s[0] for s in spec]


def test_rebuild_display_trailer_rejects_foreign_block():
    with pytest.raises(disp.WwtDisplayError, match="DatenFenste"):
        disp.rebuild_display_trailer(b"NotATrailer", [("a", 0.0, 1.0)], 0.0, 1.0)


def test_display_text_roundtrip(template_bytes):
    src = template_bytes[disp.find_trailer(template_bytes):]
    out = disp.set_display_text(
        src, title="T", comment="C",
        annotations=("line one", "line two"), editor="TraceLab",
    )
    got = disp.read_display_text(out)
    assert got["title"] == "T" and got["comment"] == "C"
    assert got["annotations"] == ["line one", "line two", "", ""]
    assert got["editor"] == "TraceLab"
    assert len(out) == len(src), "文本槽是定长缓冲，改写不许改变尾块长度"


def test_display_text_noop_without_log_block():
    stub = b"DatenFenste2\0" + b"\0" * 200
    assert disp.set_display_text(stub, title="x", annotations=()) == stub
    assert disp.read_display_text(stub) == {}


def test_bundled_trailer_asset_carries_no_session_text(trailer_asset):
    """捆绑资源不许带客户的台架 / 试验规范 / 操作员姓名。

    资源由 ``tools/make_wwt_display_trailer.py`` 从 WinWert 自己的导出文件抽取
    并清洗；重新生成后这条会看住清洗步骤没被漏掉。
    """
    text = disp.read_display_text(trailer_asset)
    assert text, "资源应当带 Log2 文本块"
    assert text["annotations"] == ["", "", "", ""]
    assert text["title"] == "" and text["comment"] == ""
    assert text["editor"] == "TraceLab"
    assert disp.declared_record_count(trailer_asset, 0) >= 2
