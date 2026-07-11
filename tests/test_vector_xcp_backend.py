"""Structured hardware-free tests for the pyxcp 0.29 Vector backend."""

from __future__ import annotations

import sys
import time
from types import SimpleNamespace

import pytest

from can_logger.p0.a2l_probe import MeasurementSummary
from can_logger.p0.ifdata_xcp import DaqEventInfo, DaqProcessorInfo, IfDataXcp
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig


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
        available_events=(DaqEventInfo(0, "10ms", 10.0, 8, ("DAQ",)),),
        daq_processor=DaqProcessorInfo(0, 1, 1, "EVENT"),
    )


def _selected() -> tuple[SelectedMeasurement, ...]:
    return (SelectedMeasurement("a", event="10ms", payload_bytes=2, address_hex="0x1000"),)


def _measurements() -> dict[str, MeasurementSummary]:
    return {"a": MeasurementSummary("a", 0x1000, "UWORD", "", "")}


class _StrictMaster:
    """Deliberately narrow fake: unknown pyxcp API calls fail naturally."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def connect(self):
        self.calls.append(("connect",))
        return SimpleNamespace(resource=0)

    def getStatus(self):  # noqa: N802 - pinned pyxcp spelling
        self.calls.append(("getStatus",))
        return SimpleNamespace(resourceProtectionStatus=SimpleNamespace(daq=False))

    def getDaqProcessorInfo(self):  # noqa: N802
        self.calls.append(("getDaqProcessorInfo",))
        return SimpleNamespace(maxDaq=8)

    def freeDaq(self):  # noqa: N802
        self.calls.append(("freeDaq",))

    def allocDaq(self, count):  # noqa: N802
        self.calls.append(("allocDaq", count))

    def allocOdt(self, daq_list, count):  # noqa: N802
        self.calls.append(("allocOdt", daq_list, count))

    def allocOdtEntry(self, daq_list, odt, count):  # noqa: N802
        self.calls.append(("allocOdtEntry", daq_list, odt, count))

    def setDaqPtr(self, daq_list, odt, index):  # noqa: N802
        self.calls.append(("setDaqPtr", daq_list, odt, index))

    def writeDaq(self, bit_offset, size, extension, address):  # noqa: N802
        self.calls.append(("writeDaq", bit_offset, size, extension, address))

    def setDaqListMode(self, mode, daq_list, event, prescaler, priority):  # noqa: N802
        self.calls.append(("setDaqListMode", mode, daq_list, event, prescaler, priority))

    def startStopDaqList(self, mode, daq_list):  # noqa: N802
        self.calls.append(("startStopDaqList", mode, daq_list))
        return SimpleNamespace(firstPid=0x10)

    def startStopSynch(self, mode):  # noqa: N802
        self.calls.append(("startStopSynch", mode))

    def disconnect(self):
        self.calls.append(("disconnect",))


class _Runtime:
    def __init__(self, master: _StrictMaster) -> None:
        self.master = master
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _patch_runtime(monkeypatch, master: _StrictMaster) -> _Runtime:
    from mf4_analyzer.acquisition_capture.pyxcp_runtime import PyXcpRuntime

    runtime = _Runtime(master)
    monkeypatch.setattr(PyXcpRuntime, "open", lambda *_args, **_kwargs: runtime)
    return runtime


def test_vector_backend_is_refused_before_native_import_on_non_windows() -> None:
    from mf4_analyzer.acquisition_capture.backends import (
        RecorderBackendUnavailableError,
        VectorXcpRecorderBackend,
    )

    with pytest.raises(RecorderBackendUnavailableError):
        VectorXcpRecorderBackend()


def test_lifecycle_uses_one_runtime_and_policy_driven_dto_ingress(monkeypatch) -> None:
    from mf4_analyzer.acquisition_capture.backends import VectorXcpRecorderBackend

    master = _StrictMaster()
    runtime = _patch_runtime(monkeypatch, master)
    monkeypatch.setattr(sys, "platform", "win32")
    backend = VectorXcpRecorderBackend(transport=TransportConfig(), ifdata=_ifdata(), measurements=_measurements())
    backend.start(_selected())

    assert ("allocDaq", 1) in master.calls
    assert ("startStopDaqList", 0x02, 0) in master.calls
    assert ("startStopSynch", 0x01) in master.calls
    backend._policy.feed("DAQ", 1, 0, bytes([0x10, 0x34, 0x12]))
    deadline = time.monotonic() + 1.0
    samples = []
    while time.monotonic() < deadline and not samples:
        samples = backend.poll()
        time.sleep(0.01)
    assert samples and samples[0][0] == "a" and samples[0][2] == float(0x1234)

    status = backend.stop()
    assert status.started is False
    assert runtime.closed is True
    assert ("startStopSynch", 0x00) in master.calls
    assert master.calls.count(("disconnect",)) >= 1


def test_failed_daq_start_closes_runtime(monkeypatch) -> None:
    from mf4_analyzer.acquisition_capture.backends import RecorderStartError, VectorXcpRecorderBackend
    from mf4_analyzer.acquisition_capture.xcp_daq_session import XcpDaqSession

    master = _StrictMaster()
    runtime = _patch_runtime(monkeypatch, master)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(XcpDaqSession, "start", lambda *_args: (_ for _ in ()).throw(RuntimeError("DAQ rejected")))
    backend = VectorXcpRecorderBackend(transport=TransportConfig(), ifdata=_ifdata(), measurements=_measurements())
    with pytest.raises(RecorderStartError, match="DAQ rejected"):
        backend.start(_selected())
    assert runtime.closed is True
