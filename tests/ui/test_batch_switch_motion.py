"""Native Batch owner contracts for the three Light PillSwitch instances."""
from __future__ import annotations

from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtTest import QSignalSpy, QTest

from mf4_analyzer.batch import AnalysisPreset
from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
from mf4_analyzer.ui.widgets.pill_switch import PillSwitch
from mf4_analyzer.ui_kit.motion import POLICY_LIGHT, POLICY_OFF


def _make_sheet(qtbot) -> BatchSheet:
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    return sheet


def _click(switch: PillSwitch) -> None:
    QTest.mouseClick(switch, Qt.LeftButton, Qt.NoModifier, QPoint(22, 12))


def _driver_inactive(switch: PillSwitch) -> bool:
    driver = switch._value_driver
    return driver is None or not driver.is_active()


def test_generic_pill_switch_stays_off_while_three_batch_owners_are_light(
    qtbot, qapp
):
    generic = PillSwitch()
    qtbot.addWidget(generic)
    generic.show()
    qapp.processEvents()
    assert generic.motion_policy() == POLICY_OFF

    sheet = _make_sheet(qtbot)
    sheet.show()
    qapp.processEvents()
    filter_switch = sheet._input_panel._filter_panel._enable_switch
    stats_switch = sheet._analysis_panel._chart_statistics.enabled
    slice_switch = sheet._analysis_panel._slice._enable_switch
    assert filter_switch.motion_policy() == POLICY_LIGHT
    assert stats_switch.motion_policy() == POLICY_LIGHT
    assert slice_switch.motion_policy() == POLICY_LIGHT
    assert sheet._analysis_panel._slice._axis_choice.motion_policy() == POLICY_LIGHT
    assert (
        sheet._analysis_panel._chart_statistics._range_mode_choice.motion_policy()
        == POLICY_LIGHT
    )


def test_batch_filter_off_then_on_keeps_cutoff_and_user_click_animates(
    qtbot, qapp
):
    sheet = _make_sheet(qtbot)
    sheet.show()
    qapp.processEvents()
    panel = sheet._input_panel._filter_panel
    switch = panel._enable_switch
    panel.spin_cutoff.setValue(250.0)
    toggled = QSignalSpy(switch.toggled)

    _click(switch)
    assert switch.isChecked()
    assert list(toggled) == [[True]]
    assert switch._value_driver is not None and switch._value_driver.is_active()
    assert panel.spin_cutoff.value() == 250.0
    assert panel.filter_params()["spec"]["cutoff"] == 250.0

    _click(switch)
    assert not switch.isChecked()
    assert panel.filter_params()["enabled"] is False
    assert panel.spin_cutoff.value() == 250.0

    _click(switch)
    assert switch.isChecked()
    assert panel.filter_params()["spec"]["cutoff"] == 250.0
    assert list(toggled) == [[True], [False], [True]]


def test_chart_statistics_only_on_time_and_slice_only_on_spectrograms(
    qtbot, qapp
):
    sheet = _make_sheet(qtbot)
    sheet.show()
    qapp.processEvents()
    stats = sheet._analysis_panel._chart_statistics
    slice_panel = sheet._analysis_panel._slice

    assert sheet.method() == "time"
    assert stats.isVisibleTo(sheet)
    assert slice_panel.isVisibleTo(sheet) is False

    sheet.apply_method("fft")
    assert stats.isVisibleTo(sheet) is False
    assert slice_panel.isVisibleTo(sheet) is False

    sheet.apply_method("fft_time")
    assert stats.isVisibleTo(sheet) is False
    assert slice_panel.isVisibleTo(sheet)
    assert slice_panel._enable_switch.motion_policy() == POLICY_LIGHT

    sheet.apply_method("order_time")
    assert stats.isVisibleTo(sheet) is False
    assert slice_panel.isVisibleTo(sheet)

    sheet.apply_method("frf")
    assert stats.isVisibleTo(sheet) is False
    assert slice_panel.isVisibleTo(sheet) is False

    sheet.apply_method("time")
    assert stats.isVisibleTo(sheet)
    assert slice_panel.isVisibleTo(sheet) is False


def test_import_recipe_snaps_batch_enable_switches(qtbot, qapp):
    sheet = _make_sheet(qtbot)
    sheet.show()
    qapp.processEvents()
    filter_switch = sheet._input_panel._filter_panel._enable_switch
    stats_switch = sheet._analysis_panel._chart_statistics.enabled

    _click(filter_switch)
    assert filter_switch._value_driver is not None
    assert filter_switch._value_driver.is_active()

    sheet.apply_preset(AnalysisPreset.free_config(
        name="imported",
        method="time",
        params={
            "filter": {
                "enabled": True,
                "spec": {"kind": "low", "order": 4, "cutoff": 80.0},
                "show_original": True,
                "show_filtered": True,
            },
            "chart_statistics": {
                "enabled": True,
                "range_mode": "full",
                "metrics": ["max"],
            },
        },
    ))
    qapp.processEvents()

    assert filter_switch.isChecked()
    assert stats_switch.isChecked()
    assert _driver_inactive(filter_switch)
    assert _driver_inactive(stats_switch)
    assert sheet._input_panel._filter_panel.spin_cutoff.value() == 80.0

    sheet.apply_method("fft_time")
    slice_switch = sheet._analysis_panel._slice._enable_switch
    _click(slice_switch)
    assert slice_switch._value_driver is not None
    assert slice_switch._value_driver.is_active()
    sheet.apply_preset(AnalysisPreset.free_config(
        name="slice",
        method="fft_time",
        params={
            "slice": {"enabled": True, "axis": "time", "positions": [5.0, 15.0]},
        },
    ))
    qapp.processEvents()
    assert slice_switch.isChecked()
    assert _driver_inactive(slice_switch)


def test_lock_and_unlock_editing_do_not_emit_changed_or_schedule_compute(
    qtbot, qapp
):
    sheet = _make_sheet(qtbot)
    sheet.show()
    qapp.processEvents()
    sheet._recompute_timer.stop()

    filter_switch = sheet._input_panel._filter_panel._enable_switch
    stats_switch = sheet._analysis_panel._chart_statistics.enabled
    slice_switch = sheet._analysis_panel._slice._enable_switch
    input_changed = QSignalSpy(sheet._input_panel.changed)
    params_changed = QSignalSpy(sheet._analysis_panel.paramsChanged)
    filter_toggled = QSignalSpy(filter_switch.toggled)
    stats_toggled = QSignalSpy(stats_switch.toggled)
    slice_toggled = QSignalSpy(slice_switch.toggled)

    assert filter_switch.cursor().shape() == Qt.PointingHandCursor
    sheet.lock_editing()
    qapp.processEvents()
    assert not filter_switch.isEnabled()
    assert filter_switch.cursor().shape() == Qt.ArrowCursor
    assert not sheet._recompute_timer.isActive()
    assert list(input_changed) == []
    assert list(params_changed) == []
    assert list(filter_toggled) == []
    assert list(stats_toggled) == []
    assert list(slice_toggled) == []
    assert _driver_inactive(filter_switch)
    assert _driver_inactive(stats_switch)
    assert _driver_inactive(slice_switch)

    sheet.unlock_editing()
    qapp.processEvents()
    assert filter_switch.isEnabled()
    assert filter_switch.cursor().shape() == Qt.PointingHandCursor
    assert not sheet._recompute_timer.isActive()
    assert list(input_changed) == []
    assert list(params_changed) == []
    assert list(filter_toggled) == []
    assert list(stats_toggled) == []
    assert list(slice_toggled) == []
