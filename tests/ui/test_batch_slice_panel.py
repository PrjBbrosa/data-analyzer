"""Tests for the batch spectrogram slice-export panel (stage 6 of the
2026-08-03 batch heatmap slice design).

``SlicePanel`` only applies to the two spectrogram methods (``fft_time`` /
``order_time``); ``time``/``fft`` never see it. The panel follows the
"预处理" card skeleton: a ``PillSwitch`` main toggle that collapses the whole
settings area when off, plus a single-dimension slice editor (axis combo +
comma-separated positions).
"""
from __future__ import annotations

import pytest
from PyQt5.QtTest import QSignalSpy

from mf4_analyzer.ui.drawers.batch.analysis_panel import AnalysisPanel
from mf4_analyzer.ui.drawers.batch.slice_panel import SlicePanel
from mf4_analyzer.ui.widgets.pill_switch import PillSwitch


def _make_panel(qtbot) -> SlicePanel:
    panel = SlicePanel()
    qtbot.addWidget(panel)
    return panel


# ---------------------------------------------------------------------------
# Panel-level behaviour
# ---------------------------------------------------------------------------

def test_slice_panel_main_switch_is_a_pill_switch(qtbot):
    panel = _make_panel(qtbot)
    assert isinstance(panel._enable_switch, PillSwitch)


def test_slice_panel_settings_collapse_when_switch_is_off(qtbot):
    panel = _make_panel(qtbot)
    assert panel._enable_switch.isChecked() is False
    assert panel._settings.isHidden() is True

    panel._enable_switch.setChecked(True)
    assert panel._settings.isHidden() is False

    panel._enable_switch.setChecked(False)
    assert panel._settings.isHidden() is True


def test_slice_panel_summary_text_tracks_switch_and_position_count(qtbot):
    panel = _make_panel(qtbot)
    assert panel._summary_note.text() == "切片关闭 · 仅导出谱图"

    panel._enable_switch.setChecked(True)
    panel._positions_edit.setText("5, 15, 25")

    assert panel._summary_note.text() == "固定时间 · 3 处"


def test_slice_panel_summary_counts_unique_positions(qtbot):
    panel = _make_panel(qtbot)
    panel._enable_switch.setChecked(True)
    panel._positions_edit.setText("15, 5, 15")

    assert panel._summary_note.text() == "固定时间 · 2 处"


def test_slice_panel_summary_caps_position_count_at_export_limit(qtbot):
    panel = _make_panel(qtbot)
    panel._enable_switch.setChecked(True)
    panel._positions_edit.setText("1, 2, 3, 4, 5, 6")

    assert panel._summary_note.text() == "固定时间 · 4 处"


def test_slice_panel_axis_switch_updates_unit_label(qtbot):
    panel = _make_panel(qtbot)
    assert panel._unit_label.text() == "s"

    panel._axis_combo.setCurrentIndex(panel._axis_combo.findData("y"))
    assert panel._unit_label.text() == "Hz"

    panel._axis_combo.setCurrentIndex(panel._axis_combo.findData("time"))
    assert panel._unit_label.text() == "s"


def test_slice_panel_order_time_context_renames_second_axis_and_clears_unit(qtbot):
    panel = _make_panel(qtbot)
    panel.set_context(method="order_time")

    assert panel._axis_combo.itemText(1) == "固定阶次"

    panel._axis_combo.setCurrentIndex(panel._axis_combo.findData("y"))
    assert panel._unit_label.text() == ""


def test_slice_panel_context_switch_back_to_fft_time_restores_frequency_wording(qtbot):
    panel = _make_panel(qtbot)
    panel.set_context(method="order_time")
    panel.set_context(method="fft_time")

    assert panel._axis_combo.itemText(1) == "固定频率"

    panel._axis_combo.setCurrentIndex(panel._axis_combo.findData("y"))
    assert panel._unit_label.text() == "Hz"


# ---------------------------------------------------------------------------
# Positions parsing / get_params
# ---------------------------------------------------------------------------

def test_slice_panel_comma_separated_positions_parse_to_floats(qtbot):
    panel = _make_panel(qtbot)
    panel._enable_switch.setChecked(True)
    panel._positions_edit.setText("5, 15, 25")

    params = panel.get_params()

    assert params == {
        "slice": {"enabled": True, "axis": "time", "positions": [5.0, 15.0, 25.0]}
    }


