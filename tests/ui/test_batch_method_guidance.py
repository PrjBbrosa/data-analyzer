"""Method-first guidance is a window-local suggestion, not a new run gate."""
from __future__ import annotations

import dataclasses
import json

from PyQt5.QtCore import QTimer
from PyQt5.QtTest import QSignalSpy
from PyQt5.QtWidgets import QFileDialog

from mf4_analyzer.batch import AnalysisPreset, BatchOutput
from mf4_analyzer.ui.drawers.batch.method_buttons import MethodButtonGroup
from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet, _METHOD_START_HINT


def _sheet(qtbot, **kwargs):
    sheet = BatchSheet(None, files=kwargs.pop("files", {}), **kwargs)
    qtbot.addWidget(sheet)
    return sheet


def test_new_window_shows_start_hint_with_default_time(qtbot):
    sheet = _sheet(qtbot)
    assert sheet._analysis_panel.current_method() == "time"
    assert sheet._guidance_engaged is False
    assert sheet._method_step_label.text() == "先选分析方法"
    assert sheet._method_hint.full_text() == _METHOD_START_HINT
    assert sheet._method_row.property("guidance") == "start"
    assert sheet._footer_locate.isVisibleTo(sheet)
    assert sheet._footer_locate.text() == "去添加"


def test_start_caption_fits_without_overlapping_tabs(qapp, qtbot):
    from PyQt5.QtCore import QPoint

    from mf4_analyzer.ui_kit import load_stylesheet

    old = qapp.styleSheet()
    try:
        load_stylesheet(qapp)
        sheet = _sheet(qtbot)
        sheet.resize(1080, 760)
        sheet.show()
        qtbot.wait(30)

        label = sheet._method_step_label
        ink = max(
            label.fontMetrics().horizontalAdvance(label.text()),
            label.fontMetrics().boundingRect(label.text()).width(),
        )
        assert label.width() >= ink
        row = sheet._method_row
        caption_right = sheet._method_caption.mapTo(
            row, sheet._method_caption.rect().topRight(),
        ).x()
        first_tab = sheet._analysis_panel._method_group._buttons["time"]
        tab_left = first_tab.mapTo(row, QPoint(0, 0)).x()
        assert caption_right <= tab_left
        assert sheet._method_caption.width() >= 128
        engaged_ink = max(
            label.fontMetrics().horizontalAdvance("分析方法"),
            label.fontMetrics().boundingRect("分析方法").width(),
        )
        assert label.minimumWidth() >= engaged_ink
    finally:
        qapp.setStyleSheet(old)


def test_clicking_current_method_engages_without_method_change(qtbot):
    sheet = _sheet(qtbot)
    params = sheet._analysis_panel.get_params()
    spy = QSignalSpy(sheet._analysis_panel.methodChanged)

    sheet._analysis_panel._method_group._buttons["time"].click()

    assert list(spy) == []
    assert sheet._guidance_engaged is True
    assert sheet._analysis_panel.get_params() == params
    assert sheet._analysis_panel.has_applied_preset() is False
    assert "已选时域" in sheet._method_hint.full_text()
    assert sheet._method_step_label.text() == "分析方法"
    assert sheet._method_row.property("guidance") == "engaged"


def test_switching_method_updates_hint_after_the_existing_transaction(qtbot):
    sheet = _sheet(qtbot)
    spy = QSignalSpy(sheet._analysis_panel.methodChanged)
    sheet._analysis_panel._method_group._buttons["order_time"].click()
    assert [tuple(item) for item in spy] == [("order_time",)]
    qtbot.waitUntil(
        lambda: "已选阶次" in sheet._method_hint.full_text(),
        timeout=1000,
    )
    assert sheet._input_panel._target_title.text() == "分析信号与转速"
    assert "下一步：添加数据文件" in sheet._method_hint.full_text()


