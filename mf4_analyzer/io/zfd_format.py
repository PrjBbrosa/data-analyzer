"""Parser for ZFGE2 .zfd measurement files (ZwickRoell / TestRunPRO).

文件布局（全部小端）：纯文本头（\\n 分隔行，魔数行 ``ZFGE2``，第 2 行版本、
第 3 行标题，随后是采集元数据和一段 ``~`` 预览网格——网格不解析），后接若干
时域通道块。每个通道由一个 ASCII 标记引导，形如 ``E17: travel`` /
``A2:  Szyl 1``（``<字母><数字>: <空格><名字>``）。

逐通道结构（marker 起始偏移记为 off）：
- 前置头（marker 前 6 字节）：u16@off-6（实测=4，忽略）、u16@off-4=采样数
  count、u16@off-2=0。
- 仅第一个通道在 off-14 处多一个 float64 = dt（=0.001 → fs=1000）。后续通道
  前面紧挨上一通道的 float32 数据、没有干净的 dt，所以 dt 只从第一个通道读、
  全通道共用。
- marker 文本行 ``<名字>\\n``，单位行 ``<单位>\\n``（可能空）。
- 单位行末 \\n 之后：2 字节 pad + 2 个 float64（显示范围 min/max，仅参考）+
  float32[count] 数据（数据即物理值，无缩放）。
"""
from __future__ import annotations
import re
import struct
from pathlib import Path

import numpy as np
import pandas as pd

_MAGIC = b"ZFGE2"
_PRE_HEADER = 6          # 前置头字节数（u16×3）
_DISP_OFFSET = 2 + 16    # 单位行 \n 之后：2 pad + 2 float64
_DEFAULT_FS = 1000.0

# 候选 marker：字母 + 1~3 位数字 + 冒号 + 空白。必须再结构校验才采纳，
# 防止在 float32 数据里踩到假标记。
_MARKER_RE = re.compile(rb"[A-Za-z]\d{1,3}:\s")


def _text_line(raw: bytes) -> str:
    return raw.decode("latin-1", "replace")


def _try_channel(data: bytes, off: int):
    """结构校验单个候选 marker；通过则返回解析出的通道 dict，否则 None。

    校验（防假标记）：off-4 的 count 是合理正整数；marker 后能读到
    ``名字\\n单位\\n``；两行都是可打印文本；数据区 [data_start, data_end)
    完整落在文件内。链式相邻性（data_end 后紧邻下一 marker 前置头）由调用方
    按已采纳通道的数据区跨度过滤，避免采纳落在别的通道数据区里的假标记。
    """
    size = len(data)
    if off < _PRE_HEADER:
        return None
    (count,) = struct.unpack_from("<H", data, off - 4)
    if count <= 0:
        return None

    nl1 = data.find(b"\n", off)
    if nl1 < 0:
        return None
    marker_line = _text_line(data[off:nl1])
    nl2 = data.find(b"\n", nl1 + 1)
    if nl2 < 0:
        return None
    unit = _text_line(data[nl1 + 1:nl2]).strip()

    # 名字行/单位行必须是可打印文本（含 CR 容忍）——数据区里的随机字节过不了
    if any(ord(ch) < 0x20 and ch not in "\r\t" for ch in marker_line + unit):
        return None
    # marker 文本必须真是 `<id>: <name>` 形状
    m = re.match(r"^([A-Za-z]\d{1,3}):\s*(.*)$", marker_line)
    if not m:
        return None
    marker_id, name = m.group(1), m.group(2).strip()

    disp_pos = nl2 + 1 + 2
    data_start = nl2 + 1 + _DISP_OFFSET
    data_end = data_start + count * 4
    if data_end > size:
        return None
    disp_min, disp_max = struct.unpack_from("<dd", data, disp_pos)
    values = np.frombuffer(
        data, dtype="<f4", count=count, offset=data_start).astype(np.float64)

    return {
        "off": off, "marker_id": marker_id, "name": name, "unit": unit,
        "count": count, "disp_min": disp_min, "disp_max": disp_max,
        "data_end": data_end, "values": values,
    }


def load_zfd_groups(fp):
    """解析 .zfd，返回与 ``DataLoader.load_hdf`` 同形状的 groups 列表。

    所有通道 count 相同、共用 dt → 合并为一组；count 不同的（未来文件）按
    wwt 的多组逻辑各成一组。名字重复时按 marker id 消歧（如 ``Szyl 1 [E5]``）。
    """
    name = Path(fp).name
    data = Path(fp).read_bytes()

    if not data.startswith(_MAGIC):
        raise ValueError(f"不是有效的 ZFD 文件（缺少 ZFGE2 魔数）: {name}")

    # 文本头取版本行/标题行（\n 分隔，魔数为第 1 行）
    head_lines = data[:4096].split(b"\n")
    version = _text_line(head_lines[1]).strip() if len(head_lines) > 1 else ""
    title = _text_line(head_lines[2]).strip() if len(head_lines) > 2 else ""

    # 结构校验每个候选；跳过落在已采纳通道数据区内的假标记。
    channels = []
    last_data_end = 0
    for match in _MARKER_RE.finditer(data):
        off = match.start()
        if off < last_data_end:
            continue
        ch = _try_channel(data, off)
        if ch is None:
            continue
        channels.append(ch)
        last_data_end = ch["data_end"]

    if not channels:
        raise ValueError(f"ZFD: 未发现任何有效通道: {name}")

    # dt 只从第一个通道读（off-14 的 float64）；不合理则回退 fs=1000 并标记推定。
    first_off = channels[0]["off"]
    fs_estimated = True
    dt = 1.0 / _DEFAULT_FS
    if first_off >= 14:
        (cand_dt,) = struct.unpack_from("<d", data, first_off - 14)
        if 0.0 < cand_dt < 1.0:
            dt = cand_dt
            fs_estimated = False

    smeta_base = {
        "source_kind": "zfd", "version": version, "title": title,
        "source_filename": name, "fs_estimated": fs_estimated,
    }

    # 按 count 分组（dt 全通道共用）
    order = []
    by_count = {}
    for ch in channels:
        by_count.setdefault(ch["count"], []).append(ch)
        if ch["count"] not in order:
            order.append(ch["count"])

    groups = []
    for count in order:
        chs = by_count[count]
        t = np.arange(count, dtype=np.float64) * dt
        frame = {"Time": t}
        units = {}
        cmeta = {}
        for ch in chs:
            # 组内同名消歧：追加 marker id（如两个 Szyl 1 → Szyl 1 [E5]）
            col = ch["name"] or ch["marker_id"]
            if col in frame:
                col = f"{ch['name']} [{ch['marker_id']}]"
                while col in frame:
                    col = f"{col}_"
            frame[col] = ch["values"]
            units[col] = ch["unit"]
            cmeta[col] = {
                "marker_id": ch["marker_id"], "unit": ch["unit"],
                "display_min": ch["disp_min"], "display_max": ch["disp_max"],
            }
        groups.append({
            "data": pd.DataFrame(frame), "channels": list(frame.keys()),
            "units": units, "channel_metadata": cmeta,
            "source_metadata": dict(smeta_base),
            "_count": count,
        })

    fs = (1.0 / dt) if dt > 0 else _DEFAULT_FS
    for g in groups:
        count = g.pop("_count")
        g["label_suffix"] = "" if len(groups) == 1 else f"{fs:.0f}Hz·{count}"
    return groups
