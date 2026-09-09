"""Parser for ZFGE2 .zfd measurement files (ZwickRoell / TestRunPRO).

Supported profile: ZFGE2, first-and-only type 0 equidistant time record,
subsequent type 4 little-endian float32 measurements, every X reference 0,
identical sample counts. Time units ``sec`` / ``s`` map to seconds.

Ordinary measurement records use little-endian signed int16 type + signed
int32 count (type 0 inserts one reserved byte before count). Declared
payload length is checked before any array is allocated. Bytes after the
declared records are counted as trailing and are not scanned as channels.
"""
from __future__ import annotations

import math
import re
import struct
from pathlib import Path

import numpy as np
import pandas as pd

_MAGIC = b"ZFGE2"
_HEADER_LINES = 11
_PARSER_PROFILE = "zfge2-single-time-f32-v1"
_TIME_UNITS = frozenset({"sec", "s"})
_MARKER_NAME_RE = re.compile(r"^([A-Za-z]\d{1,3}):\s*(.*)$")
_ITEMSIZE_F32 = 4


class ZFDError(ValueError):
    """User-facing ZFD failure with file / record / offset context."""

    def __init__(
        self,
        message,
        *,
        filename,
        record_index=None,
        offset=None,
        reason=None,
        declared_count=None,
        expected_bytes=None,
        available_bytes=None,
    ):
        self.filename = filename
        self.record_index = record_index
        self.offset = offset
        self.reason = reason
        self.declared_count = declared_count
        self.expected_bytes = expected_bytes
        self.available_bytes = available_bytes
        super().__init__(message)


def _text_line(raw: bytes) -> str:
    return raw.decode("latin-1", "replace")


class _Cursor:
    """Exact-length reader. EOF stops immediately; never loops on short data."""

    def __init__(self, data: bytes, filename: str):
        self.data = data
        self.filename = filename
        self.pos = 0

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def need(self, n, *, record_index=None, what="数据"):
        if n < 0 or self.remaining() < n:
            raise ZFDError(
                f"ZFD 数据不完整：{what}被截断，未导入此文件。"
                f"（{self.filename}"
                f"{'' if record_index is None else f'，记录 {record_index + 1}'}"
                f"，偏移 {self.pos}）",
                filename=self.filename,
                record_index=record_index,
                offset=self.pos,
                reason=f"{what}截断",
                expected_bytes=n,
                available_bytes=max(0, self.remaining()),
            )

    def read(self, n, **kwargs) -> bytes:
        self.need(n, **kwargs)
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def unpack(self, fmt, **kwargs):
        size = struct.calcsize(fmt)
        try:
            return struct.unpack(fmt, self.read(size, **kwargs))
        except struct.error as exc:
            raise ZFDError(
                f"ZFD 数据不完整：字段无法解码，未导入此文件。"
                f"（{self.filename}，偏移 {self.pos}）",
                filename=self.filename,
                offset=self.pos,
                reason=str(exc),
            ) from exc

    def read_line(self, **kwargs) -> str:
        nl = self.data.find(b"\n", self.pos)
        if nl < 0:
            raise ZFDError(
                f"ZFD 数据不完整：文本行被截断，未导入此文件。"
                f"（{self.filename}，偏移 {self.pos}）",
                filename=self.filename,
                record_index=kwargs.get("record_index"),
                offset=self.pos,
                reason="缺少换行",
            )
        line = self.data[self.pos:nl]
        self.pos = nl + 1
        return _text_line(line)


def _incomplete_payload(cur, *, record_index, count, expected, available):
    rec = record_index + 1
    return ZFDError(
        f"ZFD 数据不完整：第 {rec} 个记录声明 {count:,} 点，数据区不足，未导入此文件。"
        f"（{cur.filename}，记录 {rec}，偏移 {cur.pos}，"
        f"期望 {expected} 字节，可用 {available} 字节）",
        filename=cur.filename,
        record_index=record_index,
        offset=cur.pos,
        reason="数据区不足",
        declared_count=count,
        expected_bytes=expected,
        available_bytes=available,
    )


