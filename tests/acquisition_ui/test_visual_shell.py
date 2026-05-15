"""Structural visual-shell tests for Acquisition Cockpit v3 parity."""

from __future__ import annotations

from PyQt5.QtWidgets import QLabel, QPushButton, QWidget

from mf4_analyzer.acquisition_ui.main_window import (
    DBC_DISABLED_TOOLTIP,
    CockpitMainWindow,
)
from mf4_analyzer.acquisition_ui.state import HealthyPredicateResult


def _mode_buttons(window: CockpitMainWindow) -> dict[str, QPushButton]:
    segment = window.findChild(QWidget, "cockpitModeSegment")
    assert segment is not None
    return {
        button.property("cockpitMode"): button
        for button in segment.findChildren(QPushButton)
    }


def _connect(window: CockpitMainWindow) -> None:
    window.state_machine.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True, xcp_connected=True, first_frame_received=True
        )
    )


def test_toolbar_selectors_and_mode_segment_exist(qapp):
    window = CockpitMainWindow()
    try:
        a2l = window.findChild(QWidget, "cockpitSelectorA2l")
        dbc = window.findChild(QWidget, "cockpitSelectorDbc")
        output = window.findChild(QWidget, "cockpitSelectorOutput")
        segment = window.findChild(QWidget, "cockpitModeSegment")
        toolbar = window.findChild(QWidget, "cockpitToolbarBand")
        rec = window.findChild(QWidget, "cockpitRecIndicator")

        assert toolbar is not None
        assert a2l is not None
        assert dbc is not None
        assert output is not None
        assert segment is not None
        assert toolbar.minimumHeight() == 50
        assert toolbar.maximumHeight() == 50
        assert a2l.minimumHeight() == 28
        assert a2l.maximumHeight() == 28
        assert output.minimumHeight() == 28
        assert output.maximumHeight() == 28
        assert segment.minimumHeight() == 32
        assert segment.maximumHeight() == 32
        assert rec.minimumHeight() == 32
        assert rec.maximumHeight() == 32
        assert window.main_button.minimumHeight() == 36
        assert window.main_button.maximumHeight() == 36
        assert a2l.isEnabled() is True
        assert output.isEnabled() is True
        assert dbc.isEnabled() is False
        assert dbc.toolTip() == DBC_DISABLED_TOOLTIP
        assert set(_mode_buttons(window)) == {"capture", "replay", "history"}
        for selector, key_text, value_text in (
            (a2l, "A2L", "未加载"),
            (dbc, "DBC", "可选"),
            (output, "输出", window._output_dir_label),
        ):
            key_label = selector.findChild(QLabel, "cockpitSelectorKey")
            value_label = selector.findChild(QLabel, "cockpitSelectorValue")
            caret = selector.findChild(QLabel, "cockpitSelectorCaret")
            assert key_label is not None
            assert value_label is not None
            assert caret is not None
            assert key_label.text() == key_text
            assert value_label.text() == value_text
            assert caret.text() == "▾"

        tab_bar = window.mode_tabs.tabBar()
        assert tab_bar.isHidden() or tab_bar.maximumHeight() == 0
    finally:
        window.close()


def test_mode_segment_drives_hidden_tab_widget(qapp):
    window = CockpitMainWindow()
    try:
        buttons = _mode_buttons(window)

        buttons["replay"].click()
        assert window.mode_tabs.currentIndex() == 1
        assert buttons["replay"].isChecked() is True

        buttons["history"].click()
        assert window.mode_tabs.currentIndex() == 2
        assert buttons["history"].isChecked() is True

        buttons["capture"].click()
        assert window.mode_tabs.currentIndex() == 0
        assert buttons["capture"].isChecked() is True
    finally:
        window.close()


def test_main_button_visual_action_properties_follow_state(qapp):
    window = CockpitMainWindow()
    try:
        rec = window.findChild(QWidget, "cockpitRecIndicator")
        assert window.main_button.property("cockpitAction") == "connect"
        assert rec.property("recState") == "off"

        _connect(window)
        assert window.main_button.property("cockpitAction") == "record"
        assert rec.property("recState") == "off"

        window.state_machine.request_start_recording()
        assert window.main_button.property("cockpitAction") == "stop"
        assert rec.property("recState") == "recording"
    finally:
        window.close()
