"""Pure byte-level DTO decoder for Stage 8 XCP DAQ frames."""

from __future__ import annotations

from collections.abc import Iterator
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


def decode_dto(
    *,
    frame: bytes,
    daq_map: DaqMap,
    timestamp_size: int,
    timestamp_unit_ns: int,
    byte_order: str,
    base_monotonic_s: float,
) -> Iterator[tuple[str, float, float]]:
    """Yield ``(measurement_name, timestamp_s, value)`` from one DTO frame."""

    if not frame:
        return
    odt_key = daq_map.pid_to_odt.get(frame[0])
    if odt_key is None:
        return

    endian = "<" if byte_order == "MSB_LAST" else ">"
    timestamp_s = base_monotonic_s
    if timestamp_size > 0:
        ts_fmt = {1: "B", 2: "H", 4: "I"}.get(timestamp_size)
        if ts_fmt is None:
            return
        ts_bytes = frame[1 : 1 + timestamp_size]
        if len(ts_bytes) < timestamp_size:
            return
        ts_raw = struct.unpack(endian + ts_fmt, ts_bytes)[0]
        timestamp_s = base_monotonic_s + (ts_raw * timestamp_unit_ns) / 1e9

    for entry in daq_map.entries[odt_key]:
        fmt = _FMT_BY_DATATYPE.get(entry.datatype.lower())
        if fmt is None:
            continue
        payload = frame[entry.offset : entry.offset + entry.size]
        if len(payload) < entry.size:
            continue
        raw = struct.unpack(endian + fmt, payload)[0]
        value = float(raw) * entry.scale_a + entry.scale_b
        yield entry.measurement_name, timestamp_s, value
