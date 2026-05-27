"""XcpDaqSession orchestration tests with mocked pyxcp master."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from can_logger.p0.a2l_probe import MeasurementSummary
from can_logger.p0.ifdata_xcp import DaqEventInfo, DaqProcessorInfo, IfDataXcp
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement


def _ifdata() -> IfDataXcp:
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
        daq_timestamp_size=2,
        daq_timestamp_unit="1US",
        daq_timestamp_fixed=True,
        available_events=(
            DaqEventInfo(
                number=0,
                name="10ms",
                cycle_time_ms=10.0,
                max_odt_entries=8,
                properties=("DAQ",),
            ),
        ),
        daq_processor=DaqProcessorInfo(
            min_daq=0,
            max_event_channel=1,
            granularity_odt_entry_size_daq=1,
            overload_indication="EVENT",
        ),
    )


def _selected() -> tuple[SelectedMeasurement, ...]:
    return (
        SelectedMeasurement(
            name="a",
            address_hex="0x1000",
            event="10ms",
            event_rate_hz=100.0,
            payload_bytes=2,
        ),
    )


def _measurements() -> dict[str, MeasurementSummary]:
    return {
        "a": MeasurementSummary(
            name="a",
            address=0x1000,
            datatype="UWORD",
            unit="",
            conversion="",
            available_events=("10ms",),
        ),
    }


def _mock_master() -> MagicMock:
    master = MagicMock()
    master.connect.return_value = MagicMock(resource=0x00)
    master.getDaqProcessorInfo.return_value = MagicMock(maxDaq=4)
    return master


def test_start_issues_expected_command_sequence() -> None:
    from mf4_analyzer.acquisition_capture.xcp_daq_session import XcpDaqSession

    master = _mock_master()
    session = XcpDaqSession(
        master=master,
        ifdata=_ifdata(),
        measurements=_measurements(),
    )

    session.start(_selected())

    assert master.connect.called
    assert master.getDaqProcessorInfo.called
    assert master.allocDaq.called
    assert master.allocOdt.called
    assert master.allocOdtEntry.called
    assert master.writeDaq.called
    assert master.setDaqListMode.called
    master.startStopSynch.assert_called_with(0x01)
    assert session.daq_map is not None


def test_stop_disconnects() -> None:
    from mf4_analyzer.acquisition_capture.xcp_daq_session import XcpDaqSession

    master = _mock_master()
    session = XcpDaqSession(
        master=master,
        ifdata=_ifdata(),
        measurements=_measurements(),
    )
    session.start(_selected())

    session.stop()

    master.startStopSynch.assert_called_with(0x00)
    assert master.disconnect.called
    assert session.is_running() is False


def test_start_raises_on_master_connect_failure() -> None:
    from mf4_analyzer.acquisition_capture.xcp_daq_session import (
        XcpConnectError,
        XcpDaqSession,
    )

    master = _mock_master()
    master.connect.side_effect = RuntimeError("no slave response")
    session = XcpDaqSession(
        master=master,
        ifdata=_ifdata(),
        measurements=_measurements(),
    )

    with pytest.raises(XcpConnectError, match="CONNECT failed"):
        session.start(_selected())


def test_start_raises_when_get_daq_processor_info_fails() -> None:
    from mf4_analyzer.acquisition_capture.xcp_daq_session import (
        DaqAllocError,
        XcpDaqSession,
    )

    master = _mock_master()
    master.getDaqProcessorInfo.side_effect = RuntimeError("CMD rejected")
    session = XcpDaqSession(
        master=master,
        ifdata=_ifdata(),
        measurements=_measurements(),
    )

    with pytest.raises(DaqAllocError, match="getDaqProcessorInfo failed"):
        session.start(_selected())


def test_start_raises_when_ecu_max_daq_lower_than_a2l_min_daq() -> None:
    from mf4_analyzer.acquisition_capture.xcp_daq_session import (
        DaqAllocError,
        XcpDaqSession,
    )

    ifdata = IfDataXcp(
        cmd_id=0x500,
        resp_id=0x501,
        cmd_id_extended=False,
        resp_id_extended=False,
        can_fd=False,
        max_cto=8,
        max_dto=8,
        byte_order="MSB_LAST",
        address_granularity="BYTE",
        daq_timestamp_size=2,
        daq_timestamp_unit="1US",
        daq_timestamp_fixed=True,
        available_events=(
            DaqEventInfo(
                number=0,
                name="10ms",
                cycle_time_ms=10.0,
                max_odt_entries=8,
                properties=("DAQ",),
            ),
        ),
        daq_processor=DaqProcessorInfo(
            min_daq=4,
            max_event_channel=1,
            granularity_odt_entry_size_daq=1,
            overload_indication="EVENT",
        ),
    )
    master = _mock_master()
    master.getDaqProcessorInfo.return_value = MagicMock(maxDaq=1)
    session = XcpDaqSession(
        master=master,
        ifdata=ifdata,
        measurements=_measurements(),
    )

    with pytest.raises(DaqAllocError, match="max_daq=1"):
        session.start(_selected())


def test_seed_and_key_dll_forwarded_through_init_kwarg() -> None:
    from mf4_analyzer.acquisition_capture.xcp_daq_session import XcpDaqSession

    master = _mock_master()
    master.connect.return_value = MagicMock(resource=0x04)
    session = XcpDaqSession(
        master=master,
        ifdata=_ifdata(),
        measurements=_measurements(),
        seed_and_key_dll=None,
    )

    # RESOURCE.DAQ is locked (bit2) and no DLL configured -> XcpAuthError
    from mf4_analyzer.acquisition_capture.xcp_auth import XcpAuthError

    with pytest.raises(XcpAuthError, match="seed&key DLL"):
        session.start(_selected())
