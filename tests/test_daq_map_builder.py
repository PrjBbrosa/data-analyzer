"""Tests for Stage 8 DAQ map construction."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from can_logger.p0.a2l_probe import (
    MeasurementSummary,
    _address_extension_of,
    _conversion_facts,
)
from can_logger.p0.ifdata_xcp import DaqEventInfo, DaqProcessorInfo, IfDataXcp
from mf4_analyzer.acquisition_capture.daq_map import bind_first_pids, build_daq_map
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement


def _ifdata(
    *,
    max_dto: int = 8,
    ts_size: int = 2,
    events: tuple[tuple[str, int], ...] = (("10ms", 8),),
) -> IfDataXcp:
    return IfDataXcp(
        cmd_id=0x500,
        resp_id=0x501,
        cmd_id_extended=False,
        resp_id_extended=False,
        can_fd=False,
        max_cto=8,
        max_dto=max_dto,
        byte_order="MSB_LAST",
        address_granularity="BYTE",
        daq_timestamp_size=ts_size,
        daq_timestamp_unit="1US",
        daq_timestamp_fixed=True,
        available_events=tuple(
            DaqEventInfo(
                number=i,
                name=name,
                cycle_time_ms=10.0,
                max_odt_entries=cap,
                properties=("DAQ",),
            )
            for i, (name, cap) in enumerate(events)
        ),
        daq_processor=DaqProcessorInfo(
            min_daq=0,
            max_event_channel=len(events),
            granularity_odt_entry_size_daq=1,
            overload_indication="EVENT",
        ),
    )


def _sel(
    name: str,
    addr: int,
    event: str | None,
    *,
    event_rate_hz: float = 100.0,
    payload_bytes: int = 2,
) -> SelectedMeasurement:
    return SelectedMeasurement(
        name=name,
        address_hex=f"0x{addr:08X}",
        event=event,
        event_rate_hz=event_rate_hz,
        payload_bytes=payload_bytes,
    )


def _meas(name: str, addr: int, datatype: str = "UWORD") -> MeasurementSummary:
    return MeasurementSummary(
        name=name,
        address=addr,
        datatype=datatype,
        unit="",
        conversion="",
    )


def _measurements(*items: tuple[str, int] | tuple[str, int, str]) -> dict[str, MeasurementSummary]:
    out: dict[str, MeasurementSummary] = {}
    for item in items:
        if len(item) == 2:
            name, addr = item
            datatype = "UWORD"
        else:
            name, addr, datatype = item
        out[name] = _meas(name, addr, datatype)
    return out


def test_single_event_three_measurements_pack_one_odt_when_max_dto_allows_it() -> None:
    selected = (
        _sel("a", 0x1000, "10ms"),
        _sel("b", 0x1002, "10ms"),
        _sel("c", 0x1004, "10ms"),
    )
    meas = _measurements(("a", 0x1000), ("b", 0x1002), ("c", 0x1004))

    daq_map = build_daq_map(selected, _ifdata(max_dto=9), meas)

    assert daq_map.pid_to_odt == {}
    entries = daq_map.entries[(0, 0)]
    assert [entry.measurement_name for entry in entries] == ["a", "b", "c"]
    assert [entry.offset for entry in entries] == [3, 5, 7]
    assert entries[0].address == 0x1000
    assert entries[0].datatype == "UWORD"
    assert entries[0].size == 2

    bound = bind_first_pids(daq_map, {0: 0x30})
    assert bound.pid_to_odt == {0x30: (0, 0)}


def test_multi_event_groups_into_separate_daq_lists() -> None:
    selected = (
        _sel("a", 0x1000, "10ms"),
        _sel("b", 0x2000, "100ms"),
    )
    meas = _measurements(("a", 0x1000), ("b", 0x2000))
    ifdata = _ifdata(events=(("10ms", 8), ("100ms", 8)))

    daq_map = build_daq_map(selected, ifdata, meas)

    assert daq_map.event_for_daq == {0: 0, 1: 1}
    assert sorted({daq for daq, _odt in daq_map.entries}) == [0, 1]


def test_too_many_measurements_for_one_odt_spills_to_second_odt() -> None:
    selected = tuple(
        _sel(chr(ord("a") + i), 0x1000 + i * 2, "10ms") for i in range(4)
    )
    meas = _measurements(
        *((chr(ord("a") + i), 0x1000 + i * 2) for i in range(4))
    )

    daq_map = build_daq_map(selected, _ifdata(max_dto=8), meas)

    odt0 = daq_map.entries[(0, 0)]
    odt1 = daq_map.entries[(0, 1)]
    assert len(odt0) + len(odt1) == 4
    payload_budget = 8 - 1 - 2
    assert sum(entry.size for entry in odt0) <= payload_budget
    assert sum(entry.size for entry in odt1) <= payload_budget


def test_build_daq_map_raises_when_measurement_lookup_missing() -> None:
    selected = (_sel("ghost", 0x1000, "10ms"),)

    with pytest.raises(ValueError, match="not in A2L summary"):
        build_daq_map(selected, _ifdata(), {})


def test_build_daq_map_raises_when_event_missing() -> None:
    selected = (_sel("a", 0x1000, None),)
    meas = _measurements(("a", 0x1000))

    with pytest.raises(ValueError, match="no event assigned"):
        build_daq_map(selected, _ifdata(), meas)


def test_linear_conversion_and_address_extension_reach_daq_entry() -> None:
    selected = (_sel("BatteryVoltage", 0x40001000, "10ms"),)
    source = SimpleNamespace(
        ecu_address_extension=SimpleNamespace(extension=0x02),
    )
    method = SimpleNamespace(
        conversionType="LINEAR",
        coeffs_linear=SimpleNamespace(a=0.015625, b=0.0),
        unit="V",
    )
    scale_a, scale_b, supported, _unit = _conversion_facts(
        "BatteryVoltageConv",
        {"BatteryVoltageConv": method},
    )
    measurements = {
        "BatteryVoltage": MeasurementSummary(
            name="BatteryVoltage",
            address=0x40001000,
            datatype="UWORD",
            unit="V",
            conversion="BatteryVoltageConv",
            address_extension=_address_extension_of(source),
            scale_a=scale_a,
            scale_b=scale_b,
            conversion_supported=supported,
        )
    }

    daq_map = build_daq_map(selected, _ifdata(), measurements)

    entry = daq_map.entries[(0, 0)][0]
    assert entry.address == 0x40001000
    assert entry.address_extension == 0x02
    assert entry.scale_a == pytest.approx(0.015625)
    assert entry.scale_b == pytest.approx(0.0)
    # dto_decode consumes OdtEntry.scale_a/scale_b as physical = raw*a+b.
    assert 640 * entry.scale_a + entry.scale_b == pytest.approx(10.0)


def test_unsupported_conversion_fails_instead_of_becoming_identity() -> None:
    selected = (_sel("StateText", 0x40002000, "10ms"),)
    measurements = {
        "StateText": MeasurementSummary(
            name="StateText",
            address=0x40002000,
            datatype="UBYTE",
            unit="",
            conversion="StateTable",
            conversion_supported=False,
        )
    }

    with pytest.raises(ValueError, match="unsupported conversion.*StateText"):
        build_daq_map(selected, _ifdata(), measurements)
