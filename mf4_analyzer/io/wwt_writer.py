"""Writer for WinWert binary time-data files (.wwt).

v1 profile (see ``docs/analyzer/specs/2026-08-11-wwt-export-dual-compat-spec.md``):

- Magic ``WinWert091293``
- One equidistant ``Zeit`` + N ``Real`` (float64 physical) channels
- Optional minimal ``DatenFenste2`` stub for WinWert open trials

Not a full WinWert project round-trip: no ``Pars``, tolerance curves, or
exotic ``IntB`` / ``*T`` types.
"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from .wwt_format import (
    _HEADER_SIZE,
    _MAGIC_PREFIX,
    _MIN_TIMESERIES_SAMPLES,
    _REC_HEADER_SIZE,
)

# Re-export: exporters must keep Zeit length ≥ this or TraceLab skips the block.
MIN_TIMESERIES_SAMPLES = _MIN_TIMESERIES_SAMPLES

_DEFAULT_MAGIC = b"WinWert091293"
_NAME_LEN = 40
_UNIT_LEN = 17
_SRC_LEN = 48  # bytes from 0x54 to 0x84
_TRAILER_TAG = b"DatenFenste2\x00"


class UnevenTimeAxisError(ValueError):
    """Raised when the export time axis is not equidistant enough for WWT."""


def _encode_field(text: str, length: int) -> bytes:
    """latin-1 field, NUL-padded; truncate on encode failure / oversize."""
    raw = (text or "").encode("latin-1", "replace")
    if len(raw) > length:
        raw = raw[:length]
    return raw.ljust(length, b"\0")


def _finite_minmax(values: np.ndarray) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0, 1.0
    lo = float(np.min(finite))
    hi = float(np.max(finite))
    if lo == hi:
        hi = lo + 1.0
    return lo, hi


def infer_zeit_params(
    time: np.ndarray,
    *,
    relative_tol: float = 1e-6,
) -> tuple[float, float, int]:
    """Return ``(t0, dt, n)`` or raise ``UnevenTimeAxisError``."""
    arr = np.asarray(time, dtype=np.float64)
    if arr.ndim != 1 or arr.size < 2:
        raise UnevenTimeAxisError("时间轴至少需要 2 个等间隔采样点才能导出 WWT")
    if not np.all(np.isfinite(arr)):
        raise UnevenTimeAxisError("时间轴含有非有限值，无法导出 WWT")
    dt = float(np.median(np.diff(arr)))
    if not np.isfinite(dt) or dt <= 0.0:
        raise UnevenTimeAxisError("时间轴不是严格递增的等间隔序列")
    deltas = np.diff(arr)
    rel = float(np.max(np.abs(deltas - dt)) / dt)
    if rel > relative_tol:
        raise UnevenTimeAxisError(
            f"时间轴非等间隔（相对抖动 {rel:.3g} > {relative_tol:g}），"
            "WWT 需要等间隔 Zeit；请先重建时基或改导出 Excel"
        )
    t0 = float(arr[0])
    return t0, dt, int(arr.size)


def _pack_record(
    tag: bytes,
    n: int,
    *,
    name: str,
    unit: str,
    source_filename: str,
    a: float,
    b: float,
    c: float,
    min_v: float,
    max_v: float,
    xkanalnr: int = 0,
    payload: bytes = b"",
) -> bytes:
    rec = bytearray(_REC_HEADER_SIZE)
    tag_bytes = tag if len(tag) >= 5 else tag.ljust(5, b"\0")
    rec[0:5] = tag_bytes[:5]
    struct.pack_into("<IH", rec, 5, int(n), int(xkanalnr) & 0xFFFF)
    struct.pack_into("<dd", rec, 0x0B, float(min_v), float(max_v))
    rec[0x1B:0x1B + _NAME_LEN] = _encode_field(name, _NAME_LEN)
    rec[0x43:0x43 + _UNIT_LEN] = _encode_field(unit, _UNIT_LEN)
    rec[0x54:0x54 + _SRC_LEN] = _encode_field(source_filename, _SRC_LEN)
    struct.pack_into("<ddd", rec, 0x84, float(a), float(b), float(c))
    return bytes(rec) + payload


def build_trailer_stub(record_count: int, *, pad_to: int = 256) -> bytes:
    """Minimal ``DatenFenste2`` prefix observed in ``testdoc`` files.

    Real trailers are 30–100+ KiB of display state. This stub only mirrors the
    stable header fields (``0.2``, ``0,1,0,count``) plus zero padding.
    2026-08-11 开测证据互相矛盾：上午的合成 stub 候选被 WinWert 拒开，但
    ``testdoc/20260527.wwt``（同一 stub 布局、真实测量数据重写）实测能打开
    ——差异未定位（怀疑与正文内容有关，不是尾块本身）。产品路径仍走
    ``wwt_inplace.convert_to_wwt`` 的真实模板；stub 用于 TraceLab 往返与
    对照实验。注意 stub 没有窗口配置，WinWert 会用自己的默认版式决定
    X 轴（不受本文件控制）。
    """
    body = bytearray(_TRAILER_TAG)
    body += struct.pack("<d", 0.2)
    body += struct.pack("<HHHI", 0, 1, 0, int(record_count) & 0xFFFFFFFF)
    if len(body) < pad_to:
        body.extend(b"\0" * (pad_to - len(body)))
    return bytes(body)


def extract_wwt_trailer(path) -> bytes:
    """Return the ``DatenFenste*`` tail of an existing WWT, or raise."""
    data = Path(path).read_bytes()
    idx = data.find(b"DatenFenste")
    if idx < 0:
        raise ValueError(f"WWT has no DatenFenste trailer: {path}")
    return data[idx:]


def patch_trailer_record_count(trailer: bytes, record_count: int) -> bytes:
    """Patch the ``u32`` channel/record count in a ``DatenFenste2`` header."""
    if not trailer.startswith(_TRAILER_TAG):
        return trailer
    out = bytearray(trailer)
    # DatenFenste2\0 (13) + double (8) + u16 + u16 + u16 + u32 count
    struct.pack_into("<I", out, 13 + 8 + 2 + 2 + 2, int(record_count) & 0xFFFFFFFF)
    return bytes(out)


def write_wwt(
    path,
    time: np.ndarray,
    channels: Mapping[str, np.ndarray] | Sequence[tuple[str, np.ndarray]],
    *,
    units: Mapping[str, str] | None = None,
    title: str = "",
    comment: str = "",
    source_filename: str = "",
    zeit_name: str = "Zeit",
    zeit_unit: str = "s",
    include_trailer_stub: bool = True,
    trailer: bytes | None = None,
    magic: bytes = _DEFAULT_MAGIC,
    xkanalnr: int | None = None,
) -> Path:
    """Write a v1 WWT file and return the output path.

    ``channels`` is an ordered mapping (or sequence of ``(name, values)``)
    of Y series; each must have the same length as ``time``.

    Trailer selection:
    - ``trailer=...`` wins (a real / rebuilt ``DatenFenste2`` display block);
    - else ``include_trailer_stub`` writes the 256-byte stub.

    ``xkanalnr``（记录头 +0x9）默认按尾块能力选：**极简尾块必须写非 0**，
    否则 WinWert 拒开——这是 2026-08-11 的受控对照结果（同一份数据、同一个
    stub，仅此字段 1↔0：写 1 的 ``testdoc/20260527.wwt`` 能开，写 0 的探针 D
    打不开）。带完整显示尾块时 WinWert 从尾块曲线表取显示配置，写 0 即可
    （WinWert 自己的 .mat 导出就是 0 + 完整尾块）。
    """
    out = Path(path)
    t0, dt, n = infer_zeit_params(time)
    units = dict(units or {})
    if hasattr(channels, "items"):
        items = list(channels.items())
    else:
        items = list(channels)
    if not items:
        raise ValueError("至少需要一条数据通道才能导出 WWT")

    series: list[tuple[str, np.ndarray]] = []
    for name, values in items:
        arr = np.asarray(values, dtype=np.float64)
        if arr.shape != (n,):
            raise ValueError(
                f"通道 {name!r} 长度 {arr.size} 与时间轴 {n} 不一致"
            )
        series.append((str(name), arr))

    record_count = 1 + len(series)
    src_name = source_filename or out.name
    if not magic.startswith(_MAGIC_PREFIX):
        raise ValueError(f"WWT magic 必须以 WinWert 开头: {magic!r}")
    if xkanalnr is None:
        xkanalnr = 0 if trailer is not None else 1

    head = bytearray(_HEADER_SIZE)
    mag = bytes(magic)[:15].ljust(15, b"\0")
    head[0:15] = mag
    head[0x00F:0x10F] = _encode_field(title, 256)
    head[0x10F:0x20F] = _encode_field(comment, 256)
    struct.pack_into("<H", head, 0x20F, record_count)

    chunks: list[bytes] = [bytes(head)]
    t_end = t0 + dt * (n - 1)
    chunks.append(
        _pack_record(
            b"Zeit",
            n,
            name=zeit_name,
            unit=zeit_unit,
            source_filename=src_name,
            a=1.0,
            b=dt,
            c=t0,
            min_v=min(t0, t_end),
            max_v=max(t0, t_end) if t0 != t_end else t0 + 1.0,
            xkanalnr=0,
        )
    )
    for name, arr in series:
        lo, hi = _finite_minmax(arr)
        payload = np.ascontiguousarray(arr, dtype="<f8").tobytes()
        chunks.append(
            _pack_record(
                b"Real",
                n,
                name=name,
                unit=units.get(name, ""),
                source_filename=src_name,
                a=1.0,
                b=1.0,
                c=0.0,
                min_v=lo,
                max_v=hi,
                xkanalnr=xkanalnr,
                payload=payload,
            )
        )

    if trailer is not None:
        chunks.append(patch_trailer_record_count(trailer, record_count))
    elif include_trailer_stub:
        chunks.append(build_trailer_stub(record_count))

    out.write_bytes(b"".join(chunks))
    return out
