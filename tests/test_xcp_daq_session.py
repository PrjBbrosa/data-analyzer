"""Exact dynamic-DAQ sequence tests without permissive external mocks."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from can_logger.p0.a2l_probe import MeasurementSummary
from can_logger.p0.ifdata_xcp import DaqEventInfo, DaqProcessorInfo, IfDataXcp
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.acquisition_capture.xcp_daq_session import DaqAllocError, XcpDaqSession


def _ifdata(*, timestamp_size: int = 0) -> IfDataXcp:
    return IfDataXcp(
        cmd_id=0x500,
        resp_id=0x501,
        cmd_id_extended=False,
        resp_id_extended=False,
        can_fd=False,
        max_cto=8,
        max_dto=8,
        byte_order="MSB_LAST",
        address_granularity="BYTE",
        daq_timestamp_size=timestamp_size,
        daq_timestamp_unit="1US",
        daq_timestamp_fixed=bool(timestamp_size),
        available_events=(DaqEventInfo(3, "10ms", 10.0, 8, ("DAQ",)),),
        daq_processor=DaqProcessorInfo(0, 1, 1, "EVENT"),
    )


def _selected() -> tuple[SelectedMeasurement, ...]:
    return (
        SelectedMeasurement("a", event="10ms", payload_bytes=2, address_hex="0x1000"),
        SelectedMeasurement("b", event="10ms", payload_bytes=2, address_hex="0x1002"),
    )


class _Master:
    def __init__(self, *, first_pid: int = 0x40) -> None:
        self.first_pid = first_pid
        self.calls: list[tuple[object, ...]] = []

    def connect(self):
        self.calls.append(("connect",))
        return SimpleNamespace(resource=0)

    def getStatus(self):  # noqa: N802
        self.calls.append(("getStatus",))
        return SimpleNamespace(resourceProtectionStatus=SimpleNamespace(daq=False))

    def getDaqProcessorInfo(self):  # noqa: N802
        self.calls.append(("getDaqProcessorInfo",))
        return SimpleNamespace(maxDaq=8)

    def freeDaq(self):  # noqa: N802
        self.calls.append(("freeDaq",))

    def allocDaq(self, daq_count):  # noqa: N802
        self.calls.append(("allocDaq", daq_count))

    def allocOdt(self, daq_list_number, odt_count):  # noqa: N802
        self.calls.append(("allocOdt", daq_list_number, odt_count))

    def allocOdtEntry(self, daq_list_number, odt_number, odt_entries_count):  # noqa: N802
        self.calls.append(("allocOdtEntry", daq_list_number, odt_number, odt_entries_count))

    def setDaqPtr(self, daq_list_number, odt_number, entry_index):  # noqa: N802
        self.calls.append(("setDaqPtr", daq_list_number, odt_number, entry_index))

    def writeDaq(self, bit_offset, entry_size, address_ext, address):  # noqa: N802
        self.calls.append(("writeDaq", bit_offset, entry_size, address_ext, address))

    def setDaqListMode(self, mode, daq_list_number, event_channel_number, prescaler, priority):  # noqa: N802
        self.calls.append(("setDaqListMode", mode, daq_list_number, event_channel_number, prescaler, priority))

    def startStopDaqList(self, mode, daq_list_number):  # noqa: N802
        self.calls.append(("startStopDaqList", mode, daq_list_number))
        return SimpleNamespace(firstPid=self.first_pid)

    def startStopSynch(self, mode):  # noqa: N802
        self.calls.append(("startStopSynch", mode))

    def disconnect(self):
        self.calls.append(("disconnect",))


def _measurements() -> dict[str, MeasurementSummary]:
    return {
        "a": MeasurementSummary("a", 0x1000, "UWORD", "", ""),
        "b": MeasurementSummary("b", 0x1002, "UWORD", "", ""),
    }


def test_dynamic_daq_uses_pinned_order_and_ecu_first_pid() -> None:
    master = _Master(first_pid=0x40)
    session = XcpDaqSession(master=master, ifdata=_ifdata(), measurements=_measurements())
    session.start(_selected())

    assert master.calls == [
        ("connect",),
        ("getStatus",),
        ("getDaqProcessorInfo",),
        ("freeDaq",),
        ("allocDaq", 1),
        ("allocOdt", 0, 1),
        ("allocOdtEntry", 0, 0, 2),
        ("setDaqPtr", 0, 0, 0),
        ("writeDaq", 0xFF, 2, 0, 0x1000),
        ("setDaqPtr", 0, 0, 1),
        ("writeDaq", 0xFF, 2, 0, 0x1002),
        ("setDaqListMode", 0x00, 0, 3, 1, 0),
        ("startStopDaqList", 0x02, 0),
        ("startStopSynch", 0x01),
    ]
    assert session.daq_map is not None
    assert session.daq_map.pid_to_odt == {0x40: (0, 0)}


def test_timestamp_mode_is_capability_driven() -> None:
    master = _Master()
    session = XcpDaqSession(master=master, ifdata=_ifdata(timestamp_size=2), measurements=_measurements())
    session.start(_selected())
    assert ("setDaqListMode", 0x10, 0, 3, 1, 0) in master.calls


def test_bad_first_pid_cleans_up_and_is_not_restart_poison() -> None:
    master = _Master(first_pid=0xFC)
    session = XcpDaqSession(master=master, ifdata=_ifdata(), measurements=_measurements())
    with pytest.raises(DaqAllocError, match="firstPid out of DTO range"):
        session.start(_selected())
    assert ("startStopSynch", 0x00) in master.calls
    assert ("disconnect",) in master.calls
