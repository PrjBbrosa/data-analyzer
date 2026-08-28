"""One-pass WinWert document parse: record catalog, groups, display windows."""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .wwt_display import (
    WwtCurveDisplay,
    WwtDisplayWindow,
    WwtWindowRectMm,
    decode_display_window,
    iter_trailer_offsets,
    trailer_is_structurally_valid,
)
from .wwt_format import (
    _HEADER_SIZE,
    _MAGIC_PREFIX,
    _MIN_TIMESERIES_SAMPLES,
    _REC_HEADER_SIZE,
    _TAG_DTYPES,
    _TRAILER_PREFIX,
    _cstr,
    _looks_like_record_header,
)

__all__ = [
    "WwtCurveDisplay",
    "WwtDisplayWindow",
    "WwtDocument",
    "WwtRecord",
    "WwtWindowRectMm",
    "parse_wwt_document",
]


@dataclass(frozen=True)
class WwtRecord:
    index: int
    tag: str
    declared_n: int
    name: str
    unit: str
    scale_a: float
    offset_c: float
    axis_record: int | None
    values: np.ndarray | None
    formula: str | None
    dt: float | None = None


@dataclass(frozen=True)
class WwtDocument:
    path: Path
    version: str
    records: tuple[WwtRecord, ...]
    groups: tuple[dict, ...]
    windows: tuple[WwtDisplayWindow, ...]
    diagnostics: tuple[str, ...]


def _freeze_array(values: np.ndarray) -> np.ndarray:
    out = np.asarray(values, dtype=np.float64)
    if out.ndim != 1:
        out = np.ravel(out)
    view = out if out.flags.writeable else out
    frozen = np.array(view, dtype=np.float64, copy=True)
    frozen.setflags(write=False)
    return frozen


def _scan_next_boundary(data: bytes, data_pos: int, size: int) -> int:
    scan = data_pos
    while scan < size:
        if (data[scan:scan + len(_TRAILER_PREFIX)] == _TRAILER_PREFIX
                or _looks_like_record_header(data, scan)):
            return scan
        scan += 1
    return -1


def _append_zeit_block(blocks: list[dict], n: int, dt: float, t0: float) -> None:
    blocks.append({
        "n": n,
        "dt": dt,
        "t0": t0,
        "channels": [],
        "curve_def": n < _MIN_TIMESERIES_SAMPLES,
    })


def _materialize_groups(
    blocks: list[dict],
    *,
    name: str,
    title: str,
    comment: str,
    version: str,
    count: int,
    records_parsed: int,
    skipped: list[str],
) -> list[dict]:
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []
    for blk in blocks:
        if not blk["channels"]:
            continue
        key = (blk["n"], blk["dt"], blk["t0"])
        if key not in merged:
            merged[key] = {
                "n": blk["n"], "dt": blk["dt"], "t0": blk["t0"], "channels": [],
            }
            order.append(key)
        merged[key]["channels"].extend(blk["channels"])

    smeta_base = {
        "source_kind": "wwt", "title": title, "comment": comment,
        "winwert_version": version,
        "records_declared": count, "records_parsed": records_parsed,
        "skipped_channels": skipped, "source_filename": name,
    }
    groups: list[dict] = []
    for key in order:
        blk = merged[key]
        t = blk["t0"] + np.arange(blk["n"], dtype=np.float64) * blk["dt"]
        frame = {"Time": t}
        units: dict[str, str] = {}
        cmeta: dict[str, dict] = {}
        renamed: list[dict] = []
        for ch in blk["channels"]:
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

    for group in groups:
        n, dt, _t0 = group.pop("axis_key")
        if len(groups) == 1:
            group["label_suffix"] = ""
        else:
            fs = (1.0 / dt) if dt > 0 else 0.0
            group["label_suffix"] = f"{fs:.0f}Hz·{n}"
    return groups


