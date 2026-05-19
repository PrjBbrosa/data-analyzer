"""T1-4: CLI ``--backend vector`` plumbing.

Mac-side coverage: argument parsing, A2L preconditions, fall-through
to :class:`RecorderBackendUnavailableError` on non-Windows. Real
hardware verification lives in the Stage-8 PR-4 runbook (Windows-only).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mf4_analyzer.acquisition_capture.__main__ import (
    _build_parser,
    _make_vector_backend,
)
from mf4_analyzer.acquisition_capture.backends import BackendStatus
from mf4_analyzer.acquisition_capture.session import SessionSummary


def test_parser_accepts_vector_choice_and_flags():
    parser = _build_parser()
    args = parser.parse_args(
        [
            "--backend", "vector",
            "--duration", "1",
            "--output", "/tmp/out.mf4",
            "--a2l", "/tmp/dummy.a2l",
            "--app-name", "Python",
            "--channel", "0",
            "--bitrate", "500000",
        ]
    )

    assert args.backend == "vector"
    assert str(args.a2l) == "/tmp/dummy.a2l"
    assert args.app_name == "Python"
    assert args.channel == 0
    assert args.bitrate == 500000
    assert args.can_fd is False


def _a2l_summary(*measurements):
    from can_logger.p0.a2l_probe import A2LSummary

    return A2LSummary(
        path="stub.a2l",
        total_measurements=len(measurements),
        measurements=list(measurements),
        event_capacity={event: 16 for m in measurements for event in m.available_events},
        measurement_events={m.name: m.available_events for m in measurements},
        a2l_has_daq_events=any(m.available_events for m in measurements),
    )


def _measurement(
    name: str,
    *,
    address: int = 0x40000000,
    datatype: str = "UWORD",
    events: tuple[str, ...] = ("evt",),
):
    from can_logger.p0.a2l_probe import MeasurementSummary

    return MeasurementSummary(
        name=name,
        address=address,
        datatype=datatype,
        unit="rpm",
        conversion="",
        available_events=events,
    )


def _ifdata(*event_names: str):
    from can_logger.p0.ifdata_xcp import DaqEventInfo, DaqProcessorInfo, IfDataXcp

    return IfDataXcp(
        cmd_id=0x6C7,
        resp_id=0x6C6,
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
        available_events=tuple(
            DaqEventInfo(
                number=i,
                name=name,
                cycle_time_ms=10.0,
                max_odt_entries=16,
                properties=("DAQ",),
            )
            for i, name in enumerate(event_names)
        ),
        daq_processor=DaqProcessorInfo(
            min_daq=0,
            max_event_channel=len(event_names),
            granularity_odt_entry_size_daq=1,
            overload_indication="NO_OVERLOAD_INDICATION",
        ),
    )


def _patch_vector_loaders(monkeypatch, *, summary, ifdata):
    from can_logger.p0 import a2l_probe as a2l_probe_module
    from can_logger.p0 import ifdata_xcp as ifdata_module

    monkeypatch.setattr(
        a2l_probe_module,
        "load_measurement_summary",
        lambda path, *, limit=None: summary,
    )
    monkeypatch.setattr(
        ifdata_module,
        "parse_ifdata_xcp_file",
        lambda path: (ifdata,),
    )


def test_main_binds_vector_selected_metadata_before_backend_start(
    tmp_path,
    monkeypatch,
):
    from mf4_analyzer.acquisition_capture import __main__ as cli_module
    from mf4_analyzer.acquisition_capture import backends as backends_module

    a2l_path = tmp_path / "stub.a2l"
    a2l_path.write_text("", encoding="utf-8")
    out_path = tmp_path / "out.mf4"
    captured = {}
    _patch_vector_loaders(
        monkeypatch,
        summary=_a2l_summary(
            _measurement(
                "sig",
                address=0x40000000,
                datatype="UWORD",
                events=("evt",),
            )
        ),
        ifdata=_ifdata("evt"),
    )

    class StubVectorBackend:
        def __init__(self, **_kwargs):
            pass

        def start(self, selected):
            captured["selected"] = tuple(selected)

        def stop(self):
            return BackendStatus(False, 0, 0, 0)

        def poll(self):
            return []

        def status(self):
            return BackendStatus(False, 0, 0, 0)

        def last_frame_monotonic(self):
            return None

    class StubController:
        running = False

        def __init__(self, config, backend):
            self.config = config
            self.backend = backend

        def start(self):
            self.backend.start(self.config.selected)

        def poll_step(self):
            return None

        def stop(self):
            return SessionSummary(output_mf4=str(self.config.output_mf4))

    monkeypatch.setattr(backends_module, "VectorXcpRecorderBackend", StubVectorBackend)
    monkeypatch.setattr(cli_module, "CaptureController", StubController)

    code = cli_module.main(
        [
            "--backend", "vector",
            "--duration", "1",
            "--output", str(out_path),
            "--a2l", str(a2l_path),
            "--signals", "sig",
        ]
    )

    assert code == 0
    selected = captured["selected"][0]
    assert selected.name == "sig"
    assert selected.event == "evt"
    assert selected.address_hex == "0x40000000"
    assert selected.payload_bytes == 2
    assert selected.event_rate_hz == 100.0


def test_make_vector_backend_requires_a2l(tmp_path):
    parser = _build_parser()
    args = parser.parse_args(
        [
            "--backend", "vector",
            "--duration", "1",
            "--output", str(tmp_path / "x.mf4"),
            # no --a2l
        ]
    )

    with pytest.raises(SystemExit, match="--a2l"):
        _make_vector_backend(args)


def test_make_vector_backend_rejects_missing_a2l_file(tmp_path):
    parser = _build_parser()
    args = parser.parse_args(
        [
            "--backend", "vector",
            "--duration", "1",
            "--output", str(tmp_path / "x.mf4"),
            "--a2l", str(tmp_path / "does-not-exist.a2l"),
        ]
    )

    with pytest.raises(SystemExit, match="not found"):
        _make_vector_backend(args)


def test_make_vector_backend_rejects_unknown_signal_before_backend_construction(
    tmp_path,
    monkeypatch,
):
    from mf4_analyzer.acquisition_capture import backends as backends_module

    a2l_path = tmp_path / "stub.a2l"
    a2l_path.write_text("", encoding="utf-8")
    _patch_vector_loaders(
        monkeypatch,
        summary=_a2l_summary(_measurement("sig")),
        ifdata=_ifdata("evt"),
    )
    monkeypatch.setattr(
        backends_module,
        "VectorXcpRecorderBackend",
        lambda **_kwargs: pytest.fail("backend should not be constructed"),
    )
    parser = _build_parser()
    args = parser.parse_args(
        [
            "--backend", "vector",
            "--duration", "1",
            "--output", str(tmp_path / "x.mf4"),
            "--a2l", str(a2l_path),
            "--signals", "missing",
        ]
    )

    with pytest.raises(SystemExit, match="signal 'missing' not found"):
        _make_vector_backend(args)


def test_make_vector_backend_rejects_signal_without_available_event(
    tmp_path,
    monkeypatch,
):
    from mf4_analyzer.acquisition_capture import backends as backends_module

    a2l_path = tmp_path / "stub.a2l"
    a2l_path.write_text("", encoding="utf-8")
    _patch_vector_loaders(
        monkeypatch,
        summary=_a2l_summary(_measurement("sig", events=())),
        ifdata=_ifdata("evt"),
    )
    monkeypatch.setattr(
        backends_module,
        "VectorXcpRecorderBackend",
        lambda **_kwargs: pytest.fail("backend should not be constructed"),
    )
    parser = _build_parser()
    args = parser.parse_args(
        [
            "--backend", "vector",
            "--duration", "1",
            "--output", str(tmp_path / "x.mf4"),
            "--a2l", str(a2l_path),
            "--signals", "sig",
        ]
    )

    with pytest.raises(SystemExit, match="signal 'sig' has no available DAQ event"):
        _make_vector_backend(args)


def test_make_vector_backend_rejects_event_missing_from_ifdata(
    tmp_path,
    monkeypatch,
):
    from mf4_analyzer.acquisition_capture import backends as backends_module

    a2l_path = tmp_path / "stub.a2l"
    a2l_path.write_text("", encoding="utf-8")
    _patch_vector_loaders(
        monkeypatch,
        summary=_a2l_summary(_measurement("sig", events=("summary_evt",))),
        ifdata=_ifdata("ifdata_evt"),
    )
    monkeypatch.setattr(
        backends_module,
        "VectorXcpRecorderBackend",
        lambda **_kwargs: pytest.fail("backend should not be constructed"),
    )
    parser = _build_parser()
    args = parser.parse_args(
        [
            "--backend", "vector",
            "--duration", "1",
            "--output", str(tmp_path / "x.mf4"),
            "--a2l", str(a2l_path),
            "--signals", "sig",
        ]
    )

    with pytest.raises(SystemExit, match="not in IF_DATA available_events"):
        _make_vector_backend(args)


def test_main_maps_unknown_vector_signal_to_exit_6(
    tmp_path,
    monkeypatch,
    capsys,
):
    from mf4_analyzer.acquisition_capture import __main__ as cli_module

    a2l_path = tmp_path / "stub.a2l"
    a2l_path.write_text("", encoding="utf-8")
    _patch_vector_loaders(
        monkeypatch,
        summary=_a2l_summary(_measurement("sig")),
        ifdata=_ifdata("evt"),
    )

    code = cli_module.main(
        [
            "--backend", "vector",
            "--duration", "1",
            "--output", str(tmp_path / "x.mf4"),
            "--a2l", str(a2l_path),
            "--signals", "missing",
        ]
    )

    assert code == 6
    assert "signal 'missing' not found" in capsys.readouterr().err


def test_make_vector_backend_raises_on_non_windows(tmp_path, monkeypatch):
    """On Mac/Linux, ``VectorXcpRecorderBackend.__init__`` short-circuits
    with :class:`RecorderBackendUnavailableError`. The CLI must map
    that to SystemExit(message) so ``main()`` can exit 6."""

    # Stub out heavy loaders so we exercise the construction path,
    # not the real A2L import.
    from mf4_analyzer.acquisition_capture import __main__ as cli_module
    from can_logger.p0 import a2l_probe as a2l_probe_module
    from can_logger.p0 import ifdata_xcp as ifdata_module
    from can_logger.p0.a2l_probe import A2LSummary, MeasurementSummary
    from can_logger.p0.ifdata_xcp import DaqEventInfo, DaqProcessorInfo, IfDataXcp

    a2l_path = tmp_path / "fake.a2l"
    a2l_path.write_text("")

    monkeypatch.setattr(
        a2l_probe_module,
        "load_measurement_summary",
        lambda path, *, limit=None: A2LSummary(
            path=str(path),
            total_measurements=1,
            measurements=[
                MeasurementSummary(
                    name="sig",
                    address=0x40000000,
                    datatype="UWORD",
                    unit="rpm",
                    conversion="",
                    available_events=("evt",),
                )
            ],
            event_capacity={"evt": 16},
            measurement_events={"sig": ("evt",)},
            a2l_has_daq_events=True,
        ),
    )
    monkeypatch.setattr(
        ifdata_module,
        "parse_ifdata_xcp_file",
        lambda path: (
            IfDataXcp(
                cmd_id=0x6C7,
                resp_id=0x6C6,
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
                        name="evt",
                        cycle_time_ms=10.0,
                        max_odt_entries=16,
                        properties=(),
                    ),
                ),
                daq_processor=DaqProcessorInfo(
                    min_daq=0,
                    max_event_channel=1,
                    granularity_odt_entry_size_daq=1,
                    overload_indication="NO_OVERLOAD_INDICATION",
                ),
            ),
        ),
    )

    parser = _build_parser()
    args = parser.parse_args(
        [
            "--backend", "vector",
            "--duration", "1",
            "--output", str(tmp_path / "out.mf4"),
            "--a2l", str(a2l_path),
            "--signals", "sig",
        ]
    )

    # On Mac the VectorXcpRecorderBackend constructor raises
    # RecorderBackendUnavailableError, which _make_vector_backend
    # wraps into SystemExit("vector backend unavailable: ...").
    with pytest.raises(SystemExit, match="vector backend unavailable"):
        _make_vector_backend(args)
