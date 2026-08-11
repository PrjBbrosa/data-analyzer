"""模板原地改写：把序列写进真实 WinWert 骨架的测量槽位。

WinWert 拒绝纯合成骨架，但接受真实骨架被原地改写后的文件（2026-08-11 验证）。
本模块负责「拿一份真实模板 → 覆盖样本 / 名称 / Zeit → 改显示配置」这条路；
显示块的字段知识在 :mod:`wwt_display`，正文写入器在 :mod:`wwt_writer`。

与 clean-room 导出（:mod:`wwt_export` 的默认路径）的取舍：本路径受模板槽位
数与点数约束（要重采样、量化槽位要重新标定），好处是骨架逐字节来自真机文件。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from ..app_meta import asset_path
from . import wwt_display as _disp
from .wwt_format import (
    _HEADER_SIZE,
    _MIN_TIMESERIES_SAMPLES,
    _REC_HEADER_SIZE,
    _TAG_DTYPES,
    _TRAILER_PREFIX,
    _looks_like_record_header,
)
from .wwt_writer import _encode_field

_TEMPLATE_REL = ("wwt", "winwert_export_template.wwt")

# 记录头 +0x9（官方 .m 的 ``XKanalNr``）。WinWert 的**显示**不读它（实测改成
# 6 后曲线设置对话框仍显示 8），但尾块缺失时它是唯一的建图依据——详见
# :mod:`wwt_writer` 的 ``xkanalnr`` 说明。
_REC_XKANAL_OFF = 0x9



class WwtInplaceError(ValueError):
    """Raised when a template cannot accept the requested conversion."""


@dataclass(frozen=True)
class _Record:
    tag: str
    n: int
    name: str
    unit: str
    a: float
    b: float
    c: float
    rec_off: int
    data_off: int
    data_len: int
    known: bool = True
    # 记录序号（0 基，含被跳过的 Pars/未知记录）——尾块曲线记录按它编号。
    index: int = 0


@dataclass(frozen=True)
class WwtConvertResult:
    path: Path
    template_n: int
    channel_count: int
    resampled: bool
    slot_names: tuple[str, ...]
    time_axis: bool = False


def default_export_template() -> Path:
    """Bundled real WinWert skeleton used for any-format → WWT conversion."""
    return asset_path(*_TEMPLATE_REL)


def _decode_field(raw: bytes) -> str:
    i = raw.find(b"\0")
    if i >= 0:
        raw = raw[:i]
    return raw.decode("latin-1", "replace").strip()


def _iter_records(data: bytes, include_unknown: bool = False) -> list[_Record]:
    """Walk records; resync across ``Pars`` / unknown tags like the reader.

    ``include_unknown=True`` 时把 Pars/未知标签的记录也带出来（``known=False``，
    只保证 ``rec_off`` 可用）。无论是否带出，``index`` 都按**完整记录序列**
    计数——尾块曲线记录是按记录位置编号的，漏数 Pars 会让整张显示配置错位。
    """
    trailer = data.find(_TRAILER_PREFIX)
    end = trailer if trailer >= 0 else len(data)
    pos = _HEADER_SIZE
    out: list[_Record] = []
    index = 0
    while pos + _REC_HEADER_SIZE <= end:
        if data[pos:pos + len(_TRAILER_PREFIX)] == _TRAILER_PREFIX:
            break
        tag = _decode_field(data[pos:pos + 5])
        if tag not in _TAG_DTYPES:
            scan = pos + 1
            while scan < end:
                if (
                    data[scan:scan + len(_TRAILER_PREFIX)] == _TRAILER_PREFIX
                    or _looks_like_record_header(data, scan)
                ):
                    break
                scan += 1
            else:
                break
            if include_unknown:
                out.append(
                    _Record(
                        tag=tag,
                        n=0,
                        name=_decode_field(data[pos + 0x1B:pos + 0x1B + 40]),
                        unit="",
                        a=1.0,
                        b=0.0,
                        c=0.0,
                        rec_off=pos,
                        data_off=pos + _REC_HEADER_SIZE,
                        data_len=max(0, scan - pos - _REC_HEADER_SIZE),
                        known=False,
                        index=index,
                    )
                )
            pos = scan
            index += 1
            continue
        n = struct.unpack_from("<I", data, pos + 5)[0]
        name = _decode_field(data[pos + 0x1B:pos + 0x1B + 40])
        unit = _decode_field(data[pos + 0x43:pos + 0x43 + 17])
        a, b, c = struct.unpack_from("<ddd", data, pos + 0x84)
        dtype = _TAG_DTYPES[tag]
        dlen = 0 if dtype is None else int(n) * int(dtype.itemsize)
        if pos + _REC_HEADER_SIZE + dlen > end:
            raise WwtInplaceError(
                f"模板记录 {name!r} 数据区越过尾块（偏移 0x{pos:x}）"
            )
        out.append(
            _Record(
                tag=tag,
                n=int(n),
                name=name,
                unit=unit,
                a=float(a),
                b=float(b),
                c=float(c),
                rec_off=pos,
                data_off=pos + _REC_HEADER_SIZE,
                data_len=dlen,
                index=index,
            )
        )
        pos += _REC_HEADER_SIZE + dlen
        index += 1
    if not out:
        raise WwtInplaceError("模板中没有可解析的 WWT 记录")
    return out


def primary_measurement_slots(template_path) -> list[_Record]:
    """Largest equal-``n`` group of long measurement channels in the template."""
    data = Path(template_path).read_bytes()
    by_n: dict[int, list[_Record]] = {}
    for rec in _iter_records(data):
        if rec.tag == "Zeit" or rec.data_len <= 0:
            continue
        if rec.n < _MIN_TIMESERIES_SAMPLES:
            continue
        by_n.setdefault(rec.n, []).append(rec)
    if not by_n:
        raise WwtInplaceError("模板没有可写入的时域测量通道")
    return max(by_n.values(), key=lambda group: (len(group), group[0].n))


def list_measurement_slots(template_path) -> list[dict]:
    """Public summary of the primary measurement slot group."""
    return [
        {
            "name": rec.name,
            "unit": rec.unit,
            "tag": rec.tag,
            "n": rec.n,
            "rec_off": rec.rec_off,
        }
        for rec in primary_measurement_slots(template_path)
    ]


def resample_series(
    time: np.ndarray,
    values: np.ndarray,
    n: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Resample ``values`` onto ``n`` equidistant samples spanning ``time``."""
    t = np.asarray(time, dtype=np.float64)
    y = np.asarray(values, dtype=np.float64)
    if t.ndim != 1 or y.ndim != 1 or t.size != y.size:
        raise WwtInplaceError("时间轴与通道长度不一致，无法重采样")
    if t.size < 2:
        raise WwtInplaceError("至少需要 2 个采样点才能导出 WWT")
    if n < 2:
        raise WwtInplaceError("模板槽位点数过短")
    if t.size == n:
        dt0 = float(t[1] - t[0]) if n > 1 else 0.0
        if n == 2 or np.allclose(np.diff(t), dt0):
            return t.copy(), y.copy()
    t0 = float(t[0])
    t1 = float(t[-1])
    if not np.isfinite(t0) or not np.isfinite(t1) or t1 <= t0:
        raise WwtInplaceError("时间轴无效，无法重采样到 WWT 模板")
    t_new = np.linspace(t0, t1, n, dtype=np.float64)
    order = np.argsort(t)
    t_sorted = t[order]
    y_sorted = y[order]
    y_new = np.interp(t_new, t_sorted, y_sorted)
    return t_new, y_new