def _time_invalid(filename, *, record_index=None, offset=None, reason="时间轴无效"):
    extra = f"（{filename}"
    if record_index is not None:
        extra += f"，记录 {record_index + 1}"
    if offset is not None:
        extra += f"，偏移 {offset}"
    extra += f"，{reason}）"
    return ZFDError(
        f"ZFD 时间轴无效，无法确定真实时长；请在源软件核对并重新导出。{extra}",
        filename=filename,
        record_index=record_index,
        offset=offset,
        reason=reason,
    )


def _unsupported(filename, summary, *, record_index=None, offset=None, reason=None):
    extra = f"（{filename}"
    if record_index is not None:
        extra += f"，记录 {record_index + 1}"
    if offset is not None:
        extra += f"，偏移 {offset}"
    extra += "）"
    return ZFDError(
        f"{summary}，未导入此文件。{extra}",
        filename=filename,
        record_index=record_index,
        offset=offset,
        reason=reason or summary,
    )


def _split_display_name(raw: str):
    text = raw.rstrip("\x00\r").strip()
    match = _MARKER_NAME_RE.match(text)
    if match:
        marker_id = match.group(1)
        name = match.group(2).strip()
        return marker_id, name or marker_id
    return None, text


def _unique_column(frame, preferred, marker_id, record_index, renamed):
    if preferred not in frame:
        return preferred
    if marker_id:
        candidate = f"{preferred} [{marker_id}]"
        if candidate not in frame:
            renamed.append({"original": preferred, "renamed": candidate})
            return candidate
    candidate = f"{preferred} [{record_index}]"
    while candidate in frame:
        candidate = f"{candidate}_"
    renamed.append({"original": preferred, "renamed": candidate})
    return candidate


def _read_header(cur: _Cursor):
    lines = []
    for _ in range(_HEADER_LINES):
        lines.append(cur.read_line().rstrip("\r"))
    magic = lines[0].strip()
    if magic != "ZFGE2":
        raise ValueError(f"不是有效的 ZFD 文件（缺少 ZFGE2 魔数）: {cur.filename}")
    return lines


def _read_annotations(cur: _Cursor):
    if cur.remaining() < 2:
        raise ZFDError(
            f"ZFD 数据不完整：注释数量被截断，未导入此文件。"
            f"（{cur.filename}，偏移 {cur.pos}）",
            filename=cur.filename,
            offset=cur.pos,
            reason="注释数量截断",
        )
    (ann_count,) = cur.unpack("<h")
    if ann_count < 0:
        raise ZFDError(
            f"ZFD 数据不完整：注释数量非法，未导入此文件。"
            f"（{cur.filename}，偏移 {cur.pos - 2}，声明 {ann_count}）",
            filename=cur.filename,
            offset=cur.pos - 2,
            reason="注释数量为负",
            declared_count=ann_count,
        )
    for index in range(ann_count):
        # 3×int16 + 3×float32, then a text line. Position fields are discarded.
        cur.read(18, what=f"第 {index + 1} 条注释")
        cur.read_line()
    return ann_count


