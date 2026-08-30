"""One-pass WinWert document parse: record catalog, groups, display windows."""
from __future__ import annotations

import logging
import re
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
    "format_wwt_import_summary",
    "format_wwt_issue",
    "format_wwt_issue_for_user",
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
CODE_EXACT_OVERLAP_RELOCATED = "exact_overlap_relocated"
CODE_MISSING_FORMULA_REF = "missing_formula_ref"
CODE_DROPPED_CURVE = "dropped_curve"
CODE_DROPPED_WINDOW = "dropped_window"

_LOG = logging.getLogger(__name__)
_RECORD_INDEX_RE = re.compile(r"\brecord\s+(\d+)\b", re.I)
_FORMULA_SKIP_MARK = " (公式:"
_GENERIC_USER_SUMMARY = "部分 WinWert 内容未能按原样导入，其余可读取数据已导入。"
_CONCRETE_FORMULA_CODES = frozenset({
    CODE_MISSING_FORMULA_REF,
    "formula_axis_mismatch",
    "formula_shape_mismatch",
    "formula_no_finite_values",
    "formula_nonfinite_values",
    "formula_cycle",
})
# User toast never shows these codes. Layout success codes overlap the shared
# native-layout non-degraded set; ``invalid_rect`` is graded separately.
_USER_SILENT_CODES = frozenset({
    CODE_EXACT_OVERLAP,
    CODE_EXACT_OVERLAP_RELOCATED,
    "auto_range",
    "hidden_axis",
    "quantized_collision",
    "duplicate_ref",
    "membership_limit",
    "placed_limit",
    "grid_full",
    "grid_collision",
    "board_limit",
})

# WinWert uses this exact finite value as an in-record pen-up marker.  Keep the
# comparison exact: nearby large engineering values are still valid data.
_WWT_MISSING_SENTINEL = -1e300

# Zeit has no sample payload, so the file-size check cannot bound n. Reuse the
# record-header resync limit from wwt_format._looks_like_record_header.
_MAX_ZEIT_SAMPLES = 50_000_000
_PARS_FORMULA_WINDOW = 256


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


def _issue_record_index(issue: WwtIssue) -> int | None:
    if getattr(issue, "record_index", None) is not None:
        return int(issue.record_index)
    detail = str(getattr(issue, "detail", "") or "")
    match = _RECORD_INDEX_RE.search(detail)
    if match:
        return int(match.group(1))
    return None


def _record_from_issue(issue: WwtIssue, document) -> WwtRecord | None:
    records = getattr(document, "records", None) or ()
    index = _issue_record_index(issue)
    if index is None or index < 0 or index >= len(records):
        return None
    return records[index]


def _skip_channel_name(detail: str) -> str:
    text = str(detail or "").strip()
    if _FORMULA_SKIP_MARK in text:
        return text.split(_FORMULA_SKIP_MARK, 1)[0].strip()
    return text


def _join_names(names: list[str]) -> str:
    unique = list(dict.fromkeys(name for name in names if name))
    return "、".join(unique)


def _unresolved_ref_labels(issue: WwtIssue, document) -> tuple[str, ...]:
    rec = _record_from_issue(issue, document)
    if rec is None:
        return ()
    from .wwt_formula import unresolved_formula_ref_labels
    catalog = getattr(document, "records", ()) or ()
    return unresolved_formula_ref_labels(rec, catalog)


def _format_missing_formula_refs(
    issues: list[WwtIssue], document, *, trailing_ok: bool = True
) -> str:
    names: list[str] = []
    refs: list[str] = []
    seen_records: set[int | None] = set()
    unique: list[WwtIssue] = []
    for issue in issues:
        key = _issue_record_index(issue)
        if key is not None and key in seen_records:
            continue
        seen_records.add(key)
        unique.append(issue)
        rec = _record_from_issue(issue, document)
        if rec is not None and rec.name:
            names.append(rec.name)
        for label in _unresolved_ref_labels(issue, document):
            if label not in refs:
                refs.append(label)
    count = len(unique) or len(issues)
    name_part = f"（{_join_names(names)}）" if names else ""
    if refs:
        reason = f"当前文件解析结果中无法解析引用 {_join_names(refs)}。"
    else:
        reason = "当前文件解析结果中无法解析引用。"
    text = f"{count} 个 WinWert 公式通道未生成{name_part}：{reason}"
    if trailing_ok:
        text += "其余可读取数据已导入。"
    return text