def test_slice_panel_disabled_get_params_is_empty(qtbot):
    panel = _make_panel(qtbot)
    panel._positions_edit.setText("5, 15, 25")

    assert panel.get_params() == {}


def test_slice_panel_does_not_rewrite_the_users_raw_text(qtbot):
    """Sorting/dedup is a recipe-normalization concern (design D7), not a
    panel concern — the panel must leave whatever the user typed alone."""
    panel = _make_panel(qtbot)
    panel._enable_switch.setChecked(True)
    panel._positions_edit.setText("15, 5, 15")

    assert panel._positions_edit.text() == "15, 5, 15"
    assert panel.get_params()["slice"]["positions"] == [15.0, 5.0, 15.0]


# ---------------------------------------------------------------------------
# positions_error()
# ---------------------------------------------------------------------------

def test_slice_panel_positions_error_empty_when_disabled(qtbot):
    panel = _make_panel(qtbot)
    panel._positions_edit.setText("not a number")

    assert panel.positions_error() == ""


def test_slice_panel_positions_error_on_empty_positions(qtbot):
    panel = _make_panel(qtbot)
    panel._enable_switch.setChecked(True)
    panel._positions_edit.setText("")

    assert panel.positions_error() != ""


def test_slice_panel_positions_error_on_unparsable_text(qtbot):
    panel = _make_panel(qtbot)
    panel._enable_switch.setChecked(True)
    panel._positions_edit.setText("5, abc, 25")

    assert panel.positions_error() != ""


def test_slice_panel_positions_error_over_four_positions(qtbot):
    panel = _make_panel(qtbot)
    panel._enable_switch.setChecked(True)
    panel._positions_edit.setText("1, 2, 3, 4, 5")

    assert panel.positions_error() != ""


def test_slice_panel_positions_error_clear_for_valid_input(qtbot):
    panel = _make_panel(qtbot)
    panel._enable_switch.setChecked(True)
    panel._positions_edit.setText("5, 15, 25")

    assert panel.positions_error() == ""


def test_slice_panel_positions_error_rejects_negative_y_position(qtbot):
    panel = _make_panel(qtbot)
    panel._enable_switch.setChecked(True)
    panel._axis_combo.setCurrentIndex(panel._axis_combo.findData("y"))
    panel._positions_edit.setText("-5, 10")

    assert panel.positions_error() == "位置：固定频率或阶次不能为负数"


def test_sheet_maps_slice_recipe_issue_to_positions_messages():
    from mf4_analyzer.batch_validation import ValidationIssue
    from mf4_analyzer.ui.drawers.batch.sheet import (
        _analysis_issue_summary, _blocked_issue_reason,
    )

    issue = ValidationIssue(
        "slice", "invalid_slice_positions", "slice positions are invalid",
    )

    assert _analysis_issue_summary(issue, "fft_time") == (
        "时频 · 切片位置无效"
    )
    assert _blocked_issue_reason(issue) == "请检查切片位置"


# ---------------------------------------------------------------------------
# apply_params / get_params round trip
# ---------------------------------------------------------------------------

def test_slice_panel_apply_params_get_params_round_trip(qtbot):
    panel = _make_panel(qtbot)
    payload = {
        "slice": {"enabled": True, "axis": "y", "positions": [620.0, 1240.0]},
    }

    panel.apply_params(payload)

    assert panel.get_params() == payload


@pytest.mark.parametrize("payload", [
    {},
    {"slice": {"enabled": True, "axis": "y", "positions": [5.0, 15.0]}},
])
def test_slice_apply_params_emits_one_changed_and_forwarded_notification(
    qtbot, payload,
):
    """One programmatic slice apply is one observable parameter transaction."""
    panel = AnalysisPanel()
    qtbot.addWidget(panel)
    changed = QSignalSpy(panel._slice.changed)
    forwarded = QSignalSpy(panel.paramsChanged)

    panel._slice.apply_params(payload)

    assert len(changed) == 1
    assert len(forwarded) == 1


def test_slice_panel_apply_params_none_slice_resets_to_disabled(qtbot):
    panel = _make_panel(qtbot)
    panel.apply_params({
        "slice": {"enabled": True, "axis": "time", "positions": [5.0]},
    })

    panel.apply_params({})

    assert panel._enable_switch.isChecked() is False
    assert panel.get_params() == {}


