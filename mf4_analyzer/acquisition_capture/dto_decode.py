"""Pure byte-level DTO decoder for Stage 8 XCP DAQ frames."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
import struct

from mf4_analyzer.acquisition_capture.daq_map import DaqMap


_FMT_BY_DATATYPE = {
    "ubyte": "B",
    "sbyte": "b",
    "uword": "H",
    "sword": "h",
    "ulong": "I",
    "slong": "i",
    "a_uint64": "Q",
    "a_int64": "q",
    "float32_ieee": "f",
    "float64_ieee": "d",
    "u8": "B",
    "s8": "b",
    "u16": "H",
    "s16": "h",
    "u32": "I",
    "s32": "i",
    "u64": "Q",
    "s64": "q",
    "f32": "f",
    "f64": "d",
}


class DtoDecodeStatus(str, Enum):
    """One-frame decode outcome used by backend diagnostics."""

    SUCCESS = "success"
    EMPTY_FRAME = "empty_frame"
    UNKNOWN_PID = "unknown_pid"
    SHORT_TIMESTAMP = "short_timestamp"
    UNSUPPORTED_TIMESTAMP = "unsupported_timestamp"
    UNSUPPORTED_DATATYPE = "unsupported_datatype"
    SHORT_PAYLOAD = "short_payload"
    DECODE_ERROR = "decode_error"


@dataclass(frozen=True)
class DtoDecodeResult:
    status: DtoDecodeStatus
    samples: tuple[tuple[str, float, float], ...] = ()
    error: str | None = None


def decode_dto(
    *,
    frame: bytes,
    daq_map: DaqMap,
    timestamp_size: int,
    timestamp_unit_ns: int,
    byte_order: str,
    base_monotonic_s: float,
    frame_arrival_monotonic_s: float | None = None,
) -> Iterator[tuple[str, float, float]]:
    """Yield ``(measurement_name, timestamp_s, value)`` from one DTO frame.

    Timestamp resolution order:

    1. ``timestamp_size > 0`` — parse the ECU clock from bytes 1..N
       and use ``base_monotonic_s + ts_raw * timestamp_unit_ns / 1e9``.
       This is the canonical XCP path.

    2. ``timestamp_size == 0`` and ``frame_arrival_monotonic_s`` is
       given — use the host arrival time relative to ``base_monotonic_s``.
       **This is the only thing that lets ERD6-class ECUs (no DAQ
       timestamps) produce a usable MF4 time axis.** Without this, every
       sample shares the capture-start monotonic value and the MF4 is
       unsortable.

    3. ``timestamp_size == 0`` and arrival omitted — fall back to
       ``base_monotonic_s``. Kept for backwards compat with the
       existing ``tests/test_dto_decode.py`` suite that pre-dates the
       arrival-time wiring; production capture loops MUST pass an
       arrival.
    """

    return iter(
        decode_dto_result(
            frame=frame,
            daq_map=daq_map,
            timestamp_size=timestamp_size,
            timestamp_unit_ns=timestamp_unit_ns,
            byte_order=byte_order,
            base_monotonic_s=base_monotonic_s,
            frame_arrival_monotonic_s=frame_arrival_monotonic_s,
        ).samples
    )


def decode_dto_result(
    *,
    frame: bytes,
    daq_map: DaqMap,
    timestamp_size: int,
    timestamp_unit_ns: int,
    byte_order: str,
    base_monotonic_s: float,
    frame_arrival_monotonic_s: float | None = None,
) -> DtoDecodeResult:
    """Decode one DTO without hiding why a frame was rejected.

    The legacy :func:`decode_dto` iterator remains the public compatibility
    surface.  The Vector backend uses this structured result so unknown PIDs
    and malformed frames cannot silently disappear from acceptance evidence.
    A rejected frame never emits a partial set of measurement samples.
    """

    if not frame:
        return DtoDecodeResult(
            DtoDecodeStatus.EMPTY_FRAME,
            error="DTO frame is empty",
        )
    pid = frame[0]
    odt_key = daq_map.pid_to_odt.get(pid)
    if odt_key is None:
        return DtoDecodeResult(
            DtoDecodeStatus.UNKNOWN_PID,
            error=f"unknown DTO PID 0x{pid:02X}",
        )

    endian = "<" if byte_order == "MSB_LAST" else ">"
    if timestamp_size > 0:
        ts_fmt = {1: "B", 2: "H", 4: "I"}.get(timestamp_size)
        if ts_fmt is None:
            return DtoDecodeResult(
                DtoDecodeStatus.UNSUPPORTED_TIMESTAMP,
                error=f"unsupported DTO timestamp size {timestamp_size}",
            )
        ts_bytes = frame[1 : 1 + timestamp_size]
        if len(ts_bytes) < timestamp_size:
            return DtoDecodeResult(
                DtoDecodeStatus.SHORT_TIMESTAMP,
                error=(
                    f"DTO PID 0x{pid:02X} has {len(ts_bytes)} timestamp bytes; "
                    f"expected {timestamp_size}"
                ),
            )
        try:
            ts_raw = struct.unpack(endian + ts_fmt, ts_bytes)[0]
        except struct.error as exc:
            return DtoDecodeResult(DtoDecodeStatus.DECODE_ERROR, error=str(exc))
        timestamp_s = base_monotonic_s + (ts_raw * timestamp_unit_ns) / 1e9
    elif frame_arrival_monotonic_s is not None:
        timestamp_s = max(0.0, frame_arrival_monotonic_s - base_monotonic_s)
    else:
        timestamp_s = base_monotonic_s

    entries = daq_map.entries.get(odt_key)
    if entries is None:
        return DtoDecodeResult(
            DtoDecodeStatus.DECODE_ERROR,
            error=f"DTO PID 0x{pid:02X} maps to missing ODT {odt_key!r}",
        )

    decoded: list[tuple[str, float, float]] = []
    for entry in entries:
        fmt = _FMT_BY_DATATYPE.get(entry.datatype.lower())
        if fmt is None:
            return DtoDecodeResult(
                DtoDecodeStatus.UNSUPPORTED_DATATYPE,
                error=(
                    f"DTO PID 0x{pid:02X} measurement {entry.measurement_name!r} "
                    f"uses unsupported datatype {entry.datatype!r}"
                ),
            )
        payload = frame[entry.offset : entry.offset + entry.size]
        if len(payload) < entry.size:
            return DtoDecodeResult(
                DtoDecodeStatus.SHORT_PAYLOAD,
                error=(
                    f"DTO PID 0x{pid:02X} measurement {entry.measurement_name!r} "
                    f"has {len(payload)} bytes; expected {entry.size}"
                ),
            )
        try:
            raw = struct.unpack(endian + fmt, payload)[0]
        except struct.error as exc:
            return DtoDecodeResult(DtoDecodeStatus.DECODE_ERROR, error=str(exc))
        value = float(raw) * entry.scale_a + entry.scale_b
        decoded.append((entry.measurement_name, timestamp_s, value))

    return DtoDecodeResult(DtoDecodeStatus.SUCCESS, tuple(decoded))