def _format_unsupported_formula(issues: list[WwtIssue], document) -> str:
    names: list[str] = []
    seen_records: set[int | None] = set()
    unique: list[WwtIssue] = []
    for issue in issues:
        key = _issue_record_index(issue)
        rec = _record_from_issue(issue, document)
        name = rec.name if rec is not None else _skip_channel_name(issue.detail)
        if key is not None and key in seen_records:
            continue
        if key is not None:
            seen_records.add(key)
        elif name and name in names:
            continue
        unique.append(issue)
        if name:
            names.append(name)
    count = len(unique) or len(issues)
    name_part = f"（{_join_names(names)}）" if names else ""
    return (
        f"{count} 个 WinWert 公式通道未生成{name_part}："
        "当前版本暂不支持该公式语法。"
    )


def _format_named_formula_failure(
    issues: list[WwtIssue], document, reason: str
) -> str:
    names: list[str] = []
    seen: set[int | None] = set()
    unique: list[WwtIssue] = []
    for issue in issues:
        key = _issue_record_index(issue)
        if key is not None and key in seen:
            continue
        seen.add(key)
        unique.append(issue)
        rec = _record_from_issue(issue, document)
        if rec is not None and rec.name:
            names.append(rec.name)
        else:
            name = _skip_channel_name(issue.detail)
            if name and not _RECORD_INDEX_RE.search(name):
                names.append(name)
    count = len(unique) or len(issues)
    name_part = f"（{_join_names(names)}）" if names else ""
    return f"{count} 个 WinWert 公式通道未生成{name_part}：{reason}"


def _format_nonfinite_values(issues: list[WwtIssue], document) -> str:
    parts: list[str] = []
    for issue in issues:
        rec = _record_from_issue(issue, document)
        name = rec.name if rec is not None else ""
        match = re.search(r"(\d+)\s*/\s*(\d+)", issue.detail or "")
        if match:
            finite = int(match.group(1))
            total = int(match.group(2))
            bad = max(0, total - finite)
            quantity = f"{bad} 个非有限点"
        else:
            quantity = "非有限点"
        if name:
            parts.append(f"{name} 已生成，但含 {quantity}")
        else:
            parts.append(f"公式通道已生成，但含 {quantity}")
    return "；".join(dict.fromkeys(parts))


def _format_dropped(code: str, issues: list[WwtIssue]) -> str:
    count = len(issues)
    if code == CODE_DROPPED_CURVE:
        return f"跳过 {count} 条 WinWert 曲线"
    return f"跳过 {count} 个 WinWert 窗口"


def _format_invalid_rect(issues: list[WwtIssue]) -> str:
    total = 0
    parsed = False
    for issue in issues:
        detail = str(issue.detail or "").strip()
        token = detail.split()[0] if detail else ""
        try:
            total += int(token)
            parsed = True
        except (TypeError, ValueError):
            continue
    if not parsed:
        total = len(issues)
    return f"{total} 个窗口因布局无效未放置"


def _format_view_cap(issue: WwtIssue) -> str:
    detail = str(issue.detail or "").strip()
    if detail and issue.code not in detail and "record " not in detail.lower():
        return detail
    return "可创建的 WinWert View 已达上限"


