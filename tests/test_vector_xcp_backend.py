"""VectorXcpRecorderBackend tests with a mocked transport stack."""

from __future__ import annotations

import struct
import sys
import time
from unittest.mock import MagicMock, patch

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


def _patch_stack():
    return (
        patch.object(sys, "platform", "win32"),
        patch("mf4_analyzer.acquisition_capture.backends._import_can"),
        patch("mf4_analyzer.acquisition_capture.backends._import_xcp_master"),
    )


def test_lifecycle_on_mock_transport() -> None:
    from mf4_analyzer.acquisition_capture.backends import VectorXcpRecorderBackend

    platform_patch, can_patch, master_patch = _patch_stack()
    with platform_patch, can_patch as import_can, master_patch as import_master:
        mock_bus = MagicMock()
        import_can.return_value = MagicMock(Bus=lambda **_kwargs: mock_bus)
        mock_master = MagicMock()
        mock_master.connect.return_value = MagicMock(resource=0x00)
        mock_master.fetch.return_value = None
        import_master.return_value = lambda *_args, **_kwargs: mock_master

        backend = VectorXcpRecorderBackend(
            transport=TransportConfig(),
            ifdata=_ifdata(),
            measurements=_measurements(),
        )
        backend.start(_selected())
        assert mock_master.connect.called
        assert mock_master.startStopSynch.called

        final_status = backend.stop()

    mock_master.disconnect.assert_called()
    assert final_status.rx_count == 0
    assert final_status.bus_error_count == 0
    assert final_status.queue_overflow_count == 0
    assert final_status.last_error is None
    assert final_status.started is False


def test_status_shape_matches_capture_controller_summary_contract() -> None:
    from mf4_analyzer.acquisition_capture.backends import (
        BackendStatus,
        VectorXcpRecorderBackend,
    )

    platform_patch, can_patch, master_patch = _patch_stack()
    with platform_patch, can_patch as import_can, master_patch as import_master:
        import_can.return_value = MagicMock(Bus=lambda **_kwargs: MagicMock())
        import_master.return_value = lambda *_args, **_kwargs: MagicMock()
        backend = VectorXcpRecorderBackend(
            transport=TransportConfig(),
            ifdata=_ifdata(),
            measurements=_measurements(),
        )

    snap = backend.status()
    assert isinstance(snap, BackendStatus)
    assert isinstance(snap.queue_overflow_count, int)
    assert isinstance(snap.bus_error_count, int)
    assert snap.started is False


def test_capture_controller_round_trips_vector_backend_status(tmp_path) -> None:
    from mf4_analyzer.acquisition_capture.backends import VectorXcpRecorderBackend
    from mf4_analyzer.acquisition_capture.controller import CaptureController
    from mf4_analyzer.acquisition_capture.session import SessionConfig

    platform_patch, can_patch, master_patch = _patch_stack()
    with platform_patch, can_patch as import_can, master_patch as import_master:
        import_can.return_value = MagicMock(Bus=lambda **_kwargs: MagicMock())
        mock_master = MagicMock()
        mock_master.connect.return_value = MagicMock(resource=0x00)
        mock_master.fetch.return_value = None
        import_master.return_value = lambda *_args, **_kwargs: mock_master
        backend = VectorXcpRecorderBackend(
            transport=TransportConfig(),
            ifdata=_ifdata(),
            measurements=_measurements(),
        )
        config = SessionConfig(
            output_mf4=tmp_path / "out.mf4",
            selected=_selected(),
            backend="vector",
        )
        controller = CaptureController(config=config, backend=backend)

        controller.start()
        summary = controller.stop()

    assert summary is not None


def test_poll_returns_decoded_samples_from_dto_frames() -> None:
    from mf4_analyzer.acquisition_capture.backends import VectorXcpRecorderBackend

    dto_frame = bytes([0]) + struct.pack("<H", 0x1234)
    platform_patch, can_patch, master_patch = _patch_stack()
    with platform_patch, can_patch as import_can, master_patch as import_master:
        import_can.return_value = MagicMock(Bus=lambda **_kwargs: MagicMock())
        mock_master = MagicMock()
        mock_master.connect.return_value = MagicMock(resource=0x00)
        mock_master.fetch.side_effect = [dto_frame, None]
        import_master.return_value = lambda *_args, **_kwargs: mock_master
        backend = VectorXcpRecorderBackend(
            transport=TransportConfig(),
            ifdata=_ifdata(),
            measurements=_measurements(),
        )
        backend.start(_selected())
        time.sleep(0.05)

        samples = backend.poll()
        backend.stop()

    assert [sample[0] for sample in samples] == ["a"]
    assert samples[0][2] == float(0x1234)


def test_non_windows_raises_unavailable() -> None:
    from mf4_analyzer.acquisition_capture.backends import (
        RecorderBackendUnavailableError,
        VectorXcpRecorderBackend,
    )

    with patch.object(sys, "platform", "darwin"):
        with pytest.raises(RecorderBackendUnavailableError):
            VectorXcpRecorderBackend()
