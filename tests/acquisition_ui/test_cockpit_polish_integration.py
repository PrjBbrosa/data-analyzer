"""Cockpit polish-wave integration wiring tests."""

from __future__ import annotations

import json
from pathlib import Path

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_ui.history_tab import HistoryTab
from mf4_analyzer.acquisition_ui.main_window import (
    HISTORY_TAB_TITLE,
    REPLAY_TAB_TITLE,
    CockpitMainWindow,
)
from mf4_analyzer.acquisition_ui.replay_tab import ReplayTab
from mf4_analyzer.acquisition_ui.settings_dialog import SettingsDialog


def test_cockpit_hosts_replay_and_history_tabs(qapp):
    window = CockpitMainWindow()
    try:
        tabs = window.mode_tabs
        titles = [tabs.tabText(i) for i in range(tabs.count())]

        assert titles == ["采集", REPLAY_TAB_TITLE, HISTORY_TAB_TITLE]
        assert tabs.isTabEnabled(titles.index(REPLAY_TAB_TITLE)) is True
        assert isinstance(window.replay_tab, ReplayTab)
        assert isinstance(window.history_tab, HistoryTab)
        assert tabs.widget(titles.index(REPLAY_TAB_TITLE)) is window.replay_tab
        assert tabs.widget(titles.index(HISTORY_TAB_TITLE)) is window.history_tab
    finally:
        window.close()


def test_history_tab_open_uses_cockpit_analyzer_handoff(qapp, tmp_path: Path):
    files_dir = tmp_path / "files"
    files_dir.mkdir()
    mf4_path = files_dir / "rec_a.mf4"
    mf4_path.write_bytes(b"mf4")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "id": "rec_a",
                        "path": "files/rec_a.mf4",
                        "sets": ["dev"],
                        "path_kind": "local",
                        "required": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    opened: list[str] = []
    window = CockpitMainWindow()
    try:
        window.set_analyzer_handoff(opened.append)
        window.history_tab.set_manifest_path(manifest_path)
        assert window.history_tab.wait_for_resolutions(timeout_ms=1000) is True

        model = window.history_tab.table_view.model()
        index = model.index(0, 0)
        window.history_tab.table_view.doubleClicked.emit(index)
        qapp.processEvents()

        assert opened == [str(mf4_path.resolve())]
    finally:
        window.close()


def test_settings_action_opens_dialog_and_applies_thresholds(
    qapp, monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("HOME", str(tmp_path))
    thresholds.reset_defaults()
    window = CockpitMainWindow()
    try:
        window.settings_action.trigger()
        qapp.processEvents()
        dialog = window.findChild(SettingsDialog, "acquisitionSettingsDialog")
        assert dialog is not None

        dialog.editor_for_key("CAN_LOAD_GREEN_MAX_PCT").setValue(12.5)
        dialog.save()
        qapp.processEvents()

        assert thresholds.CAN_LOAD_GREEN_MAX_PCT == 12.5
        assert (
            tmp_path / ".acquisition-cockpit" / "settings.json"
        ).exists()
    finally:
        window.close()
        thresholds.reset_defaults()


def test_cockpit_startup_loads_user_threshold_overrides(
    qapp, monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("HOME", str(tmp_path))
    thresholds.reset_defaults()
    thresholds.save_user_settings(
        {
            "version": thresholds.SETTINGS_VERSION,
            "thresholds": {"CAN_LOAD_GREEN_MAX_PCT": 12.5},
        }
    )
    thresholds.reset_defaults()

    window = CockpitMainWindow()
    try:
        assert thresholds.CAN_LOAD_GREEN_MAX_PCT == 12.5
    finally:
        window.close()
        thresholds.reset_defaults()


def test_cockpit_startup_survives_unreadable_settings_file(
    qapp, monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("HOME", str(tmp_path))
    settings_dir = tmp_path / ".acquisition-cockpit"
    settings_dir.mkdir()
    # Replace the settings file with a directory so Path.read_text raises
    # IsADirectoryError (subclass of OSError) on macOS / Linux.
    (settings_dir / "settings.json").mkdir()

    thresholds.reset_defaults()
    window = CockpitMainWindow()
    try:
        assert thresholds.CAN_LOAD_GREEN_MAX_PCT == 60.0
    finally:
        window.close()
        thresholds.reset_defaults()