def format_wwt_issue_for_user(issue, *, document=None) -> str | None:
    """User-facing copy for one issue. Silent codes return ``None``.

    Never falls back to ``issue.detail`` for unknown codes. Internal
    ``format_wwt_issue`` (``code: detail``) stays the log/test form.
    """
    if issue is None:
        return None
    code = str(getattr(issue, "code", "") or "").strip()
    if not code:
        return None
    if code in _USER_SILENT_CODES:
        return None
    if code == CODE_VIEW_CAP:
        return _format_view_cap(issue)
    if code == CODE_MISSING_FORMULA_REF:
        return _format_missing_formula_refs([issue], document)
    if code == CODE_UNSUPPORTED_FORMULA:
        return _format_unsupported_formula([issue], document)
    if code == "formula_axis_mismatch":
        return _format_named_formula_failure(
            [issue], document, "引用数据轴不一致，未生成。"
        )
    if code == "formula_shape_mismatch":
        return _format_named_formula_failure(
            [issue], document, "样本长度或形状不一致，未生成。"
        )
    if code == "formula_no_finite_values":
        return _format_named_formula_failure(
            [issue], document, "无有效数值，未生成。"
        )
    if code == "formula_nonfinite_values":
        return _format_nonfinite_values([issue], document)
    if code == "formula_cycle":
        return _format_named_formula_failure(
            [issue], document, "公式互相引用形成循环，未生成。"
        )
    if code in {CODE_DROPPED_CURVE, CODE_DROPPED_WINDOW}:
        return _format_dropped(code, [issue])
    if code == "invalid_rect":
        return _format_invalid_rect([issue])
    if code in {CODE_UNKNOWN_RECORD, CODE_SKIPPED_CHANNEL}:
        name = _skip_channel_name(issue.detail)
        if name and "显示块" in str(issue.detail or ""):
            detail = str(issue.detail or "").strip()
            if code not in detail and not _RECORD_INDEX_RE.search(detail):
                return detail
            return "部分曲线引用了无法解析的记录，已跳过。"
        if name and _FORMULA_SKIP_MARK not in str(issue.detail or ""):
            if not _RECORD_INDEX_RE.search(name):
                return f"1 个通道未导入：{name}"
        return "部分通道未导入。"
    if code == CODE_TRUNCATED_WINDOW:
        return "部分 WinWert 显示窗口截断，已跳过。"
    _LOG.info("unrecognized WWT issue code %s", code)
    return _GENERIC_USER_SUMMARY


def _dedupe_formula_skips(
    issues: list[WwtIssue], document
) -> list[WwtIssue]:
    concrete_names: set[str] = set()
    concrete_indexes: set[int] = set()
    for issue in issues:
        if issue.code not in _CONCRETE_FORMULA_CODES:
            continue
        index = _issue_record_index(issue)
        if index is not None:
            concrete_indexes.add(index)
        rec = _record_from_issue(issue, document)
        if rec is not None and rec.name:
            concrete_names.add(rec.name)
    kept: list[WwtIssue] = []
    for issue in issues:
        if issue.code in {
            CODE_UNSUPPORTED_FORMULA, CODE_SKIPPED_CHANNEL, CODE_UNKNOWN_RECORD,
        }:
            name = _skip_channel_name(issue.detail)
            index = _issue_record_index(issue)
            if name and name in concrete_names:
                continue
            if index is not None and index in concrete_indexes:
                continue
        kept.append(issue)
    return kept


