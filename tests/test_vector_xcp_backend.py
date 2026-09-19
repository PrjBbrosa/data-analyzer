"""Structured hardware-free tests for the pyxcp 0.29 Vector backend."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from can_logger.p0.a2l_probe import MeasurementSummary
from can_logger.p0.ifdata_xcp import DaqEventInfo, DaqProcessorInfo, IfDataXcp
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
from tests._helpers.acq_owned_objects import isolated_user_env, junit_case_results

_REPO_ROOT = Path(__file__).resolve().parents[1]
_THIS = Path(__file__).resolve()
_VECTOR_MINI_ENV = "T4_ACQ_VECTOR_MINI"


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


def _patch_runtime_sequence(
    monkeypatch,
    *masters: _StrictMaster,
) -> list[_Runtime]:
    from mf4_analyzer.acquisition_capture.pyxcp_runtime import PyXcpRuntime

    runtimes = [_Runtime(master) for master in masters]
    pending = iter(runtimes)
    monkeypatch.setattr(
        PyXcpRuntime,
        "open",
        lambda *_args, **_kwargs: next(pending),
    )
    return runtimes


def _stop_vector_backend(backend) -> None:
    try:
        backend.stop()
    except Exception:
        pass
    thread = getattr(backend, "_decode_thread", None)
    if thread is not None and thread.is_alive():
        stop_event = getattr(backend, "_stop_event", None)
        if stop_event is not None:
            stop_event.set()
        thread.join(timeout=2.0)


def _register_vector_finalizer(request, backend) -> None:
    request.addfinalizer(lambda: _stop_vector_backend(backend))


def _living_vector_decode_threads() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == "xcp-daq-decode" and thread.is_alive()
    ]


@pytest.mark.parametrize("platform_name", ("darwin", "linux"))
def test_vector_backend_is_refused_before_native_import_on_non_windows(
    monkeypatch, platform_name: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform_name)
    from mf4_analyzer.acquisition_capture.backends import (
        RecorderBackendUnavailableError,
        VectorXcpRecorderBackend,
    )

    with pytest.raises(RecorderBackendUnavailableError, match="Windows-only"):
        VectorXcpRecorderBackend()


@pytest.mark.parametrize(
    ("frozen", "expected_tail"),
    (
        (False, ("-c",)),
        (True, ("--pyxcp-import-probe-child",)),
    ),
)
def test_pyxcp_import_probe_selects_source_or_frozen_child_command(
    monkeypatch,
    frozen: bool,
    expected_tail: tuple[str, ...],
) -> None:
    from mf4_analyzer.acquisition_capture import backends

    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
    else:
        monkeypatch.delattr(sys, "frozen", raising=False)
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(backends.subprocess, "run", fake_run)

    command = backends._pyxcp_import_probe_command()
    assert command[0] == sys.executable
    assert tuple(command[1 : 1 + len(expected_tail)]) == expected_tail
    if not frozen:
        probe_code = command[2]
        assert probe_code.index("PyQt5.QtWidgets") < probe_code.index("pyxcp.master")
        assert "except" not in probe_code

    assert backends._run_pyxcp_import_probe() == (0, "", "")
    assert calls == [command]


def test_lifecycle_uses_one_runtime_and_policy_driven_dto_ingress(monkeypatch, request) -> None:
    from mf4_analyzer.acquisition_capture.backends import VectorXcpRecorderBackend

    master = _StrictMaster()
    runtime = _patch_runtime(monkeypatch, master)
    monkeypatch.setattr(sys, "platform", "win32")
    backend = VectorXcpRecorderBackend(transport=TransportConfig(), ifdata=_ifdata(), measurements=_measurements())
    _register_vector_finalizer(request, backend)
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


def test_failed_daq_start_closes_runtime(monkeypatch, request) -> None:
    from mf4_analyzer.acquisition_capture.backends import RecorderStartError, VectorXcpRecorderBackend
    from mf4_analyzer.acquisition_capture.xcp_daq_session import XcpDaqSession

    master = _StrictMaster()
    runtime = _patch_runtime(monkeypatch, master)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(XcpDaqSession, "start", lambda *_args: (_ for _ in ()).throw(RuntimeError("DAQ rejected")))
    backend = VectorXcpRecorderBackend(transport=TransportConfig(), ifdata=_ifdata(), measurements=_measurements())
    _register_vector_finalizer(request, backend)
    with pytest.raises(RecorderStartError, match="DAQ rejected"):
        backend.start(_selected())
    assert runtime.closed is True


def test_fake_backend_does_not_expose_vector_diagnostics() -> None:
    from mf4_analyzer.acquisition_capture.backends import FakeRecorderBackend

    assert not hasattr(FakeRecorderBackend(), "diagnostics")


def test_vector_diagnostics_classify_bad_dto_and_continue(monkeypatch, request) -> None:
    from mf4_analyzer.acquisition_capture.backends import VectorXcpRecorderBackend

    master = _StrictMaster()
    _patch_runtime(monkeypatch, master)
    monkeypatch.setattr(sys, "platform", "win32")
    backend = VectorXcpRecorderBackend(
        transport=TransportConfig(),
        ifdata=_ifdata(),
        measurements=_measurements(),
    )
    _register_vector_finalizer(request, backend)
    backend.start(_selected())

    backend._policy.feed("DAQ", 1, 0, bytes([0x99, 0x00, 0x00]))
    backend._policy.feed("DAQ", 2, 0, bytes([0x10]))
    backend._policy.feed("DAQ", 3, 0, bytes([0x10, 0x34, 0x12]))

    deadline = time.monotonic() + 1.0
    diagnostics = backend.diagnostics()
    while time.monotonic() < deadline and not (
        diagnostics["samples_emitted_count"] == 1
        and diagnostics["unknown_pid_count"] == 1
        and diagnostics["decode_error_count"] == 1
    ):
        time.sleep(0.01)
        diagnostics = backend.diagnostics()

    samples = backend.poll()
    diagnostics = backend.diagnostics()
    assert len(samples) == 1
    assert samples[0][0] == "a"
    assert samples[0][2] == float(0x1234)
    assert diagnostics["dto_received_count"] == 3
    assert diagnostics["samples_emitted_count"] == 1
    assert diagnostics["unknown_pid_count"] == 1
    assert diagnostics["decode_error_count"] == 1
    assert diagnostics["frame_queue_high_water"] >= 1
    assert diagnostics["frame_overflow_count"] == 0
    assert diagnostics["sample_queue_high_water"] >= 1
    assert diagnostics["sample_overflow_count"] == 0
    assert diagnostics["bus_error_count"] == 0
    assert diagnostics["bus_error_observable"] is False
    assert diagnostics["bus_state"] is None
    assert diagnostics["policy_error_count"] == 0
    assert diagnostics["last_error"] is not None

    backend.stop()


def test_vector_diagnostics_report_sample_queue_overflow(monkeypatch, request) -> None:
    from mf4_analyzer.acquisition_capture.backends import VectorXcpRecorderBackend

    master = _StrictMaster()
    _patch_runtime(monkeypatch, master)
    monkeypatch.setattr(sys, "platform", "win32")
    backend = VectorXcpRecorderBackend(
        transport=TransportConfig(),
        ifdata=_ifdata(),
        measurements=_measurements(),
    )
    _register_vector_finalizer(request, backend)
    backend._sample_queue = queue.Queue(maxsize=1)
    backend.start(_selected())

    backend._policy.feed("DAQ", 1, 0, bytes([0x10, 0x01, 0x00]))
    backend._policy.feed("DAQ", 2, 0, bytes([0x10, 0x02, 0x00]))
    deadline = time.monotonic() + 1.0
    diagnostics = backend.diagnostics()
    while time.monotonic() < deadline and diagnostics["sample_overflow_count"] < 1:
        time.sleep(0.01)
        diagnostics = backend.diagnostics()

    assert diagnostics["samples_emitted_count"] == 1
    assert diagnostics["sample_queue_depth"] == 1
    assert diagnostics["sample_queue_high_water"] == 1
    assert diagnostics["sample_overflow_count"] == 1
    assert backend.status().queue_overflow_count == 1

    backend.stop()


def test_vector_diagnostics_report_policy_error_and_recover(monkeypatch, request) -> None:
    from mf4_analyzer.acquisition_capture.backends import VectorXcpRecorderBackend

    master = _StrictMaster()
    _patch_runtime(monkeypatch, master)
    monkeypatch.setattr(sys, "platform", "win32")
    backend = VectorXcpRecorderBackend(
        transport=TransportConfig(),
        ifdata=_ifdata(),
        measurements=_measurements(),
    )
    _register_vector_finalizer(request, backend)
    backend.start(_selected())

    original_get = backend._policy.get
    raised = False

    def flaky_get(*args, **kwargs):
        nonlocal raised
        if not raised:
            raised = True
            raise RuntimeError("policy read failed")
        return original_get(*args, **kwargs)

    monkeypatch.setattr(backend._policy, "get", flaky_get)
    backend._policy.feed("DAQ", 1, 0, bytes([0x10, 0x34, 0x12]))

    deadline = time.monotonic() + 1.0
    diagnostics = backend.diagnostics()
    while time.monotonic() < deadline and not (
        diagnostics["policy_error_count"] == 1
        and diagnostics["samples_emitted_count"] == 1
    ):
        time.sleep(0.01)
        diagnostics = backend.diagnostics()

    assert diagnostics["bus_error_count"] == 0
    assert diagnostics["policy_error_count"] == 1
    assert diagnostics["last_error"] == "policy read failed"
    assert backend.status().bus_error_count == 0
    assert backend.poll()[0][2] == float(0x1234)

    backend.stop()


def test_backend_status_overflow_is_frame_plus_sample_without_double_count(
    monkeypatch,
    request,
) -> None:
    from mf4_analyzer.acquisition_capture.backends import VectorXcpRecorderBackend
    from mf4_analyzer.acquisition_capture.pyxcp_daq_policy import BoundedDaqPolicy

    master = _StrictMaster()
    _patch_runtime(monkeypatch, master)
    monkeypatch.setattr(sys, "platform", "win32")
    backend = VectorXcpRecorderBackend(
        transport=TransportConfig(),
        ifdata=_ifdata(),
        measurements=_measurements(),
    )
    _register_vector_finalizer(request, backend)
    backend.start(_selected())
    backend._stop_event.set()
    backend._decode_thread.join(timeout=1.0)
    backend._policy = BoundedDaqPolicy(frame_capacity=1)
    backend._policy.feed("DAQ", 1, 0, b"first")
    backend._policy.feed("DAQ", 2, 0, b"second")
    with backend._diagnostics_lock:
        backend._queue_overflow_count = 2

    diagnostics = backend.diagnostics()
    assert diagnostics["frame_overflow_count"] == 1
    assert diagnostics["sample_overflow_count"] == 2
    assert backend.status().queue_overflow_count == 3

    backend.stop()


def test_unknown_pid_updates_dto_arrival_but_not_last_sample(monkeypatch, request) -> None:
    from mf4_analyzer.acquisition_capture.backends import VectorXcpRecorderBackend

    master = _StrictMaster()
    _patch_runtime(monkeypatch, master)
    monkeypatch.setattr(sys, "platform", "win32")
    backend = VectorXcpRecorderBackend(
        transport=TransportConfig(),
        ifdata=_ifdata(),
        measurements=_measurements(),
    )
    _register_vector_finalizer(request, backend)
    backend.start(_selected())
    backend._policy.feed("DAQ", 1, 0, bytes([0x99, 0x00, 0x00]))

    deadline = time.monotonic() + 1.0
    diagnostics = backend.diagnostics()
    while time.monotonic() < deadline and diagnostics["unknown_pid_count"] < 1:
        time.sleep(0.01)
        diagnostics = backend.diagnostics()

    assert backend.last_frame_monotonic() is None
    assert diagnostics["last_frame_monotonic_s"] is None
    assert diagnostics["last_dto_monotonic_s"] is not None

    backend.stop()


def test_repeated_start_releases_old_session_and_resets_capture_state(
    monkeypatch,
    request,
) -> None:
    from mf4_analyzer.acquisition_capture.backends import VectorXcpRecorderBackend

    first_master = _StrictMaster()
    second_master = _StrictMaster()
    first_runtime, second_runtime = _patch_runtime_sequence(
        monkeypatch,
        first_master,
        second_master,
    )
    monkeypatch.setattr(sys, "platform", "win32")
    backend = VectorXcpRecorderBackend(
        transport=TransportConfig(),
        ifdata=_ifdata(),
        measurements=_measurements(),
    )
    _register_vector_finalizer(request, backend)
    capacity = backend._sample_queue.maxsize
    backend.start(_selected())
    old_session = backend._session
    old_policy = backend._policy
    old_thread = backend._decode_thread
    backend._policy.feed("DAQ", 1, 0, bytes([0x10, 0x34, 0x12]))
    backend._policy.feed("DAQ", 2, 0, bytes([0x99, 0x00, 0x00]))
    deadline = time.monotonic() + 1.0
    diagnostics = backend.diagnostics()
    while time.monotonic() < deadline and not (
        diagnostics["samples_emitted_count"] == 1
        and diagnostics["unknown_pid_count"] == 1
    ):
        time.sleep(0.01)
        diagnostics = backend.diagnostics()
    with backend._diagnostics_lock:
        backend._policy_error_count = 2
        backend._decode_error_count = 3
        backend._queue_overflow_count = 4

    backend.start(_selected())

    assert first_runtime.closed is True
    assert second_runtime.closed is False
    assert old_session.is_running() is False
    assert old_thread.is_alive() is False
    assert backend._policy is not old_policy
    assert backend._sample_queue.maxsize == capacity
    diagnostics = backend.diagnostics()
    assert diagnostics["dto_received_count"] == 0
    assert diagnostics["samples_emitted_count"] == 0
    assert diagnostics["sample_queue_depth"] == 0
    assert diagnostics["sample_queue_high_water"] == 0
    assert diagnostics["sample_overflow_count"] == 0
    assert diagnostics["frame_queue_high_water"] == 0
    assert diagnostics["frame_overflow_count"] == 0
    assert diagnostics["unknown_pid_count"] == 0
    assert diagnostics["decode_error_count"] == 0
    assert diagnostics["policy_error_count"] == 0
    assert diagnostics["last_error"] is None
    assert backend.last_frame_monotonic() is None

    backend._policy.feed("DAQ", 3, 0, bytes([0x10, 0x78, 0x56]))
    deadline = time.monotonic() + 1.0
    samples = []
    while time.monotonic() < deadline and not samples:
        samples = backend.poll()
        time.sleep(0.01)
    assert samples and samples[0][2] == float(0x5678)

    first_stop = backend.stop()
    second_stop = backend.stop()
    assert first_stop.started is False
    assert second_stop.started is False
    assert second_runtime.closed is True


def test_failed_start_can_retry_without_inheriting_error_or_queue_state(
    monkeypatch,
    request,
) -> None:
    from mf4_analyzer.acquisition_capture.backends import (
        RecorderStartError,
        VectorXcpRecorderBackend,
    )
    from mf4_analyzer.acquisition_capture.xcp_daq_session import XcpDaqSession

    first_master = _StrictMaster()
    second_master = _StrictMaster()
    first_runtime, second_runtime = _patch_runtime_sequence(
        monkeypatch,
        first_master,
        second_master,
    )
    original_start = XcpDaqSession.start
    call_count = 0

    def fail_once(session, selected):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("DAQ rejected once")
        return original_start(session, selected)

    monkeypatch.setattr(XcpDaqSession, "start", fail_once)
    monkeypatch.setattr(sys, "platform", "win32")
    backend = VectorXcpRecorderBackend(
        transport=TransportConfig(),
        ifdata=_ifdata(),
        measurements=_measurements(),
    )
    _register_vector_finalizer(request, backend)

    with pytest.raises(RecorderStartError, match="DAQ rejected once"):
        backend.start(_selected())
    assert first_runtime.closed is True
    assert "DAQ rejected once" in (backend.status().last_error or "")

    backend.start(_selected())
    diagnostics = backend.diagnostics()
    assert diagnostics["last_error"] is None
    assert diagnostics["dto_received_count"] == 0
    assert diagnostics["samples_emitted_count"] == 0
    assert diagnostics["sample_queue_depth"] == 0
    backend._policy.feed("DAQ", 1, 0, bytes([0x10, 0x34, 0x12]))
    deadline = time.monotonic() + 1.0
    samples = []
    while time.monotonic() < deadline and not samples:
        samples = backend.poll()
        time.sleep(0.01)
    assert samples and samples[0][2] == float(0x1234)
    assert second_runtime.closed is False

    backend.stop()


@pytest.mark.skipif(
    os.environ.get(_VECTOR_MINI_ENV) != "child",
    reason="forced-failure child for the Vector teardown mini suite",
)
def test_vector_mini_forced_assert_failure(monkeypatch, request) -> None:
    from mf4_analyzer.acquisition_capture.backends import VectorXcpRecorderBackend

    master = _StrictMaster()
    runtime = _patch_runtime(monkeypatch, master)
    monkeypatch.setattr(sys, "platform", "win32")
    backend = VectorXcpRecorderBackend(
        transport=TransportConfig(),
        ifdata=_ifdata(),
        measurements=_measurements(),
    )
    _register_vector_finalizer(request, backend)
    backend.start(_selected())
    assert runtime.closed is False
    assert False, "forced vector start assertion"


@pytest.mark.skipif(
    os.environ.get(_VECTOR_MINI_ENV) != "child",
    reason="following child node for the Vector teardown mini suite",
)
def test_vector_mini_following_node_has_no_decode_thread() -> None:
    assert _living_vector_decode_threads() == []


def test_vector_assert_failure_teardown_mini_suite(tmp_path) -> None:
    junit = tmp_path / "vector-mini.xml"
    env = isolated_user_env(tmp_path / "home")
    env[_VECTOR_MINI_ENV] = "child"
    env["PYTHONPATH"] = str(_REPO_ROOT)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            f"{_THIS}::test_vector_mini_forced_assert_failure",
            f"{_THIS}::test_vector_mini_following_node_has_no_decode_thread",
            "-q",
            f"--junitxml={junit}",
            f"--basetemp={tmp_path / 'basetemp'}",
        ],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert junit.exists(), (
        f"vector mini suite produced no junit\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    cases = junit_case_results(junit)
    assert cases.get("test_vector_mini_forced_assert_failure") == "failed", (
        f"forced assert must fail: {cases}\n{result.stdout}\n{result.stderr}"
    )
    assert cases.get("test_vector_mini_following_node_has_no_decode_thread") == (
        "passed"
    ), (
        f"following node saw leftover decode thread: {cases}\n"
        f"{result.stdout}\n{result.stderr}"
    )
