"""Behavioral regressions from the method-first Batch review."""
import dataclasses

import pytest

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QSignalSpy

from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet


def _output_snapshot(sheet):
    return {
        "method": sheet.method(),
        "params": dict(sheet._analysis_panel.get_params()),
        "outputs": dataclasses.asdict(sheet._output_panel.get_outputs()),
        "signals": sheet.selected_signals(),
        "directory": sheet._output_panel.directory(),
    }


def test_mounted_methods_cannot_change_while_editing_is_locked(qtbot):
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet.show()
    group = sheet._analysis_panel._method_group
    changed = QSignalSpy(group.methodChanged)
    before = _output_snapshot(sheet)
    before_method = sheet.method()

    sheet.lock_editing()
    qtbot.mouseClick(group._buttons["frf"], Qt.LeftButton)
    qtbot.keyClick(group._buttons["fft"], Qt.Key_Right)
    from PyQt5.QtCore import QPoint, QPointF
    from PyQt5.QtGui import QWheelEvent
    from PyQt5.QtWidgets import QApplication

    pos = QPoint(max(group.width() // 2, 1), max(group.height() // 2, 1))
    QApplication.instance().sendEvent(group, QWheelEvent(
        QPointF(pos),
        QPointF(group.mapToGlobal(pos)),
        QPoint(0, 120),
        QPoint(0, 120),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.NoScrollPhase,
        False,
    ))
    assert sheet.method() == before_method
    assert _output_snapshot(sheet) == before
    assert list(changed) == []
    assert not group.isEnabled()

    sheet.unlock_editing()
    assert group.isEnabled()
    qtbot.mouseClick(group._buttons["frf"], Qt.LeftButton)
    assert sheet.method() == "frf"
    assert list(changed) == [["frf"]]


def test_new_sheet_defaults_to_time_not_fft(qtbot):
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    assert sheet.method() == "time"
    assert sheet._analysis_panel.current_method() == "time"


def test_sparse_source_group_card_matches_planned_pair_count(qtbot):
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    fl = sheet._input_panel._file_list
    fl.add_loaded_file("s1", "same.hdf", frozenset({"A", "B"}))
    fl.add_loaded_file("s2", "same.hdf", frozenset({"A", "C"}))
    sheet._input_panel.apply_target_policy("available_per_source")
    sheet.apply_signals(("B", "C"))
    sheet._recompute_pipeline_status()
    planned = sheet._build_dry_run_preview()
    snapshot = sheet.grouping_count_snapshot()
    card = sheet._analysis_panel._param_form._grouping_cards._buttons["none"]
    assert len(planned) == 2
    assert snapshot.status == "ready"
    assert snapshot.task_count == 2
    assert snapshot.groups_by_mode["none"] == 2
    assert card.formula_text().endswith("→ 2 张"), card.formula_text()
    assert "4" not in card.formula_text()


def test_thread_completion_restores_guidance_without_editing_configuration(qtbot):
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._analysis_panel._method_group._buttons["fft"].click()
    sheet._recompute_pipeline_status()
    before = sheet._method_hint.full_text()
    assert sheet._footer_locate.isVisibleTo(sheet)

    sheet._running = True
    sheet.lock_editing()
    sheet._refresh_method_guidance()
    assert not sheet._footer_locate.isVisibleTo(sheet)
    sheet._on_thread_finished()

    assert sheet._method_hint.full_text() == before
    assert sheet._footer_locate.isVisibleTo(sheet)


def test_pending_first_file_guidance_reports_parsing(qtbot):
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._analysis_panel._method_group._buttons["fft"].click()
    sheet._input_panel._file_list._set_row_state("pending.mf4", "probing")
    sheet._recompute_pipeline_status()
    assert "正在解析" in sheet._method_hint.full_text()
    assert "添加数据文件" not in sheet._method_hint.full_text()


def test_unavailable_first_source_reports_its_error_before_signal_selection(qtbot):
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._input_panel._file_list.add_disk_path("unsupported.unknown_format")
    sheet._recompute_pipeline_status()
    issue = next(issue for issue in sheet.preflight_issues() if issue.field == "source")
    assert issue.message in sheet._method_hint.full_text()
    assert sheet._locate_kind == "source"


def test_failed_first_probe_keeps_guidance_on_the_file_list(qtbot):
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._analysis_panel._method_group._buttons["fft"].click()
    sheet._input_panel._file_list._set_row_state("broken.mf4", "probe_failed")
    sheet._recompute_pipeline_status()
    assert "解析失败" in sheet._method_hint.full_text()
    assert sheet._locate_kind == "source"


def _configured_sheet(qtbot, method="fft"):
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._input_panel._file_list.add_loaded_file(
        "source", "signals.mf4", frozenset({"in", "out"}),
    )
    sheet._analysis_panel._method_group._buttons[method].click()
    sheet.apply_signals(("out",))
    return sheet


@pytest.mark.parametrize("problem", ["outputs", "fft_interval", "time_axis", "slice"])
def test_locate_focuses_the_control_that_owns_the_error(qtbot, problem):
    method = {"time_axis": "time", "slice": "fft_time"}.get(problem, "fft")
    sheet = _configured_sheet(qtbot, method)
    output = sheet._output_panel
    analysis = sheet._analysis_panel
    if problem == "outputs":
        output._chk_data.setChecked(False)
        output._chk_image.setChecked(False)
        target = output._chk_data
    elif problem == "fft_interval":
        analysis._source_interval_mode.setCurrentIndex(1)
        analysis._source_interval_edit.setText("2, 1")
        target = analysis._source_interval_edit
    elif problem == "time_axis":
        output.apply_axis_params({"x_auto": False, "x_min": 2, "x_max": 1})
        target = output.spin_x_min
    else:
        analysis._slice._enable_switch.setChecked(True)
        analysis._slice._positions_edit.setText("bad")
        target = analysis._slice._positions_edit
    sheet.show()
    sheet.activateWindow()
    qtbot.waitUntil(sheet.isActiveWindow)
    sheet._recompute_pipeline_status()
    assert sheet.preflight_issues()
    assert sheet._resolve_locate_widget(sheet._locate_kind) is target
    sheet._footer_locate.click()
    assert target.hasFocus()


@pytest.mark.parametrize("input_channel, outputs, field", [
    ("", (), "input_picker"),
    ("in", (), "output_picker"),
    ("missing", ("out",), "input_picker"),
    ("in", ("missing",), "output_picker"),
    ("in", ("in",), "output_picker"),
    ("in", ("out",), "output_picker"),
])
def test_frf_locate_targets_the_invalid_second_group(qtbot, input_channel, outputs, field):
    sheet = _configured_sheet(qtbot, "frf")
    editor = sheet._input_panel._frf_pair_editor
    editor.set_group_values(0, "in", ("out",))
    editor.add_group()
    editor.set_group_values(1, input_channel, outputs)
    sheet._refresh_method_guidance()
    assert "配对组 2" in sheet._method_hint.full_text()
    target = getattr(editor._groups[1], field)._trigger
    assert sheet._resolve_locate_widget(sheet._locate_kind) is target


def test_common_policy_group_card_is_zero_when_no_shared_targets(qtbot):
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    fl = sheet._input_panel._file_list
    fl.add_loaded_file("s1", "one.hdf", frozenset({"A", "B"}))
    fl.add_loaded_file("s2", "two.hdf", frozenset({"A", "C"}))
    sheet._input_panel.apply_target_policy("common")
    sheet.apply_signals(("B", "C"))
    sheet._recompute_pipeline_status()
    snapshot = sheet.grouping_count_snapshot()
    card = sheet._analysis_panel._param_form._grouping_cards._buttons["none"]
    assert sheet._build_dry_run_preview() == []
    assert snapshot.groups_by_mode == {"none": 0, "source": 0, "channel": 0}
    assert card.formula_text().endswith("→ 0 张")


def test_same_display_name_different_fids_are_not_merged(qtbot):
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    fl = sheet._input_panel._file_list
    fl.add_loaded_file("fid-a", "same-name.mf4", frozenset({"torque"}))
    fl.add_loaded_file("fid-b", "same-name.mf4", frozenset({"torque"}))
    sheet.apply_signals(("torque",))
    sheet._recompute_pipeline_status()
    snapshot = sheet.grouping_count_snapshot()
    assert snapshot.task_count == 2
    assert snapshot.groups_by_mode["none"] == 2
    assert snapshot.groups_by_mode["source"] == 2
    assert snapshot.groups_by_mode["channel"] == 1


def test_split_logical_sources_count_by_source_identity(qtbot):
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    fl = sheet._input_panel._file_list
    fl.add_loaded_file("file:rate-1k", "container.hdf", frozenset({"A", "B"}))
    fl.add_loaded_file("file:rate-2k", "container.hdf", frozenset({"A", "C"}))
    sheet._input_panel.apply_target_policy("available_per_source")
    sheet.apply_signals(("B", "C"))
    sheet._recompute_pipeline_status()
    snapshot = sheet.grouping_count_snapshot()
    assert snapshot.task_count == 2
    assert snapshot.groups_by_mode["none"] == 2
    assert snapshot.groups_by_mode["source"] == 2


def test_custom_x_unavailable_source_is_not_counted(qtbot):
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    fl = sheet._input_panel._file_list
    fl.add_loaded_file("s1", "a.hdf", frozenset({"B", "X"}))
    fl.add_loaded_file("s2", "b.hdf", frozenset({"C"}))
    sheet._input_panel.apply_target_policy("available_per_source")
    sheet.apply_signals(("B", "C"))
    sheet.apply_params({"x_source": "channel", "x_channel": "X"})
    sheet._recompute_pipeline_status()
    snapshot = sheet.grouping_count_snapshot()
    assert snapshot.task_count == 1
    assert snapshot.groups_by_mode["none"] == 1
    assert sheet._build_dry_run_preview() == [
        (fl._rows["s1"].label, "B", "time"),
    ]


def test_pending_and_failed_sources_do_not_show_cartesian_counts(qtbot):
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    cards = sheet._analysis_panel._param_form._grouping_cards._buttons
    sheet._input_panel._file_list._set_row_state("pending.mf4", "probing")
    sheet.apply_signals(("A", "B"))
    sheet._recompute_pipeline_status()
    assert sheet.grouping_count_snapshot().status == "pending"
    assert all(card.formula_text() == "待确定" for card in cards.values())

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    cards = sheet._analysis_panel._param_form._grouping_cards._buttons
    sheet._input_panel._file_list._set_row_state("broken.mf4", "probe_failed")
    sheet._recompute_pipeline_status()
    assert sheet.grouping_count_snapshot().status == "failed"
    assert all(card.formula_text() == "待确定" for card in cards.values())


def test_closed_image_export_distinguishes_schematic_from_zero_images(qtbot):
    from mf4_analyzer.batch import BatchOutput

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    fl = sheet._input_panel._file_list
    fl.add_loaded_file("s1", "same.hdf", frozenset({"A", "B"}))
    fl.add_loaded_file("s2", "same.hdf", frozenset({"A", "C"}))
    sheet._input_panel.apply_target_policy("available_per_source")
    sheet.apply_signals(("B", "C"))
    sheet.apply_outputs(BatchOutput(export_data=True, export_image=False))
    sheet._recompute_pipeline_status()
    snapshot = sheet.grouping_count_snapshot()
    card = sheet._analysis_panel._param_form._grouping_cards._buttons["none"]
    assert snapshot.images_enabled is False
    assert snapshot.task_count == 2
    assert snapshot.artifact_count == 2
    assert card.formula_text() == "分组示意 2 · 0 张实际图片"


def test_frf_valid_and_half_pairs_use_planner_not_signal_product(qtbot):
    from mf4_analyzer.batch_types import FrfPairRule

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    fl = sheet._input_panel._file_list
    fl.add_loaded_file("s1", "a.mf4", frozenset({"in", "out"}))
    fl.add_loaded_file("s2", "b.mf4", frozenset({"in", "out"}))
    sheet.apply_method("frf")
    sheet._input_panel.apply_frf_pair_rules((FrfPairRule("in", ("out",)),))
    sheet._recompute_pipeline_status()
    snapshot = sheet.grouping_count_snapshot()
    assert snapshot.status == "ready"
    assert snapshot.task_count == 2
    assert snapshot.groups_by_mode["none"] == 2
    assert snapshot.groups_by_mode["source"] == 2
    assert snapshot.groups_by_mode["channel"] == 1

    sheet._input_panel._frf_pair_editor.set_group_values(0, "in", ())
    sheet._recompute_pipeline_status()
    half = sheet.grouping_count_snapshot()
    assert half.status == "incomplete"
    assert half.task_count == 0


def test_card_recompute_does_not_stat_output_directory(qtbot, tmp_path, monkeypatch):
    from pathlib import Path

    from mf4_analyzer.batch import BatchOutput

    watched = tmp_path / "exports"
    watched.mkdir()
    exists_calls = []
    original = Path.exists

    def _exists(self):
        exists_calls.append(str(self))
        return original(self)

    monkeypatch.setattr(Path, "exists", _exists)
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._input_panel._file_list.add_loaded_file(
        "s1", "a.mf4", frozenset({"sig"}),
    )
    sheet.apply_signals(("sig",))
    sheet.apply_outputs(BatchOutput(export_data=True, export_image=True))
    sheet._output_panel.apply_directory(str(watched))
    exists_calls.clear()
    sheet._recompute_pipeline_status()
    assert sheet.grouping_count_snapshot().task_count == 1
    assert not any(str(watched) in path for path in exists_calls)
