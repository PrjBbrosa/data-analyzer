"""WinWert ``DatenFenste2`` 显示块：曲线表与文本块的读写。

WWT 的正文（记录）只管数据，**「打开后长什么样」全部由尾块 `DatenFenste2`
决定**。本模块是这块知识的唯一归属地：`wwt_inplace`（模板原地改写）与
`wwt_export`（clean-room 导出）都从这里取。

## 曲线表

基址 = 尾块起点 + 171，每条 283 字节，**表项 i 对应记录 i**（0 基，含 Pars /
未知记录）。表项 0 是 Zeit，也就是曲线设置对话框底部的「X Axis」行。

| 偏移 | 类型 | 含义 |
| --- | --- | --- |
| +0 / +8 | double | 轴下限 / 上限 |
| +18 | u16 | **X 轴引用曲线号；0 = 记录 0（Zeit）= 按时间显示** |
| +44 | double | **轴原点 = −(上限 × 绘图比例) − C**（C 是版式常量，见下） |
| +20 / +22 | u16 | Selector 勾选 / 是否绘制 |
| +26 / +34 | double | 主刻度间隔 / 网格间隔 —— **写 0 = 交给 WinWert 自动**（厂商自己就写 0） |
| +52 | double | 绘图比例 = K / 轴跨度（见下） |
| +60 | char[64] | 轴标签 ``Name [unit]`` |
| +263 | u32 | 颜色下拉序号 |
| +271 | 3×u8 | 颜色 RGB（与序号配套写） |

尾块头另有 `+27` u32 记录数、`+69` u16 全局 X 曲线号（逐曲线 +18 可覆盖它）。

**轴原点 +44 必须跟着量程改**：`+44 = −(hi × 比例) − C`，C 在文件内是常量
（8 个样本、几十条曲线逐条验证；实测 C 因版式而异：100 / 50 / 250，X 轴行
另有一套）。原型曲线的下限恰好是 0 时 `hi × 比例` 正好等于 K，照抄原型的
+44 就等于宣称「上限在满幅处」——下限为负的曲线于是被顶上去半格，**首帧
只画出正半边**，刷新后才归位（2026-08-11 实测）。

**刻度写 0**：WinWert 自己的导出（含 X 轴行）全部写 0（= 自动），照抄即可。

**颜色**：WinWert 自己的导出按**曲线序号循环取色**（curve1..6 = 序号 1..6）。
不给每条曲线单独配色的话，从同一个原型记录复制出来的曲线会全是一个颜色。

**+52 绘图比例**：`轴跨度 × +52 = K`，K 在文件内按方向恒定——实测 X 侧 4200、
Y 侧 2400（U-Can 版式 X 侧 2000），正是对话框 `Window size (mm) 210 × 120` 的
20 倍。**WinWert 首帧按 +52 作图**，只改轴范围不同步它，打开时数据会挤成左边
一条细带，手动刷新后才正常。

## Log2 文本块

`Log2` 标记之后是 4 条 201 字节的注释行（印在图下方的页脚）、101 字节的标题与
注释副本、51 字节的「日期/编辑者/来源」字段，全部是 NUL 填充定长缓冲。转换出来
的文件必须**清掉模板继承的台架 / 试验规范 / 操作员**文本，否则会冒充别人的测量。

来源与验证：`docs/analyzer/specs/2026-08-11-wwt-export-dual-compat-spec.md`
（用户在 WinWert 曲线设置对话框里的截图逐字段比对 + WinWert 自己写的
``.mat`` 导出文件交叉印证）。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

from .wwt_format import _TRAILER_PREFIX
from .wwt_writer import _encode_field

TRAILER_PREFIX = _TRAILER_PREFIX

RECORD_COUNT_OFF = 27
GLOBAL_X_OFF = 69

CURVE_BASE = 171
CURVE_STRIDE = 283
CURVE_FROM = 0
CURVE_TO = 8
CURVE_X = 18
CURVE_ORIGIN = 44
CURVE_SELECTOR = 20
CURVE_VISIBLE = 22
CURVE_TICKS = 26
CURVE_GRID = 34
CURVE_SCALE = 52
CURVE_LABEL = 60
CURVE_LABEL_LEN = 64
CURVE_COLOR_INDEX = 263
CURVE_COLOR_RGB = 271

# WinWert 颜色下拉的序号 → RGB。从 testdoc 样本与 WinWert 自产的 .mat 导出
# 对读得到（对话框里的名字：red / green / dark blue / … 与 RGB 一一对上）。
# 序号 7 语料里没出现过，跳过；序号 0 是黑色，留给 X 轴行。
CURVE_PALETTE: tuple[tuple[int, bytes], ...] = (
    (1, b"\xff\x00\x00"),   # red
    (2, b"\x00\xff\x00"),   # green
    (3, b"\x00\x00\x80"),   # dark blue
    (4, b"\xff\x00\xff"),   # magenta
    (5, b"\x00\x00\xff"),   # blue
    (6, b"\x80\x80\x00"),   # olive
    (8, b"\x00\xff\xff"),   # aqua
    (9, b"\x7f\x00\x00"),   # maroon
)
AXIS_COLOR: tuple[int, bytes] = (0, b"\x00\x00\x00")   # black

# 尾块至少要装得下 X 轴行，才谈得上改显示配置。
MIN_TRAILER_LEN = CURVE_BASE + CURVE_STRIDE
TIME_AXIS_LABEL = "Time [s]"

_LOG_MARKER = b"Log2"
_LOG_TEXT_OFF = 19
_ANNOTATION_COUNT = 4
_ANNOTATION_LEN = 201
_TITLE_LEN = 101
_EDITOR_GAP = 22
_EDITOR_LEN = 51


class WwtDisplayError(ValueError):
    """显示块结构不符合预期（尾块截断、曲线表越界等）。"""


def find_trailer(data: bytes) -> int:
    """尾块起点；没有尾块返回 -1。"""
    return data.find(TRAILER_PREFIX)


def curve_offset(trailer: int, curve: int) -> int:
    return trailer + CURVE_BASE + curve * CURVE_STRIDE


def declared_record_count(data: bytes, trailer: int) -> int:
    return struct.unpack_from("<I", data, trailer + RECORD_COUNT_OFF)[0]


def palette_color(position: int) -> tuple[int, bytes]:
    """按曲线位置取色，循环使用调色板（WinWert 自己也是这么配的）。"""
    return CURVE_PALETTE[max(0, position - 1) % len(CURVE_PALETTE)]


def read_curve(data: bytes, trailer: int, curve: int) -> dict | None:
    """单条曲线的显示配置；越界返回 ``None``。"""
    off = curve_offset(trailer, curve)
    if off < 0 or off + CURVE_STRIDE > len(data):
        return None
    lo, hi = struct.unpack_from("<dd", data, off + CURVE_FROM)
    ticks, grid = struct.unpack_from("<dd", data, off + CURVE_TICKS)
    (scale,) = struct.unpack_from("<d", data, off + CURVE_SCALE)
    raw = bytes(data[off + CURVE_LABEL:off + CURVE_LABEL + CURVE_LABEL_LEN])
    i = raw.find(b"\0")
    label = (raw[:i] if i >= 0 else raw).decode("latin-1", "replace").strip()
    return {
        "curve": curve,
        "label": label,
        "lo": lo,
        "hi": hi,
        "x_curve": struct.unpack_from("<H", data, off + CURVE_X)[0],
        "selected": struct.unpack_from("<H", data, off + CURVE_SELECTOR)[0],
        "visible": struct.unpack_from("<H", data, off + CURVE_VISIBLE)[0],
        "ticks": ticks,
        "grid": grid,
        "scale": scale,
        "plot_k": (hi - lo) * scale if hi > lo else 0.0,
        "origin": struct.unpack_from("<d", data, off + CURVE_ORIGIN)[0],
        "color_index": struct.unpack_from("<I", data, off + CURVE_COLOR_INDEX)[0],
        "color_rgb": bytes(data[off + CURVE_COLOR_RGB:off + CURVE_COLOR_RGB + 3]),
    }


def read_curve_table(data: bytes, trailer: int | None = None) -> list[dict]:
    """整张曲线表（表项 0 = X 轴行）。诊断 / 测试用。"""
    if trailer is None:
        trailer = find_trailer(data)
    if trailer < 0 or len(data) - trailer < MIN_TRAILER_LEN:
        return []
    count = declared_record_count(data, trailer)
    out = []
    for curve in range(max(0, min(count, 4096))):
        row = read_curve(data, trailer, curve)
        if row is None:
            break
        out.append(row)
    return out


def write_curve(
    data: bytearray, trailer: int, curve: int, *,
    label: str | None = None,
    lo: float | None = None,
    hi: float | None = None,
    x_curve: int | None = None,
    visible: bool | None = None,
    plot_k: float | None = None,
    origin_c: float | None = None,
    color: tuple[int, bytes] | None = None,
) -> None:
    """改写一条曲线（``curve`` = 记录序号）的显示配置。

    模板尾块未必装得下那么多曲线记录（极简尾块只有 256 B），越界静默跳过：
    显示配置是锦上添花，缺了不该让导出失败。
    """
    off = curve_offset(trailer, curve)
    if off < 0 or off + CURVE_STRIDE > len(data):
        return
    if x_curve is not None:
        struct.pack_into("<H", data, off + CURVE_X, int(x_curve) & 0xFFFF)
    if color is not None:
        index, rgb = color
        struct.pack_into("<I", data, off + CURVE_COLOR_INDEX, int(index))
        data[off + CURVE_COLOR_RGB:off + CURVE_COLOR_RGB + 3] = rgb[:3]
    if visible is not None:
        flag = 1 if visible else 0
        struct.pack_into("<H", data, off + CURVE_VISIBLE, flag)
        struct.pack_into("<H", data, off + CURVE_SELECTOR, flag)
    if label is not None:
        data[off + CURVE_LABEL:off + CURVE_LABEL + CURVE_LABEL_LEN] = (
            _encode_field(label, CURVE_LABEL_LEN)
        )
    if lo is not None and hi is not None and np.isfinite(lo) and np.isfinite(hi):
        if hi <= lo:
            hi = lo + 1.0
        struct.pack_into("<dd", data, off + CURVE_FROM, float(lo), float(hi))
        # 刻度/网格交给 WinWert 自动（写 0，同厂商自己的导出）。留着模板的
        # 非零间隔会让**首帧**按「跨度 ÷ 间隔」布轴，除不尽就各轴长短不一、
        # 总范围显示不全，刷新后才归位。
        struct.pack_into("<dd", data, off + CURVE_TICKS, 0.0, 0.0)
        # 绘图比例：WinWert 首帧按它作图，漏改会把数据挤成左边一条细带。
        if plot_k is not None and plot_k > 0.0:
            scale = plot_k / (hi - lo)
            struct.pack_into("<d", data, off + CURVE_SCALE, scale)
            # 轴原点：漏改会让下限为负的曲线首帧只画出正半边。
            if origin_c is not None and np.isfinite(origin_c):
                struct.pack_into(
                    "<d", data, off + CURVE_ORIGIN, -(hi * scale) - origin_c
                )


@dataclass(frozen=True)
class LayoutConstants:
    """版式常量：改轴范围时必须跟着重算的两个字段的锚点。

    ``plot_k`` —— 轴跨度 × ``+52``（绘图区尺寸 mm × 20）。
    ``origin_c`` —— ``−(hi × 比例) − +44``。
    两者都在文件内恒定，X 轴行与 Y 曲线各一套。
    """

    plot_k_x: float | None = None
    plot_k_y: float | None = None
    origin_c_x: float | None = None
    origin_c_y: float | None = None


def layout_constants(
    data: bytes, trailer: int, curves: Iterable[int]
) -> LayoutConstants:
    """从模板原始字节推出版式常量；Y 侧取中位数抗个别脏值。"""
    def of(curve: int) -> tuple[float, float] | None:
        row = read_curve(data, trailer, curve)
        if row is None or row["hi"] <= row["lo"] or row["scale"] <= 0.0:
            return None
        k = float(row["plot_k"])
        origin = row["origin"]
        if not np.isfinite(k) or k <= 0.0 or not np.isfinite(origin):
            return None
        return k, -(row["hi"] * row["scale"]) - origin

    axis = of(0)
    ys = [v for v in (of(c) for c in curves) if v is not None]
    return LayoutConstants(
        plot_k_x=axis[0] if axis else None,
        origin_c_x=axis[1] if axis else None,
        plot_k_y=float(np.median([v[0] for v in ys])) if ys else None,
        origin_c_y=float(np.median([v[1] for v in ys])) if ys else None,
    )


def force_time_axis(
    data: bytearray, trailer: int, curves: Sequence[int],
    t0: float, t1: float, layout: LayoutConstants | None = None,
) -> None:
    """把显示改成时域：每条曲线的 X 引用清 0（0 = 记录 0 = Zeit）。

    这是「打开后横坐标是时间」的决定性写入。模板曲线记录里的 X 引用指向
    角度/行程通道，不改就会把导出数据画成 Y vs 角度。
    """
    if trailer < 0 or len(data) - trailer < MIN_TRAILER_LEN:
        return
    struct.pack_into("<H", data, trailer + GLOBAL_X_OFF, 0)
    if not np.isfinite(t0) or not np.isfinite(t1) or t1 <= t0:
        t0, t1 = 0.0, 1.0
    if layout is None:
        layout = layout_constants(bytes(data), trailer, curves)
    write_curve(
        data, trailer, 0,
        label=TIME_AXIS_LABEL, lo=t0, hi=t1, x_curve=0,
        plot_k=layout.plot_k_x, origin_c=layout.origin_c_x, color=AXIS_COLOR,
    )
    for curve in curves:
        if curve != 0:
            write_curve(data, trailer, curve, x_curve=0)


def rebuild_display_trailer(
    template_trailer: bytes,
    channels: Sequence[tuple[str, float, float]],
    t0: float,
    t1: float,
) -> bytes:
    """按目标通道重建曲线表，其余段原样搬运。

    曲线表是 ``记录数 × 283`` 的连续数组，后面跟 ``Beschriftung`` 等变长段。
    重建后 clean-room 正文（任意点数 / 任意通道数）也能带上 WinWert 认可的
    显示配置。``channels`` 是 ``(标签, 下限, 上限)``，顺序即记录顺序。
    """
    if not template_trailer.startswith(TRAILER_PREFIX):
        raise WwtDisplayError("模板尾块不是 DatenFenste 块")
    src_records = struct.unpack_from(
        "<I", template_trailer, RECORD_COUNT_OFF
    )[0]
    table_end = CURVE_BASE + src_records * CURVE_STRIDE
    if src_records < 2 or table_end > len(template_trailer):
        raise WwtDisplayError(
            f"模板尾块曲线表越界（声明 {src_records} 条记录，尾块 "
            f"{len(template_trailer)} B）"
        )

    def proto(i: int) -> bytearray:
        off = CURVE_BASE + i * CURVE_STRIDE
        return bytearray(template_trailer[off:off + CURVE_STRIDE])

    layout = layout_constants(template_trailer, 0, range(1, src_records))

    def fill(buf: bytearray, label: str, lo: float, hi: float,
             k: float | None, c: float | None,
             color: tuple[int, bytes]) -> bytearray:
        holder = bytearray(CURVE_BASE) + buf
        write_curve(holder, 0, 0, label=label, lo=lo, hi=hi, x_curve=0,
                    visible=True, plot_k=k, origin_c=c, color=color)
        return holder[CURVE_BASE:]

    table = bytearray()
    table += fill(proto(0), TIME_AXIS_LABEL, t0, t1,
                  layout.plot_k_x, layout.origin_c_x, AXIS_COLOR)
    for i, (label, lo, hi) in enumerate(channels, start=1):
        # 每条曲线单独配色：所有曲线都从同一个原型记录复制，不改就全是一个颜色。
        table += fill(proto(1), label, lo, hi,
                      layout.plot_k_y, layout.origin_c_y, palette_color(i))

    out = bytearray(template_trailer[:CURVE_BASE])
    out += table
    out += template_trailer[table_end:]
    struct.pack_into("<I", out, RECORD_COUNT_OFF, 1 + len(channels))
    struct.pack_into("<H", out, GLOBAL_X_OFF, 0)
    return bytes(out)


def _log_block(trailer: bytes) -> int:
    """``Log2`` 文本块的首条注释槽偏移；找不到返回 -1。"""
    idx = trailer.find(_LOG_MARKER)
    if idx < 0:
        return -1
    return idx + _LOG_TEXT_OFF


def set_display_text(
    trailer: bytes, *,
    title: str | None = None,
    comment: str | None = None,
    annotations: Sequence[str] | None = None,
    editor: str | None = None,
) -> bytes:
    """改写 Log2 文本块（页脚注释 / 标题 / 注释 / 来源署名）。

    模板继承下来的注释行会把别人的台架编号、试验规范、操作员印在导出图的
    页脚上。``annotations=()`` 即全部清空。字段是 NUL 填充定长缓冲，超长按
    字段宽度截断。没有 ``Log2`` 块（极简尾块）时原样返回。
    """
    base = _log_block(trailer)
    if base < 0:
        return trailer
    out = bytearray(trailer)
    title_off = base + _ANNOTATION_COUNT * _ANNOTATION_LEN
    comment_off = title_off + _TITLE_LEN
    editor_off = comment_off + _TITLE_LEN + _EDITOR_GAP

    def put(off: int, size: int, text: str) -> None:
        if off + size <= len(out):
            out[off:off + size] = _encode_field(text, size)

    if annotations is not None:
        lines = list(annotations)[:_ANNOTATION_COUNT]
        lines += [""] * (_ANNOTATION_COUNT - len(lines))
        for i, line in enumerate(lines):
            put(base + i * _ANNOTATION_LEN, _ANNOTATION_LEN, line)
    if title is not None:
        put(title_off, _TITLE_LEN, title)
    if comment is not None:
        put(comment_off, _TITLE_LEN, comment)
    if editor is not None:
        put(editor_off, _EDITOR_LEN, editor)
    return bytes(out)


def read_display_text(trailer: bytes) -> dict:
    """Log2 文本块的当前内容（诊断 / 测试用）。"""
    base = _log_block(trailer)
    if base < 0:
        return {}

    def get(off: int, size: int) -> str:
        raw = bytes(trailer[off:off + size])
        i = raw.find(b"\0")
        return (raw[:i] if i >= 0 else raw).decode("latin-1", "replace").strip()

    title_off = base + _ANNOTATION_COUNT * _ANNOTATION_LEN
    comment_off = title_off + _TITLE_LEN
    return {
        "annotations": [
            get(base + i * _ANNOTATION_LEN, _ANNOTATION_LEN)
            for i in range(_ANNOTATION_COUNT)
        ],
        "title": get(title_off, _TITLE_LEN),
        "comment": get(comment_off, _TITLE_LEN),
        "editor": get(comment_off + _TITLE_LEN + _EDITOR_GAP, _EDITOR_LEN),
    }
