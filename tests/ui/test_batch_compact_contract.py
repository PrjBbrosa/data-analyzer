"""Contract tests for the approved compact batch-analysis dialog."""
from __future__ import annotations

import json

from PyQt5.QtCore import Qt


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
    assert outputs.write_manifest is True
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


def test_compact_input_uses_a_fixed_summary_and_modal_source_manager(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel

    panel = InputPanel()
    qtbot.addWidget(panel)

    assert panel._file_summary.parentWidget().height() == 54
    assert not panel._file_manager_dialog.isVisible()
    panel.open_file_manager()
    assert panel._file_manager_dialog.isVisible()


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
        qapp.setStyleSheet(
            Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
        )
        sheet = BatchSheet(None, files={})
        _show_at(qtbot, sheet, 1440, 900)

        assert sheet._toolbar_host.height() == 50
        assert sheet.strip.height() == 62
        assert sheet._footer_host.height() == 54
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

    assert strip.minimumHeight() == 62
    assert strip.maximumHeight() == 62
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
    assert form._w_render_group_by.isHidden() is True


def test_spectral_presets_use_html_cards_with_parameter_summaries(qtbot):
    from mf4_analyzer.ui.drawers.batch.analysis_panel import AnalysisPanel

    panel = AnalysisPanel()
    qtbot.addWidget(panel)
    panel.set_method("fft")

    assert all(button.minimumHeight() >= 61 for button in panel._preset_buttons.values())
    assert all(button.summary_text() for button in panel._preset_buttons.values())
    panel.set_compact_mode(True)
    assert all(button.minimumHeight() == 38 for button in panel._preset_buttons.values())
    assert all(not button.summary_visible() for button in panel._preset_buttons.values())


def test_output_uses_bordered_axis_card_instead_of_flat_inspector_group(qtbot):
    from mf4_analyzer.ui.drawers.batch.output_panel import OutputPanel

    panel = OutputPanel()
    qtbot.addWidget(panel)

    assert panel._axis_group.property("batchAxisCard") is True
    assert panel._axis_group.title() == "坐标范围"
    assert "border: 1px solid #c8d4e3" in panel._axis_group.styleSheet()
    assert "border: none" not in panel._axis_group.styleSheet()


def test_file_manager_uses_compact_structured_modal_shell(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel

    panel = InputPanel()
    qtbot.addWidget(panel)
    panel._file_list.add_loaded_file("s1", "/tmp/drive_front.mf4", frozenset({"A"}))
    panel.open_file_manager()
    qtbot.wait(20)

    assert panel._file_manager_dialog.width() <= 560
    assert panel._file_manager_header.isVisibleTo(panel._file_manager_dialog)
    assert panel._file_manager_facts.text().startswith("1 个数据源")
    assert panel._file_list.property("structuredRows") is True