def format_wwt_import_summary(
    issues, *, document=None, accepted: bool = False
) -> str:
    """One user-facing degraded-import summary. Empty → no yellow toast."""
    toastable: list[WwtIssue] = []
    for issue in issues or ():
        code = str(getattr(issue, "code", "") or "").strip()
        if not code or code in _USER_SILENT_CODES:
            continue
        if code == CODE_VIEW_CAP and not accepted:
            continue
        toastable.append(issue)
    toastable = _dedupe_formula_skips(toastable, document)
    if not toastable:
        return ""

    grouped: dict[str, list[WwtIssue]] = {}
    order: list[str] = []
    for issue in toastable:
        if issue.code not in grouped:
            grouped[issue.code] = []
            order.append(issue.code)
        grouped[issue.code].append(issue)

    parts: list[str] = []
    for code in order:
        bucket = grouped[code]
        if code == CODE_MISSING_FORMULA_REF:
            parts.append(_format_missing_formula_refs(bucket, document))
        elif code == CODE_UNSUPPORTED_FORMULA:
            parts.append(_format_unsupported_formula(bucket, document))
        elif code == "formula_axis_mismatch":
            parts.append(_format_named_formula_failure(
                bucket, document, "引用数据轴不一致，未生成。"
            ))
        elif code == "formula_shape_mismatch":
            parts.append(_format_named_formula_failure(
                bucket, document, "样本长度或形状不一致，未生成。"
            ))
        elif code == "formula_no_finite_values":
            parts.append(_format_named_formula_failure(
                bucket, document, "无有效数值，未生成。"
            ))
        elif code == "formula_nonfinite_values":
            parts.append(_format_nonfinite_values(bucket, document))
        elif code == "formula_cycle":
            parts.append(_format_named_formula_failure(
                bucket, document, "公式互相引用形成循环，未生成。"
            ))
        elif code in {CODE_DROPPED_CURVE, CODE_DROPPED_WINDOW}:
            parts.append(_format_dropped(code, bucket))
        elif code == CODE_VIEW_CAP:
            parts.append(_format_view_cap(bucket[0]))
        elif code == "invalid_rect":
            parts.append(_format_invalid_rect(bucket))
        elif code in {CODE_UNKNOWN_RECORD, CODE_SKIPPED_CHANNEL}:
            skip_names: list[str] = []
            display_parts: list[str] = []
            for issue in bucket:
                detail = str(issue.detail or "")
                if "显示块" in detail:
                    text = format_wwt_issue_for_user(issue, document=document)
                    if text:
                        display_parts.append(text)
                    continue
                name = _skip_channel_name(detail)
                if name and not _RECORD_INDEX_RE.search(name):
                    skip_names.append(name)
            if skip_names:
                unique_names = list(dict.fromkeys(skip_names))
                parts.append(
                    f"{len(unique_names)} 个通道未导入：" + "、".join(unique_names)
                )
            parts.extend(dict.fromkeys(display_parts))
        else:
            text = format_wwt_issue_for_user(bucket[0], document=document)
            if text:
                parts.append(text)
    return "；".join(dict.fromkeys(part for part in parts if part))


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


def _physical_from_raw(raw: np.ndarray, scale: float, offset: float) -> np.ndarray:
    """Map raw samples to physical units; replace the pen-up sentinel first.

    Detection must happen in the raw domain: a non-unit scale would turn
    ``-1e300`` into another finite value and leak it into the plotted range.
    """
    work = np.array(np.asarray(raw, dtype=np.float64), dtype=np.float64, copy=True)
    if work.ndim != 1:
        work = np.ravel(work)
        work = np.array(work, dtype=np.float64, copy=True)
    missing = work == _WWT_MISSING_SENTINEL
    if np.any(missing):
        work[missing] = np.nan
    return _freeze_array(work * scale + offset)


def _read_pars_formula(payload: bytes) -> str | None:
    """Return the formula only when a NUL terminator sits in the 256-byte window."""
    window = payload[:_PARS_FORMULA_WINDOW]
    if b"\0" not in window:
        return None
    text = _cstr(window)
    return text or None


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
    diagnostics: list[str] = []
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
                window = data[data_pos:min(scan, data_pos + _PARS_FORMULA_WINDOW)]
                formula = _read_pars_formula(window)
                if formula is None:
                    diagnostics.append(format_wwt_issue(
                        CODE_UNSUPPORTED_FORMULA,
                        f"record {rec_index}",
                    ))
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
            if not 0 < n < _MAX_ZEIT_SAMPLES:
                raise ValueError(
                    f"WWT 文件截断/损坏: 通道 {ch_name!r} 声明点数 {n} 超出范围"
                    f"（偏移 0x{pos:x}）: {name}")
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
            physical = _physical_from_raw(raw, a, c)
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

    injected: set[int] = set()
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
        injected.add(rec.index)

    for rec in derived:
        if rec.index in injected or rec.values is None:
            continue
        aux_item = {
            "name": rec.name,
            "record_index": rec.index,
            "tag": rec.tag,
            "n": int(rec.declared_n),
        }
        for group in groups:
            aux = group["source_metadata"]["wwt_auxiliary_records"]
            seen = {
                item.get("record_index")
                for item in aux
                if isinstance(item, dict)
            }
            if rec.index not in seen:
                aux.append(dict(aux_item))

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
