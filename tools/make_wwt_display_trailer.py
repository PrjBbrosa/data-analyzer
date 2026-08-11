#!/usr/bin/env python3
"""生成 clean-room 导出用的 WinWert 显示尾块资源。

来源是 **WinWert 自己写的文件**：用户用 WinWert 直接把 ``.mat`` 导成 ``.wwt``
（`testdoc/exporttowwt/175rpm_-45deg-270tighten.wwt`）。那份文件的正文正是
clean-room 形状（``Zeit`` + N×``Real`` float64），所以它的 ``DatenFenste2``
尾块是「WinWert 为这种正文写的显示配置」——拿它当骨架，验证结论可以直接迁移。

抽取时把源文件的会话文本清空（页脚注释 / 标题 / 注释 / 署名），资源本身不带
任何客户的台架编号、试验规范或操作员姓名；每次导出再写入本次的标题与注释。

Usage:
    PYTHONPATH=. .venv/bin/python tools/make_wwt_display_trailer.py [源.wwt]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mf4_analyzer.io import wwt_display as disp

DEFAULT_SRC = ROOT / "testdoc" / "exporttowwt" / "175rpm_-45deg-270tighten.wwt"
DEST = ROOT / "assets" / "wwt" / "winwert_display_trailer.bin"


def main(argv: list[str]) -> int:
    src = Path(argv[1]) if len(argv) > 1 else DEFAULT_SRC
    if not src.is_file():
        print(f"找不到源文件: {src}（testdoc 样本不入库）")
        return 1
    data = src.read_bytes()
    start = disp.find_trailer(data)
    if start < 0:
        print(f"{src} 没有 DatenFenste 尾块")
        return 1
    trailer = data[start:]
    before = disp.read_display_text(trailer)
    trailer = disp.set_display_text(
        trailer, title="", comment="", annotations=(), editor="TraceLab",
    )
    after = disp.read_display_text(trailer)

    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_bytes(trailer)
    print(f"源: {src.name}  尾块 {len(trailer)} B  "
          f"曲线表 {disp.declared_record_count(trailer, 0)} 条记录")
    print(f"→ {DEST.relative_to(ROOT)}")
    print("清空的会话文本:")
    for line in before["annotations"]:
        if line:
            print(f"  - {line[:70]!r}")
    for key in ("title", "comment", "editor"):
        if before[key]:
            print(f"  {key}: {before[key]!r} → {after[key]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
