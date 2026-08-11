"""CANoe ASC (Vector CAN text log) sniffing and frame reading.

``.asc`` is also used for generic tabular ASCII in this project. Evidence-based
sniffing keeps the two formats on separate paths: a hit here means the BLF/CAN
decode chain; a miss falls through to ``ascii_format`` / ``load_ascii``.

``can`` stays lazily imported so importing this module never requires the
optional CAN stack.
"""
from __future__ import annotations

import re
from pathlib import Path

from .blf_format import _emit_progress

_CANOE_BASE_RE = re.compile(
    r"^base\s+(hex|dec)\s+timestamps\s+(absolute|relative)\b",
    re.IGNORECASE,
)
_SNIFF_BYTES = 8192
_SNIFF_MAX_LINES = 64


def sniff_canoe_asc(path) -> bool:
    """Return True when ``path`` looks like a CANoe CAN bus text log.

    Reads at most the first 8 KiB / ~64 lines and looks for the mandatory
    ``base hex|dec timestamps absolute|relative`` header line. Any IO or
    decode failure returns False so callers can fall back to tabular ASCII
    without introducing a new failure mode.
    """
    try:
        with open(path, "rb") as fh:
            raw = fh.read(_SNIFF_BYTES)
    except (OSError, TypeError, ValueError):
        return False
    if not raw:
        return False
    try:
        text = raw.decode("ascii", errors="replace")
    except Exception:
        return False
    for index, line in enumerate(text.splitlines()):
        if index >= _SNIFF_MAX_LINES:
            break
        if _CANOE_BASE_RE.match(line.lstrip()):
            return True
    return False


def _read_asc_frames(fp, progress_callback=None):
    """Read a CANoe ASC into ``(timestamp, arbitration_id, data)`` tuples.

    Uses python-can's ``ASCReader`` with defaults (timestamps stay measurement-
    relative). Error/remote frames are dropped, matching ``_read_blf_frames``.
    ``SV:`` system-variable lines are skipped by the reader itself.
    """
    try:
        from can.io import ASCReader
    except ImportError as exc:
        raise ImportError(
            "python-can 未安装，无法读取 CANoe ASC 文件。请先 pip install python-can"
        ) from exc

    frames = []
    reader = ASCReader(str(fp))
    report_progress = callable(progress_callback)
    total_bytes = 1
    if report_progress:
        try:
            total_bytes = max(1, int(Path(fp).stat().st_size))
        except (OSError, TypeError, ValueError):
            total_bytes = 1
        _emit_progress(progress_callback, 0, total_bytes)
    last_reported = 0
    try:
        for frame_index, msg in enumerate(reader, 1):
            if report_progress and (
                frame_index == 1 or frame_index % 512 == 0
            ):
                try:
                    byte_pos = int(reader.file.tell())
                except (AttributeError, OSError, ValueError):
                    byte_pos = last_reported
                if byte_pos > last_reported:
                    _emit_progress(
                        progress_callback,
                        min(byte_pos, total_bytes),
                        total_bytes,
                    )
                    last_reported = byte_pos
            if msg.is_error_frame or msg.is_remote_frame:
                continue
            frames.append(
                (float(msg.timestamp), int(msg.arbitration_id), bytes(msg.data))
            )
    finally:
        stop = getattr(reader, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                pass
    if report_progress:
        _emit_progress(progress_callback, total_bytes, total_bytes)
    return frames