def _read_record(cur: _Cursor, record_index: int):
    offset = cur.pos
    if cur.remaining() < 2:
        raise ZFDError(
            f"ZFD 数据不完整：第 {record_index + 1} 个记录类型被截断，未导入此文件。"
            f"（{cur.filename}，记录 {record_index + 1}，偏移 {offset}）",
            filename=cur.filename,
            record_index=record_index,
            offset=offset,
            reason="记录类型截断",
        )
    (typ,) = cur.unpack("<h", record_index=record_index, what="记录类型")
    if typ == 0:
        cur.read(1, record_index=record_index, what="时间记录保留字节")
        (count,) = cur.unpack("<i", record_index=record_index, what="时间记录点数")
        name = cur.read_line(record_index=record_index)
        unit = cur.read_line(record_index=record_index)
        t0, dt = cur.unpack("<dd", record_index=record_index, what="时间起点/间隔")
        if count <= 0:
            raise ZFDError(
                f"ZFD 数据不完整：第 {record_index + 1} 个记录声明 {count:,} 点，未导入此文件。"
                f"（{cur.filename}，记录 {record_index + 1}，偏移 {offset}）",
                filename=cur.filename,
                record_index=record_index,
                offset=offset,
                reason="点数非法",
                declared_count=count,
            )
        return {
            "index": record_index,
            "offset": offset,
            "type": 0,
            "count": int(count),
            "name": name.rstrip("\x00\r"),
            "unit": unit.rstrip("\x00\r"),
            "t0": float(t0),
            "dt": float(dt),
            "values": None,
            "x": None,
            "disp_min": None,
            "disp_max": None,
        }

    if typ in (1, 2, 3):
        raise _unsupported(
            cur.filename,
            "暂不支持此 ZFD 的整数或其他通道类型",
            record_index=record_index,
            offset=offset,
            reason=f"type {typ}",
        )
    if typ != 4:
        raise _unsupported(
            cur.filename,
            f"暂不支持此 ZFD 的通道类型 {typ}",
            record_index=record_index,
            offset=offset,
            reason=f"未知 type {typ}",
        )

    (count,) = cur.unpack("<i", record_index=record_index, what="测量点数")
    name = cur.read_line(record_index=record_index)
    unit = cur.read_line(record_index=record_index)
    (x,) = cur.unpack("<b", record_index=record_index, what="X 引用")
    cur.read(1, record_index=record_index, what="X 保留字节")
    disp_min, disp_max = cur.unpack("<dd", record_index=record_index, what="显示范围")
    if count <= 0:
        raise ZFDError(
            f"ZFD 数据不完整：第 {record_index + 1} 个记录声明 {count:,} 点，未导入此文件。"
            f"（{cur.filename}，记录 {record_index + 1}，偏移 {offset}）",
            filename=cur.filename,
            record_index=record_index,
            offset=offset,
            reason="点数非法",
            declared_count=count,
        )
    expected = int(count) * _ITEMSIZE_F32
    available = cur.remaining()
    if expected > available:
        raise _incomplete_payload(
            cur,
            record_index=record_index,
            count=int(count),
            expected=expected,
            available=available,
        )
    values = np.frombuffer(
        cur.read(expected, record_index=record_index, what="测量数据"),
        dtype="<f4",
        count=int(count),
    ).astype(np.float64, copy=False)
    if values.size != int(count):
        raise _incomplete_payload(
            cur,
            record_index=record_index,
            count=int(count),
            expected=expected,
            available=values.size * _ITEMSIZE_F32,
        )
    return {
        "index": record_index,
        "offset": offset,
        "type": 4,
        "count": int(count),
        "name": name.rstrip("\x00\r"),
        "unit": unit.rstrip("\x00\r"),
        "t0": None,
        "dt": None,
        "values": values,
        "x": int(x),
        "disp_min": float(disp_min),
        "disp_max": float(disp_max),
    }


def _build_time_axis(time_rec, filename):
    count = time_rec["count"]
    t0 = time_rec["t0"]
    dt = time_rec["dt"]
    unit = time_rec["unit"].strip().lower()
    if unit not in _TIME_UNITS:
        raise _time_invalid(
            filename,
            record_index=time_rec["index"],
            offset=time_rec["offset"],
            reason=f"未知时间单位 {time_rec['unit']!r}",
        )
    if not math.isfinite(t0) or t0 < 0:
        raise _time_invalid(
            filename,
            record_index=time_rec["index"],
            offset=time_rec["offset"],
            reason="起点非法",
        )
    if not math.isfinite(dt) or dt <= 0:
        raise _time_invalid(
            filename,
            record_index=time_rec["index"],
            offset=time_rec["offset"],
            reason="间隔非法",
        )
    with np.errstate(over="ignore", invalid="ignore"):
        time = t0 + np.arange(count, dtype=np.float64) * dt
    if not np.isfinite(time).all():
        raise _time_invalid(
            filename,
            record_index=time_rec["index"],
            offset=time_rec["offset"],
            reason="时间溢出",
        )
    if count > 1 and not bool(np.all(np.diff(time) > 0)):
        raise _time_invalid(
            filename,
            record_index=time_rec["index"],
            offset=time_rec["offset"],
            reason="时间不递增",
        )
    return time