def test_adding_files_adopts_the_default_method_without_an_extra_click(qtbot):
    sheet = _sheet(qtbot)
    sheet._input_panel._file_list.add_loaded_file(
        1, "a.mf4", frozenset({"sig_a", "rpm"}),
    )
    assert sheet._guidance_engaged is True
    hint = sheet._method_hint.full_text()
    assert "已选时域" in hint
    assert "下一步：添加数据文件" not in hint
    assert "尚未选择分析信号" in hint
    assert sheet._analysis_panel.current_method() == "time"


def test_probe_callback_does_not_confirm_the_starting_method(qtbot):
    sheet = _sheet(qtbot)
    sheet._input_panel._file_list._set_row_state("pending.mf4", "path_pending")
    qtbot.wait(20)
    assert sheet._guidance_engaged is False
    assert sheet._method_hint.full_text() == _METHOD_START_HINT


def test_cancelled_import_does_not_engage_guidance(qtbot, monkeypatch):
    sheet = _sheet(qtbot)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""),
    )
    sheet._on_import_preset()
    assert sheet._guidance_engaged is False
    assert sheet._method_hint.full_text() == _METHOD_START_HINT


def test_successful_preset_apply_engages_guidance(qtbot):
    sheet = _sheet(qtbot)
    preset = AnalysisPreset(
        name="imported",
        method="fft",
        source="free_config",
        params={"window": "hanning"},
        outputs=BatchOutput(),
    )
    sheet.apply_preset(preset)
    assert sheet._guidance_engaged is True
    assert "已选频谱" in sheet._method_hint.full_text()


