"""Output-directory selector display contract for Acquisition Cockpit."""

from __future__ import annotations

from PyQt5.QtWidgets import QLabel

from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
from mf4_analyzer.acquisition_ui.main_window._settings_mixin import (
    compact_path_display,
)


def test_compact_path_display_rules():
    assert compact_path_display("data/runs") == "data/runs"
    assert (
        compact_path_display("output/cockpit-ui-tour-recordings-2026-07-07/deep")
        == "output/…/deep"
    )
    assert (
        compact_path_display("/private/tmp/claude-501/very-long-session/scratch")
        == "…/very-long-session/scratch"
    )
    long_leaf = "/a/b/" + "x" * 40
    assert compact_path_display(long_leaf) == "…/" + "x" * 40


def test_set_output_dir_updates_selector_and_tooltip(qtbot):
    window = CockpitMainWindow()
    qtbot.addWidget(window)
    full = "/private/tmp/claude-501/very-long-session/recordings"
    window.set_output_dir(full)
    assert window._output_dir_label == full
    value = window._output_btn.findChild(QLabel, "cockpitSelectorValue")
    assert value.text() == "…/very-long-session/recordings"
    assert window._output_btn.toolTip() == full
    window.close()
