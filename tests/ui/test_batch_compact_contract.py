"""Contract tests for the approved compact batch-analysis dialog."""
from __future__ import annotations

import json

from PyQt5.QtCore import Qt

from mf4_analyzer.ui_kit import load_stylesheet


def _show_at(qtbot, widget, width: int, height: int) -> None:
    qtbot.addWidget(widget)
    widget.resize(width, height)
    widget.show()
    qtbot.wait(20)


def test_heatmap_methods_drop_legacy_time_range_from_canonical_recipe():
    from mf4_analyzer.batch_recipe import normalize_batch_params

    for method in ("fft_time", "order_time"):
        params = normalize_batch_params(
            {"time_range": (1.0, 2.0), "window": "hanning"}, method,
        )
        assert "time_range" not in params


def test_batch_preset_name_and_patch_follow_single_analysis_slot(qtbot):
    from mf4_analyzer.ui.drawers.batch.analysis_panel import AnalysisPanel
    from mf4_analyzer.ui.analysis_preset_slots import notify_slot_changed
    from mf4_analyzer.ui.inspector_sections._helpers import _preset_settings

    _preset_settings().setValue(
        "fft/preset_override/1",
        json.dumps({
            "name": "测试",
            "params": {"window": "flattop", "t_win_s": 2.5},
        }),
    )
    panel = AnalysisPanel()
    qtbot.addWidget(panel)

    assert panel._preset_buttons["torque"].text() == "测试"
    panel._preset_buttons["torque"].click()
    assert panel.get_params()["window"] == "flattop"
    assert panel._preset_buttons["torque"].isChecked()

    panel._param_form._w_t_win_s.setValue(1.0)
    assert not any(button.isChecked() for button in panel._preset_buttons.values())

    panel._preset_buttons["torque"].click()
    _preset_settings().setValue(
        "fft/preset_override/1",
        json.dumps({"name": "测试更新", "params": {"window": "hamming"}}),
    )
    notify_slot_changed("fft", 1)
    assert panel._preset_buttons["torque"].text() == "测试更新"
    assert not any(button.isChecked() for button in panel._preset_buttons.values())
    assert panel.preset_state_text() == "已修改 · 未匹配预设"


def test_output_panel_uses_compact_fixed_export_contract(qtbot):
    from mf4_analyzer.ui.drawers.batch.output_panel import OutputPanel

    panel = OutputPanel()
    qtbot.addWidget(panel)
    outputs = panel.get_outputs()

    assert outputs.data_format == "xlsx"
    assert outputs.image_format == "png"
    assert (outputs.image_width, outputs.image_height) == (1920, 1080)
    assert outputs.image_line_width == 1.5
    assert outputs.conflict_policy == "auto_number"
    # 运行清单只服务于 runner 的断点续跑/失败重试，而这个 compact GUI 既不设
    # resume_policy 也不回传清单，写出来的 .tracelab/runs/*.json 无人消费，
    # 只会在用户的导出目录里堆垃圾 —— 固定契约改为不写。
    assert outputs.write_manifest is False
    assert outputs.resume_policy == "none"
    assert not panel._btn_output_settings.isVisible()


def test_time_method_hides_db_reference_and_source_interval(qtbot):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet.apply_method("time")

    assert not sheet._output_panel.db_reference_control.isVisibleTo(sheet)
    assert not sheet._analysis_panel.source_interval_widget().isVisibleTo(sheet)


def test_fft_hides_heatmap_z_range_but_keeps_db_reference(qtbot):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet.show()
    sheet.apply_method("fft")

    assert sheet._output_panel.db_reference_control.isVisibleTo(sheet)
    assert sheet._output_panel._z_axis_row.isHidden() is True
    assert sheet._output_panel._amplitude_unit_row.isVisibleTo(sheet)

    sheet.apply_method("fft_time")
    assert sheet._output_panel._z_axis_row.isVisibleTo(sheet)
    assert sheet._output_panel._amplitude_unit_row.isVisibleTo(sheet)

    sheet.apply_method("time")
    assert not sheet._output_panel._amplitude_unit_row.isVisibleTo(sheet)