def test_slice_panel_apply_params_without_slice_key_keeps_axis_and_positions(qtbot):
    """A slice-disabled preset must not erase the user's slice draft."""
    panel = _make_panel(qtbot)
    panel._axis_combo.setCurrentIndex(panel._axis_combo.findData("y"))
    panel._positions_edit.setText("5, 15, 25")

    panel.apply_params({"window": "hanning"})

    assert panel._enable_switch.isChecked() is False
    assert panel._axis_combo.currentData() == "y"
    assert panel._positions_edit.text() == "5, 15, 25"


# ---------------------------------------------------------------------------
# AnalysisPanel wiring
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method", ("fft_time", "order_time"))
def test_analysis_panel_shows_slice_panel_only_for_spectrogram_methods(
    qtbot, method,
):
    panel = AnalysisPanel()
    qtbot.addWidget(panel)

    panel.apply_method(method)
    assert panel._slice.isVisibleTo(panel) is True

    panel.apply_method("time")
    assert panel._slice.isVisibleTo(panel) is False

    panel.apply_method("fft")
    assert panel._slice.isVisibleTo(panel) is False


def test_analysis_panel_method_switch_updates_slice_axis_wording(qtbot):
    panel = AnalysisPanel()
    qtbot.addWidget(panel)

    panel.apply_method("fft_time")
    assert panel._slice._axis_combo.itemText(1) == "固定频率"

    panel.apply_method("order_time")
    assert panel._slice._axis_combo.itemText(1) == "固定阶次"


def test_analysis_panel_get_params_merges_slice_for_spectrogram_methods(qtbot):
    panel = AnalysisPanel()
    qtbot.addWidget(panel)
    panel.apply_method("fft_time")

    panel._slice._enable_switch.setChecked(True)
    panel._slice._positions_edit.setText("5, 15, 25")

    params = panel.get_params()

    assert params["slice"] == {
        "enabled": True, "axis": "time", "positions": [5.0, 15.0, 25.0],
    }


def test_analysis_panel_switching_to_time_drops_slice_from_params(qtbot):
    panel = AnalysisPanel()
    qtbot.addWidget(panel)
    panel.apply_method("fft_time")
    panel._slice._enable_switch.setChecked(True)
    panel._slice._positions_edit.setText("5, 15, 25")
    assert "slice" in panel.get_params()

    panel.apply_method("time")

    assert "slice" not in panel.get_params()


def test_analysis_panel_slice_positions_error_forwards_from_panel(qtbot):
    panel = AnalysisPanel()
    qtbot.addWidget(panel)
    panel.apply_method("fft_time")

    assert panel.slice_positions_error() == ""

    panel._slice._enable_switch.setChecked(True)
    panel._slice._positions_edit.setText("")
    assert panel.slice_positions_error() != ""

    panel._slice._positions_edit.setText("5, 15, 25")
    assert panel.slice_positions_error() == ""


def test_analysis_panel_slice_positions_error_ignored_outside_spectrogram_methods(
    qtbot,
):
    panel = AnalysisPanel()
    qtbot.addWidget(panel)
    panel.apply_method("fft_time")
    panel._slice._enable_switch.setChecked(True)
    panel._slice._positions_edit.setText("")
    assert panel.slice_positions_error() != ""

    panel.apply_method("time")

    assert panel.slice_positions_error() == ""


# ---------------------------------------------------------------------------
# BatchSheet integration: the slice error gates the Run button.
# ---------------------------------------------------------------------------

def test_sheet_blocks_run_button_when_slice_positions_are_invalid(qtbot, tmp_path):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._input_panel._file_list.add_loaded_file(
        "s1", "one.hdf", frozenset({"sig"}),
    )
    sheet.apply_signals(("sig",))
    sheet.apply_method("fft_time")
    sheet._output_panel.apply_directory(str(tmp_path))

    sheet._analysis_panel._slice._enable_switch.setChecked(True)
    sheet._analysis_panel._slice._positions_edit.setText("")
    sheet._recompute_pipeline_status()

    assert any(
        issue.field == "slice_positions" for issue in sheet.preflight_issues()
    )
    assert sheet.is_runnable() is False

    sheet._analysis_panel._slice._positions_edit.setText("5, 15")
    sheet._recompute_pipeline_status()

    assert not any(
        issue.field == "slice_positions" for issue in sheet.preflight_issues()
    )
