"""CANoe ASC (Vector CAN text log) sniffing and frame reading.

``.asc`` is also used for generic tabular ASCII in this project. Evidence-based
sniffing keeps the two formats on separate paths: a hit here means the BLF/CAN
decode chain; a miss falls through to ``ascii_format`` / ``load_ascii``.

``can`` stays lazily imported so importing this module never requires the
optional CAN stack.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..diagnostics import throttled
from .blf_format import _emit_progress, _sample_reader_byte_progress

_LOG = logging.getLogger(__name__)

_CANOE_BASE_RE = re.compile(
    r"^base\s+(hex|dec)\s+timestamps\s+(absolute|relative)\b",
    re.IGNORECASE,
)
_SNIFF_BYTES = 8192
_SNIFF_MAX_LINES = 64
_PREFLIGHT_BYTES = _SNIFF_BYTES
_PREFLIGHT_MAX_LINES = _SNIFF_MAX_LINES
# Real CANoe ASC mixes CAN frames with denser SV lines; ~128 B/msg is a
# conservative hint so synthetic progress stays behind EOF until the final emit.
_ASC_BYTES_PER_FRAME_HINT = 128

ASC_BACKEND_FAST = "fast"
ASC_BACKEND_PYTHON_CAN = "python-can"
ASC_PHASE_PREFLIGHT = "预检"
ASC_PHASE_FAST = "快速解析"
ASC_PHASE_FALLBACK = "兼容解析重试"
_WORK_PERCENT_MAX = 99
_PREFLIGHT_PERCENT_MAX = 2


class AscFallbackReason(str, Enum):
    """Why the fast parser handed the file to python-can."""

    UNSUPPORTED_SYNTAX = "unsupported_syntax"
    FAST_READ_FAILED = "fast_read_failed"


class AscParseCancelled(RuntimeError):
    """Raised when ``cancel_check`` trips before an ASC result is delivered."""

    def __init__(self, outcome=None):
        super().__init__("CANoe ASC 解析已取消")
        self.outcome = outcome


@dataclass(frozen=True)
class AscParseOutcome:
    """Single result object shared by UI, Batch, and the ASC reader."""

    frames: tuple
    backend: str
    fallback_reason: AscFallbackReason | None
    bytes_consumed_before_fallback: int
    warning: str | None = None
    diagnostic_context: dict = field(default_factory=dict)
    cancelled: bool = False

    @property
    def frame_count(self) -> int:
        return len(self.frames)


@dataclass(frozen=True)
class _PreflightResult:
    supported: bool
    bytes_read: int
    reason: AscFallbackReason | None = None


@dataclass(frozen=True)
class _FastScanResult:
    frames: list | None
    bytes_seen: int
    fallback_reason: AscFallbackReason | None = None


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


def _asc_file_size(fp) -> int:
    try:
        return max(1, int(Path(fp).stat().st_size))
    except (OSError, TypeError, ValueError):
        return 1


def _cancelled(cancel_check) -> bool:
    return callable(cancel_check) and bool(cancel_check())


def _raise_if_cancelled(cancel_check, *, outcome=None):
    if _cancelled(cancel_check):
        raise AscParseCancelled(outcome)


def _preflight_asc_format(fp) -> _PreflightResult:
    """Judge whether the fast parser can handle a bounded file prefix.

    Reads at most 8 KiB / ~64 lines and reuses the line classifiers. It does
    not accumulate frames or copy the full-file scanner.
    """
    bytes_read = 0
    base = 16
    try:
        with open(fp, "r", encoding="ascii", errors="replace", newline="") as fh:
            for index, raw_line in enumerate(fh):
                bytes_read += len(raw_line)
                if index >= _PREFLIGHT_MAX_LINES or bytes_read >= _PREFLIGHT_BYTES:
                    break
                stripped = raw_line.strip()
                if not stripped or stripped.startswith("//"):
                    continue
                header = _CANOE_BASE_RE.match(stripped)
                if header is not None:
                    base = 16 if header.group(1).lower() == "hex" else 10
                    continue
                parsed = _parse_asc_data_line(stripped.split(), base)
                if parsed == "skip":
                    continue
                if parsed is None and _ASC_MESSAGE_HINT_RE.match(stripped):
                    return _PreflightResult(
                        False,
                        bytes_read,
                        AscFallbackReason.UNSUPPORTED_SYNTAX,
                    )
    except (OSError, TypeError, ValueError):
        return _PreflightResult(
            False, bytes_read, AscFallbackReason.FAST_READ_FAILED,
        )
    return _PreflightResult(True, bytes_read, None)


class _AscProgressCoordinator:
    """Map preflight / fast / fallback / finalize onto monotonic 0–100 progress."""

    def __init__(self, progress_callback, *, cancel_check=None):
        self._callback = progress_callback
        self._cancel_check = cancel_check
        self._high_water = 0
        self._phase = ASC_PHASE_PREFLIGHT
        self._lo = 0
        self._hi = _PREFLIGHT_PERCENT_MAX
        self._complete = False
        self._emitted_phase = None
        self._emitted = False

    def start(self):
        self._forward(0, ASC_PHASE_PREFLIGHT)

    def note_preflight(self, supported: bool):
        self._forward(_PREFLIGHT_PERCENT_MAX, ASC_PHASE_PREFLIGHT)
        if supported:
            self._phase = ASC_PHASE_FAST
            self._lo = _PREFLIGHT_PERCENT_MAX
            self._hi = _WORK_PERCENT_MAX
        else:
            self.enter_fallback()

    def enter_fallback(self):
        self._phase = ASC_PHASE_FALLBACK
        self._lo = self._high_water
        self._hi = _WORK_PERCENT_MAX
        self._forward(self._high_water, ASC_PHASE_FALLBACK)

    def as_callback(self):
        def _cb(current, total, *_args):
            _raise_if_cancelled(self._cancel_check)
            denom = max(1, int(total))
            frac = min(1.0, max(0.0, int(current) / denom))
            percent = self._lo + int(frac * (self._hi - self._lo))
            self._forward(percent, self._phase)

        return _cb

    def complete(self):
        if self._complete:
            return
        self._complete = True
        self._high_water = 100
        self._emit(100, 100, self._phase)

    def _forward(self, percent, phase):
        percent = int(percent)
        if not self._complete:
            percent = min(percent, _WORK_PERCENT_MAX)
        percent = max(self._high_water, percent)
        if (
            self._emitted
            and percent == self._high_water
            and phase == self._emitted_phase
        ):
            return
        self._high_water = percent
        self._emitted_phase = phase
        self._emitted = True
        self._emit(percent, 100, phase)

    def _emit(self, current, total, phase):
        if not callable(self._callback):
            return
        try:
            self._callback(int(current), max(1, int(total)), phase)
            return
        except TypeError:
            pass
        except Exception:
            return
        try:
            self._callback(int(current), max(1, int(total)))
        except Exception:
            pass


def _fallback_warning(reason: AscFallbackReason | None) -> str:
    if reason is AscFallbackReason.UNSUPPORTED_SYNTAX:
        return "不支持的 ASC 语法，已切换到兼容解析重试"
    return "快速解析失败，已切换到兼容解析重试"


def _log_fallback(reason: AscFallbackReason | None, bytes_consumed: int):
    reason_value = (
        reason.value if isinstance(reason, AscFallbackReason) else "unknown"
    )
    throttled(
        _LOG,
        f"asc-fallback:{reason_value}",
        logging.WARNING,
        "CANoe ASC 快速解析无法继续（%s，已读 %d 字节），进入兼容解析重试",
        reason_value,
        int(bytes_consumed),
    )


def _outcome(
    frames,
    *,
    backend: str,
    fallback_reason: AscFallbackReason | None = None,
    bytes_consumed_before_fallback: int = 0,
    cancelled: bool = False,
) -> AscParseOutcome:
    warning = None
    context = {"backend": backend, "cancelled": cancelled}
    if fallback_reason is not None:
        warning = _fallback_warning(fallback_reason)
        context["fallback_reason"] = fallback_reason.value
        context["bytes_consumed_before_fallback"] = int(
            bytes_consumed_before_fallback
        )
    return AscParseOutcome(
        frames=tuple(frames or ()),
        backend=backend,
        fallback_reason=fallback_reason,
        bytes_consumed_before_fallback=int(bytes_consumed_before_fallback),
        warning=warning,
        diagnostic_context=context,
        cancelled=cancelled,
    )


def _read_asc_frames_fast(fp, progress_callback=None, *, cancel_check=None):
    """Parse classic / CAN FD data lines without constructing python-can Messages.

    Returns a :class:`_FastScanResult`. ``frames is None`` means the caller
    should fall back to ``ASCReader``. Empty-but-valid logs return ``[]``.
    """
    report_progress = callable(progress_callback)
    total_bytes = 1
    if report_progress:
        total_bytes = _asc_file_size(fp)
        _emit_progress(progress_callback, 0, total_bytes)

    base = 16
    frames = []
    bytes_seen = 0
    last_reported = 0
    try:
        with open(fp, "r", encoding="ascii", errors="replace", newline="") as fh:
            for raw_line in fh:
                _raise_if_cancelled(cancel_check)
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
                        return _FastScanResult(
                            None,
                            bytes_seen,
                            AscFallbackReason.UNSUPPORTED_SYNTAX,
                        )
                    continue
                frames.append(parsed)
                if report_progress and (
                    len(frames) == 1 or len(frames) % 512 == 0
                ):
                    pos = min(bytes_seen, max(0, total_bytes - 1))
                    if pos > last_reported:
                        _emit_progress(progress_callback, pos, total_bytes)
                        last_reported = pos
    except AscParseCancelled:
        raise
    except (OSError, TypeError, ValueError):
        return _FastScanResult(
            None, bytes_seen, AscFallbackReason.FAST_READ_FAILED,
        )
    return _FastScanResult(frames, bytes_seen, None)


def _read_asc_frames_python_can(
    fp, progress_callback=None, *, cancel_check=None,
):
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
        total_bytes = _asc_file_size(fp)
        _emit_progress(progress_callback, 0, total_bytes)
    last_reported = 0
    try:
        for frame_index, msg in enumerate(reader, 1):
            _raise_if_cancelled(cancel_check)
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
    except AscParseCancelled:
        raise
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


def read_asc_outcome(fp, progress_callback=None, *, cancel_check=None):
    """Parse a CANoe ASC and return a single :class:`AscParseOutcome`.

    External progress is 0–100, monotonically non-decreasing, and reaches
    100 only after the final frames are in hand. Format-incompatible input
    may fall back to python-can; programming errors still propagate.
    """
    coordinator = _AscProgressCoordinator(
        progress_callback, cancel_check=cancel_check,
    )
    coordinator.start()
    _raise_if_cancelled(cancel_check)
    preflight = _preflight_asc_format(fp)
    _raise_if_cancelled(cancel_check)
    coordinator.note_preflight(preflight.supported)

    if not preflight.supported:
        _log_fallback(preflight.reason, preflight.bytes_read)
        frames = _read_asc_frames_python_can(
            fp,
            progress_callback=coordinator.as_callback(),
            cancel_check=cancel_check,
        )
        outcome = _outcome(
            frames,
            backend=ASC_BACKEND_PYTHON_CAN,
            fallback_reason=preflight.reason,
            bytes_consumed_before_fallback=preflight.bytes_read,
        )
        coordinator.complete()
        return outcome

    fast = _read_asc_frames_fast(
        fp,
        progress_callback=coordinator.as_callback(),
        cancel_check=cancel_check,
    )
    if fast.frames is not None:
        outcome = _outcome(fast.frames, backend=ASC_BACKEND_FAST)
        coordinator.complete()
        return outcome

    _log_fallback(fast.fallback_reason, fast.bytes_seen)
    coordinator.enter_fallback()
    frames = _read_asc_frames_python_can(
        fp,
        progress_callback=coordinator.as_callback(),
        cancel_check=cancel_check,
    )
    outcome = _outcome(
        frames,
        backend=ASC_BACKEND_PYTHON_CAN,
        fallback_reason=fast.fallback_reason,
        bytes_consumed_before_fallback=fast.bytes_seen,
    )
    coordinator.complete()
    return outcome


def _read_asc_frames(fp, progress_callback=None, *, cancel_check=None):
    """Read a CANoe ASC into ``(timestamp, arbitration_id, data)`` tuples.

    Classic and CAN FD data lines are parsed in-process after a bounded
    preflight. Formats the fast path does not recognize fall back to
    python-can's ``ASCReader`` (default parameters; timestamps stay
    measurement-relative). Error/remote frames are dropped, matching
    ``_read_blf_frames``. ``SV:`` system-variable lines are skipped.
    """
    return list(
        read_asc_outcome(
            fp,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        ).frames
    )
