"""Behavioral regressions from the method-first Batch review."""
import pytest

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QSignalSpy

from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet


def test_mounted_methods_cannot_change_while_editing_is_locked(qtbot):
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet.show()
    group = sheet._analysis_panel._method_group
    changed = QSignalSpy(group.methodChanged)
    params = sheet._analysis_panel.get_params()

    sheet.lock_editing()
    qtbot.mouseClick(group._buttons["frf"], Qt.LeftButton)
    qtbot.keyClick(group._buttons["fft"], Qt.Key_Right)
    assert sheet.method() == "fft"
    assert sheet._analysis_panel.get_params() == params
    assert list(changed) == []
    assert not group.isEnabled()

    sheet.unlock_editing()
    assert group.isEnabled()
    qtbot.mouseClick(group._buttons["frf"], Qt.LeftButton)
    assert sheet.method() == "frf"
    assert list(changed) == [["frf"]]


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
