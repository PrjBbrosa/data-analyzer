"""SettingsDialog tests for Acquisition Cockpit."""

from __future__ import annotations

import json

import pytest
from PyQt5.QtWidgets import QDialog, QPushButton

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_ui.settings_dialog import SettingsDialog


@pytest.fixture(autouse=True)
def _isolated_threshold_state(monkeypatch, tmp_path):
    """Keep dialog tests away from the real per-user settings directory."""
    monkeypatch.setenv("HOME", str(tmp_path))
    thresholds.reset_defaults()
    yield
    thresholds.reset_defaults()


def _button(dialog: SettingsDialog, name: str) -> QPushButton:
    found = dialog.findChild(QPushButton, name)
    assert found is not None
    return found


def test_settings_dialog_save_persists_to_disk(qapp, tmp_path):
    path = tmp_path / "settings.json"
    dialog = SettingsDialog(settings_path=path)
    emitted: list[dict[str, float | int]] = []
    dialog.settings_saved.connect(emitted.append)

    dialog.editor_for_key("CAN_LOAD_GREEN_MAX_PCT").setValue(12.5)
    _button(dialog, "settingsSaveButton").click()
    qapp.processEvents()

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert set(payload["thresholds"]) == thresholds.VALID_THRESHOLD_KEYS
    assert payload["thresholds"]["CAN_LOAD_GREEN_MAX_PCT"] == 12.5
    assert thresholds.CAN_LOAD_GREEN_MAX_PCT == 12.5
    assert emitted[-1]["CAN_LOAD_GREEN_MAX_PCT"] == 12.5
    assert dialog.result() == QDialog.Accepted
    dialog.close()


def test_settings_dialog_cancel_does_not_write_or_apply(qapp, tmp_path):
    path = tmp_path / "settings.json"
    dialog = SettingsDialog(settings_path=path)

    dialog.editor_for_key("CAN_LOAD_GREEN_MAX_PCT").setValue(12.5)
    _button(dialog, "settingsCancelButton").click()
    qapp.processEvents()

    assert not path.exists()
    assert thresholds.CAN_LOAD_GREEN_MAX_PCT == 60.0
    assert dialog.result() == QDialog.Rejected
    dialog.close()


def test_settings_dialog_reset_to_defaults_writes_empty_overrides(qapp, tmp_path):
    path = tmp_path / "settings.json"
    thresholds.apply_overrides({"CAN_LOAD_GREEN_MAX_PCT": 12.5})
    dialog = SettingsDialog(settings_path=path)
    dialog.editor_for_key("CAN_LOAD_GREEN_MAX_PCT").setValue(9.0)
    emitted: list[bool] = []
    dialog.settings_reset.connect(lambda: emitted.append(True))

    _button(dialog, "settingsResetButton").click()
    qapp.processEvents()

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {"version": 1, "thresholds": {}}
    assert thresholds.CAN_LOAD_GREEN_MAX_PCT == 60.0
    assert dialog.editor_for_key("CAN_LOAD_GREEN_MAX_PCT").value() == 60.0
    assert emitted == [True]
    dialog.close()