def _fit_scale(tag: str, lo: float | None, hi: float | None) -> tuple[float, float]:
    """给量化槽位重新标定 ``(scale, offset)``，使数据量程刚好铺满存储类型。

    模板槽位自带的 scale 是为原始被测量标定的（Servo 模板的 int16 槽位只到
    ±32）。沿用它写入别的通道会**静默截断**——实测 ±450° 的转向角被削成
    ±32。因此写入前按本次数据的 min/max 重算：物理值 = raw×a + c。
    """
    dtype = _TAG_DTYPES[tag]
    if dtype is None or dtype.kind == "f":
        return 1.0, 0.0
    limit = 32767.0 if dtype.itemsize == 2 else 2147483647.0
    if lo is None or hi is None or not np.isfinite(lo) or not np.isfinite(hi):
        return 1.0, 0.0
    center = (hi + lo) / 2.0
    half = (hi - lo) / 2.0
    if half <= 0.0:
        return 1.0, center
    # 留一点余量，rint 后不会因为浮点误差顶出量程。
    return half / (limit - 1.0), center


def _physical_to_raw(
    values: np.ndarray, rec: _Record,
    scale: float | None = None, offset: float | None = None,
) -> bytes:
    dtype = _TAG_DTYPES[rec.tag]
    assert dtype is not None
    phys = np.asarray(values, dtype=np.float64)
    if phys.shape != (rec.n,):
        raise WwtInplaceError(
            f"通道长度 {phys.size} 与模板槽位 {rec.n} 不一致"
        )
    a = rec.a if scale is None else scale
    c = rec.c if offset is None else offset
    if a == 0.0:
        a = 1.0
    raw = (phys - c) / a
    if dtype == np.dtype("<i2"):
        raw = np.clip(np.rint(raw), -32768, 32767).astype("<i2")
    elif dtype == np.dtype("<i4"):
        raw = np.clip(np.rint(raw), -2147483648, 2147483647).astype("<i4")
    elif dtype == np.dtype("<f4"):
        raw = raw.astype("<f4")
    else:
        raw = raw.astype("<f8")
    return np.ascontiguousarray(raw).tobytes()