def test_time_grouping_cards_explain_source_and_signal_semantics(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("time")

    cards = form._grouping_cards._buttons
    assert "每文件一张" in cards["source"].text()
    assert "每信号一张" in cards["channel"].text()
    cards["channel"].click()
    assert form.get_params()["render_group_by"] == "channel"


def test_compact_input_exposes_file_management_on_the_first_level(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel

    panel = InputPanel()
    _show_at(qtbot, panel, 360, 700)

    assert not hasattr(panel, "_file_manager_dialog")
    assert not hasattr(panel, "_btn_manage_files")
    assert panel._file_list.isVisibleTo(panel)
    assert panel._file_list._btn_loaded.isVisibleTo(panel)
    assert panel._file_list._btn_disk.isVisibleTo(panel)
    assert panel._file_list._empty_label.isVisibleTo(panel)
    assert panel._file_list._list.isHidden()


def test_runner_events_project_to_compact_footer_not_task_list(qtbot):
    from mf4_analyzer.batch import BatchProgressEvent
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._task_list.apply_dry_run(
        [("a.mf4", "signal_a", "fft"), ("b.mf4", "signal_a", "fft")],
        outputs_per_task=2,
    )
    sheet._on_runner_progress(BatchProgressEvent(
        kind="task_done", task_index=1, total=2,
    ))

    assert not sheet._task_list.isVisible()
    assert sheet._footer_progress.maximum() == 2
    assert sheet._footer_progress.value() == 1
    assert sheet._footer_task_summary.text() == "1/2 任务"


def test_output_edit_clears_an_applied_analysis_card(qtbot):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._analysis_panel._preset_buttons["torque"].click()
    assert sheet._analysis_panel._preset_buttons["torque"].isChecked()

    sheet._output_panel.spin_y_min.setValue(-2.0)

    assert not any(
        button.isChecked()
        for button in sheet._analysis_panel._preset_buttons.values()
    )
    assert sheet._analysis_panel.preset_state_text() == "已修改 · 未匹配预设"


def test_batch_shell_matches_html_fixed_rows_and_contiguous_columns(qapp, qtbot):
    from pathlib import Path

    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    old_stylesheet = qapp.styleSheet()
    try:
        load_stylesheet(qapp)
        sheet = BatchSheet(None, files={})
        _show_at(qtbot, sheet, 1440, 900)

        assert sheet._toolbar_host.height() == 36
        assert sheet.strip.height() == 40
        assert sheet._footer_host.height() == 50
        assert sheet._detail_lay.spacing() == 0

        panes = (sheet._input_scroll, sheet._analysis_scroll, sheet._output_scroll)
        assert all(pane.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff for pane in panes)
        available = sum(pane.width() for pane in panes)
        expected = (0.29, 0.39, 0.32)
        for pane, ratio in zip(panes, expected):
            assert abs(pane.width() - available * ratio) <= 6
    finally:
        sheet.close()
        qapp.setStyleSheet(old_stylesheet)


def test_pipeline_strip_uses_flat_html_stage_summaries(qtbot):
    from mf4_analyzer.ui.drawers.batch.pipeline_strip import PipelineStrip

    strip = PipelineStrip()
    qtbot.addWidget(strip)

    assert strip.minimumHeight() == 40
    assert strip.maximumHeight() == 40
    assert strip.layout().spacing() == 0
    assert [card.number_label.text() for card in strip.cards] == ["01", "02", "03"]
    assert [card.title_label.text() for card in strip.cards] == ["输入", "分析", "输出"]


def test_grouping_cards_expose_html_wave_semantics_and_geometry(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("time")
    form.set_grouping_counts(source_count=4, signal_count=3)

    cards = form._grouping_cards._buttons
    assert all(card.minimumHeight() >= 132 for card in cards.values())
    assert cards["none"].formula_text() == "4 × 3 → 12 张"
    assert cards["source"].formula_text() == "4 个数据源 → 4 张"
    assert cards["channel"].formula_text() == "3 个信号 → 3 张"
    assert cards["source"].wave_semantics() == "fixed-source-vary-signal"
    assert cards["channel"].wave_semantics() == "fixed-signal-vary-source"
    assert cards["source"].preview_row_labels() == ("S1", "S2", "S3")
    assert cards["channel"].preview_row_labels() == ("F1", "F2", "F3")
    assert form._w_render_group_by.isHidden() is True


def test_spectral_presets_use_html_cards_with_parameter_summaries(qapp, qtbot):
    from pathlib import Path

    from mf4_analyzer.ui.drawers.batch.analysis_panel import AnalysisPanel

    old = qapp.styleSheet()
    try:
        load_stylesheet(qapp)
        panel = AnalysisPanel()
        qtbot.addWidget(panel)
        panel.resize(500, 700)
        panel.show()
        panel.set_method("fft")
        qapp.processEvents()

        assert all(button.height() == 66 for button in panel._preset_buttons.values())
        assert all(button.summary_text() for button in panel._preset_buttons.values())
        panel.set_compact_mode(True)
        qapp.processEvents()
        assert all(button.height() == 40 for button in panel._preset_buttons.values())
        assert all(not button.summary_visible() for button in panel._preset_buttons.values())
    finally:
        qapp.setStyleSheet(old)


def test_batch_preset_card_qss_matches_normal_and_compact_outer_heights():
    from pathlib import Path

    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")

    normal = qss.split("QPushButton#BatchAnalysisPresetCard {")[1].split("}", 1)[0]
    compact = qss.split(
        'QPushButton#BatchAnalysisPresetCard[compact="true"] {'
    )[1].split("}", 1)[0]
    assert "min-height: 54px;" in normal
    assert "max-height: 54px;" in normal
    assert "border: 1px solid #dfe5ee;" in normal
    assert "border-color: #0b73e7;" in qss.split(
        "QPushButton#BatchAnalysisPresetCard:checked {", 1
    )[1].split("}", 1)[0]
    assert "min-height: 28px;" in compact
    assert "max-height: 28px;" in compact


def test_output_uses_bordered_axis_card_instead_of_flat_inspector_group(qtbot):
    from mf4_analyzer.ui.drawers.batch.output_panel import OutputPanel

    panel = OutputPanel()
    qtbot.addWidget(panel)

    assert panel._axis_group.property("batchAxisCard") is True
    assert panel._axis_group.title() == "坐标范围"
    assert "border: 1px solid #c8d4e3" in panel._axis_group.styleSheet()
    assert "border: none" not in panel._axis_group.styleSheet()


def test_file_manager_uses_compact_structured_inline_shell(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel

    panel = InputPanel()
    _show_at(qtbot, panel, 360, 700)
    panel._file_list.add_loaded_file("s1", "/tmp/drive_front.mf4", frozenset({"A"}))
    qtbot.wait(20)

    assert panel._file_manager_host.isVisibleTo(panel)
    assert panel._file_facts.text().startswith("1 个数据源")
    assert panel._file_list.property("structuredRows") is True
    assert panel._file_list._list.isVisibleTo(panel)
    assert panel._file_list._empty_label.isHidden()
    assert panel._file_list._list.height() <= 208

    item = panel._file_list._list.item(0)
    assert item.text() == ""
    assert item.data(Qt.AccessibleTextRole).startswith("drive_front.mf4")
    row = panel._file_list._list.itemWidget(item)
    remove = row.findChild(type(panel._file_list._btn_disk), "BatchFileRowRemove")
    assert remove is not None
    assert remove.width() >= 28
    assert remove.height() >= 28

    remove.click()
    qtbot.wait(20)
    assert panel._file_list._empty_label.isVisibleTo(panel)
    assert panel._file_list._list.isHidden()
    assert panel._file_facts.text().startswith("0 个数据源")


# ---------------------------------------------------------------------------
# Plan: docs/analyzer/plans/2026-08-03-batch-panel-height-and-action-emphasis-
# implementation.md — panel-height convergence + action-button emphasis.
# ---------------------------------------------------------------------------


def test_batch_sheet_initial_size_fits_available_screen(qapp, qtbot):
    from PyQt5.QtWidgets import QApplication

    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    screen = QApplication.instance().primaryScreen()
    avail = screen.availableGeometry()

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)

    assert sheet.height() <= avail.height() - 40
    assert sheet.width() <= avail.width() - 24


def test_batch_preview_dialog_fits_available_screen(qapp, qtbot):
    from PyQt5.QtWidgets import QApplication

    from mf4_analyzer.ui.drawers.batch.preview_dialog import BatchPreviewDialog

    screen = QApplication.instance().primaryScreen()
    avail = screen.availableGeometry()

    dialog = BatchPreviewDialog(None)
    qtbot.addWidget(dialog)

    assert dialog.height() <= avail.height() - 40
    assert dialog.width() <= avail.width() - 24


def test_batch_preview_dialog_has_no_context_help_button(qtbot):
    # C4: Windows adds a "?" title-bar button to a QDialog by default; it
    # never wired up to any behavior here, so it must be cleared.
    from mf4_analyzer.ui.drawers.batch.preview_dialog import BatchPreviewDialog

    dialog = BatchPreviewDialog(None)
    qtbot.addWidget(dialog)

    assert not (dialog.windowFlags() & Qt.WindowContextHelpButtonHint)


def test_batch_sheet_is_an_independent_non_modal_window(qtbot):
    from PyQt5.QtCore import Qt

    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)

    assert not sheet.isModal()
    assert sheet.windowModality() == Qt.NonModal
    assert sheet.windowFlags() & Qt.Window
    assert sheet.windowFlags() & Qt.WindowMinMaxButtonsHint
    assert not (sheet.windowFlags() & Qt.WindowContextHelpButtonHint)


def test_batch_sheet_is_not_transient_for_its_host(qapp, qtbot):
    from PyQt5.QtWidgets import QWidget

    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    host = QWidget()
    qtbot.addWidget(host)
    host.resize(800, 600)
    host.show()
    qtbot.waitExposed(host)
    sheet = BatchSheet(host, files={})
    qtbot.addWidget(sheet)
    sheet.present()
    qtbot.wait(20)
    handle = sheet.windowHandle()
    assert handle is not None
    assert handle.transientParent() is None


def test_batch_footer_actions_stay_inside_a_short_dialog(qapp, qtbot):
    from pathlib import Path

    from PyQt5.QtCore import QPoint

    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    old_stylesheet = qapp.styleSheet()
    try:
        load_stylesheet(qapp)
        sheet = BatchSheet(None, files={})
        qtbot.addWidget(sheet)
        sheet.resize(1080, 620)
        sheet.show()
        qtbot.wait(20)

        top_left = sheet._btn_run.mapTo(sheet, QPoint(0, 0))
        assert top_left.y() + sheet._btn_run.height() <= sheet.height()
        assert sheet._btn_run.isVisible()
    finally:
        sheet.close()
        qapp.setStyleSheet(old_stylesheet)


def test_batch_action_buttons_use_global_button_roles(qtbot):
    from mf4_analyzer.ui.drawers.batch.preview_dialog import BatchPreviewDialog
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    assert sheet._btn_run.property("role") == "primary"
    assert sheet._btn_preview.property("role") == "secondary"
    assert sheet._btn_cancel.property("role") is None
    assert sheet._btn_abort.property("role") == "danger"

    dialog = BatchPreviewDialog(None)
    qtbot.addWidget(dialog)
    assert dialog._btn_run_all.property("role") == "primary"
    assert dialog._btn_regenerate.property("role") == "secondary"
    assert dialog._btn_back.property("role") is None
    assert dialog._btn_cancel.property("role") == "danger"


def test_accent_compatibility_role_uses_the_shared_secondary_qss_tokens():
    from pathlib import Path

    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")

    assert 'role="accent"' in qss
    window = qss[qss.index('role="accent"'):][:400]
    assert "{{CONTROL_ACCENT}}" in window
    assert 'role="secondary"' in window


def test_batch_header_keeps_two_rows_but_tightened(qtbot):
    """The toolbar and the pipeline strip stay two separate rows — they
    carry different things (方案 I/O vs. pipeline state). Only their
    heights shrink: 50 + 62 + 54 = 166px of chrome becomes 36 + 40 + 50
    = 126px.
    """
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)

    assert sheet.strip.parent() is sheet
    assert sheet.strip.parent() is not sheet._toolbar_host
    assert sheet._toolbar_title.text() == "批处理分析"
    chrome = (
        sheet._toolbar_host.height()
        + sheet.strip.height()
        + sheet._footer_host.height()
    )
    assert chrome == 126


def test_batch_toolbar_row_fits_its_preset_buttons(qapp, qtbot):
    """36px is only safe because the toolbar-scoped QSS shortens the preset
    buttons; without it their 36px minimum would overflow the row and Qt
    would silently pin them to the top edge.
    """
    from pathlib import Path

    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    old_stylesheet = qapp.styleSheet()
    try:
        load_stylesheet(qapp)
        sheet = BatchSheet(None, files={})
        qtbot.addWidget(sheet)
        sheet.show()
        qtbot.wait(20)

        bar = sheet._toolbar_host.layout()
        assert bar.minimumSize().height() <= sheet._toolbar_host.height()
        for button in (
            sheet._btn_fill_from_current,
            sheet._btn_import_preset,
            sheet._btn_export_preset,
        ):
            assert button.y() >= 3
            assert (
                button.y() + button.height()
                <= sheet._toolbar_host.height() - 3
            )
    finally:
        sheet.close()
        qapp.setStyleSheet(old_stylesheet)
