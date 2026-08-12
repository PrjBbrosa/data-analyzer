"""Round-trip and contract tests for ``mf4_analyzer.io.wwt_writer``."""
from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.io.loader import DataLoader
from mf4_analyzer.io.wwt_writer import (
    UnevenTimeAxisError,
    infer_zeit_params,
    write_wwt,
)


def test_write_wwt_roundtrips_through_loader(tmp_path):
    n = 200
    dt = 0.001
    t0 = 0.5
    time = t0 + np.arange(n, dtype=np.float64) * dt
    torque = np.sin(2 * np.pi * 3.0 * (time - t0))
    angle = np.linspace(-10.0, 10.0, n)
    path = tmp_path / "export.wwt"
    write_wwt(
        path,
        time,
        {"Steering torque": torque, "Steer angle": angle},
        units={"Steering torque": "Nm", "Steer angle": "deg"},
        title="TraceLab export",
        comment="roundtrip",
        include_trailer_stub=True,
    )

    groups = DataLoader.load_wwt(str(path))
    assert len(groups) == 1
    g = groups[0]
    got_t = g["data"]["Time"].to_numpy()
    assert got_t[0] == pytest.approx(t0)
    assert got_t[1] - got_t[0] == pytest.approx(dt)
    assert len(got_t) == n
    assert g["channels"] == ["Time", "Steering torque", "Steer angle"]
    np.testing.assert_allclose(
        g["data"]["Steering torque"].to_numpy(), torque, rtol=0, atol=0
    )
    np.testing.assert_allclose(
        g["data"]["Steer angle"].to_numpy(), angle, rtol=0, atol=0
    )
    assert g["units"]["Steering torque"] == "Nm"
    assert g["units"]["Steer angle"] == "deg"
    assert path.read_bytes().find(b"DatenFenste2") > 0


def test_write_wwt_body_only_still_loads(tmp_path):
    # TraceLab skips Zeit blocks with n < 100 as curve definitions.
    time = np.arange(128, dtype=np.float64) * 0.01
    y = np.arange(128, dtype=np.float64)
    path = tmp_path / "body.wwt"
    write_wwt(path, time, {"y": y}, include_trailer_stub=False)
    assert path.read_bytes().find(b"DatenFenste2") < 0
    groups = DataLoader.load_wwt(str(path))
    assert len(groups) == 1
    np.testing.assert_allclose(groups[0]["data"]["y"].to_numpy(), y)


def _xkanalnrs(data: bytes, n: int, count: int) -> list[int]:
    """各记录头 +0x9。布局：0x211 文件头 + 156B 记录头（Zeit 无数据区）。"""
    import struct

    out = []
    off = 0x211
    for i in range(count):
        out.append(struct.unpack_from("<H", data, off + 0x9)[0])
        off += 156 + (0 if i == 0 else n * 8)
    return out


def test_stub_trailer_keeps_nonzero_xkanalnr(tmp_path):
    """极简尾块下 xkanalnr 必须非 0，否则 WinWert 拒开。

    2026-08-11 受控对照：同一份数据 + 同一个 256B stub，仅此字段 1↔0——
    写 1 的 ``testdoc/20260527.wwt`` 能打开，写 0 的探针 D 打不开。没有显示
    尾块时 WinWert 靠它兜底建图。
    """
    time = np.arange(128, dtype=np.float64) * 0.01
    path = tmp_path / "stub.wwt"
    write_wwt(path, time, {"a": np.sin(time), "b": np.cos(time)})
    xs = _xkanalnrs(path.read_bytes(), 128, 3)
    assert xs[0] == 0, "Zeit 记录不参与 X 引用"
    assert all(x != 0 for x in xs[1:]), f"数据记录 xkanalnr={xs[1:]}，会被拒开"


def test_display_trailer_allows_zero_xkanalnr(tmp_path):
    """带完整显示尾块时写 0：显示配置来自尾块曲线表（WinWert 自己就这么写）。"""
    time = np.arange(128, dtype=np.float64) * 0.01
    path = tmp_path / "graft.wwt"
    write_wwt(
        path, time, {"a": np.sin(time)},
        include_trailer_stub=False,
        trailer=b"DatenFenste2\x00" + b"\0" * 512,
    )
    assert _xkanalnrs(path.read_bytes(), 128, 2) == [0, 0]


def test_infer_zeit_rejects_jitter():
    t = np.array([0.0, 0.001, 0.0025, 0.003], dtype=np.float64)
    with pytest.raises(UnevenTimeAxisError, match="非等间隔"):
        infer_zeit_params(t)


def test_write_wwt_rejects_length_mismatch(tmp_path):
    time = np.arange(10, dtype=np.float64) * 0.001
    with pytest.raises(ValueError, match="长度"):
        write_wwt(tmp_path / "bad.wwt", time, {"y": np.arange(9.0)})


def test_write_wwt_accepts_grafted_trailer(tmp_path):
    from pathlib import Path
    from mf4_analyzer.io.wwt_writer import extract_wwt_trailer

    root = Path(__file__).resolve().parent.parent
    template = root / "testdoc" / "wwt" / "YP_SS_000089.wwt"
    if not template.is_file():
        pytest.skip("testdoc trailer template missing")
    trailer = extract_wwt_trailer(template)
    time = np.arange(128, dtype=np.float64) * 0.001
    y = np.sin(time)
    path = tmp_path / "graft.wwt"
    write_wwt(
        path, time, {"y": y}, include_trailer_stub=False, trailer=trailer,
    )
    data = path.read_bytes()
    idx = data.find(b"DatenFenste2")
    assert idx > 0
    assert len(data) - idx == len(trailer)
    # count patched to 2 (Zeit + y)
    import struct
    assert struct.unpack_from("<I", data, idx + 13 + 8 + 6)[0] == 2
    groups = DataLoader.load_wwt(str(path))
    assert groups[0]["channels"] == ["Time", "y"]
