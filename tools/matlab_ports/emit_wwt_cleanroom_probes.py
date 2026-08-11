#!/usr/bin/env python3
"""Clean-room WWT 导出候选（WinWert 人工开箱验证用）。

来龙去脉见 ``docs/analyzer/specs/2026-08-11-wwt-export-dual-compat-spec.md``。
一句话：WinWert 自己把 ``.mat`` 导成 ``.wwt`` 时，写的正文就是
``Zeit + N×Real(float64)``，与 ``wwt_writer`` 的记录头逐字节一致；显示配置全在
尾块曲线表里。于是产品路径 = 自写正文 + 按目标通道重建的真实显示尾块，
点数原生保留、通道数不限、零量化。

产出：

- ``probe_cleanroom_I_native.wwt`` —— DC2E 三通道，原生 43062 点 float64。
- ``probe_cleanroom_K_8ch.wwt`` —— 8 条合成通道 5000 点（超过模板槽位数）。

Usage:
    PYTHONPATH=. .venv/bin/python tools/matlab_ports/emit_wwt_cleanroom_probes.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mf4_analyzer.io import wwt_display as disp
from mf4_analyzer.io.wwt_format import load_wwt_groups
from mf4_analyzer.io.wwt_export import export_wwt

SRC = ROOT / "testdoc" / "答复__DC2E" / "NLTNP_DC2E_0011.wwt"
OUT = Path(__file__).resolve().parent / "wwt_export_candidates"


def describe(path: Path) -> None:
    data = path.read_bytes()
    print(f"### {path.name}  {len(data) / 1e6:.2f} MB")
    for row in disp.read_curve_table(data):
        who = "X轴行 " if row["curve"] == 0 else f"curve{row['curve']}"
        print(f"   {who} X={row['x_curve']} vis={row['visible']} "
              f"[{row['lo']:>9.4g},{row['hi']:>9.4g}] K={row['plot_k']:.0f} "
              f"tick={row['ticks']:g} color={row['color_index']}"
              f"/{row['color_rgb'].hex()} {row['label']!r}")
    text = disp.read_display_text(data[disp.find_trailer(data):])
    print(f"   文本块: title={text.get('title')!r} "
          f"comment={text.get('comment')!r} 页脚={text.get('annotations')}")
    groups = load_wwt_groups(path)
    print(f"   TraceLab 回读: {len(groups)} 组 / "
          f"{sum(len(g['channels']) - 1 for g in groups)} 通道 / "
          f"{len(groups[0]['data'])} 点")


def main() -> int:
    if not SRC.is_file():
        print(f"跳过：找不到 {SRC}（testdoc 样本不入库）")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)

    group = max(load_wwt_groups(SRC), key=lambda g: len(g["data"]))
    time = group["data"]["Time"].to_numpy()
    channels = {
        n: group["data"][n].to_numpy()
        for n in group["channels"] if n != "Time"
    }
    units = {k: v for k, v in group["units"].items() if k != "Time"}
    i_path = OUT / "probe_cleanroom_I_native.wwt"
    r_i = export_wwt(
        i_path, time, channels, units=units,
        title=group["source_metadata"].get("title", ""),
        comment="TraceLab clean-room, native rate",
    )

    n = 5000
    t2 = np.arange(n, dtype=np.float64) * 0.0005
    synth = {
        f"Ch{i + 1}": (i + 1) * np.sin(2 * np.pi * (i + 1) * 0.7 * t2)
        for i in range(8)
    }
    k_path = OUT / "probe_cleanroom_K_8ch.wwt"
    r_k = export_wwt(
        k_path, t2, synth, units={k: "Nm" for k in synth},
        title="TraceLab 8-channel growth probe",
        comment="clean-room, 8 channels > template slots",
    )

    for result in (r_i, r_k):
        print(f"{result.path.name}: {result.mode} · {result.summary}")
    print()
    for path in (i_path, k_path):
        describe(path)

    # 保真自检：clean-room 不重采样、不量化，回读必须逐点精确。
    back = load_wwt_groups(i_path)[0]["data"]
    for name, values in channels.items():
        np.testing.assert_allclose(
            back[name].to_numpy(), values, rtol=0, atol=0
        )
    print("\n自检：I 的三条通道回读逐点精确一致 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
