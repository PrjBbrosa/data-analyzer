"""Parser for WinWert binary time-data files (.wwt).

文件布局（全部小端）：0x211 字节文件头（魔数 ``WinWert<版本号>`` + 标题/注释
char[256] + u16 记录总数），随后是「156 字节记录头 + 内联数据」连续排列。
``Zeit`` 记录定义时间轴（无数据区），其后的数据通道从属于最近的 ``Zeit``；
``DatenFenste2`` 尾块是显示配置；正文分组在本模块，完整文档（含全部显示块）
由 ``wwt_document.parse_wwt_document`` 一次解析。

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

import numpy as np

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
    from .wwt_document import parse_wwt_document
    return list(parse_wwt_document(fp).groups)
