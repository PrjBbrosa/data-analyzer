"""Task 0 red contracts for the pyxcp 0.29 readiness correction.

These tests deliberately describe the approved July 11 contract before the
production implementation exists.  Their initial failures are recorded in the
Task 0 evidence; subsequent tasks make them green without compatibility
guesswork.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from can_logger.p0.ifdata_xcp import DaqEventInfo, DaqProcessorInfo, IfDataXcp
from can_logger.p0.a2l_probe import MeasurementSummary
from mf4_analyzer.acquisition_capture.daq_map import build_daq_map
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement


ROOT = Path(__file__).resolve().parents[1]


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
        daq_timestamp_size=0,
        daq_timestamp_unit="1US",
        daq_timestamp_fixed=False,
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


def test_production_source_has_no_dictionary_master_or_dto_fetch_fallback() -> None:
    """Task 2/5: pyxcp owns transport and policy owns DAQ ingress."""

    production = (ROOT / "mf4_analyzer/acquisition_capture/backends.py").read_text(
        encoding="utf-8"
    )
    probe = (ROOT / "mf4_analyzer/acquisition_capture/vector_hw_probe.py").read_text(
        encoding="utf-8"
    )
    assert 'config={"bus":' not in production
    assert 'config={"bus":' not in probe
    assert "master.fetch" not in production
    assert "transport.fetch" not in production


def test_daq_layout_is_pid_unbound_until_ecu_select_returns_first_pid() -> None:
    """Task 4: local packing must not invent ECU PIDs starting at zero."""

    layout = build_daq_map(
        (SelectedMeasurement("signal", event="10ms", payload_bytes=2),),
        _ifdata(),
        {
            "signal": MeasurementSummary(
                name="signal", address=0x1000, datatype="UWORD", unit="", conversion=""
            )
        },
    )
    assert layout.pid_to_odt == {}


def test_daq_protection_comes_from_status_not_connect_resource() -> None:
    """Task 3: RESOURCE availability cannot be interpreted as a lock bit."""

    from mf4_analyzer.acquisition_capture.xcp_auth import unlock_resources_if_needed

    class StatusMaster:
        def __init__(self) -> None:
            self.status_calls = 0

        def getStatus(self):  # noqa: N802 - pinned pyxcp spelling
            self.status_calls += 1
            return SimpleNamespace(protection_status=0)

    master = StatusMaster()
    unlock_resources_if_needed(
        master=master,
        connect_response=SimpleNamespace(resource=0xFF),
        seed_and_key_dll=None,
    )
    assert master.status_calls == 1


def test_capture_controller_exposes_attached_recording_start() -> None:
    """Task 7: recording attaches to a connected stream without restart."""

    from mf4_analyzer.acquisition_capture.controller import CaptureController

    assert callable(getattr(CaptureController, "start_attached", None))
