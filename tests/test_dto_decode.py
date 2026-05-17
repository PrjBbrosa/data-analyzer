"""Tests for pure byte-level XCP DTO decoding."""

from __future__ import annotations

import struct

from mf4_analyzer.acquisition_capture.daq_map import DaqMap, OdtEntry
from mf4_analyzer.acquisition_capture.dto_decode import decode_dto


def _map_single() -> DaqMap:
    return DaqMap(
        pid_to_odt={0: (0, 0)},
        entries={
            (0, 0): (
                OdtEntry("a", offset=3, size=2, datatype="UWORD", address=0x1000),
                OdtEntry("b", offset=5, size=2, datatype="s16", address=0x1002),
            ),
        },
        event_for_daq={0: 0},
    )


def test_decode_two_measurements_little_endian() -> None:
    pid = bytes([0])
    ts = struct.pack("<H", 1000)
    a = struct.pack("<H", 0x1234)
    b = struct.pack("<h", -42)
    frame = pid + ts + a + b

    samples = list(
        decode_dto(
            frame=frame,
            daq_map=_map_single(),
            timestamp_size=2,
            timestamp_unit_ns=1000,
            byte_order="MSB_LAST",
            base_monotonic_s=100.0,
        )
    )

    assert samples[0] == ("a", 100.001, float(0x1234))
    assert samples[1] == ("b", 100.001, -42.0)


def test_decode_no_timestamp_uses_base() -> None:
    no_ts_map = DaqMap(
        pid_to_odt={0: (0, 0)},
        entries={
            (0, 0): (
                OdtEntry("a", offset=1, size=2, datatype="u16", address=0x1000),
                OdtEntry("b", offset=3, size=2, datatype="s16", address=0x1002),
            ),
        },
        event_for_daq={0: 0},
    )
    frame = bytes([0]) + struct.pack("<H", 7) + struct.pack("<h", -1)

    samples = list(
        decode_dto(
            frame=frame,
            daq_map=no_ts_map,
            timestamp_size=0,
            timestamp_unit_ns=1000,
            byte_order="MSB_LAST",
            base_monotonic_s=50.0,
        )
    )

    assert samples == [("a", 50.0, 7.0), ("b", 50.0, -1.0)]


def test_decode_big_endian_signed_32() -> None:
    daq_map = DaqMap(
        pid_to_odt={0: (0, 0)},
        entries={
            (0, 0): (
                OdtEntry("x", offset=1, size=4, datatype="SLONG", address=0x1000),
            ),
        },
        event_for_daq={0: 0},
    )
    frame = bytes([0]) + struct.pack(">i", -123456789)

    samples = list(
        decode_dto(
            frame=frame,
            daq_map=daq_map,
            timestamp_size=0,
            timestamp_unit_ns=1000,
            byte_order="MSB_FIRST",
            base_monotonic_s=0.0,
        )
    )

    assert samples[0][2] == -123456789.0


def test_unknown_pid_yields_nothing() -> None:
    samples = list(
        decode_dto(
            frame=bytes([99]) + bytes(7),
            daq_map=_map_single(),
            timestamp_size=2,
            timestamp_unit_ns=1000,
            byte_order="MSB_LAST",
            base_monotonic_s=0.0,
        )
    )

    assert samples == []
