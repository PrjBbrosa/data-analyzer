import sys
import time
from unittest.mock import MagicMock, patch

from mf4_analyzer.acquisition_capture.transport_config import TransportConfig


def _ifdata():
    from can_logger.p0.ifdata_xcp import IfDataXcp, DaqProcessorInfo

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
        available_events=(),
        daq_processor=DaqProcessorInfo(
            min_daq=0,
            max_event_channel=0,
            granularity_odt_entry_size_daq=1,
            overload_indication="EVENT",
        ),
    )


def test_probe_returns_red_on_non_windows():
    from mf4_analyzer.acquisition_capture.health import level_hw
    from mf4_analyzer.acquisition_capture.vector_hw_probe import vector_hw_probe

    with patch.object(sys, "platform", "darwin"):
        result = vector_hw_probe(TransportConfig())

    assert result.ok is False
    assert "Windows" in (result.error or "")
    assert isinstance(result.channel_count, int)
    assert isinstance(result.last_probe_ts, float)
    assert level_hw(result) == "red"


def test_probe_returns_green_on_windows_when_app_known():
    from mf4_analyzer.acquisition_capture.vector_hw_probe import vector_hw_probe

    fake_canlib = MagicMock()
    fake_canlib.get_application_config.return_value = MagicMock(
        hw_type="VN1640",
        channel=0,
        driver_version="22.0",
    )
    fake_canlib.get_channel_count.return_value = 4

    with patch.object(sys, "platform", "win32"), patch(
        "mf4_analyzer.acquisition_capture.vector_hw_probe._load_vector_canlib",
        return_value=fake_canlib,
    ):
        result = vector_hw_probe(TransportConfig(app_name="Python", channel=0))

    assert result.ok is True
    assert result.error is None
    assert result.channel_count == 4
    assert result.driver_version == "22.0"


def test_probe_reports_missing_app():
    from mf4_analyzer.acquisition_capture.vector_hw_probe import vector_hw_probe

    fake_canlib = MagicMock()
    fake_canlib.get_application_config.side_effect = LookupError(
        "application 'Python' not found"
    )

    with patch.object(sys, "platform", "win32"), patch(
        "mf4_analyzer.acquisition_capture.vector_hw_probe._load_vector_canlib",
        return_value=fake_canlib,
    ):
        result = vector_hw_probe(TransportConfig(app_name="Python", channel=0))

    assert result.ok is False
    assert "Python" in (result.error or "")
    assert isinstance(result.channel_count, int)
    assert isinstance(result.last_probe_ts, float)


def test_test_xcp_connection_returns_resource_byte_on_success():
    from mf4_analyzer.acquisition_capture.vector_hw_probe import test_xcp_connection

    mock_master = MagicMock()
    mock_master.connect.return_value = MagicMock(resource=0x05)
    mock_bus = MagicMock()
    with patch.object(sys, "platform", "win32"), patch(
        "mf4_analyzer.acquisition_capture.vector_hw_probe._open_vector_bus",
        return_value=mock_bus,
    ), patch(
        "mf4_analyzer.acquisition_capture.vector_hw_probe._make_pyxcp_master",
        return_value=mock_master,
    ):
        result = test_xcp_connection(TransportConfig(), _ifdata())

    assert result.ok is True
    assert result.resource_byte == 0x05
    assert result.latency_ms is not None
    mock_master.connect.assert_called_once()
    mock_master.disconnect.assert_called_once()
    mock_bus.shutdown.assert_called_once()


def test_test_xcp_connection_reports_no_response_on_timeout():
    from mf4_analyzer.acquisition_capture.vector_hw_probe import test_xcp_connection

    mock_master = MagicMock()
    mock_master.connect.side_effect = TimeoutError("no response")
    mock_bus = MagicMock()
    with patch.object(sys, "platform", "win32"), patch(
        "mf4_analyzer.acquisition_capture.vector_hw_probe._open_vector_bus",
        return_value=mock_bus,
    ), patch(
        "mf4_analyzer.acquisition_capture.vector_hw_probe._make_pyxcp_master",
        return_value=mock_master,
    ):
        result = test_xcp_connection(TransportConfig(), _ifdata())

    assert result.ok is False
    assert "0x500" in (result.error or "")
    mock_bus.shutdown.assert_called_once()


def test_test_xcp_connection_reports_master_creation_failure():
    from mf4_analyzer.acquisition_capture.vector_hw_probe import test_xcp_connection

    mock_bus = MagicMock()
    with patch.object(sys, "platform", "win32"), patch(
        "mf4_analyzer.acquisition_capture.vector_hw_probe._open_vector_bus",
        return_value=mock_bus,
    ), patch(
        "mf4_analyzer.acquisition_capture.vector_hw_probe._make_pyxcp_master",
        side_effect=RuntimeError("pyxcp import failed"),
    ):
        result = test_xcp_connection(TransportConfig(), _ifdata())

    assert result.ok is False
    assert "pyxcp" in (result.error or "").lower()
    mock_bus.shutdown.assert_called_once()


def test_test_xcp_connection_bus_open_failure_reports_red():
    from mf4_analyzer.acquisition_capture.vector_hw_probe import test_xcp_connection

    with patch.object(sys, "platform", "win32"), patch(
        "mf4_analyzer.acquisition_capture.vector_hw_probe._open_vector_bus",
        side_effect=RuntimeError("vxlapi: channel busy"),
    ):
        result = test_xcp_connection(TransportConfig(), _ifdata())

    assert result.ok is False
    assert "总线" in (result.error or "") or "bus" in (result.error or "").lower()


def test_test_xcp_connection_seed_key_failure_disconnects():
    from mf4_analyzer.acquisition_capture.xcp_auth import XcpAuthError
    from mf4_analyzer.acquisition_capture.vector_hw_probe import test_xcp_connection

    mock_master = MagicMock()
    mock_master.connect.return_value = MagicMock(resource=0x01)
    mock_bus = MagicMock()
    with patch.object(sys, "platform", "win32"), patch(
        "mf4_analyzer.acquisition_capture.vector_hw_probe._open_vector_bus",
        return_value=mock_bus,
    ), patch(
        "mf4_analyzer.acquisition_capture.vector_hw_probe._make_pyxcp_master",
        return_value=mock_master,
    ), patch(
        "mf4_analyzer.acquisition_capture.vector_hw_probe.unlock_resources_if_needed",
        side_effect=XcpAuthError("bad key"),
    ):
        result = test_xcp_connection(
            TransportConfig(seed_and_key_dll="seedkey.dll"), _ifdata()
        )

    assert result.ok is False
    assert "Seed&Key" in (result.error or "")
    mock_master.disconnect.assert_called_once()
    mock_bus.shutdown.assert_called_once()


def test_default_health_aggregator_can_bind_transport_probe():
    from mf4_analyzer.acquisition_capture.health import HealthAggregator, HwHealth

    transport = TransportConfig(app_name="CANalyzer", channel=2)

    def probe(candidate: TransportConfig):
        assert candidate == transport
        return HwHealth(
            ok=True,
            driver_version="22.0",
            channel_count=4,
            last_probe_ts=time.monotonic(),
        )

    agg = HealthAggregator(transport=transport, hw_probe=probe)
    assert agg.poll_once().hw.ok is True