def load_zfd_groups(fp):
    """Parse .zfd and return the same groups shape as ``DataLoader.load_hdf``."""
    name = Path(fp).name
    data = Path(fp).read_bytes()
    if not data.startswith(_MAGIC):
        raise ValueError(f"不是有效的 ZFD 文件（缺少 ZFGE2 魔数）: {name}")

    cur = _Cursor(data, name)
    header_lines = _read_header(cur)
    version = header_lines[1].strip() if len(header_lines) > 1 else ""
    title = header_lines[2].strip() if len(header_lines) > 2 else ""
    _read_annotations(cur)

    if cur.remaining() < 1:
        raise ZFDError(
            f"ZFD 数据不完整：通道数被截断，未导入此文件。（{name}，偏移 {cur.pos}）",
            filename=name,
            offset=cur.pos,
            reason="通道数截断",
        )
    (declared_records,) = cur.unpack("<b")
    if declared_records < 0:
        raise ZFDError(
            f"ZFD 数据不完整：通道数非法，未导入此文件。"
            f"（{name}，偏移 {cur.pos - 1}，声明 {declared_records}）",
            filename=name,
            offset=cur.pos - 1,
            reason="通道数为负",
            declared_count=declared_records,
        )

    records = []
    for index in range(declared_records):
        records.append(_read_record(cur, index))
    trailing_bytes = cur.remaining()

    time_recs = [rec for rec in records if rec["type"] == 0]
    meas_recs = [rec for rec in records if rec["type"] == 4]
    if not time_recs:
        raise _time_invalid(name, reason="缺失时间轴")
    if len(time_recs) > 1:
        raise _unsupported(
            name,
            "暂不支持此 ZFD 的多个时间轴",
            record_index=time_recs[1]["index"],
            offset=time_recs[1]["offset"],
        )
    if records[0]["type"] != 0:
        raise _time_invalid(
            name,
            record_index=0,
            offset=records[0]["offset"],
            reason="时间记录必须是第一条",
        )
    if not meas_recs:
        raise _unsupported(name, "暂不支持此 ZFD：没有测量通道")

    time_rec = time_recs[0]
    sample_count = time_rec["count"]
    for rec in meas_recs:
        if rec["x"] != 0:
            raise _unsupported(
                name,
                "暂不支持此 ZFD 的非零时间引用",
                record_index=rec["index"],
                offset=rec["offset"],
                reason=f"X={rec['x']}",
            )
        if rec["count"] != sample_count:
            raise ZFDError(
                f"ZFD 各记录点数不一致，未导入此文件。"
                f"（{name}，记录 {rec['index'] + 1}，"
                f"时间 {sample_count:,} 点，测量 {rec['count']:,} 点）",
                filename=name,
                record_index=rec["index"],
                offset=rec["offset"],
                reason="点数不一致",
                declared_count=rec["count"],
            )

    time = _build_time_axis(time_rec, name)
    frame = {"Time": time}
    units = {}
    cmeta = {}
    renamed = []
    for rec in meas_recs:
        marker_id, display = _split_display_name(rec["name"])
        preferred = display or marker_id or f"record_{rec['index']}"
        col = _unique_column(frame, preferred, marker_id, rec["index"], renamed)
        frame[col] = rec["values"]
        units[col] = rec["unit"].strip()
        cmeta[col] = {
            "marker_id": marker_id,
            "unit": units[col],
            "display_min": rec["disp_min"],
            "display_max": rec["disp_max"],
            "record_index": rec["index"],
            "record_type": rec["type"],
            "declared_count": rec["count"],
            "decoded_count": int(rec["values"].size),
            "x_record_index": rec["x"],
        }

    zfd_import = {
        "schema": 1,
        "parser_profile": _PARSER_PROFILE,
        "declared_record_count": int(declared_records),
        "parsed_record_count": len(records),
        "sample_count": int(sample_count),
        "time_record_index": 0,
        "time_start_s": float(time[0]),
        "time_step_s": float(time_rec["dt"]),
        "time_end_s": float(time[-1]),
        "duration_s": float(time[-1] - time[0]),
        "measurement_records_complete": True,
        "trailing_bytes": int(trailing_bytes),
        "time_name": time_rec["name"].strip(),
        "time_unit_original": time_rec["unit"],
    }
    smeta = {
        "source_kind": "zfd",
        "version": version,
        "title": title,
        "source_filename": name,
        "fs_estimated": False,
        "renamed_channels": renamed,
        "zfd_import": zfd_import,
    }
    return [{
        "data": pd.DataFrame(frame),
        "channels": list(frame.keys()),
        "units": units,
        "channel_metadata": cmeta,
        "source_metadata": smeta,
        "label_suffix": "",
    }]
