"""Parser for WinWert binary time-data files (.wwt).

文件布局（全部小端）：0x211 字节文件头（魔数 ``WinWert<版本号>`` + 标题/注释
char[256] + u16 记录总数），随后是「156 字节记录头 + 内联数据」连续排列。
``Zeit`` 记录定义时间轴（无数据区），其后的数据通道从属于最近的 ``Zeit``；
``DatenFenste2`` 尾块是显示配置，忽略。

版本策略：不做版本白名单——实测 200401 版的记录布局与 091293 完全相同，
硬拒绝会误伤。魔数前缀是 ``WinWert`` 即尝试解析，靠记录级结构验证把关：
布局真不同的版本会在第一条记录就撞上未知标签且无法重同步，此时报错并带上
版本号提示布局不兼容。

容错机制：
- ``count``（0x20F 的记录总数）不可靠——不能当作精确记录数硬走。每条记录
  开始前先探测 ``DatenFenste`` 尾块标记，命中即提前收尾。
- ``Pars``（计算通道：数据区开头是 NUL 结尾的公式串 + 变长参数结构，记录头
  里没有长度字段）和未知标签的记录，通过逐字节向前扫描下一条结构上合法的
  记录头 / 尾块标记来确定数据区大小（重同步），跳过并记入 skipped_channels。
  重同步认头时只校验名称/单位的 **NUL 前缀**；NUL 后的脏填充（见 DC2E_0011）
  不得挡掉真实 ``Zeit``。
"""
from __future__ import annotations
import struct
from pathlib import Path

import numpy as np
import pandas as pd

_MAGIC_PREFIX = b"WinWert"
_TRAILER_PREFIX = b"DatenFenste"
_HEADER_SIZE = 0x211
_REC_HEADER_SIZE = 156

# Zeit 样本数低于此值的块整体视为曲线定义块（限值/评价曲线），不产组。
# 依据：实测真实时域测量最短 2293 点，曲线定义最长 65 点，两侧余量都很大。
_MIN_TIMESERIES_SAMPLES = 100

# 数据标签 -> numpy dtype。Zeit 无数据区，单列 None。
# 注意 ``int1`` 实测是 2 字节 int16（标签名里的 1 不是字节数）。
_TAG_DTYPES = {
    "Zeit": None,
    "Real": np.dtype("<f8"),
    "int1": np.dtype("<i2"),
    "Long": np.dtype("<i4"),
    "Floa": np.dtype("<f4"),
}

# 重同步扫描认可的 5 字节标签（4 字符 + NUL）。Pars 也算合法记录头：
# 实测计算通道会连排出现，把它排除会将后一条 Pars 误吞进前一条的数据区。
_SCAN_TAGS = {t.encode("ascii") + b"\0" for t in (*_TAG_DTYPES, "Pars")}


def _cstr(raw: bytes) -> str:
    """定长字段 -> str：NUL 截断；GBK 的 ° 被写成 A1 E3 双字节，替换成
    latin-1 的 B0 再解码（其余字节实测均为 latin-1 可解）。"""
    i = raw.find(b"\0")
    if i >= 0:
        raw = raw[:i]
    raw = raw.replace(b"\xa1\xe3", b"\xb0")
    return raw.decode("latin-1", "replace").strip()


def _looks_like_record_header(data: bytes, pos: int) -> bool:
    """重同步用的记录头结构判定。判据要严——扫描是在未知记录的数据区里
    逐字节踩点，宽了会把数据区里的假标签当记录头、让游标错位：
    - 5 字节标签 ∈ 已知集合（第 5 字节必须是 NUL）；
    - 样本数 u32 在 (0, 50_000_000) 内；
    - 名称[40] / 单位[17] 的 **NUL 前缀**是可打印 latin-1（字节 ∈ {0}∪[0x20,0xFF]）。

    NUL **之后**的填充不检查：WinWert 有时在 ``Time\\0`` / ``s\\0`` 后面留下
    未初始化脏字节（DC2E_0011 第二段 Zeit）。若要求整段 40/17 字节洁净，
    Pars 重同步会假阴性跳过真实 Zeit，后续主测量通道全部因 n 不匹配被丢。
    """
    if pos + _REC_HEADER_SIZE > len(data):
        return False
    if data[pos:pos + 5] not in _SCAN_TAGS:
        return False
    (n,) = struct.unpack_from("<I", data, pos + 5)
    if not 0 < n < 50_000_000:
        return False
    for off, length in ((0x1b, 40), (0x43, 17)):
        field = data[pos + off:pos + off + length]
        end = field.find(b"\0")
        prefix = field if end < 0 else field[:end]
        for byte in prefix:
            if byte < 0x20:
                return False
    return True


