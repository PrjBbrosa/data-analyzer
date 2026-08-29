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
    "WwtIssue",
    "WwtLoadResult",
    "WwtRecord",
    "WwtWindowRectMm",
    "attach_wwt_record_store",
    "format_wwt_issue",
    "load_wwt_document",
    "parse_wwt_document",
    "parse_wwt_issue",
]

# Stable diagnostic codes. Display text is generated from code + context;
# do not dedupe on Chinese strings.
CODE_TRUNCATED_WINDOW = "truncated_window"
CODE_UNKNOWN_RECORD = "unknown_record"
CODE_UNSUPPORTED_DISPLAY = "unsupported_display"
CODE_UNSUPPORTED_FORMULA = "unsupported_formula"
CODE_UNSUPPORTED_REPRESENTATION = "unsupported_representation"
CODE_VIEW_CAP = "view_cap"
CODE_EXACT_OVERLAP = "exact_overlap"
CODE_DUPLICATE_RECORD = "duplicate_record_index"
CODE_SKIPPED_CHANNEL = "skipped_channel"

# WinWert uses this exact finite value as an in-record pen-up marker.  Keep the
# comparison exact: nearby large engineering values are still valid data.
_WWT_MISSING_SENTINEL = -1e300


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


@dataclass(frozen=True)
class WwtLoadResult:
    groups: tuple[dict, ...]
    document: WwtDocument


@dataclass(frozen=True)
class WwtIssue:
    code: str
    detail: str = ""
    record_index: int | None = None
    window_index: int | None = None

    def text(self) -> str:
        return format_wwt_issue(self.code, self.detail)


def format_wwt_issue(code: str, detail: str = "") -> str:
    """Stable ``code: detail`` form used in diagnostics, toasts, and tests."""
    code = str(code or "").strip()
    detail = str(detail or "").strip()
    if not code:
        return detail
    if not detail:
        return code
    if detail.startswith(f"{code}:"):
        return detail
    return f"{code}: {detail}"


def parse_wwt_issue(text: str) -> WwtIssue:
    raw = str(text or "").strip()
    if not raw:
        return WwtIssue("diagnostic", "")
    code, sep, detail = raw.partition(": ")
    if sep and code.replace("_", "").isalnum() and code[:1].isalpha():
        return WwtIssue(code, detail)
    return WwtIssue("diagnostic", raw)


def attach_wwt_record_store(groups, records: tuple[WwtRecord, ...]) -> None:
    """Share one immutable record tuple on every logical source from this file.

    Load-layer ownership: Accept, Reject, no-display, and project restore all
    receive this same object. Do not copy ndarrays per group.
    """
    store = records
    for group in groups or ():
        metadata = group.get("source_metadata")
        if metadata is None:
            metadata = {}
            group["source_metadata"] = metadata
        metadata["wwt_record_store"] = store


def _freeze_array(values: np.ndarray) -> np.ndarray:
    out = np.asarray(values, dtype=np.float64)
    if out.ndim != 1:
        out = np.ravel(out)
    view = out if out.flags.writeable else out
    frozen = np.array(view, dtype=np.float64, copy=True)
    frozen.setflags(write=False)
    return frozen


def _freeze_record_array(values: np.ndarray) -> np.ndarray:
    frozen = _freeze_array(values)
    if not np.any(frozen == _WWT_MISSING_SENTINEL):
        return frozen
    with_gaps = np.array(frozen, dtype=np.float64, copy=True)
    with_gaps[with_gaps == _WWT_MISSING_SENTINEL] = np.nan
    with_gaps.setflags(write=False)
    return with_gaps


def _scan_next_boundary(data: bytes, data_pos: int, size: int) -> int:
    scan = data_pos
    while scan < size:
        if (data[scan:scan + len(_TRAILER_PREFIX)] == _TRAILER_PREFIX
                or _looks_like_record_header(data, scan)):
            return scan
        scan += 1
    return -1