def parse_wwt_document(fp: str | Path) -> WwtDocument:
    """Parse body records, groups, and every structurally valid display window."""
    path = Path(fp)
    name = path.name
    data = path.read_bytes()
    size = len(data)

    if size < 15 or not data.startswith(_MAGIC_PREFIX):
        raise ValueError(f"不是有效的 WWT 文件（缺少 WinWert 魔数）: {name}")
    version = _cstr(data[:15])[len(_MAGIC_PREFIX):]
    if size < _HEADER_SIZE:
        raise ValueError(f"WWT 文件截断/损坏（文件头不完整）: {name}")

    title = _cstr(data[0x00F:0x10F])
    comment = _cstr(data[0x10F:0x20F])
    (count,) = struct.unpack_from("<H", data, 0x20F)

    blocks: list[dict] = []
    skipped: list[str] = []
    records: list[WwtRecord] = []
    pos = _HEADER_SIZE
    records_parsed = 0
    current_zeit: int | None = None
    while records_parsed < count:
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
        rec_index = records_parsed

        if tag not in _TAG_DTYPES:
            scan = _scan_next_boundary(data, data_pos, size)
            if scan < 0:
                raise ValueError(
                    f"WWT 记录解析失败: 偏移 0x{pos:x} 处标签"
                    f" {data[pos:pos + 5]!r} 未知且无法重同步"
                    f"（版本 {version}，可能布局不兼容）: {name}")
            formula = None
            if tag == "Pars":
                formula = _cstr(data[data_pos:min(scan, data_pos + 256)])
                skipped.append(
                    f"{ch_name} (公式: {formula})" if formula else ch_name)
            else:
                skipped.append(ch_name or f"<{tag}>")
            records.append(WwtRecord(
                index=rec_index,
                tag=tag,
                declared_n=int(n),
                name=ch_name,
                unit=unit,
                scale_a=float(a),
                offset_c=float(c),
                axis_record=None,
                values=None,
                formula=formula or None,
                dt=None,
            ))
            pos = scan
            records_parsed += 1
            continue

        dtype = _TAG_DTYPES[tag]
        dlen = 0 if dtype is None else n * dtype.itemsize
        if data_pos + dlen > size:
            raise ValueError(
                f"WWT 文件截断/损坏: 通道 {ch_name!r} 数据区越过文件末尾"
                f"（偏移 0x{data_pos:x} + {dlen}B > {size}B）: {name}")

        axis_record: int | None
        values: np.ndarray | None
        dt: float | None = None
        if tag == "Zeit":
            dt = float(b)
            axis_record = rec_index
            current_zeit = rec_index
            values = _freeze_array(
                np.asarray(c, dtype=np.float64)
                + np.arange(n, dtype=np.float64) * b
            )
            _append_zeit_block(blocks, n, float(b), float(c))
        else:
            if not blocks:
                raise ValueError(
                    f"WWT 结构异常: 通道 {ch_name!r} 出现在首个 Zeit 记录之前"
                    f"（偏移 0x{pos:x}）: {name}")
            blk = blocks[-1]
            raw = np.frombuffer(data, dtype=dtype, count=n, offset=data_pos)
            physical = _freeze_array(raw.astype(np.float64) * a + c)
            values = physical
            if (
                current_zeit is not None
                and n == records[current_zeit].declared_n
            ):
                axis_record = current_zeit
            else:
                axis_record = None
            if blk["curve_def"] or n != blk["n"]:
                skipped.append(ch_name)
            else:
                blk["channels"].append({
                    "name": ch_name, "unit": unit, "tag": tag,
                    "a": a, "c": c, "source_filename": src_fname,
                    "rec_idx": rec_index + 1,
                    "values": physical,
                })
        records.append(WwtRecord(
            index=rec_index,
            tag=tag,
            declared_n=int(n),
            name=ch_name,
            unit=unit,
            scale_a=float(a),
            offset_c=float(c),
            axis_record=axis_record,
            values=values,
            formula=None,
            dt=dt,
        ))
        pos = data_pos + dlen
        records_parsed += 1

    groups = _materialize_groups(
        blocks,
        name=name,
        title=title,
        comment=comment,
        version=version,
        count=count,
        records_parsed=records_parsed,
        skipped=skipped,
    )

    diagnostics: list[str] = []
    windows: list[WwtDisplayWindow] = []
    markers = iter_trailer_offsets(data)
    window_index = 0
    for marker_i, marker in enumerate(markers):
        limit = markers[marker_i + 1] if marker_i + 1 < len(markers) else size
        if not trailer_is_structurally_valid(data, marker, limit):
            diagnostics.append(
                f"显示块 {marker_i + 1} 截断或曲线表越界（偏移 0x{marker:x}）"
            )
            continue
        window = decode_display_window(data, marker, window_index)
        if window is None:
            diagnostics.append(
                f"显示块 {marker_i + 1} 截断或曲线表越界（偏移 0x{marker:x}）"
            )
            continue
        valid_curves: list[WwtCurveDisplay] = []
        for curve in window.curves:
            if curve.record_index >= len(records):
                diagnostics.append(
                    f"显示块 {marker_i + 1} 曲线引用未知记录 "
                    f"{curve.record_index}"
                )
                continue
            valid_curves.append(curve)
        windows.append(WwtDisplayWindow(
            index=window_index,
            rect_mm=window.rect_mm,
            line_width_mm=window.line_width_mm,
            curves=tuple(valid_curves),
        ))
        window_index += 1

    return WwtDocument(
        path=path,
        version=version,
        records=tuple(records),
        groups=tuple(groups),
        windows=tuple(windows),
        diagnostics=tuple(diagnostics),
    )
