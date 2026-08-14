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

from .blf_format import _emit_progress, _sample_reader_byte_progress

_CANOE_BASE_RE = re.compile(
    r"^base\s+(hex|dec)\s+timestamps\s+(absolute|relative)\b",
    re.IGNORECASE,
)
_SNIFF_BYTES = 8192
_SNIFF_MAX_LINES = 64
# Real CANoe ASC mixes CAN frames with denser SV lines; ~128 B/msg is a
# conservative hint so synthetic progress stays behind EOF until the final emit.
_ASC_BYTES_PER_FRAME_HINT = 128


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


# python-can ASC_MESSAGE_REGEX equivalent: a timestamped classic CAN or CAN FD
# line. Unparsed hits fall back to ASCReader so we never drop unknown frames.
_ASC_MESSAGE_HINT_RE = re.compile(
    r"^\s*\d+\.\d+\s+(?:\d+\s+(?:\S+\s+(?:Tx|Rx)|ErrorFrame)|CANFD)\b",
    re.IGNORECASE,
)


def _parse_asc_can_id(token, base):
    token = token.strip()
    if token.lower().endswith("x") and len(token) > 1:
        return int(token[:-1], base)
    return int(token, base)


def _parse_asc_bytes(tokens, base):
    if not tokens:
        return b""
    try:
        return bytes(int(tok, base) for tok in tokens)
    except ValueError:
        return None


def _parse_asc_canfd_tokens(tokens, timestamp, base):
    # [ts, CANFD, channel, dir|ErrorFrame, id, name_or_brs, ...]
    if len(tokens) < 5:
        return None
    if tokens[3].lower() == "errorframe":
        return "skip"
    rest = tokens[5:]
    if not rest:
        return None
    idx = 0 if rest[0].isdigit() else 1
    if len(rest) < idx + 4:
        return None
    try:
        data_length = int(rest[idx + 3])
    except (TypeError, ValueError):
        return None
    if data_length == 0:
        return "skip"
    payload = _parse_asc_bytes(rest[idx + 4:idx + 4 + data_length], base)
    if payload is None:
        return None
    try:
        aid = _parse_asc_can_id(tokens[4], base)
    except ValueError:
        return None
    return (timestamp, aid, payload)


def _parse_asc_data_line(tokens, base):
    if len(tokens) < 2:
        return None
    try:
        timestamp = float(tokens[0])
    except ValueError:
        return None
    channel = tokens[1]
    if channel.upper() == "CANFD":
        return _parse_asc_canfd_tokens(tokens, timestamp, base)
    if not channel.isdigit():
        return "skip"
    if len(tokens) < 3:
        return None
    if tokens[2].lower() == "errorframe":
        return "skip"
    if len(tokens) < 5:
        return None
    if tokens[3].lower() not in ("rx", "tx"):
        return None
    kind = tokens[4].lower()
    if kind == "r":
        return "skip"
    if kind != "d":
        return None
    if len(tokens) < 6:
        return None
    try:
        dlc = int(tokens[5], base)
    except ValueError:
        return None
    length = min(8, max(0, dlc), len(tokens) - 6)
    payload = _parse_asc_bytes(tokens[6:6 + length], base)
    if payload is None:
        return None
    try:
        aid = _parse_asc_can_id(tokens[2], base)
    except ValueError:
        return None
    return (timestamp, aid, payload)


def _read_asc_frames_fast(fp, progress_callback=None):
    """Parse classic / CAN FD data lines without constructing python-can Messages.

    Returns ``None`` when a CAN-looking line cannot be parsed, so the caller
    can fall back to ``ASCReader``. Empty-but-valid logs return ``[]``.
    """
    report_progress = callable(progress_callback)
    total_bytes = 1
    if report_progress:
        try:
            total_bytes = max(1, int(Path(fp).stat().st_size))
        except (OSError, TypeError, ValueError):
            total_bytes = 1
        _emit_progress(progress_callback, 0, total_bytes)

    base = 16
    frames = []
    bytes_seen = 0
    last_reported = 0
    try:
        with open(fp, "r", encoding="ascii", errors="replace", newline="") as fh:
            for raw_line in fh:
                bytes_seen += len(raw_line)
                stripped = raw_line.strip()
                if not stripped or stripped.startswith("//"):
                    continue
                header = _CANOE_BASE_RE.match(stripped)
                if header is not None:
                    base = 16 if header.group(1).lower() == "hex" else 10
                    continue
                tokens = stripped.split()
                parsed = _parse_asc_data_line(tokens, base)
                if parsed == "skip":
                    continue
                if parsed is None:
                    if _ASC_MESSAGE_HINT_RE.match(stripped):
                        return None
                    continue
                frames.append(parsed)
                if report_progress and (
                    len(frames) == 1 or len(frames) % 512 == 0
                ):
                    pos = min(bytes_seen, max(0, total_bytes - 1))
                    if pos > last_reported:
                        _emit_progress(progress_callback, pos, total_bytes)
                        last_reported = pos
    except (OSError, TypeError, ValueError):
        return None
    if report_progress:
        _emit_progress(progress_callback, total_bytes, total_bytes)
    return frames


def _read_asc_frames_python_can(fp, progress_callback=None):
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
                # ASCReader iterates a text stream; ``tell()`` raises during
                # ``for`` iteration, so the shared helper falls back to a
                # frame-based byte estimate.
                last_reported = _sample_reader_byte_progress(
                    reader,
                    frame_index,
                    total_bytes,
                    last_reported,
                    progress_callback,
                    bytes_per_frame_hint=_ASC_BYTES_PER_FRAME_HINT,
                )
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


def _read_asc_frames(fp, progress_callback=None):
    """Read a CANoe ASC into ``(timestamp, arbitration_id, data)`` tuples.

    Classic and CAN FD data lines are parsed in-process. Formats the fast
    path does not recognize fall back to python-can's ``ASCReader`` (default
    parameters; timestamps stay measurement-relative). Error/remote frames
    are dropped, matching ``_read_blf_frames``. ``SV:`` system-variable lines
    are skipped.
    """
    frames = _read_asc_frames_fast(fp, progress_callback)
    if frames is not None:
        return frames
    return _read_asc_frames_python_can(fp, progress_callback)