def _append_zeit_block(
    blocks: list[dict], n: int, dt: float, t0: float, zeit_index: int
) -> None:
    blocks.append({
        "n": n,
        "dt": dt,
        "t0": t0,
        "channels": [],
        "curve_def": n < _MIN_TIMESERIES_SAMPLES,
        "zeit_index": zeit_index,
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
    auxiliary: list[dict],
) -> list[dict]:
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []
    for blk in blocks:
        if not blk["channels"]:
            continue
        key = (blk["n"], blk["dt"], blk["t0"])
        if key not in merged:
            merged[key] = {
                "n": blk["n"], "dt": blk["dt"], "t0": blk["t0"],
                "channels": [], "zeit_indices": [],
            }
            order.append(key)
        merged[key]["channels"].extend(blk["channels"])
        merged[key]["zeit_indices"].append(blk["zeit_index"])

    smeta_base = {
        "source_kind": "wwt", "title": title, "comment": comment,
        "winwert_version": version,
        "records_declared": count, "records_parsed": records_parsed,
        "skipped_channels": skipped, "source_filename": name,
        "wwt_auxiliary_records": auxiliary,
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
        smeta["zeit_record_indices"] = tuple(blk["zeit_indices"])
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
    auxiliary: list[dict] = []
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
            _append_zeit_block(blocks, n, float(b), float(c), rec_index)
        else:
            if not blocks:
                raise ValueError(
                    f"WWT 结构异常: 通道 {ch_name!r} 出现在首个 Zeit 记录之前"
                    f"（偏移 0x{pos:x}）: {name}")
            blk = blocks[-1]
            raw = np.frombuffer(data, dtype=dtype, count=n, offset=data_pos)
            physical = _freeze_record_array(raw.astype(np.float64) * a + c)
            values = physical
            if (
                current_zeit is not None
                and n == records[current_zeit].declared_n
            ):
                axis_record = current_zeit
            else:
                axis_record = None
            if blk["curve_def"] or n != blk["n"]:
                auxiliary.append({
                    "name": ch_name,
                    "record_index": rec_index,
                    "tag": tag,
                    "n": int(n),
                })
            else:
                blk["channels"].append({
                    "name": ch_name, "unit": unit, "tag": tag,
                    "a": a, "c": c, "source_filename": src_fname,
                    "rec_idx": rec_index,
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
        auxiliary=auxiliary,
    )

    diagnostics: list[str] = []
    windows: list[WwtDisplayWindow] = []
    markers = iter_trailer_offsets(data)
    window_index = 0
    for marker_i, marker in enumerate(markers):
        limit = markers[marker_i + 1] if marker_i + 1 < len(markers) else size
        if not trailer_is_structurally_valid(data, marker, limit):
            diagnostics.append(format_wwt_issue(
                CODE_TRUNCATED_WINDOW,
                f"显示块 {marker_i + 1} 截断或曲线表越界（偏移 0x{marker:x}）",
            ))
            continue
        window = decode_display_window(data, marker, window_index)
        if window is None:
            diagnostics.append(format_wwt_issue(
                CODE_TRUNCATED_WINDOW,
                f"显示块 {marker_i + 1} 截断或曲线表越界（偏移 0x{marker:x}）",
            ))
            continue
        valid_curves: list[WwtCurveDisplay] = []
        for curve in window.curves:
            if curve.record_index >= len(records):
                diagnostics.append(format_wwt_issue(
                    CODE_UNKNOWN_RECORD,
                    f"显示块 {marker_i + 1} 曲线引用未知记录 "
                    f"{curve.record_index}",
                ))
                continue
            valid_curves.append(curve)
        windows.append(WwtDisplayWindow(
            index=window_index,
            rect_mm=window.rect_mm,
            line_width_mm=window.line_width_mm,
            curves=tuple(valid_curves),
        ))
        window_index += 1

    catalog = tuple(records)
    attach_wwt_record_store(groups, catalog)
    return WwtDocument(
        path=path,
        version=version,
        records=catalog,
        groups=tuple(groups),
        windows=tuple(windows),
        diagnostics=tuple(diagnostics),
    )


def _copy_groups(groups: tuple[dict, ...] | list[dict]) -> list[dict]:
    copied: list[dict] = []
    for group in groups:
        smeta = dict(group["source_metadata"])
        smeta["skipped_channels"] = list(smeta.get("skipped_channels") or [])
        smeta["renamed_channels"] = list(smeta.get("renamed_channels") or [])
        smeta["wwt_auxiliary_records"] = [
            dict(item) if isinstance(item, dict) else item
            for item in smeta.get("wwt_auxiliary_records") or []
        ]
        copied.append({
            "data": group["data"].copy(),
            "channels": list(group["channels"]),
            "units": dict(group["units"]),
            "channel_metadata": {
                key: dict(value)
                for key, value in group["channel_metadata"].items()
            },
            "source_metadata": smeta,
            "label_suffix": group.get("label_suffix", ""),
        })
    return copied


def _formula_skip_text(record: WwtRecord) -> str:
    if record.formula:
        return f"{record.name} (公式: {record.formula})"
    return record.name


def _unique_column(frame_cols: set[str], name: str, record_index: int) -> str:
    col = name
    if col not in frame_cols:
        return col
    col = f"{name} [{record_index}]"
    while col in frame_cols:
        col = f"{col}_"
    return col


def _inject_derived_channels(
    groups: list[dict], records: tuple[WwtRecord, ...]
) -> list[dict]:
    from .wwt_formula import formula_channel_metadata, formula_references

    derived = [
        rec for rec in records
        if rec.tag == "Pars" and rec.values is not None
    ]
    materialized_skip = {_formula_skip_text(rec) for rec in derived}
    for group in groups:
        skipped = group["source_metadata"]["skipped_channels"]
        group["source_metadata"]["skipped_channels"] = [
            item for item in skipped if item not in materialized_skip
        ]

    zeit_to_group: dict[int, dict] = {}
    for group in groups:
        for zeit_index in group["source_metadata"].get("zeit_record_indices", ()):
            zeit_to_group[int(zeit_index)] = group

    for rec in derived:
        group = zeit_to_group.get(rec.axis_record) if rec.axis_record is not None else None
        if group is None or rec.values is None:
            continue
        if int(rec.values.shape[0]) != len(group["data"]):
            continue
        col = _unique_column(
            set(group["data"].columns), rec.name, rec.index
        )
        if col != rec.name:
            group["source_metadata"]["renamed_channels"].append(
                {"original": rec.name, "renamed": col}
            )
        group["data"][col] = rec.values
        group["units"][col] = rec.unit
        group["channel_metadata"][col] = formula_channel_metadata(
            rec, formula_references(rec)
        )

    for group in groups:
        others = [name for name in group["data"].columns if name != "Time"]
        others.sort(
            key=lambda name: group["channel_metadata"][name]["record_index"]
        )
        ordered = ["Time"] + others if "Time" in group["data"].columns else others
        group["channels"] = ordered
        group["data"] = group["data"][ordered]
    return groups


def load_wwt_document(fp: str | Path) -> WwtLoadResult:
    """Parse a WWT file and materialize supported ``Pars`` channels."""
    from .wwt_formula import evaluate_wwt_formulas

    parsed = parse_wwt_document(fp)
    records, formula_diagnostics = evaluate_wwt_formulas(
        parsed.records, strict=False
    )
    groups = _inject_derived_channels(_copy_groups(parsed.groups), records)
    attach_wwt_record_store(groups, records)
    document = WwtDocument(
        path=parsed.path,
        version=parsed.version,
        records=records,
        groups=tuple(groups),
        windows=parsed.windows,
        diagnostics=parsed.diagnostics + formula_diagnostics,
    )
    return WwtLoadResult(groups=tuple(groups), document=document)