def _update_zeit(data: bytearray, records: list[_Record], n: int,
                 t0: float, dt: float) -> None:
    t_end = t0 + dt * (n - 1)
    for rec in records:
        if rec.tag != "Zeit" or rec.n != n:
            continue
        struct.pack_into("<ddd", data, rec.rec_off + 0x84, 1.0, dt, t0)
        struct.pack_into(
            "<dd", data, rec.rec_off + 0x0B,
            min(t0, t_end),
            max(t0, t_end) if t0 != t_end else t0 + 1.0,
        )


def write_wwt_inplace(
    template_path,
    out_path,
    channels: Mapping[str, np.ndarray] | Sequence[tuple[str, np.ndarray]],
    *,
    units: Mapping[str, str] | None = None,
    title: str | None = None,
    comment: str | None = None,
    time: np.ndarray | None = None,
    match_by_name: bool = True,
    slots: Sequence[_Record] | None = None,
    time_axis: bool = False,
    hide_unused: bool = True,
) -> Path:
    """Copy ``template_path`` to ``out_path`` and overwrite measurement slots.

    ``time_axis=True`` 把每条曲线的 X 引用清 0（= 按时间显示），否则沿用
    模板的角度/行程横坐标。``hide_unused=True`` 把没写入的模板曲线取消
    勾选——不然模板残留数据会跟导出通道一起画在同一张图上。
    """
    template = Path(template_path)
    out = Path(out_path)
    if not template.is_file():
        raise WwtInplaceError(f"找不到 WWT 模板: {template}")

    if hasattr(channels, "items"):
        items = list(channels.items())
    else:
        items = list(channels)
    if not items:
        raise WwtInplaceError("至少需要一条数据通道")

    units = dict(units or {})
    data = bytearray(template.read_bytes())
    records = _iter_records(bytes(data), include_unknown=True)
    slot_recs = list(slots) if slots is not None else primary_measurement_slots(
        template
    )
    if not slot_recs:
        raise WwtInplaceError("模板没有可写入的时域测量通道")
    if len(items) > len(slot_recs):
        raise WwtInplaceError(
            f"导出 {len(items)} 个通道，但模板只有 {len(slot_recs)} 个测量槽位"
        )

    remaining = list(slot_recs)
    assignments: list[tuple[str, np.ndarray, _Record]] = []
    pending = list(items)

    if match_by_name:
        still = []
        for name, values in pending:
            hit = next((s for s in remaining if s.name == name), None)
            if hit is None:
                still.append((name, values))
                continue
            remaining.remove(hit)
            assignments.append((name, values, hit))
        pending = still

    for name, values in pending:
        if not remaining:
            raise WwtInplaceError("模板测量槽位不足")
        assignments.append((name, values, remaining.pop(0)))

    trailer_off = _disp.find_trailer(bytes(data))
    # 版式常量（绘图比例 + 轴原点）必须在改任何轴范围**之前**从模板原值推出。
    layout = _disp.LayoutConstants()
    if trailer_off >= 0:
        layout = _disp.layout_constants(
            bytes(data), trailer_off, [r.index for r in records if r.index > 0]
        )
    slot_n = slot_recs[0].n
    for position, (name, values, rec) in enumerate(assignments, start=1):
        phys = np.asarray(values, dtype=np.float64)
        finite = phys[np.isfinite(phys)]
        lo = hi = None
        if finite.size:
            lo = float(np.min(finite))
            hi = float(np.max(finite))
            if lo == hi:
                hi = lo + 1.0
            struct.pack_into("<dd", data, rec.rec_off + 0x0B, lo, hi)
        scale, offset = _fit_scale(rec.tag, lo, hi)
        struct.pack_into("<d", data, rec.rec_off + 0x84, scale)
        struct.pack_into("<d", data, rec.rec_off + 0x94, offset)
        payload = _physical_to_raw(values, rec, scale, offset)
        if len(payload) != rec.data_len:
            raise WwtInplaceError(
                f"通道 {name!r} 编码后长度 {len(payload)} != 槽位 {rec.data_len}"
            )
        data[rec.data_off:rec.data_off + rec.data_len] = payload
        new_unit = units.get(name, rec.unit)
        data[rec.rec_off + 0x1B:rec.rec_off + 0x1B + 40] = _encode_field(name, 40)
        data[rec.rec_off + 0x43:rec.rec_off + 0x43 + 17] = _encode_field(
            new_unit, 17
        )
        if trailer_off >= 0:
            _disp.write_curve(
                data, trailer_off, rec.index,
                label=f"{name} [{new_unit}]" if new_unit else name,
                lo=lo, hi=hi, visible=True, plot_k=layout.plot_k_y,
                origin_c=layout.origin_c_y,
                color=_disp.palette_color(position),
            )

    if hide_unused and trailer_off >= 0:
        used = {rec.index for _, _, rec in assignments}
        for rec in records:
            if rec.index == 0 or rec.index in used:
                continue
            _disp.write_curve(data, trailer_off, rec.index, visible=False)

    if time is not None:
        t = np.asarray(time, dtype=np.float64)
        if t.shape != (slot_n,):
            raise WwtInplaceError("时间轴长度必须与模板测量点数一致")
        dt = float(t[1] - t[0]) if slot_n > 1 else 0.001
        _update_zeit(data, records, slot_n, float(t[0]), dt)

    if time_axis:
        if time is not None:
            t = np.asarray(time, dtype=np.float64)
            t0, t1 = float(t[0]), float(t[-1])
        else:
            zeit = next(
                (r for r in records if r.tag == "Zeit" and r.n == slot_n),
                None,
            )
            t0 = zeit.c if zeit is not None else 0.0
            t1 = t0 + (zeit.b * (slot_n - 1) if zeit is not None else 1.0)
        for rec in records:
            struct.pack_into("<H", data, rec.rec_off + _REC_XKANAL_OFF, 0)
        _disp.force_time_axis(
            data, trailer_off, [r.index for r in records], t0, t1, layout,
        )

    if title is not None:
        data[0x00F:0x10F] = _encode_field(title, 256)
    if comment is not None:
        data[0x10F:0x20F] = _encode_field(comment, 256)

    # 模板尾块的 Log2 页脚会把模板来源的台架编号 / 试验规范 / 操作员印在导出图
    # 下方——转换出来的文件不该冒充别人的测量。文本槽定长，改写不改变长度。
    if trailer_off >= 0:
        patched = _disp.set_display_text(
            bytes(data[trailer_off:]),
            title=title or "", comment=comment or "",
            annotations=(), editor="TraceLab",
        )
        data[trailer_off:] = patched

    out.write_bytes(data)
    return out


