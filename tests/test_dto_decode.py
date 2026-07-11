"""Tests for pure byte-level XCP DTO decoding."""

from __future__ import annotations

import struct

import pytest

from mf4_analyzer.acquisition_capture.daq_map import DaqMap, OdtEntry
from mf4_analyzer.acquisition_capture.dto_decode import (
    DtoDecodeStatus,
    decode_dto,
    decode_dto_result,
)


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


def test_decode_applies_known_battery_voltage_conversion() -> None:
    daq_map = DaqMap(
        pid_to_odt={0: (0, 0)},
        entries={
            (0, 0): (
                OdtEntry(
                    "BatteryVoltage",
                    offset=1,
                    size=2,
                    datatype="UWORD",
                    address=0x1000,
                    scale_a=0.015625,
                    scale_b=0.0,
                ),
            ),
        },
        event_for_daq={0: 0},
    )
    frame = bytes([0]) + struct.pack("<H", 640)

    result = decode_dto_result(
        frame=frame,
        daq_map=daq_map,
        timestamp_size=0,
        timestamp_unit_ns=1000,
        byte_order="MSB_LAST",
        base_monotonic_s=50.0,
    )

    assert result.status is DtoDecodeStatus.SUCCESS
    assert result.samples == (("BatteryVoltage", 50.0, pytest.approx(10.0)),)


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


@pytest.mark.parametrize(
    ("frame", "timestamp_size", "daq_map", "expected_status"),
    (
        (bytes([99]) + bytes(7), 2, _map_single(), DtoDecodeStatus.UNKNOWN_PID),
        (bytes([0, 1]), 2, _map_single(), DtoDecodeStatus.SHORT_TIMESTAMP),
        (bytes([0]) + bytes(7), 3, _map_single(), DtoDecodeStatus.UNSUPPORTED_TIMESTAMP),
        (bytes([0, 1, 2, 3]), 2, _map_single(), DtoDecodeStatus.SHORT_PAYLOAD),
        (
            bytes([0, 1, 2, 3]),
            0,
            DaqMap(
                pid_to_odt={0: (0, 0)},
                entries={
                    (0, 0): (
                        OdtEntry(
                            "bad",
                            offset=1,
                            size=3,
                            datatype="NOT_A_REAL_TYPE",
                            address=0x1000,
                        ),
                    ),
                },
                event_for_daq={0: 0},
            ),
            DtoDecodeStatus.UNSUPPORTED_DATATYPE,
        ),
    ),
)
def test_decode_result_classifies_rejected_dto(
    frame: bytes,
    timestamp_size: int,
    daq_map: DaqMap,
    expected_status: DtoDecodeStatus,
) -> None:
    result = decode_dto_result(
        frame=frame,
        daq_map=daq_map,
        timestamp_size=timestamp_size,
        timestamp_unit_ns=1000,
        byte_order="MSB_LAST",
        base_monotonic_s=0.0,
    )

    assert result.status is expected_status
    assert result.samples == ()


def test_decode_result_reports_success_with_samples() -> None:
    frame = bytes([0]) + struct.pack("<H", 7) + struct.pack("<h", -1)

    result = decode_dto_result(
        frame=frame,
        daq_map=_no_ts_map(),
        timestamp_size=0,
        timestamp_unit_ns=1000,
        byte_order="MSB_LAST",
        base_monotonic_s=50.0,
    )

    assert result.status is DtoDecodeStatus.SUCCESS
    assert result.samples == (("a", 50.0, 7.0), ("b", 50.0, -1.0))


# T1-5 regression coverage: frame-arrival timestamp when the ECU does not emit
# a DAQ clock. ERD6 ships ``ts_size=0``; host arrival time gives MF4 a usable
# relative time axis when it is measured against the capture start.


def _no_ts_map() -> DaqMap:
    return DaqMap(
        pid_to_odt={0: (0, 0)},
        entries={
            (0, 0): (
                OdtEntry("a", offset=1, size=2, datatype="u16", address=0x1000),
                OdtEntry("b", offset=3, size=2, datatype="s16", address=0x1002),
            ),
        },
        event_for_daq={0: 0},
    )


def test_decode_no_timestamp_uses_frame_arrival_when_provided() -> None:
    """ts_size=0 + arrival becomes seconds since capture start."""

    frame = bytes([0]) + struct.pack("<H", 7) + struct.pack("<h", -1)

    samples = list(
        decode_dto(
            frame=frame,
            daq_map=_no_ts_map(),
            timestamp_size=0,
            timestamp_unit_ns=1000,
            byte_order="MSB_LAST",
            base_monotonic_s=50.0,
            frame_arrival_monotonic_s=50.123,
        )
    )

    assert samples == [
        ("a", pytest.approx(0.123), 7.0),
        ("b", pytest.approx(0.123), -1.0),
    ]


def test_decode_no_timestamp_two_arrivals_produce_increasing_timestamps() -> None:
    """Two DTO arrivals must yield relative, increasing per-sample timestamps."""

    daq_map = _no_ts_map()
    frame1 = bytes([0]) + struct.pack("<H", 7) + struct.pack("<h", -1)
    frame2 = bytes([0]) + struct.pack("<H", 8) + struct.pack("<h", -2)

    samples1 = list(
        decode_dto(
            frame=frame1,
            daq_map=daq_map,
            timestamp_size=0,
            timestamp_unit_ns=1000,
            byte_order="MSB_LAST",
            base_monotonic_s=100.0,
            frame_arrival_monotonic_s=100.0,
        )
    )
    samples2 = list(
        decode_dto(
            frame=frame2,
            daq_map=daq_map,
            timestamp_size=0,
            timestamp_unit_ns=1000,
            byte_order="MSB_LAST",
            base_monotonic_s=100.0,
            frame_arrival_monotonic_s=100.010,
        )
    )

    assert samples1[0][1] == 0.0
    assert samples2[0][1] == pytest.approx(0.010)
    assert samples2[0][1] > samples1[0][1]


def test_decode_no_timestamp_clamps_arrival_before_base_to_zero() -> None:
    frame = bytes([0]) + struct.pack("<H", 7) + struct.pack("<h", -1)

    samples = list(
        decode_dto(
            frame=frame,
            daq_map=_no_ts_map(),
            timestamp_size=0,
            timestamp_unit_ns=1000,
            byte_order="MSB_LAST",
            base_monotonic_s=100.0,
            frame_arrival_monotonic_s=99.999,
        )
    )

    assert samples == [("a", 0.0, 7.0), ("b", 0.0, -1.0)]


def test_decode_with_ecu_timestamp_ignores_frame_arrival() -> None:
    """When the ECU provides its own DAQ clock, the arrival hint must
    NOT override it — XCP timestamp wins."""

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
            frame_arrival_monotonic_s=9999.0,  # would be wrong if honored
        )
    )

    # Same as ``test_decode_two_measurements_little_endian``: ECU clock wins.
    assert samples[0] == ("a", 100.001, float(0x1234))
    assert samples[1] == ("b", 100.001, -42.0)


def test_decode_no_timestamp_falls_back_to_base_when_arrival_omitted() -> None:
    """Legacy callers that don't pass arrival keep working
    (regression coverage for the pre-T1-5 tests)."""

    frame = bytes([0]) + struct.pack("<H", 7) + struct.pack("<h", -1)

    samples = list(
        decode_dto(
            frame=frame,
            daq_map=_no_ts_map(),
            timestamp_size=0,
            timestamp_unit_ns=1000,
            byte_order="MSB_LAST",
            base_monotonic_s=42.0,
        )
    )

    assert samples == [("a", 42.0, 7.0), ("b", 42.0, -1.0)]
