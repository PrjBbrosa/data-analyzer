import sys
import time
from unittest.mock import MagicMock, patch

import pytest


pytestmark = pytest.mark.usefixtures("qtbot")


def test_transport_tab_round_trips_values(qtbot):
    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
    from mf4_analyzer.acquisition_ui.settings_dialog import SettingsDialog

    initial = TransportConfig(
        app_name="CANalyzer",
        channel=1,
        can_fd=True,
        bitrate=1_000_000,
        data_bitrate=4_000_000,
    )
    dialog = SettingsDialog(transport=initial)
    qtbot.addWidget(dialog)

    dialog.transport_widget.channel_spin.setValue(2)
    out = dialog.current_transport()

    assert out.channel == 2
    assert out.app_name == "CANalyzer"
    assert out.can_fd is True
    assert out.bitrate == 1_000_000
    assert out.data_bitrate == 4_000_000


def test_sample_point_controls_are_driver_automatic_and_never_editable(qtbot):
    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
    from mf4_analyzer.acquisition_ui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(transport=TransportConfig(can_fd=True))
    qtbot.addWidget(dialog)

    assert dialog.transport_widget.sample_point_spin.isEnabled() is False
    assert dialog.transport_widget.fd_sample_point_spin.isEnabled() is False
    assert "driver" in dialog.transport_widget.sample_point_spin.toolTip().lower()

    dialog.transport_widget.can_fd_check.setChecked(False)
    dialog.transport_widget.can_fd_check.setChecked(True)
    assert dialog.transport_widget.fd_sample_point_spin.isEnabled() is False


def test_seed_key_label_ampersand_escaped(qtbot):
    from PyQt5.QtWidgets import QLabel

    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
    from mf4_analyzer.acquisition_ui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(transport=TransportConfig())
    qtbot.addWidget(dialog)

    labels = [label.text() for label in dialog.transport_widget.findChildren(QLabel)]
    assert "Seed&&Key DLL" in labels


def test_test_connection_button_disabled_on_non_windows(qtbot):
    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
    from mf4_analyzer.acquisition_ui.settings_dialog import SettingsDialog

    with patch.object(sys, "platform", "darwin"):
        dialog = SettingsDialog(transport=TransportConfig())
        qtbot.addWidget(dialog)

    assert dialog.transport_widget.test_btn.isEnabled() is False
    assert "Windows" in dialog.transport_widget.test_btn.toolTip()


def test_test_connection_button_disabled_without_ifdata_on_windows(qtbot):
    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
    from mf4_analyzer.acquisition_ui.settings_dialog import SettingsDialog

    with patch.object(sys, "platform", "win32"):
        dialog = SettingsDialog(transport=TransportConfig(), ifdata=None)
        qtbot.addWidget(dialog)

    assert dialog.transport_widget.test_btn.isEnabled() is False
    assert "A2L" in dialog.transport_widget.test_btn.toolTip()


def test_test_connection_result_uses_managed_nonblocking_box(qtbot, monkeypatch):
    from PyQt5.QtWidgets import QMessageBox

    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
    from mf4_analyzer.acquisition_ui.settings_dialog import (
        SettingsDialog,
        _TestConnectionResult,
    )

    def fail_static(*_args, **_kwargs):
        raise AssertionError("static QMessageBox helpers must not be used")

    opened: list[QMessageBox] = []
    monkeypatch.setattr(QMessageBox, "information", fail_static)
    monkeypatch.setattr(QMessageBox, "warning", fail_static)
    monkeypatch.setattr(QMessageBox, "open", lambda self: opened.append(self))

    dialog = SettingsDialog(transport=TransportConfig(), ifdata=MagicMock())
    qtbot.addWidget(dialog)
    dialog.show()

    dialog._show_test_connection_result(
        _TestConnectionResult(ok=False, level="red", message="no response")
    )

    assert opened == [dialog._test_connection_box]
    assert dialog._test_connection_box is not None
    assert dialog._test_connection_box.icon() == QMessageBox.Warning
    assert dialog._test_connection_box.text() == "no response"


def test_test_connection_runs_hw_then_xcp_probe_and_reports_resource(qtbot):
    from mf4_analyzer.acquisition_capture.health import HwHealth
    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
    from mf4_analyzer.acquisition_ui.settings_dialog import SettingsDialog

    with patch.object(sys, "platform", "win32"), patch(
        "mf4_analyzer.acquisition_ui.settings_dialog.vector_hw_probe",
        return_value=HwHealth(
            ok=True,
            driver_version="22.0",
            channel_count=4,
            last_probe_ts=time.monotonic(),
        ),
    ), patch(
        "mf4_analyzer.acquisition_ui.settings_dialog.test_xcp_connection",
        return_value=MagicMock(ok=True, resource_byte=0x05, latency_ms=12, error=None),
    ) as xcp_mock:
        dialog = SettingsDialog(transport=TransportConfig(), ifdata=MagicMock())
        qtbot.addWidget(dialog)
        result = dialog._run_test_connection_for_test()

    xcp_mock.assert_called_once()
    assert result.level == "green"
    assert "GET_STATUS" in result.message
    assert "12" in result.message


def test_test_connection_reports_xcp_no_response_in_red(qtbot):
    from mf4_analyzer.acquisition_capture.health import HwHealth
    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
    from mf4_analyzer.acquisition_ui.settings_dialog import SettingsDialog

    with patch.object(sys, "platform", "win32"), patch(
        "mf4_analyzer.acquisition_ui.settings_dialog.vector_hw_probe",
        return_value=HwHealth(
            ok=True,
            driver_version="22.0",
            channel_count=4,
            last_probe_ts=time.monotonic(),
        ),
    ), patch(
        "mf4_analyzer.acquisition_ui.settings_dialog.test_xcp_connection",
        return_value=MagicMock(
            ok=False,
            resource_byte=None,
            latency_ms=None,
            error="ECU 未在 1000 ms 内响应 (cmd_id=0x500)",
        ),
    ):
        dialog = SettingsDialog(transport=TransportConfig(), ifdata=MagicMock())
        qtbot.addWidget(dialog)
        result = dialog._run_test_connection_for_test()

    assert result.level == "red"
    assert "未在" in result.message and "响应" in result.message


def test_test_connection_hw_failure_skips_xcp_probe(qtbot):
    from mf4_analyzer.acquisition_capture.health import HwHealth
    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
    from mf4_analyzer.acquisition_ui.settings_dialog import SettingsDialog

    with patch.object(sys, "platform", "win32"), patch(
        "mf4_analyzer.acquisition_ui.settings_dialog.vector_hw_probe",
        return_value=HwHealth(
            ok=False,
            driver_version=None,
            channel_count=0,
            last_probe_ts=time.monotonic(),
            error="vxlapi DLL not loadable",
        ),
    ), patch(
        "mf4_analyzer.acquisition_ui.settings_dialog.test_xcp_connection",
    ) as xcp_mock:
        dialog = SettingsDialog(transport=TransportConfig(), ifdata=MagicMock())
        qtbot.addWidget(dialog)
        result = dialog._run_test_connection_for_test()

    assert result.level == "red"
    xcp_mock.assert_not_called()