def test_exported_recipe_json_does_not_contain_guidance_state(qtbot, tmp_path):
    sheet = _sheet(qtbot)
    sheet._analysis_panel._method_group._buttons["fft"].click()
    preset = sheet._build_preset_for_export()
    payload = dataclasses.asdict(preset)
    dumped = json.dumps(payload)
    assert "guidance" not in dumped
    assert "_guidance_engaged" not in payload
    path = tmp_path / "recipe.json"
    path.write_text(dumped, encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert "guidance" not in loaded


def test_new_sheet_resets_guidance(qtbot):
    first = _sheet(qtbot)
    first._analysis_panel._method_group._buttons["fft"].click()
    assert first._guidance_engaged is True
    second = _sheet(qtbot)
    assert second._guidance_engaged is False
    assert second._method_hint.full_text() == _METHOD_START_HINT


def test_locate_scrolls_without_changing_configuration(qtbot):
    sheet = _sheet(qtbot)
    sheet.resize(1080, 760)
    sheet.show()
    qtbot.wait(20)
    params = sheet._analysis_panel.get_params()
    files_before = sheet._input_panel._file_list.loaded_source_ids()
    sheet._footer_locate.click()
    assert sheet._analysis_panel.get_params() == params
    assert sheet._input_panel._file_list.loaded_source_ids() == files_before
    assert sheet._guidance_engaged is False


def test_guidance_refresh_does_not_call_preview_or_probe(qtbot, monkeypatch):
    sheet = _sheet(qtbot)
    calls = {"preview": 0, "probe": 0}

    def _preview(*_a, **_k):
        calls["preview"] += 1
        raise AssertionError("guidance must not generate a preview")

    monkeypatch.setattr(
        sheet._input_panel._file_list,
        "_start_probe",
        lambda *_a, **_k: calls.__setitem__("probe", calls["probe"] + 1),
    )
    monkeypatch.setattr(type(sheet), "_make_runner", lambda self: type(
        "Runner", (), {"preview_outputs": staticmethod(_preview)},
    )())
    sheet._analysis_panel._method_group._buttons["fft"].click()
    assert calls == {"preview": 0, "probe": 0}


def test_repeat_mount_does_not_duplicate_method_changed(qtbot):
    sheet = _sheet(qtbot)
    panel = sheet._analysis_panel
    spy = QSignalSpy(panel.methodChanged)
    panel.mount_method_selector(sheet._method_tabs_layout)
    panel.mount_method_selector(sheet._method_tabs_layout)
    panel.set_method("time")
    assert [tuple(item) for item in spy] == [("time",)]
    assert len(sheet.findChildren(MethodButtonGroup)) == 1


def test_complete_configuration_hint_allows_preview_without_extra_click(qtbot):
    sheet = _sheet(qtbot)
    sheet._input_panel._file_list.add_loaded_file(
        1, "a.mf4", frozenset({"sig_a"}),
    )
    sheet._input_panel._signal_picker.set_selected(("sig_a",))
    qtbot.waitUntil(
        lambda: sheet._guidance_engaged and "尚未选择" not in sheet._method_hint.full_text(),
        timeout=1000,
    )
    hint = sheet._method_hint.full_text()
    assert "已选时域" in hint
    assert "下一步：添加数据文件" not in hint


def test_same_method_click_does_not_change_run_eligibility(qtbot):
    sheet = _sheet(qtbot)
    before = sheet.is_runnable()
    sheet._analysis_panel._method_group._buttons["time"].click()
    assert sheet._guidance_engaged is True
    assert sheet.is_runnable() is before is False


def test_handoff_preset_keeps_explicit_method_over_time_default(qtbot):
    preset = AnalysisPreset(
        name="current",
        method="fft",
        source="free_config",
        params={"window": "hanning"},
        outputs=BatchOutput(),
    )
    sheet = _sheet(qtbot, current_preset=preset)
    assert sheet.method() == "time"
    sheet._on_fill_from_current()
    assert sheet.method() == "fft"
    assert sheet._guidance_engaged is True


def test_probe_completion_does_not_count_as_user_configuration(qtbot):
    sheet = _sheet(qtbot)
    fl = sheet._input_panel._file_list
    fl._set_row_state("pending.mf4", "path_pending")
    assert sheet._guidance_engaged is False

    def _finish():
        fl._on_probe_finished("pending.mf4", frozenset({"A", "B"}))

    QTimer.singleShot(0, _finish)
    qtbot.waitUntil(
        lambda: any(
            row.state == "loaded" for row in fl._rows.values()
        ),
        timeout=1000,
    )
    assert sheet._guidance_engaged is False
    assert sheet._method_hint.full_text() == _METHOD_START_HINT


def test_preference_restore_does_not_count_as_user_configuration(qtbot, tmp_path):
    from PyQt5.QtCore import QSettings

    from mf4_analyzer.ui.batch_settings import BatchPanelPrefs, BatchPanelPrefsStore

    store = BatchPanelPrefsStore(
        settings=QSettings(str(tmp_path / "batch-prefs.ini"), QSettings.IniFormat),
    )
    store.save(BatchPanelPrefs(
        directory=str(tmp_path / "remembered-exports"),
        outputs={"export_image": True},
    ))
    sheet = BatchSheet(None, files={}, prefs_store=store)
    qtbot.addWidget(sheet)
    qtbot.wait(20)
    assert sheet._guidance_engaged is False
    assert sheet._method_hint.full_text() == _METHOD_START_HINT
    assert sheet.method() == "time"


def test_programmatic_apply_does_not_count_as_user_configuration(qtbot):
    sheet = _sheet(qtbot)
    sheet.apply_params({"render_group_by": "source"})
    sheet.apply_signals(("sig_a",))
    assert sheet._guidance_engaged is False
    assert sheet._method_hint.full_text() == _METHOD_START_HINT


def test_failed_import_does_not_count_as_user_configuration(qtbot, monkeypatch, tmp_path):
    sheet = _sheet(qtbot)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        lambda *a, **k: (str(tmp_path / "missing.json"), ""),
    )
    sheet._on_import_preset()
    assert sheet._guidance_engaged is False
    assert sheet._method_hint.full_text() == _METHOD_START_HINT