def convert_to_wwt(
    out_path,
    time: np.ndarray,
    channels: Mapping[str, np.ndarray] | Sequence[tuple[str, np.ndarray]],
    *,
    units: Mapping[str, str] | None = None,
    title: str = "",
    comment: str = "Converted by TraceLab",
    template_path=None,
    time_axis: bool = True,
) -> WwtConvertResult:
    """Convert equidistant series from any source into a WinWert-openable WWT.

    默认 ``time_axis=True``：导出的文件在 WinWert 中按时域显示（X = Zeit）。
    传 False 可保留模板原有的显示配置（X 指向模板槽位通道，通常是角度）。
    """
    template = Path(template_path) if template_path else default_export_template()
    if not template.is_file():
        raise WwtInplaceError(
            f"缺少 WinWert 导出模板: {template}。"
            "请确认 assets/wwt/winwert_export_template.wwt 已随安装包分发。"
        )
    if hasattr(channels, "items"):
        items = list(channels.items())
    else:
        items = list(channels)
    slots = primary_measurement_slots(template)
    if len(items) > len(slots):
        raise WwtInplaceError(
            f"最多可导出 {len(slots)} 个通道到 WinWert 模板，"
            f"当前勾选了 {len(items)} 个。请减少通道后重试。"
        )
    target_n = slots[0].n
    t_arr = np.asarray(time, dtype=np.float64)
    resampled = len(t_arr) != target_n
    out_series = {}
    t_out = None
    for name, values in items:
        t_new, y_new = resample_series(t_arr, values, target_n)
        out_series[name] = y_new
        t_out = t_new
        if len(values) != target_n:
            resampled = True
    assert t_out is not None
    path = write_wwt_inplace(
        template,
        out_path,
        out_series,
        units=units,
        title=title or None,
        comment=comment,
        time=t_out,
        match_by_name=False,
        slots=slots,
        time_axis=time_axis,
    )
    return WwtConvertResult(
        path=path,
        template_n=target_n,
        channel_count=len(out_series),
        resampled=resampled,
        slot_names=tuple(s.name for s in slots),
        time_axis=time_axis,
    )
