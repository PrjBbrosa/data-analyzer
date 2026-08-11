#!/usr/bin/env python3
"""Emit WinWert time-axis probes (2026-08-11, 机制已解出).

一轮 A/B/C/D + 二轮 E1 的回执把机制钉死了（台账见
``docs/analyzer/specs/2026-08-11-wwt-export-dual-compat-spec.md``）：

- 记录头 ``xkanalnr``（+0x9）显示**不读**（E1 改成 6，对话框仍显示 8）。
- 尾块头 +69 是**全局** X 曲线号，只决定哪条曲线被当 X 隐藏（探针 C）。
- 真正的逐曲线 X 引用在尾块**曲线记录**里：
  base = 尾块 + 171 + 曲线号×283，``+18`` 的 u16 就是 X 引用曲线号，
  **0 = 记录 0（Zeit）= 按时间显示**。用 WinWert 曲线设置对话框截图
  （DC2E: X 列 = 5,5,5,5,5,0,8,8,8）逐字段验证，13 个样本交叉一致。

本轮探针：

- ``probe_time_F_product_convert.wwt`` —— **主验收**：产品路径
  （DC2E 三通道 → 捆绑模板 + 时域显示 + 隐藏未写入曲线）。
- ``probe_time_G_dc2e_curve_x0.wwt`` —— DC2E 原件，**只**把逐曲线 X 引用
  清 0，其余一字节不动（最小机制证明）。
- ``probe_time_H_dc2e_full_display.wwt`` —— DC2E 原件 + 完整显示改写
  （逐曲线 X、全局 X、X 轴标签与 0–43 s 量程），数据不动。

Usage:
    PYTHONPATH=. .venv/bin/python tools/matlab_ports/emit_wwt_timeaxis_probes.py
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mf4_analyzer.io.wwt_format import _TRAILER_PREFIX, _cstr, load_wwt_groups
from mf4_analyzer.io import wwt_display as disp
from mf4_analyzer.io.wwt_inplace import _iter_records, convert_to_wwt

SRC = ROOT / "testdoc" / "答复__DC2E" / "NLTNP_DC2E_0011.wwt"
OUT = Path(__file__).resolve().parent / "wwt_export_candidates"


def curve_x_table(path) -> list[tuple[int, int, str]]:
    """(曲线号, X 引用, 标签) —— 与 WinWert 曲线设置对话框的 X 列同源。"""
    data = Path(path).read_bytes()
    return [
        (row["curve"], row["x_curve"], row["label"])
        for row in disp.read_curve_table(data) if row["curve"] > 0
    ]


def _load_measurement():
    groups = load_wwt_groups(SRC)
    group = max(groups, key=lambda g: len(g["data"]))
    frame = group["data"]
    channels = {
        name: frame[name].to_numpy()
        for name in group["channels"] if name != "Time"
    }
    units = {k: v for k, v in group["units"].items() if k != "Time"}
    return frame["Time"].to_numpy(), channels, units, group["source_metadata"]


def emit_f(time, channels, units, meta):
    out = OUT / "probe_time_F_product_convert.wwt"
    result = convert_to_wwt(
        out, time, channels, units=units,
        title=meta.get("title", ""),
        comment="TraceLab time-axis probe F (product path)",
    )
    print(f"F: {out.name}  n={result.template_n}  time_axis={result.time_axis}")
    return out


def emit_g():
    data = bytearray(SRC.read_bytes())
    trailer = data.find(_TRAILER_PREFIX)
    touched = 0
    for rec in _iter_records(bytes(data), include_unknown=True):
        if rec.index == 0:
            continue
        disp.write_curve(data, trailer, rec.index, x_curve=0)
        touched += 1
    out = OUT / "probe_time_G_dc2e_curve_x0.wwt"
    out.write_bytes(data)
    print(f"G: {out.name}  {touched} 条曲线的 X 引用→0（其余不动）")
    return out


def emit_h():
    data = bytearray(SRC.read_bytes())
    records = _iter_records(bytes(data), include_unknown=True)
    zeit = max((r for r in records if r.tag == "Zeit"), key=lambda r: r.n)
    t0 = zeit.c
    t1 = t0 + zeit.b * (zeit.n - 1)
    trailer = disp.find_trailer(bytes(data))
    for rec in records:
        struct.pack_into("<H", data, rec.rec_off + 0x9, 0)
    disp.force_time_axis(data, trailer, [r.index for r in records], t0, t1)
    out = OUT / "probe_time_H_dc2e_full_display.wwt"
    out.write_bytes(data)
    axis = disp.read_curve(bytes(data), trailer, 0)
    print(f"H: {out.name}  完整显示改写，X 轴 [{t0:.1f}, {t1:.1f}] s "
          f"绘图比例={axis['scale']:.3f}（K={axis['plot_k']:.0f}）")
    return out


def main() -> int:
    if not SRC.is_file():
        print(f"跳过：找不到 {SRC}（testdoc 样本不入库）")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    print("原件 X 引用（应指向角度通道）:")
    for c, x, label in curve_x_table(SRC):
        print(f"  curve{c}: X={x:<3} {label!r}")
    print()
    time, channels, units, meta = _load_measurement()
    probes = [emit_f(time, channels, units, meta), emit_g(), emit_h()]
    print("\n自检：")
    for p in probes:
        groups = load_wwt_groups(p)
        xs = {x for _, x, _ in curve_x_table(p)}
        print(f"  {p.name}: X 引用集合={xs}, "
              f"{sum(len(g['channels']) - 1 for g in groups)} 通道可回读")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