def load_wwt_groups(fp):
    """解析 .wwt，返回与 ``DataLoader.load_hdf`` 同形状的 groups 列表。

    分组规则：时间轴参数 (n, dt, t0) 完全相同的 Zeit 块合并为一组；只导入
    样本数与所属 Zeit 相等的时域通道。公差带/评价曲线（n 不匹配或整块短于
    ``_MIN_TIMESERIES_SAMPLES``）与 Pars 计算通道跳过并记入
    ``source_metadata['skipped_channels']``。
    """
    name = Path(fp).name
    data = Path(fp).read_bytes()
    size = len(data)

    if size < 15 or not data.startswith(_MAGIC_PREFIX):
        raise ValueError(f"不是有效的 WWT 文件（缺少 WinWert 魔数）: {name}")
    version = _cstr(data[:15])[len(_MAGIC_PREFIX):]
    if size < _HEADER_SIZE:
        raise ValueError(f"WWT 文件截断/损坏（文件头不完整）: {name}")

    title = _cstr(data[0x00F:0x10F])
    comment = _cstr(data[0x10F:0x20F])
    (count,) = struct.unpack_from("<H", data, 0x20F)

    blocks = []          # 每个 Zeit 块: {axis 参数, curve_def, channels: [...]}
    skipped = []
    pos = _HEADER_SIZE
    records_parsed = 0
    while records_parsed < count:
        # count 声明数不可靠：尾块提前出现即收尾（记录数可少于 count）
        if data[pos:pos + len(_TRAILER_PREFIX)] == _TRAILER_PREFIX:
            break
        if pos + _REC_HEADER_SIZE > size:
            raise ValueError(
                f"WWT 文件截断/损坏: 第 {records_parsed + 1} 条记录头越过文件"
                f"末尾（偏移 0x{pos:x}）: {name}")
        tag = _cstr(data[pos:pos + 5])
        n, _u2 = struct.unpack_from("<IH", data, pos + 5)
        ch_name = _cstr(data[pos + 0x1b:pos + 0x1b + 40])
        unit = _cstr(data[pos + 0x43:pos + 0x43 + 17])
        src_fname = _cstr(data[pos + 0x54:pos + 0x54 + 48])
        a, b, c = struct.unpack_from("<ddd", data, pos + 0x84)
        data_pos = pos + _REC_HEADER_SIZE

        if tag not in _TAG_DTYPES:
            # Pars（计算通道）/ 未知标签：头里没有数据长度字段，逐字节向前
            # 扫描下一条合法记录头或尾块标记来重同步。扫不到就只能硬错——
            # 猜大小继续走会让后续所有记录错位。
            scan = data_pos
            while scan < size:
                if (data[scan:scan + len(_TRAILER_PREFIX)] == _TRAILER_PREFIX
                        or _looks_like_record_header(data, scan)):
                    break
                scan += 1
            else:
                raise ValueError(
                    f"WWT 记录解析失败: 偏移 0x{pos:x} 处标签"
                    f" {data[pos:pos + 5]!r} 未知且无法重同步"
                    f"（版本 {version}，可能布局不兼容）: {name}")
            if tag == "Pars":
                # 数据区开头是 NUL 结尾的公式串，附在名字后便于识别
                formula = _cstr(data[data_pos:min(scan, data_pos + 256)])
                skipped.append(
                    f"{ch_name} (公式: {formula})" if formula else ch_name)
            else:
                skipped.append(ch_name or f"<{tag}>")
            pos = scan
            records_parsed += 1
            continue

        dtype = _TAG_DTYPES[tag]
        dlen = 0 if dtype is None else n * dtype.itemsize
        if data_pos + dlen > size:
            raise ValueError(
                f"WWT 文件截断/损坏: 通道 {ch_name!r} 数据区越过文件末尾"
                f"（偏移 0x{data_pos:x} + {dlen}B > {size}B）: {name}")

        if tag == "Zeit":
            blocks.append({"n": n, "dt": b, "t0": c, "channels": [],
                           "curve_def": n < _MIN_TIMESERIES_SAMPLES})
        else:
            if not blocks:
                raise ValueError(
                    f"WWT 结构异常: 通道 {ch_name!r} 出现在首个 Zeit 记录之前"
                    f"（偏移 0x{pos:x}）: {name}")
            blk = blocks[-1]
            if blk["curve_def"] or n != blk["n"]:
                # 短块整块是限值/评价曲线；n 不匹配的是公差带/曲线定义
                skipped.append(ch_name)
            else:
                raw = np.frombuffer(data, dtype=dtype, count=n, offset=data_pos)
                blk["channels"].append({
                    "name": ch_name, "unit": unit, "tag": tag,
                    "a": a, "c": c, "source_filename": src_fname,
                    "rec_idx": records_parsed + 1,
                    # 物理值 = raw*a + c（Real 存的已是物理值，此时 a=1 c=0，
                    # 公式同样成立；a 可为负）
                    "values": raw.astype(np.float64) * a + c,
                })
        pos = data_pos + dlen
        records_parsed += 1

    # 按时间轴参数合并 Zeit 块（同文件内 double 位级一致，可直接比较）。
    merged = {}          # (n, dt, t0) -> {"n","dt","t0","channels"}
    order = []
    for blk in blocks:
        if not blk["channels"]:
            continue     # 曲线定义块 / 没有任何时域通道的块 → 不产出组
        key = (blk["n"], blk["dt"], blk["t0"])
        if key not in merged:
            merged[key] = {"n": blk["n"], "dt": blk["dt"], "t0": blk["t0"],
                           "channels": []}
            order.append(key)
        merged[key]["channels"].extend(blk["channels"])

    smeta_base = {
        "source_kind": "wwt", "title": title, "comment": comment,
        "winwert_version": version,
        "records_declared": count, "records_parsed": records_parsed,
        "skipped_channels": skipped, "source_filename": name,
    }
    groups = []
    for key in order:
        blk = merged[key]
        t = blk["t0"] + np.arange(blk["n"], dtype=np.float64) * blk["dt"]
        frame = {"Time": t}
        units = {}
        cmeta = {}
        renamed = []
        for ch in blk["channels"]:
            # 组内同名消歧：追加文件内记录序号（同 load_hdf 的做法），
            # 避免后者静默覆盖前者。
            preferred = ch["name"]
            col = preferred
            if col in frame:
                col = f"{ch['name']} [{ch['rec_idx']}]"
                while col in frame:
                    col = f"{col}_"
                renamed.append({"original": preferred, "renamed": col})
            frame[col] = ch["values"]
            units[col] = ch["unit"]
            cmeta[col] = {
                "tag": ch["tag"], "unit": ch["unit"],
                "scale_a": ch["a"], "offset_c": ch["c"],
                "source_filename": ch["source_filename"],
                "record_index": ch["rec_idx"],
            }
        smeta = dict(smeta_base)
        smeta["renamed_channels"] = renamed
        groups.append({
            "data": pd.DataFrame(frame), "channels": list(frame.keys()),
            "units": units, "channel_metadata": cmeta,
            "source_metadata": smeta,
            "axis_key": key,
        })

    if not groups:
        raise ValueError(f"WWT: 没有可导入的时域通道: {name}")

    # 只有一组时不加后缀；多组时用「采样率·点数」区分（如 1000Hz·9182）。
    for g in groups:
        n, dt, _t0 = g.pop("axis_key")
        if len(groups) == 1:
            g["label_suffix"] = ""
        else:
            fs = (1.0 / dt) if dt > 0 else 0.0
            g["label_suffix"] = f"{fs:.0f}Hz·{n}"
    return groups
