import sys
from pathlib import Path
from unittest.mock import patch

from PyQt5.QtWidgets import QFileDialog, QLabel


def test_transport_chip_shows_unconfigured_when_no_config(qapp):
    from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow

    window = CockpitMainWindow()
    try:
        chip = window.findChild(QLabel, "cockpitTransportStatusChip")
        assert chip is not None
        assert "传输未配置" in chip.text()
    finally:
        window.close()


def test_transport_chip_updates_when_transport_changes(qapp):
    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
    from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow

    window = CockpitMainWindow()
    try:
        window.set_transport(TransportConfig(app_name="CANalyzer", channel=1))
        chip = window.findChild(QLabel, "cockpitTransportStatusChip")
        assert chip is not None
        assert "CANalyzer" in chip.text()
        assert "Ch=1" in chip.text()
        assert "CAN 500k" in chip.text()
    finally:
        window.close()


def test_transport_chip_opens_settings_transport_tab(qapp):
    from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow

    window = CockpitMainWindow()
    try:
        window._open_settings_dialog(initial_tab="transport")
        dialog = window._settings_dialog
        assert dialog is not None
        assert "Transport" in dialog._tabs.tabText(dialog._tabs.currentIndex())
    finally:
        window.close()


def test_a2l_picker_caches_ifdata_for_transport_dialog(qapp, monkeypatch):
    from can_logger.p0 import a2l_probe as a2l_probe_module
    from can_logger.p0.a2l_probe import A2LSummary, MeasurementSummary
    from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow

    fixture = Path("tests/fixtures/ifdata_xcp/classic_can.a2l_snippet").resolve()
    monkeypatch.setattr(
        a2l_probe_module,
        "load_measurement_summary",
        lambda path, *, limit=None: A2LSummary(
            path=path,
            total_measurements=1,
            measurements=[
                MeasurementSummary(
                    name="EngineSpeed",
                    address=0x40000000,
                    datatype="UWORD",
                    unit="rpm",
                    conversion="",
                    available_events=("evt",),
                )
            ],
            event_capacity={"evt": 16},
            measurement_events={"EngineSpeed": ("evt",)},
            a2l_has_daq_events=True,
        ),
    )
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(fixture), ""),
    )
    window = CockpitMainWindow()
    try:
        window._on_pick_a2l()
        assert window._ifdata_xcp is not None
        with patch.object(sys, "platform", "win32"):
            window._open_settings_dialog(initial_tab="transport")
        dialog = window._settings_dialog
        assert dialog is not None
        assert dialog.transport_widget.test_btn.isEnabled() is True
    finally:
        window.close()
